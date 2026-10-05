"""Weekly review: this week's facts and questions, saving answers, past reviews, and coaching text."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import reviews
from ..db import get_session
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _monday(week: str) -> date:
    try:
        d = date.fromisoformat(week)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown week.") from exc
    if d.weekday() != 0:
        raise HTTPException(status_code=404, detail="Unknown week.")
    return d


@router.get("/current")
def current(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return reviews.current(db, user)


@router.get("")
def history(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return {"reviews": reviews.history(db, user)}


@router.get("/{week}")
def one(week: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return reviews.review_for(db, user, _monday(week))


class Answers(BaseModel):
    answers: dict = Field(default_factory=dict)
    focus: str = Field("", max_length=reviews.FOCUS_MAX)
    complete: bool = False


@router.put("/{week}")
def save(week: str, body: Answers, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    _monday(week)
    if len(body.answers) > 12:
        raise HTTPException(status_code=422, detail="Too many answers.")
    try:
        return reviews.save(db, user, week, body.answers, body.focus, body.complete)
    except reviews.ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{week}/coach")
def coach(week: str, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return {"text": reviews.coach_text(reviews.review_for(db, user, _monday(week)))}
