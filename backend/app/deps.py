"""Shared request dependencies."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import sessions
from .db import get_session
from .models import User


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    user = sessions.resolve(db, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user
