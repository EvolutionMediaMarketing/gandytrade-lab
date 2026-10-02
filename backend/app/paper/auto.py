"""Automatic paper trading: a strategy trades a paper account by its own rules, on live prices.

This is a forward test: the honest check of a backtest. Each run is one strategy on one market
and timeframe. Whenever a new candle finishes, the background worker looks at it exactly as the
backtester would:

  * if the run has an open trade and the strategy's exit rule is met, the trade is closed;
  * if the run has no open trade and every entry condition for one side is met, a trade is opened
    with the strategy's own stop-loss (the same candle can close one side and open the other).

Orders are placed at the current price, which is the next candle's open in the backtester. If the
market is closed, the run waits for it to open. Every automatic order goes through the same
safeguards as a manual one: the account's pause and daily loss limit, 1% risk sizing, buying power
and the open-risk limit. Stop-losses are watched every minute like any other paper trade.

Only paper money is ever involved; nothing is sent to a broker.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..backtest import engine
from ..backtest import service as backtests
from ..market.directory import lookup
from ..market.hours import next_open
from ..market.providers.base import Bar, ProviderError
from ..market.service import get_history
from ..market.symbols import Symbol
from ..market.timeframes import Timeframe, get_timeframe
from ..models import AutoRun, PaperAccount, PaperTrade, User
from ..strategies.base import Strategy
from ..strategies.library import STRATEGIES, get_strategy
from . import service as paper

log = logging.getLogger(__name__)

# Timeframes each free data service can keep up with. Short ones would use up the free allowances.
# UK shares aren't offered: their free data is daily only, with no live price to fill an order at,
# and only 25 requests a day.
TIMEFRAMES = {"oanda": ["15m", "30m", "1h", "4h", "1d"], "twelvedata": ["1h", "4h", "1d"]}
# How often a run that's waiting for a new candle looks again, per data service.
LOOK_EVERY = {"oanda": 60, "twelvedata": 300}
NOT_AUTOMATIC = {"buy_hold", "support_resistance"}  # the yardstick, and the one that needs your own levels
MAX_RUNNING = 10
HISTORY = 600  # candles the rules look back over (the longest indicator uses 200)
MAX_ERRORS = 5  # problems in a row before a run pauses itself


class AutoError(ValueError):
    """A reason a run can't be set up or changed, in plain words."""


def automatic_strategies() -> list[Strategy]:
    return [s for k, s in STRATEGIES.items() if k not in NOT_AUTOMATIC]


def allowed_timeframes(symbol: Symbol) -> list[str]:
    return TIMEFRAMES.get(symbol.provider, [])


# --- The decision (pure, so it's easy to test) ------------------------------------------------

@dataclass
class Decision:
    exit_label: str = ""  # set when the open trade's exit rule is met (on any new candle)
    late_exit: bool = False  # the exit rule was met on an earlier candle the run didn't see in time
    entry: tuple[int, float] | None = None  # (side, stop-loss) when a new trade is due
    met: str = ""  # a short note on the latest candle, for the run's status line


def decide(bars: list[Bar], strategy: Strategy, params: dict, direction: str, open_side: int,
           first_new: int | None = None) -> Decision:
    """What the rules say about the newly finished candles, given the side of the run's open trade (0 if none).

    Normally there's one new candle. If the run missed some (the worker was restarting, or prices didn't
    arrive), an exit rule met on any of them still closes the trade now, but entries are only taken from
    the latest candle: a missed entry can't be placed at the price it would have had."""
    df = engine._frame(bars)
    rules = strategy.run(df, params)
    sides = [(1, rules.long)] + ([(-1, rules.short)] if direction == "both" and rules.short is not None else [])
    last = len(df) - 1
    first = last if first_new is None else max(0, min(first_new, last))
    entries = {s: bool(side.entry().iloc[last]) for s, side in sides}
    d = Decision()
    if open_side:
        side = dict(sides).get(open_side)
        exits = side.exit.fillna(False).astype(bool) if side is not None else None
        exit_at = next((i for i in range(first, last + 1) if exits is not None and bool(exits.iloc[i])), None)
        if exit_at is None:
            wanted = []
        else:
            d.exit_label = side.exit_label or "Exit rule"
            d.late_exit = exit_at < last
            # On the same candle as the exit, only the other side can open (a reversal), as in the backtester.
            wanted = [s for s, _ in sides if entries[s] and (s != open_side or d.late_exit)]
    else:
        wanted = [s for s, _ in sides if entries[s]]
    if len(wanted) == 1:
        s = wanted[0]
        d.entry = (s, float(dict(sides)[s].stop.iloc[last]))
    # A one-line summary of the conditions, e.g. "Buy: 2 of 3 conditions met".
    parts = []
    for s, side in sides:
        checks = [bool(v.iloc[last]) if v.iloc[last] == v.iloc[last] else False for v in side.conditions.values()]
        parts.append(f"{'Buy' if s > 0 else 'Short'}: {sum(checks)} of {len(checks)} conditions met")
    d.met = "; ".join(parts)
    return d


