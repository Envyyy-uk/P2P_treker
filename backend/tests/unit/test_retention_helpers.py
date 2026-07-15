"""Чисті хелпери партиціонування/downsampling (Фаза 2.1) — без БД."""

from app.database.retention import (
    bucket_start_ms,
    cutoff_ms,
    day_bounds_ms,
    day_starts_in_range,
    partition_name_for,
)

_DAY_MS = 24 * 60 * 60 * 1000


def test_day_bounds_ms_midnight_utc():
    # 2026-07-16T00:00:00Z
    start_of_day = 1784160000000
    start, end = day_bounds_ms(start_of_day)
    assert start == start_of_day
    assert end == start_of_day + _DAY_MS


def test_day_bounds_ms_middle_of_day():
    start_of_day = 1784160000000
    mid_day = start_of_day + 12 * 60 * 60 * 1000
    start, end = day_bounds_ms(mid_day)
    assert start == start_of_day
    assert end == start_of_day + _DAY_MS


def test_partition_name_for_matches_date():
    start_of_day = 1784160000000  # 2026-07-16T00:00:00Z
    assert partition_name_for(start_of_day) == "quotes_1s_20260716"


def test_day_starts_in_range_single_day():
    start_of_day = 1784160000000
    starts = day_starts_in_range(start_of_day, start_of_day + 1000)
    assert starts == [start_of_day]


def test_day_starts_in_range_spans_multiple_days():
    start_of_day = 1784160000000
    starts = day_starts_in_range(start_of_day, start_of_day + 2 * _DAY_MS + 1000)
    assert starts == [start_of_day, start_of_day + _DAY_MS, start_of_day + 2 * _DAY_MS]


def test_day_starts_in_range_empty_when_reversed():
    assert day_starts_in_range(2000, 1000) == []


def test_bucket_start_ms_10s():
    bucket_ms = 10_000
    assert bucket_start_ms(1_000_015_000, bucket_ms) == 1_000_010_000
    assert bucket_start_ms(1_000_010_000, bucket_ms) == 1_000_010_000  # exact boundary


def test_bucket_start_ms_1m():
    bucket_ms = 60_000
    assert bucket_start_ms(1_000_125_000, bucket_ms) == 1_000_080_000


def test_cutoff_ms():
    now = 1784160000000
    assert cutoff_ms(now, retention_days=7) == now - 7 * _DAY_MS
