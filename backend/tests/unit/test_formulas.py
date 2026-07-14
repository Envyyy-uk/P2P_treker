"""Юніт-тести формул Фази 0 (сценарії — з Фази 1, п.8 плану)."""

from decimal import Decimal

import pytest

from app.core.exceptions import MarketTypeMismatchError
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.spread import formulas

D = Decimal


def make_quote(**overrides):
    defaults = dict(
        exchange=Exchange.BINANCE,
        market_type=MarketType.SPOT,
        symbol="BTC-USDT",
        bid_price=D("63780.10"),
        bid_quantity=D("0.82"),
        ask_price=D("63781.20"),
        ask_quantity=D("1.14"),
        exchange_timestamp=1_784_041_200_123,
        received_timestamp=1_784_041_200_141,
        sequence=1,
    )
    defaults.update(overrides)
    return NormalizedQuote(**defaults)


class TestGrossSpread:
    def test_equal_prices_give_zero(self):
        assert formulas.gross_spread(D("100"), D("100")) == 0

    def test_positive_spread(self):
        assert formulas.gross_spread(D("100"), D("101")) == D("0.01")

    def test_negative_spread(self):
        assert formulas.gross_spread(D("100"), D("99")) == D("-0.01")

    def test_zero_buy_ask_rejected(self):
        with pytest.raises(ValueError):
            formulas.gross_spread(D("0"), D("100"))


class TestNetSpread:
    def test_plan_formula(self):
        # net = 101 * (1 - 0.001) / (100 * (1 + 0.001)) - 1
        result = formulas.net_spread(D("100"), D("101"), D("0.001"), D("0.001"))
        expected = D("101") * D("0.999") / (D("100") * D("1.001")) - 1
        assert result == expected

    def test_spread_smaller_than_fees_is_negative(self):
        result = formulas.net_spread(D("100"), D("100.05"), D("0.001"), D("0.001"))
        assert result < 0

    def test_spread_larger_than_fees_is_positive(self):
        result = formulas.net_spread(D("100"), D("101"), D("0.001"), D("0.001"))
        assert result > 0

    def test_zero_fees_equals_gross(self):
        assert formulas.net_spread(D("100"), D("101"), D("0"), D("0")) == formulas.gross_spread(
            D("100"), D("101")
        )

    def test_negative_fee_rejected(self):
        with pytest.raises(ValueError):
            formulas.net_spread(D("100"), D("101"), D("-0.001"), D("0"))

    def test_equal_prices_with_fees_negative(self):
        assert formulas.net_spread(D("100"), D("100"), D("0.001"), D("0.001")) < 0

    def test_decimal_precision_no_float_artifacts(self):
        # Дуже велика ціна × дуже мала кількість — Decimal тримає точність
        result = formulas.net_spread(
            D("99999999.99"), D("100000001.01"), D("0.00075"), D("0.00075")
        )
        assert isinstance(result, Decimal)

    def test_very_small_quantities(self):
        qty = formulas.executable_quantity(D("0.00000001"), D("0.00000002"))
        assert qty == D("0.00000001")


class TestVolumes:
    def test_executable_quantity_is_min(self):
        assert formulas.executable_quantity(D("0.5"), D("0.42")) == D("0.42")

    def test_zero_quantity(self):
        assert formulas.executable_quantity(D("0"), D("1")) == 0

    def test_notional(self):
        assert formulas.executable_notional(D("0.5"), D("60000")) == D("30000")

    def test_expected_gross_profit(self):
        assert formulas.expected_gross_profit(D("2"), D("100"), D("101")) == D("2")

    def test_expected_net_profit_sign_matches_net_spread(self):
        profit = formulas.expected_net_profit(D("1"), D("100"), D("100.05"), D("0.001"), D("0.001"))
        assert profit < 0


class TestComparability:
    def test_different_market_types_rejected(self):
        spot = make_quote()
        futures = make_quote(exchange=Exchange.BYBIT, market_type=MarketType.PERPETUAL_FUTURES)
        with pytest.raises(MarketTypeMismatchError):
            formulas.ensure_comparable(spot, futures)

    def test_different_symbols_rejected(self):
        a = make_quote()
        b = make_quote(exchange=Exchange.BYBIT, symbol="ETH-USDT")
        with pytest.raises(MarketTypeMismatchError):
            formulas.ensure_comparable(a, b)

    def test_same_type_and_symbol_ok(self):
        a = make_quote()
        b = make_quote(exchange=Exchange.BYBIT)
        formulas.ensure_comparable(a, b)


class TestFreshness:
    def test_stale_quote_detected(self):
        q = make_quote(received_timestamp=1_000_000)
        assert q.is_stale(now_ms=1_001_001, max_quote_age_ms=1000)
        assert not q.is_stale(now_ms=1_001_000, max_quote_age_ms=1000)

    def test_timestamp_mismatch(self):
        a = make_quote(exchange_timestamp=1_000_000)
        b = make_quote(exchange=Exchange.BYBIT, exchange_timestamp=1_002_000)
        assert not formulas.timestamps_aligned(a, b, max_diff_ms=1500)
        assert formulas.timestamps_aligned(a, b, max_diff_ms=2000)
