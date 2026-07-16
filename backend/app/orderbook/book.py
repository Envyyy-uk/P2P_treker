"""Повний Order Book з кількома рівнями (Фаза 4, п.1).

На відміну від `QuoteCache` (Фаза 1) — top-of-book лише, тут зберігається
кілька рівнів bid/ask на (exchange, symbol), з підтримкою snapshot + delta
і перевіркою sequence. Потрібно для VWAP/slippage (Фаза 4, п.2–3).

Sequence-модель — узагальнена (один монотонний лічильник), не специфічна
для конкретної біржі. Кожен реальний потік delta (Binance U/u/pu, Bybit
`u`, OKX `seqId`) має бути нормалізований адаптером біржі в цю просту
модель ПЕРЕД викликом `apply_delta` — так само, як нормалізатори Фази 1
перетворювали різні формати котирувань в один `NormalizedQuote`.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    quantity: Decimal


class OrderBook:
    """Локальний стакан для однієї (exchange, symbol) пари.

    Життєвий цикл (план, Фаза 1, п.2 — та сама вимога, тут для повної
    глибини, а не тільки top-of-book):
      1. `apply_snapshot` — початковий стан, скидає попередній.
      2. `apply_delta` — інкрементальні зміни; виявлений розрив sequence
         позначає стакан як desynced (`synced=False`) — виклик має
         запросити новий snapshot (REST fallback, план Фаза 1, п.2) і
         викликати `apply_snapshot` знову, перш ніж довіряти даним.
    """

    def __init__(self) -> None:
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._sequence: int | None = None
        self._synced = False

    @property
    def synced(self) -> bool:
        return self._synced

    @property
    def sequence(self) -> int | None:
        return self._sequence

    def apply_snapshot(
        self,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        sequence: int,
    ) -> None:
        self._bids = {price: qty for price, qty in bids if qty > 0}
        self._asks = {price: qty for price, qty in asks if qty > 0}
        self._sequence = sequence
        self._synced = True

    def apply_delta(
        self,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        sequence: int,
    ) -> bool:
        """Застосовує інкрементальні зміни. Повертає False, якщо виявлено
        розрив sequence (пропущені повідомлення) — стакан позначається
        desynced, дані з нього використовувати не можна до нового snapshot.
        """
        if not self._synced:
            return False
        assert self._sequence is not None  # synced=True гарантує це
        if sequence <= self._sequence:
            return True  # старе/повторне повідомлення — безпечно ігнорувати
        if sequence > self._sequence + 1:
            self._synced = False
            return False
        self._sequence = sequence
        self._apply_side(self._bids, bids)
        self._apply_side(self._asks, asks)
        return True

    @staticmethod
    def _apply_side(store: dict[Decimal, Decimal], levels: list[tuple[Decimal, Decimal]]) -> None:
        for price, qty in levels:
            if qty == 0:
                store.pop(price, None)
            else:
                store[price] = qty

    def best_bid(self) -> BookLevel | None:
        if not self._bids:
            return None
        price = max(self._bids)
        return BookLevel(price, self._bids[price])

    def best_ask(self) -> BookLevel | None:
        if not self._asks:
            return None
        price = min(self._asks)
        return BookLevel(price, self._asks[price])

    def bids_sorted(self) -> list[BookLevel]:
        """Від найвищої ціни (найкращої для продажу) до найнижчої."""
        return [BookLevel(p, self._bids[p]) for p in sorted(self._bids, reverse=True)]

    def asks_sorted(self) -> list[BookLevel]:
        """Від найнижчої ціни (найкращої для купівлі) до найвищої."""
        return [BookLevel(p, self._asks[p]) for p in sorted(self._asks)]

    def depth(self) -> tuple[int, int]:
        return len(self._bids), len(self._asks)
