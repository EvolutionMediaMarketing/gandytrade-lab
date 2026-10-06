"""Monthly top-ups and one-off deposits on paper accounts.

Real saving plans pay in a little each month, so paper accounts can too. Money paid in is never profit:

  * the account's return is profit ÷ everything paid in (start plus deposits);
  * the drawdown limit, the daily loss limit and the dashboard's "worst fall" measure the fall in
    *growth*, so a top-up can't hide a fall. When money arrives, the high point and the day's
    starting value are scaled up by the same proportion, which leaves the fall in % exactly as it was
    (10% down before a top-up is still 10% down after it).

A top-up never lifts a pause: a paused account stays paused until you've reviewed it.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import alerts
from ..models import PaperAccount, PaperDeposit, User
from . import service as paper

MAX_DEPOSIT = 100_000.0
MAX_DAY = 28  # every month has a 28th


def deposit(db: Session, acct: PaperAccount, amount: float, kind: str = "manual",
            when: datetime | None = None) -> PaperDeposit:
    """Add pretend money to an account, keeping its limits measured on growth."""
    if not amount or amount <= 0 or amount != amount:
        raise paper.PaperError("Enter an amount above £0.")
    if amount > MAX_DEPOSIT:
        raise paper.PaperError(f"That's more than £{MAX_DEPOSIT:,.0f} in one go.")
    if acct.archived:
        raise paper.PaperError("This paper account is archived.")
    equity = paper.account_state(db, acct)["equity"]
    paper.update_limits(acct, equity, db)  # bring today's figures up to date before the money arrives
    factor = (equity + amount) / equity if equity > 0 else 1.0
    acct.peak_equity = acct.peak_equity * factor if equity > 0 else max(acct.peak_equity, amount)
    acct.day_start_equity = acct.day_start_equity * factor if equity > 0 else acct.day_start_equity + amount
    acct.cash += amount
    acct.deposits = (acct.deposits or 0.0) + amount
    row = PaperDeposit(account_id=acct.id, amount=round(amount, 2), kind=kind, at=when or datetime.now(timezone.utc))
    db.add(row)
    return row


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(paper.UK)).astimezone(paper.UK).strftime("%Y-%m")


def set_monthly(db: Session, acct: PaperAccount, amount: float, day: int, now: datetime | None = None) -> None:
    """Switch the monthly top-up on (amount > 0) or off (0). Starting part-way through a month never adds money
    straight away: if this month's day has already passed, the first top-up comes next month."""
    if amount < 0 or amount != amount or amount > MAX_DEPOSIT:
        raise paper.PaperError(f"Choose a monthly amount from £0 (off) to £{MAX_DEPOSIT:,.0f}.")
    if not 1 <= int(day) <= MAX_DAY:
        raise paper.PaperError(f"Choose a day from 1 to {MAX_DAY}, so it happens every month.")
    uk = (now or datetime.now(paper.UK)).astimezone(paper.UK)
    starting = amount > 0 and not acct.topup_amount
    moved = int(day) != acct.topup_day
    acct.topup_amount, acct.topup_day = round(float(amount), 2), int(day)
    if (starting or moved) and uk.day >= acct.topup_day:
        acct.topup_last_month = month_key(uk)


def next_topup(acct: PaperAccount, now: datetime | None = None) -> str | None:
    """The UK date of the next monthly top-up (yyyy-mm-dd), or None when it's off."""
    if not acct.topup_amount:
        return None
    uk = (now or datetime.now(paper.UK)).astimezone(paper.UK)
    if acct.topup_last_month != month_key(uk):
        if uk.day >= acct.topup_day:
            return uk.strftime("%Y-%m-%d")  # due now: the worker adds it within a minute
        return f"{uk.year:04d}-{uk.month:02d}-{acct.topup_day:02d}"
    year, month = (uk.year + 1, 1) if uk.month == 12 else (uk.year, uk.month + 1)
    return f"{year:04d}-{month:02d}-{acct.topup_day:02d}"


def run_due(db: Session, now: datetime | None = None) -> int:
    """Add any monthly top-ups that are due (the worker calls this every pass). Returns how many were added."""
    uk = (now or datetime.now(paper.UK)).astimezone(paper.UK)
    key = month_key(uk)
    added = 0
    for acct in db.scalars(select(PaperAccount).where(PaperAccount.topup_amount > 0, PaperAccount.archived.is_(False))):
        if acct.topup_last_month == key or uk.day < acct.topup_day:
            continue
        acct = db.get(PaperAccount, acct.id, with_for_update=True, populate_existing=True)
        if acct.topup_last_month == key:
            continue
        try:
            deposit(db, acct, acct.topup_amount, "monthly")
        except paper.PaperError:
            continue
        acct.topup_last_month = key
        alerts.notify(db, acct.user_id, "trades",
                      f"Monthly top-up: £{acct.topup_amount:,.2f} added to {acct.name}"
                      + (" (still paused until you review it)" if acct.halted else ""))
        db.commit()
        added += 1
    return added


def history(db: Session, acct: PaperAccount) -> list[PaperDeposit]:
    return list(db.scalars(select(PaperDeposit).where(PaperDeposit.account_id == acct.id).order_by(PaperDeposit.at)))


def add_now(db: Session, user: User, account_id: int, amount: float) -> PaperDeposit:
    acct = paper.get_account(db, user, account_id)
    row = deposit(db, acct, amount, "manual")
    db.commit()
    return row
