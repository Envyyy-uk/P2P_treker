"""Historical Backtesting Engine (Фаза 3.1).

Прогонює історичні `quotes_1s` через ТУ САМУ логіку `SpreadEngine` +
`SpreadEventTracker`, що працює live (Фази 1/2) — жодного дублювання формул
чи детектора подій окремим кодом (план, Фаза 3.1, п.2). Параметри
(поріг спреду, мінімальна тривалість, комісії, мінімальний обсяг) можна
змінювати заднім числом для експерименту — це вплине лише на результат
конкретного прогону backtest, а не на вже записані `spread_events`.

Результат — ОПТИМІСТИЧНА оцінка (план, п.5): без VWAP/slippage, без
затримки виконання і без конкуренції з іншими ботами — усе це з'явиться
у Фазі 4 (Paper Trading). Не оптимізувати параметри "під" історичні дані
(overfitting, план п.6) — прогонити ще раз на окремому, не використаному
в підборі параметрів періоді (out-of-sample), перш ніж довіряти результату.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import groupby
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.symbols import SYMBOL_MAP
from app.database.models import Quote1s
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache
from app.spread.engine import SpreadEngine
from app.spread.events import SpreadEventTracker

DISCLAIMER = (
    "Оптимістична оцінка: без VWAP/slippage, без затримки виконання ордерів "
    "і без конкуренції з іншими ботами (ці фактори з'являються у Фазі 4 — "
    "Paper Trading). Реальний результат майже завжди гірший. Не оптимізувати "
    "параметри під цей самий період (overfitting) — перевіряйте на окремому, "
    "не використаному в підборі параметрів періоді (out-of-sample)."
)


@dataclass(frozen=True)
class BacktestParams:
    symbols: list[str]
    from_ms: int
    to_ms: int
    market_type: MarketType = MarketType.SPOT
    # None -> береться з базового конфігу (settings.trading.*).
    spread_threshold: Decimal | None = None
    min_duration_ms: int = 0
    min_executable_quantity: Decimal | None = None
    min_executable_notional: Decimal | None = None
    fee_overrides: dict[Exchange, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.to_ms <= self.from_ms:
            raise ValueError("'to_ms' must be greater than 'from_ms'")
        unknown = set(self.symbols) - set(SYMBOL_MAP)
        if unknown:
            raise ValueError(f"Symbols without exchange mapping: {sorted(unknown)}")
        if not self.symbols:
            raise ValueError("At least one symbol is required")
        if self.market_type is not MarketType.SPOT:
            raise ValueError("Backtesting supports only spot market (MVP scope)")


@dataclass
class BacktestResult:
    params: BacktestParams
    ticks_processed: int
    truncated: bool
    total_events: int
    events: list[dict[str, Any]]
    total_simulated_pnl: Decimal
    average_pnl_per_event: Decimal | None
    disclaimer: str = DISCLAIMER


def _row_to_quote(row: Any, sequence: int) -> NormalizedQuote:
    return NormalizedQuote(
        exchange=Exchange(row["exchange"]),
        market_type=MarketType(row["market_type"]),
        symbol=row["symbol"],
        bid_price=row["bid_price"],
        bid_quantity=row["bid_quantity"],
        ask_price=row["ask_price"],
        ask_quantity=row["ask_quantity"],
        exchange_timestamp=row["exchange_timestamp"],
        received_timestamp=row["received_timestamp"],
        sequence=sequence,
    )


class BacktestEngine:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], base_settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._base_settings = base_settings

    async def run(self, params: BacktestParams) -> BacktestResult:
        max_ticks = self._base_settings.backtest.max_ticks_per_run
        rows = await self._load_ticks(params, max_ticks)
        truncated = len(rows) > max_ticks
        rows = rows[:max_ticks]

        settings = self._base_settings.model_copy(deep=True)
        settings.trading.symbols = params.symbols
        if params.min_executable_quantity is not None:
            settings.trading.min_executable_quantity = params.min_executable_quantity
        if params.min_executable_notional is not None:
            settings.trading.min_executable_notional = params.min_executable_notional

        cache = QuoteCache()
        engine = SpreadEngine(cache, settings)
        for exchange, fee in params.fee_overrides.items():
            engine.update_taker_fee(exchange, fee)

        threshold = (
            params.spread_threshold
            if params.spread_threshold is not None
            else settings.trading.spread_threshold
        )
        tracker = SpreadEventTracker(threshold=threshold)

        closed_events: list[dict[str, Any]] = []
        last_ts = params.from_ms
        sequence = 0
        for tick_ts, tick_rows in groupby(rows, key=lambda r: r["timestamp"]):
            for row in tick_rows:
                sequence += 1
                cache.update(_row_to_quote(row, sequence))
            spread_rows = engine.compute_all(now_ms=tick_ts)
            closed_events.extend(tracker.process(spread_rows, now_ms=tick_ts))
            last_ts = tick_ts
        closed_events.extend(tracker.flush_open(now_ms=last_ts))

        qualifying = [
            e
            for e in closed_events
            if (e["end_timestamp"] - e["start_timestamp"]) >= params.min_duration_ms
        ]
        total_pnl = sum((e["estimated_profit"] for e in qualifying), Decimal("0"))
        avg_pnl = total_pnl / len(qualifying) if qualifying else None

        return BacktestResult(
            params=params,
            ticks_processed=len(rows),
            truncated=truncated,
            total_events=len(qualifying),
            events=qualifying,
            total_simulated_pnl=total_pnl,
            average_pnl_per_event=avg_pnl,
        )

    async def _load_ticks(self, params: BacktestParams, max_ticks: int) -> list[Any]:
        table = Quote1s.__table__
        conditions = [
            table.c.symbol.in_(params.symbols),
            table.c.market_type == params.market_type.value,
            table.c.timestamp >= params.from_ms,
            table.c.timestamp < params.to_ms,
        ]
        stmt = (
            select(table)
            .where(and_(*conditions))
            .order_by(table.c.timestamp.asc())
            .limit(max_ticks + 1)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.mappings().all())
