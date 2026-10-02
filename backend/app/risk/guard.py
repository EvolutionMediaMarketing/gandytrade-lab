"""The risk guard: every simulated (and, later, real) order passes through here.

Rules:
  * A stop-loss is required. No stop, no trade.
  * Risk per trade: by default 1% of the account (never more than 2%). The trade
    size is worked out so that, if the stop is hit, you lose about that much.
  * Leverage cap: with real shares ("cash" mode) you can't buy more than your
    balance. With CFDs/spread bets, UK retail limits apply (30:1 major currency
    pairs, 20:1 gold and indices, 10:1 commodities, 5:1 shares and bonds).
  * Daily loss limit: after losing 3% in a day, no new trades until tomorrow.
  * Drawdown limit: after falling 20% from the account's high point, trading stops.
"""

from dataclasses import dataclass

MAJORS = {"EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD",
          "EUR_GBP", "EUR_JPY", "GBP_JPY", "EUR_CHF", "GBP_CHF", "AUD_JPY", "EUR_AUD", "EUR_CAD"}
MAX_RISK_PCT = 2.0


def leverage_cap(code: str, asset_class: str, mode: str) -> float:
    """Maximum position value as a multiple of the balance."""
    if mode == "cash":
        return 1.0
    if asset_class == "forex":
        return 30.0 if code in MAJORS else 20.0
    if asset_class == "metal":
        return 20.0 if code.startswith("XAU") else 10.0
    if asset_class == "index":
        return 20.0
    if asset_class == "commodity":
        return 10.0
    return 5.0  # shares, ETFs, bonds and anything else


@dataclass(frozen=True)
class RiskSettings:
    risk_pct: float = 1.0
    daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 20.0

    def cleaned(self) -> "RiskSettings":
        return RiskSettings(
            risk_pct=min(MAX_RISK_PCT, max(0.1, self.risk_pct)),
            daily_loss_pct=min(20.0, max(0.5, self.daily_loss_pct)),
            max_drawdown_pct=min(60.0, max(2.0, self.max_drawdown_pct)),
        )


@dataclass
class Decision:
    units: float = 0.0
    reason: str = ""  # why the trade was refused or reduced
    capped: bool = False

    @property
    def ok(self) -> bool:
        return self.units > 0


def size_trade(
    *,
    equity_gbp: float,
    entry: float,
    stop: float,
    side: int,  # +1 long, -1 short
    per_gbp: float,  # units of the price currency per £1 (1 for GBP, 100 for pence)
    cap: float,
    settings: RiskSettings,
) -> Decision:
    """How many units to trade so that hitting the stop loses about `risk_pct` of the account."""
    if equity_gbp <= 0:
        return Decision(reason="No money left in the account.")
    if stop is None or not stop > 0:
        return Decision(reason="No stop-loss, so no trade.")
    distance = (entry - stop) * side
    if distance <= 0:
        return Decision(reason="The stop-loss is on the wrong side of the price.")
    risk_gbp = equity_gbp * settings.risk_pct / 100
    loss_per_unit_gbp = distance / per_gbp
    units = risk_gbp / loss_per_unit_gbp
    max_units = equity_gbp * cap / (entry / per_gbp)
    if units > max_units:
        return Decision(units=max_units, capped=True,
                        reason=f"Size reduced to stay within {cap:g}:1 leverage, so less than {settings.risk_pct:g}% is at risk.")
    return Decision(units=units)


@dataclass
class AccountLimits:
    """Tracks the daily and drawdown limits as a test or paper account runs."""

    settings: RiskSettings
    peak: float
    day: str = ""
    day_start_equity: float = 0.0
    day_realised: float = 0.0
    halted: bool = False
    halt_reason: str = ""

    def new_candle(self, day: str, equity: float) -> None:
        if day != self.day:
            self.day, self.day_start_equity, self.day_realised = day, equity, 0.0
        self.peak = max(self.peak, equity)
        if not self.halted and self.peak > 0 and (self.peak - equity) / self.peak * 100 >= self.settings.max_drawdown_pct:
            self.halted = True
            self.halt_reason = (f"Trading stopped: the account fell {self.settings.max_drawdown_pct:g}% from its high, "
                                "the drawdown limit.")

    def record(self, realised_gbp: float) -> None:
        self.day_realised += realised_gbp

    def entry_block(self) -> str:
        if self.halted:
            return self.halt_reason
        if self.day_start_equity > 0 and -self.day_realised / self.day_start_equity * 100 >= self.settings.daily_loss_pct:
            return f"Daily loss limit ({self.settings.daily_loss_pct:g}%) reached: no new trades today."
        return ""
