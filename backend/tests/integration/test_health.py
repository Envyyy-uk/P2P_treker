from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_reports_clock_drift():
    with patch("app.core.time_sync._query_offset_ms", return_value=12.5):
        with TestClient(app) as client:
            response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Spread Monitor MVP"
    assert body["clock_drift_ms"] == 12.5


def test_liveness():
    with patch("app.core.time_sync._query_offset_ms", return_value=0.0):
        with TestClient(app) as client:
            assert client.get("/health/live").json() == {"status": "alive"}
