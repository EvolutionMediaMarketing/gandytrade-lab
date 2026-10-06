"""Market replay: practise on history with the future hidden, one candle at a time.

The server picks a stretch of finished candles (a date you choose, or a random one), with some history before
it to read the chart, and the indicators you use on the Charts page worked out from earlier candles only. The
browser reveals one candle at a time and fills your trades by the backtester's rules: at the next candle's
open, stop-loss first, with the same costs, risk sizing and currency conversion. Finished sessions are saved.
"""

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..backtest.costs import default_costs
from ..backtest.service import default_mode
from ..db import get_session
from ..deps import current_user
from ..indicators.chart import build_chart
from ..market import directory, events
from ..market.fx import converter, quote_currency
from ..market.providers.base import ProviderError
from ..market.service import get_history
from ..market.timeframes import get_timeframe
from ..models import ReplaySession, User
from .market import STYLES
from ..risk.guard import leverage_cap

router = APIRouter(prefix="/api/replay", tags=["replay"])
LOOKBACK = 150  # candles shown before the replay starts, to read the chart
WARMUP = 250  # extra candles before that, so indicators like the 200 average are ready from the first candle shown
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w")
KEEP = 100


class Indicator(BaseModel):
    id: str = Field(max_length=40)
    type: str = Field(max_length=20)
    params: dict = Field(default_factory=dict)


class Start(BaseModel):
    symbol: str = Field(max_length=32)
    timeframe: str = Field("1d", max_length=4)
    start: str = Field("random", max_length=10)  # "random" or yyyy-mm-dd
    at: int | None = None  # or the exact time of the first candle to play (to look at a saved replay again)
    candles: int = Field(250, ge=30, le=1000)
    style: str = Field("candles", max_length=20)
    mode: str = Field("", max_length=8)  # "" = the market's usual: real shares for shares, CFD otherwise
    indicators: list[Indicator] = Field(default_factory=list, max_length=12)


