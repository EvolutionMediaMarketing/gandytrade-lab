"""Strategy builder: make, change and delete your own strategies."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..models import AutoRun, CustomStrategy, User
from ..strategies import builder
from ..strategies.library import STRATEGIES

router = APIRouter(prefix="/api/builder", tags=["builder"])
MAX_STRATEGIES = 50


class Body(BaseModel):
    spec: dict


def _row(db: Session, user: User, sid: int) -> CustomStrategy:
    row = db.get(CustomStrategy, sid)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return row


def _in_use(db: Session, sid: int) -> int:
    return db.scalar(select(func.count()).select_from(AutoRun).where(
        AutoRun.strategy == f"{builder.PREFIX}{sid}", AutoRun.status.in_(("running", "paused")))) or 0


def _dict(db: Session, row: CustomStrategy) -> dict:
    s = STRATEGIES.get(f"{builder.PREFIX}{row.id}")
    return {"id": row.id, "key": f"{builder.PREFIX}{row.id}", "name": row.name, "spec": row.spec,
            "rules": s.rules_text if s else [], "params": [p.to_dict() for p in s.params] if s else [],
            "runs": _in_use(db, row.id), "updatedAt": row.updated_at.isoformat()}


@router.get("/catalogue")
def catalogue(_: User = Depends(current_user)) -> dict:
    return builder.catalogue()


@router.get("")
def list_mine(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    builder.sync(db)
    rows = db.scalars(select(CustomStrategy).where(CustomStrategy.user_id == user.id).order_by(CustomStrategy.name))
    return {"strategies": [_dict(db, r) for r in rows]}


@router.post("/check")
def check(body: Body, _: User = Depends(current_user)) -> dict:
    """The rules in plain words, or what's wrong, without saving."""
    try:
        spec = builder.check(body.spec)
    except builder.SpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    s = builder.build(0, spec)
    return {"rules": s.rules_text, "params": [p.to_dict() for p in s.params]}


@router.post("")
def create(body: Body, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        spec = builder.check(body.spec)
    except builder.SpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    count = db.scalar(select(func.count()).select_from(CustomStrategy).where(CustomStrategy.user_id == user.id)) or 0
    if count >= MAX_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"You have {MAX_STRATEGIES} strategies: delete one first.")
    now = datetime.now(timezone.utc)
    row = CustomStrategy(user_id=user.id, name=spec["name"], spec=spec, created_at=now, updated_at=now)
    db.add(row)
    db.commit()
    builder.sync(db)
    return _dict(db, row)


@router.put("/{sid}")
def update(sid: int, body: Body, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = _row(db, user, sid)
    if _in_use(db, sid):
        raise HTTPException(status_code=409, detail=(
            "An automatic paper run is using this strategy, and changing its rules mid-run would mix two strategies' "
            "results. Stop the run first, or save your changes as a new strategy."))
    try:
        spec = builder.check(body.spec)
    except builder.SpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.name, row.spec, row.updated_at = spec["name"], spec, datetime.now(timezone.utc)
    db.commit()
    builder.sync(db)
    return _dict(db, row)


@router.delete("/{sid}")
def delete(sid: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = _row(db, user, sid)
    if _in_use(db, sid):
        raise HTTPException(status_code=409, detail="An automatic paper run is using this strategy. Stop it first.")
    db.delete(row)
    db.commit()
    builder.sync(db)
    return {"ok": True}
