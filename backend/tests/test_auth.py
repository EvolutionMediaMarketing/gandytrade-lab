import time

import pyotp


def test_api_requires_sign_in(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/catalogue").status_code == 401


def test_login_with_password_and_code(client, user):
    code = pyotp.TOTP(user["secret"]).now()
    r = client.post("/api/auth/login", json={"username": "gandy", "password": user["password"], "code": code})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json() == {"username": "gandy"}


def test_wrong_code_rejected(client, user):
    r = client.post("/api/auth/login", json={"username": "gandy", "password": user["password"], "code": "000000"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password_rejected(client, user):
    code = pyotp.TOTP(user["secret"]).now()
    r = client.post("/api/auth/login", json={"username": "gandy", "password": "nope nope nope", "code": code})
    assert r.status_code == 401


def test_code_cannot_be_reused(client, user):
    code = pyotp.TOTP(user["secret"]).now()
    body = {"username": "gandy", "password": user["password"], "code": code}
    assert client.post("/api/auth/login", json=body).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json=body).status_code == 401


def test_lockout_after_repeated_failures(client, user):
    bad = {"username": "gandy", "password": "wrong password!!", "code": "123456"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    good = {"username": "gandy", "password": user["password"], "code": pyotp.TOTP(user["secret"]).now()}
    assert client.post("/api/auth/login", json=good).status_code == 429


def test_logout(signed_in):
    assert signed_in.post("/api/auth/logout").status_code == 200
    assert signed_in.get("/api/auth/me").status_code == 401


def test_post_without_page_header_is_blocked(client, user):
    r = client.post(
        "/api/auth/login",
        json={"username": "gandy", "password": user["password"], "code": "123456"},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403


def test_noindex_and_robots(client):
    r = client.get("/")
    assert r.headers["X-Robots-Tag"].startswith("noindex")
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


def test_short_password_refused():
    import pytest

    from app.security import hash_password

    with pytest.raises(ValueError):
        hash_password("short")
