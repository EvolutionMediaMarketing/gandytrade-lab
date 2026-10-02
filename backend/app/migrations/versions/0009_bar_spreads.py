"""Recorded bid/ask spread on cached price candles (OANDA, short timeframes).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_bars") as batch:
        batch.add_column(sa.Column("spread", sa.Float, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("price_bars") as batch:
        batch.drop_column("spread")
