"""Формули spread-розрахунків (Фаза 0, п.12; докладно — docs/phase-0/formulas.md).

Тільки Decimal. Зміна будь-якої формули інкрементує CALCULATION_VERSION;
нова версія застосовується тільки проспективно — збережені spread_events
ніколи не перераховуються заднім числом (PLAN.md, Фаза 2).
"""

from decimal import Decimal

from app.core.exceptions import MarketTypeMismatchError
from app.models.quote import NormalizedQuote

CALCULATION_VERSION = 1

_ONE = Decimal(1)


def gross_spread(buy_ask: Decimal, sell_bid: Decimal) -> Decimal:
    """gross_spread = sell_bid / buy_ask - 1"""
    if buy_ask <= 0:
        raise ValueError("buy_ask must be positive")
    return sell_bid / buy_ask - _ONE


def net_spread(
    buy_ask: Decimal,
    sell_bid: Decimal,
    buy_fee: Decimal,
    sell_fee: Decimal,
) -> Decimal:
    """Мультиплікативна модель:

    net_return = sell_bid × (1 - sell_fee) / (buy_ask × (1 + buy_fee)) - 1
    """
    if buy_ask <= 0:
        raise ValueError("buy_ask must be positive")
    if buy_fee < 0 or sell_fee < 0:
        raise ValueError("fees must be non-negative")
    return (sell_bid * (_ONE - sell_fee)) / (buy_ask * (_ONE + buy_fee)) - _ONE


def executable_quantity(buy_ask_qty: Decimal, sell_bid_qty: Decimal) -> Decimal:
    """Top-of-book MVP: min(обсяг ask на купівлі, обсяг bid на продажу)."""
    return min(buy_ask_qty, sell_bid_qty)


def executable_notional(quantity: Decimal, buy_ask: Decimal) -> Decimal:
    return quantity * buy_ask


def expected_gross_profit(quantity: Decimal, buy_ask: Decimal, sell_bid: Decimal) -> Decimal:
    return quantity * (sell_bid - buy_ask)


def expected_net_profit(
    quantity: Decimal,
    buy_ask: Decimal,
    sell_bid: Decimal,
    buy_fee: Decimal,
    sell_fee: Decimal,
) -> Decimal:
    return quantity * buy_ask * net_spread(buy_ask, sell_bid, buy_fee, sell_fee)


def ensure_comparable(buy_quote: NormalizedQuote, sell_quote: NormalizedQuote) -> None:
    """Котирування можна порівнювати тільки в межах одного market type
    та одного канонічного символу (наскрізне правило плану)."""
    if buy_quote.market_type is not sell_quote.market_type:
        raise MarketTypeMismatchError(
            f"Cannot compare {buy_quote.market_type} with {sell_quote.market_type}"
        )
    if buy_quote.symbol != sell_quote.symbol:
        raise MarketTypeMismatchError(
            f"Cannot compare different symbols: {buy_quote.symbol} vs {sell_quote.symbol}"
        )


def timestamps_aligned(
    quote_a: NormalizedQuote, quote_b: NormalizedQuote, max_diff_ms: int
) -> bool:
    """Перевірка максимальної різниці часу між біржами (Фаза 0, п.7)."""
    return abs(quote_a.exchange_timestamp - quote_b.exchange_timestamp) <= max_diff_ms
