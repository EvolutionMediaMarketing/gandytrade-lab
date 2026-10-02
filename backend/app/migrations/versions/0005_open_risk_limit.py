"""Open-risk limit per paper account (default 10% of the account).

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paper_accounts") as batch:
        batch.add_column(sa.Column("max_open_risk_pct", sa.Float, nullable=False, server_default="10"))


def downgrade() -> None:
    with op.batch_alter_table("paper_accounts") as batch:
        batch.drop_column("max_open_risk_pct")
