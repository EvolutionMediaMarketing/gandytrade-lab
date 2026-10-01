"""Sign-in and sign-out. There is one user and no sign-up page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..models import User
from ..security import check_totp, is_locked, register_failure, register_success, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_FAILURE = "Username, password or code not recognised."


class LoginRequest(BaseModel):
    username: str
    password: str
    code: str


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_session)) -> dict:
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user is None:
        raise HTTPException(status_code=401, detail=GENERIC_FAILURE)
    if is_locked(user):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Sign-in is paused for a few minutes.",
        )
    if not verify_password(user.password_hash, body.password) or not check_totp(user, body.code):
        register_failure(user)
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_FAILURE)

    register_success(user)
    db.commit()
    request.session.clear()
    request.session["uid"] = user.id
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"username": user.username}
