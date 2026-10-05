"""The weekly review: about 20 minutes each weekend looking back at the week's paper trading.

It gathers the week's facts (trades closed, best and worst, rules broken, how automatic runs did
against their backtests, what the app noticed), asks a few questions, and ends with one thing to
focus on next week. Next week's review starts by asking whether you stuck to it.

A week runs Monday to Sunday, UK time. From Friday the review is for the current week; from
Monday to Thursday it's still for the week just gone, so a review missed at the weekend can
be done on Monday. A Telegram reminder goes out on Sunday evening if the review isn't done.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import alerts
from .models import AutoRun, PaperAccount, PaperTrade, User, WeeklyReview
from .paper import performance as perf
from .paper import service as paper
from .strategies.library import STRATEGIES

UK = ZoneInfo("Europe/London")
REMIND_AT = time(17, 0)  # Sunday, UK time
FOCUS_MAX = 200
ANSWER_MAX = 1000
STUCK = ("yes", "partly", "no")
WORST = ("good_trade", "mistake", "unsure")


class ReviewError(ValueError):
    """A reason the review can't be saved, in plain words."""


def week_start(today: date) -> date:
    """The Monday of the week under review on this day."""
    monday = today - timedelta(days=today.weekday())
    return monday if today.weekday() >= 4 else monday - timedelta(days=7)


def _bounds(monday: date) -> tuple[datetime, datetime]:
    start = datetime.combine(monday, time(0, 0), tzinfo=UK)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def _trade_line(t: PaperTrade, account: str) -> dict:
    r = round(t.pnl_gbp / t.risk_gbp, 2) if t.risk_gbp and t.pnl_gbp is not None else None
    return {
        "id": t.id, "account": account, "symbol": t.symbol, "side": "buy" if t.side > 0 else "short",
        "who": "you" if t.source == "manual" else (STRATEGIES[t.strategy].name if t.strategy in STRATEGIES else "automatic"),
        "pnl": round(t.pnl_gbp or 0.0, 2), "r": r, "exitReason": t.exit_reason, "closed": _aware(t.exit_time).isoformat(),
        "reason": t.reason, "lesson": t.lesson, "flags": t.rule_flags or [],
    }


def facts(db: Session, user: User, monday: date) -> dict:
    """Everything the review shows about one week."""
    start, end = _bounds(monday)
    accounts = list(db.scalars(select(PaperAccount).where(PaperAccount.user_id == user.id, PaperAccount.archived.is_(False))))
    names = {a.id: a.name for a in accounts}
    closed = [t for t in db.scalars(select(PaperTrade).where(
        PaperTrade.account_id.in_(names), PaperTrade.status == "closed")) if start <= _aware(t.exit_time) < end]
    closed.sort(key=lambda t: _aware(t.exit_time))
    opened = [t for t in db.scalars(select(PaperTrade).where(PaperTrade.account_id.in_(names)))
              if start <= _aware(t.entry_time) < end]
    manual = [t for t in closed if t.source == "manual"]
    s = perf.stats(closed)

    per_account = []
    for a in accounts:
        mine = [t for t in closed if t.account_id == a.id]
        if not mine and not any(t.account_id == a.id for t in opened):
            continue
        st = perf.stats(mine)
        per_account.append({"name": a.name, "trades": st["trades"], "net": st["net"], "winRate": st["winRate"],
                            "opened": sum(1 for t in opened if t.account_id == a.id)})

    runs = []
    for run in db.scalars(select(AutoRun).where(AutoRun.user_id == user.id, AutoRun.status != "stopped")):
        week_trades = [t for t in closed if t.auto_run_id == run.id]
        all_trades = [t for t in db.scalars(select(PaperTrade).where(PaperTrade.auto_run_id == run.id,
                                                                     PaperTrade.status == "closed"))]
        rs = [(t.pnl_gbp or 0) / t.risk_gbp for t in all_trades if t.risk_gbp]
        runs.append({
            "strategy": STRATEGIES[run.strategy].label(run.params) if run.strategy in STRATEGIES else run.strategy,
            "symbol": run.symbol, "timeframe": run.timeframe, "account": names.get(run.account_id, ""), "status": run.status,
            "weekTrades": len(week_trades), "weekNet": round(sum(t.pnl_gbp or 0 for t in week_trades), 2),
            "totalTrades": len(all_trades), "liveAvgR": round(sum(rs) / len(rs), 2) if rs else None,
            "backtestAvgR": (run.backtest or {}).get("avgR"), "message": run.last_message,
        })

    noticed = []
    for a in accounts:
        if any(t.account_id == a.id for t in closed):
            p = perf.performance(db, a)
            noticed += [{**f, "account": a.name} for f in p["feedback"] if f["level"] in ("stop", "caution")]

    best = max(closed, key=lambda t: t.pnl_gbp or 0) if closed else None
    worst = min(closed, key=lambda t: t.pnl_gbp or 0) if closed else None
    broken = [_trade_line(t, names[t.account_id]) for t in manual if t.rule_flags]
    scores = [t.rule_score if t.rule_score is not None else paper.score(t.rule_flags or []) for t in manual]
    first_day, last_day = monday, monday + timedelta(days=6)
    return {
        "week": monday.isoformat(),
        "label": f"{first_day:%-d %b} to {last_day:%-d %b %Y}",
        "closed": s["trades"], "opened": len(opened), "manualClosed": len(manual), "autoClosed": s["trades"] - len(manual),
        "net": s["net"], "winRate": s["winRate"], "avgR": s["avgR"], "costs": s["costs"],
        "ruleScore": round(sum(scores) / len(scores)) if scores else None,
        "best": _trade_line(best, names[best.account_id]) if best and (best.pnl_gbp or 0) > 0 else None,
        "worst": _trade_line(worst, names[worst.account_id]) if worst and (worst.pnl_gbp or 0) < 0 else None,
        "broken": broken, "accounts": per_account, "runs": runs, "noticed": noticed[:6],
        "noLesson": sum(1 for t in manual if not (t.lesson or "").strip()),
    }


