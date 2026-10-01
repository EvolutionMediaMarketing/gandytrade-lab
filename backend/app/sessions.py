"""Server-side sign-in sessions and the security audit log.

The browser's signed cookie only holds a random token. The server keeps a row per
signed-in browser, so a session can be ended from the server (sign out, password
change, `python -m app.cli sign-out-everywhere`) and expires on its own:
  * after `session_idle_minutes` without activity from you, and
  * after `session_hours` in total, whatever you're doing.
Automatic chart refreshes are marked as background requests and don't count as
activity, so a tab left open on its own still signs out.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import get_settings
from .models import LoginSession, SecurityEvent, User

BACKGROUND_HEADER = "x-gt-background"
# Don't write to the database on every request; a minute's precision is plenty.
TOUCH_EVERY = timedelta(seconds=60)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite drops the zone


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:64]


def audit(db: Session, event: str, username: str = "", ip: str = "", detail: str = "") -> None:
    """Record a security event. The caller commits."""
    db.add(SecurityEvent(event=event, username=username[:64], ip=ip[:64], detail=detail[:255]))


def start(db: Session, request: Request, user: User) -> None:
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            id=_hash(token),
            user_id=user.id,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    request.session.clear()
    request.session["sid"] = token


def resolve(db: Session, request: Request) -> User | None:
    """The signed-in user for this request, or None. Expired sessions are removed."""
    token = request.session.get("sid")
    if not token or not isinstance(token, str):
        return None
    row = db.get(LoginSession, _hash(token))
    if row is None:
        request.session.clear()
        return None

    settings = get_settings()
    now = _now()
    created, last = _aware(row.created_at), _aware(row.last_active_at)
    reason = ""
    if now - created > timedelta(hours=settings.session_hours):
        reason = "session reached its maximum length"
    elif now - last > timedelta(minutes=settings.session_idle_minutes):
        reason = "no activity"
    if reason:
        user = db.get(User, row.user_id)
        audit(db, "session_expired", user.username if user else "", client_ip(request), reason)
        db.delete(row)
        db.commit()
        request.session.clear()
        return None

    background = request.headers.get(BACKGROUND_HEADER) == "1"
    if not background and now - last > TOUCH_EVERY:
        row.last_active_at = now
        db.commit()
    user = db.get(User, row.user_id)
    if user is None:
        request.session.clear()
    return user


def end(db: Session, request: Request) -> None:
    token = request.session.get("sid")
    if isinstance(token, str):
        db.execute(delete(LoginSession).where(LoginSession.id == _hash(token)))
    request.session.clear()


def end_all(db: Session, user_id: int) -> int:
    """Sign out every browser for this user. Returns how many sessions were ended."""
    result = db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    return result.rowcount or 0
