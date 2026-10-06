"""Economic calendar: the coming high-impact events, for a market or for everything."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..market import calendar, directory
from ..models import User

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("")
def upcoming(symbol: str | None = Query(None, max_length=32), days: int = Query(14, ge=1, le=120),
             past_days: int = Query(0, ge=0, le=400),
             db: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    """High-impact events from `past_days` ago to `days` ahead. With a market, each is marked whether it
    affects that market, and the next one within 24 hours is picked out for warnings."""
    sym = None
    if symbol:
        try:
            sym = directory.lookup(db, symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    rows = []
    for e in calendar.between(now - timedelta(days=past_days), now + timedelta(days=days)):
        d = e.to_dict(now)
        d["affects"] = calendar.affects(e, sym) if sym else True
        rows.append(d)
    soon = calendar.next_for(sym, now) if sym else None
    return {"events": rows, "soon": soon.to_dict(now) if soon else None, "coverage": calendar.coverage(now)}
