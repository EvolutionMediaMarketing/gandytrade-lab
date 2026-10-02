"""Target odds: hand-made prices where the answer is known, plus the API."""

import numpy as np
import pytest

from app.odds import _outcomes


def test_outcomes_on_a_steady_rise():
    # Price rises 1 a candle with a tiny range: a long target is always reached, a stop never.
    n = 300
    close = np.arange(100, 100 + n, dtype=float)
    high, low = close + 0.1, close - 0.1
    ts = np.arange(n, dtype=np.int64) * 3600
    a = np.ones(n)
    rows = _outcomes(high, low, ts, close, a, side=1, stop_k=1.0, r_levels=[2.0], horizon=20)
    r = rows[0]
    assert r["targetPct"] == 100 and r["stopPct"] == 0
    assert r["medianSeconds"] == 2 * 3600  # +2 needs two candles
    assert r["grossR"] == pytest.approx(2.0)


def test_outcomes_short_side_and_ties_count_as_stops():
    n = 300
    close = np.full(n, 100.0)
    high, low = close + 5, close - 5  # every candle touches both levels
    ts = np.arange(n, dtype=np.int64) * 60
    rows = _outcomes(high, low, ts, close, np.ones(n), side=-1, stop_k=2.0, r_levels=[1.0], horizon=10)
    assert rows[0]["stopPct"] == 100 and rows[0]["targetPct"] == 0 and rows[0]["grossR"] == -1


def test_target_odds_api(signed_in):
    r = signed_in.post("/api/tools/target-odds", json={"symbol": "EUR_USD", "timeframe": "1d",
                                                       "entry": 1.10, "stop": 1.09, "target": 1.12})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["side"] == "long" and d["planR"] == 2.0 and d["current"]["r"] == 2.0
    pcts = [row["targetPct"] for row in d["ladder"]]
    assert pcts == sorted(pcts, reverse=True)  # further targets are reached less often
    for row in d["ladder"]:
        assert row["targetPct"] + row["stopPct"] + row["neitherPct"] == pytest.approx(100, abs=0.2)
    assert d["best"]["netR"] == max(row["netR"] for row in d["ladder"])


def test_target_odds_needs_a_stop(signed_in):
    assert signed_in.post("/api/tools/target-odds", json={"symbol": "EUR_USD", "entry": 1.1, "stop": 1.1}).status_code == 400
