"""Basket backtest: one strategy trading several markets at once from one shared account.

It follows exactly the same rules as the single-market backtester (engine.py), candle by candle
in time order across all the markets:

  1. At each candle's open: exits first (in every market), then new entries.
  2. During the candle: stop-losses, then profit targets.
  3. At the close: the strategy looks at each market's finished candle and decides what to do
     at its next open.

On top of that, because the markets share one account:

  * every new trade is sized from the account's balance (1% risk by default),
  * the open-risk limit applies across the basket: if the trades already open would lose more than
    the limit (10% by default) if every stop were hit, a new trade is made smaller or skipped,
  * CFD margin and real-share buying power are shared, so a trade can be trimmed for lack of funds,
  * the daily loss and drawdown limits look at the whole account.

With a single market and no binding limits it gives exactly the same result as engine.run, which
the tests check.
"""

from dataclasses import dataclass, field

import numpy as np

from ..market.fx import Converter
from ..market.providers.base import Bar
from ..risk.guard import AccountLimits, RiskSettings, size_trade
from ..strategies.base import Strategy
from .costs import Costs
from .engine import Result, Trade, _Book, _day, _frame


@dataclass
class Leg:
    """One market in the basket."""

    code: str
    bars: list[Bar]
    conv: Converter
    costs: Costs
    leverage: float
    # Filled in by run():
    index: dict[int, int] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)


@dataclass
class BasketResult(Result):
    by_market: dict[str, list[Trade]] = field(default_factory=dict)
    timeline: list[int] = field(default_factory=list)


