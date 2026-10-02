"""The backtester: replays history one candle at a time, exactly as you'd have traded it.

On each candle, in this order:
  1. At the open: carry out orders decided at the previous close (exits first, then entries).
     An entry is resized from the actual opening price, and cancelled if the price has
     already jumped past its stop-loss.
  2. During the candle: if the low (or high, for a short) reaches the stop-loss, the trade
     closes at the stop, or at the open if the price gapped through it. Then, for strategies
     with a profit target, the same for the target (if one candle reached both, the stop is
     assumed to have come first, the cautious choice).
  3. At the close: the strategy looks at the finished candle and decides what to do at the
     next open. The risk guard sizes or refuses every new trade.

Prices in the data are mid prices. Buying costs half the spread plus slippage above mid;
selling the same below. Fees, stamp duty, currency conversion and overnight financing are
charged as set in `costs.Costs`. Everything is converted to pounds at the rate on the day.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..market.fx import Converter
from ..market.providers.base import Bar
from ..risk.guard import AccountLimits, RiskSettings, size_trade
from ..strategies.base import Strategy
from .costs import Costs


@dataclass
class Settings:
    start_balance: float = 200.0
    mode: str = "cash"  # cash = real shares/no leverage; cfd = CFD or spread bet with leverage
    direction: str = "long"  # long | both
    risk: RiskSettings = field(default_factory=RiskSettings)
    leverage: float = 1.0
    costs: Costs = field(default_factory=lambda: Costs(0, 0))


@dataclass
class Trade:
    side: int
    entry_i: int
    entry_ts: int
    entry_price: float  # what you actually paid, including spread and slippage
    entry_mid: float
    stop: float
    units: float
    entry_fees_gbp: float
    target: float | None = None
    exit_i: int = -1
    exit_ts: int = 0
    exit_price: float = 0.0
    exit_mid: float = 0.0
    exit_reason: str = ""
    pnl_gbp: float = 0.0
    gross_gbp: float = 0.0  # profit or loss before any costs
    costs_gbp: float = 0.0
    risk_gbp: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "side": "long" if self.side > 0 else "short",
            "entryTime": self.entry_ts, "entryPrice": self.entry_price, "stop": self.stop, "target": self.target,
            "exitTime": self.exit_ts, "exitPrice": self.exit_price, "exitReason": self.exit_reason,
            "units": self.units, "pnl": round(self.pnl_gbp, 2), "gross": round(self.gross_gbp, 2),
            "costs": round(self.costs_gbp, 2),
            "r": round(self.pnl_gbp / self.risk_gbp, 2) if self.risk_gbp > 0 else None,
            "bars": self.exit_i - self.entry_i, "note": self.note,
        }


@dataclass
class Result:
    trades: list[Trade]
    equity: list[tuple[int, float]]
    halted: str = ""
    skipped: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    pending_exit: str = ""  # an exit rule met on the last candle (it would fill at the next open)
    pending_entry: int = 0  # +1 / -1 if an entry was decided on the last candle


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _nights(a: int, b: int) -> int:
    return max(0, (datetime.fromtimestamp(b, tz=timezone.utc).date() - datetime.fromtimestamp(a, tz=timezone.utc).date()).days)


class _Book:
    """Fills, fees and pounds."""

    def __init__(self, costs: Costs, conv: Converter, mode: str) -> None:
        self.c, self.conv, self.mode = costs, conv, mode

    def fill(self, mid: float, buying: bool) -> float:
        adj = self.c.spread_pct / 200 + self.c.slippage_pct / 100
        return mid * (1 + adj) if buying else mid * (1 - adj)

    def value_gbp(self, units: float, price: float, ts: int) -> float:
        return units * price / self.conv.rate(ts)

    def order_fees(self, units: float, price: float, ts: int, buying: bool, opening: bool) -> float:
        value = self.value_gbp(units, price, ts)
        fees = self.c.commission_gbp + value * self.c.fx_fee_pct / 100
        if buying and opening and self.mode == "cash":
            fees += value * self.c.stamp_duty_pct / 100
        return fees

    def financing(self, trade: Trade, ts: int) -> float:
        if not self.c.financing_pct_year or self.mode != "cfd":
            return 0.0
        value = self.value_gbp(trade.units, trade.entry_mid, trade.entry_ts)
        return value * self.c.financing_pct_year / 100 / 365 * _nights(trade.entry_ts, ts)


def _frame(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ts": [b.ts for b in bars], "open": [b.open for b in bars], "high": [b.high for b in bars],
         "low": [b.low for b in bars], "close": [b.close for b in bars], "volume": [b.volume for b in bars]}
    )


def run(bars: list[Bar], strategy: Strategy, params: dict, settings: Settings, conv: Converter) -> Result:
    if strategy.benchmark:
        return buy_and_hold(bars, settings, conv)

    df = _frame(bars)
    rules = strategy.run(df, params)
    book = _Book(settings.costs, conv, settings.mode)
    risk = settings.risk.cleaned()
    allow_short = settings.direction == "both" and settings.mode == "cfd" and rules.short is not None

    sides = [(1, rules.long)] + ([(-1, rules.short)] if allow_short else [])
    entries = {s: side.entry().to_numpy() for s, side in sides}
    exits = {s: side.exit.fillna(False).astype(bool).to_numpy() for s, side in sides}
    stops = {s: side.stop.to_numpy(dtype=float) for s, side in sides}
    targets = {s: (side.target.to_numpy(dtype=float) if side.target is not None else None) for s, side in sides}

    ts = df["ts"].to_numpy(dtype=np.int64)
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))

    cash = settings.start_balance
    limits = AccountLimits(risk, peak=cash)
    trades: list[Trade] = []
    equity: list[tuple[int, float]] = []
    skipped: dict[str, int] = {}
    pos: Trade | None = None
    pending_exit = ""  # the exit rule's description, when one fired at the last close
    pending_entry: tuple[int, float, float | None] | None = None

    def close(i: int, mid: float, reason: str, fill: float | None = None) -> None:
        nonlocal cash, pos
        t = pos
        buying = t.side < 0
        price = fill if fill is not None else book.fill(mid, buying)
        fees = book.order_fees(t.units, price, ts[i], buying, opening=False) + book.financing(t, ts[i])
        move_gbp = (price - t.entry_price) * t.side * t.units / conv.rate(ts[i])
        t.exit_i, t.exit_ts, t.exit_price, t.exit_mid, t.exit_reason = i, int(ts[i]), price, mid, reason
        t.gross_gbp = (mid - t.entry_mid) * t.side * t.units / conv.rate(ts[i])
        t.pnl_gbp = move_gbp - fees - t.entry_fees_gbp
        t.costs_gbp = t.gross_gbp - t.pnl_gbp
        cash += move_gbp - fees
        limits.record(t.pnl_gbp)
        trades.append(t)
        pos = None

    def mark(i: int) -> float:
        if pos is None:
            return cash
        unreal = (c[i] - pos.entry_price) * pos.side * pos.units / conv.rate(ts[i])
        return cash + unreal - book.financing(pos, ts[i])

    for i in range(len(df)):
        limits.new_candle(_day(int(ts[i])), equity[-1][1] if equity else cash)

        # 1. At the open
        if pending_exit and pos is not None:
            close(i, o[i], pending_exit)
        pending_exit = ""
        if pending_entry is not None and pos is None and limits.halted:
            pending_entry = None
        if pending_entry is not None and pos is None:
            side, stop, target = pending_entry
            buying = side > 0
            price = book.fill(o[i], buying)
            if (o[i] - stop) * side <= 0:
                skipped["Price opened beyond the stop-loss"] = skipped.get("Price opened beyond the stop-loss", 0) + 1
            else:
                if settings.mode == "cash":
                    fee_rate = (settings.costs.fx_fee_pct + (settings.costs.stamp_duty_pct if buying else 0)) / 100
                    cap = min(settings.leverage, 1.0) / (1 + fee_rate)
                else:
                    cap = settings.leverage
                d = size_trade(equity_gbp=cash, entry=price, stop=stop, side=side,
                               per_gbp=conv.rate(ts[i]), cap=cap, settings=risk)
                if d.ok:
                    fees = book.order_fees(d.units, price, ts[i], buying, opening=True)
                    cash -= fees
                    if target is not None and (target - o[i]) * side <= 0:
                        target = None  # the price opened past the target already: manage the trade by its exit rule
                    pos = Trade(side=side, entry_i=i, entry_ts=int(ts[i]), entry_price=price, entry_mid=o[i],
                                stop=stop, units=d.units, entry_fees_gbp=fees, target=target,
                                risk_gbp=abs(price - stop) * d.units / conv.rate(ts[i]),
                                note="Leverage-capped" if d.capped else "")
                    if d.capped:
                        label = f"Smaller than {risk.risk_pct:g}% risk (leverage cap)"
                        skipped[label] = skipped.get(label, 0) + 1
                else:
                    skipped[d.reason] = skipped.get(d.reason, 0) + 1
        pending_entry = None

        # 2. During the candle: stop-loss first...
        if pos is not None:
            hit = l[i] <= pos.stop if pos.side > 0 else h[i] >= pos.stop
            if hit:
                gapped = (o[i] - pos.stop) * pos.side <= 0 and pos.entry_i < i
                level = o[i] if gapped else pos.stop
                close(i, level, "Stop-loss (gapped through)" if gapped else "Stop-loss",
                      fill=book.fill(level, buying=pos.side < 0))
        # ...then the profit target (if a candle reached both, the stop is assumed to have come first)
        if pos is not None and pos.target is not None:
            hit = h[i] >= pos.target if pos.side > 0 else l[i] <= pos.target
            if hit:
                gapped = (o[i] - pos.target) * pos.side >= 0 and pos.entry_i < i
                level = o[i] if gapped else pos.target
                close(i, level, "Target reached", fill=book.fill(level, buying=pos.side < 0))

        # 3. At the close
        eq = mark(i)
        equity.append((int(ts[i]), eq))
        limits.new_candle(_day(int(ts[i])), eq)  # a loss on this candle counts before deciding anything new
        if pos is not None:
            if not exits[pos.side][i]:
                continue
            pending_exit = dict(sides)[pos.side].exit_label or "Exit rule"
            # The same close may signal the opposite side (a reversal): it fills after the exit.
            wanted = [s for s, _ in sides if entries[s][i] and s != pos.side]
        else:
            wanted = [s for s, _ in sides if entries[s][i]]
        if len(wanted) != 1:
            continue
        block = limits.entry_block()
        if block:
            skipped[block] = skipped.get(block, 0) + 1
            continue
        tgt = targets[wanted[0]]
        tgt_value = float(tgt[i]) if tgt is not None and np.isfinite(tgt[i]) else None
        pending_entry = (wanted[0], float(stops[wanted[0]][i]), tgt_value)

    final_exit, final_entry = pending_exit, (pending_entry[0] if pending_entry else 0)
    if pos is not None:
        last = len(df) - 1
        close(last, c[last], "Still open at the end of the test")
        equity[-1] = (int(ts[last]), cash)

    return Result(trades, equity, limits.halt_reason if limits.halted else "", skipped, list(rules.notes),
                  pending_exit=final_exit, pending_entry=final_entry)


def buy_and_hold(bars: list[Bar], settings: Settings, conv: Converter) -> Result:
    """Put the whole balance in at the first open (no leverage) and hold to the last close."""
    if len(bars) < 2:
        return Result([], [(b.ts, settings.start_balance) for b in bars])
    book = _Book(settings.costs, conv, settings.mode)
    first, last = bars[0], bars[-1]
    price = book.fill(first.open, True)
    rate = conv.rate(first.ts)
    per_unit_gbp = price / rate
    fee_rate = (settings.costs.fx_fee_pct + (settings.costs.stamp_duty_pct if settings.mode == "cash" else 0)) / 100
    units = max(0.0, (settings.start_balance - settings.costs.commission_gbp) / (per_unit_gbp * (1 + fee_rate)))
    t = Trade(side=1, entry_i=0, entry_ts=first.ts, entry_price=price, entry_mid=first.open, stop=0.0,
              units=units, entry_fees_gbp=book.order_fees(units, price, first.ts, True, True))
    cash = settings.start_balance - t.entry_fees_gbp - units * per_unit_gbp
    equity = []
    for b in bars:
        equity.append((b.ts, cash + units * b.close / conv.rate(b.ts) - book.financing(t, b.ts)))
    exit_price = book.fill(last.close, False)
    exit_fees = book.order_fees(units, exit_price, last.ts, False, False) + book.financing(t, last.ts)
    proceeds = units * exit_price / conv.rate(last.ts)
    t.exit_i, t.exit_ts, t.exit_price, t.exit_mid = len(bars) - 1, last.ts, exit_price, last.close
    t.exit_reason = "End of the test"
    t.gross_gbp = units * (last.close / conv.rate(last.ts) - first.open / rate)
    final = cash + proceeds - exit_fees
    t.pnl_gbp = final - settings.start_balance
    t.costs_gbp = t.gross_gbp - t.pnl_gbp
    equity[-1] = (last.ts, final)
    return Result([t], equity)


# Shared with paper trading, so paper fills and costs follow exactly the same rules as backtests.
Book = _Book
