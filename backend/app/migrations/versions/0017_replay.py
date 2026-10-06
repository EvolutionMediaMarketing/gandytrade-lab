"""Market replay sessions.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("start_ts", sa.BigInteger, nullable=False),
        sa.Column("end_ts", sa.BigInteger, nullable=False),
        sa.Column("candles", sa.Integer, nullable=False),
        sa.Column("trades", sa.Integer, nullable=False),
        sa.Column("wins", sa.Integer, nullable=False),
        sa.Column("net_gbp", sa.Float, nullable=False),
        sa.Column("return_pct", sa.Float, nullable=False),
        sa.Column("buy_hold_pct", sa.Float, nullable=False),
        sa.Column("max_drawdown_pct", sa.Float, nullable=False),
        sa.Column("avg_r", sa.Float, nullable=True),
        sa.Column("lesson", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_sessions_user_id", "replay_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("replay_sessions")
