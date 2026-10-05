"""Price orders on paper accounts: buy or sell automatically when the market reaches a level you chose.

You place one from the chart's trade planner: the entry line is the level, with a stop-loss (required)
and an optional target. Where the level sits against the price at the time decides the kind:

  * level above the price: buy stop (buy a breakout) or sell limit (sell into a rise)
  * level below the price: buy limit (buy a dip) or sell stop (sell a breakdown)

The worker checks waiting orders every minute, the same way it watches stop-losses. When a candle
reaches the level, the trade opens at the level, or at the candle's open if the price jumped past it
(the honest fill for a stop order; a better one for a limit). It opens through exactly the same
safeguards as a trade you place yourself: the account's pause and daily loss limit, 1% risk sizing on
the balance at that moment, buying power and the open-risk limit. If a safeguard refuses it then, the
order fails, nothing is traded, and an alert says why.

Paper only. Live price orders belong to Phase 6, where they would be held by the broker.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import alerts
from ..market.directory import lookup
from ..market.providers.base import ProviderError
from ..market.timeframes import get_timeframe
from ..models import PaperAccount, PaperTrade, PriceOrder, User
from . import service as paper

MAX_WAITING = 20  # per account
EXPIRIES = ("gtc", "day", "week", "month")
CLOSE_HOUR = 22  # UK time: when "end of day" and "end of week" orders lapse (US markets have closed)


class OrderError(paper.PaperError):
    """A reason the price order can't be placed or changed, in plain words."""


@dataclass
class OrderRequest:
    account_id: int
    symbol: str
    side: int
    level: float
    stop: float
    target: float | None
    timeframe: str
    trend: str
    reason: str
    mood: str = ""
    confirmed: bool = False
    expiry: str = "gtc"


def kind_label(side: int, direction: int) -> str:
    if side > 0:
        return "Buy stop" if direction > 0 else "Buy limit"
    return "Sell limit" if direction > 0 else "Sell stop"


def expiry_time(choice: str, now: datetime | None = None) -> datetime | None:
    """When an order lapses: never, 10pm UK today (or the next weekday), 10pm UK on Friday, or in 30 days."""
    if choice not in EXPIRIES:
        raise OrderError("Choose when the order should expire.")
    now = now or datetime.now(timezone.utc)
    uk = now.astimezone(paper.UK)
    if choice == "gtc":
        return None
    if choice == "month":
        return now + timedelta(days=30)
    close = uk.replace(hour=CLOSE_HOUR, minute=0, second=0, microsecond=0)
    if choice == "day":
        while close <= uk or close.weekday() >= 5:
            close += timedelta(days=1)
    else:  # week: this Friday's close, or next Friday's if that has passed
        close += timedelta(days=(4 - uk.weekday()) % 7)
        if close <= uk:
            close += timedelta(days=7)
    return close.astimezone(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


# --- Placing and cancelling -------------------------------------------------------------------------

def create(db: Session, user: User, req: OrderRequest) -> PriceOrder:
    problems = paper.checklist_problems(paper.OrderRequest(
        account_id=req.account_id, symbol=req.symbol, side=req.side, stop=req.stop, target=req.target,
        timeframe=req.timeframe, trend=req.trend, reason=req.reason, mood=req.mood, confirmed=req.confirmed))
    if problems:
        raise OrderError("Pre-trade checklist incomplete: " + " ".join(problems))
    acct = paper.get_account(db, user, req.account_id)
    if acct.archived:
        raise OrderError("This paper account is archived.")
    if req.side not in (1, -1):
        raise OrderError("Choose buy or sell.")
    if acct.mode == "cash" and req.side < 0:
        raise OrderError("This account holds real shares, so it can only buy. Use a CFD / spread bet account to sell short.")
    symbol = lookup(db, req.symbol)
    p = symbol.precision
    if not req.level or req.level <= 0:
        raise OrderError("Set the price the order should fill at.")
    if (req.level - req.stop) * req.side <= 0:
        raise OrderError(f"The stop-loss must be {'below' if req.side > 0 else 'above'} the order's price "
                         f"({req.level:.{p}f}) for a {'buy' if req.side > 0 else 'sell'}.")
    if req.target is not None and (req.target - req.level) * req.side <= 0:
        raise OrderError("The target is on the wrong side of the order's price.")
    expires = expiry_time(req.expiry)

    q = paper.latest_quote(db, symbol)  # a closed market is fine: the order waits for it to open
    if abs(req.level - q.mid) <= q.mid * 1e-6:
        raise OrderError("That's the current price. Use “Now, at the live price” instead.")
    direction = 1 if req.level > q.mid else -1
    waiting = db.scalars(select(PriceOrder.id).where(PriceOrder.account_id == acct.id, PriceOrder.status == "waiting")).all()
    if len(waiting) >= MAX_WAITING:
        raise OrderError(f"This account already has {MAX_WAITING} waiting orders. Cancel some first.")

    flags = []
    if (req.side > 0 and req.trend == "down") or (req.side < 0 and req.trend == "up"):
        flags.append("Traded against the trend you identified")
    last_loss = db.scalar(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "closed",
                                                   PaperTrade.pnl_gbp < 0).order_by(PaperTrade.exit_time.desc()).limit(1))
    if last_loss is not None and last_loss.exit_time is not None:
        if datetime.now(timezone.utc) - _aware(last_loss.exit_time) < timedelta(minutes=paper.REVENGE_MINUTES):
            flags.append(f"Placed within {paper.REVENGE_MINUTES} minutes of a losing trade")

    order = PriceOrder(
        account_id=acct.id, symbol=symbol.code, timeframe=req.timeframe[:8], side=req.side, level=req.level,
        direction=direction, stop=req.stop, target=req.target, status="waiting", placed_mid=q.mid,
        expires_at=expires, last_checked_ts=q.bars[-1].ts if q.bars else 0, message="",
        trend=req.trend, reason=req.reason.strip()[:300], mood=req.mood[:20], rule_flags=flags,
    )
    db.add(order)
    db.commit()
    return order


