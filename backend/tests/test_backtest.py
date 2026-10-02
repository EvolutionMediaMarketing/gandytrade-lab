"""The backtester: fills, stops, costs, risk limits and no look-ahead, checked on hand-made prices."""

import pandas as pd
import pytest

from app.backtest import engine
from app.backtest.costs import Costs, default_costs
from app.market.fx import Converter
from app.market.providers.base import Bar
from app.market.providers import sample
from app.market.symbols import get_symbol
from app.market.timeframes import get_timeframe
from app.risk.guard import RiskSettings, leverage_cap
from app.strategies.base import Rules, Side, Strategy
from app.strategies.library import STRATEGIES

DAY = 86400
T0 = 1_700_006_400  # a midnight UTC
GBP = Converter("GBP")
FREE = Costs(0, 0)


def bars_from(rows):
    """rows of (open, high, low, close), one per day."""
    return [Bar(T0 + i * DAY, o, h, lo, c, 0) for i, (o, h, lo, c) in enumerate(rows)]


def scripted(enter_at: dict[int, float], exit_on: set[int] = frozenset(), side: int = 1) -> Strategy:
    """A test strategy: enter after candle i with the given stop; exit after the listed candles."""

    def compute(df: pd.DataFrame, _p: dict) -> Rules:
        n = len(df)
        go = pd.Series([i in enter_at for i in range(n)])
        stop = pd.Series([enter_at.get(i, float("nan")) for i in range(n)])
        leave = pd.Series([i in exit_on for i in range(n)])
        s = Side({"scripted": go}, leave, stop, exit_label="Exit rule")
        return Rules(s, None) if side > 0 else Rules(Side({"never": pd.Series([False] * n)}, leave, stop), s)

    return Strategy("t", "Test", "", [], "", "", "", [], compute)


def settings(**kw):
    base = dict(start_balance=1000.0, mode="cfd", direction="both", risk=RiskSettings(1.0, 3.0, 20.0),
                leverage=30.0, costs=FREE)
    base.update(kw)
    return engine.Settings(**base)


FLAT = [(100, 101, 99, 100)] * 3


def test_enters_at_next_open_and_sizes_to_one_percent_risk():
    bars = bars_from(FLAT + [(102, 106, 101, 105), (105, 111, 104, 110), (112, 113, 108, 109)])
    r = engine.run(bars, scripted({2: 95.0}, {4}), {}, settings(), GBP)
    t = r.trades[0]
    assert t.entry_i == 3 and t.entry_price == 102  # next open, not the signal candle's close
    assert t.units == pytest.approx(10 / (102 - 95))  # £10 risk (1% of £1,000) / 7 per unit
    assert t.exit_i == 5 and t.exit_price == 112  # exit decided at candle 4's close, filled at 5's open
    assert t.pnl_gbp == pytest.approx((112 - 102) * t.units)
    assert r.equity[-1][1] == pytest.approx(1000 + t.pnl_gbp)


def test_stop_loss_fills_at_the_stop():
    bars = bars_from(FLAT + [(100, 101, 94, 96), (96, 97, 95, 96)])
    t = engine.run(bars, scripted({2: 95.0}), {}, settings(), GBP).trades[0]
    assert t.exit_reason == "Stop-loss" and t.exit_price == 95 and t.exit_i == 3
    assert t.pnl_gbp == pytest.approx(-10.0)  # exactly the 1% risked


def test_gap_through_stop_fills_at_the_open():
    bars = bars_from(FLAT + [(100, 101, 99, 100), (90, 92, 88, 91)])
    t = engine.run(bars, scripted({2: 95.0}), {}, settings(), GBP).trades[0]
    assert t.exit_reason.startswith("Stop-loss (gapped") and t.exit_price == 90
    assert t.pnl_gbp == pytest.approx(-20.0)  # gaps can lose more than planned; the report shows it


def test_entry_cancelled_if_price_opens_past_the_stop():
    bars = bars_from(FLAT + [(94, 95, 93, 94), (94, 95, 93, 94)])
    r = engine.run(bars, scripted({2: 95.0}), {}, settings(), GBP)
    assert r.trades == [] and sum(r.skipped.values()) == 1


def test_short_trade():
    bars = bars_from(FLAT + [(100, 101, 97, 98), (95, 96, 94, 95), (95, 96, 94, 95)])
    r = engine.run(bars, scripted({2: 105.0}, {4}, side=-1), {}, settings(), GBP)
    t = r.trades[0]
    assert t.side == -1 and t.units == pytest.approx(10 / 5)
    assert t.pnl_gbp == pytest.approx((100 - 95) * 2)


