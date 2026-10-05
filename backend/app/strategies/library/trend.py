"""Trend-following strategies: join a move that's already under way."""

import pandas as pd

from ...indicators.core import atr, ema, ichimoku, macd, sma
from ..base import Param, Rules, Side, Strategy, crossed_above, crossed_below

STOP_ATR = Param("stop_atr", "Stop distance (× ATR)", 2.0, 0.5, 6.0, 0.25,
                 "How far below the entry the stop-loss goes, in multiples of the Average True Range.")


def _ma_cross(df: pd.DataFrame, p: dict) -> Rules:
    fast, slow = sma(df["close"], p["fast"]), sma(df["close"], p["slow"])
    a = atr(df, 14)
    c = df["close"]
    long = Side(
        conditions={
            f"Fast average ({p['fast']}) is above slow average ({p['slow']})": fast > slow,
            "It crossed above on this candle": crossed_above(fast, slow),
        },
        exit=crossed_below(fast, slow),
        stop=c - p["stop_atr"] * a,
        exit_label="Fast average crosses back below the slow average",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
    )
    short = Side(
        conditions={
            f"Fast average ({p['fast']}) is below slow average ({p['slow']})": fast < slow,
            "It crossed below on this candle": crossed_below(fast, slow),
        },
        exit=crossed_above(fast, slow),
        stop=c + p["stop_atr"] * a,
        exit_label="Fast average crosses back above the slow average",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
    )
    notes = ["Fast average must be shorter than the slow one."] if p["fast"] >= p["slow"] else []
    return Rules(long, short, notes)


MA_CROSS = Strategy(
    key="ma_cross",
    name="Moving-average crossover",
    summary="Buy when a short-term average crosses above a long-term average; sell when it crosses back.",
    rules_text=[
        "Work out two simple moving averages of the closing price: a fast one (20 candles) and a slow one (50).",
        "Buy at the next open when the fast average crosses above the slow one.",
        "Put the stop-loss 2 × ATR below the entry price.",
        "Sell at the next open when the fast average crosses back below the slow one, or if the stop is hit.",
    ],
    works_when="Markets trend for weeks or months (strong rallies or slides).",
    fails_when="Prices go sideways: the averages keep crossing and you collect many small losses.",
    exercise="Backtest it on GBP/USD daily, then on the S&P 500 ETF (SPY). Which suits it better, and why?",
    params=[
        Param("fast", "Fast average (candles)", 20, 2, 200),
        Param("slow", "Slow average (candles)", 50, 5, 400),
        STOP_ATR,
    ],
    compute=_ma_cross,
)


def _trend_pullback(df: pd.DataFrame, p: dict) -> Rules:
    c, low, high = df["close"], df["low"], df["high"]
    trend = sma(c, p["trend"])
    fast = ema(c, p["pullback"])
    a = atr(df, 14)
    long = Side(
        conditions={
            f"Uptrend: price above the {p['trend']}-candle average": c > trend,
            f"Pulled back: the candle dipped to the {p['pullback']} average": low <= fast,
            f"Recovered: closed back above the {p['pullback']} average": c > fast,
        },
        exit=c < trend,
        stop=low.rolling(5).min() - 0.5 * a,
        exit_label=f"Price closes below the {p['trend']}-candle average (trend over)",
        stop_label="Just below the lowest low of the last 5 candles",
    )
    short = Side(
        conditions={
            f"Downtrend: price below the {p['trend']}-candle average": c < trend,
            f"Bounced: the candle rose to the {p['pullback']} average": high >= fast,
            f"Rejected: closed back below the {p['pullback']} average": c < fast,
        },
        exit=c > trend,
        stop=high.rolling(5).max() + 0.5 * a,
        exit_label=f"Price closes above the {p['trend']}-candle average",
        stop_label="Just above the highest high of the last 5 candles",
    )
    return Rules(long, short)


