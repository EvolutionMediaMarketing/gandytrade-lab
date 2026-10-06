"""Market replay: a stretch of history to step through, and saved sessions."""

import pytest


def start(client, **kw):
    body = {"symbol": "EUR_USD", "timeframe": "1d", "start": "random", "candles": 120,
            "indicators": [{"id": "sma-1", "type": "sma", "params": {"length": 200}}]}
    body.update(kw)
    return client.post("/api/replay/start", json=body)


def test_replay_window_has_history_before_the_start_and_warm_indicators(signed_in):
    r = start(signed_in)
    assert r.status_code == 200, r.text
    d = r.json()
    s, bars = d["startIndex"], d["bars"]
    assert 30 <= s <= 150 and len(bars) == s + 120
    assert len(d["rates"]) == len(bars) and all(x > 0 for x in d["rates"])
    assert d["costs"]["spread_pct"] > 0 and d["mode"] == "cfd" and d["futureTimes"] == []
    times = [b["time"] for b in bars]
    assert times == sorted(times)
    line = d["indicators"][0]["lines"][0]["values"]
    # The 200 average already has a value on the first candle shown (worked out from earlier, hidden candles).
    assert line and line[0]["time"] == times[0] and all(times[0] <= v["time"] <= times[-1] for v in line)


def test_replay_from_a_chosen_date(signed_in):
    all_bars = start(signed_in, candles=60).json()["bars"]
    when = all_bars[len(all_bars) // 2]["time"]
    from datetime import datetime, timezone

    day = datetime.fromtimestamp(when, tz=timezone.utc).strftime("%Y-%m-%d")
    d = start(signed_in, start=day, candles=60).json()
    assert d["bars"][d["startIndex"]]["time"] >= when - 86400
    assert start(signed_in, start="2999-01-01").status_code == 400
    assert start(signed_in, start="soon").status_code == 400
    assert start(signed_in, timeframe="1m").status_code == 400


def test_sessions_are_saved_and_listed(signed_in):
    body = {"symbol": "EUR_USD", "timeframe": "1d", "start_ts": 1, "end_ts": 2, "candles": 120, "trades": 5, "wins": 2,
            "net_gbp": 3.5, "return_pct": 1.75, "buy_hold_pct": -2.0, "max_drawdown_pct": 4.1, "avg_r": 0.35,
            "lesson": "Waited for closes"}
    assert signed_in.post("/api/replay/results", json=body).status_code == 200
    rows = signed_in.get("/api/replay/results").json()["sessions"]
    assert len(rows) == 1 and rows[0]["avgR"] == pytest.approx(0.35) and rows[0]["lesson"] == "Waited for closes"