# --- Reviews ---------------------------------------------------------------------------------------

def _get(db: Session, user: User, monday: date) -> WeeklyReview | None:
    return db.scalar(select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week == monday.isoformat()))


def _previous(db: Session, user: User, monday: date) -> WeeklyReview | None:
    return db.scalar(select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week < monday.isoformat(),
                                                WeeklyReview.completed_at.is_not(None))
                     .order_by(WeeklyReview.week.desc()).limit(1))


def current(db: Session, user: User, today: date | None = None) -> dict:
    monday = week_start(today or datetime.now(UK).date())
    row = _get(db, user, monday)
    prev = _previous(db, user, monday)
    return {
        "week": monday.isoformat(),
        "facts": row.facts if row and row.completed_at else facts(db, user, monday),
        "answers": (row.answers or {}) if row else {},
        "focus": row.focus if row else "",
        "completed": bool(row and row.completed_at),
        "completedAt": _aware(row.completed_at).isoformat() if row and row.completed_at else None,
        "previousFocus": {"week": prev.week, "focus": prev.focus} if prev else None,
    }


def _clean(answers: dict) -> dict:
    out = {}
    for key in ("stuck", "stuckNote", "best", "worstKind", "worst", "rules", "runs", "other"):
        v = answers.get(key)
        if v is None:
            continue
        v = str(v).strip()[:ANSWER_MAX]
        if key == "stuck" and v and v not in STUCK:
            raise ReviewError("Choose yes, partly or no for last week's focus.")
        if key == "worstKind" and v and v not in WORST:
            raise ReviewError("Choose what kind of trade the worst one was.")
        out[key] = v
    return out


def save(db: Session, user: User, week: str, answers: dict, focus: str, complete: bool,
         today: date | None = None) -> dict:
    try:
        monday = date.fromisoformat(week)
    except ValueError as exc:
        raise ReviewError("Unknown week.") from exc
    if monday.weekday() != 0 or monday > (today or datetime.now(UK).date()):
        raise ReviewError("Unknown week.")
    focus = focus.strip()[:FOCUS_MAX]
    if complete and len(focus) < 5:
        raise ReviewError("Write one thing to focus on next week before finishing.")
    row = _get(db, user, monday)
    if row is None:
        row = WeeklyReview(user_id=user.id, week=monday.isoformat(), answers={}, facts={}, focus="")
        db.add(row)
    row.answers = _clean(answers)
    row.focus = focus
    row.updated_at = datetime.now(timezone.utc)
    if complete:
        row.facts = facts(db, user, monday)  # kept as they were, for looking back later
        row.completed_at = row.completed_at or datetime.now(timezone.utc)
    db.commit()
    return review_for(db, user, monday)


def review_for(db: Session, user: User, monday: date) -> dict:
    """The review of a given week (a Friday in it is a day when that week is the one under review)."""
    return current(db, user, monday + timedelta(days=4))


