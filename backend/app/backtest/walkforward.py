"""Walk-forward check and robustness verdict: does a strategy still work on years it wasn't tuned on?

A normal backtest has a hidden flaw: the settings were chosen by looking at the same history they're
tested on. Try enough settings and one will look good by luck. The walk-forward check removes that
advantage by doing what you'd have had to do for real, without knowing the future:

  1. The shared history is split into 9 equal stretches.
  2. On stretches 1 to 3, every candidate setting is backtested and the one that made the most is picked.
  3. That pick is then traded on stretch 4, which it has never seen. Then everything slides on one
     stretch (tune on 2 to 4, trade 5), and so on: 6 unseen stretches covering the last two-thirds of the history.
  4. The 6 unseen results are joined into one account, carrying the balance forward.

The candidate settings are fixed before the test starts: your settings, the same with every length
×0.5, ×0.75, ×1.5 and ×2, and the strategy's standard settings. Every run here keeps trading past the
drawdown limit, so the whole history is judged; costs, risk sizing and the open-risk limit are exactly
as in a normal backtest (the same basket engine runs every stretch).

The robustness verdict then weighs seven checks: unseen years profitable, how much of the tuned
result survived, how many unseen stretches made money, whether neighbouring settings also work, how
many markets made money, the Monte Carlo chance of ending below the start, and enough unseen trades.
It is evidence about the past, never a prediction or advice to trade.
"""

import threading
from dataclasses import dataclass

from ..risk.guard import RiskSettings
from ..strategies.base import Strategy
from . import basket, montecarlo, report
from .engine import Result

SEGMENTS = 9
TRAIN_SEGMENTS = 3
WINDOWS = SEGMENTS - TRAIN_SEGMENTS
MIN_SEGMENT_CANDLES = 40
FACTORS = (0.5, 0.75, 1.5, 2.0)
SECONDS_PER_YEAR = 365.25 * 86400
MAX_POINTS = 1500

# One check at a time: it's around 60 backtests, and the server is shared.
_busy = threading.Lock()


class Busy(RuntimeError):
    """Another walk-forward check is already running."""


@dataclass
class Setup:
    legs: list[basket.Leg]
    strategy: Strategy
    params: dict
    start_balance: float
    mode: str
    direction: str
    risk: RiskSettings
    max_open_risk_pct: float = 10.0
    market_spreads: bool = True


# --- Candidate settings ------------------------------------------------------------------------------

def _key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


def settings_label(strategy: Strategy, params: dict) -> str:
    """Short name for a set of settings: the lengths joined by '/', e.g. '55/20'."""
    lengths = [f"{params[p.key]:g}" for p in strategy.length_params()]
    return "/".join(lengths) if lengths else "standard"


def candidates(strategy: Strategy, params: dict) -> list[dict]:
    """The settings tried in every tuning stretch, fixed before the test: yours first (it wins ties)."""
    yours = strategy.clean_params(params)
    standard = strategy.clean_params({})
    found: dict[tuple, dict] = {}

    def add(p: dict, role: str) -> None:
        k = _key(p)
        if k in found:
            if role and not found[k]["role"]:
                found[k]["role"] = role
            return
        found[k] = {"params": p, "role": role}

    add(yours, "yours")
    for f in sorted(FACTORS):
        add(strategy.scaled(yours, f), "")
    add(standard, "standard")
    out = []
    for c in found.values():
        label = settings_label(strategy, c["params"])
        if c["role"] == "yours":
            label += " (yours)"
        elif c["role"] == "standard":
            label += " (standard)"
        out.append({**c, "label": label})
    return out


# --- Running ------------------------------------------------------------------------------------------

def _run(setup: Setup, params: dict, start: float, frm: int, to: int | None) -> basket.BasketResult:
    return basket.run(setup.legs, setup.strategy, params, start_balance=start, mode=setup.mode,
                      direction=setup.direction, risk=setup.risk, max_open_risk_pct=setup.max_open_risk_pct,
                      market_spreads=setup.market_spreads, keep_going=True, trade_from=frm, trade_to=to)


