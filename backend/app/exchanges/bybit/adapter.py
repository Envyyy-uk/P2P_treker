"""Bybit v5 spot orderbook.1 adapter.

Bybit вимагає прикладний ping кожні ~20 секунд.
Після reconnect локальний стан стакана скидається — чекаємо новий snapshot.
"""

import json
from typing import Any

from app.exchanges.base_ws import BaseWsAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.normalizer.bybit import BybitBookNormalizer


class BybitAdapter(BaseWsAdapter):
    exchange = Exchange.BYBIT
    ws_url = "wss://stream.bybit.com/v5/public/spot"
    keepalive_interval_s = 20.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._normalizer = BybitBookNormalizer()

    def subscribe_payloads(self, native_symbols: list[str]) -> list[str]:
        return [
            json.dumps({"op": "subscribe", "args": [f"orderbook.1.{s}" for s in native_symbols]})
        ]

    def keepalive_payload(self) -> str:
        return json.dumps({"op": "ping"})

    def on_reconnect(self) -> None:
        self._normalizer.reset()

    def parse(self, message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
        return self._normalizer.handle(message, received_ts_ms)
