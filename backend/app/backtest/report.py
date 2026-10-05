"""Turning a backtest into numbers and honest, plain-English warnings."""

from datetime import datetime, timezone

import numpy as np

from .engine import Result

MIN_TRADES = 30
SECONDS_PER_YEAR = 365.25 * 86400


def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"


def _pct(x: float) -> str:
    return f"{x:+.1f}%"


def max_drawdown(equity: list[tuple[int, float]]) -> tuple[float, float]:
    """Largest fall from a high point, as (percent, pounds)."""
    if not equity:
        return 0.0, 0.0
    values = np.array([v for _, v in equity], dtype=float)
    peaks = np.maximum.accumulate(values)
    drops = peaks - values
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(peaks > 0, drops / peaks * 100, 0.0)
    return float(pct.max()), float(drops.max())


def metrics(result: Result, start: float) -> dict:
    trades = result.trades
    final = result.equity[-1][1] if result.equity else start
    net = final - start
    first_ts = result.equity[0][0] if result.equity else 0
    last_ts = result.equity[-1][0] if result.equity else 0
    years = max((last_ts - first_ts) / SECONDS_PER_YEAR, 1e-9)
    wins = [t.pnl_gbp for t in trades if t.pnl_gbp > 0]
    losses = [t.pnl_gbp for t in trades if t.pnl_gbp <= 0]
    streak = longest = 0
    for t in trades:
        streak = streak + 1 if t.pnl_gbp <= 0 else 0
        longest = max(longest, streak)
    dd_pct, dd_gbp = max_drawdown(result.equity)
    bars_in = sum(max(1, t.exit_i - t.entry_i) for t in trades)
    rs = [t.pnl_gbp / t.risk_gbp for t in trades if t.risk_gbp > 0]
    growth = final / start if start > 0 else 0
    return {
        "start": round(start, 2),
        "final": round(final, 2),
        "net": round(net, 2),
        "returnPct": round(net / start * 100, 2) if start else 0.0,
        "annualPct": round((growth ** (1 / years) - 1) * 100, 2) if growth > 0 and years >= 0.25 else None,
        "years": round(years, 2),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avgWin": round(sum(wins) / len(wins), 2) if wins else None,
        "avgLoss": round(sum(losses) / len(losses), 2) if losses else None,
        "profitFactor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "maxDrawdownPct": round(dd_pct, 2),
        "maxDrawdownGbp": round(dd_gbp, 2),
        "longestLosingRun": longest,
        "avgR": round(sum(rs) / len(rs), 2) if rs else None,
        "costs": round(sum(t.costs_gbp for t in trades), 2),
        "grossNet": round(sum(t.gross_gbp for t in trades), 2),
        "exposurePct": round(min(100.0, bars_in / max(1, len(result.equity)) * 100), 1),
    }


def headline(name: str, m: dict, bh: dict) -> str:
    if m["trades"] == 0:
        return f"{name} found no trades in this period."
    span = f"{m['years']:.1f} years" if m["years"] >= 1 else f"{m['years'] * 12:.0f} months"
    text = (f"Over {span}, {name} turned {_money(m['start'])} into {_money(m['final'])} ({_pct(m['returnPct'])}) "
            f"from {m['trades']} trades, after {_money(m['costs'])} of costs.")
    if bh:
        text += f" Simply buying and holding gave {_pct(bh['returnPct'])}."
    return text


def _month(ts: int) -> str:
    if ts <= 1:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%B %Y")


def warnings(m: dict, bh: dict | None, result: Result, benchmark: bool) -> list[dict]:
    """Each warning: level (stop | caution | info) and text."""
    out: list[dict] = []
    if not benchmark:
        if m["trades"] < MIN_TRADES:
            out.append({"level": "caution", "text": (
                f"Only {m['trades']} trades. Too few to tell skill from luck: aim for at least {MIN_TRADES}. "
                "Try a longer period, a shorter timeframe or other markets.")})
        if m["grossNet"] > 0 and m["net"] <= 0:
            out.append({"level": "stop", "text": (
                f"Profitable before costs ({_money(m['grossNet'])}) but costs ({_money(m['costs'])}) turn it into a loss. "
                "In real trading this loses money.")})
        elif m["grossNet"] > 0 and m["costs"] > 0.5 * m["grossNet"]:
            out.append({"level": "caution", "text": (
                f"Costs ate {m['costs'] / m['grossNet'] * 100:.0f}% of the profit. Small changes in spreads could wipe it out.")})
        if bh is not None and m["net"] < bh["net"]:
            out.append({"level": "caution", "text": (
                f"Lost to simply buying and holding ({_money(m['net'])} vs {_money(bh['net'])}). "
                "All that trading didn't beat doing nothing.")})
    if m["maxDrawdownPct"] >= 25:
        out.append({"level": "caution", "text": (
            f"At its worst the account fell {m['maxDrawdownPct']:.0f}% ({_money(m['maxDrawdownGbp'])}) from its high. "
            "Ask yourself honestly whether you'd have kept going.")})
    if m["longestLosingRun"] >= 8:
        out.append({"level": "info", "text": f"There was a run of {m['longestLosingRun']} losing trades in a row. That's normal for many strategies, but hard to sit through."})
    when = _month(result.limit_hit_ts)
    if result.halted:
        text = (f"Trading stopped{' in ' + when if when else ''}: the account fell {result.limit_pct:g}% from its high "
                "(the drawdown limit), so no new trades were opened after that.") if result.limit_pct else result.halted
        if result.wanted_after_stop:
            text += (f" The rules wanted {result.wanted_after_stop} more trade{'s' if result.wanted_after_stop != 1 else ''}. "
                     "Tick \"Keep testing past the drawdown limit\" to see how they would have gone.")
        out.append({"level": "stop", "text": text})
    elif result.kept_going and result.limit_hit_ts:
        out.append({"level": "caution", "text": (
            f"The account fell {result.limit_pct:g}% from its high{' in ' + when if when else ''}. On a paper or live account "
            "trading would have stopped there; this test kept going to show what happened next. "
            "The results include everything after that point.")})
    for reason, count in result.skipped.items():
        out.append({"level": "info", "text": f"{reason} ({count}×)."})
    for note in result.notes:
        out.append({"level": "stop", "text": note})
    if m["years"] < 2 and m["trades"]:
        out.append({"level": "info", "text": "Less than two years of history: results may just reflect one kind of market."})
    return out
