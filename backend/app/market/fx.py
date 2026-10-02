"""Converting profits and losses into pounds.

Each market is priced in its own currency: EUR/USD in US dollars, Apple in US
dollars, Tesco in pence. Backtests and calculators report everything in GBP,
using the daily GBP exchange rate from the OANDA practice feed for the day each
trade closed. Without an OANDA key, fixed approximate rates are used and the
result says so.
"""

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from .symbols import Symbol
from .timeframes import get_timeframe

# Approximate units of each currency per £1, used only when live rates aren't available.
APPROX_PER_GBP = {
    "USD": 1.33, "EUR": 1.16, "JPY": 198.0, "CHF": 1.07, "CAD": 1.84, "AUD": 2.03, "NZD": 2.28,
    "HKD": 10.4, "SGD": 1.72, "SEK": 12.8, "NOK": 13.6, "DKK": 8.65, "PLN": 4.95, "CZK": 29.0,
    "HUF": 470.0, "ZAR": 24.0, "MXN": 25.0, "TRY": 54.0, "CNH": 9.5, "THB": 43.0,
}
# OANDA pairs giving "units per £1" directly, or the inverse (GBP per unit).
DIRECT = {"USD", "JPY", "CHF", "CAD", "AUD", "NZD", "HKD", "SGD", "PLN", "ZAR"}
INVERSE = {"EUR"}


def quote_currency(symbol: Symbol) -> str:
    """The currency a market's price is quoted in."""
    if symbol.provider == "alphavantage":
        return "GBX"  # London shares in pence
    if symbol.provider == "twelvedata":
        return "USD"
    parts = symbol.code.split("_")
    return parts[-1] if len(parts) == 2 else "USD"


@dataclass
class Converter:
    """Converts amounts in one currency to GBP, by date."""

    currency: str
    times: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))
    per_gbp: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    fixed: float = 1.0
    note: str = ""

    def rate(self, ts: int | float) -> float:
        """Units of `currency` per £1 at time ts."""
        if self.times.size:
            i = int(np.searchsorted(self.times, ts, side="right")) - 1
            return float(self.per_gbp[max(i, 0)])
        return self.fixed

    def to_gbp(self, amount: float, ts: int | float) -> float:
        return amount / self.rate(ts)


def converter(db: Session | None, currency: str) -> Converter:
    if currency == "GBP":
        return Converter("GBP")
    if currency == "GBX":
        return Converter("GBX", fixed=100.0)

    if db is not None and (currency in DIRECT or currency in INVERSE):
        from .directory import lookup
        from .service import get_history

        code = f"GBP_{currency}" if currency in DIRECT else f"{currency}_GBP"
        try:
            history = get_history(db, lookup(db, code), get_timeframe("1d"))
            if not history.sample and history.bars:
                times = np.array([b.ts for b in history.bars], dtype=np.int64)
                closes = np.array([b.close for b in history.bars], dtype=float)
                per_gbp = closes if currency in DIRECT else 1.0 / closes
                return Converter(currency, times, per_gbp, note=f"{currency} converted to GBP at each day's OANDA rate.")
        except Exception:
            pass

    approx = APPROX_PER_GBP.get(currency)
    if approx is None:
        return Converter(currency, fixed=1.0, note=f"No exchange rate for {currency}; amounts shown as if 1 {currency} = £1.")
    return Converter(currency, fixed=approx, note=f"{currency} converted at a fixed approximate rate ({approx} per £1).")
