"""Trailing stops on paper trades: follow the best price, never loosen, and a stop you set yourself cancels them
(only after you've confirmed the warning)."""

import pytest

from app.market.providers.base import Bar
from app.paper import service as paper
from tests.test_paper import MINUTE, NOW, FakeMarket, accounts, order


@pytest.fixture()
def market(monkeypatch):
    m = FakeMarket()
    m.bars = [Bar(NOW - 10 * MINUTE, 1.25, 1.25, 1.25, 1.25, 0)]  # trades open "ten minutes ago"; later candles are new
    monkeypatch.setattr(paper, "latest_quote", m.quote)
    return m


def check_all():
    from sqlalchemy import select

    from app.db import new_session
    from app.models import PaperAccount, PaperTrade

    db = new_session()
    try:
        for t in db.scalars(select(PaperTrade).where(PaperTrade.status == "open")).all():
            acct = db.get(PaperAccount, t.account_id)
            paper.check_trade(db, acct, t, paper.latest_quote(db, None))
        db.commit()
    finally:
        db.close()


def trade(client, tid, account_id):
    d = client.get(f"/api/paper/accounts/{account_id}").json()
    return next((t for t in d["open"] + d.get("closed", []) if t["id"] == tid), None)


def bars(*rows):
    """Finished 1-minute candles ending a minute ago: (open, high, low, close)."""
    n = len(rows)
    return [Bar(NOW - (n - i + 1) * MINUTE, o, h, low, c, 0) for i, (o, h, low, c) in enumerate(rows)]


def test_trailing_stop_follows_the_high_and_never_loosens(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    r = order(signed_in, cfd, stop=1.2400, target=None, trail_distance=0.0050)
    assert r.status_code == 200, r.text
    tid = r.json()["trade"]["id"]
    assert r.json()["trade"]["trailDistance"] == 0.005
    # The price climbs to 1.2580: the stop follows to 1.2530.
    market.bars = bars((1.2500, 1.2540, 1.2495, 1.2535), (1.2535, 1.2580, 1.2530, 1.2570))
    market.mid = 1.2570
    check_all()
    t = trade(signed_in, tid, cfd)
    assert t["status"] == "open" and t["stop"] == pytest.approx(1.2530)
    # A dip that stays above the stop: the stop stays where it is.
    market.bars = bars((1.2570, 1.2575, 1.2540, 1.2545))
    market.mid = 1.2545
    check_all()
    assert trade(signed_in, tid, cfd)["stop"] == pytest.approx(1.2530)
    # Then it falls through: closed by the trailing stop, in profit.
    market.bars = bars((1.2545, 1.2550, 1.2520, 1.2525))
    market.mid = 1.2525
    check_all()
    t = trade(signed_in, tid, cfd)
    assert t["status"] == "closed" and t["exitReason"] == "Trailing stop" and t["pnl"] > 0
    ev = signed_in.get(f"/api/paper/trades/{tid}/events").json()["events"]
    assert any(e["kind"] == "stop_trailed" for e in ev)


def test_short_trailing_stop_follows_the_low(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    tid = order(signed_in, cfd, side="short", stop=1.2600, target=None, trend="down", trail_distance=0.004).json()["trade"]["id"]
    market.bars = bars((1.2500, 1.2505, 1.2420, 1.2430))
    market.mid = 1.2430
    check_all()
    assert trade(signed_in, tid, cfd)["stop"] == pytest.approx(1.2460)


def test_setting_the_stop_yourself_warns_then_cancels_the_trailing_stop(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    tid = order(signed_in, cfd, stop=1.2400, target=None, trail_distance=0.005).json()["trade"]["id"]
    r = signed_in.patch(f"/api/paper/trades/{tid}", json={"stop": 1.2450})
    assert r.status_code == 409 and "cancel the trailing stop" in r.json()["detail"]
    assert trade(signed_in, tid, cfd)["trailDistance"] == 0.005  # nothing changed
    r = signed_in.patch(f"/api/paper/trades/{tid}", json={"stop": 1.2450, "cancel_trail": True})
    assert r.status_code == 200, r.text
    assert r.json()["trade"]["trailDistance"] is None and r.json()["trade"]["stop"] == 1.245
    # From now on the stop stays put as the price rises.
    market.bars = bars((1.2500, 1.2600, 1.2495, 1.2590))
    market.mid = 1.2590
    check_all()
    assert trade(signed_in, tid, cfd)["stop"] == pytest.approx(1.2450)
    kinds = [e["kind"] for e in signed_in.get(f"/api/paper/trades/{tid}/events").json()["events"]]
    assert "trail_off" in kinds


def test_switching_trailing_on_later_starts_from_the_current_price(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    tid = order(signed_in, cfd, stop=1.2400, target=None).json()["trade"]["id"]
    market.mid = 1.2600
    r = signed_in.post(f"/api/paper/trades/{tid}/trailing", json={"distance": 0.0050})
    assert r.status_code == 200, r.text
    assert r.json()["trade"]["stop"] == pytest.approx(1.2550)  # tightened at once to 0.0050 behind 1.2600
    # A wider distance never loosens the stop.
    off = signed_in.post(f"/api/paper/trades/{tid}/trailing", json={"distance": None}).json()["trade"]
    assert off["trailDistance"] is None and off["stop"] == pytest.approx(1.2550)
    wide = signed_in.post(f"/api/paper/trades/{tid}/trailing", json={"distance": 0.02}).json()["trade"]
    assert wide["stop"] == pytest.approx(1.2550)


def test_trailing_distance_is_checked(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    assert "more than half the price" in order(signed_in, cfd, trail_distance=0.9).json()["detail"]


def test_price_order_passes_its_trailing_stop_to_the_trade(signed_in, market):
    from tests.test_price_orders import place, work

    cfd = accounts(signed_in)["cfd"]["id"]
    o = place(signed_in, cfd, trail_distance=0.004).json()
    assert o["trailDistance"] == 0.004
    market.bars = [Bar(NOW, 1.2500, 1.2620, 1.2490, 1.2610, 0)]
    market.mid = 1.2610
    assert work()["filled"] == 1
    t = signed_in.get(f"/api/paper/accounts/{cfd}").json()["open"][0]
    assert t["trailDistance"] == 0.004
