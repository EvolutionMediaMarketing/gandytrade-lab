"""Sign-in and sign-out. There is one user and no sign-up page."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import sessions
from ..db import get_session
from ..deps import current_user
from ..models import User
from ..security import check_totp, is_locked, register_failure, register_success, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_FAILURE = "Username, password or code not recognised."


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    code: str = Field(max_length=16)


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_session)) -> dict:
    ip = sessions.client_ip(request)
    username = body.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        sessions.audit(db, "login_failed", username, ip, "unknown username")
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_FAILURE)
    if is_locked(user):
        sessions.audit(db, "login_blocked", username, ip, "sign-in paused after repeated failures")
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Sign-in is paused for a few minutes.",
        )
    if not verify_password(user.password_hash, body.password) or not check_totp(user, body.code):
        register_failure(user)
        locked = is_locked(user)
        sessions.audit(db, "login_failed", username, ip, "locked for a few minutes" if locked else "wrong password or code")
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_FAILURE)

    register_success(user)
    sessions.start(db, request, user)
    sessions.audit(db, "login_ok", username, ip)
    db.commit()
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_session)) -> dict:
    user = sessions.resolve(db, request)
    sessions.end(db, request)
    if user is not None:
        sessions.audit(db, "logout", user.username, sessions.client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"username": user.username}