TREND_PULLBACK = Strategy(
    key="trend_pullback",
    name="Trend pullback",
    summary="In an uptrend, wait for a dip to the 20 average and buy when price recovers.",
    rules_text=[
        "Only buy when the price is above its 200-candle average (the market is in an uptrend).",
        "Wait for a candle that dips down to the 20-candle exponential average…",
        "…and still closes above it. Buy at the next open.",
        "Stop-loss just below the lowest low of the last 5 candles.",
        "Sell if the price closes below the 200-candle average.",
    ],
    works_when="Steady trends with regular shallow dips.",
    fails_when="The trend is ending: dips keep getting deeper until the stop is hit.",
    exercise="Compare this with the crossover on the same market. Does buying dips give better entries?",
    params=[
        Param("trend", "Trend average (candles)", 200, 20, 400),
        Param("pullback", "Pullback average (candles)", 20, 5, 100),
    ],
    compute=_trend_pullback,
)


def _breakout(df: pd.DataFrame, p: dict) -> Rules:
    c = df["close"]
    upper = df["high"].rolling(p["entry_len"]).max().shift(1)
    lower = df["low"].rolling(p["entry_len"]).min().shift(1)
    exit_low = df["low"].rolling(p["exit_len"]).min().shift(1)
    exit_high = df["high"].rolling(p["exit_len"]).max().shift(1)
    a = atr(df, 14)
    long = Side(
        conditions={f"Closed above the highest high of the previous {p['entry_len']} candles": c > upper},
        exit=c < exit_low,
        stop=c - p["stop_atr"] * a,
        exit_label=f"Price closes below the lowest low of the previous {p['exit_len']} candles",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
    )
    short = Side(
        conditions={f"Closed below the lowest low of the previous {p['entry_len']} candles": c < lower},
        exit=c > exit_high,
        stop=c + p["stop_atr"] * a,
        exit_label=f"Price closes above the highest high of the previous {p['exit_len']} candles",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
    )
    return Rules(long, short)


BREAKOUT = Strategy(
    key="breakout",
    name="Breakout",
    summary="Buy when price closes at a new high of the last N candles; sell at a low of the last M. "
            "Named by its two lengths: Breakout 20/10 is the standard, Breakout 55/20 a slower version.",
    rules_text=[
        "Buy at the next open when the price closes above the highest high of the previous N candles (breakout length, standard 20).",
        "Stop-loss 2 × ATR below the entry.",
        "Sell when the price closes below the lowest low of the previous M candles (exit length, standard 10).",
    ],
    works_when="Big, lasting moves, especially in commodities and currencies.",
    fails_when="False breakouts in quiet ranges: price pokes out and falls straight back.",
    exercise="Try it on gold (XAU/USD) daily. Look at how much of the profit came from the few biggest trades.",
    params=[
        Param("entry_len", "Breakout length (candles)", 20, 5, 200),
        Param("exit_len", "Exit length (candles)", 10, 2, 100),
        STOP_ATR,
    ],
    compute=_breakout,
    named_by_lengths=True,
)


def _macd(df: pd.DataFrame, p: dict) -> Rules:
    c = df["close"]
    m = macd(c, p["fast"], p["slow"], p["signal"])
    a = atr(df, 14)
    long = Side(
        conditions={
            "MACD is above zero (momentum is upward)": m["macd"] > 0,
            "MACD crossed above its signal line on this candle": crossed_above(m["macd"], m["signal"]),
        },
        exit=crossed_below(m["macd"], m["signal"]),
        stop=c - p["stop_atr"] * a,
        exit_label="MACD crosses below its signal line",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
    )
    short = Side(
        conditions={
            "MACD is below zero (momentum is downward)": m["macd"] < 0,
            "MACD crossed below its signal line on this candle": crossed_below(m["macd"], m["signal"]),
        },
        exit=crossed_above(m["macd"], m["signal"]),
        stop=c + p["stop_atr"] * a,
        exit_label="MACD crosses above its signal line",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
    )
    return Rules(long, short)


