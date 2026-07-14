"""Binance spot bookTicker adapter.

Binance сам шле WS ping-фрейми (бібліотека відповідає pong автоматично),
тому прикладний keepalive не потрібен.
"""

import json
from typing import Any

from app.exchanges.base_ws import BaseWsAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.normalizer.binance import normalize_book_ticker


class BinanceAdapter(BaseWsAdapter):
    exchange = Exchange.BINANCE
    ws_url = "wss://stream.binance.com:9443/ws"
    keepalive_interval_s = None

    def subscribe_payloads(self, native_symbols: list[str]) -> list[str]:
        return [
            json.dumps(
                {
                    "method": "SUBSCRIBE",
                    "params": [f"{s.lower()}@bookTicker" for s in native_symbols],
                    "id": 1,
                }
            )
        ]

    def parse(self, message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
        return normalize_book_ticker(message, received_ts_ms)
