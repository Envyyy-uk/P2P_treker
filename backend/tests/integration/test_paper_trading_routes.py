"""Paper Trading API: реальний застосунок (без БД — цей підсистема в
пам'яті і не залежить від Postgres), реальний PaperTradingEngine,
реальні (щедро профінансовані) баланси зі старту застосунку."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LIVE_ADAPTERS_ENABLED", "false")
    monkeypatch.setenv("DATABASE__ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as c:
                yield c
    finally:
        get_settings.cache_clear()


def make_body(**overrides):
    body = {
        "symbol": "BTC-USDT",
        "buy_exchange": "binance",
        "sell_exchange": "bybit",
        "quantity": "1",
        "buy_book": {
            "bids": [{"price": "99", "quantity": "10"}],
            "asks": [{"price": "100", "quantity": "10"}],
        },
        "sell_book": {
            "bids": [{"price": "102", "quantity": "10"}],
            "asks": [{"price": "103", "quantity": "10"}],
        },
    }
    body.update(overrides)
    return body


def test_execute_successful_trade(client):
    resp = client.post("/api/paper-trading/execute", json=make_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["buy_order"]["status"] == "filled"
    assert body["sell_order"]["status"] == "filled"
    assert body["buy_order"]["avg_fill_price"] == "100"
    assert body["sell_order"]["avg_fill_price"] == "102"
    assert body["realized_pnl"] is not None


def test_execute_rejects_same_exchange(client):
    resp = client.post("/api/paper-trading/execute", json=make_body(sell_exchange="binance"))
    assert resp.status_code == 400


def test_execute_rejects_non_positive_quantity(client):
    resp = client.post("/api/paper-trading/execute", json=make_body(quantity="0"))
    assert resp.status_code == 400


def test_execute_with_empty_book_rejects_buy_leg(client):
    resp = client.post(
        "/api/paper-trading/execute",
        json=make_body(buy_book={"bids": [], "asks": []}),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["buy_order"]["status"] == "rejected"
    assert body["sell_order"]["status"] == "canceled"


def test_balances_endpoint_shows_default_funding(client):
    resp = client.get("/api/paper-trading/balances")
    assert resp.status_code == 200
    balances = resp.json()
    assert "binance:USDT" in balances
    assert float(balances["binance:USDT"]["available"]) > 0


def test_set_balance_endpoint(client):
    resp = client.post(
        "/api/paper-trading/balances",
        json={"exchange": "binance", "asset": "USDT", "total": "5000"},
    )
    assert resp.status_code == 200
    balances = client.get("/api/paper-trading/balances").json()
    assert balances["binance:USDT"]["total"] == "5000"


def test_set_balance_then_insufficient_funds_rejects_order(client):
    client.post(
        "/api/paper-trading/balances",
        json={"exchange": "binance", "asset": "USDT", "total": "1"},
    )
    resp = client.post("/api/paper-trading/execute", json=make_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["buy_order"]["status"] == "rejected"
    assert "balance" in body["buy_order"]["rejection_reason"]
