"""Keep each replay's trades, so it can be looked at again.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("replay_sessions", sa.Column("trades_detail", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("replay_sessions", "trades_detail")