MACD_MOMENTUM = Strategy(
    key="macd_momentum",
    name="MACD momentum",
    summary="Buy when MACD crosses up through its signal line while above zero.",
    rules_text=[
        "MACD (12, 26, 9) measures momentum: the gap between a fast and a slow average.",
        "Buy at the next open when MACD is above zero and crosses above its signal line.",
        "Stop-loss 2 × ATR below the entry.",
        "Sell when MACD crosses back below its signal line.",
    ],
    works_when="Trends that pause and then continue.",
    fails_when="Choppy markets, where MACD crosses back and forth.",
    exercise="Turn on the MACD indicator on the chart and find the last three signals by eye before backtesting.",
    params=[
        Param("fast", "Fast length", 12, 2, 50),
        Param("slow", "Slow length", 26, 5, 100),
        Param("signal", "Signal length", 9, 2, 50),
        STOP_ATR,
    ],
    compute=_macd,
)


def _ichimoku(df: pd.DataFrame, p: dict) -> Rules:
    c = df["close"]
    ich = ichimoku(df, p["conversion"], p["base"], p["span_b"], p["displacement"])
    off = ich["lead_offset"]
    # The cloud under today's candle was calculated `off` candles ago (no look-ahead).
    span_a_now, span_b_now = ich["lead_a"].shift(off), ich["lead_b"].shift(off)
    top = pd.concat([span_a_now, span_b_now], axis=1).max(axis=1, skipna=False)
    bottom = pd.concat([span_a_now, span_b_now], axis=1).min(axis=1, skipna=False)
    tenkan, kijun = ich["tenkan"], ich["kijun"]
    a = atr(df, 14)
    past = c.shift(off)
    long = Side(
        conditions={
            "Price is above the cloud": c > top,
            "Conversion line (Tenkan) is above base line (Kijun)": tenkan > kijun,
            "Cloud ahead is green (Span A above Span B)": ich["lead_a"] > ich["lead_b"],
            f"Lagging line is above the price {off} candles ago": c > past,
        },
        exit=c < kijun,
        stop=kijun - p["stop_atr"] * a,
        exit_label="Price closes below the base line (Kijun)",
        stop_label=f"{p['stop_atr']} × ATR below the base line",
    )
    short = Side(
        conditions={
            "Price is below the cloud": c < bottom,
            "Conversion line (Tenkan) is below base line (Kijun)": tenkan < kijun,
            "Cloud ahead is red (Span A below Span B)": ich["lead_a"] < ich["lead_b"],
            f"Lagging line is below the price {off} candles ago": c < past,
        },
        exit=c > kijun,
        stop=kijun + p["stop_atr"] * a,
        exit_label="Price closes above the base line (Kijun)",
        stop_label=f"{p['stop_atr']} × ATR above the base line",
    )
    return Rules(long, short)


ICHIMOKU_TREND = Strategy(
    key="ichimoku_trend",
    name="Ichimoku Cloud trend",
    summary="Buy when all four Ichimoku signals agree on an uptrend; sell below the base line.",
    rules_text=[
        "Price closes above the cloud.",
        "The conversion line (Tenkan) is above the base line (Kijun).",
        "The cloud ahead is green (Span A above Span B).",
        "The lagging line is above where the price was 25 candles ago (it's drawn 26 candles back, counting today).",
        "When all four are true, buy at the next open. Stop-loss 1 × ATR below the base line.",
        "Sell when the price closes below the base line.",
    ],
    works_when="Clear, sustained trends; it keeps you in while all signals agree.",
    fails_when="Price is inside or hugging the cloud: signals flip often and late.",
    exercise="Add the Ichimoku indicator to a daily chart and tick off the four checks on the latest candle.",
    params=[
        Param("conversion", "Conversion (Tenkan)", 9, 2, 60),
        Param("base", "Base (Kijun)", 26, 5, 120),
        Param("span_b", "Span B", 52, 10, 240),
        Param("displacement", "Displacement", 26, 1, 120),
        Param("stop_atr", "Stop distance (× ATR)", 1.0, 0.25, 6.0, 0.25),
    ],
    compute=_ichimoku,
)
