"""Таблиця відповідності символів між біржами (Фаза 0, п.2–3).

Канонічний формат платформи: "BASE-QUOTE", напр. "BTC-USDT".
"""

from app.models.enums import Exchange

# Пари MVP (Spot). Ключ — канонічний символ, значення — нативний символ біржі.
SYMBOL_MAP: dict[str, dict[Exchange, str]] = {
    "BTC-USDT": {
        Exchange.BINANCE: "BTCUSDT",
        Exchange.BYBIT: "BTCUSDT",
        Exchange.OKX: "BTC-USDT",
    },
    "ETH-USDT": {
        Exchange.BINANCE: "ETHUSDT",
        Exchange.BYBIT: "ETHUSDT",
        Exchange.OKX: "ETH-USDT",
    },
    "SOL-USDT": {
        Exchange.BINANCE: "SOLUSDT",
        Exchange.BYBIT: "SOLUSDT",
        Exchange.OKX: "SOL-USDT",
    },
    "BNB-USDT": {
        Exchange.BINANCE: "BNBUSDT",
        Exchange.BYBIT: "BNBUSDT",
        Exchange.OKX: "BNB-USDT",
    },
    "XRP-USDT": {
        Exchange.BINANCE: "XRPUSDT",
        Exchange.BYBIT: "XRPUSDT",
        Exchange.OKX: "XRP-USDT",
    },
}

# Зворотний індекс: (біржа, нативний символ) -> канонічний символ.
NATIVE_TO_CANONICAL: dict[tuple[Exchange, str], str] = {
    (exchange, native): canonical
    for canonical, mapping in SYMBOL_MAP.items()
    for exchange, native in mapping.items()
}


def to_native(canonical_symbol: str, exchange: Exchange) -> str:
    """Канонічний символ -> нативний символ біржі."""
    try:
        return SYMBOL_MAP[canonical_symbol][exchange]
    except KeyError as exc:
        raise KeyError(f"No mapping for {canonical_symbol!r} on {exchange.value}") from exc


def to_canonical(native_symbol: str, exchange: Exchange) -> str:
    """Нативний символ біржі -> канонічний символ."""
    try:
        return NATIVE_TO_CANONICAL[(exchange, native_symbol)]
    except KeyError as exc:
        raise KeyError(f"Unknown native symbol {native_symbol!r} on {exchange.value}") from exc
