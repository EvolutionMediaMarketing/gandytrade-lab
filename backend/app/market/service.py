"""Get price bars: from the database cache, refreshed from the provider when stale."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import FetchState, PriceBar
from .providers import oanda, sample, twelvedata
from .providers.base import Bar, ProviderError
from .symbols import Symbol
from .timeframes import Timeframe, refresh_after_seconds

MAX_BARS = 2000


@dataclass
class BarsResult:
    bars: list[Bar]
    source: str
    sample: bool = False
    stale: bool = False
    warnings: list[str] = field(default_factory=list)


def _provider_key(symbol: Symbol) -> str:
    settings = get_settings()
    return settings.oanda_token if symbol.provider == "oanda" else settings.twelvedata_key


def _fetch_from_provider(symbol: Symbol, tf: Timeframe, count: int) -> list[Bar]:
    key = _provider_key(symbol)
    if symbol.provider == "oanda":
        return oanda.fetch_candles(key, symbol, tf, count)
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


def get_bars(db: Session, symbol: Symbol, tf: Timeframe, limit: int = 1000) -> BarsResult:
    limit = max(50, min(limit, MAX_BARS))

    if not _provider_key(symbol):
        return BarsResult(
            bars=sample.generate(symbol, tf, limit),
            source="sample",
            sample=True,
            warnings=["Sample data: not real prices. Add your free data key to see real prices."],
        )

    state = db.scalar(
        select(FetchState).where(
            FetchState.source == symbol.provider,
            FetchState.symbol == symbol.code,
            FetchState.timeframe == tf.code,
        )
    )
    now = datetime.now(timezone.utc)
    fetched_at = state.fetched_at if state else None
    if fetched_at is not None and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    fresh = fetched_at is not None and (now - fetched_at).total_seconds() < refresh_after_seconds(tf)

    result = BarsResult(bars=[], source=symbol.provider)
    if not fresh:
        try:
            bars = _fetch_from_provider(symbol, tf, limit)
            _upsert(db, symbol, tf, bars)
            if state is None:
                db.add(FetchState(source=symbol.provider, symbol=symbol.code, timeframe=tf.code, fetched_at=now))
            else:
                state.fetched_at = now
            db.commit()
        except ProviderError as exc:
            db.rollback()
            result.stale = True
            result.warnings.append(str(exc))

    result.bars = _read_cache(db, symbol, tf, limit)
    if not result.bars and result.warnings:
        raise ProviderError(result.warnings[0])
    if result.stale and result.bars:
        result.warnings.append("Showing saved prices; they may be out of date.")
    return result
