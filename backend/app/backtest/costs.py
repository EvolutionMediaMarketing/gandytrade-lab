"""Trading costs, so backtest results are honest.

Defaults are typical for a UK retail account in 2026; every one can be changed
on the backtest page. All percentages are of the trade's value.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Costs:
    spread_pct: float  # gap between buy and sell price; half paid on the way in, half on the way out
    slippage_pct: float  # fills a little worse than the price you saw, on every order and stop
    commission_gbp: float = 0.0  # fixed fee per order (buy or sell)
    fx_fee_pct: float = 0.0  # currency conversion fee per order (e.g. buying US shares with pounds)
    stamp_duty_pct: float = 0.0  # UK shares: 0.5% on purchases (not CFDs)
    financing_pct_year: float = 0.0  # CFDs: overnight funding, per year of the position's value

    def to_dict(self) -> dict:
        return asdict(self)


def default_costs(asset_class: str, mode: str) -> Costs:
    cfd = mode == "cfd"
    financing = 6.5 if cfd else 0.0
    if asset_class == "forex":
        return Costs(spread_pct=0.01, slippage_pct=0.005, financing_pct_year=financing)
    if asset_class == "metal":
        return Costs(spread_pct=0.03, slippage_pct=0.01, financing_pct_year=financing)
    if asset_class == "commodity":
        return Costs(spread_pct=0.05, slippage_pct=0.02, financing_pct_year=financing)
    if asset_class in ("index", "bond"):
        return Costs(spread_pct=0.02, slippage_pct=0.01, financing_pct_year=financing)
    if asset_class == "ukstock":
        return Costs(spread_pct=0.10, slippage_pct=0.02, stamp_duty_pct=0.0 if cfd else 0.5,
                     financing_pct_year=financing)
    # US stocks and ETFs bought with pounds
    return Costs(spread_pct=0.05, slippage_pct=0.02, fx_fee_pct=0.0 if cfd else 0.15, financing_pct_year=financing)


def merge(base: Costs, overrides: dict | None) -> Costs:
    if not overrides:
        return base
    values = base.to_dict()
    for key, value in overrides.items():
        if key in values and value is not None:
            try:
                values[key] = min(50.0, max(0.0, float(value)))
            except (TypeError, ValueError):
                pass
    return Costs(**values)
