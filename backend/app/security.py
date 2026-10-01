"""Passwords, two-factor codes and login lockout."""

import time
from datetime import datetime, timedelta, timezone

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import get_settings
from .models import User

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(username: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="GandyTrade Lab")


def check_totp(user: User, code: str, now: float | None = None) -> bool:
    """Accept the current 30-second code (or one step either side), never the same step twice."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(user.totp_secret)
    now = time.time() if now is None else now
    current_step = int(now // 30)
    for step in (current_step - 1, current_step, current_step + 1):
        if step <= user.totp_last_step:
            continue
        if totp.at(step * 30) == code:
            user.totp_last_step = step
            return True
    return False


def is_locked(user: User, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    locked_until = user.locked_until
    if locked_until is None:
        return False
    if locked_until.tzinfo is None:  # SQLite returns naive datetimes
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > now


def register_failure(user: User) -> None:
    settings = get_settings()
    user.failed_logins += 1
    if user.failed_logins >= settings.max_failed_logins:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0


def register_success(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None
