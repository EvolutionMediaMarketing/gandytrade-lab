"""Background worker: watches open paper trades and closes them at their stop-loss or target,
runs automatic paper trading (strategies trading paper accounts by their own rules), strategy
research scans, and sends Telegram alerts.

Runs in its own container (`gandytrade-worker`) with the same code and database as the app:

    python -m app.worker

Each market is checked on a schedule that suits its free data allowance:
  * OANDA practice (forex, metals, commodities, indices): every minute, on 1-minute candles
  * Twelve Data (US shares): every 10 minutes, on 15-minute candles (the free plan allows 800 requests a day)
  * Alpha Vantage (UK shares): every 6 hours, on daily candles (25 requests a day)
"""

import logging
import signal
import time

from sqlalchemy import select

from .db import new_session, wait_for_database
from .logsafe import install_log_redaction
from .market.directory import lookup
from .market.providers.base import ProviderError
from .models import PaperAccount, PaperTrade
from . import alerts, research, reviews
from .paper import auto
from .paper import service as paper

log = logging.getLogger("gandytrade.worker")
LOOP_SECONDS = 60
CHECK_EVERY = {"oanda": 60, "twelvedata": 600, "alphavantage": 6 * 3600}

_stop = False


def _handle_stop(*_args) -> None:
    global _stop
    _stop = True


def run_once(last_checked: dict[str, float], last_looked: dict | None = None) -> dict:
    """One pass over every open paper trade. Returns counts, for the log and tests."""
    db = new_session()
    stats = {"checked": 0, "closed": 0, "errors": 0}
    try:
        trades = list(db.scalars(select(PaperTrade).where(PaperTrade.status == "open")))
        by_symbol: dict[str, list[PaperTrade]] = {}
        for t in trades:
            by_symbol.setdefault(t.symbol, []).append(t)
        now = time.time()
        touched_accounts: set[int] = set()
        for code, group in by_symbol.items():
            try:
                symbol = lookup(db, code)
            except ValueError:
                stats["errors"] += 1
                continue
            if now - last_checked.get(code, 0) < CHECK_EVERY.get(symbol.provider, 60):
                continue
            last_checked[code] = now
            try:
                q = paper.latest_quote(db, symbol)
            except (paper.PaperError, ProviderError) as exc:
                log.warning("No price for %s: %s", code, exc)
                stats["errors"] += 1
                continue
            for t in group:
                # Lock and re-read: you may have closed it from the browser a moment ago.
                t = db.get(PaperTrade, t.id, with_for_update=True, populate_existing=True)
                if t is None or t.status != "open":
                    continue
                acct = db.get(PaperAccount, t.account_id)
                stats["checked"] += 1
                if paper.check_trade(db, acct, t, q):
                    stats["closed"] += 1
                    log.info("Closed paper trade %s on %s: %s", t.id, code, t.exit_reason)
                touched_accounts.add(acct.id)
            db.commit()
        # Automatic runs act on newly finished candles (after stops above, as in the backtester).
        try:
            touched_accounts |= auto.run_due(db, last_looked if last_looked is not None else {}, now)
        except Exception:
            db.rollback()
            log.exception("Automatic trading pass failed")
            stats["errors"] += 1
        # Strategy research: a slice of any scan in progress, and the weekly scan when it's due.
        try:
            research.schedule_weekly(db)
            research.work(db)
        except Exception:
            db.rollback()
            log.exception("Research pass failed")
            stats["errors"] += 1
        # Keep each account's high point, day-start figure and drawdown limit up to date.
        quotes: dict = {}
        for acct in list(db.scalars(select(PaperAccount).where(PaperAccount.archived.is_(False)))):
            if acct.id in touched_accounts:
                equity = paper.account_state(db, acct, quotes)["equity"]
            elif not paper.open_trades(db, acct):
                equity = acct.cash
            else:
                continue  # its markets weren't due a check this pass
            paper.update_limits(acct, equity, db)
        db.commit()
        # Sunday evening: a nudge if this week's review isn't done.
        try:
            reviews.remind(db)
        except Exception:
            db.rollback()
            log.exception("Review reminder failed")
        # Send any alerts the steps above queued (Telegram trouble never stops the rest).
        try:
            alerts.send_pending(db)
        except Exception:
            db.rollback()
            log.exception("Sending alerts failed")
    except Exception:
        db.rollback()
        log.exception("Worker pass failed")
        stats["errors"] += 1
    finally:
        db.close()
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_log_redaction()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    wait_for_database()
    log.info("Paper trading worker started")
    last_checked: dict[str, float] = {}
    last_looked: dict[int, float] = {}
    while not _stop:
        started = time.time()
        stats = run_once(last_checked, last_looked)
        if stats["closed"] or stats["errors"]:
            log.info("Pass: %s", stats)
        while not _stop and time.time() - started < LOOP_SECONDS:
            time.sleep(1)
    log.info("Paper trading worker stopped")


if __name__ == "__main__":
    main()