# --- Setting runs up ---------------------------------------------------------------------------

def _finished_bars(db: Session, symbol: Symbol, tf: Timeframe) -> tuple[list[Bar], bool]:
    hist = get_history(db, symbol, tf, HISTORY)
    return hist.bars, hist.sample


def create(db: Session, user: User, account_id: int, code: str, timeframe: str, strategy_key: str,
           params: dict | None = None, direction: str = "long") -> AutoRun:
    acct = paper.get_account(db, user, account_id)
    if acct.archived:
        raise AutoError("This paper account is archived.")
    symbol = lookup(db, code)
    strategy = get_strategy(strategy_key)
    if strategy.key in NOT_AUTOMATIC:
        raise AutoError(f"{strategy.name} can't run automatically.")
    if not allowed_timeframes(symbol):
        raise AutoError(f"{symbol.name} can't trade automatically: the free data for UK shares is daily only, "
                        "with no live price to place orders at. Forex, metals, indices, commodities and US shares can.")
    if timeframe not in allowed_timeframes(symbol):
        allowed = ", ".join(allowed_timeframes(symbol)) or "none"
        raise AutoError(f"Automatic trading on {symbol.name} can use these timeframes: {allowed}. "
                        "Shorter ones would use up the free data allowance.")
    tf = get_timeframe(timeframe)
    direction = "both" if direction == "both" and acct.mode == "cfd" and strategy.can_short else "long"
    running = db.scalar(select(func.count()).select_from(AutoRun).where(AutoRun.user_id == user.id,
                                                                        AutoRun.status == "running"))
    if running >= MAX_RUNNING:
        raise AutoError(f"You can have up to {MAX_RUNNING} automatic runs going at once. Stop one first.")
    clash = db.scalar(select(AutoRun).where(AutoRun.account_id == acct.id, AutoRun.symbol == symbol.code,
                                            AutoRun.status != "stopped"))
    if clash is not None:
        raise AutoError(f"This account already has an automatic run on {symbol.name}. "
                        "Use a separate paper account to test another strategy on the same market, so their results don't mix.")

    leftover = db.scalar(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.symbol == symbol.code,
                                                  PaperTrade.status == "open", PaperTrade.source == "auto"))
    if leftover is not None:
        raise AutoError(f"An earlier automatic run left a {symbol.name} trade open on this account. "
                        "Close it first, so the new run's results don't mix with it.")
    bars, sample = _finished_bars(db, symbol, tf)
    if sample:
        raise AutoError("Only sample prices are available for this market (no data key), so there's nothing real to trade on.")
    if len(bars) < 60:
        raise AutoError(f"Not enough finished candles for {symbol.name} on {tf.label} yet.")
    clean = strategy.clean_params(params)

    # What the backtest says, recorded now so the live results can be compared with it later.
    state = paper.account_state(db, acct)
    try:
        bt = backtests.run(db, backtests.Request(
            symbol=symbol.code, timeframe=tf.code, strategy=strategy.key, params=clean,
            start_balance=max(10.0, state["equity"]), risk_pct=acct.risk_pct, mode=acct.mode, direction=direction,
            daily_loss_pct=acct.daily_loss_pct, max_drawdown_pct=acct.max_drawdown_pct))
        m, bh = bt["metrics"], bt["buyHold"]
        summary = {k: m.get(k) for k in ("returnPct", "annualPct", "trades", "winRate", "avgR", "profitFactor",
                                         "maxDrawdownPct", "years")}
        summary["buyHoldReturnPct"] = bh.get("returnPct")
        summary["tradesPerYear"] = round(m["trades"] / m["years"], 1) if m.get("years") else None
    except (ValueError, ProviderError):
        summary = {}

    run = AutoRun(user_id=user.id, account_id=acct.id, symbol=symbol.code, timeframe=tf.code, strategy=strategy.key,
                  params=clean, direction=direction, status="running", last_bar_ts=bars[-1].ts,
                  last_check_at=datetime.now(timezone.utc), errors=0, backtest=summary,
                  last_message="Started. Waiting for the next candle to finish; signals from before now are ignored.")
    db.add(run)
    db.commit()
    return run


