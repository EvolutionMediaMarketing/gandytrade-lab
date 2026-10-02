"""Calculators. Position sizing uses the same risk guard as the backtester and paper trading."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..backtest.costs import default_costs
from ..backtest.service import default_mode
from ..db import get_session
from ..deps import current_user
from ..market.directory import lookup
from ..market.fx import converter, quote_currency
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
