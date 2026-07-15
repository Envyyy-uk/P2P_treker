"""Phase 2.1: partition quotes_1s by day, add downsample tables

Revision ID: 9bd1a8fa90b4
Revises: c151c86d6651
Create Date: 2026-07-16

quotes_1s stayed a plain table in the Phase 2 migration; this revision
converts it to a RANGE-partitioned table (partition key: timestamp, ms)
so daily partitions can be created/dropped cheaply for retention (plan,
Phase 2.1, п.1). Existing rows are preserved via rename -> recreate ->
copy -> drop. A DEFAULT partition catches any row outside the daily
partitions the application has created so far (safety net).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9bd1a8fa90b4"
down_revision: str | None = "c151c86d6651"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(38, 18)


def _downsample_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_type", sa.String(length=24), nullable=False),
        sa.Column("open_bid", _MONEY, nullable=False),
        sa.Column("high_bid", _MONEY, nullable=False),
        sa.Column("low_bid", _MONEY, nullable=False),
        sa.Column("close_bid", _MONEY, nullable=False),
        sa.Column("open_ask", _MONEY, nullable=False),
        sa.Column("high_ask", _MONEY, nullable=False),
        sa.Column("low_ask", _MONEY, nullable=False),
        sa.Column("close_ask", _MONEY, nullable=False),
        sa.Column("avg_bid", _MONEY, nullable=False),
        sa.Column("avg_ask", _MONEY, nullable=False),
        sa.Column("avg_quote_age_ms", _MONEY, nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange", "symbol", "market_type", "bucket_timestamp", name=f"uq_{name}_bucket"
        ),
    )
    op.create_index(f"ix_{name}_symbol_ts", name, ["symbol", "bucket_timestamp"], unique=False)


def upgrade() -> None:
    # 1. Partition quotes_1s by RANGE(timestamp). Existing (dev-only) data is
    #    preserved through rename -> recreate partitioned -> copy -> drop.
    op.rename_table("quotes_1s", "quotes_1s_unpartitioned")
    # Index names don't follow a RENAME TABLE — drop them so the new
    # partitioned quotes_1s can reuse the same names.
    op.drop_index("ix_quotes_1s_symbol_ts", table_name="quotes_1s_unpartitioned")
    op.drop_index("ix_quotes_1s_exchange_symbol_ts", table_name="quotes_1s_unpartitioned")

    op.execute(
        """
        CREATE TABLE quotes_1s (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            timestamp BIGINT NOT NULL,
            exchange VARCHAR(16) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            market_type VARCHAR(24) NOT NULL,
            bid_price NUMERIC(38,18) NOT NULL,
            bid_quantity NUMERIC(38,18) NOT NULL,
            ask_price NUMERIC(38,18) NOT NULL,
            ask_quantity NUMERIC(38,18) NOT NULL,
            exchange_timestamp BIGINT NOT NULL,
            received_timestamp BIGINT NOT NULL,
            quote_age_ms INTEGER NOT NULL,
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
        """
    )
    # Default partition: safety net for rows outside app-managed daily
    # partitions (e.g. before the app's first ensure_partitions() run).
    op.execute("CREATE TABLE quotes_1s_default PARTITION OF quotes_1s DEFAULT")

    # Indexes on the parent propagate to every partition automatically.
    op.execute("CREATE INDEX ix_quotes_1s_symbol_ts ON quotes_1s (symbol, timestamp)")
    op.execute(
        "CREATE INDEX ix_quotes_1s_exchange_symbol_ts ON quotes_1s (exchange, symbol, timestamp)"
    )

    op.execute(
        """
        INSERT INTO quotes_1s (
            timestamp, exchange, symbol, market_type, bid_price, bid_quantity,
            ask_price, ask_quantity, exchange_timestamp, received_timestamp, quote_age_ms
        )
        SELECT
            timestamp, exchange, symbol, market_type, bid_price, bid_quantity,
            ask_price, ask_quantity, exchange_timestamp, received_timestamp, quote_age_ms
        FROM quotes_1s_unpartitioned
        """
    )
    op.drop_table("quotes_1s_unpartitioned")

    # 2. Downsample tables (Фаза 2.1, п.4): 10s / 1m / 5m.
    _downsample_table("quotes_10s")
    _downsample_table("quotes_1m")
    _downsample_table("quotes_5m")


def downgrade() -> None:
    op.drop_index("ix_quotes_5m_symbol_ts", table_name="quotes_5m")
    op.drop_table("quotes_5m")
    op.drop_index("ix_quotes_1m_symbol_ts", table_name="quotes_1m")
    op.drop_table("quotes_1m")
    op.drop_index("ix_quotes_10s_symbol_ts", table_name="quotes_10s")
    op.drop_table("quotes_10s")

    op.execute(
        """
        CREATE TABLE quotes_1s_flat (
            id BIGSERIAL PRIMARY KEY,
            timestamp BIGINT NOT NULL,
            exchange VARCHAR(16) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            market_type VARCHAR(24) NOT NULL,
            bid_price NUMERIC(38,18) NOT NULL,
            bid_quantity NUMERIC(38,18) NOT NULL,
            ask_price NUMERIC(38,18) NOT NULL,
            ask_quantity NUMERIC(38,18) NOT NULL,
            exchange_timestamp BIGINT NOT NULL,
            received_timestamp BIGINT NOT NULL,
            quote_age_ms INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO quotes_1s_flat (
            timestamp, exchange, symbol, market_type, bid_price, bid_quantity,
            ask_price, ask_quantity, exchange_timestamp, received_timestamp, quote_age_ms
        )
        SELECT
            timestamp, exchange, symbol, market_type, bid_price, bid_quantity,
            ask_price, ask_quantity, exchange_timestamp, received_timestamp, quote_age_ms
        FROM quotes_1s
        """
    )
    op.drop_table("quotes_1s")  # drops all partitions too
    op.rename_table("quotes_1s_flat", "quotes_1s")
    op.create_index("ix_quotes_1s_symbol_ts", "quotes_1s", ["symbol", "timestamp"], unique=False)
    op.create_index(
        "ix_quotes_1s_exchange_symbol_ts",
        "quotes_1s",
        ["exchange", "symbol", "timestamp"],
        unique=False,
    )
