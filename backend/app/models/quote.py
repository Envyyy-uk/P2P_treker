"""Єдина модель котирування для всіх бірж (Фаза 0, п.8).

Усі ціни та кількості — Decimal. Float у фінансових полях заборонений.
Timestamps — epoch milliseconds (int).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import Exchange, MarketType


class NormalizedQuote(BaseModel):
    """Top-of-book котирування у канонічному форматі платформи."""

    model_config = ConfigDict(frozen=True)

    exchange: Exchange
    market_type: MarketType
    symbol: str  # канонічний символ, напр. "BTC-USDT"
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    exchange_timestamp: int  # ms, час події на біржі
    received_timestamp: int  # ms, час отримання нами
    sequence: int | None = None

    @field_validator("bid_price", "ask_price", "bid_quantity", "ask_quantity", mode="before")
    @classmethod
    def _reject_float(cls, v: object) -> object:
        # Float втрачає точність ще до потрапляння в Decimal — приймаємо
        # тільки str/int/Decimal (біржі віддають ціни рядками).
        if isinstance(v, float):
            raise ValueError("float is forbidden for financial fields; pass str or Decimal")
        return v

    @field_validator("bid_price", "ask_price")
    @classmethod
    def _positive_price(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("price must be positive")
        return v

    @field_validator("bid_quantity", "ask_quantity")
    @classmethod
    def _non_negative_quantity(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("quantity must be non-negative")
        return v

    def quote_age_ms(self, now_ms: int) -> int:
        """Вік котирування відносно моменту отримання."""
        return now_ms - self.received_timestamp

    def is_stale(self, now_ms: int, max_quote_age_ms: int) -> bool:
        return self.quote_age_ms(now_ms) > max_quote_age_ms
