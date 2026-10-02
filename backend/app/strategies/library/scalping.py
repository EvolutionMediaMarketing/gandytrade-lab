"""Scalping: short trades on 1 to 15-minute candles, inside the busiest hours of the UK trading day.

Costs matter far more here than on daily charts: a scalp aims for a few pips, and the spread and
slippage are charged on every trade. Each of these closes any open trade by the end of its session,
so nothing is held overnight, and takes no new trades in the session's last 15 minutes (a trade
opened then would only be closed again straight away). Sessions end by 20:00 UK at the latest,
before markets close for the night or the weekend. Times are UK time (British Summer Time included).
"""

import numpy as np
import pandas as pd

from ...indicators.core import adx, atr, bollinger, ema, rsi
from ..base import Param, Rules, Side, Strategy, never, uk_clock


LAST_ENTRY = 15  # minutes before the session ends: no new trades after this


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# --- London open breakout ---------------------------------------------------------------------------

def _london_breakout(df: pd.DataFrame, p: dict) -> Rules:
    start, end, day, step = uk_clock(df)
    c, h, lo = df["close"], df["high"], df["low"]
    open_at = int(p["open_hour"]) * 60
    range_end = open_at + int(p["range_minutes"])
    exit_at = int(p["exit_hour"]) * 60
    idx = df.index
    if step <= 0 or step > int(p["range_minutes"]) or step > 15:
        side = Side({"Needs 1 to 15-minute candles": never(idx)}, exit=never(idx), stop=pd.Series(np.nan, index=idx))
        return Rules(side, side, ["The London open breakout needs 1, 5 or 15-minute candles."])

    in_range = (start >= open_at) & (end <= range_end)
    expected = (range_end - open_at) // step
    high_so_far = h.where(in_range).groupby(day).cummax().groupby(day).ffill()
    low_so_far = lo.where(in_range).groupby(day).cummin().groupby(day).ffill()
    complete = in_range.astype(int).groupby(day).cumsum() >= expected  # no missing candles in the range
    window = (start >= range_end) & (end <= exit_at - LAST_ENTRY) & complete
    up, down = c > high_so_far, c < low_so_far
    breaks = (up | down) & window
    first = breaks & (breaks.astype(int).groupby(day).cumsum() == 1)
    session_over = end >= exit_at
    t = p["target_r"]
    rng = f"{_hhmm(open_at)} to {_hhmm(range_end)}"
    long = Side(
        conditions={
            f"After the opening range ({rng} UK), before {_hhmm(exit_at - LAST_ENTRY)}": window,
            "Closed above the opening range's high": up,
            "The first break of the range today": first,
        },
        exit=session_over,
        stop=low_so_far.where(window),
        target=c + t * (c - low_so_far),
        exit_label=f"End of the session ({_hhmm(exit_at)} UK)",
        stop_label="The bottom of the opening range",
        target_label=f"{t:g} × the risk above the entry",
    )
    short = Side(
        conditions={
            f"After the opening range ({rng} UK), before {_hhmm(exit_at - LAST_ENTRY)}": window,
            "Closed below the opening range's low": down,
            "The first break of the range today": first,
        },
        exit=session_over,
        stop=high_so_far.where(window),
        target=c - t * (high_so_far - c),
        exit_label=f"End of the session ({_hhmm(exit_at)} UK)",
        stop_label="The top of the opening range",
        target_label=f"{t:g} × the risk below the entry",
    )
    return Rules(long, short)


