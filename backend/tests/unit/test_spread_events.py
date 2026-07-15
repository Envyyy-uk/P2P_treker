"""SpreadEventTracker: детектор порогових подій (Фаза 2/3, визначення events)."""

from dataclasses import replace
from decimal import Decimal

from app.models.enums import Exchange, MarketType
from app.spread.engine import SpreadRow
from app.spread.events import SpreadEventTracker

D = Decimal


def make_row(net_pct: str, valid=True, symbol="BTC-USDT", **overrides) -> SpreadRow:
    defaults = dict(
        symbol=symbol,
        market_type=MarketType.SPOT,
        buy_exchange=Exchange.BINANCE,
        sell_exchange=Exchange.BYBIT,
        buy_price=D("100"),
        sell_price=D("101"),
        gross_spread_pct=D(net_pct),
        net_spread_pct=D(net_pct),
        executable_quantity=D("1"),
        executable_notional=D("100"),
        expected_net_profit=D(net_pct) / 100 * 100,
        quote_age_ms=10,
        timestamp_diff_ms=10,
        stale=False,
        valid=valid,
    )
    defaults.update(overrides)
    return SpreadRow(**defaults)


def test_crossing_threshold_opens_event():
    tracker = SpreadEventTracker(threshold=D("0.001"))  # 0.1%
    closed = tracker.process([make_row("0.05")], now_ms=1000)  # below threshold
    assert closed == []
    assert tracker.open_count == 0

    closed = tracker.process([make_row("0.2")], now_ms=2000)  # crosses up
    assert closed == []
    assert tracker.open_count == 1


def test_dropping_below_threshold_closes_event():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.2")], now_ms=1000)
    closed = tracker.process([make_row("0.05")], now_ms=1500)
    assert len(closed) == 1
    event = closed[0]
    assert event["start_timestamp"] == 1000
    assert event["end_timestamp"] == 1500
    assert tracker.open_count == 0


def test_invalid_row_closes_event_even_above_threshold():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.2")], now_ms=1000)
    closed = tracker.process([make_row("0.5", valid=False)], now_ms=1500)
    assert len(closed) == 1


def test_max_and_average_net_spread_tracked():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.1")], now_ms=1000)
    tracker.process([make_row("0.3")], now_ms=1100)  # new max
    tracker.process([make_row("0.2")], now_ms=1200)
    closed = tracker.process([make_row("0.05")], now_ms=1300)
    event = closed[0]
    assert event["start_net_spread"] == D("0.001")  # 0.1% -> частка
    assert event["max_net_spread"] == D("0.003")
    assert event["average_net_spread"] == (D("0.001") + D("0.003") + D("0.002")) / 3


def test_peak_volume_and_profit_captured_at_max():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    row1 = make_row("0.1", executable_quantity=D("1"), executable_notional=D("100"))
    row2 = make_row("0.3", executable_quantity=D("5"), executable_notional=D("500"))
    tracker.process([row1], now_ms=1000)
    tracker.process([row2], now_ms=1100)
    closed = tracker.process([make_row("0.05")], now_ms=1200)
    event = closed[0]
    assert event["executable_quantity"] == D("5")
    assert event["executable_notional"] == D("500")


def test_disappearing_direction_closes_event():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.2")], now_ms=1000)
    closed = tracker.process([], now_ms=2000)  # напрямок зник зі зрізу
    assert len(closed) == 1
    assert tracker.open_count == 0


def test_multiple_directions_tracked_independently():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    row_a = make_row("0.2", buy_exchange=Exchange.BINANCE, sell_exchange=Exchange.BYBIT)
    row_b = make_row("0.2", buy_exchange=Exchange.BYBIT, sell_exchange=Exchange.BINANCE)
    tracker.process([row_a, row_b], now_ms=1000)
    assert tracker.open_count == 2
    row_a_dropped = replace(row_a, net_spread_pct=D("0.05"), gross_spread_pct=D("0.05"))
    closed = tracker.process([row_a_dropped, row_b], now_ms=1500)
    assert len(closed) == 1
    assert tracker.open_count == 1


def test_flush_open_closes_all_pending():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.2")], now_ms=1000)
    events = tracker.flush_open(now_ms=5000)
    assert len(events) == 1
    assert events[0]["end_timestamp"] == 5000
    assert tracker.open_count == 0


def test_calculation_version_carried_through():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    tracker.process([make_row("0.2", calculation_version=1)], now_ms=1000)
    closed = tracker.process([make_row("0.05")], now_ms=1100)
    assert closed[0]["calculation_version"] == 1


def test_no_open_event_below_threshold_produces_nothing():
    tracker = SpreadEventTracker(threshold=D("0.001"))
    for i in range(5):
        closed = tracker.process([make_row("0.02")], now_ms=1000 + i * 100)
        assert closed == []
    assert tracker.open_count == 0
