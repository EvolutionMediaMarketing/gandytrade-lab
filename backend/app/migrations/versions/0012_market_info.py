"""Saved market background for the chart's hover card: company details, Wikipedia summary, headlines.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_info",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("profile", sa.JSON, nullable=True),
        sa.Column("profile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wiki", sa.JSON, nullable=True),
        sa.Column("wiki_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("news", sa.JSON, nullable=True),
        sa.Column("news_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("market_info")