def get_order(db: Session, user: User, order_id: int) -> tuple[PriceOrder, PaperAccount]:
    o = db.get(PriceOrder, order_id)
    if o is None:
        raise OrderError("Order not found.")
    return o, paper.get_account(db, user, o.account_id)


def cancel(db: Session, user: User, order_id: int) -> PriceOrder:
    o, _ = get_order(db, user, order_id)
    # Lock and re-read: the worker may be filling it at this moment.
    o = db.get(PriceOrder, o.id, with_for_update=True, populate_existing=True)
    if o.status != "waiting":
        raise OrderError(f"This order has already {_done_word(o.status)}.")
    _finish(o, "cancelled", "Cancelled by you.")
    db.commit()
    return o


def _done_word(status: str) -> str:
    return {"filled": "filled", "cancelled": "been cancelled", "expired": "expired", "failed": "failed"}.get(status, "finished")


def _finish(o: PriceOrder, status: str, message: str) -> None:
    o.status, o.message, o.finished_at = status, message[:300], datetime.now(timezone.utc)


def order_dict(o: PriceOrder, precision: int = 5) -> dict:
    return {
        "id": o.id, "accountId": o.account_id, "symbol": o.symbol, "timeframe": o.timeframe,
        "side": "long" if o.side > 0 else "short", "kind": kind_label(o.side, o.direction),
        "level": o.level, "direction": "up" if o.direction > 0 else "down", "stop": o.stop, "target": o.target,
        "status": o.status, "placedMid": o.placed_mid, "precision": precision,
        "createdAt": _aware(o.created_at).isoformat() if o.created_at else None,
        "expiresAt": _aware(o.expires_at).isoformat() if o.expires_at else None,
        "finishedAt": _aware(o.finished_at).isoformat() if o.finished_at else None,
        "message": o.message, "tradeId": o.trade_id, "reason": o.reason, "ruleFlags": o.rule_flags or [],
    }


# --- Watching (the background worker calls this) --------------------------------------------------

