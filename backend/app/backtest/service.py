"""Running a backtest from a request: fetch history, apply costs and risk rules, build the report."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..market.directory import lookup
from ..market.fx import converter, quote_currency
from ..market.service import get_history
from ..market.timeframes import get_timeframe
from ..risk.guard import RiskSettings, leverage_cap
from ..strategies.library import get_strategy
from . import engine, report
from .costs import default_costs, merge

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


def default_mode(asset_class: str) -> str:
    return "cash" if asset_class in CASH_FIRST else "cfd"


def _thin(points: list[tuple[int, float]]) -> list[dict]:
    step = max(1, len(points) // MAX_POINTS)
    picked = points[::step]
    if picked and picked[-1] != points[-1]:
        picked.append(points[-1])
    return [{"time": t, "value": round(v, 2)} for t, v in picked]


def run(db: Session, req: Request) -> dict:
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
    settings = engine.Settings(
        start_balance=start, mode=mode, direction=direction if mode == "cfd" else "long", risk=risk,
        leverage=leverage_cap(symbol.code, symbol.asset_class, mode), costs=costs,
    )

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
    }
    return {
        "symbol": symbol.to_dict(),
        "timeframe": tf.code,
        "strategy": {"key": strategy.key, "name": strategy.name, "params": params},
        "startBalance": start,
        "from": bars[0].ts,
        "to": bars[-1].ts,
        "candles": len(bars),
        "source": history.source,
        "sample": history.sample,
        "headline": report.headline(strategy.name, m, None if strategy.benchmark else bh),
        "metrics": m,
        "buyHold": bh,
        "warnings": warnings,
        "assumptions": assumptions,
        "equity": _thin(result.equity),
        "buyHoldEquity": _thin(bh_result.equity),
        "trades": [t.to_dict() for t in result.trades],
    }