def get_run(db: Session, user: User, run_id: int) -> AutoRun:
    run = db.get(AutoRun, run_id)
    if run is None or run.user_id != user.id:
        raise AutoError("Automatic run not found.")
    return run


def open_trade_of(db: Session, run: AutoRun, lock: bool = False) -> PaperTrade | None:
    q = select(PaperTrade).where(PaperTrade.auto_run_id == run.id, PaperTrade.status == "open")
    return db.scalar(q.with_for_update() if lock else q)


def change(db: Session, user: User, run_id: int, action: str, close_open: bool = False) -> AutoRun:
    """Pause, resume or stop a run. Pausing or stopping leaves any open trade with its stop-loss in place,
    unless you ask for it to be closed too."""
    run = get_run(db, user, run_id)
    run = db.get(AutoRun, run.id, with_for_update=True, populate_existing=True)
    if run.status == "stopped":
        raise AutoError("This run has been stopped. Start a new one instead.")
    if action == "resume":
        if run.status == "running":
            return run
        symbol = lookup(db, run.symbol)
        bars, _ = _finished_bars(db, symbol, get_timeframe(run.timeframe))
        run.status, run.errors = "running", 0
        if bars:
            run.last_bar_ts = max(run.last_bar_ts, bars[-1].ts)
        run.last_message = "Resumed. Waiting for the next candle to finish; signals while paused are ignored."
    elif action in ("pause", "stop"):
        run.status = "paused" if action == "pause" else "stopped"
        t = open_trade_of(db, run, lock=True)
        word = "Paused" if action == "pause" else "Stopped"
        if t is not None and close_open:
            acct = db.get(PaperAccount, run.account_id)
            symbol = lookup(db, t.symbol)
            q = paper.latest_quote(db, symbol)
            paper.check_fresh(q, symbol)
            paper.close(db, acct, t, q.mid, q.ts, q.source, f"Closed when the run was {word.lower()}", "closed")
            paper.update_limits(acct, paper.account_state(db, acct)["equity"])
            run.last_message = f"{word} by you, and its open trade was closed."
        elif t is not None:
            run.last_message = (f"{word} by you. Its open trade stays open with its stop-loss; "
                                "the exit rule is no longer applied, so close it yourself when you're ready.")
        else:
            run.last_message = f"{word} by you."
    else:
        raise AutoError("Unknown action.")
    db.commit()
    return run


# --- Running (the background worker calls this) ------------------------------------------------

def _when(ts: int, tf: Timeframe) -> str:
    fmt = "%d %b" if not tf.intraday else "%d %b %H:%M"
    return datetime.fromtimestamp(ts, tz=paper.UK).strftime(fmt)


