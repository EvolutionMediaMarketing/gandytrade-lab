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


def test_events_match_markets_by_tag():
    from app.market import events
    from app.market.symbols import get_symbol

    gbp = events.tags_for(get_symbol("GBP_USD"))
    assert {"gbp", "usd", "all"} <= gbp and "oil" not in gbp
    brent = {e["title"] for e in events.for_market(get_symbol("BCO_USD"), 0, 2_000_000_000)}
    assert "OPEC decides not to cut output" in brent and "UK votes to leave the EU" not in brent
    cable = {e["title"] for e in events.for_market(get_symbol("GBP_USD"), 0, 2_000_000_000)}
    assert "UK votes to leave the EU" in cable and "Lehman Brothers collapses" in cable  # "all"
    # Dates are real days, in order, with every tag known.
    known = {"all", "equities", "us_equities", "uk_equities", "eu_equities", "japan", "usd", "gbp", "eur", "jpy", "chf",
             "aud", "cny", "gold", "silver", "metals", "oil", "gas", "energy", "grains"}
    days = [e[0] for e in events.EVENTS]
    assert days == sorted(days)
    assert all(set(e[3]) <= known for e in events.EVENTS)


def test_replay_includes_events_in_its_window(signed_in):
    d = start(signed_in, symbol="GBP_USD", candles=120).json()
    assert isinstance(d["events"], list)
    lo, hi = d["bars"][0]["time"] - 7 * 86400, d["bars"][-1]["time"]
    assert all(lo <= e["time"] <= hi for e in d["events"])


def test_a_saved_replay_can_be_reopened_changed_and_deleted(signed_in):
    first = start(signed_in, candles=60).json()
    at = first["bars"][first["startIndex"]]["time"]
    trades = [{"side": 1, "entryTime": at, "exitTime": at + 86400, "entryPrice": 1.1, "exitPrice": 1.2, "stop": 1.05,
               "pnl": 4.0, "r": 2.0, "reason": "Target reached"}]
    body = {"symbol": "EUR_USD", "timeframe": "1d", "start_ts": at, "end_ts": at + 86400 * 40, "candles": 40, "trades": 1,
            "wins": 1, "net_gbp": 4.0, "return_pct": 2.0, "buy_hold_pct": 1.0, "max_drawdown_pct": 0.5, "avg_r": 2.0,
            "lesson": "", "trades_detail": trades}
    row = signed_in.post("/api/replay/results", json=body).json()
    assert row["tradesDetail"] == trades
    # Reopen exactly where it started.
    again = start(signed_in, at=at, candles=140).json()
    assert again["bars"][again["startIndex"]]["time"] == at
    # Change the lesson without saving a second copy.
    assert signed_in.patch(f"/api/replay/results/{row['id']}", json={"lesson": "Patience paid"}).json()["lesson"] == "Patience paid"
    assert len(signed_in.get("/api/replay/results").json()["sessions"]) == 1
    assert signed_in.delete(f"/api/replay/results/{row['id']}").json() == {"ok": True}
    assert signed_in.get("/api/replay/results").json()["sessions"] == []
    assert signed_in.delete(f"/api/replay/results/{row['id']}").status_code == 404
