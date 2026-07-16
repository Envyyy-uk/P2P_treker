"""Торгові обмеження: tick/step size, min qty/notional (Фаза 4, п.4)."""

from decimal import Decimal

import pytest

from app.paper_trading.rules import SymbolRules, round_to_step, round_to_tick, validate_order

D = Decimal


def make_rules(**overrides):
    defaults = dict(
        tick_size=D("0.01"), step_size=D("0.001"), min_quantity=D("0.001"), min_notional=D("10")
    )
    defaults.update(overrides)
    return SymbolRules(**defaults)


class TestRounding:
    def test_round_to_tick_exact_multiple_unchanged(self):
        assert round_to_tick(D("100.05"), D("0.01")) == D("100.05")

    def test_round_to_tick_rounds_down(self):
        assert round_to_tick(D("100.057"), D("0.01")) == D("100.05")

    def test_round_to_step_rounds_down(self):
        assert round_to_step(D("1.2349"), D("0.001")) == D("1.234")

    def test_round_to_tick_rejects_non_positive(self):
        with pytest.raises(ValueError):
            round_to_tick(D("100"), D("0"))

    def test_round_to_step_rejects_non_positive(self):
        with pytest.raises(ValueError):
            round_to_step(D("1"), D("-0.001"))


class TestValidateOrder:
    def test_valid_order_passes(self):
        rules = make_rules()
        result = validate_order(D("1"), D("100.00"), rules)
        assert result.valid
        assert result.violations == []

    def test_below_min_quantity_rejected(self):
        rules = make_rules(min_quantity=D("0.01"))
        result = validate_order(D("0.001"), D("100"), rules)
        assert not result.valid
        assert any("min_quantity" in v for v in result.violations)

    def test_below_min_notional_rejected(self):
        rules = make_rules(min_notional=D("1000"))
        result = validate_order(D("1"), D("100"), rules)
        assert not result.valid
        assert any("min_notional" in v for v in result.violations)

    def test_quantity_not_aligned_to_step_rejected(self):
        rules = make_rules(step_size=D("0.01"), min_quantity=D("0"), min_notional=D("0"))
        result = validate_order(D("1.005"), D("100"), rules)
        assert not result.valid
        assert any("step_size" in v for v in result.violations)

    def test_price_not_aligned_to_tick_rejected(self):
        rules = make_rules(min_quantity=D("0"), min_notional=D("0"))
        result = validate_order(D("1"), D("100.001"), rules)
        assert not result.valid
        assert any("tick_size" in v for v in result.violations)

    def test_zero_quantity_rejected(self):
        rules = make_rules()
        result = validate_order(D("0"), D("100"), rules)
        assert not result.valid

    def test_negative_price_rejected(self):
        rules = make_rules()
        result = validate_order(D("1"), D("-1"), rules)
        assert not result.valid

    def test_multiple_violations_all_reported(self):
        rules = make_rules(min_quantity=D("10"), min_notional=D("10000"))
        result = validate_order(D("0.001"), D("100"), rules)
        assert not result.valid
        assert len(result.violations) >= 2
