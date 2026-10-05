"""Monte Carlo check: how differently could the same strategy have turned out by luck alone?

A backtest gives one history: the trades in one particular order. Here each simulated history
draws the same number of trades at random from the real ones (some twice, some not at all) and
replays them on the starting balance at the same risk per trade. Doing that a couple of thousand
times shows the spread of results and worst falls that luck alone could have produced.

Each trade's result is taken as its R multiple (profit or loss after costs ÷ the amount risked),
so a trade that lost its full risk is -1R. Replayed at 1% risk, -1R takes 1% off the balance at
the time. Trades are replayed one after another, so overlapping trades in a basket are treated as
if they came one at a time: a simplification, said so in the notes.
"""

from dataclasses import dataclass

import numpy as np

SIMULATIONS = 2000
MIN_TRADES = 20
CHUNK = 200  # simulations at a time, to keep memory small on long scalping histories
CURVE_POINTS = 120
SEED = 20261005  # fixed, so the same backtest always gives the same answer


@dataclass
class Inputs:
    r: list[float]  # each trade's result in R, in the order they happened
    start_balance: float
    risk_pct: float
    drawdown_limit_pct: float = 20.0
    actual_drawdown_pct: float | None = None
    actual_return_pct: float | None = None


def r_multiples(trades) -> list[float]:
    """R multiples of closed backtest trades (engine.Trade), in order."""
    return [t.pnl_gbp / t.risk_gbp for t in trades if t.risk_gbp and t.risk_gbp > 0]


def _paths(r: np.ndarray, picks: np.ndarray, f: float, start: float) -> np.ndarray:
    """Balance after each trade, for each simulated history (rows)."""
    growth = np.maximum(1.0 + r[picks] * f, 0.0)  # a balance can't go below nothing
    return start * np.cumprod(growth, axis=1)


def _worst_fall(paths: np.ndarray, start: float) -> np.ndarray:
    with_start = np.concatenate([np.full((paths.shape[0], 1), start), paths], axis=1)
    peaks = np.maximum.accumulate(with_start, axis=1)
    return ((peaks - with_start) / peaks).max(axis=1) * 100


def _longest_losing_run(results: np.ndarray) -> np.ndarray:
    out = np.zeros(results.shape[0], dtype=int)
    run = np.zeros(results.shape[0], dtype=int)
    for j in range(results.shape[1]):
        run = np.where(results[:, j] < 0, run + 1, 0)
        out = np.maximum(out, run)
    return out


def run(inp: Inputs, simulations: int = SIMULATIONS) -> dict:
    n = len(inp.r)
    if n < MIN_TRADES:
        return {"ok": False, "reason": f"Only {n} trades: Monte Carlo needs at least {MIN_TRADES} to say anything useful."}
    r = np.asarray(inp.r, dtype=float)
    f = inp.risk_pct / 100
    start = inp.start_balance
    rng = np.random.default_rng(SEED)
    steps = np.unique(np.linspace(0, n - 1, min(CURVE_POINTS, n)).round().astype(int))

    finals, falls, runs, sampled = [], [], [], []
    done = 0
    while done < simulations:
        k = min(CHUNK, simulations - done)
        picks = rng.integers(0, n, size=(k, n))
        paths = _paths(r, picks, f, start)
        finals.append(paths[:, -1])
        falls.append(_worst_fall(paths, start))
        runs.append(_longest_losing_run(r[picks]))
        sampled.append(paths[:, steps])
        done += k
    final = np.concatenate(finals)
    fall = np.concatenate(falls)
    losing = np.concatenate(runs)
    curves = np.concatenate(sampled)

    actual_path = start * np.cumprod(np.maximum(1.0 + r * f, 0.0))
    actual_fall = float(_worst_fall(actual_path[None, :], start)[0])

    def pct(a: np.ndarray, q: float) -> float:
        return float(np.percentile(a, q))

    ret = (final / start - 1) * 100
    bands = {str(q): [round(pct(curves[:, i], q), 2) for i in range(len(steps))] for q in (5, 25, 50, 75, 95)}
    limit = inp.drawdown_limit_pct
    out = {
        "ok": True,
        "simulations": simulations,
        "trades": n,
        "riskPct": inp.risk_pct,
        "startBalance": start,
        "drawdownLimitPct": limit,
        "final": {str(q): round(pct(final, q), 2) for q in (5, 25, 50, 75, 95)},
        "returnPct": {str(q): round(pct(ret, q), 1) for q in (5, 25, 50, 75, 95)},
        "worstFall": {str(q): round(pct(fall, q), 1) for q in (50, 75, 90, 95, 99)},
        "losingRun": {str(q): int(pct(losing, q)) for q in (50, 95, 99)},
        "chanceLoss": round(float((final < start).mean() * 100), 1),
        "chanceLimit": round(float((fall >= limit).mean() * 100), 1),
        "chanceHalved": round(float((fall >= 50).mean() * 100), 1),
        # How the real ordering compares: the share of simulated histories with a smaller worst fall.
        "replayFall": round(actual_fall, 1),
        "replayFallRank": round(float((fall < actual_fall).mean() * 100)),
        "curve": {"step": [int(s) + 1 for s in steps], "bands": bands,
                  "replay": [round(float(actual_path[s]), 2) for s in steps]},
    }
    out["summary"] = summary(out)
    return out


