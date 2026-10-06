"""The 12-week course: progress, quiz results and tasks."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import course
from ..db import get_session
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/api/course", tags=["course"])


def _fail(exc: course.CourseError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def progress(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return course.progress(db, user)


@router.post("/{week}/start")
def start(week: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        return course.start(db, user, week)
    except course.CourseError as exc:
        raise _fail(exc) from exc


class Quiz(BaseModel):
    score: int = Field(ge=0, le=course.QUIZ_QUESTIONS)


@router.post("/{week}/quiz")
def quiz(week: int, body: Quiz, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        return course.record_quiz(db, user, week, body.score)
    except course.CourseError as exc:
        raise _fail(exc) from exc


class Task(BaseModel):
    done: bool = True
    note: str = Field("", max_length=4000)


@router.post("/{week}/task")
def task(week: int, body: Task, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        return course.record_task(db, user, week, body.done, body.note)
    except course.CourseError as exc:
        raise _fail(exc) from exc
