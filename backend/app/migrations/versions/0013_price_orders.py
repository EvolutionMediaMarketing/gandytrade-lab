"""Paper price orders: buy or sell when the market reaches a chosen level.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("side", sa.Integer, nullable=False),
        sa.Column("level", sa.Float, nullable=False),
        sa.Column("direction", sa.Integer, nullable=False),
        sa.Column("stop", sa.Float, nullable=False),
        sa.Column("target", sa.Float, nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("placed_mid", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_ts", sa.BigInteger, nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("paper_trades.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trend", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("mood", sa.String(20), nullable=False),
        sa.Column("rule_flags", sa.JSON, nullable=False),
    )
    op.create_index("ix_price_orders_account_id", "price_orders", ["account_id"])
    op.create_index("ix_price_orders_symbol", "price_orders", ["symbol"])
    op.create_index("ix_price_orders_status", "price_orders", ["status"])


def downgrade() -> None:
    op.drop_table("price_orders")
