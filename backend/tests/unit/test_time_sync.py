from unittest.mock import patch

import pytest

from app.core.exceptions import ClockDriftError
from app.core.time_sync import check_clock_drift_on_startup, measure_clock_drift


async def test_first_reachable_server_wins():
    def fake_query(server, timeout_s):
        if server == "bad.example":
            raise OSError("unreachable")
        return 42.0

    with patch("app.core.time_sync._query_offset_ms", side_effect=fake_query):
        result = await measure_clock_drift(["bad.example", "good.example"], timeout_s=1)
    assert result.server == "good.example"
    assert result.offset_ms == 42.0


async def test_all_servers_down_returns_unknown():
    with patch("app.core.time_sync._query_offset_ms", side_effect=OSError("down")):
        result = await measure_clock_drift(["a", "b"], timeout_s=1)
    assert not result.known


async def test_startup_fails_on_excessive_drift():
    with patch("app.core.time_sync._query_offset_ms", return_value=900.0):
        with pytest.raises(ClockDriftError):
            await check_clock_drift_on_startup(
                servers=["x"], max_drift_ms=500, fail_on_drift=True, timeout_s=1
            )


async def test_startup_tolerates_drift_when_configured():
    with patch("app.core.time_sync._query_offset_ms", return_value=-900.0):
        result = await check_clock_drift_on_startup(
            servers=["x"], max_drift_ms=500, fail_on_drift=False, timeout_s=1
        )
    assert result.offset_ms == -900.0


async def test_startup_does_not_block_when_ntp_unreachable():
    with patch("app.core.time_sync._query_offset_ms", side_effect=OSError("down")):
        result = await check_clock_drift_on_startup(
            servers=["x"], max_drift_ms=500, fail_on_drift=True, timeout_s=1
        )
    assert not result.known
