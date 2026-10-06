"""Paper price orders: placed from the chart, filled by the worker when the price reaches the level,
always through the same safeguards as a trade you place yourself."""

from datetime import datetime, timedelta, timezone

import pytest

from app.market.providers.base import Bar
from app.paper import orders
from tests.test_paper import MINUTE, NOW, FakeMarket, accounts  # noqa: F401  (fixture helpers)
from app.paper import service as paper


@pytest.fixture()
def market(monkeypatch):
    m = FakeMarket()
    monkeypatch.setattr(paper, "latest_quote", m.quote)
    return m


def place(client, account_id, **kw):
    body = {"account_id": account_id, "symbol": "GBP_USD", "side": "long", "level": 1.2600, "stop": 1.2550,
            "target": 1.2700, "timeframe": "1h", "trend": "up", "reason": "Break above last week's high",
            "mood": "calm", "confirmed": True, "expiry": "gtc"}
    body.update(kw)
    return client.post("/api/paper/price-orders", json=body)


def work():
    from app.db import new_session

    db = new_session()
    try:
        return orders.work(db, {}, {"oanda": 0, "twelvedata": 0})
    finally:
        db.close()


def bar(ts, o, h, low, c):
    return Bar(ts, o, h, low, c, 0)


def test_the_kind_follows_where_the_level_is(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    assert place(signed_in, cfd).json()["kind"] == "Buy stop"  # above 1.25: buy the breakout
    assert place(signed_in, cfd, level=1.2400, stop=1.2350, target=None).json()["kind"] == "Buy limit"  # a dip
    assert place(signed_in, cfd, side="short", level=1.2600, stop=1.2650, target=1.2500, trend="down").json()["kind"] == "Sell limit"
    assert place(signed_in, cfd, side="short", level=1.2400, stop=1.2450, target=None, trend="down").json()["kind"] == "Sell stop"
    listed = signed_in.get(f"/api/paper/price-orders?account_id={cfd}").json()["waiting"]
    assert len(listed) == 4 and all(o["status"] == "waiting" for o in listed)


def test_orders_are_checked_before_they_wait(signed_in, market):
    accs = accounts(signed_in)
    cfd, cash = accs["cfd"]["id"], accs["cash"]["id"]
    assert "below the order's price" in place(signed_in, cfd, stop=1.2650).json()["detail"]
    assert "current price" in place(signed_in, cfd, level=1.2500, stop=1.2450).json()["detail"]
    assert "only buy" in place(signed_in, cash, side="short", level=1.24, stop=1.245, target=None).json()["detail"]
    assert "checklist" in place(signed_in, cfd, confirmed=False).json()["detail"].lower()
    assert "wrong side" in place(signed_in, cfd, target=1.2580).json()["detail"]


def test_a_buy_stop_fills_at_its_level_when_a_candle_reaches_it(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    o = place(signed_in, cfd).json()
    market.bars = [bar(NOW, 1.2500, 1.2620, 1.2490, 1.2610)]
    market.mid = 1.2610
    assert work()["filled"] == 1
    done = signed_in.get(f"/api/paper/price-orders?account_id={cfd}&done=true").json()
    assert done["waiting"] == [] and done["finished"][0]["status"] == "filled"
    tid = done["finished"][0]["tradeId"]
    detail = signed_in.get(f"/api/paper/accounts/{cfd}").json()
    t = next(x for x in detail["open"] if x["id"] == tid)
    assert t["entryMid"] == 1.26 and t["entryQuoteTs"] == NOW  # the level, not the later price
    assert t["riskGbp"] == pytest.approx(2.0, abs=0.02)  # 1% of £200, sized when it filled
    assert t["source"] == "manual" and t["reason"] == o["reason"]
    ev = signed_in.get(f"/api/paper/trades/{tid}/events").json()["events"]
    assert "Buy stop order reached 1.26" in ev[0]["detail"]


def test_a_gap_past_the_level_fills_at_the_open(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    place(signed_in, cfd, level=1.2400, stop=1.2300, target=None)  # buy limit: a better price for a gap down
    market.bars = [bar(NOW, 1.2380, 1.2390, 1.2370, 1.2385)]
    market.mid = 1.2385
    assert work()["filled"] == 1
    t = signed_in.get(f"/api/paper/accounts/{cfd}").json()["open"][0]
    assert t["entryMid"] == 1.238


def test_waits_until_reached_and_never_rechecks_a_finished_candle(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    place(signed_in, cfd)
    market.bars = [bar(NOW - MINUTE, 1.2500, 1.2590, 1.2490, 1.2550)]
    market.mid = 1.2550
    assert work()["filled"] == 0
    assert signed_in.get(f"/api/paper/price-orders?account_id={cfd}").json()["waiting"][0]["status"] == "waiting"


def test_a_safeguard_refusing_it_fails_the_order_and_trades_nothing(signed_in, market):
    from app.db import new_session
    from app.models import PaperAccount

    cfd = accounts(signed_in)["cfd"]["id"]
    place(signed_in, cfd)
    db = new_session()
    acct = db.get(PaperAccount, cfd)
    acct.halted, acct.halt_reason = True, "Paused: the account fell 20% from its high."
    db.commit()
    db.close()
    market.bars = [bar(NOW, 1.2500, 1.2620, 1.2490, 1.2610)]
    assert work()["failed"] == 1
    o = signed_in.get(f"/api/paper/price-orders?account_id={cfd}&done=true").json()["finished"][0]
    assert o["status"] == "failed" and "Paused" in o["message"] and o["tradeId"] is None
    assert signed_in.get(f"/api/paper/accounts/{cfd}").json()["open"] == []


def test_a_jump_past_the_stop_as_well_is_not_traded(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    place(signed_in, cfd, level=1.2400, stop=1.2350, target=None)
    market.bars = [bar(NOW, 1.2300, 1.2320, 1.2290, 1.2310)]  # opened below the stop
    market.mid = 1.2310
    assert work()["failed"] == 1
    o = signed_in.get(f"/api/paper/price-orders?account_id={cfd}&done=true").json()["finished"][0]
    assert "jumped past your stop-loss" in o["message"]


def test_closed_market_waits(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    place(signed_in, cfd)
    market.ts = NOW - 3 * 3600  # the last price is hours old: the market is shut
    market.bars = [bar(NOW - 3 * 3600, 1.2500, 1.2620, 1.2490, 1.2610)]
    assert work() == {"filled": 0, "failed": 0, "expired": 0}


def test_cancel_and_expiry(signed_in, market):
    from app.db import new_session
    from app.models import PriceOrder

    cfd = accounts(signed_in)["cfd"]["id"]
    a = place(signed_in, cfd).json()
    b = place(signed_in, cfd, level=1.2400, stop=1.2350, target=None).json()
    assert signed_in.post(f"/api/paper/price-orders/{a['id']}/cancel").json()["status"] == "cancelled"
    assert signed_in.post(f"/api/paper/price-orders/{a['id']}/cancel").status_code == 400
    db = new_session()
    db.get(PriceOrder, b["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()
    assert work()["expired"] == 1
    assert signed_in.get(f"/api/paper/price-orders?account_id={cfd}").json()["waiting"] == []


def test_expiry_times():
    uk = paper.UK
    tue_morning = datetime(2026, 10, 6, 9, 0, tzinfo=uk)
    assert orders.expiry_time("gtc", tue_morning) is None
    assert orders.expiry_time("day", tue_morning).astimezone(uk) == datetime(2026, 10, 6, 22, 0, tzinfo=uk)
    assert orders.expiry_time("week", tue_morning).astimezone(uk) == datetime(2026, 10, 9, 22, 0, tzinfo=uk)
    fri_late = datetime(2026, 10, 9, 23, 0, tzinfo=uk)
    assert orders.expiry_time("day", fri_late).astimezone(uk) == datetime(2026, 10, 12, 22, 0, tzinfo=uk)  # Monday
    assert orders.expiry_time("week", fri_late).astimezone(uk) == datetime(2026, 10, 16, 22, 0, tzinfo=uk)
    with pytest.raises(orders.OrderError):
        orders.expiry_time("someday", tue_morning)


def test_kind_labels():
    assert orders.kind_label(1, 1) == "Buy stop" and orders.kind_label(1, -1) == "Buy limit"
    assert orders.kind_label(-1, -1) == "Sell stop" and orders.kind_label(-1, 1) == "Sell limit"


def test_at_the_open_waits_for_the_market_and_fills_at_the_opening_price(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    # While the market is open, "at the open" is refused.
    assert "market is open" in place(signed_in, cfd, at_open=True, level=1.25, stop=1.2450).json()["detail"]
    # Closed: the last price is hours old.
    market.ts = NOW - 3 * 3600
    market.bars = [bar(NOW - 3 * 3600, 1.2500, 1.2500, 1.2500, 1.2500)]
    o = place(signed_in, cfd, at_open=True, level=1.25, stop=1.2450, target=None).json()
    assert o["kind"] == "Buy at the open" and o["direction"] == "open"
    assert work()["filled"] == 0  # still closed
    # It opens 0.0030 higher: filled at that opening price, sized then.
    market.ts = NOW
    market.bars = [bar(NOW - MINUTE, 1.2530, 1.2540, 1.2525, 1.2535)]
    market.mid = 1.2535
    assert work()["filled"] == 1
    t = signed_in.get(f"/api/paper/accounts/{cfd}").json()["open"][0]
    assert t["entryMid"] == 1.253 and t["riskGbp"] == pytest.approx(2.0, abs=0.02)


def test_at_the_open_gap_past_the_stop_is_not_traded(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    market.ts = NOW - 3 * 3600
    market.bars = [bar(NOW - 3 * 3600, 1.2500, 1.2500, 1.2500, 1.2500)]
    place(signed_in, cfd, at_open=True, level=1.25, stop=1.2450, target=None)
    market.ts = NOW
    market.bars = [bar(NOW - MINUTE, 1.2400, 1.2410, 1.2390, 1.2405)]
    market.mid = 1.2405
    assert work()["failed"] == 1
    o = signed_in.get(f"/api/paper/price-orders?account_id={cfd}&done=true").json()["finished"][0]
    assert "jumped past your stop-loss" in o["message"]