def step(db: Session, run: AutoRun) -> str:
    """Look at the newest finished candle for one run and act on it. Returns what happened ('' if nothing new)."""
    # Lock the run and re-read it: you may have paused or stopped it a moment ago.
    run = db.get(AutoRun, run.id, with_for_update=True, populate_existing=True)
    if run is None or run.status != "running":
        return ""
    symbol = lookup(db, run.symbol)
    tf = get_timeframe(run.timeframe)
    strategy = get_strategy(run.strategy)
    bars, sample = _finished_bars(db, symbol, tf)
    if sample:
        run.last_message = "Only sample prices available (no data key), so nothing was traded."
        return ""
    if len(bars) < 60 or bars[-1].ts <= run.last_bar_ts:
        return ""
    candle = bars[-1]
    acct = db.get(PaperAccount, run.account_id)
    t = open_trade_of(db, run, lock=True)
    first_new = next(i for i, b in enumerate(bars) if b.ts > run.last_bar_ts)
    missed = len(bars) - 1 - first_new
    d = decide(bars, strategy, run.params or {}, run.direction, t.side if t else 0, first_new)
    label = f"{_when(candle.ts, tf)} candle" + (f" ({missed} earlier candle{'s' if missed > 1 else ''} missed)" if missed else "")

    if not d.exit_label and not (t is None and d.entry):
        run.last_bar_ts = candle.ts
        run.last_message = f"{label}: {'holding the open trade, exit rule not met' if t else 'no setup'}. {d.met}."
        return ""

    # Something to do: it needs a live price, so wait if the market is closed.
    q = paper.latest_quote(db, symbol)
    try:
        paper.check_fresh(q, symbol)
    except paper.PaperError:
        run.last_message = f"{label}: the rules want to act, but the market is closed. Waiting for it to open."
        return ""

    done = []
    if t is not None and d.exit_label:
        late = " (met on a missed candle, so closed late)" if d.late_exit else ""
        paper.close(db, acct, t, q.mid, q.ts, q.source, f"Exit rule: {d.exit_label}"[:80], "exit_rule")
        paper.update_limits(acct, paper.account_state(db, acct)["equity"])
        done.append(f"closed the {'buy' if t.side > 0 else 'short'} (exit rule: {d.exit_label}){late}")
        t = None
    if t is None and d.entry:
        side, stop = d.entry
        word = "buy" if side > 0 else "short"
        try:
            new = paper.place(db, acct, symbol.code, side, stop, None, tf.code, source="auto", strategy=strategy.key,
                              auto_run_id=run.id,
                              reason=f"Automatic: {strategy.name} on the {label}. All entry conditions met.")
            done.append(f"opened a {word} at {new.entry_price:.{symbol.precision}f}, stop-loss {stop:.{symbol.precision}f}")
        except paper.PaperError as exc:
            done.append(f"a {word} was due but the safeguards stopped it: {exc}")
    run.last_bar_ts = candle.ts
    run.last_message = (f"{label}: " + "; then ".join(done) + ".")[:255]
    return run.last_message


def due(run: AutoRun, provider: str, last_looked: dict, now: float) -> bool:
    tf = get_timeframe(run.timeframe)
    if now < run.last_bar_ts + 2 * tf.seconds:
        return False  # the next candle hasn't finished yet
    if now - last_looked.get(run.id, 0) < LOOK_EVERY.get(provider, 60):
        return False
    if provider in ("twelvedata", "oanda"):
        opens = next_open(provider)
        if opens is not None and opens.timestamp() > now + 600:
            return False  # market closed (e.g. the weekend): the finished candle is acted on when it opens
    return True


def run_due(db: Session, last_looked: dict, now: float | None = None) -> set[int]:
    """One pass over every running run. Returns the accounts it touched."""
    now = now or time.time()
    touched: set[int] = set()
    for run in list(db.scalars(select(AutoRun).where(AutoRun.status == "running"))):
        try:
            symbol = lookup(db, run.symbol)
        except ValueError:
            run.status, run.last_message = "paused", "Paused: this market is no longer available."
            db.commit()
            continue
        if not due(run, symbol.provider, last_looked, now):
            continue
        last_looked[run.id] = now
        try:
            happened = step(db, run)
            run.errors = 0
            if happened:
                log.info("Automatic run %s: %s", run.id, happened)
                touched.add(run.account_id)
        except Exception as exc:  # one run's problem never stops the others
            db.rollback()
            if not isinstance(exc, (ProviderError, paper.PaperError, ValueError)):
                log.exception("Automatic run %s failed", run.id)
            run = db.get(AutoRun, run.id)
            run.errors += 1
            run.last_message = f"Couldn't check this run: {exc}"[:255]
            if run.errors >= MAX_ERRORS:
                run.status = "paused"
                run.last_message = f"Paused after {MAX_ERRORS} problems in a row. Last one: {exc}"[:255]
        run.last_check_at = datetime.now(timezone.utc)
        db.commit()
    return touched


# --- How it's going ----------------------------------------------------------------------------

def live_results(db: Session, run: AutoRun) -> dict:
    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.auto_run_id == run.id)))
    closed = [t for t in trades if t.status == "closed" and t.pnl_gbp is not None]
    wins = [t for t in closed if t.pnl_gbp > 0]
    rs = [t.pnl_gbp / t.risk_gbp for t in closed if t.risk_gbp > 0]
    return {
        "trades": len(closed),
        "open": len(trades) - len(closed),
        "net": round(sum(t.pnl_gbp for t in closed), 2),
        "winRate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avgR": round(sum(rs) / len(rs), 2) if rs else None,
        "costs": round(sum(t.costs_gbp or 0 for t in closed), 2),
    }
