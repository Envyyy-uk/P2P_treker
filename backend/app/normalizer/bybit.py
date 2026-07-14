"""Нормалізація Bybit v5 spot orderbook.1 → NormalizedQuote.

Формат:
{"topic":"orderbook.1.BTCUSDT","ts":1672304484978,"type":"snapshot",
 "data":{"s":"BTCUSDT","b":[["16493.50","0.006"]],"a":[["16611.00","0.029"]],
         "u":18521288,"seq":7961638724}}

Стан: snapshot замінює обидві сторони; delta оновлює тільки надіслані
сторони (порожній список = без змін, кількість "0" = рівень зник).
Нормалізатор stateful — тримає останні best bid/ask на символ.
"""

from decimal import Decimal
from typing import Any

from app.core.symbols import to_canonical
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote

_ZERO = Decimal("0")


class BybitBookNormalizer:
    def __init__(self) -> None:
        # symbol -> (price, qty) для кожної сторони; None = сторона відсутня
        self._bids: dict[str, tuple[str, str] | None] = {}
        self._asks: dict[str, tuple[str, str] | None] = {}
        self._sequences: dict[str, int] = {}

    def reset(self) -> None:
        """Після reconnect локальний стан скидається — чекаємо новий snapshot."""
        self._bids.clear()
        self._asks.clear()
        self._sequences.clear()

    def handle(self, message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
        topic = message.get("topic", "")
        if not topic.startswith("orderbook.1.") or "data" not in message:
            return None  # pong / subscribe ack / інші topic'и
        data = message["data"]
        native = data.get("s", "")
        try:
            symbol = to_canonical(native, Exchange.BYBIT)
        except KeyError:
            return None

        msg_type = message.get("type")
        sequence = data.get("u")
        if msg_type == "snapshot":
            self._apply_side(self._bids, symbol, data.get("b", []), snapshot=True)
            self._apply_side(self._asks, symbol, data.get("a", []), snapshot=True)
        elif msg_type == "delta":
            if symbol not in self._sequences:
                return None  # delta до першого snapshot — ігноруємо
            self._apply_side(self._bids, symbol, data.get("b", []), snapshot=False)
            self._apply_side(self._asks, symbol, data.get("a", []), snapshot=False)
        else:
            return None
        if sequence is not None:
            self._sequences[symbol] = sequence

        bid = self._bids.get(symbol)
        ask = self._asks.get(symbol)
        if bid is None or ask is None:
            return None  # одна зі сторін порожня — котирування неповне
        exchange_ts = message.get("ts", received_ts_ms)
        return NormalizedQuote(
            exchange=Exchange.BYBIT,
            market_type=MarketType.SPOT,
            symbol=symbol,
            bid_price=bid[0],
            bid_quantity=bid[1],
            ask_price=ask[0],
            ask_quantity=ask[1],
            exchange_timestamp=exchange_ts,
            received_timestamp=received_ts_ms,
            sequence=sequence,
        )

    @staticmethod
    def _apply_side(
        store: dict[str, tuple[str, str] | None],
        symbol: str,
        levels: list[list[str]],
        snapshot: bool,
    ) -> None:
        if not levels:
            if snapshot:
                store[symbol] = None
            return  # порожній список у delta = без змін
        price, qty = levels[0][0], levels[0][1]
        store[symbol] = None if Decimal(qty) == _ZERO else (price, qty)