LONDON_BREAKOUT = Strategy(
    key="london_breakout",
    name="London open breakout (scalp)",
    summary="Mark the first 30 minutes after London opens, then trade the first break of that range, out by midday.",
    rules_text=[
        "Use 5-minute candles (1 or 15 also work). All times are UK time.",
        "From 08:00 to 08:30, note the highest and lowest price: the opening range.",
        "After 08:30, the first candle to close above the range is a buy; below it, a short. One trade a day at most.",
        "Stop-loss at the other side of the range. Target 1.5 × the risk.",
        "Anything still open is closed at 12:00.",
    ],
    works_when="Days when London's open starts a clear move, often in GBP/USD, EUR/USD and the FTSE 100.",
    fails_when="Quiet or choppy mornings, when the price pokes out of the range and falls back (a false break).",
    exercise="Try a 60-minute range. Fewer false breaks, but are the stops now too wide to be worth it?",
    params=[
        Param("open_hour", "Range starts (UK hour)", 8, 7, 9),
        Param("range_minutes", "Range length (minutes)", 30, 15, 120, 15),
        Param("exit_hour", "Close everything at (UK hour)", 12, 9, 16),
        Param("target_r", "Target (× risk)", 1.5, 0.5, 4.0, 0.25),
    ],
    compute=_london_breakout,
    intraday_only=True,
    suggested_timeframe="5m",
)


# --- 5-minute trend pullback ------------------------------------------------------------------------

def _scalp_pullback(df: pd.DataFrame, p: dict) -> Rules:
    start, end, _day, _step = uk_clock(df)
    c, h, lo = df["close"], df["high"], df["low"]
    fast, slow = ema(c, p["fast"]), ema(c, p["slow"])
    a = atr(df, 14)
    s_at, e_at = int(p["start_hour"]) * 60, int(p["end_hour"]) * 60
    session = (start >= s_at) & (end <= e_at - LAST_ENTRY)
    t = p["target_r"]
    long_stop = c - p["stop_atr"] * a
    short_stop = c + p["stop_atr"] * a
    hours = f"{_hhmm(s_at)} to {_hhmm(e_at)} UK"
    long = Side(
        conditions={
            f"Within trading hours ({hours})": session,
            f"Uptrend: fast average ({p['fast']}) above slow ({p['slow']}), price above the slow": (fast > slow) & (c > slow),
            "Pulled back to touch the fast average": lo <= fast,
            "Closed back above the fast average": c > fast,
        },
        exit=(end >= e_at) | (c < slow),
        stop=long_stop,
        target=c + t * (c - long_stop),
        exit_label=f"Price closes below the slow average, or the session ends ({_hhmm(e_at)} UK)",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
        target_label=f"{t:g} × the risk above the entry",
    )
    short = Side(
        conditions={
            f"Within trading hours ({hours})": session,
            f"Downtrend: fast average ({p['fast']}) below slow ({p['slow']}), price below the slow": (fast < slow) & (c < slow),
            "Pulled back up to touch the fast average": h >= fast,
            "Closed back below the fast average": c < fast,
        },
        exit=(end >= e_at) | (c > slow),
        stop=short_stop,
        target=c - t * (short_stop - c),
        exit_label=f"Price closes above the slow average, or the session ends ({_hhmm(e_at)} UK)",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
        target_label=f"{t:g} × the risk below the entry",
    )
    notes = ["The fast average must be shorter than the slow one."] if p["fast"] >= p["slow"] else []
    return Rules(long, short, notes)


SCALP_PULLBACK = Strategy(
    key="scalp_pullback",
    name="Trend pullback (scalp)",
    summary="On 5-minute candles during London and New York hours, join the trend when price dips to its 20 average.",
    rules_text=[
        "Use 5-minute candles. Trade only 08:00 to 17:00 UK, when spreads are tightest.",
        "Uptrend: the 20 average is above the 50, and the price is above the 50.",
        "Buy when a candle dips to touch the 20 average and closes back above it. Shorts are the mirror image.",
        "Stop-loss 1 × ATR from the entry. Target 1 × the risk.",
        "Get out if the price closes on the wrong side of the 50 average, and at 17:00 whatever happens.",
    ],
    works_when="Steady intraday trends, such as after a strong London open or US data release.",
    fails_when="Choppy days, when the averages tangle and every pullback keeps going.",
    exercise="Compare a 1R and a 2R target. Does the bigger target win more, after costs?",
    params=[
        Param("fast", "Fast average", 20, 5, 50),
        Param("slow", "Slow average", 50, 20, 200),
        Param("stop_atr", "Stop distance (× ATR)", 1.0, 0.5, 3.0, 0.25),
        Param("target_r", "Target (× risk)", 1.0, 0.5, 3.0, 0.25),
        Param("start_hour", "Start (UK hour)", 8, 7, 14),
        Param("end_hour", "Stop trading (UK hour)", 17, 10, 20),
    ],
    compute=_scalp_pullback,
    intraday_only=True,
    suggested_timeframe="5m",
)


