"""Спільні enum-типи платформи.

Правило плану: різні market types ніколи не порівнюються між собою.
MVP працює тільки зі Spot.
"""

from enum import StrEnum


class Exchange(StrEnum):
    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"


class MarketType(StrEnum):
    SPOT = "spot"
    # Зарезервовано на майбутнє; MVP їх не використовує.
    PERPETUAL_FUTURES = "perpetual_futures"
    DELIVERY_FUTURES = "delivery_futures"
    INVERSE_FUTURES = "inverse_futures"
