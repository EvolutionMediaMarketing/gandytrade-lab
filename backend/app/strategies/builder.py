"""Strategy builder: your own strategies, made from blocks, that work everywhere the built-in ones do.

A strategy is stored as a small JSON spec: buy rules and (optionally) short rules, each a list of conditions
that must all be true to enter, and a list of exit conditions (any one closes the trade); a stop-loss rule; and
an optional target. Each condition compares two operands (price, a number, or an indicator) with above, below,
crosses above/below, or rising/falling. Everything is worked out from the current and earlier candles only.

The spec is turned into an ordinary Strategy, registered in the library under the key "custom_<id>", so the
backtester, walk-forward check, research scans, automatic paper runs, replay and the signal assistant all use it
with no special handling. Every length in it (an average's length, RSI's length, a swing-low lookback) becomes a
setting the walk-forward check can tune; thresholds like "RSI below 40" are kept as they are ("level_" settings).
"""

import copy
import math
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..indicators.core import adx, atr, bollinger, ema, ichimoku, macd, rsi, sma
from .base import Param, Rules, Side, Strategy, crossed_above, crossed_below, never
from .library import STRATEGIES

PREFIX = "custom_"
MAX_CONDITIONS = 8

# Operand types: label, the length fields they take (name, label, default, min, max), and what they are.
OPERANDS: dict[str, dict[str, Any]] = {
    "close": {"label": "Close", "group": "Price", "lengths": []},
    "open": {"label": "Open", "group": "Price", "lengths": []},
    "high": {"label": "High", "group": "Price", "lengths": []},
    "low": {"label": "Low", "group": "Price", "lengths": []},
    "close_ago": {"label": "Close N candles ago", "group": "Price", "lengths": [("length", "Candles ago", 26, 1, 500)]},
    "highest": {"label": "Highest high of the previous N candles", "group": "Price", "lengths": [("length", "Candles", 20, 2, 500)]},
    "lowest": {"label": "Lowest low of the previous N candles", "group": "Price", "lengths": [("length", "Candles", 20, 2, 500)]},
    "number": {"label": "A number", "group": "Number", "lengths": []},
    "sma": {"label": "Simple moving average", "group": "Averages", "lengths": [("length", "Length", 50, 2, 500)]},
    "ema": {"label": "Exponential moving average", "group": "Averages", "lengths": [("length", "Length", 21, 2, 500)]},
    "rsi": {"label": "RSI", "group": "Momentum", "lengths": [("length", "Length", 14, 2, 100)]},
    "macd": {"label": "MACD line", "group": "Momentum", "lengths": [("fast", "Fast", 12, 2, 100), ("slow", "Slow", 26, 3, 200), ("signal", "Signal", 9, 2, 50)]},
    "macd_signal": {"label": "MACD signal line", "group": "Momentum", "lengths": [("fast", "Fast", 12, 2, 100), ("slow", "Slow", 26, 3, 200), ("signal", "Signal", 9, 2, 50)]},
    "macd_hist": {"label": "MACD histogram", "group": "Momentum", "lengths": [("fast", "Fast", 12, 2, 100), ("slow", "Slow", 26, 3, 200), ("signal", "Signal", 9, 2, 50)]},
    "adx": {"label": "ADX (trend strength)", "group": "Momentum", "lengths": [("length", "Length", 14, 2, 100)]},
    "atr": {"label": "ATR (typical candle range)", "group": "Volatility", "lengths": [("length", "Length", 14, 2, 100)]},
    "bb_upper": {"label": "Upper Bollinger Band", "group": "Volatility", "lengths": [("length", "Length", 20, 2, 200)]},
    "bb_middle": {"label": "Middle Bollinger Band", "group": "Volatility", "lengths": [("length", "Length", 20, 2, 200)]},
    "bb_lower": {"label": "Lower Bollinger Band", "group": "Volatility", "lengths": [("length", "Length", 20, 2, 200)]},
    "cloud_top": {"label": "Ichimoku cloud top (under today's candle)", "group": "Ichimoku", "lengths": []},
    "cloud_bottom": {"label": "Ichimoku cloud bottom (under today's candle)", "group": "Ichimoku", "lengths": []},
    "tenkan": {"label": "Ichimoku conversion line (Tenkan)", "group": "Ichimoku", "lengths": []},
    "kijun": {"label": "Ichimoku base line (Kijun)", "group": "Ichimoku", "lengths": []},
    "span_a_ahead": {"label": "Ichimoku Span A (cloud ahead)", "group": "Ichimoku", "lengths": []},
    "span_b_ahead": {"label": "Ichimoku Span B (cloud ahead)", "group": "Ichimoku", "lengths": []},
}
OPS = {
    "above": "is above", "below": "is below", "crosses_above": "crosses above", "crosses_below": "crosses below",
    "rising": "is rising", "falling": "is falling",
}
NO_RIGHT = {"rising", "falling"}
STOPS = {"atr": "× ATR(14) from the entry", "percent": "% from the entry", "swing": "lowest low (buy) or highest high (short) of the last N candles"}


