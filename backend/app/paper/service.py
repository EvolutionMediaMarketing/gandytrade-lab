"""Paper trading: place, watch and close pretend-money trades on live prices.

The same rules as the backtester apply: fills include half the spread plus slippage,
fees and overnight financing come from the same cost model, and every order is sized
and checked by the same risk guard. Every fill records the market price it was based
on and when that price was quoted (`PaperEvent`), so fills can be audited later.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..backtest.costs import default_costs
from ..backtest.engine import Book
from ..market.directory import lookup
from ..market.fx import Converter, converter, quote_currency
from ..market.providers.base import Bar, ProviderError
from ..market.service import get_bars
from ..market.symbols import Symbol
from ..market.timeframes import get_timeframe
from ..models import PaperAccount, PaperEvent, PaperTrade, User
from ..risk.guard import RiskSettings, leverage_cap, size_trade

UK = ZoneInfo("Europe/London")
# How fresh a price must be to trade on it. Older means the market is closed.
STALE_AFTER = {"oanda": 20 * 60, "twelvedata": 30 * 60}
# Candles used to watch open trades. Twelve Data's free allowance is limited, so stocks use 15-minute candles.
WATCH_TIMEFRAME = {"oanda": "1m", "twelvedata": "15m", "alphavantage": "1d"}
REVENGE_MINUTES = 30
MAX_OPEN_RISK_PCT = 10.0  # the most an account may ever have at risk at once
FLAG_POINTS = 25


class PaperError(ValueError):
    """A reason the order or change can't go ahead, in plain words."""


@dataclass
class Quote:
    mid: float
    ts: int  # when this price was quoted (Unix seconds)
    source: str
    sample: bool
    bars: list[Bar]
    timeframe: str


# --- Prices ------------------------------------------------------------------------------------

def watch_timeframe(symbol: Symbol) -> str:
    return WATCH_TIMEFRAME.get(symbol.provider, "1m")


def latest_quote(db: Session, symbol: Symbol) -> Quote:
    tf = get_timeframe(watch_timeframe(symbol))
    result = get_bars(db, symbol, tf, 200)
    if not result.bars:
        raise PaperError(result.warnings[0] if result.warnings else "No price available.")
    last = result.bars[-1]
    quoted = min(int(time.time()), last.ts + tf.seconds)
    return Quote(last.close, quoted, result.source, result.sample, result.bars, tf.code)


def check_fresh(q: Quote, symbol: Symbol) -> None:
    limit = STALE_AFTER.get(symbol.provider)
    if q.sample or limit is None:
        return
    age = time.time() - q.ts
    if age > limit:
        from ..market.hours import closed_message

        raise PaperError(closed_message(symbol.provider, symbol.asset_class, datetime.fromtimestamp(q.ts, tz=UK)))


def _book(db: Session, symbol: Symbol, mode: str) -> tuple[Book, Converter]:
    conv = converter(db, quote_currency(symbol))
    return Book(default_costs(symbol.asset_class, mode), conv, mode), conv


# --- Accounts ----------------------------------------------------------------------------------

def ensure_default_accounts(db: Session, user: User) -> None:
    if db.scalar(select(PaperAccount.id).where(PaperAccount.user_id == user.id)):
        return
    for name, mode in (("Shares (no leverage)", "cash"), ("CFD / spread bet", "cfd")):
        db.add(PaperAccount(user_id=user.id, name=name, mode=mode, starting_balance=200.0, cash=200.0,
                            peak_equity=200.0, deposits=0.0, risk_pct=1.0, daily_loss_pct=3.0, max_drawdown_pct=20.0,
                            max_open_risk_pct=MAX_OPEN_RISK_PCT,
                            day="", day_start_equity=200.0, halted=False, halt_reason="", archived=False))
    db.commit()


def create_account(db: Session, user: User, name: str, balance: float, mode: str, risk_pct: float = 1.0) -> PaperAccount:
    if mode not in ("cash", "cfd"):
        raise PaperError("Choose real shares or CFD / spread bet.")
    acct = PaperAccount(user_id=user.id, name=name.strip()[:60] or "Paper account", mode=mode,
                        starting_balance=balance, cash=balance, peak_equity=balance, deposits=0.0,
                        risk_pct=RiskSettings(risk_pct).cleaned().risk_pct, daily_loss_pct=3.0, max_drawdown_pct=20.0,
                        max_open_risk_pct=MAX_OPEN_RISK_PCT,
                        day="", day_start_equity=balance, halted=False, halt_reason="", archived=False)
    db.add(acct)
    db.commit()
    return acct