def reached(o: PriceOrder, q: paper.Quote, now: float | None = None) -> tuple[float, int, float | None, bool] | None:
    """Whether a candle since the last check (or the latest price) reached the order's level.
    Returns (fill level, when, recorded spread, gapped past) or None. Finished candles are never checked twice."""
    tf_seconds = get_timeframe(q.timeframe).seconds
    now = time.time() if now is None else now
    for b in q.bars:
        if b.ts <= o.last_checked_ts:
            continue
        if o.direction > 0 and b.high >= o.level:
            gapped = b.open >= o.level
            return (b.open if gapped else o.level, b.ts, b.spread, gapped)
        if o.direction < 0 and b.low <= o.level:
            gapped = b.open <= o.level
            return (b.open if gapped else o.level, b.ts, b.spread, gapped)
        if b.ts + tf_seconds <= now:
            o.last_checked_ts = b.ts
    if (q.mid - o.level) * o.direction >= 0:
        return (q.mid, q.ts, q.spread, q.mid != o.level)
    return None


def work(db: Session, last_looked: dict[str, float], check_every: dict[str, int], now: float | None = None) -> dict:
    """One pass over every waiting order: expire old ones, and fill those whose level was reached."""
    now = time.time() if now is None else now
    stats = {"filled": 0, "failed": 0, "expired": 0}
    waiting = list(db.scalars(select(PriceOrder).where(PriceOrder.status == "waiting").order_by(PriceOrder.id)))
    by_symbol: dict[str, list[PriceOrder]] = {}
    for o in waiting:
        acct = db.get(PaperAccount, o.account_id)
        expires = _aware(o.expires_at)
        if expires is not None and expires.timestamp() <= now:
            _finish(o, "expired", "Expired without the price reaching it.")
            alerts.notify(db, acct.user_id, "trades", f"Price order expired: {kind_label(o.side, o.direction)} "
                          f"{o.symbol} at {o.level:g} · {acct.name}")
            stats["expired"] += 1
            continue
        by_symbol.setdefault(o.symbol, []).append(o)
    db.commit()

    for code, group in by_symbol.items():
        try:
            symbol = lookup(db, code)
        except ValueError:
            continue
        if now - last_looked.get(code, 0) < check_every.get(symbol.provider, 60):
            continue
        last_looked[code] = now
        try:
            q = paper.latest_quote(db, symbol)
            paper.check_fresh(q, symbol)  # a closed market: the order waits for it to open
        except (paper.PaperError, ProviderError):
            continue
        for o in group:
            o = db.get(PriceOrder, o.id, with_for_update=True, populate_existing=True)
            if o is None or o.status != "waiting":
                continue
            hit = reached(o, q, now)
            if hit is None:
                db.commit()  # keep last_checked_ts
                continue
            level, when, spread, gapped = hit
            acct = db.get(PaperAccount, o.account_id)
            kind = kind_label(o.side, o.direction)
            note = f"{kind} order reached {o.level:g}" + (f"; the price jumped to {level:g}" if gapped else "")
            order_id = o.id
            try:
                if acct.archived:
                    raise paper.PaperError("The paper account has been archived.")
                t = paper.place(db, acct, o.symbol, o.side, o.stop, o.target, o.timeframe, trend=o.trend,
                                reason=o.reason, mood=o.mood, source="manual",
                                order=paper.Triggered(level, when, spread, list(o.rule_flags or []), note))
            except paper.PaperError as exc:
                db.rollback()
                o = db.get(PriceOrder, order_id)
                acct = db.get(PaperAccount, o.account_id)
                _finish(o, "failed", f"Reached {o.level:g} but not opened: {exc}")
                alerts.notify(db, acct.user_id, "problems",
                              f"Price order not filled: {kind} {symbol.name} at {o.level:g}\n{exc}\n{acct.name}")
                db.commit()
                stats["failed"] += 1
                continue
            except ProviderError:
                db.rollback()
                continue
            o = db.get(PriceOrder, order_id)
            o.trade_id = t.id
            _finish(o, "filled", f"Filled at {t.entry_price:.{symbol.precision}f}.")
            p = symbol.precision
            alerts.notify(db, acct.user_id, "trades",
                          f"Price order filled: {kind} {symbol.name} at {t.entry_price:.{p}f}\n"
                          f"Stop-loss {t.stop:.{p}f}" + (f", target {t.target:.{p}f}" if t.target is not None else "")
                          + f"\nRisk £{t.risk_gbp:.2f} · {acct.name}")
            db.commit()
            stats["filled"] += 1
    return stats
