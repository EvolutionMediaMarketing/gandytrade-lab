"""Command-line tools, run on the server inside the app container.

    python -m app.cli create-user      first-time setup of your login
    python -m app.cli reset-2fa        new two-factor secret (e.g. new phone)
    python -m app.cli set-password     change your password
    python -m app.cli unlock           clear a sign-in lockout
    python -m app.cli sign-out-everywhere   end every signed-in session now
    python -m app.cli audit            show recent sign-ins and security events
    python -m app.cli refresh-markets  download the full market lists now
"""

import argparse
import getpass
import io
import sys

import qrcode
from sqlalchemy import func, select

from . import sessions
from .db import init_db, new_session, wait_for_database
from .models import SecurityEvent, User
from .security import hash_password, new_totp_secret, provisioning_uri


def _ask_password() -> str:
    while True:
        first = getpass.getpass("New password (12+ characters): ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            print("Passwords don't match, try again.")
            continue
        try:
            return hash_password(first)
        except ValueError as exc:
            print(exc)


def _show_totp(username: str, secret: str) -> None:
    uri = provisioning_uri(username, secret)
    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make(fit=True)
    out = io.StringIO()
    qr.print_ascii(out=out, invert=True)
    print("\nScan this QR code with your authenticator app:\n")
    print(out.getvalue())
    print("Or add it manually with this secret key:", secret)
    print("Account name:", username, " Issuer: GandyTrade Lab\n")


def _get_user(session, username: str | None) -> User:
    if username:
        user = session.scalar(select(User).where(User.username == username))
    else:
        user = session.scalar(select(User))
    if user is None:
        sys.exit("No user found. Run create-user first.")
    return user


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--username", default=None)
    for name in ("reset-2fa", "set-password", "unlock", "sign-out-everywhere"):
        p = sub.add_parser(name)
        p.add_argument("--username", default=None)
    sub.add_parser("refresh-markets")
    audit = sub.add_parser("audit")
    audit.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    wait_for_database()
    init_db()
    session = new_session()
    try:
        if args.command == "create-user":
            if session.scalar(select(func.count()).select_from(User)):
                sys.exit("A user already exists. This lab is single-user.")
            username = args.username or input("Username: ").strip()
            if not username:
                sys.exit("Username can't be empty.")
            password_hash = _ask_password()
            secret = new_totp_secret()
            session.add(User(username=username, password_hash=password_hash, totp_secret=secret))
            sessions.audit(session, "user_created", username, "server")
            session.commit()
            _show_totp(username, secret)
            print("User created. Sign in at https://gandytrade.co.uk")
        elif args.command == "reset-2fa":
            user = _get_user(session, args.username)
            user.totp_secret = new_totp_secret()
            user.totp_last_step = 0
            ended = sessions.end_all(session, user.id)
            sessions.audit(session, "2fa_reset", user.username, "server", f"{ended} session(s) signed out")
            session.commit()
            _show_totp(user.username, user.totp_secret)
            print("Two-factor reset. Remove the old entry from your authenticator app.")
        elif args.command == "set-password":
            user = _get_user(session, args.username)
            user.password_hash = _ask_password()
            ended = sessions.end_all(session, user.id)
            sessions.audit(session, "password_changed", user.username, "server", f"{ended} session(s) signed out")
            session.commit()
            print("Password changed. Every browser has been signed out.")
        elif args.command == "unlock":
            user = _get_user(session, args.username)
            user.failed_logins = 0
            user.locked_until = None
            sessions.audit(session, "unlocked", user.username, "server")
            session.commit()
            print("Sign-in unlocked.")
        elif args.command == "sign-out-everywhere":
            user = _get_user(session, args.username)
            ended = sessions.end_all(session, user.id)
            sessions.audit(session, "signed_out_everywhere", user.username, "server", f"{ended} session(s)")
            session.commit()
            print(f"Signed out {ended} session(s).")
        elif args.command == "refresh-markets":
            from .market import directory

            result = directory.refresh(session, force=True)
            if not result:
                print("No data keys set, so there's no market list to download.")
            for provider, outcome in result.items():
                print(f"{provider}: {outcome} markets" if isinstance(outcome, int) else f"{provider}: {outcome}")
            for cls, n in sorted(directory.counts(session).items()):
                print(f"  {cls:<10} {n}")
        elif args.command == "audit":
            rows = session.scalars(
                select(SecurityEvent).order_by(SecurityEvent.at.desc()).limit(max(1, min(args.limit, 1000)))
            ).all()
            if not rows:
                print("No security events yet.")
            for e in reversed(rows):
                when = e.at.strftime("%Y-%m-%d %H:%M:%S UTC")
                print(f"{when}  {e.event:<22} {e.username:<16} {e.ip:<16} {e.detail}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
