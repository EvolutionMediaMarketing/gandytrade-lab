"""How a paper account is doing: the numbers, and plain-English feedback on your habits.

Everything here is worked out from the account's own closed trades. The feedback is rule-based:
each rule looks for one well-known bad habit (widening stops, revenge trading, losses much bigger
than wins, closing winners early...) and says what it found, with the evidence. It describes
what happened; it never tells you what to trade.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AutoRun, PaperAccount, PaperTrade
from ..strategies.library import STRATEGIES
from . import service as paper

RECENT_DAYS = 30
MIN_FOR_HABITS = 10  # closed trades before habit-based feedback means much
GOOD_RULE_SCORE = 90  # the graduation checklist asks for this on manual trades


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def stats(trades: list[PaperTrade]) -> dict:
    """Summary figures for a set of closed trades (all money in £, after costs)."""
    n = len(trades)
    pnl = [t.pnl_gbp or 0.0 for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    rs = [(t.pnl_gbp or 0.0) / t.risk_gbp for t in trades if t.risk_gbp and t.risk_gbp > 0]
    streak = longest = 0
    for p in pnl:
        streak = streak + 1 if p <= 0 else 0
        longest = max(longest, streak)
    holds = [(_aware(t.exit_time) - _aware(t.entry_time)).total_seconds() / 3600 for t in trades if t.exit_time]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(len(wins) / n * 100, 1) if n else None,
        "net": round(sum(pnl), 2),
        "costs": round(sum(t.costs_gbp or 0.0 for t in trades), 2),
        "avgWin": round(avg_win, 2) if avg_win is not None else None,
        "avgLoss": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff": round(avg_win / -avg_loss, 2) if avg_win and avg_loss and avg_loss < 0 else None,
        "expectancy": round(sum(pnl) / n, 2) if n else None,  # what an average trade made, after costs
        "avgR": round(sum(rs) / len(rs), 2) if rs else None,
        "profitFactor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "best": round(max(pnl), 2) if pnl else None,
        "worst": round(min(pnl), 2) if pnl else None,
        "longestLosingRun": longest,
        "avgHoldHours": round(sum(holds) / len(holds), 1) if holds else None,
    }


def _curve(acct: PaperAccount, closed: list[PaperTrade], equity_now: float) -> tuple[list[dict], float, float]:
    """Realised balance after each closed trade, plus today's value. Returns the points and the
    largest and current fall from a high, in %."""
    start = acct.starting_balance + (acct.deposits or 0.0)
    created = _aware(acct.created_at) or datetime.now(timezone.utc)
    points = [{"time": int(created.timestamp()), "value": round(start, 2)}]
    balance = start
    for t in closed:
        balance += t.pnl_gbp or 0.0
        ts = int(_aware(t.exit_time).timestamp())
        if ts <= points[-1]["time"]:
            ts = points[-1]["time"] + 1  # the chart needs times in order
        points.append({"time": ts, "value": round(balance, 2)})
    now = max(int(datetime.now(timezone.utc).timestamp()), points[-1]["time"] + 1)
    points.append({"time": now, "value": round(equity_now, 2)})
    peak, worst = points[0]["value"], 0.0
    for p in points:
        peak = max(peak, p["value"])
        if peak > 0:
            worst = max(worst, (peak - p["value"]) / peak * 100)
    current = (peak - points[-1]["value"]) / peak * 100 if peak > 0 else 0.0
    return points, round(worst, 1), round(max(0.0, current), 1)


def _planned_r(t: PaperTrade) -> float | None:
    if t.target is None or not t.initial_stop or t.entry_price == t.initial_stop:
        return None
    return abs(t.target - t.entry_price) / abs(t.entry_price - t.initial_stop)


def feedback(db: Session, acct: PaperAccount, closed: list[PaperTrade], s: dict, manual: list[PaperTrade],
             current_dd: float) -> list[dict]:
    """Rule-based observations, most important first. Each: level (stop | caution | info | good), title, text."""
    out: list[dict] = []
    now = datetime.now(timezone.utc)
    recent = [t for t in closed if _aware(t.exit_time) >= now - timedelta(days=RECENT_DAYS)]
    recent_manual = [t for t in recent if t.source == "manual"]

    def flagged(trades: list[PaperTrade], text: str) -> list[PaperTrade]:
        return [t for t in trades if any(text in f for f in (t.rule_flags or []))]

    if s["trades"] < 20:
        out.append({"level": "info", "title": "Early days", "text": (
            f"Only {s['trades']} closed trade{'s' if s['trades'] != 1 else ''} so far. Win rate and averages swing a lot "
            "until there are 20 to 30, so read the numbers below as a rough guide.")})

    if s["trades"] >= MIN_FOR_HABITS and s["avgWin"] and s["avgLoss"] and -s["avgLoss"] > 2 * s["avgWin"] \
            and (s["winRate"] or 0) < 70:
        out.append({"level": "stop", "title": "Losses much bigger than wins", "text": (
            f"Your average loss (£{-s['avgLoss']:.2f}) is more than twice your average win (£{s['avgWin']:.2f}), and "
            f"only {s['winRate']:.0f}% of trades win. That loses money over time. Usually it means stops are being "
            "moved or ignored, or winners are taken too early.")})

    widened = flagged(recent_manual, "Moved the stop-loss further away")
    if widened:
        out.append({"level": "stop", "title": "Stops moved further away", "text": (
            f"In the last {RECENT_DAYS} days you moved a stop-loss further away on {len(widened)} trade"
            f"{'s' if len(widened) != 1 else ''}. That turns a planned small loss into a bigger one. "
            "Decide the stop before the trade and leave it, or move it only towards profit.")})

    revenge = flagged(recent_manual, "Opened within")
    if revenge:
        out.append({"level": "caution", "title": "Trading straight after a loss", "text": (
            f"{len(revenge)} trade{'s were' if len(revenge) != 1 else ' was'} opened within 30 minutes of a losing one "
            f"in the last {RECENT_DAYS} days. Trades taken to win the money back are usually rushed. "
            "A rule that helps: after a loss, wait until the next candle closes, or the next day.")})

    against = flagged(recent_manual, "Traded against the trend")
    if against:
        out.append({"level": "caution", "title": "Against your own reading of the trend", "text": (
            f"{len(against)} trade{'s went' if len(against) != 1 else ' went'} against the trend you said you saw. "
            "If the reason is good, write it in the journal; if not, it's worth asking why.")})

    # Do you trade more after losing than after winning?
    if len(manual) >= MIN_FOR_HABITS:
        def opened_after(result_sign: int) -> tuple[int, int]:
            closes = [t for t in manual if (t.pnl_gbp or 0) * result_sign > 0 and t.exit_time]
            follow = 0
            for c in closes:
                end = _aware(c.exit_time)
                follow += sum(1 for t in manual if end < _aware(t.entry_time) <= end + timedelta(hours=24))
            return follow, len(closes)
        after_loss, n_loss = opened_after(-1)
        after_win, n_win = opened_after(1)
        if n_loss >= 3 and n_win >= 3:
            rate_loss, rate_win = after_loss / n_loss, after_win / n_win
            if rate_loss > 1.5 * max(rate_win, 0.1) and rate_loss >= 1:
                out.append({"level": "caution", "title": "More trades after losses", "text": (
                    f"In the day after a losing trade you opened {rate_loss:.1f} trades on average, against "
                    f"{rate_win:.1f} after a win. Trading more when behind is a classic way to dig a deeper hole.")})

    early = [t for t in manual if t.exit_reason == "Closed by you" and (t.pnl_gbp or 0) > 0 and _planned_r(t)
             and t.risk_gbp and (t.pnl_gbp / t.risk_gbp) < 0.5 * _planned_r(t)]
    if len(early) >= 3:
        out.append({"level": "caution", "title": "Winners closed early", "text": (
            f"{len(early)} winning trades were closed by hand at less than half the way to their target. "
            "Small wins with full-size losses is how many good strategies end up losing. "
            "If the plan had a target, give it a chance, or move the stop up to protect the profit instead.")})

    if len(manual) >= 5:
        avg_score = sum(t.rule_score if t.rule_score is not None else paper.score(t.rule_flags or []) for t in manual) / len(manual)
        if avg_score < GOOD_RULE_SCORE:
            out.append({"level": "caution", "title": f"Rule score {avg_score:.0f}", "text": (
                f"Your average rule score on trades you placed is {avg_score:.0f}. The bar before any real money is "
                f"{GOOD_RULE_SCORE} or more: following the plan matters more than any one result.")})
        else:
            out.append({"level": "good", "title": f"Rule score {avg_score:.0f}", "text": (
                "You're following your own rules on the trades you place. That's the habit that matters most.")})

    no_lesson = [t for t in manual if not (t.lesson or "").strip()]
    if len(no_lesson) >= 3 and len(no_lesson) >= len(manual) / 2:
        out.append({"level": "info", "title": "Journal gaps", "text": (
            f"{len(no_lesson)} of your {len(manual)} closed trades have no lesson written. One line each is enough, "
            "and the weekly review works from them.")})

    if current_dd >= 10:
        out.append({"level": "caution", "title": f"Down {current_dd:.0f}% from the high", "text": (
            f"The account is {current_dd:.0f}% below its highest value. Trading pauses at {acct.max_drawdown_pct:g}%. "
            "This is a good moment to slow down and review the last few trades.")})

    # Automatic runs: is paper keeping up with the backtest?
    for run in db.scalars(select(AutoRun).where(AutoRun.account_id == acct.id)):
        live = [t for t in closed if t.auto_run_id == run.id]
        bt_r = (run.backtest or {}).get("avgR")
        if len(live) >= MIN_FOR_HABITS and bt_r is not None:
            live_r = sum((t.pnl_gbp or 0) / t.risk_gbp for t in live if t.risk_gbp) / len(live)
            name = STRATEGIES[run.strategy].label(run.params) if run.strategy in STRATEGIES else run.strategy
            if live_r < bt_r - 0.3:
                out.append({"level": "caution", "title": f"{name} on {run.symbol} is behind its backtest", "text": (
                    f"Average R on paper is {live_r:.2f} from {len(live)} trades, against {bt_r:.2f} in the backtest. "
                    "Some drop is normal; a big one usually means the backtest was too kind.")})

    if not any(f["level"] in ("stop", "caution") for f in out) and s["trades"] >= MIN_FOR_HABITS:
        out.append({"level": "good", "title": "No bad habits spotted", "text": (
            "Nothing in your recent trades matches the usual warning signs. Keep journalling, and keep the size small.")})
    order = {"stop": 0, "caution": 1, "info": 2, "good": 3}
    return sorted(out, key=lambda f: order[f["level"]])


def performance(db: Session, acct: PaperAccount) -> dict:
    closed = list(db.scalars(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "closed")
                             .order_by(PaperTrade.exit_time)))
    state = paper.account_state(db, acct)
    manual = [t for t in closed if t.source == "manual"]
    auto = [t for t in closed if t.source == "auto"]
    s = stats(closed)
    points, max_dd, current_dd = _curve(acct, closed, state["equity"])

    groups: dict[tuple, list[PaperTrade]] = defaultdict(list)
    for t in closed:
        label = "Your own trades" if t.source == "manual" else (STRATEGIES[t.strategy].name if t.strategy in STRATEGIES else t.strategy or "Automatic")
        groups[(label, t.symbol)].append(t)
    breakdown = []
    for (label, symbol), ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        g = stats(ts)
        breakdown.append({"label": label, "symbol": symbol, "trades": g["trades"], "net": g["net"], "winRate": g["winRate"],
                          "avgR": g["avgR"], "costs": g["costs"]})

    funded = acct.starting_balance + (acct.deposits or 0.0)
    return {
        "account": {"id": acct.id, "name": acct.name, "mode": acct.mode, "funded": round(funded, 2),
                    "equity": round(state["equity"], 2), "returnPct": round((state["equity"] - funded) / funded * 100, 2) if funded else 0.0,
                    "openCount": len(state["valued"]), "maxDrawdownLimit": acct.max_drawdown_pct},
        "all": s, "manual": stats(manual), "auto": stats(auto),
        "maxDrawdownPct": max_dd, "currentDrawdownPct": current_dd,
        "ruleScore": round(sum(t.rule_score if t.rule_score is not None else paper.score(t.rule_flags or []) for t in manual) / len(manual))
        if manual else None,
        "curve": points,
        "breakdown": breakdown,
        "feedback": feedback(db, acct, closed, s, manual, current_dd),
    }


# --- Coach export ------------------------------------------------------------------------------------

def coach_export(db: Session, acct: PaperAccount) -> str:
    """A plain-text summary to paste into a coaching chat with Claude: no keys, no personal details."""
    p = performance(db, acct)
    s, a = p["all"], p["account"]

    def money(v):
        return "–" if v is None else f"{'-' if v < 0 else ''}£{abs(v):,.2f}"

    lines = [
        f"# GandyTrade paper account: {a['name']} ({'CFD / spread bet' if a['mode'] == 'cfd' else 'real shares'})",
        f"Exported {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC. Pretend money only.",
        "",
        "## Summary",
        f"- Funded {money(a['funded'])}; now {money(a['equity'])} ({a['returnPct']:+.1f}%), {a['openCount']} open trade(s)",
        f"- Closed trades: {s['trades']} ({p['manual']['trades']} placed by me, {p['auto']['trades']} automatic)",
        f"- Win rate {s['winRate'] if s['winRate'] is not None else '–'}%, average win {money(s['avgWin'])}, "
        f"average loss {money(s['avgLoss'])}, expectancy {money(s['expectancy'])} a trade, average R {s['avgR'] if s['avgR'] is not None else '–'}",
        f"- Costs paid {money(s['costs'])}; worst fall {p['maxDrawdownPct']}% (now {p['currentDrawdownPct']}% below the high)",
        f"- Rule score on my own trades: {p['ruleScore'] if p['ruleScore'] is not None else '–'}",
        "",
        "## What the app noticed",
    ]
    lines += [f"- [{f['level']}] {f['title']}: {f['text']}" for f in p["feedback"]] or ["- Nothing yet."]
    runs = list(db.scalars(select(AutoRun).where(AutoRun.account_id == acct.id)))
    if runs:
        from .auto import live_results

        lines += ["", "## Automatic runs"]
        for run in runs:
            name = STRATEGIES[run.strategy].label(run.params) if run.strategy in STRATEGIES else run.strategy
            lv, bt = live_results(db, run), run.backtest or {}
            lines.append(f"- {name}, {run.symbol} {run.timeframe} ({run.status}): paper {lv['trades']} trades, net {money(lv['net'])}, "
                         f"avg R {lv['avgR'] if lv['avgR'] is not None else '–'}; backtest {bt.get('trades', '–')} trades, "
                         f"avg R {bt.get('avgR', '–')}, {bt.get('returnPct', '–')}% over {bt.get('years', '–')} yrs")
    closed = list(db.scalars(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "closed")
                             .order_by(PaperTrade.exit_time.desc()).limit(20)))
    lines += ["", "## Last 20 closed trades (newest first)",
              "| Closed | Market | Side | Who | Result | R | Why it closed | Rules broken | Lesson |",
              "|---|---|---|---|---|---|---|---|---|"]
    for t in closed:
        who = "me" if t.source == "manual" else (STRATEGIES[t.strategy].name if t.strategy in STRATEGIES else "auto")
        r = f"{t.pnl_gbp / t.risk_gbp:.2f}" if t.risk_gbp and t.pnl_gbp is not None else "–"
        clean = lambda x: (x or "").replace("|", "/").replace("\n", " ")  # noqa: E731
        lines.append(f"| {_aware(t.exit_time):%d %b %H:%M} | {t.symbol} | {'buy' if t.side > 0 else 'short'} | {who} | "
                     f"{money(t.pnl_gbp)} | {r} | {clean(t.exit_reason)} | {clean('; '.join(t.rule_flags or [])) or '–'} | "
                     f"{clean(t.lesson) or '–'} |")
    if not closed:
        lines.append("| – | – | – | – | – | – | – | – | – |")
    lines += ["", "Please review this like a trading coach: what's going well, the one habit to work on next week, "
              "and anything in the numbers I should be wary of."]
    return "\n".join(lines)
