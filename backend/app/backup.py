"""Off-server backups: encrypt a database dump and upload it to a Backblaze B2 bucket.

The nightly job (deploy/scripts/backup.sh) dumps the database, proves the dump restores into a
scratch database, then pipes it to this module inside a throwaway copy of the app container:

    python -m app.backup nightly NAME [--restore-tested]   < dump.sql.gz   (encrypt, upload, record)
    python -m app.backup decrypt                          < file.enc > dump.sql.gz
    python -m app.backup test                              (check the bucket settings with a tiny upload)

Encryption: AES-256-GCM with a key derived from GT_BACKUP_PASSPHRASE by scrypt, so the storage
company only ever holds scrambled data. Uploads use B2's S3-compatible API, signed with the
bucket-limited, write-only key. Nothing here can read or delete what's already in the bucket.
"""

import hashlib
import hmac
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

MAGIC = b"GTB1"
SALT_LEN, NONCE_LEN = 16, 12
SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024}
MIN_PASSPHRASE = 20
OVERDUE_HOURS = 48
PREFIX = "nightly"


class BackupError(RuntimeError):
    """A problem in plain words; never contains a key or the passphrase."""


# --- Encryption ----------------------------------------------------------------------------------

def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, dklen=32, **SCRYPT)


def encrypt(data: bytes, passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"The backup passphrase must be at least {MIN_PASSPHRASE} characters.")
    salt, nonce = os.urandom(SALT_LEN), os.urandom(NONCE_LEN)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise BackupError("This isn't a GandyTrade backup file.")
    salt = blob[4:4 + SALT_LEN]
    nonce = blob[4 + SALT_LEN:4 + SALT_LEN + NONCE_LEN]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[4 + SALT_LEN + NONCE_LEN:], MAGIC)
    except Exception as exc:  # wrong passphrase or a damaged file look the same, by design
        raise BackupError("Couldn't decrypt: wrong passphrase, or the file is damaged.") from exc


# --- Uploading (S3-compatible, signature version 4) -----------------------------------------------

ENDPOINT = re.compile(r"^s3\.([a-z]{2}-[a-z]+-\d{3})\.backblazeb2\.com$")


def configured() -> bool:
    s = get_settings()
    return all([s.backup_endpoint, s.backup_bucket, s.backup_key_id, s.backup_key, s.backup_passphrase])


def _endpoint() -> tuple[str, str]:
    host = get_settings().backup_endpoint.strip().removeprefix("https://").rstrip("/")
    m = ENDPOINT.match(host)
    if not m:
        raise BackupError("GT_BACKUP_ENDPOINT should look like s3.eu-central-003.backblazeb2.com (from the bucket's page).")
    return host, m.group(1)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signed_put_headers(host: str, region: str, path: str, body: bytes, key_id: str, secret: str,
                       now: datetime | None = None) -> dict[str, str]:
    """Headers for a signed PUT of `body` to https://host/path (path already URL-encoded)."""
    now = now or datetime.now(timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    payload = hashlib.sha256(body).hexdigest()
    signed = "host;x-amz-content-sha256;x-amz-date"
    canonical = "\n".join(["PUT", path, "", f"host:{host}", f"x-amz-content-sha256:{payload}", f"x-amz-date:{amz_date}",
                           "", signed, payload])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(_sign(_sign(_sign(("AWS4" + secret).encode(), day), region), "s3"), "aws4_request")
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "x-amz-date": amz_date, "x-amz-content-sha256": payload,
        "Authorization": f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={signature}",
    }


def upload(name: str, body: bytes) -> None:
    from .market.providers.http import safe_client

    s = get_settings()
    host, region = _endpoint()
    path = "/" + quote(s.backup_bucket.strip(), safe="") + "/" + quote(name, safe="/-_.~")
    headers = signed_put_headers(host, region, path, body, s.backup_key_id.strip(), s.backup_key.strip())
    headers["Content-Type"] = "application/octet-stream"
    try:
        with safe_client(timeout=120) as client:
            r = client.put(f"https://{host}{path}", content=body, headers=headers)
    except Exception as exc:
        raise BackupError(f"Couldn't reach the backup storage ({exc.__class__.__name__}).") from exc
    if r.status_code != 200:
        code = re.search(r"<Code>([^<]{1,60})</Code>", r.text or "")
        hint = {403: " Check the key ID, the key, and that the key is allowed to write to this bucket.",
                404: " Check the bucket name."}.get(r.status_code, "")
        raise BackupError(f"The backup storage refused the upload ({r.status_code} {code.group(1) if code else ''}).{hint}")


