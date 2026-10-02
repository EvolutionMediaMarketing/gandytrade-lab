"""Calculators. Position sizing uses the same risk guard as the backtester and paper trading."""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..backtest.costs import default_costs
from ..backtest.service import default_mode
from ..db import get_session
from ..deps import current_user
from ..market.directory import lookup
from ..market.fx import converter, quote_currency
from ..market.providers.base import ProviderError
from ..market.service import get_bars
from ..market.timeframes import get_timeframe
from ..indicators.core import atr
from ..models import User
from ..risk.guard import RiskSettings, leverage_cap, size_trade

router = APIRouter(prefix="/api/tools", tags=["tools"])


class PositionBody(BaseModel):
    symbol: str = Field(max_length=32)
    balance: float = Field(gt=0, le=10_000_000)
    risk_pct: float = Field(1.0, ge=0.1, le=2.0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    mode: str = Field("", max_length=8)


@router.post("/position-size")
def position_size(body: PositionBody, db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    try:
        symbol = lookup(db, body.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mode = body.mode if body.mode in ("cash", "cfd") else default_mode(symbol.asset_class)
    side = 1 if body.stop < body.entry else -1
    if mode == "cash" and side < 0:
        raise HTTPException(status_code=400, detail="With real shares you can only buy, so the stop-loss must be below the entry price.")
    currency = quote_currency(symbol)
    conv = converter(db, currency)
    per_gbp = conv.rate(time.time())
    cap = leverage_cap(symbol.code, symbol.asset_class, mode)
    settings = RiskSettings(risk_pct=body.risk_pct).cleaned()
    d = size_trade(equity_gbp=body.balance, entry=body.entry, stop=body.stop, side=side, per_gbp=per_gbp, cap=cap, settings=settings)
    if not d.ok:
        raise HTTPException(status_code=400, detail=d.reason)
    value_gbp = d.units * body.entry / per_gbp
    risk_gbp = d.units * abs(body.entry - body.stop) / per_gbp
    costs = default_costs(symbol.asset_class, mode)
    round_trip = value_gbp * (costs.spread_pct + 2 * costs.slippage_pct + 2 * costs.fx_fee_pct) / 100 + 2 * costs.commission_gbp
    if mode == "cash":
        round_trip += value_gbp * costs.stamp_duty_pct / 100
    return {
        "symbol": symbol.to_dict(),
        "mode": mode,
        "side": "long" if side > 0 else "short",
        "units": d.units,
        "riskGbp": round(risk_gbp, 2),
        "valueGbp": round(value_gbp, 2),
        "leverageUsed": round(value_gbp / body.balance, 2),
        "leverageCap": cap,
        "capped": d.capped,
        "note": d.reason,
        "currency": currency,
        "perGbp": per_gbp,
        "rateNote": conv.note,
        "perPointGbp": round(d.units / per_gbp, 4),
        "costGbp": round(round_trip, 2),
        "marginGbp": round(value_gbp / cap, 2) if mode == "cfd" else None,
    }


@router.get("/quote")
def quote(symbol: str = Query(max_length=32), db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    """The latest price as a guide for the calculator, plus a typical stop distance (2 × daily ATR).
    Uses the same cached prices as the charts, so it rarely costs a data request."""
    import pandas as pd

    try:
        sym = lookup(db, symbol)
        daily = get_bars(db, sym, get_timeframe("1d"), 60)
        # London shares only have daily prices on the free feed; others use 15-minute candles for freshness.
        recent = daily if sym.provider == "alphavantage" else get_bars(db, sym, get_timeframe("15m"), 50)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not recent.bars:
        raise HTTPException(status_code=502, detail="No recent price available.")
    last = recent.bars[-1]
    df = pd.DataFrame({"high": [b.high for b in daily.bars], "low": [b.low for b in daily.bars],
                       "close": [b.close for b in daily.bars]})
    daily_atr = atr(df, 14).iloc[-1] if len(df) >= 15 else float("nan")
    ok = daily_atr == daily_atr
    return {
        "symbol": sym.to_dict(),
        "price": last.close,
        "time": last.ts,
        "sample": recent.sample,
        "currency": quote_currency(sym),
        "dailyAtr": float(daily_atr) if ok else None,
        "suggestedStopLong": float(last.close - 2 * daily_atr) if ok else None,
        "suggestedStopShort": float(last.close + 2 * daily_atr) if ok else None,
    }


class OddsBody(BaseModel):
    symbol: str = Field(max_length=32)
    timeframe: str = Field("1h", max_length=4)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float | None = Field(None, gt=0)
    mode: str = Field("", max_length=8)


@router.post("/target-odds")
def target_odds(body: OddsBody, db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    from ..odds import target_odds as compute

    try:
        return compute(db, body.symbol, body.timeframe, body.entry, body.stop, body.target, body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