def test_no_shorts_in_cash_mode():
    bars = bars_from(FLAT + [(100, 101, 97, 98), (95, 96, 94, 95)])
    r = engine.run(bars, scripted({2: 105.0}, side=-1), {}, settings(mode="cash", direction="long", leverage=1), GBP)
    assert r.trades == []


def test_costs_spread_slippage_commission_and_stamp_duty():
    c = Costs(spread_pct=0.2, slippage_pct=0.1, commission_gbp=1.0, stamp_duty_pct=0.5)
    bars = bars_from(FLAT + [(100, 101, 99, 100), (110, 111, 109, 110), (110, 111, 109, 110)])
    t = engine.run(bars, scripted({2: 90.0}, {4}), {}, settings(costs=c, mode="cash", leverage=1, direction="long"), GBP).trades[0]
    buy = 100 * (1 + 0.001 + 0.001)  # half the spread + slippage
    sell = 110 * (1 - 0.001 - 0.001)
    assert t.entry_price == pytest.approx(buy) and t.exit_price == pytest.approx(sell)
    stamp = t.units * buy * 0.005
    assert t.pnl_gbp == pytest.approx((sell - buy) * t.units - 1.0 - 1.0 - stamp)
    assert t.gross_gbp == pytest.approx((110 - 100) * t.units)
    assert t.costs_gbp == pytest.approx(t.gross_gbp - t.pnl_gbp)


def test_overnight_financing_in_cfd_mode():
    c = Costs(0, 0, financing_pct_year=365.0)  # 1% a night, to make it easy to check
    bars = bars_from(FLAT + [(100, 101, 99, 100)] * 4)
    t = engine.run(bars, scripted({2: 90.0}, {5}), {}, settings(costs=c), GBP).trades[0]
    nights = t.exit_i - t.entry_i
    assert t.pnl_gbp == pytest.approx(-(t.units * 100) * 0.01 * nights)


def test_leverage_cap_reduces_size():
    bars = bars_from(FLAT + [(100, 101, 99.9, 100)] * 2)
    t = engine.run(bars, scripted({2: 99.95}), {}, settings(mode="cash", leverage=1, direction="long"), GBP).trades[0]
    assert t.units == pytest.approx(1000 / 100)  # can't buy more than the balance
    assert t.note == "Leverage-capped"


def test_pence_are_converted_to_pounds():
    gbx = Converter("GBX", fixed=100.0)
    bars = bars_from(FLAT + [(100, 101, 99, 100), (110, 111, 109, 110), (110, 111, 109, 110)])
    t = engine.run(bars, scripted({2: 90.0}, {4}), {}, settings(), gbx).trades[0]
    assert t.units == pytest.approx(10 / (10 / 100))  # 10p stop distance = £0.10 per share
    assert t.pnl_gbp == pytest.approx(10.0)  # 10p rise × 100 shares = £10


def test_drawdown_limit_stops_trading():
    rows = FLAT[:]
    entries = {}
    for k in range(40):  # lose 1% again and again
        i = len(rows) - 1
        entries[i] = 95.0
        rows += [(100, 101, 94, 96), (100, 101, 99, 100)]
    r = engine.run(bars_from(rows), scripted(entries), {}, settings(risk=RiskSettings(1.0, 50.0, 20.0)), GBP)
    assert "drawdown limit" in r.halted
    final = r.equity[-1][1]
    assert 780 <= final <= 820 and len(r.trades) < 40


def test_daily_loss_limit_blocks_new_trades():
    # Hourly candles within one day: three 1% losses hit a 2.5% daily limit.
    rows = [(100, 101, 99, 100)]
    entries = {}
    for k in range(5):
        entries[len(rows) - 1] = 95.0
        rows += [(100, 101, 94, 96), (100, 101, 99, 100)]
    bars = [Bar(T0 + i * 3600, o, h, lo, c, 0) for i, (o, h, lo, c) in enumerate(rows)]
    r = engine.run(bars, scripted(entries), {}, settings(risk=RiskSettings(1.0, 2.5, 50.0)), GBP)
    assert len(r.trades) == 3
    assert any("Daily loss limit" in k for k in r.skipped)


