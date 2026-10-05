"""Walk-forward check and robustness verdict.

Includes the phase 4 gate: a strategy tuned on prices with no edge at all (pure random walks) must be
labelled Reject, while a trend-follower on genuinely trending prices must not be.
"""

import numpy as np
import pytest

from app.backtest import basket, walkforward
from app.backtest.costs import default_costs
from app.market.providers.base import Bar
from app.risk.guard import RiskSettings
from app.strategies.library import STRATEGIES

T0 = 1_000_000_000
DAY = 86400


class GBP:
    def rate(self, ts):
        return 1.0


def _bars(closes: np.ndarray, rng, wick: float) -> list[Bar]:
    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, wick, len(closes))))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, wick, len(closes))))
    return [Bar(T0 + i * DAY, opens[i], highs[i], lows[i], closes[i]) for i in range(len(closes))]


def random_walk(seed: int, n: int = 2400) -> list[Bar]:
    """No edge for anyone: each day's move is independent of the last."""
    rng = np.random.default_rng(seed)
    return _bars(100 * np.exp(np.cumsum(rng.normal(0, 0.012, n))), rng, 0.006)


def trending(seed: int, n: int = 2400) -> list[Bar]:
    """Long trends that flip direction every 300 days: what trend-followers are built for."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-1, 1], n // 300 + 1) * 0.0025, 300)[:n]
    return _bars(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n) + drift)), rng, 0.002)


def setup(make, seed: int, key: str = "breakout", params: dict | None = None, k: int = 4, direction: str = "long"):
    legs = [basket.Leg(code=f"M{j}", bars=make(seed * 100 + j), conv=GBP(), costs=default_costs("index", "cfd"),
                       leverage=20.0) for j in range(k)]
    return walkforward.Setup(legs, STRATEGIES[key], params or {}, 200.0, "cfd", direction, RiskSettings(1.0, 3.0, 20.0))


@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("key", ["breakout", "ma_cross"])
def test_gate_tuning_on_random_prices_is_rejected(key, seed):
    r = walkforward.run(setup(random_walk, seed, key))
    assert r["ok"]
    assert r["verdict"]["key"] == "reject", (r["verdict"], r["checks"])


def test_gate_trend_follower_on_trending_prices_is_not_rejected():
    r = walkforward.run(setup(trending, 3, "breakout", direction="both"))
    assert r["verdict"]["key"] in ("incubate", "candidate"), r["checks"]
    assert r["unseen"]["metrics"]["returnPct"] > 0


def test_candidates_are_fixed_up_front_with_yours_first():
    s = STRATEGIES["breakout"]
    c = walkforward.candidates(s, {"entry_len": 55, "exit_len": 20})
    assert c[0]["role"] == "yours" and c[0]["label"] == "55/20 (yours)"
    labels = [x["label"] for x in c]
    assert "20/10 (standard)" in labels
    assert "27/10" in labels and "110/40" in labels  # ×0.5 (rounded down) and ×2
    assert len({tuple(sorted(x["params"].items())) for x in c}) == len(c)  # no duplicates
    # The stop (2 × ATR) is a multiple, not a length: never changed.
    assert {x["params"]["stop_atr"] for x in c} == {s.clean_params({})["stop_atr"]}


def test_each_unseen_stretch_comes_after_its_tuning_and_none_overlap():
    r = walkforward.run(setup(random_walk, 5))
    rows = r["windows"]
    assert len(rows) == walkforward.WINDOWS
    for a, b in zip(rows, rows[1:]):
        assert a["testTo"] < b["testFrom"]
    for w in rows:
        assert w["trainFrom"] < w["trainTo"] < w["testFrom"] <= w["testTo"]
        assert w["picked"] in r["candidates"]


def test_windowed_run_only_trades_inside_its_stretch():
    st = setup(trending, 4)
    ts = [b.ts for b in st.legs[0].bars]
    frm, to = ts[1000], ts[1400]
    res = basket.run(st.legs, st.strategy, {}, start_balance=200.0, mode="cfd", direction="long", risk=st.risk,
                     keep_going=True, trade_from=frm, trade_to=to)
    assert res.trades
    assert all(frm <= t.entry_ts and t.exit_ts <= to for t in res.trades)
    assert res.equity[0][0] == frm and res.equity[-1][0] == to


def test_too_little_history_is_explained_not_run():
    st = setup(random_walk, 6)
    for leg in st.legs:
        leg.bars = leg.bars[:200]
    r = walkforward.run(st)
    assert r["ok"] is False and "at least 360 candles" in r["reason"]


def test_one_check_at_a_time():
    walkforward._busy.acquire()
    try:
        with pytest.raises(walkforward.Busy):
            walkforward.run(setup(random_walk, 7))
    finally:
        walkforward._busy.release()


def test_api_single_market_and_basket(signed_in):
    one = signed_in.post("/api/backtests/walkforward", json={"symbol": "EUR_USD", "timeframe": "1d", "strategy": "breakout"})
    assert one.status_code == 200, one.text
    body = one.json()
    assert body["sample"] is True and body["warnings"][0]["level"] == "stop"
    if body["ok"]:
        assert body["verdict"]["key"] in walkforward.VERDICTS
        assert not any(c["key"] == "markets" for c in body["checks"])  # one market: no across-markets check
    many = signed_in.post("/api/backtests/basket/walkforward",
                          json={"markets": ["EUR_USD", "GBP_USD"], "timeframe": "1d", "strategy": "breakout"})
    assert many.status_code == 200, many.text
    if many.json()["ok"]:
        assert any(c["key"] == "markets" for c in many.json()["checks"])
    hold = signed_in.post("/api/backtests/walkforward", json={"symbol": "EUR_USD", "strategy": "buy_hold"})
    assert hold.status_code == 400
