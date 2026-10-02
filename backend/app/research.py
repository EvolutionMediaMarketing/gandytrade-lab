"""Strategy research: backtest every strategy across a basket of markets, check each result for
the usual traps, and shortlist the ones worth testing on paper.

A scan is a background job run by the worker, a few markets at a time, so it never holds up
stop-loss checks. One also runs by itself every week, on the latest prices.

For every market, timeframe, strategy and direction (buys only, or buys and shorts), with the
strategy's default settings and the same costs and risk rules as the Backtest page, five checks:

  1. Profitable after costs.
  2. Enough trades to mean something (30 or more).
  3. Worst fall no more than 20%.
  4. Robust: still profitable with shorter and longer settings (lengths × 0.75 and × 1.5),
     so the result doesn't hang on one lucky number.
  5. Still working recently: profitable over the most recent third of the history.

Results that pass all five go on the shortlist, ranked by an evidence score (average R × √trades:
a steady edge over many trades scores higher than a big result from a few). Testing hundreds of
combinations means some will look good by luck, which is why checks 4 and 5 exist and why
anything shortlisted still goes to paper trading first. Nothing here is a recommendation to trade.
"""

import logging
import math
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .backtest import engine, report
from .backtest.costs import default_costs
from .config import get_settings
from .market.directory import lookup
from .market.fx import converter, quote_currency
from .market.providers.base import ProviderError
from .market.service import get_history
from .market.timeframes import get_timeframe
from .models import ResearchJob, User
from .paper.auto import NOT_AUTOMATIC
from .risk.guard import RiskSettings, leverage_cap
from .strategies.base import Strategy
from .strategies.library import STRATEGIES

log = logging.getLogger(__name__)

# Markets with free OANDA practice data: a spread of metals, energy, farm goods, stock indices and currencies.
BASKET = [
    "XAU_USD", "XAG_USD", "XCU_USD", "BCO_USD", "NATGAS_USD", "CORN_USD", "WHEAT_USD",
    "SPX500_USD", "NAS100_USD", "UK100_GBP", "DE30_EUR", "JP225_USD",
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD",
]
TIMEFRAMES = ("4h", "1d", "1w")
DEFAULT_TIMEFRAMES = ["1d"]
MAX_MARKETS = 30
MIN_TRADES = 30
MAX_DRAWDOWN = 20.0
RECENT_SHARE = 1 / 3
MIN_RECENT_TRADES = 5
BALANCE = 200.0
WEEKLY_EVERY = timedelta(days=7)
PASS_BUDGET_SECONDS = 20  # work per worker pass, so stop-loss checks are never held up for long
CHECKS = ["profitable", "enoughTrades", "drawdown", "robust", "recent"]
LEVELS = {"oversold", "exit_level"}  # thresholds, not lengths: left alone by the robustness check


class ResearchError(ValueError):
    """A reason a scan can't be started, in plain words."""


def strategies() -> list[Strategy]:
    return [s for k, s in STRATEGIES.items() if k not in NOT_AUTOMATIC]


def variants(s: Strategy) -> list[dict]:
    """Shorter and longer versions of the default settings: every whole-number length × 0.75 and × 1.5."""
    base = s.clean_params({})
    out = []
    for factor in (0.75, 1.5):
        changed = {}
        for p in s.params:
            if p.key not in LEVELS and float(p.step).is_integer() and float(p.default).is_integer() and p.default >= 2:
                changed[p.key] = max(p.minimum, min(p.maximum, round(p.default * factor)))
        if changed:
            out.append(s.clean_params({**base, **changed}))
    return out


# --- Jobs ------------------------------------------------------------------------------------------

def start(db: Session, user: User, markets: list[str] | None = None, timeframes: list[str] | None = None,
          automatic: bool = False) -> ResearchJob:
    busy = db.scalar(select(ResearchJob).where(ResearchJob.user_id == user.id, ResearchJob.status.in_(("queued", "running"))))
    if busy is not None:
        raise ResearchError("A scan is already running. It'll finish in a few minutes.")
    markets = list(dict.fromkeys(markets or BASKET))[:MAX_MARKETS]
    timeframes = [t for t in dict.fromkeys(timeframes or DEFAULT_TIMEFRAMES) if t in TIMEFRAMES] or DEFAULT_TIMEFRAMES
    units = [[m, t] for m in markets for t in timeframes]
    job = ResearchJob(user_id=user.id, status="queued", automatic=automatic,
                      settings={"markets": markets, "timeframes": timeframes, "balance": BALANCE, "riskPct": 1.0},
                      todo=units, total=len(units), done=0, rows=[], skipped=[], message="Waiting for the worker to start it.")
    db.add(job)
    db.commit()
    return job