def test_buy_and_hold():
    bars = bars_from([(100, 101, 99, 100), (100, 120, 100, 120), (120, 121, 119, 120)])
    r = engine.buy_and_hold(bars, settings(mode="cash", leverage=1), GBP)
    assert r.equity[-1][1] == pytest.approx(1200)


@pytest.mark.parametrize("key", [k for k in STRATEGIES if k != "buy_hold"])
def test_strategies_never_look_ahead(key):
    """Signals on candle i must be the same whether or not later candles exist."""
    sym = get_symbol("EUR_USD")
    strat = STRATEGIES[key]
    if strat.intraday_only:  # scalpers: ten days of 5-minute candles
        full = sample.generate(sym, get_timeframe("5m"), 3000, now=T0 + 900 * DAY)
        cut = 2000
    else:
        full = sample.generate(sym, get_timeframe("1d"), 800, now=T0 + 900 * DAY)
        cut = 600
    params = {"support": 1.0, "resistance": 1.2} if key == "support_resistance" else {}
    df_full = engine._frame(full)
    df_cut = engine._frame(full[:cut])
    a, b = strat.run(df_full, params), strat.run(df_cut, params)
    for side_full, side_cut in ((a.long, b.long), (a.short, b.short)):
        if side_full is None:
            continue
        pd.testing.assert_series_equal(side_full.entry().iloc[:cut], side_cut.entry(), check_names=False)
        pd.testing.assert_series_equal(side_full.exit.fillna(False).astype(bool).iloc[:cut],
                                       side_cut.exit.fillna(False).astype(bool), check_names=False)
        pd.testing.assert_series_equal(side_full.stop.iloc[:cut], side_cut.stop, check_names=False)
        if side_full.target is not None:
            pd.testing.assert_series_equal(side_full.target.iloc[:cut], side_cut.target, check_names=False)
        if strat.intraday_only:
            assert side_full.entry().any(), f"{key} never set up on 5-minute candles"


@pytest.mark.parametrize("key", [k for k in STRATEGIES if k not in ("buy_hold", "support_resistance")])
def test_every_strategy_trades_on_sample_data(key):
    sym = get_symbol("EUR_USD")
    tf = "5m" if STRATEGIES[key].intraday_only else "1d"
    bars = sample.generate(sym, get_timeframe(tf), 6000 if tf == "5m" else 2000, now=T0 + 3000 * DAY)
    s = settings(costs=default_costs("forex", "cfd"), leverage=leverage_cap("EUR_USD", "forex", "cfd"))
    r = engine.run(bars, STRATEGIES[key], {}, s, GBP)
    assert r.trades, key
    for t in r.trades:
        assert t.entry_i < t.exit_i or t.exit_reason.startswith(("Stop", "Target"))
        assert t.risk_gbp <= 1000 * 0.01 * 1.6  # never much more than ~1% at risk (account changes over time)


def test_leverage_caps():
    assert leverage_cap("EUR_USD", "forex", "cfd") == 30
    assert leverage_cap("USD_TRY", "forex", "cfd") == 20
    assert leverage_cap("XAG_USD", "metal", "cfd") == 10
    assert leverage_cap("AAPL", "stock", "cfd") == 5
    assert leverage_cap("AAPL", "stock", "cash") == 1


# --- API -------------------------------------------------------------------------------------

