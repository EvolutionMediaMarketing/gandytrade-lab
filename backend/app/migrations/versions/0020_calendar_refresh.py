"""Economic calendar dates found on official schedule pages, and the last check of each.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_dates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("series", sa.String(12), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("tentative", sa.Boolean, nullable=False),
        sa.Column("found_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("series", "day", name="uq_calendar_date"),
    )
    op.create_index("ix_calendar_dates_series", "calendar_dates", ["series"])
    op.create_table(
        "calendar_checks",
        sa.Column("series", sa.String(12), primary_key=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("found", sa.Integer, nullable=False),
        sa.Column("added", sa.Integer, nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("calendar_checks")
    op.drop_table("calendar_dates")
