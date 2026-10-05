"""Running a basket backtest from a request: load each market, run the basket, and compare it with
each market traded alone and with simply holding the whole basket."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..market.directory import lookup
from ..market.fx import converter, quote_currency
from ..market.providers.base import ProviderError
from ..market.service import get_history, history_cap
from ..market.timeframes import Timeframe, get_timeframe
from ..risk.guard import RiskSettings, leverage_cap
from ..strategies.base import Strategy
from ..strategies.library import get_strategy
from . import basket, engine, montecarlo, report, walkforward
from .costs import default_costs
from .service import _thin

MAX_MARKETS = 12
MAX_OPEN_RISK = 10.0


@dataclass
class Request:
    markets: list[str]
    timeframe: str = "1d"
    strategy: str = "breakout"
    params: dict = field(default_factory=dict)
    start_balance: float = 200.0
    risk_pct: float = 1.0
    mode: str = "cfd"
    direction: str = "long"
    max_open_risk_pct: float = 10.0
    years: float = 0
    daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 20.0
    keep_going: bool = False  # keep trading past the drawdown limit (tests only)


@dataclass
class Prepared:
    legs: list
    names: dict
    warnings: list
    sample: bool
    strategy: Strategy
    params: dict
    tf: Timeframe
    mode: str
    direction: str
    start: float
    risk: RiskSettings
    open_limit: float


def prepare(db: Session, req: Request) -> Prepared:
    """Check the request and load every market over the period they all cover."""
    codes = list(dict.fromkeys(req.markets))[:MAX_MARKETS]
    if len(codes) < 2:
        raise ValueError("Choose at least two markets for a basket.")
    tf = get_timeframe(req.timeframe)
    strategy = get_strategy(req.strategy)
    if strategy.benchmark:
        raise ValueError("Choose a strategy to test (buy and hold is the yardstick).")
    if strategy.intraday_only and tf.seconds > 900:
        raise ValueError(f"{strategy.name} only trades on 1 to 15-minute candles.")
    params = strategy.clean_params(req.params)
    mode = req.mode if req.mode in ("cash", "cfd") else "cfd"
    direction = req.direction if req.direction in ("long", "both") and mode == "cfd" else "long"
    start = min(10_000_000.0, max(10.0, float(req.start_balance)))
    risk = RiskSettings(req.risk_pct, req.daily_loss_pct, req.max_drawdown_pct).cleaned()
    open_limit = min(MAX_OPEN_RISK, max(1.0, float(req.max_open_risk_pct)))

    loaded, warnings, sample = [], [], False
    for code in codes:
        try:
            symbol = lookup(db, code)
            hist = get_history(db, symbol, tf)
        except (ValueError, ProviderError) as exc:
            warnings.append({"level": "caution", "text": f"{code} left out: {exc}"})
            continue
        if len(hist.bars) < 60:
            warnings.append({"level": "caution", "text": f"{symbol.name} left out: only {len(hist.bars)} candles of history."})
            continue
        sample = sample or hist.sample
        if not hist.sample:
            warnings.extend({"level": "caution", "text": f"{symbol.name}: {w}"} for w in hist.warnings)
        loaded.append((symbol, hist.bars))
    if len(loaded) < 2:
        raise ValueError("Fewer than two of those markets have enough history on this timeframe.")

    # Test over the period every market covers, so they're compared fairly.
    first = max(bars[0].ts for _, bars in loaded)
    last = min(bars[-1].ts for _, bars in loaded)
    latest_start = max(loaded, key=lambda x: x[1][0].ts)
    earliest_start = min(b[0].ts for _, b in loaded)
    if first - earliest_start > 365 * 86400 and not (req.years and req.years > 0):
        when = datetime.fromtimestamp(first, tz=timezone.utc).strftime("%B %Y")
        sym, its_bars = latest_start
        if len(its_bars) >= history_cap(sym, tf):
            text = (f"The test starts in {when}: backtests use at most {len(its_bars):,} candles, which for "
                    f"{sym.name} on this timeframe reaches back to then. Every market is tested over the same period.")
        else:
            text = (f"The test starts in {when} because {sym.name} has prices only from then "
                    f"({len(its_bars):,} candles). Leave it out to test further back.")
        warnings.append({"level": "info", "text": text})
    if req.years and req.years > 0:
        first = max(first, last - req.years * 365.25 * 86400)
    legs = []
    for symbol, bars in loaded:
        cut = [b for b in bars if first <= b.ts <= last]
        if len(cut) < 60:
            warnings.append({"level": "caution", "text": f"{symbol.name} left out: too little shared history."})
            continue
        legs.append(basket.Leg(code=symbol.code, bars=cut, conv=converter(db, quote_currency(symbol)),
                               costs=default_costs(symbol.asset_class, mode),
                               leverage=leverage_cap(symbol.code, symbol.asset_class, mode)))
    if len(legs) < 2:
        raise ValueError("Fewer than two markets share enough history on this timeframe.")
    names = {s.code: s.name for s, _ in loaded}
    return Prepared(legs, names, warnings, sample, strategy, params, tf, mode, direction, start, risk, open_limit)


def walkforward_setup(db: Session, req: Request) -> tuple[walkforward.Setup, list, bool]:
    p = prepare(db, req)
    return (walkforward.Setup(p.legs, p.strategy, p.params, p.start, p.mode, p.direction, p.risk, p.open_limit),
            p.warnings, p.sample)


def run(db: Session, req: Request) -> dict:
    p = prepare(db, req)
    legs, names, warnings, sample, strategy, params = p.legs, p.names, p.warnings, p.sample, p.strategy, p.params
    tf, mode, direction, start, risk, open_limit = p.tf, p.mode, p.direction, p.start, p.risk, p.open_limit

    result = basket.run(legs, strategy, params, start_balance=start, mode=mode, direction=direction, risk=risk,
                        max_open_risk_pct=open_limit, keep_going=bool(req.keep_going))
    m = report.metrics(result, start)

    # Each market alone, with the whole balance (the normal backtest).
    alone, holds = [], []
    for leg in legs:
        settings = engine.Settings(start_balance=start, mode=mode, direction=direction, risk=risk,
                                   leverage=leg.leverage, costs=leg.costs, keep_going=bool(req.keep_going))
        res = engine.run(leg.bars, strategy, params, settings, leg.conv)
        am = report.metrics(res, start)
        bh_settings = engine.Settings(start_balance=start, mode="cash", leverage=1.0,
                                      costs=replace(default_costs(lookup(db, leg.code).asset_class, "cash"), financing_pct_year=0.0))
        holds.append(engine.buy_and_hold(leg.bars, bh_settings, leg.conv))
        in_basket = report.metrics(engine.Result(leg.trades, result.equity), start) if leg.trades else None
        rs = [t.pnl_gbp / t.risk_gbp for t in leg.trades if t.risk_gbp > 0]
        alone.append({
            "market": leg.code, "name": names.get(leg.code, leg.code),
            "basketTrades": len(leg.trades), "basketNet": round(sum(t.pnl_gbp for t in leg.trades), 2),
            "basketWinRate": round(sum(1 for t in leg.trades if t.pnl_gbp > 0) / len(leg.trades) * 100, 1) if leg.trades else None,
            "basketAvgR": round(sum(rs) / len(rs), 2) if rs else None,
            "aloneReturnPct": am["returnPct"], "aloneTrades": am["trades"], "aloneDrawdownPct": am["maxDrawdownPct"],
            "holdReturnPct": report.metrics(holds[-1], start)["returnPct"],
        })
        _ = in_basket
    hold_curve = basket.equal_weight_hold(legs, result.timeline, start, holds)
    hold_result = engine.Result([], hold_curve)
    hm = report.metrics(hold_result, start)
    avg_alone = sum(a["aloneReturnPct"] for a in alone) / len(alone)

    warnings = report.warnings(m, hm, result, False) + warnings
    if sample:
        warnings.insert(0, {"level": "stop", "text": "Sample data, not real prices: this result means nothing. Add your free data key."})
    warnings.append({"level": "info", "text": (
        "Buy and hold here is the whole basket: the money split equally between the markets and simply held, "
        "without leverage or financing.")})
    span = (result.timeline[-1] - result.timeline[0]) / (365.25 * 86400) if result.timeline else 0
    tweaked = [f"{p.label.split(' (')[0].lower()} {params[p.key]:g}" for p in strategy.params if params.get(p.key) != p.default]
    shown_name = strategy.name + (f" ({', '.join(tweaked)})" if tweaked else "")
    headline = (f"Over {span:.1f} years, {shown_name} on {len(legs)} markets together turned "
                f"£{start:,.2f} into £{m['final']:,.2f} ({m['returnPct']:+.1f}%) from {m['trades']} trades, after "
                f"£{m['costs']:,.2f} of costs. Holding the basket gave {hm['returnPct']:+.1f}%; "
                f"the same markets traded one at a time averaged {avg_alone:+.1f}%.")
    trades = []
    for t in result.trades:
        d = t.to_dict()
        d["symbol"] = getattr(t, "symbol", "")
        trades.append(d)
    return {
        "strategy": {"key": strategy.key, "name": strategy.name, "params": params},
        "timeframe": tf.code, "mode": mode, "direction": direction, "startBalance": start,
        "maxOpenRiskPct": open_limit, "riskPct": risk.risk_pct, "keptGoing": bool(req.keep_going),
        "monteCarlo": montecarlo.run(montecarlo.Inputs(
            r=montecarlo.r_multiples(result.trades), start_balance=start, risk_pct=risk.risk_pct,
            drawdown_limit_pct=risk.max_drawdown_pct)),
        "limitHit": result.limit_hit_ts if result.limit_hit_ts > 1 else None,
        "from": result.timeline[0], "to": result.timeline[-1], "years": round(span, 1),
        "markets": alone, "metrics": m, "buyHold": hm, "averageAloneReturnPct": round(avg_alone, 2),
        "headline": headline, "warnings": warnings, "skipped": result.skipped,
        "equity": _thin(result.equity), "buyHoldEquity": _thin(hold_curve), "trades": trades[-300:],
        "sample": sample,
    }
