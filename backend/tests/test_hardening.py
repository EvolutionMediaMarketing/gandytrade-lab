"""Security hardening: proxy secret, server-side sessions, audit log, outbound allowlist, log redaction."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pyotp
import pytest

from app.logsafe import RedactingFilter, redact
from app.market.providers import http as safe_http
from app.market.providers import twelvedata
from app.market.symbols import get_symbol
from app.market.timeframes import get_timeframe


def _sign_in(client, user):
    code = pyotp.TOTP(user["secret"]).now()
    body = {"username": user["username"], "password": user["password"], "code": code}
    assert client.post("/api/auth/login", json=body).status_code == 200


def _session_row():
    from sqlalchemy import select

    from app.db import new_session
    from app.models import LoginSession

    db = new_session()
    return db, db.scalar(select(LoginSession))


def _events():
    from sqlalchemy import select

    from app.db import new_session
    from app.models import SecurityEvent

    db = new_session()
    try:
        return [e.event for e in db.scalars(select(SecurityEvent).order_by(SecurityEvent.id))]
    finally:
        db.close()


# --- Proxy secret ---------------------------------------------------------------

@pytest.fixture()
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_PROXY_SECRET", "s3cret-from-apache")
    monkeypatch.setenv("GT_DATABASE_URL", f"sqlite:///{tmp_path / 'g.db'}")
    monkeypatch.setenv("GT_COOKIE_SECURE", "false")
    monkeypatch.setenv("GT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GT_FRONTEND_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from app import config, db
    from app.main import create_app

    config.get_settings.cache_clear()
    db.reset_engine()
    with TestClient(create_app()) as c:
        yield c
    db.reset_engine()
    config.get_settings.cache_clear()


def test_direct_requests_without_proxy_secret_are_refused(gated_client):
    assert gated_client.get("/").status_code == 403
    assert gated_client.get("/api/auth/me").status_code == 403
    assert gated_client.get("/api/auth/me", headers={"X-GT-Proxy": "wrong"}).status_code == 403


def test_requests_through_apache_are_allowed(gated_client):
    r = gated_client.get("/api/auth/me", headers={"X-GT-Proxy": "s3cret-from-apache"})
    assert r.status_code == 401  # reached the app; just not signed in


def test_health_check_stays_open_and_reveals_nothing(gated_client):
    r = gated_client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


# --- Headers ----------------------------------------------------------------------

def test_hsts_and_isolation_headers(client):
    r = client.get("/")
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert '"openapi"' not in client.get("/openapi.json").text  # API schema not published


# --- Sessions -----------------------------------------------------------------------

def test_cookie_holds_only_a_token(client, user):
    _sign_in(client, user)
    db, row = _session_row()
    try:
        assert row is not None and len(row.id) == 64  # stored hashed
    finally:
        db.close()


def test_logout_ends_the_session_server_side(client, user):
    _sign_in(client, user)
    stolen = dict(client.cookies)
    client.post("/api/auth/logout")
    client.cookies.update(stolen)  # replaying the old cookie must not work
    assert client.get("/api/auth/me").status_code == 401


def test_idle_session_expires(client, user):
    _sign_in(client, user)
    db, row = _session_row()
    row.last_active_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.commit()
    db.close()
    assert client.get("/api/auth/me").status_code == 401
    assert "session_expired" in _events()


def test_session_has_absolute_limit(client, user):
    _sign_in(client, user)
    db, row = _session_row()
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=13)
    db.commit()
    db.close()
    assert client.get("/api/auth/me").status_code == 401


def test_background_refresh_does_not_count_as_activity(client, user):
    _sign_in(client, user)
    db, row = _session_row()
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    row.last_active_at = old
    db.commit()
    db.close()
    assert client.get("/api/auth/me", headers={"X-GT-Background": "1"}).status_code == 200
    db, row = _session_row()
    assert abs((row.last_active_at.replace(tzinfo=timezone.utc) - old).total_seconds()) < 1
    db.close()
    assert client.get("/api/auth/me").status_code == 200
    db, row = _session_row()
    assert row.last_active_at.replace(tzinfo=timezone.utc) > old + timedelta(minutes=5)
    db.close()


def test_sign_out_everywhere(client, user):
    _sign_in(client, user)
    from app import sessions
    from app.db import new_session
    from app.models import User

    db = new_session()
    u = db.query(User).one()
    assert sessions.end_all(db, u.id) == 1
    db.commit()
    db.close()
    assert client.get("/api/auth/me").status_code == 401


def test_old_style_cookie_is_not_accepted(client, user):
    # Sessions from before this change held a user id directly; they must not sign anyone in.
    from itsdangerous import TimestampSigner
    import base64
    import json

    payload = base64.b64encode(json.dumps({"uid": 1}).encode())
    client.cookies.set("gt_session", TimestampSigner("test-secret").sign(payload).decode())
    assert client.get("/api/auth/me").status_code == 401


# --- Audit log -------------------------------------------------------------------------

def test_audit_log_records_sign_ins_and_failures(client, user):
    client.post("/api/auth/login", json={"username": "gandy", "password": "bad password!!", "code": "000000"})
    client.post("/api/auth/login", json={"username": "nobody", "password": "x" * 12, "code": "000000"})
    _sign_in(client, user)
    client.post("/api/auth/logout")
    assert _events() == ["login_failed", "login_failed", "login_ok", "logout"]


# --- Outbound allowlist ------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://example.com/",
    "http://api.twelvedata.com/time_series",  # plain HTTP
    "https://api-fxtrade.oanda.com/v3/",  # live host
])
def test_safe_client_refuses_other_hosts(url):
    with safe_http.safe_client() as c, pytest.raises(safe_http.BlockedHost):
        c.get(url)


def test_twelvedata_key_sent_in_header_not_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"status": "ok", "values": []})

    twelvedata.limiter.calls.clear()
    twelvedata.fetch_candles("KEY123456789", get_symbol("AAPL"), get_timeframe("1d"), 5,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert "KEY123456789" not in seen["url"]
    assert seen["auth"] == "apikey KEY123456789"


# --- Log redaction ------------------------------------------------------------------------

def test_redaction():
    assert "abc123" not in redact("GET https://x/y?symbol=A&apikey=abc123&b=1")
    assert "tok3n-value-xyz" not in redact("Authorization: Bearer tok3n-value-xyz")
    assert "dbpass" not in redact("postgresql://gandytrade:dbpass@gandytrade-db:5432/x")


def test_redacting_filter_cleans_records():
    record = logging.LogRecord("httpx", logging.INFO, "", 0, "HTTP Request: GET %s", ("https://a/b?apikey=SECRET99",), None)
    RedactingFilter().filter(record)
    assert "SECRET99" not in record.getMessage()
