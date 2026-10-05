"""Monte Carlo check: reproducible, sensible ranges, and honest plain-English findings."""

import time

from app.backtest import montecarlo


def _mix(wins=40, losses=60, win_r=2.5):
    r = [win_r] * wins + [-1.0] * losses
    # Spread the wins out, so the real ordering is a fairly smooth one.
    return [r[(i * 37) % len(r)] for i in range(len(r))]


def test_too_few_trades():
    out = montecarlo.run(montecarlo.Inputs(r=[1.0, -1.0] * 5, start_balance=200, risk_pct=1))
    assert not out["ok"] and "at least 20" in out["reason"]


def test_ranges_are_ordered_and_reproducible():
    inp = montecarlo.Inputs(r=_mix(), start_balance=200, risk_pct=1, drawdown_limit_pct=20)
    a, b = montecarlo.run(inp), montecarlo.run(inp)
    assert a == b  # same backtest, same answer
    f, w = a["final"], a["worstFall"]
    assert f["5"] <= f["25"] <= f["50"] <= f["75"] <= f["95"]
    assert w["50"] <= w["90"] <= w["95"] <= w["99"]
    assert 0 <= a["chanceLoss"] <= 100 and 0 <= a["chanceLimit"] <= 100
    bands = a["curve"]["bands"]
    assert len(bands["50"]) == len(a["curve"]["step"]) == len(a["curve"]["replay"])
    assert all(lo <= hi for lo, hi in zip(bands["5"], bands["95"]))
    assert a["curve"]["replay"][-1] > 200  # +0.75R a trade on average: the real ordering made money
    assert any("1 in 20" in s["text"] for s in a["summary"])


def test_more_risk_means_deeper_falls():
    lo = montecarlo.run(montecarlo.Inputs(r=_mix(), start_balance=200, risk_pct=0.5))
    hi = montecarlo.run(montecarlo.Inputs(r=_mix(), start_balance=200, risk_pct=2))
    assert hi["worstFall"]["95"] > lo["worstFall"]["95"] * 2.5
    assert hi["chanceLimit"] >= lo["chanceLimit"]


def test_losing_strategy_is_called_out():
    out = montecarlo.run(montecarlo.Inputs(r=[1.0] * 30 + [-1.0] * 50, start_balance=200, risk_pct=2))
    assert out["chanceLoss"] > 90
    assert any(s["level"] == "stop" and "below the starting balance" in s["text"] for s in out["summary"])


def test_fast_enough_for_long_histories():
    t = time.time()
    montecarlo.run(montecarlo.Inputs(r=_mix(400, 600) * 3, start_balance=200, risk_pct=1))
    assert time.time() - t < 5
