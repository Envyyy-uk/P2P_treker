from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import (
    Environment,
    ExchangeConfig,
    LoggingConfig,
    Settings,
    TradingConfig,
)
from app.models.enums import Exchange, MarketType


def test_default_settings_valid():
    s = Settings(_env_file=None)
    assert s.environment is Environment.DEV
    assert s.trading.market_type is MarketType.SPOT
    assert len(s.trading.symbols) == 5
    assert s.trading.max_quote_age_ms == 1000
    assert isinstance(s.exchanges[Exchange.BINANCE].taker_fee, Decimal)


def test_non_spot_market_rejected():
    with pytest.raises(ValidationError, match="only spot"):
        TradingConfig(market_type=MarketType.PERPETUAL_FUTURES)


def test_unmapped_symbol_rejected():
    with pytest.raises(ValidationError, match="without exchange mapping"):
        TradingConfig(symbols=["DOGE-USDT"])


def test_empty_symbols_rejected():
    with pytest.raises(ValidationError):
        TradingConfig(symbols=[])


def test_requires_two_enabled_exchanges():
    exchanges = {
        Exchange.BINANCE: ExchangeConfig(enabled=True),
        Exchange.BYBIT: ExchangeConfig(enabled=False),
        Exchange.OKX: ExchangeConfig(enabled=False),
    }
    with pytest.raises(ValidationError, match="two enabled exchanges"):
        Settings(_env_file=None, exchanges=exchanges)


def test_production_cannot_disable_masking():
    with pytest.raises(ValidationError, match="masking"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            logging=LoggingConfig(mask_secrets=False),
        )


def test_nested_env_override(monkeypatch):
    monkeypatch.setenv("TRADING__MAX_QUOTE_AGE_MS", "2000")
    monkeypatch.setenv("EXCHANGES__BINANCE__TAKER_FEE", "0.00075")
    s = Settings(_env_file=None)
    assert s.trading.max_quote_age_ms == 2000
    assert s.exchanges[Exchange.BINANCE].taker_fee == Decimal("0.00075")


def test_api_secret_not_exposed_in_repr():
    cfg = ExchangeConfig(api_key="k", api_secret="verysecret")  # type: ignore[arg-type]
    assert "verysecret" not in repr(cfg)
    assert "verysecret" not in str(cfg)
