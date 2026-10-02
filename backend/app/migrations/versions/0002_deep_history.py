"""Remember when long price history was downloaded for backtests.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fetch_state") as batch:
        batch.add_column(sa.Column("deep_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fetch_state") as batch:
        batch.drop_column("deep_fetched_at")
