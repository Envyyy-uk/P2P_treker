"""Capital Model API (Фаза 4.1): реальний застосунок, реальний
CapitalMonitor поверх того самого BalanceManager, що й Paper Trading."""

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


def test_status_returns_all_enabled_exchanges(client):
    resp = client.get("/api/capital/status")
    assert resp.status_code == 200
    body = resp.json()
    exchanges = {row["exchange"] for row in body}
    assert exchanges == {"binance", "bybit", "okx"}
    for row in body:
        assert row["quote_asset_status"]["asset"] == "USDT"
        assert float(row["quote_asset_status"]["available"]) > 0


def test_rebalance_signals_empty_without_configured_target(client):
    resp = client.get("/api/capital/rebalance-signals")
    assert resp.status_code == 200
    assert resp.json() == []


def test_check_direction_available_by_default(client):
    resp = client.post(
        "/api/capital/check-direction",
        json={
            "symbol": "BTC-USDT",
            "buy_exchange": "binance",
            "sell_exchange": "bybit",
            "quantity": "1",
            "buy_price": "100",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is True


def test_check_direction_unavailable_after_draining_balance(client):
    client.post(
        "/api/paper-trading/balances",
        json={"exchange": "binance", "asset": "USDT", "total": "1"},
    )
    resp = client.post(
        "/api/capital/check-direction",
        json={
            "symbol": "BTC-USDT",
            "buy_exchange": "binance",
            "sell_exchange": "bybit",
            "quantity": "1",
            "buy_price": "100",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "USDT" in body["reason"]


def test_transfer_moves_funds_and_reflects_in_balances(client):
    before = client.get("/api/paper-trading/balances").json()
    before_binance = float(before["binance:USDT"]["available"])
    before_bybit = float(before["bybit:USDT"]["available"])

    resp = client.post(
        "/api/capital/transfer",
        json={
            "asset": "USDT",
            "from_exchange": "binance",
            "to_exchange": "bybit",
            "amount": "1000",
        },
    )
    assert resp.status_code == 200

    after = client.get("/api/paper-trading/balances").json()
    assert float(after["binance:USDT"]["available"]) == before_binance - 1000
    assert float(after["bybit:USDT"]["available"]) == before_bybit + 1000


def test_transfer_rejects_same_exchange(client):
    resp = client.post(
        "/api/capital/transfer",
        json={
            "asset": "USDT",
            "from_exchange": "binance",
            "to_exchange": "binance",
            "amount": "100",
        },
    )
    assert resp.status_code == 400


def test_transfer_rejects_non_positive_amount(client):
    resp = client.post(
        "/api/capital/transfer",
        json={"asset": "USDT", "from_exchange": "binance", "to_exchange": "bybit", "amount": "0"},
    )
    assert resp.status_code == 400


def test_transfer_fails_when_insufficient_balance(client):
    resp = client.post(
        "/api/capital/transfer",
        json={
            "asset": "USDT",
            "from_exchange": "binance",
            "to_exchange": "bybit",
            "amount": "999999999",
        },
    )
    assert resp.status_code == 400
