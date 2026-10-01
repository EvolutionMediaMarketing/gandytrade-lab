import math

import numpy as np
import pandas as pd
import pytest

from app.indicators import core


def bars(closes, spread=1.0):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + spread, "low": c - spread, "close": c, "volume": 100.0})


def test_sma():
    s = core.sma(pd.Series([1, 2, 3, 4, 5], dtype=float), 3)
    assert math.isnan(s[1])
    assert s.tolist()[2:] == [2.0, 3.0, 4.0]


def test_ema_matches_recursion():
    src = pd.Series([10, 11, 12, 11, 13, 14, 15, 14], dtype=float)
    out = core.ema(src, 3)
    alpha = 2 / 4
    expected = [10.0]
    for v in src[1:]:
        expected.append(alpha * v + (1 - alpha) * expected[-1])
    assert math.isnan(out[1])
    np.testing.assert_allclose(out[2:], expected[2:])


def test_rma_is_wilder():
    src = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    out = core.rma(src, 3)
    assert out[2] == pytest.approx(2.0)  # seed: simple average of first 3
    assert out[3] == pytest.approx((2.0 * 2 + 4) / 3)


def test_rsi_extremes():
    assert core.rsi(pd.Series(range(1, 40), dtype=float), 14).iloc[-1] == pytest.approx(100.0)
    assert core.rsi(pd.Series(range(40, 1, -1), dtype=float), 14).iloc[-1] == pytest.approx(0.0)


def test_rsi_hand_calculated():
    closes = pd.Series([10, 11, 10, 12, 11], dtype=float)
    out = core.rsi(closes, 2)
    # changes: +1, -1, +2, -1 ; seed avg gain=(1+0)/2=0.5, avg loss=(0+1)/2=0.5 at index 2 -> RSI 50
    assert out[2] == pytest.approx(50.0)
    # index 3: gain=(0.5*1+2)/2=1.25, loss=(0.5*1+0)/2=0.25 -> RS=5 -> RSI=83.333
    assert out[3] == pytest.approx(100 - 100 / 6)


def test_macd_is_ema_difference():
    src = pd.Series(np.linspace(1, 50, 80))
    m = core.macd(src, 12, 26, 9)
    fast = src.ewm(span=12, adjust=False).mean()
    slow = src.ewm(span=26, adjust=False).mean()
    assert m["macd"].iloc[-1] == pytest.approx(fast.iloc[-1] - slow.iloc[-1])
    assert m["hist"].iloc[-1] == pytest.approx(m["macd"].iloc[-1] - m["signal"].iloc[-1])
    assert math.isnan(m["signal"].iloc[20])


def test_bollinger_flat_market():
    bb = core.bollinger(pd.Series([5.0] * 30), 20, 2)
    assert bb["upper"].iloc[-1] == bb["lower"].iloc[-1] == 5.0


def test_bollinger_uses_population_std():
    src = pd.Series([1.0, 2.0, 3.0, 4.0])
    bb = core.bollinger(src, 4, 1)
    assert bb["upper"].iloc[-1] - bb["basis"].iloc[-1] == pytest.approx(np.std([1, 2, 3, 4]))


def test_atr_constant_range():
    df = bars([100.0] * 30, spread=2.0)
    assert core.atr(df, 14).iloc[-1] == pytest.approx(4.0)


def test_stochastic_close_at_high():
    df = pd.DataFrame({"high": np.arange(1, 31, dtype=float), "low": np.arange(0, 30, dtype=float)})
    df["close"] = df["high"]
    st = core.stochastic(df, 14, 1, 1)
    assert st["k"].iloc[-1] == pytest.approx(100.0)


def test_vwap_restarts_each_day():
    df = pd.DataFrame({"high": [2.0, 4.0, 10.0], "low": [2.0, 4.0, 10.0], "close": [2.0, 4.0, 10.0], "volume": [1.0, 3.0, 5.0]})
    ts = pd.Series([0, 3600, 86400])
    v = core.vwap(df, ts)
    assert v[1] == pytest.approx((2 * 1 + 4 * 3) / 4)
    assert v[2] == pytest.approx(10.0)


def test_ichimoku_lines():
    df = bars(list(range(1, 80)), spread=1.0)
    ich = core.ichimoku(df, 9, 26, 52, 26)
    i = 60
    hh = df["high"].iloc[i - 8 : i + 1].max()
    ll = df["low"].iloc[i - 8 : i + 1].min()
    assert ich["tenkan"].iloc[i] == pytest.approx((hh + ll) / 2)
    assert ich["lead_a"].iloc[i] == pytest.approx((ich["tenkan"].iloc[i] + ich["kijun"].iloc[i]) / 2)
    assert ich["lead_offset"] == 25 and ich["lag_offset"] == -25


def test_heikin_ashi():
    df = pd.DataFrame({"open": [10.0, 12.0], "high": [13.0, 15.0], "low": [9.0, 11.0], "close": [12.0, 14.0], "volume": [1.0, 1.0]})
    ha = core.heikin_ashi(df)
    assert ha["close"][0] == pytest.approx((10 + 13 + 9 + 12) / 4)
    assert ha["open"][0] == pytest.approx(11.0)
    assert ha["open"][1] == pytest.approx((ha["open"][0] + ha["close"][0]) / 2)
    assert ha["high"][1] >= max(ha["open"][1], ha["close"][1])