class SpecError(ValueError):
    """Why a strategy can't be saved, in plain words."""


# --- Checking a spec ----------------------------------------------------------------------------------

def _num(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise SpecError(f"{what} must be a number.") from None
    if not math.isfinite(f):
        raise SpecError(f"{what} must be a number.")
    return f


def _check_operand(o: Any, where: str) -> dict:
    if not isinstance(o, dict) or o.get("type") not in OPERANDS:
        raise SpecError(f"{where}: choose what to compare.")
    t = o["type"]
    out = {"type": t}
    if t == "number":
        out["value"] = _num(o.get("value"), f"{where}: the number")
    for name, label, default, lo, hi in OPERANDS[t]["lengths"]:
        v = int(round(_num(o.get(name, default), f"{where}: {label.lower()}")))
        if not lo <= v <= hi:
            raise SpecError(f"{where}: {label.lower()} must be from {lo} to {hi}.")
        out[name] = v
    if t.startswith("macd") and out["fast"] >= out["slow"]:
        raise SpecError(f"{where}: MACD's fast length must be shorter than its slow length.")
    return out


def _check_conditions(conds: Any, where: str, need: bool) -> list[dict]:
    if not isinstance(conds, list):
        raise SpecError(f"{where}: rules must be a list.")
    if need and not conds:
        raise SpecError(f"{where}: add at least one rule.")
    if len(conds) > MAX_CONDITIONS:
        raise SpecError(f"{where}: at most {MAX_CONDITIONS} rules.")
    out = []
    for i, c in enumerate(conds, 1):
        w = f"{where}, rule {i}"
        if not isinstance(c, dict) or c.get("op") not in OPS:
            raise SpecError(f"{w}: choose how to compare.")
        left = _check_operand(c.get("left"), w)
        if left["type"] == "number":
            raise SpecError(f"{w}: start with a price or indicator, not a number.")
        right = None if c["op"] in NO_RIGHT else _check_operand(c.get("right"), w)
        out.append({"left": left, "op": c["op"], "right": right})
    return out


def check(spec: Any) -> dict:
    """A clean copy of the spec, or SpecError saying what's wrong."""
    if not isinstance(spec, dict):
        raise SpecError("The strategy is empty.")
    name = str(spec.get("name", "")).strip()[:60]
    if not name:
        raise SpecError("Give the strategy a name.")
    out: dict[str, Any] = {"name": name, "description": str(spec.get("description", "")).strip()[:500]}
    sides = 0
    for side, word in (("long", "Buy rules"), ("short", "Short rules")):
        s = spec.get(side) or {}
        enabled = bool(s.get("enabled", side == "long"))
        out[side] = {
            "enabled": enabled,
            "entry": _check_conditions(s.get("entry", []), f"{word} (enter)", enabled),
            "exit": _check_conditions(s.get("exit", []), f"{word} (exit)", False),
        }
        sides += enabled
    if not sides:
        raise SpecError("Turn on buy rules, short rules or both.")
    stop = spec.get("stop") or {}
    st = stop.get("type", "atr")
    if st not in STOPS:
        raise SpecError("Choose a stop-loss rule.")
    out["stop"] = {"type": st}
    if st == "atr":
        out["stop"]["value"] = _num(stop.get("value", 2), "The stop-loss ATR multiple")
        if not 0.2 <= out["stop"]["value"] <= 10:
            raise SpecError("The stop-loss must be 0.2 to 10 × ATR.")
    elif st == "percent":
        out["stop"]["value"] = _num(stop.get("value", 2), "The stop-loss percentage")
        if not 0.05 <= out["stop"]["value"] <= 30:
            raise SpecError("The stop-loss must be 0.05% to 30%.")
    else:
        out["stop"]["length"] = int(round(_num(stop.get("length", 10), "The swing length")))
        if not 2 <= out["stop"]["length"] <= 200:
            raise SpecError("The swing length must be 2 to 200 candles.")
    target = spec.get("target") or {}
    if target.get("type", "none") == "r":
        v = _num(target.get("value", 2), "The target")
        if not 0.25 <= v <= 20:
            raise SpecError("The target must be 0.25R to 20R.")
        out["target"] = {"type": "r", "value": v}
    else:
        out["target"] = {"type": "none"}
    return out


# --- Turning a spec into a Strategy ----------------------------------------------------------------

def _slots(spec: dict) -> list[tuple[list, str, Param]]:
    """Every tunable number in the spec: (path to its dict, field, Param). Lengths are 'len_' settings (the
    walk-forward check may scale them); numbers compared against are 'level_' settings (left as they are)."""
    out: list[tuple[list, str, Param]] = []
    n = 0
    for side in ("long", "short"):
        if not spec[side]["enabled"]:
            continue
        for part in ("entry", "exit"):
            for ci, c in enumerate(spec[side][part]):
                for which in ("left", "right"):
                    o = c[which]
                    if o is None:
                        continue
                    where = f"{'buy' if side == 'long' else 'short'} {'rule' if part == 'entry' else 'exit'} {ci + 1}"
                    for name, label, _d, lo, hi in OPERANDS[o["type"]]["lengths"]:
                        n += 1
                        out.append(([side, part, ci, which], name,
                                    Param(f"len_{n}", f"{OPERANDS[o['type']]['label']} {label.lower()} ({where})", o[name], lo, hi, 1)))
                    if o["type"] == "number":
                        n += 1
                        v = o["value"]
                        step = 1 if float(v).is_integer() else 0.01
                        out.append(([side, part, ci, which], "value",
                                    Param(f"level_{n}", f"Level ({where})", v, -1e9, 1e9, step)))
    if spec["stop"]["type"] == "atr":
        out.append((["stop"], "value", Param("stop_atr", "Stop distance (× ATR)", spec["stop"]["value"], 0.2, 10, 0.1)))
    elif spec["stop"]["type"] == "percent":
        out.append((["stop"], "value", Param("stop_pct", "Stop distance (%)", spec["stop"]["value"], 0.05, 30, 0.05)))
    else:
        out.append((["stop"], "length", Param("len_stop", "Swing low/high lookback (candles)", spec["stop"]["length"], 2, 200, 1)))
    if spec["target"]["type"] == "r":
        out.append((["target"], "value", Param("target_r", "Target (× the risk)", spec["target"]["value"], 0.25, 20, 0.25)))
    return out


def _apply(spec: dict, slots: list, p: dict) -> dict:
    s = copy.deepcopy(spec)
    for path, field, param in slots:
        node: Any = s
        for k in path:
            node = node[k]
        node[field] = p.get(param.key, param.default)
    return s


def operand_label(o: dict) -> str:
    t = o["type"]
    if t == "number":
        v = o["value"]
        return f"{v:g}"
    if t in ("close", "open", "high", "low"):
        return OPERANDS[t]["label"]
    if t == "close_ago":
        return f"the close {o['length']} candles ago"
    if t == "highest":
        return f"the highest high of the previous {o['length']} candles"
    if t == "lowest":
        return f"the lowest low of the previous {o['length']} candles"
    if t in ("sma", "ema"):
        return f"the {o['length']} {'average' if t == 'sma' else 'EMA'}"
    if t == "rsi":
        return f"RSI({o['length']})"
    if t == "adx":
        return f"ADX({o['length']})"
    if t == "atr":
        return f"ATR({o['length']})"
    if t.startswith("macd"):
        name = {"macd": "MACD", "macd_signal": "the MACD signal line", "macd_hist": "the MACD histogram"}[t]
        return f"{name} ({o['fast']}/{o['slow']}/{o['signal']})"
    if t.startswith("bb_"):
        return f"the {t[3:]} Bollinger Band ({o['length']})"
    return {"cloud_top": "the top of the Ichimoku cloud", "cloud_bottom": "the bottom of the Ichimoku cloud",
            "tenkan": "the conversion line (Tenkan)", "kijun": "the base line (Kijun)",
            "span_a_ahead": "Span A (cloud ahead)", "span_b_ahead": "Span B (cloud ahead)"}[t]


def condition_label(c: dict) -> str:
    left = operand_label(c["left"])
    left = left[0].upper() + left[1:]
    if c["op"] in NO_RIGHT:
        return f"{left} {OPS[c['op']]}"
    return f"{left} {OPS[c['op']]} {operand_label(c['right'])}"


class _Values:
    """Works out each operand's values for one set of candles, once each."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.cache: dict[tuple, pd.Series] = {}
        self._ich = None

    def ich(self):
        if self._ich is None:
            ich = ichimoku(self.df, 9, 26, 52, 26)
            off = ich["lead_offset"]
            a_now, b_now = ich["lead_a"].shift(off), ich["lead_b"].shift(off)
            self._ich = {
                "cloud_top": pd.concat([a_now, b_now], axis=1).max(axis=1, skipna=False),
                "cloud_bottom": pd.concat([a_now, b_now], axis=1).min(axis=1, skipna=False),
                "tenkan": ich["tenkan"], "kijun": ich["kijun"], "span_a_ahead": ich["lead_a"], "span_b_ahead": ich["lead_b"],
            }
        return self._ich

    def get(self, o: dict) -> pd.Series:
        key = tuple(sorted(o.items()))
        if key in self.cache:
            return self.cache[key]
        df, t = self.df, o["type"]
        c = df["close"]
        if t in ("close", "open", "high", "low"):
            v = df[t]
        elif t == "number":
            v = pd.Series(float(o["value"]), index=df.index)
        elif t == "close_ago":
            v = c.shift(int(o["length"]))
        elif t == "highest":
            v = df["high"].rolling(int(o["length"])).max().shift(1)
        elif t == "lowest":
            v = df["low"].rolling(int(o["length"])).min().shift(1)
        elif t == "sma":
            v = sma(c, int(o["length"]))
        elif t == "ema":
            v = ema(c, int(o["length"]))
        elif t == "rsi":
            v = rsi(c, int(o["length"]))
        elif t == "adx":
            v = adx(df, int(o["length"]))
        elif t == "atr":
            v = atr(df, int(o["length"]))
        elif t.startswith("macd"):
            m = macd(c, int(o["fast"]), int(o["slow"]), int(o["signal"]))
            v = m[{"macd": "macd", "macd_signal": "signal", "macd_hist": "hist"}[t]]
        elif t.startswith("bb_"):
            b = bollinger(c, int(o["length"]), 2.0)
            v = b[{"bb_upper": "upper", "bb_middle": "basis", "bb_lower": "lower"}[t]]
        else:
            v = self.ich()[t]
        v = v.astype(float)
        self.cache[key] = v
        return v

    def condition(self, cnd: dict) -> pd.Series:
        left = self.get(cnd["left"])
        op = cnd["op"]
        if op == "rising":
            return left > left.shift(1)
        if op == "falling":
            return left < left.shift(1)
        right = self.get(cnd["right"])
        if op == "above":
            return left > right
        if op == "below":
            return left < right
        if op == "crosses_above":
            return crossed_above(left, right)
        return crossed_below(left, right)


def _side(spec: dict, vals: _Values, side: str) -> Side:
    df = vals.df
    c = df["close"]
    s = spec[side]
    sign = 1 if side == "long" else -1
    if not s["enabled"]:
        nan = pd.Series(np.nan, index=df.index)
        return Side(conditions={"(no rules for this side)": never(df.index)}, exit=never(df.index), stop=nan)
    conditions = {condition_label(x): vals.condition(x) for x in s["entry"]}
    if s["exit"]:
        exits = [vals.condition(x) for x in s["exit"]]
        exit_ = exits[0].fillna(False).astype(bool)
        for e in exits[1:]:
            exit_ = exit_ | e.fillna(False).astype(bool)
        exit_label = " or ".join(condition_label(x) for x in s["exit"])
    else:
        exit_, exit_label = never(df.index), "Only the stop-loss or target closes the trade"
    st = spec["stop"]
    if st["type"] == "atr":
        stop = c - sign * float(st["value"]) * atr(df, 14)
        stop_label = f"{float(st['value']):g} × ATR {'below' if sign > 0 else 'above'} the entry"
    elif st["type"] == "percent":
        stop = c * (1 - sign * float(st["value"]) / 100)
        stop_label = f"{float(st['value']):g}% {'below' if sign > 0 else 'above'} the entry"
    else:
        n = int(st["length"])
        stop = df["low"].rolling(n).min() if sign > 0 else df["high"].rolling(n).max()
        stop = stop.where((c - stop) * sign > 0)  # a stop on the wrong side means no trade
        stop_label = f"The {'lowest low' if sign > 0 else 'highest high'} of the last {n} candles"
    target, target_label = None, ""
    if spec["target"]["type"] == "r":
        r = float(spec["target"]["value"])
        target = c + (c - stop) * r
        target_label = f"{r:g} × the risk {'above' if sign > 0 else 'below'} the entry"
    return Side(conditions=conditions, exit=exit_, stop=stop, exit_label=exit_label, stop_label=stop_label,
                target=target, target_label=target_label)


def rules_text(spec: dict) -> list[str]:
    out = []
    for side, word in (("long", "Buy"), ("short", "Short")):
        s = spec[side]
        if not s["enabled"]:
            continue
        out.append(f"{word} at the next open when all of these are true at a candle's close: "
                   + "; ".join(condition_label(x) for x in s["entry"]) + ".")
        if s["exit"]:
            out.append(f"Close the {word.lower()} when any of these is true: " + "; ".join(condition_label(x) for x in s["exit"]) + ".")
    st = spec["stop"]
    out.append("Stop-loss: " + (f"{st['value']:g} × ATR(14) from the entry" if st["type"] == "atr"
                                else f"{st['value']:g}% from the entry" if st["type"] == "percent"
                                else f"the lowest low (buys) or highest high (shorts) of the last {st['length']} candles") + ".")
    if spec["target"]["type"] == "r":
        out.append(f"Target: {spec['target']['value']:g} × the risk.")
    return out


def build(row_id: int, spec: dict) -> Strategy:
    spec = check(spec)
    slots = _slots(spec)

    def compute(df: pd.DataFrame, p: dict) -> Rules:
        s = _apply(spec, slots, p)
        vals = _Values(df)
        long = _side(s, vals, "long")
        short = _side(s, vals, "short") if s["short"]["enabled"] else None
        return Rules(long, short)

    summary = spec["description"] or " ".join(rules_text(spec)[:1])
    return Strategy(
        key=f"{PREFIX}{row_id}", name=spec["name"], summary=summary[:300], rules_text=rules_text(spec),
        works_when="Your own strategy: test it before trusting it.", fails_when="Unknown until tested: run the walk-forward check.",
        exercise="Backtest it on three markets, then run the walk-forward check before giving it a paper account.",
        params=[p for _, _, p in slots], compute=compute, can_short=spec["short"]["enabled"], custom=True,
    )


# --- Keeping the library in step with the database ------------------------------------------------

def sync(db: Session) -> None:
    """Register every saved strategy in the library (and drop deleted ones). Cheap: call it freely."""
    from ..models import CustomStrategy

    rows = list(db.scalars(select(CustomStrategy)))
    keep = set()
    for r in rows:
        key = f"{PREFIX}{r.id}"
        keep.add(key)
        cur = STRATEGIES.get(key)
        stamp = r.updated_at.isoformat() if r.updated_at else ""
        if cur is not None and getattr(cur, "version", None) == stamp:
            continue
        try:
            s = build(r.id, r.spec)
        except SpecError:
            continue
        STRATEGIES[key] = replace(s, version=stamp)
    for key in [k for k in STRATEGIES if k.startswith(PREFIX) and k not in keep]:
        del STRATEGIES[key]


def catalogue() -> dict:
    """What the builder page can offer."""
    return {
        "operands": [{"type": k, "label": v["label"], "group": v["group"],
                      "lengths": [{"name": n, "label": lab, "default": d, "min": lo, "max": hi} for n, lab, d, lo, hi in v["lengths"]]}
                     for k, v in OPERANDS.items()],
        "ops": [{"op": k, "label": v, "needsRight": k not in NO_RIGHT} for k, v in OPS.items()],
        "stops": [{"type": k, "label": v} for k, v in STOPS.items()],
        "maxConditions": MAX_CONDITIONS,
    }