def get_job(db: Session, user: User, job_id: int) -> ResearchJob:
    job = db.get(ResearchJob, job_id)
    if job is None or job.user_id != user.id:
        raise ResearchError("Scan not found.")
    return job


def schedule_weekly(db: Session) -> None:
    """Queue a fresh scan for each user once a week (only with a real price feed: sample prices prove nothing)."""
    if not get_settings().oanda_token:
        return
    now = datetime.now(timezone.utc)
    for user in db.scalars(select(User)):
        last = db.scalar(select(ResearchJob).where(ResearchJob.user_id == user.id).order_by(ResearchJob.id.desc()).limit(1))
        if last is not None:
            created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
            if now - created < WEEKLY_EVERY or last.status in ("queued", "running"):
                continue
            settings = last.settings or {}
        else:
            settings = {}
        try:
            start(db, user, settings.get("markets"), settings.get("timeframes"), automatic=True)
            log.info("Queued the weekly strategy scan for user %s", user.id)
        except ResearchError:
            pass


def work(db: Session, budget: float = PASS_BUDGET_SECONDS) -> bool:
    """Do some of the oldest unfinished scan. Returns True if there was anything to do."""
    job = db.scalar(select(ResearchJob).where(ResearchJob.status.in_(("queued", "running"))).order_by(ResearchJob.id).limit(1))
    if job is None:
        return False
    started = time.time()
    job.status = "running"
    rows, skipped, todo = list(job.rows or []), list(job.skipped or []), list(job.todo or [])
    first = True
    while todo and (first or time.time() - started < budget):  # always at least one market per pass
        first = False
        code, tf = todo.pop(0)
        try:
            new_rows, note = scan_market(db, code, tf)
            rows.extend(new_rows)
            if note:
                skipped.append({"market": code, "timeframe": tf, "reason": note})
        except (ProviderError, ValueError) as exc:
            skipped.append({"market": code, "timeframe": tf, "reason": str(exc)[:200]})
        except Exception as exc:  # one market's problem never stops the scan
            log.exception("Scan of %s %s failed", code, tf)
            skipped.append({"market": code, "timeframe": tf, "reason": f"Unexpected problem: {exc.__class__.__name__}"})
        job.done = job.total - len(todo)
        job.message = f"Tested {job.done} of {job.total} market and timeframe pairs."
    job.rows, job.skipped, job.todo = rows, skipped, todo
    if not todo:
        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)
        job.message = f"Finished: {len(rows)} combinations tested."
    db.commit()
    return True


# --- One market -----------------------------------------------------------------------------------

def _settings(symbol, mode: str, direction: str) -> engine.Settings:
    return engine.Settings(start_balance=BALANCE, mode=mode, direction=direction, risk=RiskSettings(1.0, 3.0, 20.0).cleaned(),
                           leverage=leverage_cap(symbol.code, symbol.asset_class, mode),
                           costs=default_costs(symbol.asset_class, mode))


