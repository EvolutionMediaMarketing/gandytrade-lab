"""Automatic paper trading: strategy runs, and a link from each paper trade to the run that opened it.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("params", sa.JSON, nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_bar_ts", sa.BigInteger, nullable=False),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message", sa.String(255), nullable=False),
        sa.Column("errors", sa.Integer, nullable=False),
        sa.Column("backtest", sa.JSON, nullable=False),
    )
    op.create_index("ix_auto_runs_user_id", "auto_runs", ["user_id"])
    op.create_index("ix_auto_runs_account_id", "auto_runs", ["account_id"])
    op.create_index("ix_auto_runs_status", "auto_runs", ["status"])
    with op.batch_alter_table("paper_trades") as batch:
        batch.add_column(sa.Column("auto_run_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_paper_trades_auto_run_id", "auto_runs", ["auto_run_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_paper_trades_auto_run_id", ["auto_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("paper_trades") as batch:
        batch.drop_index("ix_paper_trades_auto_run_id")
        batch.drop_constraint("fk_paper_trades_auto_run_id", type_="foreignkey")
        batch.drop_column("auto_run_id")
    op.drop_table("auto_runs")
