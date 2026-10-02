"""Baseline: the tables as they were when migrations were introduced (Phase 1 + hardening).

Existing databases were built with create_all, so every table here is created only
if it's missing. A new database and the live one both end up identical.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _tables(md: sa.MetaData) -> None:
    sa.Table(
        "users", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("totp_secret", sa.String(64), nullable=False),
        sa.Column("totp_last_step", sa.BigInteger, nullable=False),
        sa.Column("failed_logins", sa.Integer, nullable=False),
        sa.Column("locked_until", TZ, nullable=True),
        sa.Column("created_at", TZ, nullable=False),
    )
    sa.Table(
        "login_sessions", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("last_active_at", TZ, nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("user_agent", sa.String(255), nullable=False),
    )
    sa.Table(
        "security_events", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", TZ, nullable=False, index=True),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("detail", sa.String(255), nullable=False),
    )
    sa.Table(
        "instruments", md,
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("asset_class", sa.String(16), nullable=False, index=True),
        sa.Column("provider", sa.String(16), nullable=False, index=True),
        sa.Column("provider_symbol", sa.String(32), nullable=False),
        sa.Column("precision", sa.Integer, nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    sa.Table(
        "favourites", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("added_at", TZ, nullable=False),
        sa.UniqueConstraint("user_id", "code", name="uq_favourite"),
    )
    sa.Table(
        "price_bars", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False, index=True),
        sa.Column("ts", sa.BigInteger, nullable=False, index=True),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.UniqueConstraint("source", "symbol", "timeframe", "ts", name="uq_price_bar"),
    )
    sa.Table(
        "fetch_state", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.UniqueConstraint("source", "symbol", "timeframe", name="uq_fetch_state"),
    )


def upgrade() -> None:
    md = sa.MetaData()
    _tables(md)
    md.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("The baseline can't be undone; restore a backup instead.")
