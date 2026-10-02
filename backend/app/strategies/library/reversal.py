"""Mean-reversion strategies: buy a dip that's gone too far, expecting a bounce."""

import pandas as pd

from ...indicators.core import atr, bollinger, rsi, sma
from ..base import Param, Rules, Side, Strategy, crossed_above, crossed_below


def _rsi(df: pd.DataFrame, p: dict) -> Rules:
    c = df["close"]
    r = rsi(c, p["length"])
    trend = sma(c, p["trend"])
    a = atr(df, 14)
    low_level, high_level = p["oversold"], 100 - p["oversold"]
    long = Side(
        conditions={
            f"Uptrend: price above the {p['trend']}-candle average": c > trend,
            f"RSI was below {low_level:g} (oversold) on the previous candle": r.shift(1) < low_level,
            f"RSI has turned back up above {low_level:g}": r >= low_level,
        },
        exit=r > p["exit_level"],
        stop=c - p["stop_atr"] * a,
        exit_label=f"RSI rises above {p['exit_level']:g}",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
    )
    short = Side(
        conditions={
            f"Downtrend: price below the {p['trend']}-candle average": c < trend,
            f"RSI was above {high_level:g} (overbought) on the previous candle": r.shift(1) > high_level,
            f"RSI has turned back down below {high_level:g}": r <= high_level,
        },
        exit=r < 100 - p["exit_level"],
        stop=c + p["stop_atr"] * a,
        exit_label=f"RSI falls below {100 - p['exit_level']:g}",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
    )
    return Rules(long, short)


RSI_REVERSAL = Strategy(
    key="rsi_reversal",
    name="RSI reversal",
    summary="In an uptrend, buy when RSI climbs back out of oversold; sell once it recovers.",
    rules_text=[
        "Only buy when the price is above its 200-candle average.",
        "RSI (14) measures how stretched recent moves are. Below 30 is called oversold.",
        "When RSI was below 30 and turns back above it, buy at the next open.",
        "Stop-loss 2 × ATR below the entry.",
        "Sell when RSI rises above 55.",
    ],
    works_when="Healthy uptrends with sharp but short-lived dips, such as large share indices.",
    fails_when="A real crash: oversold can stay oversold for a long time.",
    exercise="Lower the oversold level to 20. Do you get fewer, better trades, or just fewer?",
    params=[
        Param("length", "RSI length", 14, 2, 50),
        Param("oversold", "Oversold level", 30, 5, 45),
        Param("exit_level", "Exit when RSI above", 55, 40, 90),
        Param("trend", "Trend average (candles)", 200, 20, 400),
        Param("stop_atr", "Stop distance (× ATR)", 2.0, 0.5, 6.0, 0.25),
    ],
    compute=_rsi,
)


def _bollinger(df: pd.DataFrame, p: dict) -> Rules:
    c = df["close"]
    bb = bollinger(c, p["length"], p["mult"])
    a = atr(df, 14)
    long = Side(
        conditions={
            "Previous candle closed below the lower band (stretched down)": c.shift(1) < bb["lower"].shift(1),
            "This candle closed back inside the bands": c > bb["lower"],
        },
        exit=c >= bb["basis"],
        stop=c - p["stop_atr"] * a,
        exit_label="Price reaches the middle band",
        stop_label=f"{p['stop_atr']} × ATR below the entry",
    )
    short = Side(
        conditions={
            "Previous candle closed above the upper band (stretched up)": c.shift(1) > bb["upper"].shift(1),
            "This candle closed back inside the bands": c < bb["upper"],
        },
        exit=c <= bb["basis"],
        stop=c + p["stop_atr"] * a,
        exit_label="Price reaches the middle band",
        stop_label=f"{p['stop_atr']} × ATR above the entry",
    )
    return Rules(long, short)


BOLLINGER_BOUNCE = Strategy(
    key="bollinger_bounce",
    name="Bollinger bounce",
    summary="Buy when price snaps back inside the lower Bollinger Band; sell at the middle band.",
    rules_text=[
        "Bollinger Bands sit 2 standard deviations above and below a 20-candle average.",
        "When a candle closes below the lower band and the next closes back inside, buy at the next open.",
        "Stop-loss 2 × ATR below the entry.",
        "Sell when the price reaches the middle band.",
    ],
    works_when="Range-bound markets that swing between support and resistance, such as many currency pairs.",
    fails_when="Strong trends, where price can 'walk' along a band for a long time.",
    exercise="Run it on EUR/GBP, then on a trending stock. Compare win rates and average losses.",
    params=[
        Param("length", "Band length (candles)", 20, 5, 100),
        Param("mult", "Band width (std devs)", 2.0, 1.0, 4.0, 0.25),
        Param("stop_atr", "Stop distance (× ATR)", 2.0, 0.5, 6.0, 0.25),
    ],
    compute=_bollinger,
)


def _levels(df: pd.DataFrame, p: dict) -> Rules:
    c, o, low, high = df["close"], df["open"], df["low"], df["high"]
    a = atr(df, 14)
    sup, res = float(p["support"]), float(p["resistance"])
    notes = []
    if sup <= 0 or res <= 0:
        notes.append("Set your support and resistance prices first (read them off the chart).")
    elif sup >= res:
        notes.append("Support must be below resistance.")
    valid = not notes
    zone = p["zone_atr"] * a
    false = pd.Series(False, index=df.index)
    long = Side(
        conditions={
            f"Price came down to support ({sup:g})": (low <= sup + zone) & (c > sup - zone) if valid else false,
            "Buyers stepped in: the candle closed up": c > o,
        },
        exit=(c >= res - zone) if valid else false,
        stop=pd.Series(sup, index=df.index) - a,
        exit_label=f"Price reaches resistance ({res:g})",
        stop_label="1 × ATR below support",
    )
    short = Side(
        conditions={
            f"Price came up to resistance ({res:g})": (high >= res - zone) & (c < res + zone) if valid else false,
            "Sellers stepped in: the candle closed down": c < o,
        },
        exit=(c <= sup + zone) if valid else false,
        stop=pd.Series(res, index=df.index) + a,
        exit_label=f"Price reaches support ({sup:g})",
        stop_label="1 × ATR above resistance",
    )
    return Rules(long, short, notes)


SUPPORT_RESISTANCE = Strategy(
    key="support_resistance",
    name="Support and resistance (manual)",
    summary="You mark the support and resistance prices; buy bounces off support, sell at resistance.",
    rules_text=[
        "Look at the chart and find a price where falls have stopped several times (support), "
        "and one where rises have stopped (resistance).",
        "Enter both prices in the settings.",
        "When a candle dips to support and closes up, buy at the next open. Stop-loss 1 × ATR below support.",
        "Sell when the price reaches resistance.",
    ],
    works_when="Clear trading ranges that have held several times.",
    fails_when="The level breaks: old support often becomes resistance after a breakdown.",
    exercise="Find a range on a daily chart from last year, enter its levels, and see how many bounces it caught.",
    params=[
        Param("support", "Support price", 0, 0, 1_000_000, 0.00001, "The price falls have stopped at."),
        Param("resistance", "Resistance price", 0, 0, 1_000_000, 0.00001, "The price rises have stopped at."),
        Param("zone_atr", "How close counts (× ATR)", 0.5, 0.1, 3.0, 0.1),
    ],
    compute=_levels,
)