def _annual(start: float, end: float, seconds: float) -> float | None:
    years = seconds / SECONDS_PER_YEAR
    if years < 0.25 or start <= 0:
        return None
    growth = end / start
    if growth <= 0:
        return -100.0
    return (growth ** (1 / years) - 1) * 100


def _thin(points: list[tuple[int, float]]) -> list[dict]:
    step = max(1, len(points) // MAX_POINTS)
    picked = points[::step]
    if picked and picked[-1] != points[-1]:
        picked.append(points[-1])
    return [{"time": t, "value": round(v, 2)} for t, v in picked]


def _chain(setup: Setup, windows: list[tuple[int, int]], picks: list[dict], start: float):
    """Trade each unseen stretch with its pick, carrying the balance forward. Returns trades, equity, ends."""
    balance = start
    trades, equity, results = [], [], []
    for (frm, to), params in zip(windows, picks):
        res = _run(setup, params, balance, frm, to)
        end = res.equity[-1][1] if res.equity else balance
        results.append((balance, end, res))
        trades.extend(res.trades)
        equity.extend(res.equity)
        balance = end
    return trades, equity, results


def run(setup: Setup) -> dict:
    """The walk-forward check and verdict. Raises Busy if one is already running."""
    if not _busy.acquire(blocking=False):
        raise Busy("A walk-forward check is already running. Try again in a minute.")
    try:
        return _run_check(setup)
    finally:
        _busy.release()


def _run_check(setup: Setup) -> dict:
    s, start = setup.strategy, setup.start_balance
    timeline = sorted({b.ts for leg in setup.legs for b in leg.bars})
    n = len(timeline)
    need = SEGMENTS * MIN_SEGMENT_CANDLES
    if n < need:
        return {"ok": False, "reason": (
            f"The walk-forward check needs at least {need} candles of shared history ({SEGMENTS} stretches of "
            f"{MIN_SEGMENT_CANDLES}); this test has {n}. Try a shorter timeframe, more history, or leave out "
            "a market with a short history.")}

    cands = candidates(s, setup.params)
    edges = [round(k * n / SEGMENTS) for k in range(SEGMENTS + 1)]
    windows = []
    for w in range(WINDOWS):
        train = (timeline[edges[w]], timeline[edges[w + TRAIN_SEGMENTS] - 1])
        test = (timeline[edges[w + TRAIN_SEGMENTS]], timeline[edges[w + TRAIN_SEGMENTS + 1] - 1])
        windows.append((train, test))

    # 1. Tune: in each training stretch, the candidate that made the most (yours wins a tie).
    picks, tuned = [], []
    for (frm, to), _test in windows:
        best, best_ret, best_end = cands[0], None, start
        for c in cands:
            res = _run(setup, c["params"], start, frm, to)
            end = res.equity[-1][1] if res.equity else start
            ret = (end / start - 1) * 100
            if best_ret is None or ret > best_ret + 1e-9:
                best, best_ret, best_end = c, ret, end
        picks.append(best)
        tuned.append({"returnPct": best_ret or 0.0, "annualPct": _annual(start, best_end, to - frm)})

    # 2. Trade each unseen stretch with its pick, and (for comparison) with your settings throughout.
    tests = [t for _, t in windows]
    wf_trades, wf_equity, wf_results = _chain(setup, tests, [p["params"] for p in picks], start)
    yours = cands[0]
    fx_trades, fx_equity, fx_results = _chain(setup, tests, [yours["params"]] * len(tests), start)
    wf_m = report.metrics(Result(wf_trades, wf_equity), start)
    fx_m = report.metrics(Result(fx_trades, fx_equity), start)
    span = (tests[-1][1] - tests[0][0])
    wf_annual = _annual(start, wf_m["final"], span)
    fx_annual = _annual(start, fx_m["final"], span)
    tuned_annuals = [t["annualPct"] for t in tuned if t["annualPct"] is not None]
    tuned_annual = sum(tuned_annuals) / len(tuned_annuals) if tuned_annuals else None
    efficiency = (wf_annual / tuned_annual * 100) if (tuned_annual and tuned_annual > 0 and wf_annual is not None) else None

    rows = []
    for k, (((tf, tt), (sf, st)), pick, tu) in enumerate(zip(windows, picks, tuned)):
        b0, b1, res = wf_results[k]
        y0, y1, _ = fx_results[k]
        rows.append({
            "trainFrom": tf, "trainTo": tt, "testFrom": sf, "testTo": st,
            "picked": pick["label"], "pickedParams": pick["params"],
            "tunedReturnPct": round(tu["returnPct"], 1),
            "tunedAnnualPct": None if tu["annualPct"] is None else round(tu["annualPct"], 1),
            "testReturnPct": round((b1 / b0 - 1) * 100, 1) if b0 > 0 else 0.0,
            "testTrades": len(res.trades),
            "yoursTestReturnPct": round((y1 / y0 - 1) * 100, 1) if y0 > 0 else 0.0,
        })

    # 3. Neighbouring settings over the whole history: a plateau, or one lucky peak?
    whole = []
    by_market: dict[str, list] = {}
    for c in cands:
        res = _run(setup, c["params"], start, timeline[0], None)
        m = report.metrics(res, start)
        whole.append({"label": c["label"], "params": c["params"], "role": c["role"],
                      "returnPct": m["returnPct"], "annualPct": m["annualPct"], "profitFactor": m["profitFactor"],
                      "trades": m["trades"], "maxDrawdownPct": m["maxDrawdownPct"], "avgR": m["avgR"]})
        if c is yours:
            by_market = res.by_market

    # 4. Monte Carlo on the unseen trades only.
    mc = montecarlo.run(montecarlo.Inputs(r=montecarlo.r_multiples(wf_trades), start_balance=start,
                                          risk_pct=setup.risk.risk_pct, drawdown_limit_pct=setup.risk.max_drawdown_pct))

    checks = _checks(wf_m, efficiency, tuned_annual, rows, whole, by_market, mc, len(setup.legs))
    verdict = _verdict(checks)
    distinct = len({r["picked"] for r in rows})
    notes = []
    if len(cands) == 1:
        notes.append("This strategy has no length settings to tune, so the same settings were used throughout: "
                     "this is a plain check on unseen years.")
    elif distinct >= 4:
        notes.append(f"The best settings changed a lot from stretch to stretch ({distinct} different picks in 6): "
                     "a sign the strategy's edge depends on settings that don't stay put.")
    elif distinct == 1:
        notes.append(f"The same settings ({rows[0]['picked']}) won every tuning stretch: a steady choice.")
    notes.append("Your settings on the same unseen years are shown for comparison, but you chose them after seeing the "
                 "whole history, so their result there isn't a fair unseen test. The walk-forward line is.")

    def year(ts: int) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %Y")

    headline = (
        f"Tuned on 3 stretches and traded on the next, 6 times over ({year(tests[0][0])} to {year(tests[-1][1])}): "
        f"the unseen years turned £{start:,.2f} into £{wf_m['final']:,.2f} ({wf_m['returnPct']:+.1f}%"
        + (f", {wf_annual:+.1f}% a year" if wf_annual is not None else "") + ")"
        + (f", against {tuned_annual:+.1f}% a year in the stretches the settings were tuned on." if tuned_annual is not None else ".")
    )
    return {
        "ok": True,
        "strategy": {"key": s.key, "name": s.name, "params": setup.params},
        "segments": SEGMENTS, "trainSegments": TRAIN_SEGMENTS, "windows": rows,
        "candidates": [c["label"] for c in cands],
        "unseen": {"from": tests[0][0], "to": tests[-1][1], "metrics": wf_m,
                   "annualPct": None if wf_annual is None else round(wf_annual, 2),
                   "equity": _thin(wf_equity)},
        "yours": {"metrics": fx_m, "annualPct": None if fx_annual is None else round(fx_annual, 2),
                  "equity": _thin(fx_equity)},
        "tunedAnnualPct": None if tuned_annual is None else round(tuned_annual, 2),
        "efficiencyPct": None if efficiency is None else round(efficiency, 0),
        "settings": whole,
        "monteCarlo": mc,
        "checks": checks, "verdict": verdict, "notes": notes, "headline": headline,
        "startBalance": start,
    }


# --- Checks and verdict -------------------------------------------------------------------------------

def _check(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _checks(wf: dict, efficiency, tuned_annual, rows, whole, by_market, mc, n_markets) -> list[dict]:
    out = []
    ret, avg_r = wf["returnPct"], wf["avgR"]
    out.append(_check("unseen", "Made money on unseen years",
                      "pass" if ret > 0 and (avg_r or 0) > 0 else "fail",
                      f"The 6 unseen stretches together: {ret:+.1f}%, average {avg_r if avg_r is not None else '–'}R a trade."))

    if tuned_annual is None or tuned_annual <= 0:
        out.append(_check("efficiency", "Kept its tuned edge", "fail",
                          "Even the best settings lost money in the tuning stretches, so there was no edge to keep."))
    else:
        e = efficiency if efficiency is not None else 0.0
        status = "pass" if e >= 50 else "warn" if e >= 25 else "fail"
        out.append(_check("efficiency", "Kept its tuned edge", status,
                          f"Unseen years kept {max(e, -999):.0f}% of the yearly return seen while tuning "
                          f"({tuned_annual:+.1f}% a year). 50% or more is a good sign; well below means the tuning mostly found luck."))

    wins = sum(1 for r in rows if r["testReturnPct"] > 0)
    out.append(_check("windows", "Made money in most unseen stretches",
                      "pass" if wins >= 4 else "warn" if wins == 3 else "fail",
                      f"{wins} of {len(rows)} unseen stretches made money."))

    if len(whole) > 1:
        good = sum(1 for w in whole if w["returnPct"] > 0)
        share = good / len(whole)
        out.append(_check("plateau", "Neighbouring settings work too",
                          "pass" if share >= 0.8 else "warn" if share >= 0.5 else "fail",
                          f"{good} of {len(whole)} settings tried made money over the whole history. A good strategy works "
                          "across a range of settings, not just one lucky number."))

    if n_markets > 1:
        nets = [sum(t.pnl_gbp for t in ts) for ts in by_market.values()]
        good = sum(1 for v in nets if v > 0)
        share = good / len(nets) if nets else 0
        out.append(_check("markets", "Works across markets",
                          "pass" if share >= 2 / 3 else "warn" if share >= 0.5 else "fail",
                          f"With your settings, {good} of {len(nets)} markets made money over the whole history."))

    if mc.get("ok"):
        loss = mc["chanceLoss"]
        out.append(_check("luck", "Survives bad luck",
                          "pass" if loss <= 5 else "warn" if loss <= 20 else "fail",
                          f"Reshuffling the unseen trades 2,000 times, {loss:.0f}% of histories ended below the start."))
    else:
        out.append(_check("luck", "Survives bad luck", "warn", mc.get("reason", "Too few trades for a Monte Carlo check.")))

    trades = wf["trades"]
    out.append(_check("trades", "Enough unseen trades",
                      "pass" if trades >= 30 else "warn" if trades >= 15 else "fail",
                      f"{trades} trades in the unseen stretches. Under 30 is too few to tell skill from luck."))
    return out


VERDICTS = {
    "reject": ("Reject", "It didn't hold up on years it wasn't tuned on. As it stands, the edge looks like luck or "
                         "hindsight. Don't put it on paper; change the idea, not just the numbers."),
    "watchlist": ("Watchlist", "There's something there, but a real weakness too. Keep it in view and look again with "
                               "more markets or history before giving it a paper account."),
    "incubate": ("Incubate", "It held up on unseen years with a doubt or two. Worth running on paper to see whether it "
                             "behaves as tested."),
    "candidate": ("Candidate", "It passed every check here. Run it on paper: it still has to prove itself there "
                               "before the graduation checklist."),
}


def _verdict(checks: list[dict]) -> dict:
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    unseen_failed = any(c["key"] == "unseen" for c in fails)
    if unseen_failed or len(fails) >= 2:
        key = "reject"
    elif fails or len(warns) >= 3:
        key = "watchlist"
    elif warns:
        key = "incubate"
    else:
        key = "candidate"
    label, text = VERDICTS[key]
    return {"key": key, "label": label, "text": text,
            "passed": sum(1 for c in checks if c["status"] == "pass"), "total": len(checks)}
