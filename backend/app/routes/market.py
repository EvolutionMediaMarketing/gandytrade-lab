"""Symbols, timeframes, indicator catalogue and chart data."""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..deps import current_user
from ..indicators.chart import build_chart, catalogue_json
from ..market.providers.base import ProviderError
from ..market.service import get_bars
from ..market import directory, info
from ..market.symbols import SYMBOLS
from ..market.timeframes import TIMEFRAMES, get_timeframe
from ..models import User

router = APIRouter(prefix="/api", tags=["market"])

STYLES = ["candles", "bars", "line", "area", "heikin_ashi"]


ASSET_CLASSES = ["forex", "metal", "commodity", "index", "bond", "stock", "etf", "ukstock"]


@router.get("/catalogue")
def catalogue(db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    settings = get_settings()
    directory.refresh_in_background()  # weekly; does nothing if the list is fresh
    return {
        # A hand-picked shortlist shown before you search; everything else is found with search.
        "symbols": [s.to_dict() for s in SYMBOLS.values()],
        "marketCounts": directory.counts(db),
        "timeframes": [{"code": t.code, "label": t.label, "intraday": t.intraday} for t in TIMEFRAMES.values()],
        "styles": STYLES,
        "indicators": catalogue_json(),
        "dataSources": {
            "oanda": bool(settings.oanda_token),
            "twelvedata": bool(settings.twelvedata_key),
            "alphavantage": bool(settings.alphavantage_key),
        },
    }


@router.get("/markets/search")
def search_markets(
    q: str = Query("", max_length=40),
    asset_class: str = Query("", alias="class", max_length=16),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_session),
    _: User = Depends(current_user),
) -> dict:
    cls = asset_class if asset_class in ASSET_CLASSES else ""
    return {"results": directory.search(db, q, cls, limit)}


class IndicatorRequest(BaseModel):
    id: str = Field(max_length=40)
    type: str = Field(max_length=20)
    params: dict = Field(default_factory=dict)


class ChartRequest(BaseModel):
    symbol: str = Field(max_length=32)
    timeframe: str = "1d"
    style: str = "candles"
    limit: int = 1000
    indicators: list[IndicatorRequest] = Field(default_factory=list)


@router.post("/chart")
def chart(body: ChartRequest, db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    try:
        symbol = directory.lookup(db, body.symbol)
        tf = get_timeframe(body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    style = body.style if body.style in STYLES else "candles"

    try:
        result = get_bars(db, symbol, tf, body.limit)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = build_chart(result.bars, tf, style, [i.model_dump() for i in body.indicators])
    if symbol.provider == "alphavantage":
        result.warnings.append("London share prices are in pence (100p = £1). Daily, weekly and monthly charts only.")
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


@router.get("/markets/info")
def market_info(symbol: str = Query(max_length=32), full: bool = False,
                db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    """Background for the hover card: what the market is, sector, a summary, saved headlines.
    Information only; nothing here touches a trade."""
    try:
        sym = directory.lookup(db, symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return info.info(db, sym, full=full)


@router.post("/markets/info/news")
def market_news(symbol: str = Query(max_length=32), db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    try:
        sym = directory.lookup(db, symbol)
        return info.headlines(db, sym)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