@router.post("/start")
def start(body: Start, db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    if body.timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Replay works on 15-minute, hourly, 4-hour, daily or weekly candles.")
    try:
        symbol = directory.lookup(db, body.symbol)
        tf = get_timeframe(body.timeframe)
        history = get_history(db, symbol, tf)
        bars = history.bars
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sample = history.sample
    n = len(bars)
    first_ok = min(LOOKBACK, max(0, n - body.candles - 1))
    last_ok = n - body.candles
    if body.at is None and (n < 80 or last_ok < 30):
        raise HTTPException(status_code=400, detail=(
            f"Only {n} candles of history for {symbol.name} on this timeframe: not enough to replay "
            f"{body.candles}. Try fewer candles or a longer timeframe."))
    if body.at is not None:
        s = next((i for i, b in enumerate(bars) if b.ts >= body.at), n)
        if s >= n:
            raise HTTPException(status_code=400, detail="That replay's candles are no longer in the price history.")
        s = max(s, 30)
    elif body.start == "random":
        # Prefer starts with enough earlier history for the chart and its indicators (e.g. a 200 average) to be ready.
        low = min(max(first_ok, 30, LOOKBACK + WARMUP), max(30, last_ok))
        s = random.randint(low, max(low, last_ok))
    else:
        try:
            when = datetime.strptime(body.start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Choose a start date as yyyy-mm-dd, or a random one.") from exc
        s = next((i for i, b in enumerate(bars) if b.ts >= when), n)
        if s > last_ok:
            raise HTTPException(status_code=400, detail=(
                f"That's too close to today to replay {body.candles} candles. The latest start is "
                f"{datetime.fromtimestamp(bars[last_ok].ts, tz=timezone.utc):%d %b %Y}."))
        s = max(s, 30)
    shown_from = max(0, s - LOOKBACK)
    window = bars[max(0, shown_from - WARMUP): s + body.candles]
    if body.at is not None and len(window) < 2:
        raise HTTPException(status_code=400, detail="Not enough candles to show that replay.")
    style = body.style if body.style in STYLES else "candles"
    chart = build_chart(window, tf, style, [i.model_dump() for i in body.indicators])
    cut = bars[shown_from].ts
    chart["bars"] = [b for b in chart["bars"] if b["time"] >= cut]
    for ind in chart["indicators"]:
        for line in ind.get("lines", []):
            line["values"] = [v for v in line["values"] if cut <= v["time"] <= window[-1].ts]
    chart["futureTimes"] = []
    mode = body.mode if body.mode in ("cash", "cfd") else default_mode(symbol.asset_class)
    conv = converter(db, quote_currency(symbol))
    return {
        **chart,
        "symbol": symbol.to_dict(), "timeframe": tf.code, "style": style, "source": symbol.provider,
        "sample": sample, "stale": False, "warnings": [],
        "startIndex": s - shown_from,  # the first candle to play, in the returned bars
        "rates": [conv.rate(b["time"]) for b in chart["bars"]],  # price units per £1, candle by candle
        "mode": mode, "costs": default_costs(symbol.asset_class, mode).to_dict(),
        "leverage": leverage_cap(symbol.code, symbol.asset_class, mode),
        # Major news that touched this market in the window (the browser shows each once its candle is revealed).
        "events": events.for_market(symbol, chart["bars"][0]["time"] - 7 * 86400, chart["bars"][-1]["time"]) if chart["bars"] else [],
    }


class Result(BaseModel):
    symbol: str = Field(max_length=32)
    timeframe: str = Field(max_length=8)
    start_ts: int
    end_ts: int
    candles: int = Field(ge=0, le=100_000)
    trades: int = Field(ge=0, le=100_000)
    wins: int = Field(ge=0, le=100_000)
    net_gbp: float
    return_pct: float
    buy_hold_pct: float
    max_drawdown_pct: float = Field(ge=0, le=100)
    avg_r: float | None = None
    lesson: str = Field("", max_length=500)
    trades_detail: list[dict] | None = Field(None, max_length=500)


def _dict(r: ReplaySession) -> dict:
    return {"id": r.id, "symbol": r.symbol, "timeframe": r.timeframe, "startTs": r.start_ts, "endTs": r.end_ts,
            "candles": r.candles, "trades": r.trades, "wins": r.wins, "netGbp": r.net_gbp, "returnPct": r.return_pct,
            "buyHoldPct": r.buy_hold_pct, "maxDrawdownPct": r.max_drawdown_pct, "avgR": r.avg_r, "lesson": r.lesson,
            "createdAt": r.created_at.isoformat(), "tradesDetail": r.trades_detail}


@router.post("/results")
def save(body: Result, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = ReplaySession(user_id=user.id, **body.model_dump())
    db.add(row)
    db.flush()
    old = db.scalars(select(ReplaySession.id).where(ReplaySession.user_id == user.id)
                     .order_by(ReplaySession.id.desc()).offset(KEEP)).all()
    for i in old:
        db.delete(db.get(ReplaySession, i))
    db.commit()
    return _dict(row)


def _mine(db: Session, user: User, session_id: int) -> ReplaySession:
    row = db.get(ReplaySession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Replay not found.")
    return row


class Lesson(BaseModel):
    lesson: str = Field("", max_length=500)


@router.patch("/results/{session_id}")
def change(session_id: int, body: Lesson, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = _mine(db, user, session_id)
    row.lesson = body.lesson.strip()
    db.commit()
    return _dict(row)


@router.delete("/results/{session_id}")
def delete(session_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    db.delete(_mine(db, user, session_id))
    db.commit()
    return {"ok": True}


@router.get("/results")
def results(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    rows = db.scalars(select(ReplaySession).where(ReplaySession.user_id == user.id).order_by(ReplaySession.id.desc()).limit(KEEP))
    return {"sessions": [_dict(r) for r in rows]}
