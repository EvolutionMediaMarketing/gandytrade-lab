"""Shared request dependencies."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_session
from .models import User


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    user_id = request.session.get("uid")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user
