import pytest

from app.core.symbols import SYMBOL_MAP, to_canonical, to_native
from app.models.enums import Exchange


def test_all_symbols_mapped_for_all_exchanges():
    for canonical, mapping in SYMBOL_MAP.items():
        assert set(mapping) == set(Exchange), f"{canonical} lacks mapping for some exchange"


def test_mvp_has_five_to_ten_pairs():
    assert 5 <= len(SYMBOL_MAP) <= 10


def test_to_native_examples_from_plan():
    assert to_native("BTC-USDT", Exchange.BINANCE) == "BTCUSDT"
    assert to_native("BTC-USDT", Exchange.BYBIT) == "BTCUSDT"
    assert to_native("BTC-USDT", Exchange.OKX) == "BTC-USDT"


def test_roundtrip_native_canonical():
    for canonical, mapping in SYMBOL_MAP.items():
        for exchange, native in mapping.items():
            assert to_canonical(native, exchange) == canonical


def test_unknown_symbol_raises():
    with pytest.raises(KeyError):
        to_native("DOGE-USDT", Exchange.BINANCE)
    with pytest.raises(KeyError):
        to_canonical("DOGEUSDT", Exchange.BINANCE)