def history(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.completed_at.is_not(None))
                      .order_by(WeeklyReview.week.desc()).limit(52)).all()
    by_week = {r.week: r for r in rows}
    out = []
    for r in rows:
        nxt = by_week.get((date.fromisoformat(r.week) + timedelta(days=7)).isoformat())
        out.append({"week": r.week, "label": (r.facts or {}).get("label", r.week), "focus": r.focus,
                    "stuck": (nxt.answers or {}).get("stuck") if nxt else None,
                    "closed": (r.facts or {}).get("closed"), "net": (r.facts or {}).get("net"),
                    "ruleScore": (r.facts or {}).get("ruleScore")})
    return out


def coach_text(review: dict) -> str:
    f, a = review["facts"], review["answers"]

    def money(v):
        return "–" if v is None else f"{'-' if v < 0 else ''}£{abs(v):,.2f}"

    lines = [f"# GandyTrade weekly review: {f['label']}", "Pretend money only.", "",
             f"- Closed {f['closed']} trades ({f['manualClosed']} mine, {f['autoClosed']} automatic), opened {f['opened']}",
             f"- Net {money(f['net'])}, win rate {f['winRate'] if f['winRate'] is not None else '–'}%, "
             f"average R {f['avgR'] if f['avgR'] is not None else '–'}, costs {money(f['costs'])}",
             f"- Rule score on my trades: {f['ruleScore'] if f['ruleScore'] is not None else '–'}"]
    if review.get("previousFocus"):
        lines.append(f"- Last week's focus: \"{review['previousFocus']['focus']}\". Stuck to it: {a.get('stuck', '–')}. {a.get('stuckNote', '')}")
    if f.get("best"):
        b = f["best"]
        lines.append(f"- Best: {b['side']} {b['symbol']} ({b['who']}) {money(b['pnl'])}. What went right: {a.get('best', '–')}")
    elif a.get("best"):
        lines.append(f"- What went well: {a['best']}")
    if f.get("worst"):
        w = f["worst"]
        lines.append(f"- Worst: {w['side']} {w['symbol']} ({w['who']}) {money(w['pnl'])}. "
                     f"Kind: {a.get('worstKind', '–')}. {a.get('worst', '')}")
    if f.get("broken"):
        lines.append(f"- Rules broken on {len(f['broken'])} trade(s): "
                     + "; ".join(f"{t['symbol']}: {', '.join(t['flags'])}" for t in f["broken"][:5]))
        lines.append(f"  What I'll do differently: {a.get('rules', '–')}")
    for r in f.get("runs", []):
        lines.append(f"- Automatic {r['strategy']} on {r['symbol']}: {r['weekTrades']} trades this week ({money(r['weekNet'])}); "
                     f"{r['totalTrades']} in total, avg R {r['liveAvgR'] if r['liveAvgR'] is not None else '–'} "
                     f"vs backtest {r['backtestAvgR'] if r['backtestAvgR'] is not None else '–'}")
    for n in f.get("noticed", []):
        lines.append(f"- App noticed ({n['account']}): {n['title']}. {n['text']}")
    if a.get("other"):
        lines.append(f"- Anything else: {a['other']}")
    lines += ["", f"Focus for next week: {review.get('focus') or '–'}", "",
              "Please review this like a trading coach: is my focus the right one, and what should I watch next week?"]
    return "\n".join(lines)


# --- Reminder (the worker calls this) -------------------------------------------------------------------

def remind(db: Session, now: datetime | None = None) -> int:
    """On Sunday evening, nudge anyone whose review for this week isn't done (once a week)."""
    now = (now or datetime.now(timezone.utc)).astimezone(UK)
    if now.weekday() != 6 or now.time() < REMIND_AT:
        return 0
    monday = week_start(now.date())
    sent = 0
    for user in db.scalars(select(User)):
        row = _get(db, user, monday)
        if row is not None and (row.completed_at or row.reminded_at):
            continue
        if row is None:
            row = WeeklyReview(user_id=user.id, week=monday.isoformat(), answers={}, facts={}, focus="")
            db.add(row)
        row.reminded_at = datetime.now(timezone.utc)
        f = facts(db, user, monday)
        alerts.notify(db, user.id, "reviews", (
            f"Time for your weekly review ({f['label']}).\n{f['closed']} trades closed this week, net "
            f"{'-' if f['net'] < 0 else ''}£{abs(f['net']):.2f}. About 20 minutes: open GandyTrade → Review."))
        sent += 1
    db.commit()
    return sent