def get_account(db: Session, user: User, account_id: int) -> PaperAccount:
    acct = db.get(PaperAccount, account_id)
    if acct is None or acct.user_id != user.id:
        raise PaperError("Paper account not found.")
    return acct


def open_trades(db: Session, acct: PaperAccount) -> list[PaperTrade]:
    return list(db.scalars(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "open")
                           .order_by(PaperTrade.entry_time)))


@dataclass
class Valued:
    trade: PaperTrade
    symbol: Symbol
    price: float | None
    quote_ts: int | None
    unrealised: float
    value_gbp: float
    cap: float
    sample: bool


def value_trade(db: Session, acct: PaperAccount, t: PaperTrade, quotes: dict | None = None) -> Valued:
    symbol = lookup(db, t.symbol)
    quotes = quotes if quotes is not None else {}
    q = quotes.get(t.symbol)
    if q is None:
        try:
            q = latest_quote(db, symbol)
        except (PaperError, ProviderError):
            q = None
        quotes[t.symbol] = q
    book, conv = _book(db, symbol, acct.mode)
    rate = conv.rate(time.time())
    if q is None:
        return Valued(t, symbol, None, None, 0.0, t.units * t.entry_mid / rate, leverage_cap(symbol.code, symbol.asset_class, acct.mode), False)
    unreal = (q.mid - t.entry_price) * t.side * t.units / rate - _financing(book, t, int(time.time()))
    return Valued(t, symbol, q.mid, q.ts, unreal, t.units * q.mid / rate,
                  leverage_cap(symbol.code, symbol.asset_class, acct.mode), q.sample)


def _financing(book: Book, t: PaperTrade, now_ts: int) -> float:
    if book.mode != "cfd" or not book.c.financing_pct_year:
        return 0.0
    start = t.entry_time if t.entry_time.tzinfo else t.entry_time.replace(tzinfo=timezone.utc)
    nights = max(0, (datetime.fromtimestamp(now_ts, tz=timezone.utc).date() - start.astimezone(timezone.utc).date()).days)
    return t.units * t.entry_mid / t.entry_rate * book.c.financing_pct_year / 100 / 365 * nights


def account_state(db: Session, acct: PaperAccount, quotes: dict | None = None) -> dict:
    quotes = {} if quotes is None else quotes
    valued = [value_trade(db, acct, t, quotes) for t in open_trades(db, acct)]
    equity = acct.cash + sum(v.unrealised for v in valued)
    if acct.mode == "cash":
        used = sum(v.value_gbp for v in valued)
        buying_power = max(0.0, equity - used)
    else:
        used = sum(v.value_gbp / v.cap for v in valued)  # margin held
        buying_power = max(0.0, equity - used)
    return {"equity": equity, "used": used, "buying_power": buying_power, "valued": valued}


def trade_risk(t: PaperTrade) -> float:
    """What this open trade would lose (in £, before costs) if its stop-loss were hit now.
    Zero once the stop has been moved to break-even or into profit."""
    return max(0.0, (t.entry_price - t.stop) * t.side * t.units / (t.entry_rate or 1.0))


def open_risk(db: Session, acct: PaperAccount, exclude: int | None = None) -> float:
    return sum(trade_risk(t) for t in open_trades(db, acct) if t.id != exclude)


def open_risk_limit(acct: PaperAccount, equity: float) -> float:
    pct = min(MAX_OPEN_RISK_PCT, max(1.0, acct.max_open_risk_pct or MAX_OPEN_RISK_PCT))
    return max(0.0, equity) * pct / 100


def update_limits(acct: PaperAccount, equity: float) -> None:
    """Start a new trading day, track the high point and apply the drawdown limit."""
    today = datetime.now(UK).strftime("%Y-%m-%d")
    if acct.day != today:
        acct.day, acct.day_start_equity = today, equity
    funded = acct.starting_balance + acct.deposits
    acct.peak_equity = max(acct.peak_equity, equity, 0.0)
    if not acct.halted and acct.peak_equity > 0 and (acct.peak_equity - equity) / acct.peak_equity * 100 >= acct.max_drawdown_pct:
        acct.halted = True
        acct.halt_reason = (f"Paused: the account fell {acct.max_drawdown_pct:g}% from its high "
                            f"(£{acct.peak_equity:,.2f} to £{equity:,.2f}). Review what happened before resuming.")
    if funded <= 0:
        acct.halted = True


