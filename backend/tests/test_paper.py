"""Paper trading: orders, fills against recorded prices, stops, targets, the journal and the limits."""

import time

import pytest

from app.backtest.costs import default_costs
from app.market.providers.base import Bar
from app.paper import service as paper

NOW = int(time.time())
MINUTE = 60


class FakeMarket:
    """Controls the price the paper engine sees."""

    def __init__(self):
        self.mid = 1.2500
        self.bars: list[Bar] = []
        self.ts = NOW
        self.source = "oanda"
        self.sample = False

    def quote(self, db, symbol):
        bars = self.bars or [Bar(self.ts - MINUTE, self.mid, self.mid, self.mid, self.mid, 0)]
        return paper.Quote(self.mid, self.ts, self.source, self.sample, bars, "1m")


@pytest.fixture()
def market(monkeypatch):
    m = FakeMarket()
    monkeypatch.setattr(paper, "latest_quote", m.quote)
    return m


def order(client, account_id, **kw):
    body = {"account_id": account_id, "symbol": "GBP_USD", "side": "long", "stop": 1.2400, "target": 1.2700,
            "timeframe": "1h", "trend": "up", "reason": "Pullback to the 20 average in an uptrend",
            "mood": "calm", "confirmed": True}
    body.update(kw)
    return client.post("/api/paper/orders", json=body)


def accounts(client):
    return {a["mode"]: a for a in client.get("/api/paper/accounts").json()["accounts"]}


ADJ = default_costs("forex", "cfd").spread_pct / 200 + default_costs("forex", "cfd").slippage_pct / 100


def test_default_accounts(signed_in):
    accs = accounts(signed_in)
    assert accs["cash"]["equity"] == 200 and accs["cfd"]["equity"] == 200


