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
# Ready-made groups of markets. Commodities, indices and currencies come from OANDA; company shares
# and sector funds (ETFs) from Twelve Data's free plan, which allows only a few requests a minute,
# so those are scanned on daily and weekly candles and a few at a time.
SECTORS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "AVGO", "XLK", "NAS100_USD"],
    "Pharma & health": ["LLY", "JNJ", "PFE", "MRK", "ABBV", "UNH", "AMGN", "XLV", "IBB"],
    "Energy": ["XOM", "CVX", "COP", "XLE", "BCO_USD", "WTICO_USD", "NATGAS_USD"],
    "Financials": ["JPM", "BAC", "GS", "V", "MA", "XLF"],
    "Agriculture": ["CORN_USD", "WHEAT_USD", "SOYBN_USD", "SUGAR_USD", "DBA", "ADM", "DE"],
    "Metals & mining": ["XAU_USD", "XAG_USD", "XCU_USD", "XPT_USD", "GDX", "FCX", "NEM"],
    "Consumer": ["KO", "PG", "PEP", "MCD", "WMT", "COST", "XLP"],
    "Stock indices": ["SPX500_USD", "NAS100_USD", "US30_USD", "UK100_GBP", "DE30_EUR", "JP225_USD"],
    "Currencies": ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "EUR_GBP"],
}
SHARE_TIMEFRAMES = ("1d", "1w")  # Twelve Data markets: one request gives years of daily or weekly candles
SHARE_LOADS_PER_MINUTE = 3  # leaves most of the 8-a-minute allowance for your charts
MAX_RETRIES = 5
TIMEFRAMES = ("5m", "15m", "4h", "1d", "1w")
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
LEVELS = {"oversold", "exit_level", "rsi_level", "adx_max"}  # thresholds, not lengths: left alone by the robustness check


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
            if p.key not in LEVELS and not p.key.endswith("_hour") and float(p.step).is_integer() and float(p.default).is_integer() and p.default >= 2:
                step = int(p.step) or 1
                steps = p.default * factor / step  # stay on the setting's own steps, and always move off the default
                scaled = max(step, (math.floor(steps) if factor < 1 else math.ceil(steps)) * step)
                changed[p.key] = max(p.minimum, min(p.maximum, scaled))
        if changed:
            out.append(s.clean_params({**base, **changed}))
    return out


# --- Jobs ------------------------------------------------------------------------------------------

