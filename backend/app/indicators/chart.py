"""Turn price bars plus a list of requested indicators into chart-ready series."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..market.providers.base import Bar
from ..market.timeframes import Timeframe
from . import core


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    step: float = 1


@dataclass(frozen=True)
class IndicatorDef:
    type: str
    name: str
    pane: str  # "price" draws on the price chart; anything else gets its own panel
    params: tuple[Param, ...]
    description: str
    intraday_only: bool = False


def _p(key: str, label: str, default: float, lo: float, hi: float, step: float = 1) -> Param:
    return Param(key, label, default, lo, hi, step)


CATALOGUE: dict[str, IndicatorDef] = {
    d.type: d
    for d in [
        IndicatorDef("sma", "Simple moving average", "price", (_p("length", "Length", 20, 2, 500),),
                     "Average closing price over the last N bars. Smooths out noise to show the trend."),
        IndicatorDef("ema", "Exponential moving average", "price", (_p("length", "Length", 50, 2, 500),),
                     "Like the simple average but gives recent bars more weight, so it reacts faster."),
        IndicatorDef("bollinger", "Bollinger Bands", "price",
                     (_p("length", "Length", 20, 2, 200), _p("mult", "Std. deviations", 2, 0.5, 5, 0.1)),
                     "A moving average with bands that widen when prices are volatile and narrow when calm."),
        IndicatorDef("vwap", "VWAP", "price", (),
                     "Volume-weighted average price for the day. Intraday charts only.", intraday_only=True),
        IndicatorDef("ichimoku", "Ichimoku Cloud", "price",
                     (_p("conversion", "Conversion line", 9, 2, 100), _p("base", "Base line", 26, 2, 200),
                      _p("span_b", "Leading span B", 52, 2, 300), _p("displacement", "Displacement", 26, 1, 200)),
                     "Trend, momentum and support in one view. Price above the cloud suggests an uptrend."),
        IndicatorDef("volume", "Volume", "volume", (),
                     "How much traded in each bar. Forex shows tick volume, the number of price updates."),
        IndicatorDef("rsi", "RSI", "rsi", (_p("length", "Length", 14, 2, 100),),
                     "Momentum from 0 to 100. Above 70 is often called overbought, below 30 oversold."),
        IndicatorDef("macd", "MACD", "macd",
                     (_p("fast", "Fast", 12, 2, 100), _p("slow", "Slow", 26, 3, 200), _p("signal", "Signal", 9, 2, 50)),
                     "The gap between a fast and slow average. Crossing its signal line hints at momentum shifts."),
        IndicatorDef("stochastic", "Stochastic", "stochastic",
                     (_p("k", "%K length", 14, 2, 100), _p("smooth", "%K smoothing", 3, 1, 20), _p("d", "%D length", 3, 1, 20)),
                     "Where the close sits in the recent high-low range, 0 to 100. Above 80 or below 20 are extremes."),
        IndicatorDef("atr", "ATR", "atr", (_p("length", "Length", 14, 2, 100),),
                     "Average true range: how much price typically moves per bar. Used to size stop-losses."),
    ]
}


def catalogue_json() -> list[dict]:
    return [
        {
            "type": d.type,
            "name": d.name,
            "pane": d.pane,
            "description": d.description,
            "intradayOnly": d.intraday_only,
            "params": [p.__dict__ for p in d.params],
        }
        for d in CATALOGUE.values()
    ]


def clean_params(defn: IndicatorDef, raw: dict) -> dict:
    out = {}
    for p in defn.params:
        value = raw.get(p.key, p.default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = p.default
        if math.isnan(value):
            value = p.default
        value = min(max(value, p.minimum), p.maximum)
        out[p.key] = int(round(value)) if p.step >= 1 else value
    return out


def _series(times: list[int], values: pd.Series | np.ndarray) -> list[dict]:
    arr = np.asarray(values, dtype=float)
    return [{"time": t, "value": round(float(v), 8)} for t, v in zip(times, arr) if not math.isnan(v)]


def _shifted(times: list[int], future: list[int], values: pd.Series, offset: int) -> list[dict]:
    """Plot each value `offset` bars later (positive) or earlier (negative)."""
    arr = values.to_numpy(dtype=float)
    n = len(times)
    out = []
    for i, v in enumerate(arr):
        if math.isnan(v):
            continue
        j = i + offset
        if j < 0:
            continue
        if j < n:
            t = times[j]
        elif j - n < len(future):
            t = future[j - n]
        else:
            continue
        out.append({"time": t, "value": round(float(v), 8)})
    return out


def build_chart(bars: list[Bar], tf: Timeframe, style: str, requested: list[dict]) -> dict:
    df = pd.DataFrame([b.__dict__ for b in bars])
    if df.empty:
        return {"bars": [], "indicators": [], "futureTimes": []}
    times = [int(t) for t in df["ts"]]
    ts_series = df["ts"]

    display = core.heikin_ashi(df) if style == "heikin_ashi" else df
    out_bars = [
        {
            "time": t,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for t, r in zip(times, display.itertuples(index=False))
    ]

    future: list[int] = []
    indicators: list[dict] = []
    close = df["close"]

    for item in requested[:20]:
        defn = CATALOGUE.get(str(item.get("type")))
        if defn is None:
            continue
        params = clean_params(defn, item.get("params") or {})
        ind = {"id": str(item.get("id") or defn.type), "type": defn.type, "pane": defn.pane,
               "params": params, "lines": [], "levels": [], "note": None}

        if defn.intraday_only and not tf.intraday:
            ind["note"] = f"{defn.name} is only shown on intraday charts."
        elif defn.type == "sma":
            ind["lines"].append({"key": "sma", "label": f"SMA {params['length']}", "values": _series(times, core.sma(close, params["length"]))})
        elif defn.type == "ema":
            ind["lines"].append({"key": "ema", "label": f"EMA {params['length']}", "values": _series(times, core.ema(close, params["length"]))})
        elif defn.type == "bollinger":
            bb = core.bollinger(close, params["length"], params["mult"])
            ind["lines"] += [
                {"key": "upper", "label": "Upper", "values": _series(times, bb["upper"])},
                {"key": "basis", "label": "Basis", "values": _series(times, bb["basis"])},
                {"key": "lower", "label": "Lower", "values": _series(times, bb["lower"])},
            ]
            ind["fill"] = {"upper": "upper", "lower": "lower"}
        elif defn.type == "vwap":
            ind["lines"].append({"key": "vwap", "label": "VWAP", "values": _series(times, core.vwap(df, ts_series))})
        elif defn.type == "ichimoku":
            ich = core.ichimoku(df, params["conversion"], params["base"], params["span_b"], params["displacement"])
            offset = ich["lead_offset"]
            if len(future) < offset:
                future = [times[-1] + k * tf.seconds for k in range(1, offset + 1)]
            ind["lines"] += [
                {"key": "tenkan", "label": "Conversion", "values": _series(times, ich["tenkan"])},
                {"key": "kijun", "label": "Base", "values": _series(times, ich["kijun"])},
                {"key": "lead_a", "label": "Leading span A", "values": _shifted(times, future, ich["lead_a"], offset)},
                {"key": "lead_b", "label": "Leading span B", "values": _shifted(times, future, ich["lead_b"], offset)},
                {"key": "lagging", "label": "Lagging span", "values": _shifted(times, future, ich["lagging"], ich["lag_offset"])},
            ]
            ind["fill"] = {"upper": "lead_a", "lower": "lead_b", "twoTone": True}
        elif defn.type == "volume":
            ind["lines"].append({"key": "volume", "label": "Volume", "kind": "histogram",
                                 "values": _series(times, df["volume"])})
        elif defn.type == "rsi":
            ind["lines"].append({"key": "rsi", "label": f"RSI {params['length']}", "values": _series(times, core.rsi(close, params["length"]))})
            ind["levels"] = [70, 50, 30]
        elif defn.type == "macd":
            if params["fast"] >= params["slow"]:
                params["fast"] = max(2, params["slow"] - 1)
            m = core.macd(close, params["fast"], params["slow"], params["signal"])
            ind["lines"] += [
                {"key": "hist", "label": "Histogram", "kind": "histogram", "values": _series(times, m["hist"])},
                {"key": "macd", "label": "MACD", "values": _series(times, m["macd"])},
                {"key": "signal", "label": "Signal", "values": _series(times, m["signal"])},
            ]
            ind["levels"] = [0]
        elif defn.type == "stochastic":
            st = core.stochastic(df, params["k"], params["smooth"], params["d"])
            ind["lines"] += [
                {"key": "k", "label": "%K", "values": _series(times, st["k"])},
                {"key": "d", "label": "%D", "values": _series(times, st["d"])},
            ]
            ind["levels"] = [80, 20]
        elif defn.type == "atr":
            ind["lines"].append({"key": "atr", "label": f"ATR {params['length']}", "values": _series(times, core.atr(df, params["length"]))})

        indicators.append(ind)

    return {"bars": out_bars, "indicators": indicators, "futureTimes": future}
