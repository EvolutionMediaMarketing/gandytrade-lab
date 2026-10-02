"""Paper trading: accounts, trades (with journal and rule score) and their event log.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("starting_balance", sa.Float, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("deposits", sa.Float, nullable=False),
        sa.Column("risk_pct", sa.Float, nullable=False),
        sa.Column("daily_loss_pct", sa.Float, nullable=False),
        sa.Column("max_drawdown_pct", sa.Float, nullable=False),
        sa.Column("peak_equity", sa.Float, nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("day_start_equity", sa.Float, nullable=False),
        sa.Column("halted", sa.Boolean, nullable=False),
        sa.Column("halt_reason", sa.String(255), nullable=False),
        sa.Column("archived", sa.Boolean, nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_paper_accounts_user_id", "paper_accounts", ["user_id"])
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("side", sa.Integer, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("units", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("entry_mid", sa.Float, nullable=False),
        sa.Column("entry_quote_ts", sa.BigInteger, nullable=False),
        sa.Column("entry_time", TZ, nullable=False),
        sa.Column("entry_rate", sa.Float, nullable=False),
        sa.Column("entry_fees", sa.Float, nullable=False),
        sa.Column("stop", sa.Float, nullable=False),
        sa.Column("initial_stop", sa.Float, nullable=False),
        sa.Column("target", sa.Float, nullable=True),
        sa.Column("risk_gbp", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("exit_mid", sa.Float, nullable=True),
        sa.Column("exit_quote_ts", sa.BigInteger, nullable=True),
        sa.Column("exit_time", TZ, nullable=True),
        sa.Column("exit_reason", sa.String(80), nullable=False),
        sa.Column("pnl_gbp", sa.Float, nullable=True),
        sa.Column("costs_gbp", sa.Float, nullable=True),
        sa.Column("last_checked_ts", sa.BigInteger, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("trend", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("mood", sa.String(20), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False),
        sa.Column("lesson", sa.String(500), nullable=False),
        sa.Column("rule_flags", sa.JSON, nullable=False),
        sa.Column("rule_score", sa.Integer, nullable=True),
    )
    op.create_index("ix_paper_trades_account_id", "paper_trades", ["account_id"])
    op.create_index("ix_paper_trades_status", "paper_trades", ["status"])
    op.create_table(
        "paper_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("paper_trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", TZ, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("mid", sa.Float, nullable=True),
        sa.Column("quote_ts", sa.BigInteger, nullable=True),
        sa.Column("quote_source", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(255), nullable=False),
    )
    op.create_index("ix_paper_events_trade_id", "paper_events", ["trade_id"])


def downgrade() -> None:
    op.drop_table("paper_events")
    op.drop_table("paper_trades")
    op.drop_table("paper_accounts")
