"""BacktestParams: валідація вхідних параметрів (без БД)."""

from decimal import Decimal

import pytest

from app.backtesting.engine import BacktestParams
from app.models.enums import Exchange, MarketType


def make_params(**overrides):
    defaults = dict(symbols=["BTC-USDT"], from_ms=1000, to_ms=2000)
    defaults.update(overrides)
    return BacktestParams(**defaults)


class TestBacktestParamsValidation:
    def test_valid_params_construct_cleanly(self):
        params = make_params()
        assert params.symbols == ["BTC-USDT"]
        assert params.market_type is MarketType.SPOT
        assert params.min_duration_ms == 0
        assert params.fee_overrides == {}

    def test_to_ms_must_be_after_from_ms(self):
        with pytest.raises(ValueError, match="'to_ms' must be greater"):
            make_params(from_ms=2000, to_ms=1000)

    def test_to_ms_equal_from_ms_rejected(self):
        with pytest.raises(ValueError, match="'to_ms' must be greater"):
            make_params(from_ms=1000, to_ms=1000)

    def test_unknown_symbol_rejected(self):
        with pytest.raises(ValueError, match="without exchange mapping"):
            make_params(symbols=["DOGE-USDT"])

    def test_empty_symbols_rejected(self):
        with pytest.raises(ValueError, match="At least one symbol"):
            make_params(symbols=[])

    def test_non_spot_market_type_rejected(self):
        with pytest.raises(ValueError, match="only spot market"):
            make_params(market_type=MarketType.PERPETUAL_FUTURES)

    def test_optional_overrides_default_to_none(self):
        params = make_params()
        assert params.spread_threshold is None
        assert params.min_executable_quantity is None
        assert params.min_executable_notional is None

    def test_fee_overrides_accepted(self):
        params = make_params(fee_overrides={Exchange.BINANCE: Decimal("0.0005")})
        assert params.fee_overrides[Exchange.BINANCE] == Decimal("0.0005")

    def test_params_are_frozen(self):
        params = make_params()
        with pytest.raises(AttributeError):
            params.from_ms = 5000  # type: ignore[misc]
