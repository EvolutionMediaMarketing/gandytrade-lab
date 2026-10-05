"""Weekly reviews, and the new 'reviews' alert kind (switched on for anyone who already has alerts).

Revision ID: 0011
Revises: 0010
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week", sa.String(10), nullable=False),
        sa.Column("answers", sa.JSON, nullable=False),
        sa.Column("facts", sa.JSON, nullable=False),
        sa.Column("focus", sa.String(200), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "week", name="uq_weekly_review"),
    )
    op.create_index("ix_weekly_reviews_user_id", "weekly_reviews", ["user_id"])
    bind = op.get_bind()
    table = sa.table("alert_settings", sa.column("id", sa.Integer), sa.column("kinds", sa.JSON))
    for row in bind.execute(sa.select(table.c.id, table.c.kinds)).fetchall():
        kinds = row.kinds if isinstance(row.kinds, list) else json.loads(row.kinds or "[]")
        if "reviews" not in kinds:
            bind.execute(table.update().where(table.c.id == row.id).values(kinds=kinds + ["reviews"]))


def downgrade() -> None:
    op.drop_table("weekly_reviews")
