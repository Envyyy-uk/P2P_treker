"""Phase 2: quotes_1s and spread_events tables

Revision ID: c151c86d6651
Revises:
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c151c86d6651"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(38, 18)


def upgrade() -> None:
    op.create_table(
        "quotes_1s",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_type", sa.String(length=24), nullable=False),
        sa.Column("bid_price", _MONEY, nullable=False),
        sa.Column("bid_quantity", _MONEY, nullable=False),
        sa.Column("ask_price", _MONEY, nullable=False),
        sa.Column("ask_quantity", _MONEY, nullable=False),
        sa.Column("exchange_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("received_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("quote_age_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quotes_1s_symbol_ts", "quotes_1s", ["symbol", "timestamp"], unique=False
    )
    op.create_index(
        "ix_quotes_1s_exchange_symbol_ts",
        "quotes_1s",
        ["exchange", "symbol", "timestamp"],
        unique=False,
    )

    op.create_table(
        "spread_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("start_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("end_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_type", sa.String(length=24), nullable=False),
        sa.Column("buy_exchange", sa.String(length=16), nullable=False),
        sa.Column("sell_exchange", sa.String(length=16), nullable=False),
        sa.Column("start_net_spread", _MONEY, nullable=False),
        sa.Column("max_net_spread", _MONEY, nullable=False),
        sa.Column("average_net_spread", _MONEY, nullable=False),
        sa.Column("executable_quantity", _MONEY, nullable=False),
        sa.Column("executable_notional", _MONEY, nullable=False),
        sa.Column("estimated_profit", _MONEY, nullable=False),
        sa.Column("threshold", _MONEY, nullable=False),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_spread_events_symbol_start",
        "spread_events",
        ["symbol", "start_timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_spread_events_direction_start",
        "spread_events",
        ["symbol", "buy_exchange", "sell_exchange", "start_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_spread_events_direction_start", table_name="spread_events")
    op.drop_index("ix_spread_events_symbol_start", table_name="spread_events")
    op.drop_table("spread_events")
    op.drop_index("ix_quotes_1s_exchange_symbol_ts", table_name="quotes_1s")
    op.drop_index("ix_quotes_1s_symbol_ts", table_name="quotes_1s")
    op.drop_table("quotes_1s")
