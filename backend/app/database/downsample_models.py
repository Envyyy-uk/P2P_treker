"""ORM-моделі downsample-таблиць (Фаза 2.1, п.4): 10с / 1хв / 5хв.

Кожен рівень будується прямою агрегацією з `quotes_1s` (не каскадно одне
з одного) — простіше й достатньо для обсягів MVP. OHLC на bid/ask +
середній вік котирування в бакеті.
"""

from decimal import Decimal

from sqlalchemy import BigInteger, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

_MONEY = Numeric(38, 18)


class _QuotesDownsampleMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(24), nullable=False)
    open_bid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    high_bid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    low_bid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    close_bid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    open_ask: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    high_ask: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    low_ask: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    close_ask: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    avg_bid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    avg_ask: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    avg_quote_age_ms: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)


class Quote10s(_QuotesDownsampleMixin, Base):
    __tablename__ = "quotes_10s"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "market_type", "bucket_timestamp", name="uq_quotes_10s_bucket"
        ),
        Index("ix_quotes_10s_symbol_ts", "symbol", "bucket_timestamp"),
    )


class Quote1m(_QuotesDownsampleMixin, Base):
    __tablename__ = "quotes_1m"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "market_type", "bucket_timestamp", name="uq_quotes_1m_bucket"
        ),
        Index("ix_quotes_1m_symbol_ts", "symbol", "bucket_timestamp"),
    )


class Quote5m(_QuotesDownsampleMixin, Base):
    __tablename__ = "quotes_5m"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "market_type", "bucket_timestamp", name="uq_quotes_5m_bucket"
        ),
        Index("ix_quotes_5m_symbol_ts", "symbol", "bucket_timestamp"),
    )
