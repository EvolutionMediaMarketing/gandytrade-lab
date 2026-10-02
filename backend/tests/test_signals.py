"""The signal assistant reports rules and evidence, consistently with the backtester."""

import re


def test_signals_for_every_strategy(signed_in):
    r = signed_in.get("/api/signals", params={"symbol": "EUR_USD", "timeframe": "1d"})
    assert r.status_code == 200, r.text
    d = r.json()
    keys = {c["key"] for c in d["strategies"]}
    assert len(keys) == 7 and "buy_hold" not in keys
    assert d["mode"] == "cfd" and d["sample"] is True
    order = {"complete": 0, "forming": 1, "in_trade": 2, "none": 3}
    statuses = [order[c["status"]] for c in d["strategies"]]
    assert statuses == sorted(statuses)
    for c in d["strategies"]:
        for side in c["sides"]:
            assert side["met"] == sum(x["ok"] for x in side["checks"])
            if side["status"] == "complete":
                assert side["met"] == side["total"] and side["plan"]["riskGbp"] <= 2.01
        assert {s["side"] for s in c["sides"]} == {"long", "short"}


def test_signals_never_say_buy_now(signed_in):
    text = signed_in.get("/api/signals", params={"symbol": "AAPL", "timeframe": "1d"}).text.lower()
    assert not re.search(r"buy now|you should|recommend", text)


def test_shares_signals_are_long_only(signed_in):
    d = signed_in.get("/api/signals", params={"symbol": "AAPL", "timeframe": "1d"}).json()
    assert d["mode"] == "cash"
    assert all({s["side"] for s in c["sides"]} == {"long"} for c in d["strategies"])


def test_signals_match_the_backtester(signed_in):
    """'In a trade' must agree with a backtest of the same rules and settings."""
    d = signed_in.get("/api/signals", params={"symbol": "GBP_USD", "timeframe": "1d"}).json()
    for c in d["strategies"]:
        bt = signed_in.post("/api/backtests", json={"symbol": "GBP_USD", "timeframe": "1d", "strategy": c["key"],
                                                    "direction": "both"}).json()
        assert bt["metrics"]["trades"] == c["history"]["trades"], c["key"]
        open_at_end = bool(bt["trades"]) and bt["trades"][-1]["exitReason"].startswith("Still open")
        if c["status"] == "in_trade":
            assert open_at_end
