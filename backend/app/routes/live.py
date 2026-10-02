"""Live prices for the charts and the Paper page (OANDA markets only)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..market.directory import lookup
from ..market.stream import stream
from ..models import PaperAccount, PaperTrade, User

router = APIRouter(prefix="/api", tags=["live"])


@router.get("/live")
def live_prices(symbols: str = Query("", max_length=400), db: Session = Depends(get_session),
                user: User = Depends(current_user)) -> dict:
    wanted = []
    for code in {c.strip() for c in symbols.split(",") if c.strip()}:
        try:
            if lookup(db, code).provider == "oanda":
                wanted.append(code)
        except ValueError:
            continue
    # Markets with open paper trades stay connected while the app is running.
    open_codes = set(db.scalars(select(PaperTrade.symbol).join(PaperAccount, PaperAccount.id == PaperTrade.account_id)
                                .where(PaperAccount.user_id == user.id, PaperTrade.status == "open")))
    oanda_open = set()
    for code in open_codes:
        try:
            if lookup(db, code).provider == "oanda":
                oanda_open.add(code)
        except ValueError:
            continue
    stream.pin(oanda_open)
    stream.want(sorted(wanted))
    ticks = stream.latest(sorted(wanted))
    return {
        "live": stream.live,
        "status": stream.status,
        "prices": {c: {"bid": t.bid, "ask": t.ask, "mid": t.mid, "time": t.time} for c, t in ticks.items()},
    }
