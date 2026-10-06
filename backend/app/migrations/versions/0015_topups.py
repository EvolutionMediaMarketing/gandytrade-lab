"""Monthly top-ups and deposits on paper accounts.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_accounts", sa.Column("topup_amount", sa.Float, nullable=False, server_default="0"))
    op.add_column("paper_accounts", sa.Column("topup_day", sa.Integer, nullable=False, server_default="1"))
    op.add_column("paper_accounts", sa.Column("topup_last_month", sa.String(7), nullable=False, server_default=""))
    op.create_table(
        "paper_deposits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_deposits_account_id", "paper_deposits", ["account_id"])


def downgrade() -> None:
    op.drop_table("paper_deposits")
    op.drop_column("paper_accounts", "topup_last_month")
    op.drop_column("paper_accounts", "topup_day")
    op.drop_column("paper_accounts", "topup_amount")
