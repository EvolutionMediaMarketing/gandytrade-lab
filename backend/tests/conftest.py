import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("GT_COOKIE_SECURE", "false")
    monkeypatch.setenv("GT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GT_FRONTEND_DIR", str(tmp_path / "frontend"))
    monkeypatch.setenv("GT_OANDA_TOKEN", "")
    monkeypatch.setenv("GT_TWELVEDATA_KEY", "")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<html>lab</html>")

    from app import config, db

    config.get_settings.cache_clear()
    db.reset_engine()

    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-Requested-With": "gandytrade"})
        yield c
    db.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture()
def user(client):
    from app.db import new_session
    from app.models import User
    from app.security import hash_password, new_totp_secret

    session = new_session()
    secret = new_totp_secret()
    u = User(username="gandy", password_hash=hash_password("correct horse battery"), totp_secret=secret)
    session.add(u)
    session.commit()
    session.close()
    return {"username": "gandy", "password": "correct horse battery", "secret": secret}


@pytest.fixture()
def signed_in(client, user):
    import pyotp

    code = pyotp.TOTP(user["secret"]).now()
    r = client.post("/api/auth/login", json={"username": user["username"], "password": user["password"], "code": code})
    assert r.status_code == 200, r.text
    return client
