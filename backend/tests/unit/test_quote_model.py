from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote


def base_kwargs(**overrides):
    kwargs = dict(
        exchange=Exchange.BINANCE,
        market_type=MarketType.SPOT,
        symbol="BTC-USDT",
        bid_price="63780.10",
        bid_quantity="0.82",
        ask_price="63781.20",
        ask_quantity="1.14",
        exchange_timestamp=1_784_041_200_123,
        received_timestamp=1_784_041_200_141,
        sequence=123456,
    )
    kwargs.update(overrides)
    return kwargs


def test_prices_parsed_from_strings_as_decimal():
    q = NormalizedQuote(**base_kwargs())
    assert q.bid_price == Decimal("63780.10")
    assert isinstance(q.ask_quantity, Decimal)


def test_float_prices_rejected():
    with pytest.raises(ValidationError, match="float is forbidden"):
        NormalizedQuote(**base_kwargs(bid_price=63780.10))


def test_non_positive_price_rejected():
    with pytest.raises(ValidationError):
        NormalizedQuote(**base_kwargs(ask_price="0"))


def test_negative_quantity_rejected():
    with pytest.raises(ValidationError):
        NormalizedQuote(**base_kwargs(bid_quantity="-1"))


def test_zero_quantity_allowed():
    q = NormalizedQuote(**base_kwargs(bid_quantity="0"))
    assert q.bid_quantity == 0


def test_quote_is_immutable():
    q = NormalizedQuote(**base_kwargs())
    with pytest.raises(ValidationError):
        q.bid_price = Decimal("1")  # type: ignore[misc]


def test_quote_age():
    q = NormalizedQuote(**base_kwargs())
    assert q.quote_age_ms(now_ms=q.received_timestamp + 120) == 120
