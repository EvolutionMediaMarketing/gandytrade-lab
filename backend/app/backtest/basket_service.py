"""Running a basket backtest from a request: load each market, run the basket, and compare it with
each market traded alone and with simply holding the whole basket."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..market.directory import lookup
from ..market.fx import converter, quote_currency
from ..market.providers.base import ProviderError
from ..market.service import get_history
from ..market.timeframes import get_timeframe
from ..risk.guard import RiskSettings, leverage_cap
from ..strategies.library import get_strategy
from . import basket, engine, report
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


def run(db: Session, req: Request) -> dict:
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
        warnings.append({"level": "info", "text": (
            f"The test starts in {when} because {latest_start[0].name} has prices only from then "
            f"({len(latest_start[1])} candles). Leave it out to test further back.")})
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

    result = basket.run(legs, strategy, params, start_balance=start, mode=mode, direction=direction, risk=risk,
                        max_open_risk_pct=open_limit)
    m = report.metrics(result, start)

    # Each market alone, with the whole balance (the normal backtest).
    alone, holds = [], []
    for leg in legs:
        settings = engine.Settings(start_balance=start, mode=mode, direction=direction, risk=risk,
                                   leverage=leg.leverage, costs=leg.costs)
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
    headline = (f"Over {span:.1f} years, {strategy.name} on {len(legs)} markets together turned "
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
        "maxOpenRiskPct": open_limit, "riskPct": risk.risk_pct,
        "from": result.timeline[0], "to": result.timeline[-1], "years": round(span, 1),
        "markets": alone, "metrics": m, "buyHold": hm, "averageAloneReturnPct": round(avg_alone, 2),
        "headline": headline, "warnings": warnings, "skipped": result.skipped,
        "equity": _thin(result.equity), "buyHoldEquity": _thin(hold_curve), "trades": trades[-300:],
        "sample": sample,
    }
