"""News alerts: the lookups made (for the daily allowance) and the stories already sent.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_lookups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("feed", sa.String(60), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("found", sa.Integer, nullable=False),
        sa.Column("error", sa.String(200), nullable=False),
    )
    op.create_index("ix_news_lookups_feed", "news_lookups", ["feed"])
    op.create_index("ix_news_lookups_at", "news_lookups", ["at"])
    op.create_table(
        "news_seen",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("news_seen")
    op.drop_table("news_lookups")