def entry_block(acct: PaperAccount, equity: float) -> str:
    if acct.archived:
        return "This paper account is archived."
    if acct.halted:
        return acct.halt_reason or "This paper account is paused."
    if acct.day_start_equity > 0 and (acct.day_start_equity - equity) / acct.day_start_equity * 100 >= acct.daily_loss_pct:
        return f"Daily loss limit reached ({acct.daily_loss_pct:g}% today). No new trades until tomorrow."
    return ""


# --- Orders ------------------------------------------------------------------------------------

@dataclass
class OrderRequest:
    account_id: int
    symbol: str
    side: int
    stop: float
    target: float | None
    timeframe: str
    trend: str
    reason: str
    mood: str = ""
    confirmed: bool = False


def checklist_problems(req: OrderRequest) -> list[str]:
    problems = []
    if req.trend not in ("up", "down", "sideways"):
        problems.append("Say which way the market is trending.")
    if not req.stop or req.stop <= 0:
        problems.append("Set a stop-loss.")
    if len(req.reason.strip()) < 10:
        problems.append("Write one sentence on why you're taking this trade.")
    if not req.confirmed:
        problems.append("Confirm you've checked the size and the amount at risk.")
    return problems


def open_trade(db: Session, user: User, req: OrderRequest) -> PaperTrade:
    """A trade you place yourself: the pre-trade checklist must be complete."""
    problems = checklist_problems(req)
    if problems:
        raise PaperError("Pre-trade checklist incomplete: " + " ".join(problems))
    acct = get_account(db, user, req.account_id)
    return place(db, acct, req.symbol, req.side, req.stop, req.target, req.timeframe,
                 trend=req.trend, reason=req.reason, mood=req.mood)


def place(db: Session, acct: PaperAccount, code: str, side: int, stop: float, target: float | None, timeframe: str, *,
          trend: str = "", reason: str = "", mood: str = "", source: str = "manual", strategy: str = "",
          auto_run_id: int | None = None) -> PaperTrade:
    """Open a paper trade. Manual and automatic trades go through exactly the same safeguards:
    the account's pause and daily loss limit, fresh prices, risk sizing, buying power and the open-risk limit."""
    if side not in (1, -1):
        raise PaperError("Choose buy or short.")
    symbol = lookup(db, code)
    if acct.mode == "cash" and side < 0:
        raise PaperError("This account holds real shares, so it can only buy. Use a CFD / spread bet account to go short.")

    state = account_state(db, acct)
    update_limits(acct, state["equity"])
    block = entry_block(acct, state["equity"])
    if block:
        db.commit()
        raise PaperError(block)

    q = latest_quote(db, symbol)
    check_fresh(q, symbol)
    book, conv = _book(db, symbol, acct.mode)
    buying = side > 0
    fill = book.fill(q.mid, buying)
    if (fill - stop) * side <= 0:
        raise PaperError("The stop-loss is on the wrong side of the current price. "
                         f"The price is now about {q.mid:.{symbol.precision}f}.")
    if target is not None and (target - fill) * side <= 0:
        raise PaperError("The target is on the wrong side of the current price.")

    rate = conv.rate(time.time())
    risk = RiskSettings(acct.risk_pct, acct.daily_loss_pct, acct.max_drawdown_pct).cleaned()
    cap = leverage_cap(symbol.code, symbol.asset_class, acct.mode)
    d = size_trade(equity_gbp=state["equity"], entry=fill, stop=stop, side=side, per_gbp=rate,
                   cap=1e9, settings=risk)
    if not d.ok:
        raise PaperError(d.reason)
    # Buying power: real shares can't spend more than is free; CFDs need free margin.
    fee_rate = (book.c.fx_fee_pct + (book.c.stamp_duty_pct if acct.mode == "cash" else 0)) / 100
    max_value = state["buying_power"] / (1 + fee_rate) if acct.mode == "cash" else state["buying_power"] * cap
    max_units = max_value / (fill / rate)
    units, note = d.units, ""
    if units > max_units:
        units = max_units
        note = "Smaller than planned: not enough buying power for the full size."
    if units <= 0 or units * fill / rate < 0.01:
        raise PaperError("Not enough buying power left in this account for this trade.")

    # Open-risk limit: everything at risk across open trades stays within (by default) 10% of the account.
    already = open_risk(db, acct)
    limit = open_risk_limit(acct, state["equity"])
    room = limit - already
    loss_per_unit = abs(fill - stop) / rate
    if room < max(0.01, 0.1 * d.units * loss_per_unit):
        raise PaperError(
            f"Open-risk limit reached: £{already:,.2f} is already at risk across your open trades, and this account "
            f"allows £{limit:,.2f} ({acct.max_open_risk_pct:g}% of £{state['equity']:,.2f}). "
            "Close a trade, or move a stop-loss closer, before opening another.")
    if units * loss_per_unit > room:
        units = room / loss_per_unit
        note = (f"Smaller than planned: the open-risk limit ({acct.max_open_risk_pct:g}% of the account) "
                f"left room for £{room:,.2f} of risk.")

    flags = []
    if source == "manual":
        if (side > 0 and trend == "down") or (side < 0 and trend == "up"):
            flags.append("Traded against the trend you identified")
        last_loss = db.scalar(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "closed",
                                                       PaperTrade.pnl_gbp < 0).order_by(PaperTrade.exit_time.desc()).limit(1))
        if last_loss is not None and last_loss.exit_time is not None:
            closed = last_loss.exit_time if last_loss.exit_time.tzinfo else last_loss.exit_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - closed < timedelta(minutes=REVENGE_MINUTES):
                flags.append(f"Opened within {REVENGE_MINUTES} minutes of a losing trade")

    fees = book.order_fees(units, fill, int(time.time()), buying, opening=True)
    acct.cash -= fees
    risk_gbp = units * abs(fill - stop) / rate
    t = PaperTrade(
        account_id=acct.id, symbol=symbol.code, timeframe=timeframe[:8], side=side, status="open",
        units=units, entry_price=fill, entry_mid=q.mid, entry_quote_ts=q.ts, entry_rate=rate, entry_fees=fees,
        stop=stop, initial_stop=stop, target=target, risk_gbp=risk_gbp, exit_reason="",
        last_checked_ts=_bar_index_ts(q), source=source, strategy=strategy[:40], trend=trend, reason=reason.strip()[:300],
        mood=mood[:20], notes="", lesson="", rule_flags=flags, rule_score=None, auto_run_id=auto_run_id,
    )
    db.add(t)
    db.flush()
    db.add(PaperEvent(trade_id=t.id, kind="opened", price=fill, mid=q.mid, quote_ts=q.ts, quote_source=q.source,
                      detail=(note or ("sample prices" if q.sample else ""))[:255]))
    db.commit()
    return t


