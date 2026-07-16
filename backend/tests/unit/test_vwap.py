"""VWAP і slippage по глибині стакана (Фаза 4, п.2–3)."""

from decimal import Decimal

import pytest

from app.orderbook.book import BookLevel
from app.orderbook.vwap import buy_slippage_pct, compute_vwap, sell_slippage_pct

D = Decimal


def levels(*pairs):
    return [BookLevel(D(p), D(q)) for p, q in pairs]


class TestComputeVwap:
    def test_single_level_fully_covers_target(self):
        result = compute_vwap(levels(("100", "5")), D("2"))
        assert result.vwap_price == D("100")
        assert result.filled_quantity == D("2")
        assert result.notional == D("200")
        assert result.fully_filled

    def test_walks_multiple_levels(self):
        result = compute_vwap(levels(("100", "1"), ("101", "1")), D("2"))
        assert result.filled_quantity == D("2")
        assert result.notional == D("201")
        assert result.vwap_price == D("100.5")
        assert result.fully_filled

    def test_partial_fill_when_book_exhausted(self):
        result = compute_vwap(levels(("100", "1")), D("5"))
        assert result.filled_quantity == D("1")
        assert not result.fully_filled

    def test_empty_book_returns_none_price(self):
        result = compute_vwap([], D("1"))
        assert result.vwap_price is None
        assert result.filled_quantity == 0
        assert not result.fully_filled

    def test_exact_boundary_across_levels(self):
        result = compute_vwap(levels(("100", "2"), ("101", "3")), D("5"))
        assert result.filled_quantity == D("5")
        assert result.fully_filled
        assert result.notional == D("2") * D("100") + D("3") * D("101")

    def test_zero_target_quantity_rejected(self):
        with pytest.raises(ValueError):
            compute_vwap(levels(("100", "1")), D("0"))

    def test_negative_target_quantity_rejected(self):
        with pytest.raises(ValueError):
            compute_vwap(levels(("100", "1")), D("-1"))

    def test_very_small_quantity_precision(self):
        result = compute_vwap(levels(("63781.20", "1.14")), D("0.00000001"))
        assert result.filled_quantity == D("0.00000001")
        assert result.fully_filled


class TestSlippage:
    def test_buy_slippage_positive_when_vwap_worse(self):
        pct = buy_slippage_pct(top_ask=D("100"), vwap_price=D("101"))
        assert pct == D("1")  # 1%

    def test_buy_slippage_zero_when_no_movement(self):
        assert buy_slippage_pct(D("100"), D("100")) == 0

    def test_sell_slippage_positive_when_vwap_worse(self):
        pct = sell_slippage_pct(top_bid=D("100"), vwap_price=D("99"))
        assert pct == D("1")

    def test_sell_slippage_zero_when_no_movement(self):
        assert sell_slippage_pct(D("100"), D("100")) == 0

    def test_buy_slippage_rejects_non_positive_top(self):
        with pytest.raises(ValueError):
            buy_slippage_pct(D("0"), D("100"))

    def test_sell_slippage_rejects_non_positive_top(self):
        with pytest.raises(ValueError):
            sell_slippage_pct(D("0"), D("100"))
