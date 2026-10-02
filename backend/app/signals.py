"""The signal assistant: what each strategy's rules say about the chart on screen.

For the last finished candle, every strategy gets:
  * a checklist of its conditions, each ticked or not,
  * a status: No setup, Watch: forming, Setup complete, or In a trade (the rules
    would already be holding a position),
  * evidence: how the same rules did on this market and timeframe in the past,
    with costs, and how past signals on the same side turned out,
  * the trade plan the rules imply (entry, stop-loss, size from the risk guard).

It reports rules and history. It never tells you to buy or sell.
"""

import time
from collections import OrderedDict

from sqlalchemy.orm import Session

from .backtest import engine, report
from .backtest.costs import default_costs
from .backtest.service import default_mode
from .market.directory import lookup
from .market.fx import converter, quote_currency
from .market.service import MAX_HISTORY, get_history
from .market.timeframes import get_timeframe
from .risk.guard import RiskSettings, leverage_cap, size_trade
from .strategies.library import STRATEGIES

SKIP = {"buy_hold", "support_resistance"}  # the yardstick, and the one that needs your own levels
STATUS_ORDER = {"complete": 0, "forming": 1, "in_trade": 2, "none": 3}
_cache: OrderedDict[tuple, dict] = OrderedDict()
CACHE_SIZE = 64


