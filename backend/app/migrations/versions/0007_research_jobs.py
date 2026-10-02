"""Strategy research scans.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("automatic", sa.Boolean, nullable=False),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("todo", sa.JSON, nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("done", sa.Integer, nullable=False),
        sa.Column("rows", sa.JSON, nullable=False),
        sa.Column("skipped", sa.JSON, nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_jobs_user_id", "research_jobs", ["user_id"])
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("research_jobs")
