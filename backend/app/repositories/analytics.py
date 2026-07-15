"""Analytics repository (Фаза 3): тільки читання історії quotes/spread_events.

Не бере участі в write-шляху (Фаза 2/2.1) — окремий read-only шлях поверх
тих самих таблиць. Дає:
  - OHLC-серію котирувань з автовибором downsample-рівня (Фаза 3, п.5:
    backend виконує агрегацію/downsampling/обмеження кількості точок);
  - історію gross/net spread для пари бірж, порахований через
    ТУ САМУ формулу, що й live Spread Engine (app.spread.formulas) —
    щоб історія і live ніколи не розходились у математиці;
  - фільтрований/paginated список spread events;
  - агреговану статистику (Postgres percentile_cont для медіани).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.downsample_models import Quote1m, Quote5m, Quote10s
from app.database.models import Quote1s, SpreadEvent
from app.models.enums import Exchange, MarketType
from app.spread import formulas

QUOTE_TABLES: dict[str, Table] = {
    "1s": Quote1s.__table__,  # type: ignore[dict-item]
    "10s": Quote10s.__table__,  # type: ignore[dict-item]
    "1m": Quote1m.__table__,  # type: ignore[dict-item]
    "5m": Quote5m.__table__,  # type: ignore[dict-item]
}
INTERVAL_MS: dict[str, int] = {"1s": 1_000, "10s": 10_000, "1m": 60_000, "5m": 300_000}
_INTERVAL_ORDER = ("1s", "10s", "1m", "5m")


def choose_interval(from_ms: int, to_ms: int, max_points: int, requested: str | None) -> str:
    """Автовибір granularity (план, Фаза 3, п.5).

    Якщо клієнт явно попросив рівень — використовуємо його (свідомий вибір).
    Інакше беремо найдрібніший інтервал, що вкладається в max_points; якщо
    навіть 5хв замало — все одно повертаємо 5хв, а виклик обріже результат
    через LIMIT і позначить truncated=True.
    """
    if requested and requested != "auto":
        if requested not in INTERVAL_MS:
            raise ValueError(f"Unknown interval: {requested!r}")
        return requested
    span = max(to_ms - from_ms, 1)
    for interval in _INTERVAL_ORDER:
        if span // INTERVAL_MS[interval] <= max_points:
            return interval
    return _INTERVAL_ORDER[-1]


def _row_to_ohlc(interval: str, row: dict[str, Any]) -> dict[str, Any]:
    """Уніфікує сирі quotes_1s (single snapshot) і downsample-рядки (OHLC)
    в одну форму — фронтенду не треба знати, з якої таблиці прийшли дані."""
    if interval == "1s":
        bid, ask = row["bid_price"], row["ask_price"]
        return {
            "ts": row["timestamp"],
            "open_bid": bid,
            "high_bid": bid,
            "low_bid": bid,
            "close_bid": bid,
            "open_ask": ask,
            "high_ask": ask,
            "low_ask": ask,
            "close_ask": ask,
            "sample_count": 1,
        }
    return {
        "ts": row["bucket_timestamp"],
        "open_bid": row["open_bid"],
        "high_bid": row["high_bid"],
        "low_bid": row["low_bid"],
        "close_bid": row["close_bid"],
        "open_ask": row["open_ask"],
        "high_ask": row["high_ask"],
        "low_ask": row["low_ask"],
        "close_ask": row["close_ask"],
        "sample_count": row["sample_count"],
    }


@dataclass
class QuoteHistoryResult:
    interval: str
    points: list[dict[str, Any]]
    truncated: bool


@dataclass
class SpreadHistoryResult:
    interval: str
    points: list[dict[str, Any]]
    truncated: bool


@dataclass
class SpreadEventStats:
    total_count: int
    qualifying_count: int
    pct_meeting_min_duration: Decimal | None
    total_duration_ms: int
    average_duration_ms: Decimal | None
    median_duration_ms: Decimal | None
    max_duration_ms: int | None
    average_net_spread_pct: Decimal | None
    max_net_spread_pct: Decimal | None
    average_executable_quantity: Decimal | None
    average_estimated_profit: Decimal | None


class AnalyticsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ---- quotes OHLC history -------------------------------------------------

    async def quote_history(
        self,
        *,
        exchange: Exchange,
        symbol: str,
        market_type: MarketType,
        from_ms: int,
        to_ms: int,
        interval: str,
        max_points: int,
    ) -> QuoteHistoryResult:
        rows = await self._fetch_ohlc(
            exchange, symbol, market_type, from_ms, to_ms, interval, max_points
        )
        truncated = len(rows) > max_points
        points = [_row_to_ohlc(interval, dict(row)) for row in rows[:max_points]]
        return QuoteHistoryResult(interval=interval, points=points, truncated=truncated)

    async def _fetch_ohlc(
        self,
        exchange: Exchange,
        symbol: str,
        market_type: MarketType,
        from_ms: int,
        to_ms: int,
        interval: str,
        max_points: int,
    ) -> list[Any]:
        table = QUOTE_TABLES[interval]
        ts_col = table.c.timestamp if interval == "1s" else table.c.bucket_timestamp
        conditions = [
            table.c.exchange == exchange.value,
            table.c.symbol == symbol,
            table.c.market_type == market_type.value,
            ts_col >= from_ms,
            ts_col < to_ms,
        ]
        # +1 рядок, щоб дізнатись, чи є дані за межами cap (truncated).
        stmt = select(table).where(and_(*conditions)).order_by(ts_col.asc()).limit(max_points + 1)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.mappings().all())

    # ---- computed spread history (buy/sell OHLC aligned by bucket) -----------

    async def spread_history(
        self,
        *,
        buy_exchange: Exchange,
        sell_exchange: Exchange,
        symbol: str,
        market_type: MarketType,
        from_ms: int,
        to_ms: int,
        interval: str,
        max_points: int,
        buy_fee: Decimal,
        sell_fee: Decimal,
    ) -> SpreadHistoryResult:
        """Gross/Net spread по історичних close-цінах (план, Фаза 3, п.5).

        Рахується ТІЄЮ Ж формулою, що й live Spread Engine
        (app.spread.formulas) — одне джерело правди для математики.
        Комісії — поточні з конфігурації, не історичні на кожен момент
        часу (BД їх не зберігає посекундно) — прийнятне спрощення MVP,
        аналогічне застереженню про backtesting (план, Фаза 3.1, п.5).
        """
        buy_rows = await self._fetch_ohlc(
            buy_exchange, symbol, market_type, from_ms, to_ms, interval, max_points
        )
        sell_rows = await self._fetch_ohlc(
            sell_exchange, symbol, market_type, from_ms, to_ms, interval, max_points
        )
        ts_key = "timestamp" if interval == "1s" else "bucket_timestamp"
        sell_by_ts = {row[ts_key]: row for row in sell_rows}

        points: list[dict[str, Any]] = []
        for buy_row in buy_rows:
            ts = buy_row[ts_key]
            sell_row = sell_by_ts.get(ts)
            if sell_row is None:
                continue  # немає вирівняних даних sell-біржі на цей бакет
            buy_ask = buy_row["ask_price"] if interval == "1s" else buy_row["close_ask"]
            sell_bid = sell_row["bid_price"] if interval == "1s" else sell_row["close_bid"]
            gross = formulas.gross_spread(buy_ask, sell_bid)
            net = formulas.net_spread(buy_ask, sell_bid, buy_fee, sell_fee)
            points.append(
                {
                    "ts": ts,
                    "buy_price": buy_ask,
                    "sell_price": sell_bid,
                    "gross_spread_pct": gross * 100,
                    "net_spread_pct": net * 100,
                }
            )
        points.sort(key=lambda p: p["ts"])
        truncated = len(buy_rows) > max_points or len(sell_rows) > max_points
        return SpreadHistoryResult(
            interval=interval, points=points[:max_points], truncated=truncated
        )

    # ---- spread events: list + stats -----------------------------------------

    def _event_filters(
        self,
        *,
        symbol: str | None,
        buy_exchange: Exchange | None,
        sell_exchange: Exchange | None,
        market_type: MarketType | None,
        from_ms: int | None,
        to_ms: int | None,
        min_net_spread_pct: Decimal | None,
        min_notional: Decimal | None,
    ) -> list[Any]:
        table = SpreadEvent.__table__
        conditions: list[Any] = []
        if symbol is not None:
            conditions.append(table.c.symbol == symbol)
        if buy_exchange is not None:
            conditions.append(table.c.buy_exchange == buy_exchange.value)
        if sell_exchange is not None:
            conditions.append(table.c.sell_exchange == sell_exchange.value)
        if market_type is not None:
            conditions.append(table.c.market_type == market_type.value)
        if from_ms is not None:
            conditions.append(table.c.start_timestamp >= from_ms)
        if to_ms is not None:
            conditions.append(table.c.start_timestamp < to_ms)
        if min_net_spread_pct is not None:
            conditions.append(table.c.average_net_spread >= min_net_spread_pct / 100)
        if min_notional is not None:
            conditions.append(table.c.executable_notional >= min_notional)
        return conditions

    async def list_spread_events(
        self,
        *,
        symbol: str | None = None,
        buy_exchange: Exchange | None = None,
        sell_exchange: Exchange | None = None,
        market_type: MarketType | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        min_net_spread_pct: Decimal | None = None,
        min_notional: Decimal | None = None,
        min_duration_ms: int = 0,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        table = SpreadEvent.__table__
        conditions = self._event_filters(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            market_type=market_type,
            from_ms=from_ms,
            to_ms=to_ms,
            min_net_spread_pct=min_net_spread_pct,
            min_notional=min_notional,
        )
        duration = table.c.end_timestamp - table.c.start_timestamp
        if min_duration_ms > 0:
            conditions.append(duration >= min_duration_ms)
        where_clause = and_(*conditions) if conditions else true()

        async with self._session_factory() as session:
            total = (
                await session.execute(select(func.count()).select_from(table).where(where_clause))
            ).scalar_one()
            stmt = (
                select(table)
                .where(where_clause)
                .order_by(table.c.start_timestamp.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            rows = (await session.execute(stmt)).mappings().all()
        return [dict(row) for row in rows], total

    async def spread_event_stats(
        self,
        *,
        symbol: str | None = None,
        buy_exchange: Exchange | None = None,
        sell_exchange: Exchange | None = None,
        market_type: MarketType | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        min_net_spread_pct: Decimal | None = None,
        min_notional: Decimal | None = None,
        min_duration_ms: int = 0,
    ) -> SpreadEventStats:
        table = SpreadEvent.__table__
        base_conditions = self._event_filters(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            market_type=market_type,
            from_ms=from_ms,
            to_ms=to_ms,
            min_net_spread_pct=min_net_spread_pct,
            min_notional=min_notional,
        )
        base_where = and_(*base_conditions) if base_conditions else true()
        duration = table.c.end_timestamp - table.c.start_timestamp
        duration_condition = duration >= min_duration_ms
        qualifying_where = (
            and_(*base_conditions, duration_condition) if base_conditions else duration_condition
        )

        async with self._session_factory() as session:
            total_count = (
                await session.execute(select(func.count()).select_from(table).where(base_where))
            ).scalar_one()

            agg_stmt = select(
                func.count().label("qualifying_count"),
                func.coalesce(func.sum(duration), 0).label("total_duration_ms"),
                func.avg(duration).label("average_duration_ms"),
                func.percentile_cont(0.5).within_group(duration.asc()).label("median_duration_ms"),
                func.max(duration).label("max_duration_ms"),
                func.avg(table.c.average_net_spread).label("average_net_spread"),
                func.max(table.c.max_net_spread).label("max_net_spread"),
                func.avg(table.c.executable_quantity).label("average_executable_quantity"),
                func.avg(table.c.estimated_profit).label("average_estimated_profit"),
            ).where(qualifying_where)
            agg = (await session.execute(agg_stmt)).mappings().one()

        qualifying_count = agg["qualifying_count"] or 0
        pct = Decimal(qualifying_count) / Decimal(total_count) * 100 if total_count else None
        avg_net = agg["average_net_spread"]
        max_net = agg["max_net_spread"]
        # percentile_cont (ordered-set aggregate) returns a Python float over
        # asyncpg/SQLAlchemy, unlike avg()/sum() which come back as Decimal —
        # normalize via str() to avoid float rounding error, per "тільки Decimal".
        median = agg["median_duration_ms"]
        return SpreadEventStats(
            total_count=total_count,
            qualifying_count=qualifying_count,
            pct_meeting_min_duration=pct,
            total_duration_ms=agg["total_duration_ms"] or 0,
            average_duration_ms=agg["average_duration_ms"],
            median_duration_ms=Decimal(str(median)) if median is not None else None,
            max_duration_ms=agg["max_duration_ms"],
            average_net_spread_pct=avg_net * 100 if avg_net is not None else None,
            max_net_spread_pct=max_net * 100 if max_net is not None else None,
            average_executable_quantity=agg["average_executable_quantity"],
            average_estimated_profit=agg["average_estimated_profit"],
        )

    async def export_spread_events(
        self,
        *,
        symbol: str | None = None,
        buy_exchange: Exchange | None = None,
        sell_exchange: Exchange | None = None,
        market_type: MarketType | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        min_net_spread_pct: Decimal | None = None,
        min_notional: Decimal | None = None,
        min_duration_ms: int = 0,
        max_rows: int = 50_000,
    ) -> list[dict[str, Any]]:
        """Без пагінації (експорт), але з жорстким cap'ом на обсяг вибірки."""
        table = SpreadEvent.__table__
        conditions = self._event_filters(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            market_type=market_type,
            from_ms=from_ms,
            to_ms=to_ms,
            min_net_spread_pct=min_net_spread_pct,
            min_notional=min_notional,
        )
        duration = table.c.end_timestamp - table.c.start_timestamp
        if min_duration_ms > 0:
            conditions.append(duration >= min_duration_ms)
        where_clause = and_(*conditions) if conditions else true()

        stmt = (
            select(table)
            .where(where_clause)
            .order_by(table.c.start_timestamp.asc())
            .limit(max_rows)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).mappings().all()
        return [dict(row) for row in rows]