def _bar_index_ts(q: Quote) -> int:
    """Stops are checked from the candle after the one the trade was opened in."""
    return q.bars[-1].ts if q.bars else 0


# --- Changes and closing -----------------------------------------------------------------------

def get_trade(db: Session, user: User, trade_id: int) -> tuple[PaperTrade, PaperAccount]:
    t = db.get(PaperTrade, trade_id)
    if t is None:
        raise PaperError("Trade not found.")
    acct = get_account(db, user, t.account_id)
    return t, acct


def modify(db: Session, user: User, trade_id: int, stop: float | None = None, target: float | None = None,
           clear_target: bool = False, notes: str | None = None, lesson: str | None = None, mood: str | None = None) -> PaperTrade:
    t, acct = get_trade(db, user, trade_id)
    if t.status == "open" and (stop is not None or target is not None or clear_target):
        symbol = lookup(db, t.symbol)
        q = latest_quote(db, symbol)
        if stop is not None:
            if (q.mid - stop) * t.side <= 0:
                raise PaperError("That stop-loss is past the current price; it would close the trade straight away. Close it instead.")
            widened = (t.stop - stop) * t.side > 0
            if widened:
                state = account_state(db, acct)
                new_risk = max(0.0, (t.entry_price - stop) * t.side * t.units / (t.entry_rate or 1.0))
                limit = open_risk_limit(acct, state["equity"])
                if open_risk(db, acct, exclude=t.id) + new_risk > limit + 1e-9:
                    raise PaperError(
                        f"That would put more than {acct.max_open_risk_pct:g}% of the account (£{limit:,.2f}) at risk "
                        "across your open trades, so the stop-loss can't move that far.")
            db.add(PaperEvent(trade_id=t.id, kind="stop_moved", mid=q.mid, quote_ts=q.ts, quote_source=q.source,
                              detail=f"{t.stop:g} → {stop:g}" + (" (further away)" if widened else "")))
            if widened and "Moved the stop-loss further away" not in (t.rule_flags or []):
                t.rule_flags = [*(t.rule_flags or []), "Moved the stop-loss further away"]
            t.stop = stop
        if clear_target:
            t.target = None
        elif target is not None:
            if (target - q.mid) * t.side <= 0:
                raise PaperError("The target is on the wrong side of the current price.")
            db.add(PaperEvent(trade_id=t.id, kind="target_moved", mid=q.mid, quote_ts=q.ts, quote_source=q.source,
                              detail=f"{t.target} → {target:g}"))
            t.target = target
    if notes is not None:
        t.notes = notes[:2000]
    if lesson is not None:
        t.lesson = lesson[:500]
    if mood is not None:
        t.mood = mood[:20]
    db.commit()
    return t


