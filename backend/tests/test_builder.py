"""Strategy builder: checking specs, building rules with no look-ahead, and working everywhere."""

import numpy as np
import pandas as pd
import pytest

from app.strategies import builder
from app.strategies.library import STRATEGIES

@pytest.fixture(autouse=True)
def built_ins_only_afterwards():
    yield
    for k in [k for k in STRATEGIES if k.startswith(builder.PREFIX)]:
        del STRATEGIES[k]


ICHI_RSI = {
    "name": "Cloud and RSI dip",
    "long": {"enabled": True,
             "entry": [{"left": {"type": "close"}, "op": "above", "right": {"type": "cloud_top"}},
                       {"left": {"type": "rsi", "length": 14}, "op": "below", "right": {"type": "number", "value": 40}}],
             "exit": [{"left": {"type": "close"}, "op": "below", "right": {"type": "cloud_bottom"}}]},
    "short": {"enabled": False},
    "stop": {"type": "atr", "value": 2},
    "target": {"type": "none"},
}


def frame(n=600, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"ts": np.arange(n) * 86400 + 1_600_000_000, "open": o, "high": np.maximum(o, c) * 1.004,
                         "low": np.minimum(o, c) * 0.996, "close": c, "volume": 0.0, "spread": np.nan})


def test_check_cleans_and_explains_problems():
    clean = builder.check(ICHI_RSI)
    assert clean["long"]["entry"][1]["left"] == {"type": "rsi", "length": 14}
    for bad, msg in [
        ({**ICHI_RSI, "name": ""}, "name"),
        ({**ICHI_RSI, "long": {"enabled": True, "entry": []}}, "at least one rule"),
        ({**ICHI_RSI, "long": {"enabled": True, "entry": [{"left": {"type": "number", "value": 1}, "op": "above", "right": {"type": "close"}}]}}, "not a number"),
        ({**ICHI_RSI, "long": {"enabled": True, "entry": [{"left": {"type": "sma", "length": 1}, "op": "above", "right": {"type": "close"}}]}}, "from 2 to 500"),
        ({**ICHI_RSI, "long": {"enabled": True, "entry": [{"left": {"type": "macd", "fast": 30, "slow": 20, "signal": 9}, "op": "rising"}]}}, "fast length"),
        ({**ICHI_RSI, "stop": {"type": "atr", "value": 50}}, "0.2 to 10"),
        ({**ICHI_RSI, "long": {"enabled": False}, "short": {"enabled": False}}, "Turn on"),
    ]:
        with pytest.raises(builder.SpecError, match=msg):
            builder.check(bad)


def test_rules_read_in_plain_words():
    s = builder.build(7, ICHI_RSI)
    assert s.key == "custom_7" and s.custom and not s.can_short
    assert s.rules_text[0].startswith("Buy at the next open when all of these are true")
    assert "Close is above the top of the Ichimoku cloud" in s.rules_text[0] and "RSI(14) is below 40" in s.rules_text[0]
    assert "Close is below the bottom of the Ichimoku cloud" in s.rules_text[1]
    # Lengths can be tuned by the walk-forward check; the RSI level and stop multiple can't.
    assert [p.key for p in s.length_params()] == ["len_1"]
    assert {p.key for p in s.params} == {"len_1", "level_2", "stop_atr"}


def test_no_look_ahead_signals_only_use_past_candles():
    df = frame()
    s = builder.build(1, ICHI_RSI)
    full = s.run(df).long.entry()
    for cut in (300, 450, 599):
        part = s.run(df.iloc[: cut + 1].reset_index(drop=True)).long.entry()
        assert (part.to_numpy() == full.iloc[: cut + 1].to_numpy()).all()


def test_every_operand_and_op_computes():
    df = frame(400)
    ops = list(builder.OPS)
    for i, t in enumerate(builder.OPERANDS):
        if t == "number":
            continue
        op = ops[i % len(ops)]
        right = None if op in builder.NO_RIGHT else {"type": "close"}
        spec = {**ICHI_RSI, "long": {"enabled": True, "entry": [{"left": {"type": t}, "op": op, "right": right}], "exit": []},
                "short": {"enabled": True, "entry": [{"left": {"type": t}, "op": "rising"}], "exit": []},
                "stop": {"type": "swing", "length": 10}, "target": {"type": "r", "value": 2}}
        rules = builder.build(1, spec).run(df)
        assert len(rules.long.entry()) == len(df) and rules.short is not None
        tgt = rules.long.target
        ok = rules.long.stop.notna() & tgt.notna()
        assert ((tgt[ok] - df["close"][ok]) > 0).all()  # a buy's target is above the close


def test_api_create_use_in_a_backtest_and_protect_running_strategies(signed_in):
    r = signed_in.post("/api/builder", json={"spec": ICHI_RSI})
    assert r.status_code == 200, r.text
    made = r.json()
    key = made["key"]
    assert key in STRATEGIES and made["rules"]
    assert any(s["key"] == key and s["custom"] for s in signed_in.get("/api/strategies").json()["strategies"])
    bt = signed_in.post("/api/backtests", json={"symbol": "EUR_USD", "timeframe": "1d", "strategy": key})
    assert bt.status_code == 200, bt.text
    wf = signed_in.post("/api/backtests/walkforward", json={"symbol": "EUR_USD", "timeframe": "1d", "strategy": key})
    assert wf.status_code == 200, wf.text
    # Changing it is fine until an automatic run uses it.
    changed = {**ICHI_RSI, "name": "Cloud and RSI dip v2"}
    assert signed_in.put(f"/api/builder/{made['id']}", json={"spec": changed}).json()["name"] == "Cloud and RSI dip v2"
    from app.db import new_session
    from app.models import AutoRun

    db = new_session()
    db.add(AutoRun(user_id=1, account_id=1, symbol="EUR_USD", timeframe="1d", strategy=key, params={}, status="running",
                   last_message="", backtest={}))
    db.commit()
    db.close()
    assert signed_in.put(f"/api/builder/{made['id']}", json={"spec": ICHI_RSI}).status_code == 409
    assert signed_in.delete(f"/api/builder/{made['id']}").status_code == 409
    assert signed_in.post("/api/builder", json={"spec": {**ICHI_RSI, "stop": {"type": "atr", "value": 99}}}).status_code == 400


def test_deleted_strategies_leave_the_library(signed_in):
    made = signed_in.post("/api/builder", json={"spec": ICHI_RSI}).json()
    assert made["key"] in STRATEGIES
    assert signed_in.delete(f"/api/builder/{made['id']}").json() == {"ok": True}
    assert made["key"] not in STRATEGIES


def test_custom_strategy_appears_in_the_signal_assistant(signed_in):
    made = signed_in.post("/api/builder", json={"spec": ICHI_RSI}).json()
    r = signed_in.get("/api/signals?symbol=EUR_USD&timeframe=1d")
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["strategies"] if s["key"] == made["key"])
    labels = " ".join(c["label"] for c in row["long"]["conditions"]) if "long" in row else str(row)
    assert "Ichimoku cloud" in labels and "RSI(14)" in labels
