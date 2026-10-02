"""Indicator maths. Inputs are pandas Series/DataFrames of price bars in time order.

Conventions follow TradingView's built-in indicators where they differ from
textbook versions (Wilder smoothing for RSI and ATR, population standard
deviation for Bollinger Bands, Ichimoku spans offset by displacement - 1),
so values here can be checked against a TradingView chart.
"""

import numpy as np
import pandas as pd


def sma(src: pd.Series, length: int) -> pd.Series:
    return src.rolling(length, min_periods=length).mean()


def ema(src: pd.Series, length: int) -> pd.Series:
    out = src.ewm(span=length, adjust=False).mean()
    out.iloc[: length - 1] = np.nan  # too early to be meaningful
    return out


def rma(src: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average: seeded with a simple average, then alpha = 1/length."""
    values = src.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    valid = np.where(~np.isnan(values))[0]
    if len(valid) < length:
        return pd.Series(out, index=src.index)
    first = valid[0]
    seed_end = first + length
    if seed_end > len(values):
        return pd.Series(out, index=src.index)
    out[seed_end - 1] = values[first:seed_end].mean()
    for i in range(seed_end, len(values)):
        out[i] = (out[i - 1] * (length - 1) + values[i]) / length
    return pd.Series(out, index=src.index)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = rma(change.clip(lower=0), length)
    loss = rma((-change).clip(lower=0), length)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & gain.notna()] = 100.0
    out[(loss == 0) & (gain == 0)] = 50.0
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    line = fast_ema - slow_ema
    sig = line.ewm(span=signal, adjust=False).mean()
    df = pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})
    df.iloc[: slow - 1] = np.nan
    df.iloc[: slow + signal - 2, df.columns.get_loc("signal")] = np.nan
    df.iloc[: slow + signal - 2, df.columns.get_loc("hist")] = np.nan
    return df


def bollinger(close: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    basis = sma(close, length)
    dev = close.rolling(length, min_periods=length).std(ddof=0)
    return pd.DataFrame({"basis": basis, "upper": basis + mult * dev, "lower": basis - mult * dev})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    tr = ranges.max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average Directional Index (Wilder): how strongly the price is trending, 0 to 100, whichever way.
    Below about 20 usually means a quiet, sideways market."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = rma(true_range(df), length)
    plus_di = 100 * rma(plus_dm.fillna(0), length) / tr
    minus_di = 100 * rma(minus_dm.fillna(0), length) / tr
    total = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / total
    return rma(dx, length)


def stochastic(df: pd.DataFrame, k_length: int = 14, k_smooth: int = 3, d_length: int = 3) -> pd.DataFrame:
    lowest = df["low"].rolling(k_length, min_periods=k_length).min()
    highest = df["high"].rolling(k_length, min_periods=k_length).max()
    span = highest - lowest
    raw = 100 * (df["close"] - lowest) / span.replace(0, np.nan)
    raw = raw.where(span != 0, 50.0).where(span.notna())
    k = sma(raw, k_smooth)
    d = sma(k, d_length)
    return pd.DataFrame({"k": k, "d": d})


def vwap(df: pd.DataFrame, ts: pd.Series) -> pd.Series:
    """Volume-weighted average price, restarting each UTC day (intraday charts only)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume = df["volume"].fillna(0)
    day = (ts // 86400).to_numpy()
    pv = (typical * volume).groupby(day).cumsum()
    vv = volume.groupby(day).cumsum()
    return (pv / vv.replace(0, np.nan)).set_axis(df.index)


def ichimoku(
    df: pd.DataFrame, conversion: int = 9, base: int = 26, span_b: int = 52, displacement: int = 26
) -> dict:
    """Returns unshifted lines plus the offsets to plot them with.

    The leading spans are drawn (displacement - 1) bars into the future and the
    lagging span (displacement - 1) bars into the past, as on TradingView.
    """

    def midpoint(n: int) -> pd.Series:
        hh = df["high"].rolling(n, min_periods=n).max()
        ll = df["low"].rolling(n, min_periods=n).min()
        return (hh + ll) / 2

    tenkan = midpoint(conversion)
    kijun = midpoint(base)
    lead_a = (tenkan + kijun) / 2
    lead_b = midpoint(span_b)
    offset = displacement - 1
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "lead_a": lead_a,
        "lead_b": lead_b,
        "lagging": df["close"],
        "lead_offset": offset,
        "lag_offset": -offset,
    }


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    ha_close = (o + h + l + c) / 4
    ha_open = np.empty_like(ha_close)
    if len(ha_open):
        ha_open[0] = (o[0] + c[0]) / 2
        for i in range(1, len(ha_open)):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    ha_high = np.maximum.reduce([h, ha_open, ha_close])
    ha_low = np.minimum.reduce([l, ha_open, ha_close])
    return pd.DataFrame(
        {"open": ha_open, "high": ha_high, "low": ha_low, "close": ha_close, "volume": df["volume"].to_numpy()},
        index=df.index,
    )