def start(db: Session, user: User, markets: list[str] | None = None, timeframes: list[str] | None = None,
          automatic: bool = False, strategy_keys: list[str] | None = None) -> ResearchJob:
    busy = db.scalar(select(ResearchJob).where(ResearchJob.user_id == user.id, ResearchJob.status.in_(("queued", "running"))))
    if busy is not None:
        raise ResearchError("A scan is already running. It'll finish in a few minutes.")
    markets = list(dict.fromkeys(markets or BASKET))[:MAX_MARKETS]
    timeframes = [t for t in dict.fromkeys(timeframes or DEFAULT_TIMEFRAMES) if t in TIMEFRAMES] or DEFAULT_TIMEFRAMES
    available = {s.key: s for s in strategies()}
    unknown = [k for k in (strategy_keys or []) if k not in available]
    if unknown:
        raise ResearchError(f"Unknown or non-scannable strategy: {', '.join(unknown)}.")
    chosen = [available[k] for k in dict.fromkeys(strategy_keys or [])] or list(available.values())
    # One unit of work per market, timeframe and strategy, so no single step holds up the worker for long.
    units = [[m, t, s.key] for m in markets for t in timeframes for s in chosen
             if not (s.intraday_only and get_timeframe(t).seconds > 900)]
    if not units:
        raise ResearchError("The scalping strategies only run on short candles: tick 5 or 15 minutes as well.")
    job = ResearchJob(user_id=user.id, status="queued", automatic=automatic,
                      settings={"markets": markets, "timeframes": timeframes, "balance": BALANCE, "riskPct": 1.0,
                                "strategies": [s.key for s in chosen] if strategy_keys else []},
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
            start(db, user, settings.get("markets"), settings.get("timeframes"), automatic=True,
                  strategy_keys=settings.get("strategies") or None)
            log.info("Queued the weekly strategy scan for user %s", user.id)
        except ResearchError:
            pass


class _Later(Exception):
    """The free allowance for US share prices is used up for now: try this market again next pass."""


_share_loads: list[float] = []
_cache: dict = {}  # the market being scanned, kept between passes so its prices aren't fetched twice


def _pace_shares() -> None:
    now = time.time()
    _share_loads[:] = [t for t in _share_loads if now - t < 60]
    if len(_share_loads) >= SHARE_LOADS_PER_MINUTE:
        raise _Later()
    _share_loads.append(now)


def work(db: Session, budget: float = PASS_BUDGET_SECONDS) -> bool:
    """Do some of the oldest unfinished scan. Returns True if there was anything to do."""
    job = db.scalar(select(ResearchJob).where(ResearchJob.status.in_(("queued", "running"))).order_by(ResearchJob.id).limit(1))
    if job is None:
        return False
    started = time.time()
    job.status = "running"
    rows, skipped, todo = list(job.rows or []), list(job.skipped or []), list(job.todo or [])
    first = True
    cache = _cache
    if cache.get("job") != job.id:  # a new scan starts with fresh prices
        cache.clear()
        cache["job"] = job.id
    skipped_keys = {(k["market"], k["timeframe"]) for k in skipped}
    while todo and (first or time.time() - started < budget):  # always at least one unit per pass
        first = False
        unit = todo.pop(0)
        code, tf = unit[0], unit[1]
        keys = [unit[2]] if len(unit) > 2 else [x.key for x in strategies()]
        try:
            for key in keys:
                new_rows, note = scan_unit(db, code, tf, key, cache)
                rows.extend(new_rows)
                if note and (code, tf) not in skipped_keys:
                    skipped.append({"market": code, "timeframe": tf, "reason": note})
                    skipped_keys.add((code, tf))
        except _Later:
            todo.insert(0, unit)  # back to the front; carries on next pass
            job.message = (f"Tested {job.total - len(todo)} of {job.total}. Pausing briefly: US share prices "
                           "are fetched a few a minute to stay inside the free allowance.")
            break
        except ProviderError as exc:
            tries = (unit[3] if len(unit) > 3 else 0) + 1
            if "limit" in str(exc).lower() and tries < MAX_RETRIES:
                todo.insert(0, [code, tf, unit[2] if len(unit) > 2 else keys[0], tries])
                break
            if (code, tf) not in skipped_keys:
                skipped.append({"market": code, "timeframe": tf, "reason": str(exc)[:200]})
                skipped_keys.add((code, tf))
        except ValueError as exc:
            if (code, tf) not in skipped_keys:
                skipped.append({"market": code, "timeframe": tf, "reason": str(exc)[:200]})
                skipped_keys.add((code, tf))
        except Exception as exc:  # one market's problem never stops the scan
            log.exception("Scan of %s %s failed", code, tf)
            if (code, tf) not in skipped_keys:
                skipped.append({"market": code, "timeframe": tf, "reason": f"Unexpected problem: {exc.__class__.__name__}"})
                skipped_keys.add((code, tf))
        job.done = job.total - len(todo)
        job.message = f"Tested {job.done} of {job.total} combinations of market, timeframe and strategy."
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


def _market_data(db: Session, code: str, timeframe: str, cache: dict) -> dict:
    """Prices, buy-and-hold and the currency converter for one market and timeframe (kept for the pass)."""
    key = (code, timeframe)
    if key in cache:
        return cache[key]
    for k in [k for k in cache if k != "job"]:
        del cache[k]  # only the market being scanned is kept in memory
    symbol = lookup(db, code)
    if symbol.provider == "alphavantage":
        out = {"note": "UK shares aren't scanned: their free data allows only 25 requests a day."}
    elif symbol.provider == "twelvedata" and timeframe not in SHARE_TIMEFRAMES:
        out = {"note": "US shares and funds are scanned on daily and weekly candles only (free data limits)."}
    else:
        if symbol.provider == "twelvedata":
            _pace_shares()
        tf = get_timeframe(timeframe)
        history = get_history(db, symbol, tf)
        bars = history.bars
        if history.sample:
            out = {"note": "Sample prices only (no data key)."}
        elif len(bars) < 300:
            out = {"note": f"Only {len(bars)} candles of history: too short to judge."}
        else:
            conv = converter(db, quote_currency(symbol))
            bh_settings = replace(_settings(symbol, "cash", "long"), leverage=1.0)
            bh_settings = replace(bh_settings, costs=replace(bh_settings.costs, financing_pct_year=0.0))
            out = {"note": "", "symbol": symbol, "tf": tf, "bars": bars, "conv": conv,
                   "bh": report.metrics(engine.buy_and_hold(bars, bh_settings, conv), BALANCE),
                   "cutoff": bars[0].ts + (bars[-1].ts - bars[0].ts) * (1 - RECENT_SHARE),
                   "years": (bars[-1].ts - bars[0].ts) / (365.25 * 86400)}
    cache[key] = out
    return out


def scan_market(db: Session, code: str, timeframe: str) -> tuple[list[dict], str]:
    """Every strategy on one market and timeframe. Returns the result rows and a note if it was skipped."""
    cache: dict = {}
    rows: list[dict] = []
    for s in strategies():
        new, note = scan_unit(db, code, timeframe, s.key, cache)
        if note:
            return [], note
        rows.extend(new)
    return rows, ""


def scan_unit(db: Session, code: str, timeframe: str, strategy_key: str, cache: dict) -> tuple[list[dict], str]:
    """One strategy (both directions) on one market and timeframe."""
    data = _market_data(db, code, timeframe, cache)
    if data["note"]:
        return [], data["note"]
    s = STRATEGIES[strategy_key]
    symbol, tf, bars, conv, bh = data["symbol"], data["tf"], data["bars"], data["conv"], data["bh"]
    if s.intraday_only and tf.seconds > 900:
        return [], ""
    cutoff, years = data["cutoff"], data["years"]
    mode = "cfd"
    rows = []
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
            "maxDrawdownPct": m["maxDrawdownPct"], "costs": m["costs"], "grossNet": m["grossNet"],
            "costShare": round(m["costs"] / m["grossNet"] * 100) if m["grossNet"] > 0 else None,
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
            # Tests shorter than a year: the average result over the test itself, never scaled up to a year.
            "years": round(min(r.get("years") or 0 for r in good), 1),
            "avgReturnPct": round(sum(r["returnPct"] for r in good) / len(good), 2),
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