def score(flags: list[str]) -> int:
    return max(0, 100 - FLAG_POINTS * len(flags))


def close(db: Session, acct: PaperAccount, t: PaperTrade, level: float, quote_ts: int, source: str, reason: str,
          kind: str) -> None:
    """Close at a market level (mid). The fill includes half the spread and slippage."""
    symbol = lookup(db, t.symbol)
    book, conv = _book(db, symbol, acct.mode)
    buying = t.side < 0
    fill = book.fill(level, buying)
    now = int(time.time())
    rate = conv.rate(now)
    fees = book.order_fees(t.units, fill, now, buying, opening=False) + _financing(book, t, now)
    move = (fill - t.entry_price) * t.side * t.units / rate
    gross = (level - t.entry_mid) * t.side * t.units / rate
    t.status, t.exit_price, t.exit_mid, t.exit_quote_ts = "closed", fill, level, quote_ts
    t.exit_time = datetime.now(timezone.utc)
    t.exit_reason = reason[:80]
    t.pnl_gbp = move - fees - t.entry_fees
    t.costs_gbp = gross - t.pnl_gbp
    t.rule_score = score(t.rule_flags or [])
    acct.cash += move - fees
    db.add(PaperEvent(trade_id=t.id, kind=kind, price=fill, mid=level, quote_ts=quote_ts, quote_source=source,
                      detail=reason[:255]))


def close_now(db: Session, user: User, trade_id: int) -> PaperTrade:
    t, acct = get_trade(db, user, trade_id)
    # Lock and re-read: the background worker may be closing it at this very moment.
    t = db.get(PaperTrade, t.id, with_for_update=True, populate_existing=True)
    if t.status != "open":
        raise PaperError("This trade is already closed.")
    symbol = lookup(db, t.symbol)
    q = latest_quote(db, symbol)
    check_fresh(q, symbol)
    close(db, acct, t, q.mid, q.ts, q.source, "Closed by you", "closed")
    state = account_state(db, acct)
    update_limits(acct, state["equity"])
    db.commit()
    return t


# --- Watching open trades (the background worker calls this) -----------------------------------

def check_trade(db: Session, acct: PaperAccount, t: PaperTrade, q: Quote) -> bool:
    """Close the trade if a candle since the last check reached its stop or target. Returns True if closed.

    Candles are checked in order. If one candle reached both, the stop is assumed to have come first.
    If the price opened beyond a level (a gap), the trade closes at the open, as it would in real life.
    """
    tf_seconds = get_timeframe(q.timeframe).seconds
    now = time.time()
    for b in q.bars:
        if b.ts <= t.last_checked_ts:
            continue
        hit = None
        if (b.low <= t.stop) if t.side > 0 else (b.high >= t.stop):
            gapped = (b.open - t.stop) * t.side <= 0
            hit = (b.open if gapped else t.stop, "Stop-loss (gapped through)" if gapped else "Stop-loss", "stop")
        elif t.target is not None and ((b.high >= t.target) if t.side > 0 else (b.low <= t.target)):
            gapped = (b.open - t.target) * t.side >= 0
            hit = (b.open if gapped else t.target, "Target reached", "target")
        if hit:
            close(db, acct, t, hit[0], b.ts, q.source, hit[1], hit[2])
            return True
        if b.ts + tf_seconds <= now:
            t.last_checked_ts = b.ts  # finished candles are never checked twice; the forming one is
    # The latest price itself (covers the rest of the candle the trade was opened in).
    if (q.mid - t.stop) * t.side <= 0:
        close(db, acct, t, q.mid, q.ts, q.source, "Stop-loss", "stop")
        return True
    if t.target is not None and (q.mid - t.target) * t.side >= 0:
        close(db, acct, t, q.mid, q.ts, q.source, "Target reached", "target")
        return True
    return False
