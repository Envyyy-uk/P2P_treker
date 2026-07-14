"""Spread Engine (Фаза 1, п.6–7).

Рахує ОБИДВА напрямки для кожної пари бірж по кожному символу.
Тільки Decimal. Stale-котирування позначаються, а не зникають мовчки —
UI показує їх окремим статусом; валідною можливість стає лише коли
все свіже і обсяг вищий за пороги.
"""

from dataclasses import dataclass
from decimal import Decimal
from itertools import permutations

from app.core.config import Settings
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache
from app.spread import formulas
from app.spread.formulas import CALCULATION_VERSION

_HUNDRED = Decimal("100")
_PCT_PLACES = Decimal("0.0001")  # 4 знаки у відсотках


@dataclass(frozen=True)
class SpreadRow:
    symbol: str
    market_type: MarketType
    buy_exchange: Exchange
    sell_exchange: Exchange
    buy_price: Decimal  # ask на біржі купівлі
    sell_price: Decimal  # bid на біржі продажу
    gross_spread_pct: Decimal
    net_spread_pct: Decimal
    executable_quantity: Decimal
    executable_notional: Decimal
    expected_net_profit: Decimal
    quote_age_ms: int  # максимальний вік з двох котирувань
    timestamp_diff_ms: int
    stale: bool
    valid: bool  # свіже, вирівняне в часі, обсяг вище порогів
    calculation_version: int = CALCULATION_VERSION

    def to_wire(self) -> dict[str, object]:
        """Серіалізація для WS: Decimal -> str, щоб не втратити точність."""
        return {
            "symbol": self.symbol,
            "market_type": self.market_type.value,
            "buy_exchange": self.buy_exchange.value,
            "sell_exchange": self.sell_exchange.value,
            "buy_price": str(self.buy_price),
            "sell_price": str(self.sell_price),
            "gross_spread_pct": str(self.gross_spread_pct.quantize(_PCT_PLACES)),
            "net_spread_pct": str(self.net_spread_pct.quantize(_PCT_PLACES)),
            "executable_quantity": str(self.executable_quantity),
            "executable_notional": str(self.executable_notional),
            "expected_net_profit": str(self.expected_net_profit),
            "quote_age_ms": self.quote_age_ms,
            "timestamp_diff_ms": self.timestamp_diff_ms,
            "stale": self.stale,
            "valid": self.valid,
            "calculation_version": self.calculation_version,
        }


class SpreadEngine:
    def __init__(self, cache: QuoteCache, settings: Settings) -> None:
        self._cache = cache
        self._settings = settings
        self._taker_fees: dict[Exchange, Decimal] = {
            exchange: cfg.taker_fee for exchange, cfg in settings.exchanges.items() if cfg.enabled
        }

    def update_taker_fee(self, exchange: Exchange, fee: Decimal) -> None:
        """Для періодичного оновлення комісій з API біржі (Фаза 0, п.5)."""
        if fee < 0:
            raise ValueError("fee must be non-negative")
        self._taker_fees[exchange] = fee

    def compute_all(self, now_ms: int) -> list[SpreadRow]:
        trading = self._settings.trading
        rows: list[SpreadRow] = []
        for symbol in trading.symbols:
            quotes = self._cache.snapshot(trading.market_type, symbol)
            available = {e: q for e, q in quotes.items() if e in self._taker_fees}
            for buy_exchange, sell_exchange in permutations(available, 2):
                rows.append(
                    self._compute_pair(available[buy_exchange], available[sell_exchange], now_ms)
                )
        return rows

    def _compute_pair(
        self, buy_quote: NormalizedQuote, sell_quote: NormalizedQuote, now_ms: int
    ) -> SpreadRow:
        formulas.ensure_comparable(buy_quote, sell_quote)
        trading = self._settings.trading

        # Напрямок: купуємо по ask на buy-біржі, продаємо по bid на sell-біржі.
        buy_ask = buy_quote.ask_price
        sell_bid = sell_quote.bid_price
        buy_fee = self._taker_fees[buy_quote.exchange]
        sell_fee = self._taker_fees[sell_quote.exchange]

        gross = formulas.gross_spread(buy_ask, sell_bid)
        net = formulas.net_spread(buy_ask, sell_bid, buy_fee, sell_fee)
        quantity = formulas.executable_quantity(buy_quote.ask_quantity, sell_quote.bid_quantity)
        notional = formulas.executable_notional(quantity, buy_ask)
        net_profit = formulas.expected_net_profit(quantity, buy_ask, sell_bid, buy_fee, sell_fee)

        age_ms = max(buy_quote.quote_age_ms(now_ms), sell_quote.quote_age_ms(now_ms))
        ts_diff_ms = abs(buy_quote.exchange_timestamp - sell_quote.exchange_timestamp)
        stale = buy_quote.is_stale(now_ms, trading.max_quote_age_ms) or sell_quote.is_stale(
            now_ms, trading.max_quote_age_ms
        )
        aligned = ts_diff_ms <= trading.max_timestamp_diff_ms
        volume_ok = (
            quantity >= trading.min_executable_quantity
            and quantity > 0
            and notional >= trading.min_executable_notional
        )
        return SpreadRow(
            symbol=buy_quote.symbol,
            market_type=buy_quote.market_type,
            buy_exchange=buy_quote.exchange,
            sell_exchange=sell_quote.exchange,
            buy_price=buy_ask,
            sell_price=sell_bid,
            gross_spread_pct=gross * _HUNDRED,
            net_spread_pct=net * _HUNDRED,
            executable_quantity=quantity,
            executable_notional=notional,
            expected_net_profit=net_profit,
            quote_age_ms=age_ms,
            timestamp_diff_ms=ts_diff_ms,
            stale=stale,
            valid=not stale and aligned and volume_ok,
        )