def evaluate(db: Session, code: str, timeframe: str, balance: float = 200.0, risk_pct: float = 1.0, mode: str = "") -> dict:
    symbol = lookup(db, code)
    tf = get_timeframe(timeframe)
    mode = mode if mode in ("cash", "cfd") else default_mode(symbol.asset_class)
    history = get_history(db, symbol, tf, MAX_HISTORY)
    bars = history.bars
    if len(bars) < 60:
        raise ValueError(f"Not enough finished candles for {symbol.name} on {tf.label} yet.")

    key = (symbol.code, tf.code, bars[-1].ts, len(bars), round(balance, 2), round(risk_pct, 2), mode, history.sample)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    conv = converter(db, quote_currency(symbol))
    risk = RiskSettings(risk_pct=risk_pct).cleaned()
    cap = leverage_cap(symbol.code, symbol.asset_class, mode)
    settings = engine.Settings(start_balance=balance, mode=mode, direction="both" if mode == "cfd" else "long",
                               risk=risk, leverage=cap, costs=default_costs(symbol.asset_class, mode))
    bh_settings = engine.Settings(start_balance=balance, mode="cash", leverage=1.0,
                                  costs=default_costs(symbol.asset_class, "cash"))
    bh = report.metrics(engine.buy_and_hold(bars, bh_settings, conv), balance)
    df = engine._frame(bars)
    last = len(bars) - 1
    now_rate = conv.rate(bars[-1].ts)

    cards = []
    for s in STRATEGIES.values():
        if s.key in SKIP or (s.intraday_only and tf.seconds > 900):
            continue
        params = s.clean_params({})
        rules = s.run(df, params)
        result = engine.run(bars, s, params, settings, conv)
        m = report.metrics(result, balance)
        open_trade = next((t for t in result.trades if t.exit_reason.startswith("Still open")), None)

        sides = [("long", 1, rules.long)]
        if mode == "cfd" and rules.short is not None:
            sides.append(("short", -1, rules.short))

        items = []
        for side_name, sign, side in sides:
            checks = [{"label": label, "ok": bool(series.iloc[last]) if series.iloc[last] == series.iloc[last] else False}
                      for label, series in side.conditions.items()]
            met = sum(c["ok"] for c in checks)
            total = len(checks)
            stop = side.stop.iloc[last]
            stop = float(stop) if stop == stop else None
            if met == total and stop is not None:
                status = "complete"
            elif total > 1 and met >= max(1, (total + 1) // 2):
                status = "forming"
            else:
                status = "none"
            past = [t for t in result.trades if t.side == sign and not t.exit_reason.startswith("Still open")]
            wins = [t for t in past if t.pnl_gbp > 0]
            rs = [t.pnl_gbp / t.risk_gbp for t in past if t.risk_gbp > 0]
            evidence = {
                "trades": len(past),
                "winRate": round(len(wins) / len(past) * 100, 1) if past else None,
                "avgR": round(sum(rs) / len(rs), 2) if rs else None,
                "lowSample": len(past) < report.MIN_TRADES,
            }
            plan = None
            if status in ("complete", "forming") and stop is not None:
                entry = float(df["close"].iloc[last])
                d = size_trade(equity_gbp=balance, entry=entry, stop=stop, side=sign, per_gbp=now_rate, cap=cap, settings=risk)
                plan = {
                    "entry": entry, "stop": stop, "units": d.units if d.ok else 0,
                    "riskGbp": round(d.units * abs(entry - stop) / now_rate, 2) if d.ok else 0,
                    "valueGbp": round(d.units * entry / now_rate, 2) if d.ok else 0,
                    "note": d.reason, "stopRule": side.stop_label, "exitRule": side.exit_label,
                }
                if side.target is not None and side.target.iloc[last] == side.target.iloc[last]:
                    plan["target"] = float(side.target.iloc[last])
                    plan["targetRule"] = side.target_label
            waiting = [c["label"] for c in checks if not c["ok"]]
            if status == "complete":
                reason = (f"All {total} conditions are met on the latest finished candle. "
                          f"Under these rules a {'buy' if sign > 0 else 'short'} would be placed at the next open. "
                          f"Stop-loss: {side.stop_label}.")
            elif status == "forming":
                reason = f"{met} of {total} conditions are met. Still waiting for: " + "; ".join(w[0].lower() + w[1:] for w in waiting) + "."
            else:
                reason = f"{met} of {total} conditions are met, so there's no setup."
            item = {"side": side_name, "status": status, "checks": checks, "met": met, "total": total,
                    "reason": reason, "evidence": evidence, "plan": plan}
            items.append(item)
        best = min(items, key=lambda it: (STATUS_ORDER[it["status"]], -it["met"] / max(it["total"], 1)))

        card = {
            "key": s.key, "name": s.name, "summary": s.summary,
            "status": best["status"], "best": best,
            "sides": items,
            "history": {
                "trades": m["trades"], "returnPct": m["returnPct"], "annualPct": m["annualPct"],
                "maxDrawdownPct": m["maxDrawdownPct"], "winRate": m["winRate"], "years": m["years"],
                "beatsBuyHold": bool(m["net"] > bh["net"]),
            },
        }
        if open_trade is not None:
            # The rules already hold a position, so a new setup on the same side wouldn't be taken.
            card["status"] = "in_trade"
            card["openTrade"] = {
                "side": "long" if open_trade.side > 0 else "short", "since": open_trade.entry_ts,
                "entry": open_trade.entry_price, "stop": open_trade.stop,
                "exitRule": (rules.long if open_trade.side > 0 else rules.short).exit_label,
                "exitPending": bool(result.pending_exit),
            }
        if result.halted:
            card["note"] = result.halted
        cards.append(card)

    cards.sort(key=lambda c: (STATUS_ORDER[c["status"]], -(c["best"]["met"] / max(c["best"]["total"], 1))))
    out = {
        "symbol": symbol.to_dict(), "timeframe": tf.code, "candleClosed": bars[-1].ts + tf.seconds,
        "mode": mode, "balance": balance, "riskPct": risk.risk_pct,
        "sample": history.sample, "years": round((bars[-1].ts - bars[0].ts) / (365.25 * 86400), 1),
        "buyHold": {"returnPct": bh["returnPct"], "annualPct": bh["annualPct"]},
        "strategies": cards, "generatedAt": int(time.time()),
    }
    _cache[key] = out
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return out