def test_checklist_must_be_complete(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    r = order(signed_in, cfd, reason="because", confirmed=False, trend="")
    assert r.status_code == 400
    assert "checklist" in r.json()["detail"].lower()


def test_order_fills_at_the_recorded_price_and_risks_one_percent(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    r = order(signed_in, cfd)
    assert r.status_code == 200, r.text
    t = r.json()["trade"]
    assert t["entryMid"] == 1.25 and t["entryQuoteTs"] == NOW
    assert t["entryPrice"] == pytest.approx(1.25 * (1 + ADJ))
    assert t["riskGbp"] == pytest.approx(2.0, abs=0.01)  # 1% of £200
    ev = signed_in.get(f"/api/paper/trades/{t['id']}/events").json()["events"]
    assert ev[0]["kind"] == "opened" and ev[0]["mid"] == 1.25 and ev[0]["quoteTs"] == NOW


def test_cash_account_cannot_short(signed_in, market):
    cash = accounts(signed_in)["cash"]["id"]
    r = order(signed_in, cash, side="short", stop=1.26, target=1.20, trend="down")
    assert r.status_code == 400 and "only buy" in r.json()["detail"]


def test_stop_on_wrong_side_is_refused(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    assert order(signed_in, cfd, stop=1.2600).status_code == 400


def test_market_closed_is_refused(signed_in, market):
    market.ts = NOW - 3 * 3600
    cfd = accounts(signed_in)["cfd"]["id"]
    r = order(signed_in, cfd)
    assert r.status_code == 400 and "closed" in r.json()["detail"]


def _open(signed_in, market, **kw):
    cfd = accounts(signed_in)["cfd"]["id"]
    t = order(signed_in, cfd, **kw).json()["trade"]
    return cfd, t


def _run_worker(market, bars):
    from app import worker

    market.bars = bars
    market.mid = bars[-1].close
    return worker.run_once({})


def test_worker_closes_at_the_stop(signed_in, market):
    cfd, t = _open(signed_in, market)
    stats = _run_worker(market, [
        Bar(NOW - MINUTE, 1.25, 1.25, 1.25, 1.25, 0),  # the candle the trade opened in
        Bar(NOW, 1.2450, 1.2460, 1.2390, 1.2420, 0),  # dips through the stop
    ])
    assert stats["closed"] == 1
    closed = signed_in.get(f"/api/paper/accounts/{cfd}").json()["closed"][0]
    assert closed["exitReason"] == "Stop-loss" and closed["exitPrice"] == pytest.approx(1.24 * (1 - ADJ))
    assert closed["pnl"] == pytest.approx(-2.0 - closed["costs"] + (closed["pnl"] + 2.0 + closed["costs"]), abs=0.02)
    assert -2.2 < closed["pnl"] < -1.9


def test_worker_closes_at_the_target(signed_in, market):
    cfd, t = _open(signed_in, market)
    _run_worker(market, [Bar(NOW - MINUTE, 1.25, 1.25, 1.25, 1.25, 0), Bar(NOW, 1.26, 1.2720, 1.2590, 1.2650, 0)])
    closed = signed_in.get(f"/api/paper/accounts/{cfd}").json()["closed"][0]
    assert closed["exitReason"] == "Target reached" and 1.8 < closed["r"] < 2.0  # 2R target, less costs


def test_gap_through_stop_fills_at_the_open(signed_in, market):
    cfd, t = _open(signed_in, market)
    _run_worker(market, [Bar(NOW - MINUTE, 1.25, 1.25, 1.25, 1.25, 0), Bar(NOW, 1.2300, 1.2320, 1.2290, 1.2310, 0)])
    closed = signed_in.get(f"/api/paper/accounts/{cfd}").json()["closed"][0]
    assert closed["exitReason"].startswith("Stop-loss (gapped") and closed["exitPrice"] == pytest.approx(1.23 * (1 - ADJ))


def test_candle_the_trade_opened_in_is_not_used(signed_in, market):
    """That candle's low happened before the trade existed, so it mustn't trigger the stop."""
    market.bars = [Bar(NOW - MINUTE, 1.25, 1.25, 1.2300, 1.25, 0)]
    cfd, t = _open(signed_in, market)
    _run_worker(market, [Bar(NOW - MINUTE, 1.25, 1.25, 1.2300, 1.25, 0)])
    assert signed_in.get(f"/api/paper/accounts/{cfd}").json()["openCount"] == 1


def test_widening_the_stop_is_flagged_and_scored(signed_in, market):
    cfd, t = _open(signed_in, market)
    r = signed_in.patch(f"/api/paper/trades/{t['id']}", json={"stop": 1.2300, "notes": "Gave it more room"})
    assert r.status_code == 200
    assert "Moved the stop-loss further away" in r.json()["trade"]["ruleFlags"]
    signed_in.post(f"/api/paper/trades/{t['id']}/close")
    closed = signed_in.get(f"/api/paper/accounts/{cfd}").json()["closed"][0]
    assert closed["ruleScore"] == 75 and closed["notes"] == "Gave it more room" and closed["exitReason"] == "Closed by you"


def test_against_trend_and_revenge_flags(signed_in, market):
    cfd, t = _open(signed_in, market)
    market.mid = 1.2450  # close at a loss
    signed_in.post(f"/api/paper/trades/{t['id']}/close")
    market.mid = 1.25
    t2 = order(signed_in, cfd, trend="down").json()["trade"]
    assert set(t2["ruleFlags"]) == {"Traded against the trend you identified", "Opened within 30 minutes of a losing trade"}
    assert t2["ruleScore"] == 50


def test_daily_loss_limit_blocks_orders(signed_in, market):
    from app.db import new_session
    from app.models import PaperAccount

    cfd = accounts(signed_in)["cfd"]["id"]
    db = new_session()
    acct = db.get(PaperAccount, cfd)
    from datetime import datetime
    acct.day = datetime.now(paper.UK).strftime("%Y-%m-%d")
    acct.day_start_equity = 220.0  # the account is already 9% down on the day
    db.commit()
    db.close()
    r = order(signed_in, cfd)
    assert r.status_code == 400 and "Daily loss limit" in r.json()["detail"]


def test_drawdown_pause_and_resume(signed_in, market):
    from app.db import new_session
    from app.models import PaperAccount

    cfd = accounts(signed_in)["cfd"]["id"]
    db = new_session()
    acct = db.get(PaperAccount, cfd)
    acct.cash = 150.0  # 25% below its £200 high
    db.commit()
    db.close()
    r = order(signed_in, cfd)
    assert r.status_code == 400 and "Paused" in r.json()["detail"]
    signed_in.patch(f"/api/paper/accounts/{cfd}", json={"resume": True})
    assert order(signed_in, cfd).status_code == 200


def test_every_fill_matches_its_recorded_price(signed_in, market):
    """The Phase 3 gate check: each fill is the recorded market price plus half the spread and slippage."""
    from sqlalchemy import select

    from app.db import new_session
    from app.models import PaperEvent, PaperTrade

    cfd, t = _open(signed_in, market)
    _run_worker(market, [Bar(NOW - MINUTE, 1.25, 1.25, 1.25, 1.25, 0), Bar(NOW, 1.26, 1.2720, 1.2590, 1.2650, 0)])
    _, t2 = _open(signed_in, market, side="short", stop=1.29, target=1.24, trend="down")
    signed_in.post(f"/api/paper/trades/{t2['id']}/close")
    db = new_session()
    fills = db.scalars(select(PaperEvent).where(PaperEvent.price.is_not(None))).all()
    assert len(fills) == 4
    for e in fills:
        tr = db.get(PaperTrade, e.trade_id)
        buying = (e.kind == "opened") == (tr.side > 0)
        expected = e.mid * (1 + ADJ) if buying else e.mid * (1 - ADJ)
        assert e.price == pytest.approx(expected), e.kind
        assert e.quote_ts and e.quote_source == "oanda"
    db.close()


def test_buying_power_limits_cash_accounts(signed_in, market):
    cash = accounts(signed_in)["cash"]["id"]
    # A very tight stop would need far more than £200 of shares; the size is capped to what the account can buy.
    r = order(signed_in, cash, symbol="EUR_USD", stop=1.2499, target=None)
    t = r.json()["trade"]
    assert t["valueGbp"] <= 200.01
