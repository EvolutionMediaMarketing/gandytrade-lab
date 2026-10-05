"""Basket backtest: identical to the normal backtester for one market, and the shared limits work."""

import pytest

from app.backtest import basket, engine
from app.backtest.costs import default_costs
from app.market.providers import sample
from app.market.symbols import get_symbol
from app.market.timeframes import get_timeframe
from app.risk.guard import RiskSettings
from app.strategies.library import STRATEGIES

T0 = 1_500_000_000
DAY = 86400


class GBP:
    def rate(self, ts):
        return 1.0


def bars(code, n=1500):
    return sample.generate(get_symbol(code), get_timeframe("1d"), n, now=T0 + 3000 * DAY)


def leg(code, n=1500):
    return basket.Leg(code=code, bars=bars(code, n), conv=GBP(), costs=default_costs("forex", "cfd"), leverage=30.0)


@pytest.mark.parametrize("key", ["breakout", "ma_cross", "rsi_reversal"])
def test_one_market_matches_the_normal_backtest(key):
    s = STRATEGIES[key]
    risk = RiskSettings(1.0, 3.0, 20.0)
    one = leg("EUR_USD")
    res_b = basket.run([one], s, {}, start_balance=200.0, mode="cfd", direction="both", risk=risk, max_open_risk_pct=100.0)
    settings = engine.Settings(start_balance=200.0, mode="cfd", direction="both", risk=risk, leverage=30.0,
                               costs=default_costs("forex", "cfd"))
    res_e = engine.run(one.bars, s, {}, settings, GBP())
    assert len(res_b.trades) == len(res_e.trades) > 0
    for a, b in zip(res_b.trades, res_e.trades):
        assert (a.side, a.entry_ts, a.exit_ts, a.exit_reason) == (b.side, b.entry_ts, b.exit_ts, b.exit_reason)
        assert a.pnl_gbp == pytest.approx(b.pnl_gbp)
    assert res_b.equity[-1][1] == pytest.approx(res_e.equity[-1][1])


def test_open_risk_limit_caps_the_whole_basket():
    s = STRATEGIES["breakout"]
    legs = [leg(c) for c in ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "NZD_USD")]
    res = basket.run(legs, s, {}, start_balance=200.0, mode="cfd", direction="both", risk=RiskSettings(1.0, 50.0, 90.0),
                     max_open_risk_pct=2.0)
    assert any("Open-risk limit" in k for k in res.skipped)
    # Replay: at no time did open trades risk more than 2% of the account (plus rounding).
    events = sorted([(t.entry_ts, 1, t) for t in res.trades] + [(t.exit_ts, 0, t) for t in res.trades], key=lambda e: (e[0], e[1]))
    open_risk, worst = 0.0, 0.0
    for _ts, kind, t in events:
        open_risk += t.risk_gbp if kind else -t.risk_gbp
        worst = max(worst, open_risk)
    assert worst <= 0.02 * max(v for _, v in res.equity) + 0.05
    assert {getattr(t, "symbol") for t in res.trades} <= {lg.code for lg in legs}
    assert sum(len(v) for v in res.by_market.values()) == len(res.trades)


def test_basket_api(signed_in):
    r = signed_in.post("/api/backtests/basket", json={"markets": ["EUR_USD", "GBP_USD", "XAU_USD"], "timeframe": "1d",
                                                        "strategy": "breakout"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["markets"]) == 3 and d["metrics"]["trades"] == sum(m["basketTrades"] for m in d["markets"])
    assert d["warnings"][0]["text"].startswith("Sample data")
    assert "markets together" in d["headline"] and d["buyHoldEquity"]
    assert signed_in.post("/api/backtests/basket", json={"markets": ["EUR_USD"]}).status_code == 400
