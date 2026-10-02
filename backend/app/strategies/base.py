"""The shared format every strategy is written in.

A strategy is a set of plain-English conditions per side (long = betting the
price rises, short = betting it falls). A setup is complete when every condition
is true on a finished candle. Each side also has an exit rule and a stop-loss
price. The same calculation feeds the backtester, the signal assistant, paper
trading and, later, live trading, so their results always agree.

Everything is calculated from the current and earlier candles only (no peeking
at the future). Trades are placed at the next candle's open.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    step: float = 1
    help: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "default": self.default, "minimum": self.minimum,
            "maximum": self.maximum, "step": self.step, "help": self.help,
        }


@dataclass
class Side:
    """One direction of a strategy, as series aligned to the candles."""

    conditions: dict[str, pd.Series]  # label -> True/False per candle
    exit: pd.Series  # True on candles where an open trade should be closed at the next open
    stop: pd.Series  # stop-loss price to use if a trade is opened after this candle
    exit_label: str = ""
    stop_label: str = ""
    # Optional profit target: the price to take profit at if a trade is opened after this candle.
    target: pd.Series | None = None
    target_label: str = ""

    def entry(self) -> pd.Series:
        if not self.conditions:
            return pd.Series(False, index=self.exit.index)
        out = None
        for series in self.conditions.values():
            s = series.fillna(False).astype(bool)
            out = s if out is None else (out & s)
        return out & self.stop.notna() & np.isfinite(self.stop)


@dataclass
class Rules:
    long: Side
    short: Side | None = None
    notes: list[str] = field(default_factory=list)  # e.g. "Set your support level first"


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    summary: str
    rules_text: list[str]
    works_when: str
    fails_when: str
    exercise: str
    params: list[Param]
    compute: Callable[[pd.DataFrame, dict], Rules]
    benchmark: bool = False  # buy and hold: compared against, not risk-managed
    can_short: bool = True
    intraday_only: bool = False  # scalping: only trades on short candles (1 to 15 minutes)
    suggested_timeframe: str = ""

    def clean_params(self, raw: dict | None) -> dict:
        raw = raw or {}
        out = {}
        for p in self.params:
            try:
                v = float(raw.get(p.key, p.default))
            except (TypeError, ValueError):
                v = p.default
            if not np.isfinite(v):
                v = p.default
            v = min(p.maximum, max(p.minimum, v))
            out[p.key] = int(v) if float(p.step).is_integer() and float(p.default).is_integer() else v
        return out

    def run(self, df: pd.DataFrame, params: dict | None = None) -> Rules:
        return self.compute(df, self.clean_params(params))

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "summary": self.summary, "rules": self.rules_text,
            "worksWhen": self.works_when, "failsWhen": self.fails_when, "exercise": self.exercise,
            "params": [p.to_dict() for p in self.params], "benchmark": self.benchmark, "canShort": self.can_short,
            "intradayOnly": self.intraday_only, "suggestedTimeframe": self.suggested_timeframe,
        }


# --- Small helpers used by the strategies -------------------------------------------------------

def crossed_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift(1) <= b_prev)


def crossed_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift(1) >= b_prev)


def never(index: pd.Index) -> pd.Series:
    return pd.Series(False, index=index)


# --- Session hours (UK time), for strategies that only trade at certain times of day --------------

def uk_clock(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, int]:
    """For each candle: UK minutes past midnight at its start and at its end, the UK date, and the
    candle length in minutes. British Summer Time is handled."""
    when = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Europe/London")
    start = when.dt.hour * 60 + when.dt.minute
    gaps = df["ts"].diff()
    gaps = gaps[gaps > 0]
    step = int(gaps.mode().iloc[0] // 60) if len(gaps) else 0  # the usual gap, ignoring weekends and holidays
    return start, start + step, when.dt.date, step
