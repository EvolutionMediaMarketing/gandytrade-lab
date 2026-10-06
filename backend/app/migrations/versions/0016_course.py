"""12-week course progress.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quiz_score", sa.Integer, nullable=False),
        sa.Column("quiz_passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(4000), nullable=False),
        sa.UniqueConstraint("user_id", "week", name="uq_course_progress_user_week"),
    )
    op.create_index("ix_course_progress_user_id", "course_progress", ["user_id"])


def downgrade() -> None:
    op.drop_table("course_progress")
