"""Інтеграційний тест WS-каналу спредів: клієнт отримує spread_update
з наростаючим sequence; движок бачить котирування, покладені в кеш."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import now_ms


def put_quotes(cache):
    current = now_ms()
    for exchange, bid, ask in [
        (Exchange.BINANCE, "100", "100.1"),
        (Exchange.BYBIT, "101", "101.1"),
    ]:
        cache.update(
            NormalizedQuote(
                exchange=exchange,
                market_type=MarketType.SPOT,
                symbol="BTC-USDT",
                bid_price=bid,
                bid_quantity="1",
                ask_price=ask,
                ask_quantity="1",
                exchange_timestamp=current,
                received_timestamp=current,
                sequence=1,
            )
        )


def test_ws_pushes_spread_updates(monkeypatch):
    monkeypatch.setenv("LIVE_ADAPTERS_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                put_quotes(app.state.quote_cache)
                with client.websocket_connect("/ws/spreads") as ws:
                    first = json.loads(ws.receive_text())
                    second = json.loads(ws.receive_text())
        assert first["type"] in ("spread_update", "heartbeat")
        assert second["sequence"] > first["sequence"]
        update = first if first["type"] == "spread_update" else second
        directions = {(row["buy_exchange"], row["sell_exchange"]) for row in update["data"]}
        assert ("binance", "bybit") in directions
        assert ("bybit", "binance") in directions
        row = next(
            r
            for r in update["data"]
            if (r["buy_exchange"], r["sell_exchange"]) == ("binance", "bybit")
        )
        assert row["valid"] is True
        assert isinstance(row["net_spread_pct"], str)
    finally:
        get_settings.cache_clear()


def test_health_exposes_adapters_and_cache(monkeypatch):
    monkeypatch.setenv("LIVE_ADAPTERS_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                body = client.get("/health").json()
        assert body["cached_quotes"] == 0
        assert body["ws_clients"] == 0
        assert body["exchanges"] == {}  # адаптери вимкнені в тестах
    finally:
        get_settings.cache_clear()
