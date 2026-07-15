"""Analytics API routes: параметри, валідація, серіалізація — з фейковим
репозиторієм (без реальної БД). SQL-коректність AnalyticsRepository
перевірена окремо e2e проти реального Postgres (docs/phase-3/README.md)."""

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@dataclass
class FakeQuoteResult:
    interval: str
    points: list
    truncated: bool


@dataclass
class FakeStats:
    total_count: int = 10
    qualifying_count: int = 8
    pct_meeting_min_duration: Decimal | None = Decimal("80")
    total_duration_ms: int = 40000
    average_duration_ms: Decimal | None = Decimal("5000")
    median_duration_ms: Decimal | None = Decimal("4500")
    max_duration_ms: int | None = 9000
    average_net_spread_pct: Decimal | None = Decimal("0.15")
    max_net_spread_pct: Decimal | None = Decimal("0.4")
    average_executable_quantity: Decimal | None = Decimal("0.5")
    average_estimated_profit: Decimal | None = Decimal("1.23")


class FakeAnalyticsRepository:
    def __init__(self):
        self.last_call: dict = {}

    async def quote_history(self, **kwargs):
        self.last_call = {"method": "quote_history", **kwargs}
        return FakeQuoteResult(
            interval=kwargs["interval"],
            points=[{"ts": 1, "open_bid": Decimal("100"), "close_bid": Decimal("100.5")}],
            truncated=False,
        )

    async def spread_history(self, **kwargs):
        self.last_call = {"method": "spread_history", **kwargs}
        return FakeQuoteResult(
            interval=kwargs["interval"],
            points=[
                {
                    "ts": 1,
                    "buy_price": Decimal("100"),
                    "sell_price": Decimal("101"),
                    "gross_spread_pct": Decimal("1.0"),
                    "net_spread_pct": Decimal("0.8"),
                }
            ],
            truncated=False,
        )

    async def list_spread_events(self, *, page, page_size, **filters):
        self.last_call = {
            "method": "list_spread_events",
            "page": page,
            "page_size": page_size,
            **filters,
        }
        events = [{"symbol": "BTC-USDT", "start_net_spread": Decimal("0.002")}]
        return events, 1

    async def spread_event_stats(self, **filters):
        self.last_call = {"method": "spread_event_stats", **filters}
        return FakeStats()

    async def export_spread_events(self, **filters):
        self.last_call = {"method": "export_spread_events", **filters}
        return [
            {"symbol": "BTC-USDT", "buy_exchange": "binance", "start_net_spread": Decimal("0.002")}
        ]


@pytest.fixture
def client_with_fake_repo(monkeypatch):
    monkeypatch.setenv("LIVE_ADAPTERS_ENABLED", "false")
    monkeypatch.setenv("DATABASE__ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    fake_repo = FakeAnalyticsRepository()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                app.state.analytics_repo = fake_repo
                yield client, fake_repo
    finally:
        get_settings.cache_clear()


def test_quotes_endpoint_serializes_decimal_as_string(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get(
        "/api/analytics/quotes",
        params={"exchange": "binance", "symbol": "BTC-USDT", "from": 0, "to": 10_000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"][0]["open_bid"] == "100"
    assert isinstance(body["points"][0]["close_bid"], str)


def test_quotes_endpoint_rejects_inverted_range(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get(
        "/api/analytics/quotes",
        params={"exchange": "binance", "symbol": "BTC-USDT", "from": 1000, "to": 500},
    )
    assert resp.status_code == 400


def test_quotes_endpoint_rejects_unknown_interval(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get(
        "/api/analytics/quotes",
        params={
            "exchange": "binance",
            "symbol": "BTC-USDT",
            "from": 0,
            "to": 10_000,
            "interval": "3m",
        },
    )
    assert resp.status_code == 400


def test_spread_history_rejects_same_exchange_pair(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get(
        "/api/analytics/spread-history",
        params={
            "buy_exchange": "binance",
            "sell_exchange": "binance",
            "symbol": "BTC-USDT",
            "from": 0,
            "to": 10_000,
        },
    )
    assert resp.status_code == 400


def test_spread_history_passes_current_fees_and_threshold(client_with_fake_repo):
    client, repo = client_with_fake_repo
    resp = client.get(
        "/api/analytics/spread-history",
        params={
            "buy_exchange": "binance",
            "sell_exchange": "bybit",
            "symbol": "BTC-USDT",
            "from": 0,
            "to": 10_000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "threshold_pct" in body
    assert repo.last_call["buy_fee"] > 0


def test_spread_events_list_applies_default_page_size(client_with_fake_repo):
    client, repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert body["page"] == 1
    assert repo.last_call["page_size"] > 0


def test_spread_events_list_caps_page_size_at_max(client_with_fake_repo):
    client, repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events", params={"page_size": 999_999})
    assert resp.status_code == 200
    from app.core.config import get_settings

    assert repo.last_call["page_size"] == get_settings().analytics.max_page_size


def test_spread_events_list_default_min_duration_applied(client_with_fake_repo):
    client, repo = client_with_fake_repo
    client.get("/api/analytics/spread-events")
    from app.core.config import get_settings

    expected = get_settings().analytics.default_min_event_duration_ms
    assert repo.last_call["min_duration_ms"] == expected


def test_spread_events_list_explicit_min_duration_overrides_default(client_with_fake_repo):
    client, repo = client_with_fake_repo
    client.get("/api/analytics/spread-events", params={"min_duration_ms": 0})
    assert repo.last_call["min_duration_ms"] == 0


def test_spread_events_stats_endpoint(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 10
    assert body["pct_meeting_min_duration"] == "80"
    assert body["median_duration_ms"] == "4500"


def test_export_json_default_format(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["start_net_spread"] == "0.002"


def test_export_csv_format(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events/export", params={"format": "csv"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "start_net_spread" in resp.text
    assert "0.002" in resp.text


def test_export_rejects_invalid_format(client_with_fake_repo):
    client, _repo = client_with_fake_repo
    resp = client.get("/api/analytics/spread-events/export", params={"format": "xml"})
    assert resp.status_code == 422


def test_analytics_returns_503_when_db_disabled_and_no_repo():
    # Без fixture, тобто analytics_repo лишається None (реальний lifespan-шлях).
    import os

    os.environ["LIVE_ADAPTERS_ENABLED"] = "false"
    os.environ["DATABASE__ENABLED"] = "false"
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/analytics/quotes",
                    params={"exchange": "binance", "symbol": "BTC-USDT", "from": 0, "to": 1000},
                )
        assert resp.status_code == 503
    finally:
        get_settings.cache_clear()
        os.environ.pop("LIVE_ADAPTERS_ENABLED", None)
        os.environ.pop("DATABASE__ENABLED", None)
