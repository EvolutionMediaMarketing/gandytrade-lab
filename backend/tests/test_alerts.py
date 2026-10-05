"""Telegram alerts: linking a chat, the queue and its retries, which events alert, and keeping the token secret."""

import json
import logging
import time
from types import SimpleNamespace

import httpx
import pytest

from app import alerts
from app.market.providers import http as safe_http
from app.market.providers.base import Bar
from app.paper import service as paper

TOKEN = "123456789:AAH-test_token_value_abcdefghijklmnop"


class FakeTelegram:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail = False
        self.updates = [{"update_id": 1, "message": {"chat": {"id": 4242, "type": "private", "first_name": "Gandy",
                                                               "username": "gandy"}, "text": "hi"}}]

    def handler(self, request: httpx.Request):
        assert request.url.host == "api.telegram.org" and f"/bot{TOKEN}/" in request.url.path
        method = request.url.path.rsplit("/", 1)[-1]
        if self.fail:
            return httpx.Response(502, json={"ok": False, "description": "Bad Gateway"})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": self.updates})
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.sent)}})


@pytest.fixture()
def telegram(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(alerts, "get_settings", lambda: SimpleNamespace(telegram_bot_token=TOKEN))
    monkeypatch.setattr(alerts, "safe_client", lambda timeout=15: httpx.Client(
        transport=httpx.MockTransport(fake.handler), event_hooks={"request": [safe_http.check_request]}))
    return fake


def _send():
    from app.db import new_session

    db = new_session()
    try:
        return alerts.send_pending(db)
    finally:
        db.close()


def _queue(user_id, kind="trades", text="hello"):
    from app.db import new_session

    db = new_session()
    alerts.notify(db, user_id, kind, text)
    db.commit()
    db.close()


def _user_id():
    from app.db import new_session
    from app.models import User

    db = new_session()
    try:
        return db.query(User).first().id
    finally:
        db.close()


def test_token_never_reaches_the_logs(caplog):
    from app.logsafe import RedactingFilter

    record = logging.LogRecord("httpx", logging.WARNING, __file__, 1,
                               f"HTTP Request: POST https://api.telegram.org/bot{TOKEN}/sendMessage", None, None)
    RedactingFilter().filter(record)
    assert TOKEN not in record.getMessage() and "/bot[hidden]/sendMessage" in record.getMessage()
    assert safe_http.host_allowed("api.telegram.org")


def test_link_chat_test_and_choose(signed_in, telegram):
    s = signed_in.get("/api/alerts").json()
    assert s["botConfigured"] and not s["chatLinked"] and set(s["kinds"]) == set(alerts.KINDS)
    chats = signed_in.post("/api/alerts/find-chats").json()["chats"]
    assert chats == [{"chatId": "4242", "name": "Gandy (@gandy)", "type": "private"}]
    assert signed_in.post("/api/alerts/link", json={"chat_id": "999"}).status_code == 400  # never messaged the bot
    s = signed_in.post("/api/alerts/link", json={"chat_id": "4242"}).json()
    assert s["chatLinked"] and s["chatName"] == "Gandy (@gandy)"
    assert telegram.sent[-1]["chat_id"] == "4242" and "linked" in telegram.sent[-1]["text"]
    assert signed_in.post("/api/alerts/test").status_code == 200
    assert "Test message" in telegram.sent[-1]["text"]
    s = signed_in.patch("/api/alerts", json={"kinds": ["problems"]}).json()
    assert s["kinds"] == ["problems"]
    assert signed_in.patch("/api/alerts", json={"kinds": ["everything"]}).status_code == 422


def test_queue_sends_skips_and_retries(signed_in, telegram):
    signed_in.post("/api/alerts/link", json={"chat_id": "4242"})
    uid = _user_id()
    sent_before = len(telegram.sent)
    _queue(uid, "trades", "Paper trade closed")
    assert _send()["sent"] == 1 and telegram.sent[-1]["text"] == "Paper trade closed"
    signed_in.patch("/api/alerts", json={"kinds": ["problems"]})
    _queue(uid, "trades", "not wanted")
    _queue(None, "problems", "Backup problem")  # for everyone
    out = _send()
    assert out == {"sent": 1, "skipped": 1, "failed": 0}
    assert [m["text"] for m in telegram.sent[sent_before:]] == ["Paper trade closed", "Backup problem"]
    telegram.fail = True
    _queue(uid, "problems", "retry me")
    for _ in range(alerts.MAX_ATTEMPTS):
        assert _send()["failed"] == 1
    assert _send() == {"sent": 0, "skipped": 0, "failed": 0}  # given up after the last attempt
    recent = signed_in.get("/api/alerts").json()["recent"]
    assert recent[0]["status"] == "failed" and TOKEN not in recent[0]["error"]


def test_not_set_up_means_skipped(signed_in, monkeypatch):
    monkeypatch.setattr(alerts, "get_settings", lambda: SimpleNamespace(telegram_bot_token=""))
    _queue(_user_id(), "trades", "nobody to send to")
    assert _send()["skipped"] == 1
    assert signed_in.post("/api/alerts/test").status_code == 400


# --- Which events alert -------------------------------------------------------------------------------

NOW = int(time.time())


@pytest.fixture()
def market(monkeypatch):
    m = SimpleNamespace(mid=1.25, bars=[])

    def quote(db, symbol):
        bars = m.bars or [Bar(NOW - 60, m.mid, m.mid, m.mid, m.mid, 0)]
        return paper.Quote(m.mid, NOW, "oanda", False, bars, "1m")

    monkeypatch.setattr(paper, "latest_quote", quote)
    return m


def _queued():
    from app.db import new_session
    from app.models import Alert

    db = new_session()
    try:
        return [(a.kind, a.text) for a in db.query(Alert).order_by(Alert.id)]
    finally:
        db.close()


def _cfd(client):
    return next(a for a in client.get("/api/paper/accounts").json()["accounts"] if a["mode"] == "cfd")["id"]


def test_trade_events_alert(signed_in, market):
    from app.db import new_session
    from app.models import PaperAccount, PaperTrade

    acct_id = _cfd(signed_in)
    db = new_session()
    acct = db.get(PaperAccount, acct_id)
    auto = paper.place(db, acct, "GBP_USD", 1, 1.24, 1.27, "1h", source="auto", strategy="breakout")
    opened = _queued()
    assert opened[-1][0] == "trades" and "opened (automatic)" in opened[-1][1] and "20-day breakout" in opened[-1][1]
    # A stop-loss hit by the worker alerts...
    market.mid = 1.239
    market.bars = [Bar(NOW + 60, 1.25, 1.25, 1.238, 1.239, 0)]
    assert paper.check_trade(db, acct, db.get(PaperTrade, auto.id), paper.latest_quote(db, None))
    db.commit()
    assert "closed: Stop-loss" in _queued()[-1][1]
    db.close()
    # ...but a trade you close yourself doesn't.
    market.mid, market.bars = 1.25, []
    r = signed_in.post("/api/paper/orders", json={"account_id": acct_id, "symbol": "GBP_USD", "side": "long", "stop": 1.24,
                                                  "target": 1.27, "timeframe": "1h", "trend": "up",
                                                  "reason": "Testing alerts on manual trades", "mood": "calm", "confirmed": True})
    n = len(_queued())
    signed_in.post(f"/api/paper/trades/{r.json()['trade']['id']}/close")
    assert len(_queued()) == n


def test_account_pause_and_backup_failure_alert(signed_in, market):
    from app import backup
    from app.db import new_session
    from app.models import PaperAccount

    db = new_session()
    acct = db.get(PaperAccount, _cfd(signed_in))
    acct.peak_equity = 300.0
    paper.update_limits(acct, 200.0, db)
    db.commit()
    db.close()
    kind, text = _queued()[-1]
    assert kind == "problems" and "Paper account paused" in text
    backup.record(False, detail="The backup storage refused the upload (403 AccessDenied).")
    kind, text = _queued()[-1]
    assert kind == "problems" and "403" in text