def summary(m: dict) -> list[dict]:
    """Plain-English findings, each with a level like the backtest warnings (info | caution | stop)."""
    lines: list[dict] = []
    wf, ret = m["worstFall"], m["returnPct"]
    lines.append({"level": "info", "text": (
        f"In half of the {m['simulations']:,} reshuffled histories the worst fall was under {wf['50']:.0f}%; "
        f"in 1 in 10 it was over {wf['90']:.0f}%, and in 1 in 20 over {wf['95']:.0f}%. "
        "Plan for the 1-in-20 figure, not the backtest's own.")})
    rank = m["replayFallRank"]
    if rank <= 35:
        lines.append({"level": "caution", "text": (
            f"The backtest's own worst fall ({m['replayFall']:.0f}% replayed this way) was on the lucky side: "
            f"{100 - rank}% of reshuffled histories fell further. Expect deeper falls than the backtest showed.")})
    elif rank >= 65:
        lines.append({"level": "info", "text": (
            f"The backtest's own worst fall ({m['replayFall']:.0f}% replayed this way) was on the unlucky side: "
            f"{rank}% of reshuffled histories fell less.")})
    limit = m["drawdownLimitPct"]
    cl = m["chanceLimit"]
    if cl >= 50:
        lines.append({"level": "caution", "text": (
            f"The {limit:g}% drawdown limit was reached in {cl:.0f}% of histories: with this risk per trade, expect it to "
            "pause trading at some point, by luck alone. Lower risk per trade makes that less likely.")})
    else:
        lines.append({"level": "info", "text": f"The {limit:g}% drawdown limit was reached in {cl:.0f}% of histories."})
    loss = m["chanceLoss"]
    level = "stop" if loss >= 30 else "caution" if loss >= 10 else "info"
    lines.append({"level": level, "text": (
        f"{loss:.0f}% of histories ended below the starting balance. The middle result was {ret['50']:+.0f}%, "
        f"with 9 in 10 between {ret['5']:+.0f}% and {ret['95']:+.0f}%.")})
    lines.append({"level": "info", "text": (
        f"Losing runs: {m['losingRun']['50']} in a row was typical, and 1 in 20 histories had {m['losingRun']['95']} or more. "
        "Knowing that in advance makes a bad run easier to sit through.")})
    if m["chanceHalved"] >= 1:
        lines.append({"level": "stop", "text": (
            f"In {m['chanceHalved']:.0f}% of histories the account fell by half or more at some point. "
            "That's too much risk for a beginner's account.")})
    return lines
