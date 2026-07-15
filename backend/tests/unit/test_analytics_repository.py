"""AnalyticsRepository: чисті функції (без БД) — автовибір інтервалу,
уніфікація OHLC-рядків. SQL-логіка перевіряється окремим e2e-прогоном
проти реального Postgres (див. docs/phase-3/README.md), як і у Фазах 2/2.1."""

import pytest

from app.repositories.analytics import INTERVAL_MS, _row_to_ohlc, choose_interval


class TestChooseInterval:
    def test_explicit_request_wins_over_auto_selection(self):
        # Дуже короткий діапазон, але клієнт явно попросив 5m.
        assert choose_interval(0, 1000, max_points=2000, requested="5m") == "5m"

    def test_auto_picks_finest_interval_within_cap(self):
        span = 2000 * INTERVAL_MS["1s"]  # рівно межа для 1s при cap=2000
        assert choose_interval(0, span, max_points=2000, requested="auto") == "1s"

    def test_auto_escalates_to_coarser_interval_for_long_range(self):
        span = 5000 * INTERVAL_MS["1s"]  # забагато точок для 1s
        result = choose_interval(0, span, max_points=2000, requested="auto")
        assert result in ("10s", "1m", "5m")
        assert span // INTERVAL_MS[result] <= 2000

    def test_auto_falls_back_to_coarsest_when_even_5m_exceeds_cap(self):
        span = 365 * 24 * 60 * 60 * 1000  # рік
        assert choose_interval(0, span, max_points=100, requested="auto") == "5m"

    def test_none_requested_behaves_like_auto(self):
        span = 2000 * INTERVAL_MS["1s"]
        assert choose_interval(0, span, max_points=2000, requested=None) == "1s"

    def test_unknown_explicit_interval_raises(self):
        with pytest.raises(ValueError, match="Unknown interval"):
            choose_interval(0, 1000, max_points=2000, requested="3m")

    def test_zero_span_uses_finest_interval(self):
        assert choose_interval(1000, 1000, max_points=2000, requested="auto") == "1s"


class TestRowToOhlc:
    def test_raw_1s_row_collapses_to_single_point_ohlc(self):
        row = {"timestamp": 123, "bid_price": "100.5", "ask_price": "100.6"}
        point = _row_to_ohlc("1s", row)
        assert point["ts"] == 123
        assert point["open_bid"] == point["high_bid"] == point["low_bid"] == point["close_bid"]
        assert point["open_bid"] == "100.5"
        assert point["open_ask"] == point["close_ask"] == "100.6"
        assert point["sample_count"] == 1

    def test_downsample_row_passes_through_ohlc_fields(self):
        row = {
            "bucket_timestamp": 456,
            "open_bid": "1",
            "high_bid": "2",
            "low_bid": "0.5",
            "close_bid": "1.5",
            "open_ask": "1.1",
            "high_ask": "2.1",
            "low_ask": "0.6",
            "close_ask": "1.6",
            "sample_count": 10,
        }
        point = _row_to_ohlc("10s", row)
        assert point["ts"] == 456
        assert point["high_bid"] == "2"
        assert point["sample_count"] == 10
