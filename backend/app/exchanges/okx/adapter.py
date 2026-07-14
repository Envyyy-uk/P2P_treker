"""OKX bbo-tbt adapter (public channel, best bid/offer).

OKX закриває з'єднання після 30 с тиші — шлемо текстовий "ping",
біржа відповідає "pong" (обробляється у base_ws)."""

import json
from typing import Any

from app.exchanges.base_ws import BaseWsAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.normalizer.okx import normalize_bbo


class OKXAdapter(BaseWsAdapter):
    exchange = Exchange.OKX
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    keepalive_interval_s = 25.0

    def subscribe_payloads(self, native_symbols: list[str]) -> list[str]:
        return [
            json.dumps(
                {
                    "op": "subscribe",
                    "args": [{"channel": "bbo-tbt", "instId": s} for s in native_symbols],
                }
            )
        ]

    def keepalive_payload(self) -> str:
        return "ping"

    def parse(self, message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
        return normalize_bbo(message, received_ts_ms)