# --- 1-minute range fade ----------------------------------------------------------------------------

def _range_fade(df: pd.DataFrame, p: dict) -> Rules:
    start, end, _day, _step = uk_clock(df)
    c = df["close"]
    bands = bollinger(c, p["length"], p["mult"])
    r = rsi(c, p["rsi_length"])
    quiet = adx(df, 14) < p["adx_max"]
    a = atr(df, 14)
    s_at, e_at = int(p["start_hour"]) * 60, int(p["end_hour"]) * 60
    session = (start >= s_at) & (end <= e_at - LAST_ENTRY)
    lvl = p["rsi_level"]
    hours = f"{_hhmm(s_at)} to {_hhmm(e_at)} UK"
    long = Side(
        conditions={
            f"Within trading hours ({hours})": session,
            f"Quiet, sideways market (ADX below {p['adx_max']:g})": quiet,
            "Closed below the lower Bollinger Band": c < bands["lower"],
            f"RSI ({p['rsi_length']}) below {lvl:g}": r < lvl,
        },
        exit=(c >= bands["basis"]) | (end >= e_at),
        stop=c - p["stop_atr"] * a,
        target=bands["basis"],
        exit_label=f"Back to the middle band, or the session ends ({_hhmm(e_at)} UK)",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
        target_label="The middle Bollinger Band",
    )
    short = Side(
        conditions={
            f"Within trading hours ({hours})": session,
            f"Quiet, sideways market (ADX below {p['adx_max']:g})": quiet,
            "Closed above the upper Bollinger Band": c > bands["upper"],
            f"RSI ({p['rsi_length']}) above {100 - lvl:g}": r > 100 - lvl,
        },
        exit=(c <= bands["basis"]) | (end >= e_at),
        stop=c + p["stop_atr"] * a,
        target=bands["basis"],
        exit_label=f"Back to the middle band, or the session ends ({_hhmm(e_at)} UK)",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
        target_label="The middle Bollinger Band",
    )
    return Rules(long, short)


RANGE_FADE = Strategy(
    key="scalp_range_fade",
    name="Range fade (scalp)",
    summary="On 1-minute candles in a quiet market, sell stretches above the Bollinger Band and buy stretches below, for a snap back to the middle.",
    rules_text=[
        "Use 1-minute candles (5 also works). Trade only 08:00 to 16:00 UK.",
        "Only when the market is quiet: ADX below 20 means no strong trend either way.",
        "Buy when a candle closes below the lower Bollinger Band (20, 2) with RSI (7) under 20. Shorts are the mirror image.",
        "Target: the middle band. Stop-loss 1.5 × ATR from the entry.",
        "Get out at the middle band, or at 16:00 whatever happens.",
    ],
    works_when="Calm, range-bound sessions with no big news due.",
    fails_when="A breakout or a news release: the stretch keeps stretching. Costs also take a big bite of such small moves.",
    exercise="Look at the costs line: how much of the profit before costs did the spread take?",
    params=[
        Param("length", "Band length (candles)", 20, 10, 60),
        Param("mult", "Band width (std devs)", 2.0, 1.5, 3.5, 0.25),
        Param("rsi_length", "RSI length", 7, 2, 21),
        Param("rsi_level", "RSI extreme", 20, 5, 35),
        Param("adx_max", "Quiet market: ADX below", 20, 10, 35),
        Param("stop_atr", "Stop distance (× ATR)", 1.5, 0.5, 4.0, 0.25),
        Param("start_hour", "Start (UK hour)", 8, 0, 20),
        Param("end_hour", "Stop trading (UK hour)", 16, 4, 20),
    ],
    compute=_range_fade,
    intraday_only=True,
    suggested_timeframe="1m",
)
