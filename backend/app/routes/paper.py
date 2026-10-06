"""Paper trading: accounts, orders, open trades, the journal and the fill log."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import current_user
from ..market.providers.base import ProviderError
from ..market.directory import lookup
from ..models import PaperAccount, PaperEvent, PaperTrade, PriceOrder, User
from .. import sessions
from ..paper import auto, orders, topups
from ..paper import performance as perf
from ..paper import service as paper
from ..models import AutoRun
from ..strategies.library import STRATEGIES

router = APIRouter(prefix="/api/paper", tags=["paper"])
MOODS = {"", "calm", "confident", "unsure", "anxious", "bored", "fomo", "frustrated"}


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400 if isinstance(exc, (paper.PaperError, ValueError)) else 502, detail=str(exc))


_precision_cache: dict[str, tuple[int, str]] = {}


def _market(db: Session, code: str) -> tuple[int, str]:
    if code not in _precision_cache:
        try:
            s = lookup(db, code)
            _precision_cache[code] = (s.precision, s.name)
        except ValueError:
            _precision_cache[code] = (5, code)
    return _precision_cache[code]


def _trade_dict(t: PaperTrade, v: "paper.Valued | None" = None, db: Session | None = None) -> dict:
    d = {
        "id": t.id, "symbol": t.symbol, "timeframe": t.timeframe, "side": "long" if t.side > 0 else "short",
        "status": t.status, "units": t.units, "entryPrice": t.entry_price, "entryMid": t.entry_mid,
        "entryQuoteTs": t.entry_quote_ts, "entryTime": t.entry_time.isoformat(), "stop": t.stop,
        "initialStop": t.initial_stop, "target": t.target, "riskGbp": round(t.risk_gbp, 2),
        "exitPrice": t.exit_price, "exitTime": t.exit_time.isoformat() if t.exit_time else None,
        "exitReason": t.exit_reason, "pnl": round(t.pnl_gbp, 2) if t.pnl_gbp is not None else None,
        "costs": round(t.costs_gbp, 2) if t.costs_gbp is not None else None,
        "r": round(t.pnl_gbp / t.risk_gbp, 2) if t.pnl_gbp is not None and t.risk_gbp > 0 else None,
        "source": t.source, "strategy": t.strategy, "autoRunId": t.auto_run_id, "trend": t.trend, "reason": t.reason, "mood": t.mood,
        "notes": t.notes, "lesson": t.lesson, "ruleFlags": t.rule_flags or [],
        "ruleScore": t.rule_score if t.rule_score is not None else paper.score(t.rule_flags or []),
        "trailDistance": t.trail_distance, "accountId": t.account_id,
    }
    if db is not None:
        d["precision"], d["name"] = _market(db, t.symbol)
    if v is not None:
        d.update({"price": v.price, "priceTime": v.quote_ts, "unrealised": round(v.unrealised, 2),
                  "valueGbp": round(v.value_gbp, 2), "name": v.symbol.name, "precision": v.symbol.precision,
                  "sample": v.sample})
    return d


def _account_dict(db: Session, acct: PaperAccount, quotes: dict, detail: bool = False) -> dict:
    state = paper.account_state(db, acct, quotes)
    funded = acct.starting_balance + acct.deposits
    out = {
        "id": acct.id, "name": acct.name, "mode": acct.mode, "startingBalance": acct.starting_balance,
        "deposits": acct.deposits, "cash": round(acct.cash, 2), "equity": round(state["equity"], 2),
        "funded": round(funded, 2), "profit": round(state["equity"] - funded, 2),
        "topupAmount": acct.topup_amount, "topupDay": acct.topup_day, "nextTopup": topups.next_topup(acct),
        "returnPct": round((state["equity"] - funded) / funded * 100, 2) if funded else 0.0,
        "buyingPower": round(state["buying_power"], 2), "used": round(state["used"], 2),
        "riskPct": acct.risk_pct, "dailyLossPct": acct.daily_loss_pct, "maxDrawdownPct": acct.max_drawdown_pct,
        "peakEquity": round(acct.peak_equity, 2),
        "maxOpenRiskPct": acct.max_open_risk_pct,
        "openRisk": round(paper.open_risk(db, acct), 2),
        "openRiskLimit": round(paper.open_risk_limit(acct, state["equity"]), 2), "halted": acct.halted, "haltReason": acct.halt_reason,
        "archived": acct.archived, "openCount": len(state["valued"]),
        "autoRunning": db.scalar(select(func.count()).select_from(AutoRun).where(
            AutoRun.account_id == acct.id, AutoRun.status == "running")) or 0,
        "autoPaused": db.scalar(select(func.count()).select_from(AutoRun).where(
            AutoRun.account_id == acct.id, AutoRun.status == "paused")) or 0,
        "block": paper.entry_block(acct, state["equity"]),
    }
    if detail:
        out["open"] = [_trade_dict(v.trade, v) for v in state["valued"]]
        closed = db.scalars(select(PaperTrade).where(PaperTrade.account_id == acct.id, PaperTrade.status == "closed")
                            .order_by(PaperTrade.exit_time.desc()).limit(300)).all()
        out["closed"] = [_trade_dict(t, db=db) for t in closed]
        out["depositHistory"] = [{"amount": d.amount, "kind": d.kind, "at": d.at.isoformat()} for d in topups.history(db, acct)]
    return out


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    paper.ensure_default_accounts(db, user)
    quotes: dict = {}
    accts = db.scalars(select(PaperAccount).where(PaperAccount.user_id == user.id).order_by(PaperAccount.id)).all()
    return {"accounts": [_account_dict(db, a, quotes) for a in accts]}


class NewAccount(BaseModel):
    name: str = Field(max_length=60)
    starting_balance: float = Field(200, ge=10, le=10_000_000)
    mode: str = Field(max_length=8)
    risk_pct: float = Field(1.0, ge=0.1, le=2.0)


@router.post("/accounts")
def new_account(body: NewAccount, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.create_account(db, user, body.name, body.starting_balance, body.mode, body.risk_pct)
    except paper.PaperError as exc:
        raise _fail(exc) from exc
    return _account_dict(db, acct, {})


class AccountChange(BaseModel):
    name: str | None = Field(None, max_length=60)
    risk_pct: float | None = Field(None, ge=0.1, le=2.0)
    max_open_risk_pct: float | None = Field(None, ge=1.0, le=10.0)  # can be lowered, never raised above 10%
    daily_loss_pct: float | None = Field(None, ge=0.5, le=5.0)
    max_drawdown_pct: float | None = Field(None, ge=5.0, le=25.0)
    archived: bool | None = None
    resume: bool = False  # lift a drawdown pause after reviewing it
    topup_amount: float | None = Field(None, ge=0, le=topups.MAX_DEPOSIT)  # monthly top-up, 0 = off
    topup_day: int | None = Field(None, ge=1, le=topups.MAX_DAY)


@router.patch("/accounts/{account_id}")
def change_account(account_id: int, body: AccountChange, db: Session = Depends(get_session),
                   user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.get_account(db, user, account_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if body.name:
        acct.name = body.name.strip()[:60]
    if body.risk_pct is not None:
        acct.risk_pct = body.risk_pct
    if body.max_open_risk_pct is not None:
        acct.max_open_risk_pct = body.max_open_risk_pct
    if body.daily_loss_pct is not None:
        acct.daily_loss_pct = body.daily_loss_pct
    if body.max_drawdown_pct is not None:
        acct.max_drawdown_pct = body.max_drawdown_pct
    if body.archived is not None:
        acct.archived = body.archived
    if body.topup_amount is not None or body.topup_day is not None:
        try:
            topups.set_monthly(db, acct, acct.topup_amount if body.topup_amount is None else body.topup_amount,
                               acct.topup_day if body.topup_day is None else body.topup_day)
        except paper.PaperError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.resume and acct.halted:
        state = paper.account_state(db, acct)
        acct.halted, acct.halt_reason = False, ""
        acct.peak_equity = state["equity"]  # the limit is measured afresh from here
    db.commit()
    return _account_dict(db, acct, {})


class DeleteAccount(BaseModel):
    confirm_name: str = Field(max_length=60)


@router.post("/accounts/{account_id}/delete")
def delete_account(account_id: int, body: DeleteAccount, request: Request, db: Session = Depends(get_session),
                   user: User = Depends(current_user)) -> dict:
    try:
        name = paper.get_account(db, user, account_id).name
        counts = paper.delete_account(db, user, account_id, body.confirm_name)
    except paper.PaperError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sessions.audit(db, "paper_account_deleted", user.username, sessions.client_ip(request),
                   f"{name}: {counts['trades']} trade(s), {counts['runs']} automatic run(s)")
    db.commit()
    return {"ok": True, **counts}


class Deposit(BaseModel):
    amount: float = Field(gt=0, le=topups.MAX_DEPOSIT)


@router.post("/accounts/{account_id}/deposit")
def add_money(account_id: int, body: Deposit, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        topups.add_now(db, user, account_id, body.amount)
    except paper.PaperError as exc:
        raise _fail(exc) from exc
    return _account_dict(db, paper.get_account(db, user, account_id), {}, detail=True)


@router.get("/accounts/{account_id}/performance")
def account_performance(account_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.get_account(db, user, account_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return perf.performance(db, acct)


@router.get("/accounts/{account_id}/coach-export")
def coach_export(account_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.get_account(db, user, account_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"text": perf.coach_export(db, acct)}


JOURNAL_LIMIT = 2000


@router.get("/journal")
def journal(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    """Every trade on every paper account, newest first, with its journal entry (the Journal page filters them)."""
    accts = {a.id: a for a in db.scalars(select(PaperAccount).where(PaperAccount.user_id == user.id))}
    trades = db.scalars(select(PaperTrade).where(PaperTrade.account_id.in_(list(accts) or [-1]))
                        .order_by(PaperTrade.entry_time.desc(), PaperTrade.id.desc()).limit(JOURNAL_LIMIT)).all()
    out = []
    for t in trades:
        d = _trade_dict(t, db=db)
        d["accountName"] = accts[t.account_id].name
        d["accountArchived"] = accts[t.account_id].archived
        d["strategyName"] = (STRATEGIES[t.strategy].name if t.strategy in STRATEGIES else t.strategy) if t.source == "auto" else ""
        out.append(d)
    return {"trades": out, "limited": len(trades) >= JOURNAL_LIMIT}


@router.get("/accounts/{account_id}")
def account_detail(account_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.get_account(db, user, account_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_dict(db, acct, {}, detail=True)


class OrderBody(BaseModel):
    account_id: int
    symbol: str = Field(max_length=32)
    side: str = Field(max_length=5)  # long | short
    stop: float = Field(gt=0)
    target: float | None = Field(None, gt=0)
    timeframe: str = Field("", max_length=4)
    trend: str = Field("", max_length=10)
    reason: str = Field("", max_length=300)
    mood: str = Field("", max_length=20)
    confirmed: bool = False
    trail_distance: float | None = Field(None, gt=0)  # trailing stop, in price units behind the price


class PriceOrderBody(BaseModel):
    account_id: int
    symbol: str = Field(max_length=32)
    side: str = Field(max_length=5)  # long | short
    level: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float | None = Field(None, gt=0)
    timeframe: str = Field("", max_length=8)
    trend: str = Field("", max_length=10)
    reason: str = Field("", max_length=300)
    mood: str = Field("", max_length=20)
    confirmed: bool = False
    expiry: str = Field("gtc", max_length=8)
    trail_distance: float | None = Field(None, gt=0)
    at_open: bool = False


def _precision(db: Session, code: str) -> int:
    return _market(db, code)[0]


@router.get("/price-orders")
def list_price_orders(account_id: int | None = None, symbol: str | None = None, done: bool = False,
                      db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    """Waiting price orders (and, with done=true, the 30 most recent finished ones) on your accounts."""
    ids = [a.id for a in db.scalars(select(PaperAccount).where(PaperAccount.user_id == user.id))]
    if account_id is not None:
        ids = [i for i in ids if i == account_id]
    q = select(PriceOrder).where(PriceOrder.account_id.in_(ids))
    if symbol:
        q = q.where(PriceOrder.symbol == symbol[:32])
    waiting = db.scalars(q.where(PriceOrder.status == "waiting").order_by(PriceOrder.level.desc())).all()
    finished = db.scalars(q.where(PriceOrder.status != "waiting").order_by(PriceOrder.id.desc()).limit(30)).all() if done else []
    return {"waiting": [orders.order_dict(o, _precision(db, o.symbol)) for o in waiting],
            "finished": [orders.order_dict(o, _precision(db, o.symbol)) for o in finished]}


@router.post("/price-orders")
def new_price_order(body: PriceOrderBody, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        if body.side not in ("long", "short"):
            raise paper.PaperError("Choose buy or sell.")
        o = orders.create(db, user, orders.OrderRequest(**{**body.model_dump(), "side": 1 if body.side == "long" else -1,
                                                            "mood": body.mood if body.mood in MOODS else ""}))
    except (paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    return orders.order_dict(o, _precision(db, o.symbol))


class PriceOrderChange(BaseModel):
    level: float | None = Field(None, gt=0)
    stop: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    clear_target: bool = False
    expiry: str | None = Field(None, max_length=8)
    trail_distance: float | None = Field(None, gt=0)
    clear_trail: bool = False


@router.patch("/price-orders/{order_id}")
def change_price_order(order_id: int, body: PriceOrderChange, db: Session = Depends(get_session),
                       user: User = Depends(current_user)) -> dict:
    try:
        o = orders.modify(db, user, order_id, **body.model_dump())
    except (paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    return orders.order_dict(o, _precision(db, o.symbol))


@router.post("/price-orders/{order_id}/cancel")
def cancel_price_order(order_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        o = orders.cancel(db, user, order_id)
    except paper.PaperError as exc:
        raise _fail(exc) from exc
    return orders.order_dict(o, _precision(db, o.symbol))


@router.post("/orders")
def open_paper_trade(body: OrderBody, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    if body.mood not in MOODS:
        raise HTTPException(status_code=422, detail="Unknown mood.")
    req = paper.OrderRequest(account_id=body.account_id, symbol=body.symbol, side=1 if body.side == "long" else -1,
                             stop=body.stop, target=body.target, timeframe=body.timeframe, trend=body.trend,
                             reason=body.reason, mood=body.mood, confirmed=body.confirmed,
                             trail_distance=body.trail_distance)
    try:
        t = paper.open_trade(db, user, req)
    except (paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    acct = db.get(PaperAccount, t.account_id)
    return {"trade": _trade_dict(t, paper.value_trade(db, acct, t)), "note": _last_note(db, t.id)}


def _last_note(db: Session, trade_id: int) -> str:
    ev = db.scalar(select(PaperEvent).where(PaperEvent.trade_id == trade_id).order_by(PaperEvent.id.desc()).limit(1))
    return ev.detail if ev else ""


class TradeChange(BaseModel):
    stop: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    clear_target: bool = False
    notes: str | None = Field(None, max_length=2000)
    lesson: str | None = Field(None, max_length=500)
    mood: str | None = Field(None, max_length=20)
    cancel_trail: bool = False  # you've seen the warning: setting the stop yourself cancels the trailing stop


@router.patch("/trades/{trade_id}")
def change_trade(trade_id: int, body: TradeChange, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    if body.mood is not None and body.mood not in MOODS:
        raise HTTPException(status_code=422, detail="Unknown mood.")
    try:
        t = paper.modify(db, user, trade_id, body.stop, body.target, body.clear_target, body.notes, body.lesson, body.mood,
                         cancel_trail=body.cancel_trail)
    except paper.TrailActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (paper.PaperError, ProviderError) as exc:
        raise _fail(exc) from exc
    return {"trade": _trade_dict(t, db=db)}


class Trailing(BaseModel):
    distance: float | None = Field(None, gt=0)  # None switches it off


@router.post("/trades/{trade_id}/trailing")
def trailing(trade_id: int, body: Trailing, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        t = paper.set_trailing(db, user, trade_id, body.distance)
    except (paper.PaperError, ProviderError) as exc:
        raise _fail(exc) from exc
    return {"trade": _trade_dict(t, db=db)}


@router.post("/trades/{trade_id}/close")
def close_trade(trade_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        t = paper.close_now(db, user, trade_id)
    except (paper.PaperError, ProviderError) as exc:
        raise _fail(exc) from exc
    return {"trade": _trade_dict(t, db=db)}


@router.get("/trades/{trade_id}/events")
def trade_events(trade_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        t, _ = paper.get_trade(db, user, trade_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    events = db.scalars(select(PaperEvent).where(PaperEvent.trade_id == t.id).order_by(PaperEvent.id)).all()
    return {"events": [{"at": e.at.isoformat(), "kind": e.kind, "price": e.price, "mid": e.mid, "quoteTs": e.quote_ts,
                        "source": e.quote_source, "detail": e.detail} for e in events]}


# --- Automatic paper trading -------------------------------------------------------------------

def _run_dict(db: Session, run: AutoRun) -> dict:
    s = STRATEGIES.get(run.strategy)
    _, name = _market(db, run.symbol)
    t = auto.open_trade_of(db, run)
    return {
        "id": run.id, "accountId": run.account_id, "symbol": run.symbol, "name": name, "timeframe": run.timeframe,
        "strategy": run.strategy, "strategyName": s.label(run.params) if s else run.strategy, "params": run.params or {},
        "direction": run.direction, "status": run.status, "createdAt": run.created_at.isoformat(),
        "lastCheckAt": run.last_check_at.isoformat() if run.last_check_at else None,
        "lastCandle": run.last_bar_ts, "message": run.last_message, "backtest": run.backtest or {},
        "live": auto.live_results(db, run), "openTradeId": t.id if t else None, "eventPause": run.event_pause,
    }


@router.get("/auto/options")
def auto_options(user: User = Depends(current_user)) -> dict:
    return {
        "strategies": [{"key": s.key, "name": s.name, "summary": s.summary, "canShort": s.can_short,
                        "intradayOnly": s.intraday_only, "suggestedTimeframe": s.suggested_timeframe}
                       for s in auto.automatic_strategies()],
        "timeframes": auto.TIMEFRAMES, "maxRunning": auto.MAX_RUNNING,
    }


@router.get("/auto")
def list_runs(account_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        acct = paper.get_account(db, user, account_id)
    except paper.PaperError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runs = db.scalars(select(AutoRun).where(AutoRun.account_id == acct.id).order_by(AutoRun.id.desc())).all()
    return {"runs": [_run_dict(db, r) for r in runs]}


class NewRun(BaseModel):
    account_id: int
    symbol: str = Field(max_length=32)
    timeframe: str = Field(max_length=4)
    strategy: str = Field(max_length=40)
    direction: str = Field("long", max_length=5)
    params: dict = Field(default_factory=dict)


@router.post("/auto")
def start_run(body: NewRun, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        run = auto.create(db, user, body.account_id, body.symbol, body.timeframe, body.strategy,
                          body.params, body.direction)
    except (auto.AutoError, paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    return _run_dict(db, run)


class NewBasketRuns(BaseModel):
    account_id: int | None = None  # None: make a new CFD account for the basket
    new_account_name: str = Field("", max_length=60)
    new_account_risk_pct: float = Field(1.0, ge=0.1, le=2.0)
    markets: list[str] = Field(min_length=2, max_length=auto.MAX_BASKET)
    timeframe: str = Field(max_length=4)
    strategy: str = Field(max_length=40)
    direction: str = Field("long", max_length=5)
    params: dict[str, float] = Field(default_factory=dict)
    stop_run_ids: list[int] = Field(default_factory=list, max_length=50)


@router.post("/auto/basket")
def start_basket(body: NewBasketRuns, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    if any(len(m) > 32 for m in body.markets):
        raise HTTPException(status_code=400, detail="Unknown market.")
    try:
        runs = auto.create_basket(db, user, body.account_id, body.markets, body.timeframe, body.strategy,
                                  body.params, body.direction, body.stop_run_ids,
                                  body.new_account_name, body.new_account_risk_pct)
    except (auto.AutoError, paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    return {"runs": [_run_dict(db, r) for r in runs]}


class RunChange(BaseModel):
    action: str = Field(max_length=12)  # pause | resume | stop | event_pause
    close_open: bool = False
    on: bool = False  # for event_pause


@router.post("/auto/{run_id}")
def change_run(run_id: int, body: RunChange, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        if body.action == "event_pause":
            run = auto.set_event_pause(db, user, run_id, body.on)
        else:
            run = auto.change(db, user, run_id, body.action, body.close_open)
    except (auto.AutoError, paper.PaperError, ValueError, ProviderError) as exc:
        raise _fail(exc) from exc
    return _run_dict(db, run)
