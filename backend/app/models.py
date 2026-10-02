"""Database tables."""

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # The last accepted two-factor time step, so a code can't be reused.
    totp_last_step: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    """A signed-in browser. Deleting the row signs that browser out immediately."""

    __tablename__ = "login_sessions"

    # SHA-256 of the random token held in the browser's cookie; the token itself is never stored.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class SecurityEvent(Base):
    """Append-only record of sign-ins, failures and account changes."""

    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event: Mapped[str] = mapped_column(String(48))
    username: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")


class Instrument(Base):
    """Every market the free data feeds offer, refreshed weekly from each provider's list."""

    __tablename__ = "instruments"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # our code, e.g. EUR_USD or AAPL
    name: Mapped[str] = mapped_column(String(160))
    asset_class: Mapped[str] = mapped_column(String(16), index=True)  # forex|metal|commodity|index|bond|stock|etf|ukstock
    provider: Mapped[str] = mapped_column(String(16), index=True)  # oanda|twelvedata
    provider_symbol: Mapped[str] = mapped_column(String(32))
    precision: Mapped[int] = mapped_column(Integer, default=2)
    exchange: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favourite(Base):
    """A market you've starred. Stored on the server so it follows you between devices."""

    __tablename__ = "favourites"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_favourite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BacktestRun(Base):
    """A saved backtest: the settings used and the full result, so it can be reopened and compared."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    strategy: Mapped[str] = mapped_column(String(40))
    summary: Mapped[dict] = mapped_column(JSON)  # headline numbers, for the list of past runs
    result: Mapped[dict] = mapped_column(JSON)  # everything the results page shows


class PriceBar(Base):
    """Cached price history, so data is only downloaded once."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("source", "symbol", "timeframe", "ts", name="uq_price_bar"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)  # bar open time, Unix seconds UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)


class FetchState(Base):
    """When each symbol and timeframe was last refreshed from its provider."""

    __tablename__ = "fetch_state"
    __table_args__ = (UniqueConstraint("source", "symbol", "timeframe", name="uq_fetch_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When the long history (up to 5,000 bars) was last downloaded for backtests.
    deep_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaperAccount(Base):
    """A pretend-money account. Each is either real shares (no leverage) or CFD/spread bet."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(8))  # cash | cfd
    starting_balance: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)  # realised balance in GBP (excludes open trades)
    deposits: Mapped[float] = mapped_column(Float, default=0.0)  # top-ups added after the start
    risk_pct: Mapped[float] = mapped_column(Float, default=1.0)
    daily_loss_pct: Mapped[float] = mapped_column(Float, default=3.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=20.0)
    # Most the account can have at risk at once: the total lost if every open trade hit its stop-loss.
    max_open_risk_pct: Mapped[float] = mapped_column(Float, default=10.0)
    peak_equity: Mapped[float] = mapped_column(Float)
    day: Mapped[str] = mapped_column(String(10), default="")  # UK date the day-start figures belong to
    day_start_equity: Mapped[float] = mapped_column(Float, default=0.0)
    halted: Mapped[bool] = mapped_column(default=False)
    halt_reason: Mapped[str] = mapped_column(String(255), default="")
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaperTrade(Base):
    """One paper trade from entry to exit, with its journal entry and rule score."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8), default="")
    side: Mapped[int] = mapped_column(Integer)  # +1 buy, -1 short
    status: Mapped[str] = mapped_column(String(10), index=True)  # open | closed
    units: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)  # fill, including spread and slippage
    entry_mid: Mapped[float] = mapped_column(Float)  # the market price recorded at that moment
    entry_quote_ts: Mapped[int] = mapped_column(BigInteger)  # time of that recorded price
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entry_rate: Mapped[float] = mapped_column(Float, default=1.0)  # price-currency units per £1 at entry
    entry_fees: Mapped[float] = mapped_column(Float, default=0.0)
    stop: Mapped[float] = mapped_column(Float)
    initial_stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_gbp: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_quote_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(80), default="")
    pnl_gbp: Mapped[float | None] = mapped_column(Float, nullable=True)
    costs_gbp: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_ts: Mapped[int] = mapped_column(BigInteger, default=0)  # newest candle checked for stop/target
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | strategy
    strategy: Mapped[str] = mapped_column(String(40), default="")
    # Journal and pre-trade checklist
    trend: Mapped[str] = mapped_column(String(10), default="")  # up | down | sideways
    reason: Mapped[str] = mapped_column(String(300), default="")
    mood: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(String(2000), default="")
    lesson: Mapped[str] = mapped_column(String(500), default="")
    rule_flags: Mapped[list] = mapped_column(JSON, default=list)  # rules broken, in plain words
    rule_score: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PaperEvent(Base):
    """Every fill and change, with the market price recorded at that moment (the Phase 3 gate checks these)."""

    __tablename__ = "paper_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("paper_trades.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20))  # opened | stop | target | closed | stop_moved | target_moved
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # fill price, if any
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)  # market price used
    quote_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # time of that market price
    quote_source: Mapped[str] = mapped_column(String(16), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")
