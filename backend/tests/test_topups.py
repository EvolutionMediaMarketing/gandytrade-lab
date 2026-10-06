"""Monthly top-ups and deposits: money paid in is never profit, and falls are measured on growth."""

from datetime import datetime, timedelta, timezone

import pytest

from app.paper import service as paper
from app.paper import topups
from tests.test_paper import FakeMarket, accounts, order

UK = paper.UK


@pytest.fixture()
def market(monkeypatch):
    m = FakeMarket()
    monkeypatch.setattr(paper, "latest_quote", m.quote)
    return m


def db_account(account_id):
    from app.db import new_session
    from app.models import PaperAccount

    db = new_session()
    return db, db.get(PaperAccount, account_id)


def test_adding_money_is_not_profit(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    r = signed_in.post(f"/api/paper/accounts/{cfd}/deposit", json={"amount": 50})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["equity"] == 250 and a["funded"] == 250 and a["profit"] == 0 and a["returnPct"] == 0
    assert a["depositHistory"][0]["amount"] == 50 and a["depositHistory"][0]["kind"] == "manual"
    assert signed_in.post(f"/api/paper/accounts/{cfd}/deposit", json={"amount": 0}).status_code == 422


def test_a_top_up_keeps_the_fall_measured_on_growth(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    db, acct = db_account(cfd)
    acct.cash, acct.peak_equity, acct.day_start_equity = 180.0, 200.0, 200.0  # 10% down, and down 10% today
    acct.day = datetime.now(UK).strftime("%Y-%m-%d")
    db.commit()
    topups.deposit(db, acct, 90.0)
    db.commit()
    assert acct.cash == 270.0
    assert (acct.peak_equity - 270.0) / acct.peak_equity == pytest.approx(0.10)  # still 10% down
    assert (acct.day_start_equity - 270.0) / acct.day_start_equity == pytest.approx(0.10)
    db.close()


def test_a_top_up_never_lifts_a_pause(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    db, acct = db_account(cfd)
    acct.cash, acct.peak_equity, acct.halted, acct.halt_reason = 150.0, 200.0, True, "Paused: fell 25%."
    db.commit()
    topups.deposit(db, acct, 100.0)
    db.commit()
    assert acct.halted
    db.close()
    assert "Paused" in order(signed_in, cfd).json()["detail"]


def test_monthly_top_up_on_its_day_once_a_month(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    # Set up on the 10th for the 15th: nothing until the 15th.
    oct10 = datetime(2026, 10, 10, 9, 0, tzinfo=UK)
    db, acct = db_account(cfd)
    topups.set_monthly(db, acct, 25.0, 15, now=oct10)
    db.commit()
    assert topups.next_topup(acct, oct10) == "2026-10-15"
    assert topups.run_due(db, oct10) == 0
    oct15 = datetime(2026, 10, 15, 0, 5, tzinfo=UK)
    assert topups.run_due(db, oct15) == 1
    assert topups.run_due(db, oct15 + timedelta(hours=3)) == 0  # once a month
    db.refresh(acct)
    assert acct.cash == 225.0 and acct.deposits == 25.0 and acct.topup_last_month == "2026-10"
    assert topups.next_topup(acct, oct15) == "2026-11-15"
    assert topups.run_due(db, datetime(2026, 11, 16, 8, 0, tzinfo=UK)) == 1  # a missed day is caught up
    db.refresh(acct)
    assert acct.cash == 250.0
    assert topups.next_topup(acct, datetime(2026, 12, 20, tzinfo=UK)) == "2026-12-20"  # December's is due now
    db.close()


def test_starting_after_this_months_day_waits_for_next_month(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    oct20 = datetime(2026, 10, 20, 9, 0, tzinfo=UK)
    db, acct = db_account(cfd)
    topups.set_monthly(db, acct, 25.0, 1, now=oct20)
    db.commit()
    assert topups.run_due(db, oct20) == 0
    assert topups.next_topup(acct, oct20) == "2026-11-01"
    assert topups.run_due(db, datetime(2026, 11, 1, 6, 0, tzinfo=UK)) == 1
    db.close()


def test_monthly_settings_through_the_api(signed_in, market):
    cfd = accounts(signed_in)["cfd"]["id"]
    r = signed_in.patch(f"/api/paper/accounts/{cfd}", json={"topup_amount": 30, "topup_day": 5})
    assert r.status_code == 200, r.text
    assert r.json()["topupAmount"] == 30 and r.json()["topupDay"] == 5 and r.json()["nextTopup"]
    assert signed_in.patch(f"/api/paper/accounts/{cfd}", json={"topup_day": 31}).status_code == 422
    off = signed_in.patch(f"/api/paper/accounts/{cfd}", json={"topup_amount": 0}).json()
    assert off["topupAmount"] == 0 and off["nextTopup"] is None


def test_dashboard_falls_ignore_deposits(signed_in, market):
    from app.models import PaperDeposit, PaperTrade
    from app.paper.performance import _curve

    db, acct = db_account(accounts(signed_in)["cfd"]["id"])
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    acct.created_at = t0

    def trade(day, pnl):
        return PaperTrade(exit_time=t0 + timedelta(days=day), pnl_gbp=pnl)

    deposits = [PaperDeposit(amount=200.0, at=t0 + timedelta(days=2))]
    acct.deposits = 200.0
    # £200 start, lose £20 (10%), then £200 arrives, then win £38 (+10% of £380).
    points, worst, current = _curve(acct, [trade(1, -20.0), trade(3, 38.0)], 418.0, deposits)
    assert worst == pytest.approx(10.0) and current == pytest.approx(1.0)
    assert [p["value"] for p in points][:4] == [200.0, 180.0, 380.0, 418.0]
    assert points[2]["deposit"] == 200.0
    db.close()
