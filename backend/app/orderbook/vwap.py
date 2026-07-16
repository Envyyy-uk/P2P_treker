"""VWAP і slippage по реальній глибині стакана (Фаза 4, п.2–3).

На відміну від Фази 1 (top-of-book, `executable_quantity = min(...)`),
тут ідемо по кількох рівнях книги, поки не наберемо цільовий обсяг —
це і є "реальний executable quantity/notional" з плану.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.orderbook.book import BookLevel

_ZERO = Decimal("0")


@dataclass(frozen=True)
class VwapResult:
    vwap_price: Decimal | None  # None, якщо обсяг взагалі недоступний
    filled_quantity: Decimal
    notional: Decimal
    fully_filled: bool  # False -> стакан вичерпано раніше, ніж набрався обсяг


def compute_vwap(levels: list[BookLevel], target_quantity: Decimal) -> VwapResult:
    """Проходить рівні `levels` У ПОРЯДКУ, В ЯКОМУ ЇХ ПЕРЕДАНО (найкращий
    рівень першим — виклик відповідає за сортування: `asks_sorted()` для
    купівлі, `bids_sorted()` для продажу), накопичуючи обсяг до
    `target_quantity`.
    """
    if target_quantity <= 0:
        raise ValueError("target_quantity must be positive")

    remaining = target_quantity
    filled = _ZERO
    notional = _ZERO
    for level in levels:
        if remaining <= 0:
            break
        take = min(level.quantity, remaining)
        filled += take
        notional += take * level.price
        remaining -= take

    if filled == 0:
        return VwapResult(
            vwap_price=None, filled_quantity=_ZERO, notional=_ZERO, fully_filled=False
        )
    return VwapResult(
        vwap_price=notional / filled,
        filled_quantity=filled,
        notional=notional,
        fully_filled=remaining <= 0,
    )


def buy_slippage_pct(top_ask: Decimal, vwap_price: Decimal) -> Decimal:
    """Наскільки VWAP купівлі гірший за top-of-book ask (частка, >=0 зазвичай)."""
    if top_ask <= 0:
        raise ValueError("top_ask must be positive")
    return (vwap_price / top_ask - 1) * 100


def sell_slippage_pct(top_bid: Decimal, vwap_price: Decimal) -> Decimal:
    """Наскільки VWAP продажу гірший за top-of-book bid (частка, >=0 зазвичай)."""
    if top_bid <= 0:
        raise ValueError("top_bid must be positive")
    return (1 - vwap_price / top_bid) * 100
