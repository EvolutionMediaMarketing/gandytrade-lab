"""Favourite markets: star the ones you follow so they're always one click away."""

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..market import directory
from ..models import Favourite, User

router = APIRouter(prefix="/api/favourites", tags=["favourites"])

MAX_FAVOURITES = 200
CODE = Path(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.\-]+$")


def _list(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(Favourite).where(Favourite.user_id == user.id).order_by(Favourite.added_at)).all()
    out = []
    for fav in rows:
        try:
            out.append(directory.lookup(db, fav.code).to_dict())
        except ValueError:
            continue  # a market the data feed no longer offers; kept in case it returns
    return out


@router.get("")
def list_favourites(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return {"favourites": _list(db, user)}


@router.put("/{code}")
def add_favourite(code: str = CODE, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        directory.lookup(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    exists = db.scalar(select(Favourite).where(Favourite.user_id == user.id, Favourite.code == code))
    if exists is None:
        count = db.scalar(select(func.count()).select_from(Favourite).where(Favourite.user_id == user.id))
        if count >= MAX_FAVOURITES:
            raise HTTPException(status_code=400, detail=f"You can have up to {MAX_FAVOURITES} favourites.")
        db.add(Favourite(user_id=user.id, code=code))
        db.commit()
    return {"favourites": _list(db, user)}


@router.delete("/{code}")
def remove_favourite(code: str = CODE, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    db.execute(delete(Favourite).where(Favourite.user_id == user.id, Favourite.code == code))
    db.commit()
    return {"favourites": _list(db, user)}
