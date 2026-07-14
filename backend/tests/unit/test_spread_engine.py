"""Юніт-тести Spread Engine — сценарії з плану (Фаза 1, п.8)."""

from decimal import Decimal

import pytest

from app.core.config import ExchangeConfig, Settings, TradingConfig
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache
from app.spread.engine import SpreadEngine
from app.spread.formulas import CALCULATION_VERSION

D = Decimal
NOW = 1_784_041_200_500


def make_settings(**trading_overrides) -> Settings:
    trading = TradingConfig(
        symbols=["BTC-USDT"],
        max_quote_age_ms=1000,
        max_timestamp_diff_ms=1500,
        min_executable_quantity=D("0"),
        min_executable_notional=D("10"),
        **trading_overrides,
    )
    return Settings(
        _env_file=None,
        trading=trading,
        exchanges={
            Exchange.BINANCE: ExchangeConfig(taker_fee=D("0.001")),
            Exchange.BYBIT: ExchangeConfig(taker_fee=D("0.001")),
            Exchange.OKX: ExchangeConfig(taker_fee=D("0.001")),
        },
    )


def make_quote(
    exchange=Exchange.BINANCE,
    bid="63780.10",
    bid_qty="0.82",
    ask="63781.20",
    ask_qty="1.14",
    exchange_ts=NOW - 100,
    received_ts=NOW - 100,
    symbol="BTC-USDT",
):
    return NormalizedQuote(
        exchange=exchange,
        market_type=MarketType.SPOT,
        symbol=symbol,
        bid_price=bid,
        bid_quantity=bid_qty,
        ask_price=ask,
        ask_quantity=ask_qty,
        exchange_timestamp=exchange_ts,
        received_timestamp=received_ts,
        sequence=1,
    )


def engine_with(*quotes, settings=None) -> SpreadEngine:
    cache = QuoteCache()
    for q in quotes:
        cache.update(q)
    return SpreadEngine(cache, settings or make_settings())


def rows_by_direction(rows):
    return {(r.buy_exchange, r.sell_exchange): r for r in rows}


def test_both_directions_for_each_pair():
    engine = engine_with(
        make_quote(Exchange.BINANCE),
        make_quote(Exchange.BYBIT),
        make_quote(Exchange.OKX),
    )
    rows = engine.compute_all(NOW)
    # 3 біржі -> 6 напрямків (план, Фаза 1, п.6)
    assert len(rows) == 6
    directions = rows_by_direction(rows)
    assert (Exchange.BINANCE, Exchange.BYBIT) in directions
    assert (Exchange.BYBIT, Exchange.BINANCE) in directions


def test_direction_uses_buy_ask_and_sell_bid():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="101"),
        make_quote(Exchange.BYBIT, bid="103", ask="104"),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.buy_price == D("101")  # купуємо по ask
    assert row.sell_price == D("103")  # продаємо по bid


def test_equal_prices_negative_net():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100"),
        make_quote(Exchange.BYBIT, bid="100", ask="100"),
    )
    for row in engine.compute_all(NOW):
        assert row.gross_spread_pct == 0
        assert row.net_spread_pct < 0


def test_spread_larger_than_fees_positive_and_valid():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100.1", ask_qty="1"),
        make_quote(Exchange.BYBIT, bid="101", ask="101.1", bid_qty="1"),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.net_spread_pct > 0
    assert row.valid
    assert row.expected_net_profit > 0


def test_spread_smaller_than_fees_negative_but_reported():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100.00"),
        make_quote(Exchange.BYBIT, bid="100.05", ask="100.06"),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.gross_spread_pct > 0
    assert row.net_spread_pct < 0


def test_zero_volume_invalid():
    engine = engine_with(
        make_quote(Exchange.BINANCE, ask_qty="0"),
        make_quote(Exchange.BYBIT),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.executable_quantity == 0
    assert not row.valid


def test_notional_below_threshold_invalid():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100.1", ask_qty="0.01"),
        make_quote(Exchange.BYBIT, bid="101", ask="101.1", bid_qty="0.01"),
    )
    # notional = 0.01 * 100.1 ≈ 1 < min 10
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert not row.valid


def test_missing_exchange_quote_no_rows_for_it():
    engine = engine_with(make_quote(Exchange.BINANCE))
    assert engine.compute_all(NOW) == []


def test_stale_quote_marked_and_invalid():
    engine = engine_with(
        make_quote(Exchange.BINANCE, received_ts=NOW - 5000, exchange_ts=NOW - 5000),
        make_quote(Exchange.BYBIT),
    )
    for row in engine.compute_all(NOW):
        assert row.stale
        assert not row.valid


def test_timestamp_mismatch_invalid_but_not_stale():
    engine = engine_with(
        make_quote(Exchange.BINANCE, exchange_ts=NOW - 100, received_ts=NOW - 100),
        make_quote(Exchange.BYBIT, exchange_ts=NOW - 2000, received_ts=NOW - 100),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert not row.stale
    assert row.timestamp_diff_ms == 1900
    assert not row.valid


def test_executable_quantity_is_min_of_sides():
    engine = engine_with(
        make_quote(Exchange.BINANCE, ask_qty="0.5"),
        make_quote(Exchange.BYBIT, bid_qty="0.42"),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.executable_quantity == D("0.42")


def test_very_large_price_and_small_quantity_decimal_exact():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="99999999.98", ask="99999999.99", ask_qty="0.00000001"),
        make_quote(Exchange.BYBIT, bid="100000001.01", ask="100000001.02", bid_qty="0.00000002"),
    )
    row = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert row.executable_quantity == D("0.00000001")
    assert row.executable_notional == D("0.9999999999")
    assert isinstance(row.net_spread_pct, D)


def test_rows_carry_calculation_version():
    engine = engine_with(make_quote(Exchange.BINANCE), make_quote(Exchange.BYBIT))
    for row in engine.compute_all(NOW):
        assert row.calculation_version == CALCULATION_VERSION


def test_update_taker_fee_changes_result():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100"),
        make_quote(Exchange.BYBIT, bid="101", ask="101"),
    )
    before = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    engine.update_taker_fee(Exchange.BINANCE, D("0.005"))
    after = rows_by_direction(engine.compute_all(NOW))[(Exchange.BINANCE, Exchange.BYBIT)]
    assert after.net_spread_pct < before.net_spread_pct
    with pytest.raises(ValueError):
        engine.update_taker_fee(Exchange.BINANCE, D("-0.001"))


def test_to_wire_serializes_decimals_as_strings():
    engine = engine_with(
        make_quote(Exchange.BINANCE, bid="100", ask="100.1", ask_qty="1"),
        make_quote(Exchange.BYBIT, bid="101", ask="101.1", bid_qty="1"),
    )
    wire = engine.compute_all(NOW)[0].to_wire()
    assert isinstance(wire["buy_price"], str)
    assert isinstance(wire["net_spread_pct"], str)
    assert wire["market_type"] == "spot"
    # 4 знаки після коми у відсотках
    assert len(wire["net_spread_pct"].split(".")[-1]) == 4