def scan_market(db: Session, code: str, timeframe: str) -> tuple[list[dict], str]:
    """Every strategy on one market and timeframe. Returns the result rows and a note if it was skipped."""
    symbol = lookup(db, code)
    if symbol.provider != "oanda":
        return [], "Only markets with OANDA data are scanned (the other free feeds allow too few requests)."
    tf = get_timeframe(timeframe)
    history = get_history(db, symbol, tf)
    if history.sample:
        return [], "Sample prices only (no data key)."
    bars = history.bars
    if len(bars) < 300:
        return [], f"Only {len(bars)} candles of history: too short to judge."
    conv = converter(db, quote_currency(symbol))
    mode = "cfd"
    bh_settings = replace(_settings(symbol, "cash", "long"), leverage=1.0)
    bh_settings = replace(bh_settings, costs=replace(bh_settings.costs, financing_pct_year=0.0))
    bh = report.metrics(engine.buy_and_hold(bars, bh_settings, conv), BALANCE)
    cutoff = bars[0].ts + (bars[-1].ts - bars[0].ts) * (1 - RECENT_SHARE)
    years = (bars[-1].ts - bars[0].ts) / (365.25 * 86400)

    rows = []
    for s in strategies():
        directions = ["long", "both"] if s.can_short else ["long"]
        for direction in directions:
            settings = _settings(symbol, mode, direction)
            params = s.clean_params({})
            result = engine.run(bars, s, params, settings, conv)
            m = report.metrics(result, BALANCE)
            trades = [t for t in result.trades]
            recent = [t for t in trades if t.exit_ts >= cutoff]
            recent_net = sum(t.pnl_gbp for t in recent)
            variant_nets = [report.metrics(engine.run(bars, s, v, settings, conv), BALANCE)["net"] for v in variants(s)]
            checks = {
                "profitable": m["net"] > 0,
                "enoughTrades": m["trades"] >= MIN_TRADES,
                "drawdown": m["maxDrawdownPct"] <= MAX_DRAWDOWN,
                "robust": bool(variant_nets) and all(n > 0 for n in variant_nets),
                "recent": len(recent) >= MIN_RECENT_TRADES and recent_net > 0,
            }
            avg_r = m["avgR"] or 0.0
            ratio = m["returnPct"] / max(m["maxDrawdownPct"], 1.0)
            bh_ratio = bh["returnPct"] / max(bh["maxDrawdownPct"], 1.0)
            rows.append({
                "market": symbol.code, "name": symbol.name, "assetClass": symbol.asset_class, "timeframe": tf.code,
                "strategy": s.key, "strategyName": s.name, "direction": direction, "years": round(years, 1),
                "returnPct": m["returnPct"], "annualPct": m["annualPct"], "trades": m["trades"],
                "tradesPerYear": round(m["trades"] / years, 1) if years > 0 else None,
                "winRate": m["winRate"], "avgR": m["avgR"], "profitFactor": m["profitFactor"],
                "maxDrawdownPct": m["maxDrawdownPct"], "costs": m["costs"],
                "variantReturns": [round(n / BALANCE * 100, 1) for n in variant_nets],
                "recentTrades": len(recent), "recentNet": round(recent_net, 2),
                "buyHoldReturnPct": bh["returnPct"], "buyHoldDrawdownPct": bh["maxDrawdownPct"],
                "beatsBuyHold": bool(m["net"] > bh["net"]), "smootherThanBuyHold": bool(ratio > bh_ratio),
                "checks": {k: bool(v) for k, v in checks.items()},
                "passed": sum(bool(v) for v in checks.values()),
                "score": round(avg_r * math.sqrt(m["trades"]), 2) if m["trades"] else 0.0,
                "sample": False,
            })
    return rows, ""


# --- Turning results into suggestions ---------------------------------------------------------------

def summarise(rows: list[dict]) -> dict:
    """The shortlist, near misses, and strategies that held up across several markets."""
    shortlist = sorted([r for r in rows if r["passed"] == len(CHECKS)], key=lambda r: -r["score"])
    near = sorted([r for r in rows if r["passed"] == len(CHECKS) - 1 and r["checks"]["profitable"]], key=lambda r: -r["score"])
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["strategy"], r["direction"], r["timeframe"]), []).append(r)
    across = []
    for (key, direction, tf), group in groups.items():
        good = [r for r in group if r["checks"]["profitable"] and r["checks"]["robust"]]
        if len(good) < 2:
            continue
        across.append({
            "strategy": key, "strategyName": group[0]["strategyName"], "direction": direction, "timeframe": tf,
            "markets": len(group), "held": len(good),
            "heldMarkets": [{"market": r["market"], "name": r["name"], "returnPct": r["returnPct"], "passed": r["passed"]}
                            for r in sorted(good, key=lambda r: -r["score"])],
            "avgAnnualPct": round(sum(r["annualPct"] or 0 for r in good) / len(good), 2),
            "tradesPerYear": round(sum(r["tradesPerYear"] or 0 for r in good), 1),
        })
    across.sort(key=lambda a: (-a["held"], -a["avgAnnualPct"]))
    return {"shortlist": shortlist[:15], "nearMisses": near[:10], "acrossMarkets": across[:8], "tested": len(rows)}


def job_dict(job: ResearchJob, full: bool = False) -> dict:
    out = {
        "id": job.id, "status": job.status, "automatic": job.automatic, "settings": job.settings or {},
        "createdAt": job.created_at.isoformat(), "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
        "done": job.done, "total": job.total, "message": job.message,
    }
    if full:
        rows = job.rows or []
        out.update({"summary": summarise(rows), "rows": rows, "skipped": job.skipped or []})
    return out
