"""Target odds: how often, and how fast, the price has reached a target before a stop-loss.

For every past candle on this market and timeframe, imagine entering at its close with the
same stop and target distances as your plan, scaled to how volatile the market was then
(distances are measured in ATR, so a quiet week and a wild one compare fairly). Then look
forward and see which was touched first and how long it took. If one candle touched both,
the stop is counted first, the cautious assumption.

This describes random entries on this market. A good setup should do better than this; a
backtest of the strategy is the better guide. It's history, not a forecast.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from sqlalchemy.orm import Session

from .backtest.costs import default_costs
from .backtest.service import default_mode
from .indicators.core import atr
from .market.directory import lookup
from .market.service import MAX_HISTORY, get_history
from .market.timeframes import get_timeframe

LADDER = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
MAX_HORIZON = 250  # candles a trade is given to reach either level
MIN_STARTS = 200


def _outcomes(high, low, ts, base, a, side: int, stop_k: float, r_levels: list[float], horizon: int) -> list[dict]:
    starts = len(base) - horizon
    hw = sliding_window_view(high[1:], horizon)[:starts]
    lw = sliding_window_view(low[1:], horizon)[:starts]
    tw = sliding_window_view(ts[1:], horizon)[:starts]
    b, aa = base[:starts], a[:starts]
    runmax = np.maximum.accumulate(hw, axis=1)
    runmin = np.minimum.accumulate(lw, axis=1)
    stop_level = b - side * stop_k * aa
    stop_hit = (runmin <= stop_level[:, None]) if side > 0 else (runmax >= stop_level[:, None])
    t_stop = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), horizon)
    out = []
    for r in r_levels:
        level = b + side * r * stop_k * aa
        hit = (runmax >= level[:, None]) if side > 0 else (runmin <= level[:, None])
        t_tgt = np.where(hit.any(axis=1), hit.argmax(axis=1), horizon)
        won = t_tgt < t_stop  # a tie (same candle) counts as the stop
        lost = (t_stop <= t_tgt) & (t_stop < horizon)
        neither = ~won & ~lost
        n = len(b)
        secs = (tw[np.arange(n), np.minimum(t_tgt, horizon - 1)] - ts[:starts])[won]
        out.append({
            "r": r,
            "targetPct": round(float(won.mean()) * 100, 1),
            "stopPct": round(float(lost.mean()) * 100, 1),
            "neitherPct": round(float(neither.mean()) * 100, 1),
            "medianSeconds": int(np.median(secs)) if secs.size else None,
            "p25Seconds": int(np.percentile(secs, 25)) if secs.size else None,
            "p75Seconds": int(np.percentile(secs, 75)) if secs.size else None,
            # Average result in R before costs, counting trades that hit neither as break-even.
            "grossR": round(float(won.mean() * r - lost.mean()), 3),
        })
    return out


def target_odds(db: Session, code: str, timeframe: str, entry: float, stop: float, target: float | None,
                mode: str = "") -> dict:
    symbol = lookup(db, code)
    tf = get_timeframe(timeframe)
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("Set an entry and a stop-loss first.")
    side = 1 if stop < entry else -1
    history = get_history(db, symbol, tf, MAX_HISTORY)
    bars = history.bars
    horizon = min(MAX_HORIZON, max(20, len(bars) // 5))
    if len(bars) - horizon - 20 < MIN_STARTS:
        raise ValueError(f"Not enough history on this timeframe ({len(bars)} candles) to judge the odds.")

    high = np.array([x.high for x in bars], dtype=float)
    low = np.array([x.low for x in bars], dtype=float)
    close = np.array([x.close for x in bars], dtype=float)
    ts = np.array([x.ts for x in bars], dtype=np.int64)
    import pandas as pd

    a = atr(pd.DataFrame({"high": high, "low": low, "close": close}), 14).to_numpy()
    first = 20  # skip the candles before ATR is ready
    atr_now = float(a[-1])
    if not np.isfinite(atr_now) or atr_now <= 0:
        raise ValueError("Not enough history to measure volatility.")
    stop_k = abs(entry - stop) / atr_now
    plan_r = abs(target - entry) / abs(entry - stop) if target and (target - entry) * side > 0 else None
    levels = sorted(set(LADDER + ([round(plan_r, 3)] if plan_r else [])))

    rows = _outcomes(high[first:], low[first:], ts[first:], close[first:], a[first:], side, stop_k, levels, horizon)

    # Costs in R: the spread and slippage on the way in and out, as a share of the stop distance.
    m = mode if mode in ("cash", "cfd") else default_mode(symbol.asset_class)
    c = default_costs(symbol.asset_class, m)
    cost_pct = c.spread_pct + 2 * c.slippage_pct + 2 * c.fx_fee_pct + (c.stamp_duty_pct if m == "cash" else 0)
    cost_r = round(float(entry * cost_pct / 100 / abs(entry - stop)), 3)
    for row in rows:
        row["netR"] = round(float(row["grossR"]) - cost_r, 3)
        row["targetPrice"] = float(entry + side * row["r"] * abs(entry - stop))
        row["viable"] = bool(row["netR"] > 0)
        row["breakEvenPct"] = round(100 * (1 + cost_r) / (1 + row["r"]), 1)

    current = next((r for r in rows if plan_r and abs(r["r"] - round(plan_r, 3)) < 1e-9), None)
    viable = [r for r in rows if r["viable"]]
    best = max(rows, key=lambda r: r["netR"])
    return {
        "symbol": symbol.to_dict(), "timeframe": tf.code, "side": "long" if side > 0 else "short",
        "starts": int(len(close) - first - horizon), "horizonCandles": horizon, "horizonSeconds": horizon * tf.seconds,
        "years": round(float(ts[-1] - ts[0]) / (365.25 * 86400), 1), "sample": history.sample,
        "stopAtr": round(float(stop_k), 2), "costR": cost_r, "planR": round(plan_r, 2) if plan_r else None,
        "current": current, "ladder": rows, "best": best,
        "anyViable": bool(viable),
        "largestViable": max(viable, key=lambda r: r["r"]) if viable else None,
    }
