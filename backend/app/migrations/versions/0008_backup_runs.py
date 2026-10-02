"""Record of nightly backups.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("restore_tested", sa.Boolean, nullable=False),
        sa.Column("uploaded", sa.Boolean, nullable=False),
        sa.Column("detail", sa.String(255), nullable=False),
    )
    op.create_index("ix_backup_runs_at", "backup_runs", ["at"])


def downgrade() -> None:
    op.drop_table("backup_runs")