def test_backtest_api_runs_saves_and_lists(signed_in):
    body = {"symbol": "EUR_USD", "timeframe": "1d", "strategy": "ma_cross", "start_balance": 200}
    r = signed_in.post("/api/backtests", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sample"] is True and data["warnings"][0]["level"] == "stop"
    assert data["metrics"]["trades"] > 0 and data["buyHold"]["trades"] == 1
    assert data["assumptions"]["mode"] == "cfd" and data["assumptions"]["leverageCap"] == 30
    runs = signed_in.get("/api/backtests").json()["runs"]
    assert runs[0]["id"] == data["id"] and runs[0]["strategyName"] == "Moving-average crossover"
    assert signed_in.get(f"/api/backtests/{data['id']}").json()["headline"] == data["headline"]
    signed_in.delete(f"/api/backtests/{data['id']}")
    assert signed_in.get(f"/api/backtests/{data['id']}").status_code == 404


def test_backtest_api_validates(signed_in):
    assert signed_in.post("/api/backtests", json={"symbol": "EUR_USD", "strategy": "nope"}).status_code == 400
    assert signed_in.post("/api/backtests", json={"symbol": "EUR_USD", "risk_pct": 5}).status_code == 422
    assert signed_in.get("/api/strategies").json()["strategies"][0]["key"] == "buy_hold"


def test_shares_default_to_no_leverage(signed_in):
    data = signed_in.post("/api/backtests", json={"symbol": "AAPL", "strategy": "macd_momentum"}).json()
    assert data["assumptions"]["mode"] == "cash" and data["assumptions"]["leverageCap"] == 1
    assert data["assumptions"]["costs"]["fx_fee_pct"] == 0.15


def test_position_size_tool(signed_in):
    r = signed_in.post("/api/tools/position-size", json={"symbol": "TSCO.LON", "balance": 200, "risk_pct": 1, "entry": 380, "stop": 370})
    assert r.status_code == 200, r.text
    d = r.json()
    # £2 risk, 10p stop = £0.10 a share, so 20 shares worth £76
    assert d["units"] == pytest.approx(20) and d["riskGbp"] == pytest.approx(2.0) and d["valueGbp"] == pytest.approx(76.0)
    assert d["mode"] == "cash" and d["currency"] == "GBX"
    short = signed_in.post("/api/tools/position-size", json={"symbol": "AAPL", "balance": 200, "entry": 100, "stop": 105})
    assert short.status_code == 400  # can't short real shares
    capped = signed_in.post("/api/tools/position-size", json={"symbol": "TSCO.LON", "balance": 200, "entry": 380, "stop": 379.9}).json()
    assert capped["capped"] is True and capped["valueGbp"] <= 200.01


# --- Regressions found in the independent review ----------------------------------------------

def test_drawdown_is_the_largest_percentage_fall():
    from app.backtest.report import max_drawdown

    assert max_drawdown([(0, 100), (1, 50), (2, 1000), (3, 800)]) == (50.0, 200.0)


def test_reversal_on_the_same_candle_as_an_exit():
    """A long exit and a short entry on the same close: exit then go short at the next open."""
    def compute(df, _p):
        n = len(df)
        flags = lambda idx: pd.Series([i in idx for i in range(n)])
        long = Side({"go": flags({2})}, flags({4}), pd.Series([90.0] * n), exit_label="Exit rule")
        short = Side({"go": flags({4})}, flags({6}), pd.Series([110.0] * n), exit_label="Exit rule")
        return Rules(long, short)

    strat = Strategy("rev", "Reversal", "", [], "", "", "", [], compute)
    bars = bars_from([(100, 101, 99, 100)] * 9)
    r = engine.run(bars, strat, {}, settings(), GBP)
    assert [(t.side, t.entry_i, t.exit_i) for t in r.trades] == [(1, 3, 5), (-1, 5, 7)]


def test_no_new_trade_after_the_drawdown_halt():
    rows = FLAT + [(100, 101, 94, 96), (100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100)]
    entries = {2: 95.0, 3: 95.0, 4: 95.0, 5: 95.0}
    r = engine.run(bars_from(rows), scripted(entries), {}, settings(risk=RiskSettings(2.0, 50.0, 2.0)), GBP)
    assert r.halted and len(r.trades) == 1  # the 2% loss trips the 2% limit; nothing opens afterwards


def test_cash_buys_never_cost_more_than_the_balance():
    c = Costs(0, 0, fx_fee_pct=0.15, stamp_duty_pct=0.5)
    bars = bars_from(FLAT + [(100, 101, 99.95, 100)] * 2)
    s = settings(mode="cash", leverage=1, direction="long", costs=c)
    t = engine.run(bars, scripted({2: 99.99}), {}, s, GBP).trades[0]
    assert t.units * 100 + t.entry_fees_gbp <= 1000 + 1e-9


def test_no_financing_in_cash_mode_even_if_set():
    c = Costs(0, 0, financing_pct_year=365.0)
    bars = bars_from(FLAT + [(100, 101, 99, 100)] * 4)
    t = engine.run(bars, scripted({2: 90.0}, {5}), {}, settings(costs=c, mode="cash", leverage=1, direction="long"), GBP).trades[0]
    assert t.pnl_gbp == pytest.approx(0.0)


def test_quote_for_the_calculator(signed_in):
    d = signed_in.get("/api/tools/quote", params={"symbol": "NVDA"}).json()
    assert d["price"] > 0 and d["currency"] == "USD" and d["sample"] is True
    assert d["suggestedStopLong"] < d["price"] < d["suggestedStopShort"]
    assert signed_in.get("/api/tools/quote", params={"symbol": "NOPE"}).status_code == 400
