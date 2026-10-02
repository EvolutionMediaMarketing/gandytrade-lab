"""Saved backtest runs.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("summary", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
    )
    op.create_index("ix_backtest_runs_user_id", "backtest_runs", ["user_id"])
    op.create_index("ix_backtest_runs_created_at", "backtest_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("backtest_runs")
