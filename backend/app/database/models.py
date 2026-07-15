"""ORM-моделі історії (Фаза 2, п.2).

Усі фінансові поля — Numeric (Decimal), timestamps — epoch ms (BigInteger).
Схема створюється ТІЛЬКИ через Alembic (migrations/versions).
"""

from decimal import Decimal

from sqlalchemy import BigInteger, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Запас точності для крипто-цін і кількостей.
_MONEY = Numeric(38, 18)


class Quote1s(Base):
    """Секундні snapshot'и top-of-book (стратегія: 1 запис/с на біржу+пару)."""

    __tablename__ = "quotes_1s"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # час семплу, ms
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(24), nullable=False)
    bid_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    bid_quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    ask_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    ask_quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    exchange_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quote_age_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_quotes_1s_symbol_ts", "symbol", "timestamp"),
        Index("ix_quotes_1s_exchange_symbol_ts", "exchange", "symbol", "timestamp"),
    )


class SpreadEvent(Base):
    """Закриті spread events: net_spread перетнув поріг вгору і повернувся.

    Правило versioning (PLAN.md, Фаза 2): рядки з попередньою
    calculation_version НІКОЛИ не перераховуються заднім числом.
    """

    __tablename__ = "spread_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    start_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(24), nullable=False)
    buy_exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    sell_exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    start_net_spread: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)  # частка
    max_net_spread: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    average_net_spread: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # Обсяг/прибуток у момент максимального net spread.
    executable_quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    executable_notional: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    estimated_profit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    threshold: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    calculation_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_spread_events_symbol_start", "symbol", "start_timestamp"),
        Index(
            "ix_spread_events_direction_start",
            "symbol",
            "buy_exchange",
            "sell_exchange",
            "start_timestamp",
        ),
    )
