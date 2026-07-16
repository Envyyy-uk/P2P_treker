"""Backtest API route: параметри, валідація, серіалізація — з фейковим
двигуном (без реальної БД). Коректність самого BacktestEngine перевірена
окремо e2e проти реального Postgres (docs/phase-3.1/README.md)."""

from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.backtesting.engine import DISCLAIMER
from app.main import app


@dataclass
class FakeBacktestResult:
    params: object
    ticks_processed: int = 100
    truncated: bool = False
    total_events: int = 2
    events: list = field(
        default_factory=lambda: [
            {"start_timestamp": 1000, "end_timestamp": 2000, "estimated_profit": Decimal("0.5")}
        ]
    )
    total_simulated_pnl: Decimal = Decimal("0.5")
    average_pnl_per_event: Decimal | None = Decimal("0.25")
    disclaimer: str = DISCLAIMER


class FakeBacktestEngine:
    def __init__(self):
        self.last_params = None

    async def run(self, params):
        self.last_params = params
        return FakeBacktestResult(params=params)


@pytest.fixture
def client_with_fake_engine(monkeypatch):
    monkeypatch.setenv("LIVE_ADAPTERS_ENABLED", "false")
    monkeypatch.setenv("DATABASE__ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    fake_engine = FakeBacktestEngine()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                app.state.backtest_engine = fake_engine
                yield client, fake_engine
    finally:
        get_settings.cache_clear()


def test_run_backtest_returns_serialized_result(client_with_fake_engine):
    client, _engine = client_with_fake_engine
    resp = client.post(
        "/api/backtest/run",
        json={"symbols": ["BTC-USDT"], "from": 1000, "to": 2000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_simulated_pnl"] == "0.5"
    assert body["average_pnl_per_event"] == "0.25"
    assert body["events"][0]["estimated_profit"] == "0.5"
    assert body["disclaimer"] == DISCLAIMER


def test_run_backtest_passes_experimental_params(client_with_fake_engine):
    client, engine = client_with_fake_engine
    resp = client.post(
        "/api/backtest/run",
        json={
            "symbols": ["BTC-USDT"],
            "from": 1000,
            "to": 2000,
            "spread_threshold": "0.002",
            "min_duration_ms": 500,
            "min_executable_notional": "50",
            "fee_overrides": {"binance": "0.0002"},
        },
    )
    assert resp.status_code == 200
    assert engine.last_params.spread_threshold == Decimal("0.002")
    assert engine.last_params.min_duration_ms == 500
    assert engine.last_params.min_executable_notional == Decimal("50")


def test_run_backtest_rejects_inverted_range(client_with_fake_engine):
    client, _engine = client_with_fake_engine
    resp = client.post(
        "/api/backtest/run",
        json={"symbols": ["BTC-USDT"], "from": 2000, "to": 1000},
    )
    assert resp.status_code == 400


def test_run_backtest_rejects_unknown_symbol(client_with_fake_engine):
    client, _engine = client_with_fake_engine
    resp = client.post(
        "/api/backtest/run",
        json={"symbols": ["DOGE-USDT"], "from": 1000, "to": 2000},
    )
    assert resp.status_code == 400


def test_run_backtest_returns_503_when_db_disabled():
    import os

    os.environ["LIVE_ADAPTERS_ENABLED"] = "false"
    os.environ["DATABASE__ENABLED"] = "false"
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/backtest/run",
                    json={"symbols": ["BTC-USDT"], "from": 1000, "to": 2000},
                )
        assert resp.status_code == 503
    finally:
        get_settings.cache_clear()
        os.environ.pop("LIVE_ADAPTERS_ENABLED", None)
        os.environ.pop("DATABASE__ENABLED", None)
