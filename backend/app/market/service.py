"""Get price bars: from the database cache, refreshed from the provider when stale."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import FetchState, PriceBar
from .providers import alphavantage, oanda, sample, twelvedata
from .providers.base import Bar, ProviderError
from .symbols import Symbol
from .timeframes import Timeframe, refresh_after_seconds

MAX_BARS = 2000
MAX_HISTORY = 5000
DEEP_REFRESH_EVERY = timedelta(days=30)


@dataclass
class BarsResult:
    bars: list[Bar]
    source: str
    sample: bool = False
    stale: bool = False
    warnings: list[str] = field(default_factory=list)


KEY_NAMES = {"oanda": "OANDA", "twelvedata": "Twelve Data", "alphavantage": "Alpha Vantage"}


def _provider_key(symbol: Symbol) -> str:
    settings = get_settings()
    return {
        "oanda": settings.oanda_token,
        "twelvedata": settings.twelvedata_key,
        "alphavantage": settings.alphavantage_key,
    }.get(symbol.provider, "")


def _fetch_from_provider(symbol: Symbol, tf: Timeframe, count: int) -> list[Bar]:
    key = _provider_key(symbol)
    if symbol.provider == "oanda":
        return oanda.fetch_candles(key, symbol, tf, count)
    if symbol.provider == "alphavantage":
        return alphavantage.fetch_candles(key, symbol, tf, count)
    return twelvedata.fetch_candles(key, symbol, tf, count)


def _upsert(db: Session, symbol: Symbol, tf: Timeframe, bars: list[Bar]) -> None:
    if not bars:
        return
    existing = {
        row.ts: row
        for row in db.scalars(
            select(PriceBar).where(
                PriceBar.source == symbol.provider,
                PriceBar.symbol == symbol.code,
                PriceBar.timeframe == tf.code,
                PriceBar.ts >= bars[0].ts,
            )
        )
    }
    for b in bars:
        row = existing.get(b.ts)
        if row is None:
            db.add(
                PriceBar(
                    source=symbol.provider,
                    symbol=symbol.code,
                    timeframe=tf.code,
                    ts=b.ts,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
            )
        else:  # the latest bar is still forming, so update it
            row.open, row.high, row.low, row.close, row.volume = b.open, b.high, b.low, b.close, b.volume


def _read_cache(db: Session, symbol: Symbol, tf: Timeframe, limit: int) -> list[Bar]:
    rows = db.scalars(
        select(PriceBar)
        .where(
            PriceBar.source == symbol.provider,
            PriceBar.symbol == symbol.code,
            PriceBar.timeframe == tf.code,
        )
        .order_by(PriceBar.ts.desc())
        .limit(limit)
    ).all()
    return [Bar(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in reversed(rows)]


def _refresh(db: Session, symbol: Symbol, tf: Timeframe, count: int, deep: bool, result: BarsResult) -> None:
    """Fetch from the provider into the cache; problems become warnings and saved prices are used."""
    state = db.scalar(
        select(FetchState).where(
            FetchState.source == symbol.provider,
            FetchState.symbol == symbol.code,
            FetchState.timeframe == tf.code,
        )
    )
    now = datetime.now(timezone.utc)
    fetched_at = _aware(state.fetched_at) if state else None
    deep_at = _aware(state.deep_fetched_at) if state and state.deep_fetched_at else None
    if deep:
        due = deep_at is None or now - deep_at > DEEP_REFRESH_EVERY
    else:
        due = fetched_at is None or (now - fetched_at).total_seconds() >= refresh_after_seconds(tf, symbol.provider)
    if not due:
        return
    try:
        bars = _fetch_from_provider(symbol, tf, count)
        _upsert(db, symbol, tf, bars)
        if state is None:
            state = FetchState(source=symbol.provider, symbol=symbol.code, timeframe=tf.code, fetched_at=now)
            db.add(state)
        state.fetched_at = now
        if deep:
            state.deep_fetched_at = now
        db.commit()
    except ProviderError as exc:
        db.rollback()
        result.stale = True
        result.warnings.append(str(exc))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sample(symbol: Symbol, tf: Timeframe, limit: int) -> BarsResult:
    return BarsResult(
        bars=sample.generate(symbol, tf, limit),
        source="sample",
        sample=True,
        warnings=[f"Sample data: not real prices. Add your free {KEY_NAMES.get(symbol.provider, 'data')} key to see real prices."],
    )


def get_bars(db: Session, symbol: Symbol, tf: Timeframe, limit: int = 1000) -> BarsResult:
    """Recent prices for the chart."""
    limit = max(50, min(limit, MAX_BARS))
    if not _provider_key(symbol):
        return _sample(symbol, tf, limit)
    result = BarsResult(bars=[], source=symbol.provider)
    _refresh(db, symbol, tf, limit, deep=False, result=result)
    return _finish(db, symbol, tf, limit, result)


def get_history(db: Session, symbol: Symbol, tf: Timeframe, limit: int = MAX_HISTORY) -> BarsResult:
    """Long price history for backtests: up to 5,000 bars, downloaded once and then kept up to date.
    The candle that's still forming is left out, so a backtest only ever sees finished candles."""
    limit = max(50, min(limit, MAX_HISTORY))
    if not _provider_key(symbol):
        result = _sample(symbol, tf, limit + 1)
    else:
        result = BarsResult(bars=[], source=symbol.provider)
        _refresh(db, symbol, tf, MAX_HISTORY, deep=True, result=result)
        _refresh(db, symbol, tf, 500, deep=False, result=result)
        result = _finish(db, symbol, tf, limit + 1, result)
    now = datetime.now(timezone.utc).timestamp()
    if result.bars and result.bars[-1].ts + tf.seconds > now:
        result.bars = result.bars[:-1]
    result.bars = result.bars[-limit:]
    return result


def _finish(db: Session, symbol: Symbol, tf: Timeframe, limit: int, result: BarsResult) -> BarsResult:
    result.bars = _read_cache(db, symbol, tf, limit)
    if not result.bars and result.warnings:
        raise ProviderError(result.warnings[0])
    if result.stale and result.bars:
        result.warnings.append("Showing saved prices; they may be out of date.")
    return result
