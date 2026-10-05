"""Running a backtest from a request: fetch history, apply costs and risk rules, build the report."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..market.directory import lookup
from ..market.fx import converter, quote_currency
from ..market.service import get_history
from ..market.timeframes import get_timeframe
from ..risk.guard import RiskSettings, leverage_cap
from ..strategies.library import get_strategy
from ..market.symbols import Symbol
from ..market.timeframes import Timeframe
from ..strategies.base import Strategy
from . import basket, engine, montecarlo, report, walkforward
from .costs import Costs, default_costs, merge

MAX_POINTS = 2000  # equity curve points sent to the browser
CASH_FIRST = {"stock", "etf", "ukstock"}


@dataclass
class Request:
    symbol: str
    timeframe: str = "1d"
    strategy: str = "ma_cross"
    params: dict = field(default_factory=dict)
    start_balance: float = 200.0
    risk_pct: float = 1.0
    mode: str = ""  # "" = sensible default for the market
    direction: str = "long"
    years: float = 0  # 0 = all available history
    daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 20.0
    costs: dict = field(default_factory=dict)
    keep_going: bool = False  # keep trading past the drawdown limit (tests only)


def default_mode(asset_class: str) -> str:
    return "cash" if asset_class in CASH_FIRST else "cfd"


def _thin(points: list[tuple[int, float]]) -> list[dict]:
    step = max(1, len(points) // MAX_POINTS)
    picked = points[::step]
    if picked and picked[-1] != points[-1]:
        picked.append(points[-1])
    return [{"time": t, "value": round(v, 2)} for t, v in picked]


@dataclass
class Prepared:
    symbol: Symbol
    tf: Timeframe
    strategy: Strategy
    params: dict
    mode: str
    direction: str
    start: float
    history: object
    bars: list
    currency: str
    conv: object
    costs: Costs
    risk: RiskSettings
    own_spread: bool
    settings: engine.Settings


def prepare(db: Session, req: Request) -> Prepared:
    """Check the request, load the history and work out costs and risk settings."""
    symbol = lookup(db, req.symbol)
    tf = get_timeframe(req.timeframe)
    strategy = get_strategy(req.strategy)
    params = strategy.clean_params(req.params)
    mode = req.mode if req.mode in ("cash", "cfd") else default_mode(symbol.asset_class)
    direction = req.direction if req.direction in ("long", "both") else "long"
    start = min(10_000_000.0, max(10.0, float(req.start_balance)))

    history = get_history(db, symbol, tf)
    bars = history.bars
    if req.years and req.years > 0 and bars:
        cutoff = bars[-1].ts - req.years * 365.25 * 86400
        bars = [b for b in bars if b.ts >= cutoff]
    if len(bars) < 60:
        raise ValueError(f"Not enough price history for {symbol.name} on this timeframe ({len(bars)} candles).")

    currency = quote_currency(symbol)
    conv = converter(db, currency)
    costs = merge(default_costs(symbol.asset_class, mode), req.costs)
    risk = RiskSettings(req.risk_pct, req.daily_loss_pct, req.max_drawdown_pct).cleaned()
    # If you set your own spread, it's used everywhere; otherwise OANDA's recorded spreads are used where known.
    own_spread = "spread_pct" in (req.costs or {}) and req.costs.get("spread_pct") is not None
    settings = engine.Settings(
        start_balance=start, mode=mode, direction=direction if mode == "cfd" else "long", risk=risk,
        leverage=leverage_cap(symbol.code, symbol.asset_class, mode), costs=costs, market_spreads=not own_spread,
        keep_going=bool(req.keep_going),
    )
    return Prepared(symbol, tf, strategy, params, mode, direction, start, history, bars, currency, conv, costs,
                    risk, own_spread, settings)


def walkforward_setup(db: Session, req: Request) -> tuple[walkforward.Setup, list, bool]:
    """The walk-forward check for one market runs on the basket engine with a single market, which gives
    exactly the same trades as the normal backtester (the tests check), with no open-risk limit."""
    p = prepare(db, req)
    if p.strategy.benchmark:
        raise ValueError("Buy and hold has nothing to tune: choose a strategy to check.")
    leg = basket.Leg(code=p.symbol.code, bars=p.bars, conv=p.conv, costs=p.costs, leverage=p.settings.leverage)
    setup = walkforward.Setup([leg], p.strategy, p.params, p.start, p.mode, p.settings.direction, p.risk,
                              max_open_risk_pct=100.0, market_spreads=not p.own_spread)
    warnings = [{"level": "stop", "text": "Sample data, not real prices: this result means nothing."}] if p.history.sample else []
    return setup, warnings, p.history.sample


def run(db: Session, req: Request) -> dict:
    p = prepare(db, req)
    symbol, tf, strategy, params, mode, direction, start = p.symbol, p.tf, p.strategy, p.params, p.mode, p.direction, p.start
    history, bars, currency, conv, costs, risk, own_spread, settings = (
        p.history, p.bars, p.currency, p.conv, p.costs, p.risk, p.own_spread, p.settings)

    # The yardstick is plain buy and hold: no leverage, no overnight financing.
    from dataclasses import replace

    bh_settings = replace(settings, mode="cash", leverage=1.0,
                          costs=merge(default_costs(symbol.asset_class, "cash"), req.costs))
    bh_settings = replace(bh_settings, costs=replace(bh_settings.costs, financing_pct_year=0.0))
    result = engine.run(bars, strategy, params, bh_settings if strategy.benchmark else settings, conv)
    bh_result = engine.buy_and_hold(bars, bh_settings, conv)
    m = report.metrics(result, start)
    bh = report.metrics(bh_result, start)
    warnings = report.warnings(m, None if strategy.benchmark else bh, result, strategy.benchmark)
    if history.sample:
        warnings.insert(0, {"level": "stop", "text": "Sample data, not real prices: this result means nothing. Add your free data key."})
    for w in history.warnings:
        if not history.sample:
            warnings.append({"level": "info", "text": w})
    if conv.note and currency not in ("GBP", "GBX"):
        warnings.append({"level": "info", "text": conv.note})
    if m["trades"] == 0 and not strategy.benchmark and len(bars) < 300:
        warnings.append({"level": "caution", "text": (
            f"Only {len(bars)} candles of history, too few for indicators that look back 200 candles. "
            "Try the weekly timeframe, which has much longer history.")})
    recorded = [b.spread / b.close * 100 for b in bars if b.spread and b.close > 0]
    spread_note = ""
    if recorded and not own_spread:
        avg = sum(recorded) / len(recorded)
        spread_note = (f"Spreads: OANDA's actual bid/ask spread at each candle, averaging {avg:.4f}% of the price "
                       f"(the typical figure would be {costs.spread_pct:g}%). Candles without a recorded spread use the typical one.")
        warnings.append({"level": "info", "text": spread_note})
    elif own_spread:
        warnings.append({"level": "info", "text": f"Spreads: your own figure of {costs.spread_pct:g}% on every trade."})
    if strategy.intraday_only and tf.seconds > 900:
        warnings.insert(0, {"level": "stop", "text": (
            f"{strategy.name} only trades on 1 to 15-minute candles. Try the {strategy.suggested_timeframe or '5m'} timeframe.")})
    elif strategy.intraday_only:
        warnings.append({"level": "info", "text": (
            ("Scalping test: costs use OANDA's recorded spread for each candle, so busy and quiet hours are priced as they were. "
             if recorded and not own_spread else
             "Scalping test: costs use typical spreads. Real spreads widen at the open, around news and late at night. ")
            + "Real fills can also lag on fast moves, so treat a thin profit here as a loss.")})
    if not strategy.benchmark:
        warnings.append({"level": "info", "text": "Buy and hold is shown without leverage or overnight financing: simply owning the market."})
    if direction == "both" and mode == "cash":
        warnings.append({"level": "info", "text": "Short trades need CFD/spread-bet mode, so only long trades were tested."})

    assumptions = {
        "mode": mode,
        "modeLabel": "Real shares / no leverage" if mode == "cash" else "CFD or spread bet (leverage allowed)",
        "direction": settings.direction,
        "leverageCap": settings.leverage,
        "riskPct": risk.risk_pct,
        "dailyLossPct": risk.daily_loss_pct,
        "maxDrawdownPct": risk.max_drawdown_pct,
        "costs": costs.to_dict(),
        "currency": currency,
        "fills": "Orders fill at the next candle's open; stops fill at the stop price, or the open if it gapped past.",
        "spreads": "recorded" if recorded and not own_spread else ("yours" if own_spread else "typical"),
        "avgSpreadPct": round(sum(recorded) / len(recorded), 5) if recorded else None,
    }
    return {
        "symbol": symbol.to_dict(),
        "timeframe": tf.code,
        "strategy": {"key": strategy.key, "name": strategy.name, "label": strategy.label(params), "params": params},
        "startBalance": start,
        "keptGoing": bool(req.keep_going),
        "monteCarlo": None if strategy.benchmark else montecarlo.run(montecarlo.Inputs(
            r=montecarlo.r_multiples(result.trades), start_balance=start, risk_pct=risk.risk_pct,
            drawdown_limit_pct=risk.max_drawdown_pct)),
        "limitHit": result.limit_hit_ts if result.limit_hit_ts > 1 else None,
        "from": bars[0].ts,
        "to": bars[-1].ts,
        "candles": len(bars),
        "source": history.source,
        "sample": history.sample,
        "headline": report.headline(strategy.label(params), m, None if strategy.benchmark else bh),
        "metrics": m,
        "buyHold": bh,
        "warnings": warnings,
        "assumptions": assumptions,
        "equity": _thin(result.equity),
        "buyHoldEquity": _thin(bh_result.equity),
        "trades": [t.to_dict() for t in result.trades],
    }
