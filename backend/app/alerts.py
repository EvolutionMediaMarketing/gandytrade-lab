"""Alerts to your phone through your own Telegram bot.

Anything worth knowing (an automatic trade opened or closed, a stop-loss or target hit, a run or
account pausing itself, a backup failing, the weekly research scan finishing) is queued with
`notify()`, in the same database transaction as the event itself. The background worker sends the
queue with `send_pending()` each minute. If Telegram is unreachable, messages wait and are retried;
nothing else in the app waits for Telegram.

The bot token lives only in app.env (GT_TELEGRAM_BOT_TOKEN). The chat it sends to is linked in
Settings: you message your bot, the app lists the chats that have, and you pick yours. Messages are
plain text with trade details only: never keys, passwords or account numbers.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .market.providers.http import safe_client
from .models import Alert, AlertSettings, User

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
KINDS = {
    "trades": "Trades: automatic trades opening and closing, and stop-losses or targets hit on any paper trade",
    "problems": "Problems: an automatic run or an account pausing itself, or a backup failing",
    "research": "Research: when the weekly scan finishes, with the size of the shortlist",
    "reviews": "Weekly review: a reminder on Sunday evening if this week's review isn't done",
}
DEFAULT_KINDS = ["trades", "problems", "research", "reviews"]
MAX_ATTEMPTS = 5
PER_PASS = 20
KEEP_DAYS = 30


class AlertError(RuntimeError):
    """A problem in plain words (never contains the token)."""


def configured() -> bool:
    return bool(get_settings().telegram_bot_token.strip())


def settings_for(db: Session, user_id: int) -> AlertSettings:
    row = db.scalar(select(AlertSettings).where(AlertSettings.user_id == user_id))
    if row is None:
        row = AlertSettings(user_id=user_id, chat_id="", chat_name="", kinds=list(DEFAULT_KINDS))
        db.add(row)
        db.flush()
    return row


def notify(db: Session, user_id: int | None, kind: str, text: str) -> None:
    """Queue a message (committed with the caller's transaction). user_id None means every user."""
    if kind not in KINDS:
        raise ValueError(f"Unknown alert kind '{kind}'.")
    db.add(Alert(user_id=user_id, kind=kind, text=text[:1000], status="pending", attempts=0, error=""))


# --- Talking to Telegram --------------------------------------------------------------------------

def _call(method: str, payload: dict | None = None, client: httpx.Client | None = None) -> dict:
    token = get_settings().telegram_bot_token.strip()
    if not token:
        raise AlertError("No Telegram bot token in app.env yet (GT_TELEGRAM_BOT_TOKEN).")
    own = client is None
    client = client or safe_client(timeout=15)
    try:
        r = client.post(API.format(token=token, method=method), json=payload or {})
    except httpx.HTTPError as exc:
        raise AlertError(f"Couldn't reach Telegram ({exc.__class__.__name__}).") from exc
    finally:
        if own:
            client.close()
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 401:
        raise AlertError("Telegram didn't accept the bot token. Check GT_TELEGRAM_BOT_TOKEN in app.env.")
    if r.status_code == 429:
        raise AlertError("Telegram asked us to slow down; trying again shortly.")
    if not data.get("ok"):
        desc = str(data.get("description") or f"error {r.status_code}")[:150]
        raise AlertError(f"Telegram said: {desc}")
    return data.get("result") or {}


def send_text(chat_id: str, text: str, client: httpx.Client | None = None) -> None:
    _call("sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}, client)


def recent_chats(client: httpx.Client | None = None) -> list[dict]:
    """Chats that have messaged the bot recently (so you can pick yours)."""
    updates = _call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]}, client)
    chats: dict[str, dict] = {}
    for u in updates if isinstance(updates, list) else []:
        chat = (u.get("message") or {}).get("chat") or {}
        if "id" not in chat:
            continue
        name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("title") or "Chat"
        if chat.get("username"):
            name += f" (@{chat['username']})"
        chats[str(chat["id"])] = {"chatId": str(chat["id"]), "name": name[:120], "type": chat.get("type", "")}
    return list(chats.values())


# --- The queue (the worker calls this) ---------------------------------------------------------------

def send_pending(db: Session, client: httpx.Client | None = None) -> dict:
    """Send waiting messages. Returns counts, for the log and tests."""
    stats = {"sent": 0, "skipped": 0, "failed": 0}
    pending = list(db.scalars(select(Alert).where(Alert.status == "pending").order_by(Alert.id).limit(PER_PASS)))
    if not pending:
        return stats
    users = [u.id for u in db.scalars(select(User))]
    targets: dict[int, AlertSettings] = {}
    for uid in users:
        row = db.scalar(select(AlertSettings).where(AlertSettings.user_id == uid))
        if row is not None:
            targets[uid] = row
    now = datetime.now(timezone.utc)
    for alert in pending:
        recipients = [targets[u] for u in ([alert.user_id] if alert.user_id else users) if u in targets]
        recipients = [r for r in recipients if r.chat_id and alert.kind in (r.kinds or [])]
        if not configured() or not recipients:
            alert.status, alert.error = "skipped", "Alerts not set up, or this kind is switched off."
            stats["skipped"] += 1
            continue
        try:
            for r in recipients:
                send_text(r.chat_id, alert.text, client)
            alert.status, alert.sent_at, alert.error = "sent", now, ""
            stats["sent"] += 1
        except AlertError as exc:
            alert.attempts += 1
            alert.error = str(exc)[:255]
            if alert.attempts >= MAX_ATTEMPTS:
                alert.status = "failed"
            stats["failed"] += 1
            log.warning("Alert %s not sent: %s", alert.id, exc)
            break  # Telegram is having trouble: try the rest next pass
    # Keep a month of history.
    for old in db.scalars(select(Alert).where(Alert.created_at < now - timedelta(days=KEEP_DAYS), Alert.status != "pending")):
        db.delete(old)
    db.commit()
    return stats


# --- Message wording --------------------------------------------------------------------------------

def _price(v: float | None, precision: int) -> str:
    return "–" if v is None else f"{v:.{precision}f}"


def opened_text(trade, symbol, account_name: str, strategy_name: str) -> str:
    side = "Buy" if trade.side > 0 else "Short"
    return (f"Paper trade opened (automatic)\n{side} {symbol.name} at {_price(trade.entry_price, symbol.precision)}\n"
            f"Stop-loss {_price(trade.stop, symbol.precision)}, target {_price(trade.target, symbol.precision)}\n"
            f"Risk £{trade.risk_gbp:.2f} · {strategy_name} · {account_name}")


def closed_text(trade, symbol, account_name: str) -> str:
    side = "buy" if trade.side > 0 else "short"
    pnl = trade.pnl_gbp or 0.0
    r = f" ({pnl / trade.risk_gbp:+.2f}R)" if trade.risk_gbp else ""
    who = "automatic" if trade.source == "auto" else "yours"
    return (f"Paper trade closed: {trade.exit_reason}\n{symbol.name} {side} ({who}) closed at "
            f"{_price(trade.exit_price, symbol.precision)}\nResult {'+' if pnl >= 0 else '-'}£{abs(pnl):.2f}{r} · {account_name}")