def run(legs: list[Leg], strategy: Strategy, params: dict, *, start_balance: float, mode: str, direction: str,
        risk: RiskSettings, max_open_risk_pct: float = 10.0, market_spreads: bool = True) -> BasketResult:
    risk = risk.cleaned()
    allow_short_mode = direction == "both" and mode == "cfd"

    # Per-market rule arrays, worked out once.
    state = []
    for leg in legs:
        df = _frame(leg.bars)
        rules = strategy.run(df, params)
        sides = [(1, rules.long)] + ([(-1, rules.short)] if allow_short_mode and rules.short is not None else [])
        leg.index = {int(t): i for i, t in enumerate(df["ts"].to_numpy(dtype=np.int64))}
        leg.trades = []
        state.append({
            "leg": leg, "book": _Book(leg.costs, leg.conv, mode, market_spreads), "sides": sides,
            "entries": {s: side.entry().to_numpy() for s, side in sides},
            "exits": {s: side.exit.fillna(False).astype(bool).to_numpy() for s, side in sides},
            "stops": {s: side.stop.to_numpy(dtype=float) for s, side in sides},
            "targets": {s: (side.target.to_numpy(dtype=float) if side.target is not None else None) for s, side in sides},
            "o": df["open"].to_numpy(dtype=float), "h": df["high"].to_numpy(dtype=float),
            "l": df["low"].to_numpy(dtype=float), "c": df["close"].to_numpy(dtype=float),
            "sp": df["spread"].to_numpy(dtype=float),
            "pos": None, "pending_exit": "", "pending_entry": None, "last_i": None,
            "exit_labels": {s: side.exit_label or "Exit rule" for s, side in sides},
        })

    timeline = sorted({t for leg in legs for t in leg.index})
    cash = start_balance
    limits = AccountLimits(risk, peak=cash)
    equity: list[tuple[int, float]] = []
    skipped: dict[str, int] = {}
    all_trades: list[Trade] = []

    def skip(label: str) -> None:
        skipped[label] = skipped.get(label, 0) + 1

    def unrealised(st, ts: int) -> float:
        pos, i = st["pos"], st["last_i"]
        if pos is None or i is None:
            return 0.0
        return (st["c"][i] - pos.entry_price) * pos.side * pos.units / st["leg"].conv.rate(ts) - st["book"].financing(pos, ts)

    def open_risk(ts: int) -> float:
        total = 0.0
        for st in state:
            pos = st["pos"]
            if pos is not None:
                total += max(0.0, (pos.entry_price - pos.stop) * pos.side * pos.units / st["leg"].conv.rate(ts))
        return total

    def used_funds(ts: int) -> float:
        """Margin held (CFD) or money tied up (real shares) by the open trades."""
        total = 0.0
        for st in state:
            pos, i = st["pos"], st["last_i"]
            if pos is not None and i is not None:
                value = pos.units * st["c"][i] / st["leg"].conv.rate(ts)
                total += value / st["leg"].leverage if mode == "cfd" else value
        return total

    def close(st, g: int, i: int, ts: int, mid: float, reason: str, fill: float | None = None) -> None:
        nonlocal cash
        t, book, conv = st["pos"], st["book"], st["leg"].conv
        buying = t.side < 0
        price = fill if fill is not None else book.fill(mid, buying, st["sp"][i])
        fees = book.order_fees(t.units, price, ts, buying, opening=False) + book.financing(t, ts)
        move = (price - t.entry_price) * t.side * t.units / conv.rate(ts)
        t.exit_i, t.exit_ts, t.exit_price, t.exit_mid, t.exit_reason = g, ts, price, mid, reason
        t.gross_gbp = (mid - t.entry_mid) * t.side * t.units / conv.rate(ts)
        t.pnl_gbp = move - fees - t.entry_fees_gbp
        t.costs_gbp = t.gross_gbp - t.pnl_gbp
        cash += move - fees
        limits.record(t.pnl_gbp)
        st["leg"].trades.append(t)
        all_trades.append(t)
        st["pos"] = None

    for g, ts in enumerate(timeline):
        day = _day(ts)
        limits.new_candle(day, equity[-1][1] if equity else cash)
        active = [st for st in state if ts in st["leg"].index]

        # 1. At the open: exits everywhere first...
        for st in active:
            i = st["leg"].index[ts]
            if st["pending_exit"] and st["pos"] is not None:
                close(st, g, i, ts, st["o"][i], st["pending_exit"])
            st["pending_exit"] = ""
        # ...then entries, in the order the markets were listed.
        for st in active:
            i = st["leg"].index[ts]
            pending, st["pending_entry"] = st["pending_entry"], None
            if pending is None or st["pos"] is not None:
                continue
            if limits.halted:
                continue
            side, stop, target = pending
            book, conv, o = st["book"], st["leg"].conv, st["o"][i]
            buying = side > 0
            price = book.fill(o, buying, st["sp"][i])
            if (o - stop) * side <= 0:
                skip("Price opened beyond the stop-loss")
                continue
            if mode == "cash":
                fee_rate = (st["leg"].costs.fx_fee_pct + (st["leg"].costs.stamp_duty_pct if buying else 0)) / 100
                cap = min(st["leg"].leverage, 1.0) / (1 + fee_rate)
            else:
                cap = st["leg"].leverage
            rate = conv.rate(ts)
            d = size_trade(equity_gbp=cash, entry=price, stop=stop, side=side, per_gbp=rate, cap=cap, settings=risk)
            if not d.ok:
                skip(d.reason)
                continue
            units, note = d.units, "Leverage-capped" if d.capped else ""
            if d.capped:
                skip(f"Smaller than {risk.risk_pct:g}% risk (leverage cap)")
            # Shared funds: margin (CFD) or cash (real shares) already in use elsewhere in the basket.
            eq_now = cash + sum(unrealised(s, ts) for s in state)
            used = used_funds(ts)
            if used > 0:
                free = max(0.0, (eq_now if mode == "cfd" else cash) - used)
                max_units = free * (cap if mode == "cfd" else cap) / (price / rate)
                if units > max_units:
                    if max_units * price / rate < 0.01:
                        skip("Not enough free funds while other trades were open")
                        continue
                    units, note = max_units, "Smaller: funds tied up in other trades"
                    skip("Smaller than planned: funds tied up in other trades")
            # Open-risk limit across the whole basket.
            loss_per_unit = abs(price - stop) / rate
            room = max(0.0, eq_now) * max_open_risk_pct / 100 - open_risk(ts)
            if room < max(0.01, 0.1 * d.units * loss_per_unit):
                skip(f"Open-risk limit ({max_open_risk_pct:g}%) reached: trade skipped")
                continue
            if units * loss_per_unit > room:
                units, note = room / loss_per_unit, f"Smaller: open-risk limit ({max_open_risk_pct:g}%)"
                skip(f"Smaller than planned: open-risk limit ({max_open_risk_pct:g}%)")
            fees = book.order_fees(units, price, ts, buying, opening=True)
            cash -= fees
            if target is not None and (target - o) * side <= 0:
                target = None
            t = Trade(side=side, entry_i=g, entry_ts=ts, entry_price=price, entry_mid=o, stop=stop, units=units,
                      entry_fees_gbp=fees, target=target, risk_gbp=abs(price - stop) * units / rate, note=note)
            t.symbol = st["leg"].code  # type: ignore[attr-defined]
            st["pos"] = t

        # 2. During the candle: stop-loss first, then the target.
        for st in active:
            i = st["leg"].index[ts]
            pos = st["pos"]
            o, hi, lo = st["o"][i], st["h"][i], st["l"][i]
            if pos is not None:
                hit = lo <= pos.stop if pos.side > 0 else hi >= pos.stop
                if hit:
                    gapped = (o - pos.stop) * pos.side <= 0 and pos.entry_i < g
                    level = o if gapped else pos.stop
                    close(st, g, i, ts, level, "Stop-loss (gapped through)" if gapped else "Stop-loss",
                          fill=st["book"].fill(level, pos.side < 0, st["sp"][i]))
            pos = st["pos"]
            if pos is not None and pos.target is not None:
                hit = hi >= pos.target if pos.side > 0 else lo <= pos.target
                if hit:
                    gapped = (o - pos.target) * pos.side >= 0 and pos.entry_i < g
                    level = o if gapped else pos.target
                    close(st, g, i, ts, level, "Target reached", fill=st["book"].fill(level, pos.side < 0, st["sp"][i]))
            st["last_i"] = i

        # 3. At the close: value the account, then each market's rules decide.
        eq = cash + sum(unrealised(st, ts) for st in state)
        equity.append((ts, eq))
        limits.new_candle(day, eq)
        for st in active:
            i = st["leg"].index[ts]
            pos, sides = st["pos"], st["sides"]
            if pos is not None:
                if not st["exits"][pos.side][i]:
                    continue
                st["pending_exit"] = st["exit_labels"][pos.side]
                wanted = [s for s, _ in sides if st["entries"][s][i] and s != pos.side]
            else:
                wanted = [s for s, _ in sides if st["entries"][s][i]]
            if len(wanted) != 1:
                continue
            block = limits.entry_block()
            if block:
                skip(block)
                continue
            tgt = st["targets"][wanted[0]]
            tgt_value = float(tgt[i]) if tgt is not None and np.isfinite(tgt[i]) else None
            st["pending_entry"] = (wanted[0], float(st["stops"][wanted[0]][i]), tgt_value)

    # Anything still open is closed at its last price, so the result is complete.
    if timeline:
        g = len(timeline) - 1
        for st in state:
            if st["pos"] is not None and st["last_i"] is not None:
                i = st["last_i"]
                close(st, g, i, timeline[-1], st["c"][i], "Still open at the end of the test")
        equity[-1] = (timeline[-1], cash)

    all_trades.sort(key=lambda t: (t.exit_ts, t.entry_ts))
    return BasketResult(all_trades, equity, limits.halt_reason if limits.halted else "", skipped, [],
                        by_market={st["leg"].code: st["leg"].trades for st in state}, timeline=timeline)


def equal_weight_hold(legs: list[Leg], timeline: list[int], start_balance: float, hold_results: list[Result]) -> list[tuple[int, float]]:
    """Buy-and-hold of the whole basket: the money split equally, each share held throughout."""
    n = len(legs)
    curves = []
    for res in hold_results:
        pts = res.equity
        curves.append((np.array([p[0] for p in pts], dtype=np.int64), np.array([p[1] for p in pts], dtype=float)))
    out = []
    for ts in timeline:
        total = 0.0
        for times, values in curves:
            k = np.searchsorted(times, ts, side="right") - 1
            total += (values[k] if k >= 0 else start_balance) / n
        out.append((ts, total))
    return out
