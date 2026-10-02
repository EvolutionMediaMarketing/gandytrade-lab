"""The signal assistant panel beside the chart."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import signals
from ..db import get_session
from ..deps import current_user
from ..market.providers.base import ProviderError
from ..models import User

router = APIRouter(prefix="/api", tags=["signals"])


@router.get("/signals")
def get_signals(
    symbol: str = Query(max_length=32),
    timeframe: str = Query("1d", max_length=4),
    balance: float = Query(200, gt=0, le=10_000_000),
    risk: float = Query(1.0, ge=0.1, le=2.0),
    mode: str = Query("", max_length=8),
    db: Session = Depends(get_session),
    _: User = Depends(current_user),
) -> dict:
    try:
        return signals.evaluate(db, symbol, timeframe, balance, risk, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
