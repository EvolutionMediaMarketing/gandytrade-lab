"""Database tables."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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
