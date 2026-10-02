"""Strategy research: start a scan, follow its progress, read the shortlist."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import research
from ..db import get_session
from ..deps import current_user
from ..market.directory import lookup
from ..models import ResearchJob, User

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/options")
def options(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    basket = []
    for code in research.BASKET:
        try:
            s = lookup(db, code)
            basket.append({"code": s.code, "name": s.name, "assetClass": s.asset_class})
        except ValueError:
            continue  # not in the market list yet (it fills in once the OANDA list has been downloaded)
    sectors = []
    for name, codes in research.SECTORS.items():
        found, missing = [], []
        for code in codes:
            try:
                sym = lookup(db, code)
                found.append({"code": sym.code, "name": sym.name, "assetClass": sym.asset_class, "provider": sym.provider})
            except ValueError:
                missing.append(code)
        sectors.append({"name": name, "markets": found, "missing": missing})
    return {"basket": basket, "sectors": sectors, "timeframes": list(research.TIMEFRAMES), "defaultTimeframes": research.DEFAULT_TIMEFRAMES,
            "checks": research.CHECKS, "minTrades": research.MIN_TRADES, "maxDrawdownPct": research.MAX_DRAWDOWN,
            "strategies": [{"key": s.key, "name": s.name, "intradayOnly": s.intraday_only} for s in research.strategies()]}


@router.get("")
def list_jobs(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    jobs = db.scalars(select(ResearchJob).where(ResearchJob.user_id == user.id).order_by(ResearchJob.id.desc()).limit(10)).all()
    return {"jobs": [research.job_dict(j) for j in jobs]}


class NewScan(BaseModel):
    markets: list[str] = Field(default_factory=list, max_length=research.MAX_MARKETS)
    timeframes: list[str] = Field(default_factory=list, max_length=len(research.TIMEFRAMES))
    strategies: list[str] = Field(default_factory=list, max_length=40)  # empty = all of them


@router.post("")
def new_scan(body: NewScan, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    markets = []
    for code in body.markets:
        try:
            markets.append(lookup(db, code[:32]).code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job = research.start(db, user, markets or None, body.timeframes or None, strategy_keys=body.strategies or None)
    except research.ResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return research.job_dict(job)


@router.get("/{job_id}")
def job(job_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        j = research.get_job(db, user, job_id)
    except research.ResearchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return research.job_dict(j, full=True)