# --- Recording and status ---------------------------------------------------------------------------

def record(ok: bool, name: str = "", size: int = 0, restore_tested: bool = False, uploaded: bool = False, detail: str = "") -> None:
    from .db import new_session
    from .models import BackupRun

    db = new_session()
    try:
        db.add(BackupRun(ok=ok, name=name[:160], size=size, restore_tested=restore_tested, uploaded=uploaded,
                         detail=detail[:255]))
        if not ok:
            from .alerts import notify

            notify(db, None, "problems", f"GandyTrade backup problem\n{detail[:300] or 'The nightly backup failed.'}\n"
                                         "See Settings → Backups.")
        db.commit()
    finally:
        db.close()


def status(db) -> dict:
    from sqlalchemy import select

    from .models import BackupRun

    runs = db.scalars(select(BackupRun).order_by(BackupRun.at.desc()).limit(10)).all()
    last_ok = next((r for r in runs if r.ok), None)

    def at(r):
        return r.at if r.at.tzinfo else r.at.replace(tzinfo=timezone.utc)

    overdue = bool(runs) and (last_ok is None or datetime.now(timezone.utc) - at(last_ok) > timedelta(hours=OVERDUE_HOURS))
    return {
        "offServer": configured(),
        "overdue": overdue,
        "lastOk": at(last_ok).isoformat() if last_ok else None,
        "runs": [{"at": at(r).isoformat(), "ok": r.ok, "name": r.name, "size": r.size, "restoreTested": r.restore_tested,
                  "uploaded": r.uploaded, "detail": r.detail} for r in runs],
    }


# --- Command line ------------------------------------------------------------------------------------

def nightly(name: str, data: bytes, restore_tested: bool) -> str:
    """Encrypt and upload one dump (if off-server backups are set up), and record the result."""
    if not data:
        record(False, name, detail="The database dump was empty.")
        raise BackupError("The database dump was empty.")
    if not configured():
        record(restore_tested, name, len(data), restore_tested, False,
               "Kept on the server only: off-server backups aren't set up yet." if restore_tested
               else "The test restore failed; see the server log.")
        return "Saved on the server only (off-server backups not set up)."
    s = get_settings()
    try:
        blob = encrypt(data, s.backup_passphrase)
        if decrypt(blob, s.backup_passphrase) != data:  # never upload something that won't come back
            raise BackupError("The encrypted copy didn't decrypt back to the original.")
        remote = f"{PREFIX}/{datetime.now(timezone.utc):%Y/%m}/{name}.enc"
        upload(remote, blob)
    except BackupError as exc:
        record(False, name, len(data), restore_tested, False, str(exc))
        raise
    ok = restore_tested
    record(ok, remote, len(blob), restore_tested, True,
           "Encrypted and copied off the server." if ok else "Copied off the server, but the test restore failed.")
    return f"Encrypted and uploaded as {remote} ({len(blob):,} bytes)."


def main(argv: list[str]) -> int:
    from .logsafe import install_log_redaction

    install_log_redaction()
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "nightly" and len(argv) >= 3:
            print(nightly(os.path.basename(argv[2]), sys.stdin.buffer.read(), "--restore-tested" in argv))
        elif cmd == "decrypt":
            sys.stdout.buffer.write(decrypt(sys.stdin.buffer.read(), get_settings().backup_passphrase))
        elif cmd == "test":
            if not configured():
                raise BackupError("Off-server backups aren't set up: add the GT_BACKUP_ settings to app.env.")
            s = get_settings()
            blob = encrypt(b"GandyTrade backup test " + str(time.time()).encode(), s.backup_passphrase)
            upload(f"test/connection-check-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.enc", blob)
            print("Connection OK: a small encrypted test file was uploaded to the bucket's test/ folder.")
        elif cmd == "record-failure":
            record(False, detail=" ".join(argv[2:])[:255] or "The nightly backup failed on the server.")
        else:
            print(__doc__)
            return 2
    except BackupError as exc:
        print(f"Backup problem: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
