"""Trailing stops on paper trades and price orders.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_trades", sa.Column("trail_distance", sa.Float, nullable=True))
    op.add_column("paper_trades", sa.Column("trail_peak", sa.Float, nullable=True))
    op.add_column("price_orders", sa.Column("trail_distance", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("price_orders", "trail_distance")
    op.drop_column("paper_trades", "trail_peak")
    op.drop_column("paper_trades", "trail_distance")
