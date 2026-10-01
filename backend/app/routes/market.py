"""Symbols, timeframes, indicator catalogue and chart data."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..deps import current_user
from ..indicators.chart import build_chart, catalogue_json
from ..market.providers.base import ProviderError
from ..market.service import get_bars
from ..market.symbols import SYMBOLS, get_symbol
from ..market.timeframes import TIMEFRAMES, get_timeframe
from ..models import User

router = APIRouter(prefix="/api", tags=["market"])

STYLES = ["candles", "bars", "line", "area", "heikin_ashi"]


@router.get("/catalogue")
def catalogue(_: User = Depends(current_user)) -> dict:
    settings = get_settings()
    return {
        "symbols": [s.to_dict() for s in SYMBOLS.values()],
        "timeframes": [{"code": t.code, "label": t.label, "intraday": t.intraday} for t in TIMEFRAMES.values()],
        "styles": STYLES,
        "indicators": catalogue_json(),
        "dataSources": {
            "oanda": bool(settings.oanda_token),
            "twelvedata": bool(settings.twelvedata_key),
        },
    }


class IndicatorRequest(BaseModel):
    id: str = Field(max_length=40)
    type: str = Field(max_length=20)
    params: dict = Field(default_factory=dict)


class ChartRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    style: str = "candles"
    limit: int = 1000
    indicators: list[IndicatorRequest] = Field(default_factory=list)


@router.post("/chart")
def chart(body: ChartRequest, db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    try:
        symbol = get_symbol(body.symbol)
        tf = get_timeframe(body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    style = body.style if body.style in STYLES else "candles"

    try:
        result = get_bars(db, symbol, tf, body.limit)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = build_chart(result.bars, tf, style, [i.model_dump() for i in body.indicators])
    data.update(
        {
            "symbol": symbol.to_dict(),
            "timeframe": tf.code,
            "style": style,
            "source": result.source,
            "sample": result.sample,
            "stale": result.stale,
            "warnings": result.warnings,
            "fetchedAt": int(time.time()),
        }
    )
    return data
