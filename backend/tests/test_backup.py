"""Off-server backups: encryption round trip, the upload signature, what gets recorded, and status."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app import backup
from app.market.providers import http as safe_http

PASS = "correct horse battery staple 2026"


def _settings(**kw):
    base = {"backup_endpoint": "s3.eu-central-003.backblazeb2.com", "backup_bucket": "gt-backups",
            "backup_key_id": "KEYID123", "backup_key": "SECRETxyz", "backup_passphrase": PASS}
    base.update(kw)
    return SimpleNamespace(**base)


def test_encrypt_round_trip_and_wrong_passphrase():
    data = b"-- PostgreSQL dump\n" * 500
    blob = backup.encrypt(data, PASS)
    assert blob.startswith(b"GTB1") and data not in blob
    assert backup.decrypt(blob, PASS) == data
    assert backup.encrypt(data, PASS) != blob  # fresh salt and nonce every time
    with pytest.raises(backup.BackupError, match="wrong passphrase"):
        backup.decrypt(blob, PASS + "x")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(backup.BackupError):
        backup.decrypt(tampered, PASS)
    with pytest.raises(backup.BackupError, match="at least"):
        backup.encrypt(data, "short")


def test_signature_matches_the_reference_library():
    # Expected value produced by botocore's S3SigV4Auth for the same request.
    now = datetime(2026, 10, 2, 12, 37, 39, tzinfo=timezone.utc)
    h = backup.signed_put_headers("s3.eu-central-003.backblazeb2.com", "eu-central-003",
                                  "/my-bucket/nightly/2026/10/gandytrade-20261002-021700.sql.gz.enc",
                                  b"hello encrypted world" * 100, "KEYID123", "SECRETxyz", now)
    assert h["Authorization"].endswith("Signature=be1aeb0c2dcda9d5ef4947efc0cb2d3da4c5cf867315dc95999fe2bc472d0152")
    assert "Credential=KEYID123/20261002/eu-central-003/s3/aws4_request" in h["Authorization"]


def test_only_backblaze_s3_hosts_are_added_to_the_allowlist(monkeypatch):
    assert safe_http.host_allowed("s3.eu-central-003.backblazeb2.com")
    assert safe_http.host_allowed("s3.us-west-004.backblazeb2.com")
    for bad in ("evil.com", "s3.eu-central-003.backblazeb2.com.evil.com", "api.backblazeb2.com", "s3.amazonaws.com"):
        assert not safe_http.host_allowed(bad)
    with pytest.raises(backup.BackupError, match="should look like"):
        monkeypatch.setattr(backup, "get_settings", lambda: _settings(backup_endpoint="https://evil.example.com"))
        backup._endpoint()


@pytest.fixture()
def storage(monkeypatch):
    """A fake bucket that records uploads (and can refuse them)."""
    got = {"puts": [], "status": 200}

    def handler(request: httpx.Request):
        got["puts"].append(request)
        if got["status"] != 200:
            return httpx.Response(got["status"], text="<Error><Code>AccessDenied</Code></Error>")
        return httpx.Response(200)

    def client(timeout=20):
        return httpx.Client(transport=httpx.MockTransport(handler), event_hooks={"request": [safe_http.check_request]})

    monkeypatch.setattr(safe_http, "safe_client", client)
    monkeypatch.setattr(backup, "get_settings", lambda: _settings())
    return got


def _runs():
    from app.db import new_session
    from app.models import BackupRun

    db = new_session()
    try:
        return [(r.ok, r.uploaded, r.restore_tested, r.detail, r.name) for r in db.query(BackupRun).order_by(BackupRun.id)]
    finally:
        db.close()


def test_nightly_encrypts_uploads_and_records(client, storage):
    data = b"-- dump --" * 1000
    msg = backup.nightly("gandytrade-20261002-021700.sql.gz", data, restore_tested=True)
    assert "uploaded" in msg
    put = storage["puts"][0]
    assert put.method == "PUT" and put.url.host == "s3.eu-central-003.backblazeb2.com"
    assert put.url.path.startswith("/gt-backups/nightly/") and put.url.path.endswith(".sql.gz.enc")
    assert backup.decrypt(put.content, PASS) == data  # what left the server decrypts back to the dump
    assert b"-- dump --" not in put.content
    assert "SECRETxyz" not in str(put.headers)
    ok, uploaded, tested, detail, name = _runs()[-1]
    assert ok and uploaded and tested and name.startswith("nightly/")


def test_refused_upload_is_recorded_without_secrets(client, storage):
    storage["status"] = 403
    with pytest.raises(backup.BackupError, match="403 AccessDenied"):
        backup.nightly("x.sql.gz", b"data", restore_tested=True)
    ok, uploaded, _, detail, _ = _runs()[-1]
    assert not ok and not uploaded and "SECRETxyz" not in detail and PASS not in detail


def test_without_settings_backups_stay_on_the_server(client, monkeypatch):
    monkeypatch.setattr(backup, "get_settings", lambda: _settings(backup_bucket=""))
    assert "server only" in backup.nightly("x.sql.gz", b"data", restore_tested=True)
    ok, uploaded, _, detail, _ = _runs()[-1]
    assert ok and not uploaded and "aren't set up" in detail


def test_status_and_overdue(signed_in, monkeypatch):
    from app.db import new_session
    from app.models import BackupRun

    s = signed_in.get("/api/backup/status").json()
    assert s["runs"] == [] and not s["overdue"]  # nothing has run yet: no alarm
    db = new_session()
    db.add(BackupRun(ok=True, name="old", size=1, restore_tested=True, uploaded=True, detail="",
                     at=datetime.now(timezone.utc) - timedelta(hours=60)))
    db.commit()
    assert signed_in.get("/api/backup/status").json()["overdue"]
    db.add(BackupRun(ok=True, name="new", size=1, restore_tested=True, uploaded=True, detail=""))
    db.commit()
    db.close()
    s = signed_in.get("/api/backup/status").json()
    assert not s["overdue"] and s["runs"][0]["name"] == "new"
