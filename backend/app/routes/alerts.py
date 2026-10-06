"""Telegram alerts: link your chat, choose what to hear about, send a test."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import alerts, sessions
from ..db import get_session
from ..deps import current_user
from ..market import news_watch
from ..models import Alert, User

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _status(db: Session, user: User) -> dict:
    row = alerts.settings_for(db, user.id)
    db.commit()
    recent = db.scalars(select(Alert).where((Alert.user_id == user.id) | (Alert.user_id.is_(None)))
                        .order_by(Alert.id.desc()).limit(10)).all()
    return {
        "botConfigured": alerts.configured(),
        "chatLinked": bool(row.chat_id),
        "chatName": row.chat_name,
        "kinds": row.kinds or [],
        "kindLabels": alerts.KINDS,
        "news": news_watch.status(db, user.id),
        "recent": [{"at": a.created_at.isoformat(), "kind": a.kind, "text": a.text, "status": a.status, "error": a.error}
                   for a in recent],
    }


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def status(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return _status(db, user)


@router.post("/find-chats")
def find_chats(user: User = Depends(current_user)) -> dict:
    try:
        return {"chats": alerts.recent_chats()}
    except alerts.AlertError as exc:
        raise _fail(exc) from exc


class Link(BaseModel):
    chat_id: str = Field(max_length=32)


@router.post("/link")
def link(body: Link, request: Request, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        chats = {c["chatId"]: c for c in alerts.recent_chats()}
        chat = chats.get(body.chat_id.strip())
        if chat is None:
            raise alerts.AlertError("That chat hasn't messaged your bot recently. Send it a message, then try again.")
        alerts.send_text(chat["chatId"], "GandyTrade Lab alerts are linked to this chat. Pretend money only; "
                                         "you'll hear about the alerts you've chosen in Settings.")
    except alerts.AlertError as exc:
        raise _fail(exc) from exc
    row = alerts.settings_for(db, user.id)
    row.chat_id, row.chat_name = chat["chatId"], chat["name"]
    sessions.audit(db, "alerts_linked", user.username, sessions.client_ip(request), chat["name"])
    db.commit()
    return _status(db, user)


@router.post("/unlink")
def unlink(request: Request, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = alerts.settings_for(db, user.id)
    row.chat_id, row.chat_name = "", ""
    sessions.audit(db, "alerts_unlinked", user.username, sessions.client_ip(request))
    db.commit()
    return _status(db, user)


class Kinds(BaseModel):
    kinds: list[str] = Field(max_length=len(alerts.KINDS))


@router.patch("")
def choose(body: Kinds, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    unknown = [k for k in body.kinds if k not in alerts.KINDS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown alert kind: {', '.join(unknown)}.")
    row = alerts.settings_for(db, user.id)
    row.kinds = list(dict.fromkeys(body.kinds))
    db.commit()
    return _status(db, user)


@router.post("/test")
def test(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    row = alerts.settings_for(db, user.id)
    if not row.chat_id:
        raise HTTPException(status_code=400, detail="Link your Telegram chat first.")
    try:
        alerts.send_text(row.chat_id, "Test message from GandyTrade Lab. Alerts are working.")
    except alerts.AlertError as exc:
        raise _fail(exc) from exc
    return {"ok": True}
