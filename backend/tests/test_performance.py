"""The performance dashboard: figures from closed trades, the balance curve, and habit feedback."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import PaperAccount, PaperTrade

NOW = datetime.now(timezone.utc)


def _trade(acct_id, pnl, risk=2.0, hours_ago=1, source="manual", flags=None, lesson="", exit_reason="Stop-loss",
           target=None, entry=1.0, stop=0.99, opened_hours=2, symbol="EUR_USD", run_id=None):
    closed = NOW - timedelta(hours=hours_ago)
    return PaperTrade(
        account_id=acct_id, symbol=symbol, timeframe="1h", side=1, status="closed", units=100, entry_price=entry,
        entry_mid=entry, entry_quote_ts=0, entry_time=closed - timedelta(hours=opened_hours), entry_rate=1.0,
        entry_fees=0.0, stop=stop, initial_stop=stop, target=target, risk_gbp=risk, exit_price=entry, exit_mid=entry,
        exit_quote_ts=0, exit_time=closed, exit_reason=exit_reason, pnl_gbp=pnl, costs_gbp=0.1, last_checked_ts=0,
        source=source, strategy="breakout" if source == "auto" else "", trend="up", reason="test", mood="",
        notes="", lesson=lesson, rule_flags=flags or [], rule_score=100 - 25 * len(flags or []), auto_run_id=run_id,
    )


@pytest.fixture()
def account(signed_in):
    from app.db import new_session

    signed_in.get("/api/paper/accounts")  # creates the starter accounts
    db = new_session()
    acct = db.query(PaperAccount).filter(PaperAccount.mode == "cfd").first()
    yield db, acct
    db.close()


def _perf(client, acct_id):
    r = client.get(f"/api/paper/accounts/{acct_id}/performance")
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_account(signed_in, account):
    _db, acct = account
    p = _perf(signed_in, acct.id)
    assert p["all"]["trades"] == 0 and p["curve"][0]["value"] == 200
    assert p["feedback"][0]["title"] == "Early days"


def test_figures_and_curve(signed_in, account):
    db, acct = account
    for i, pnl in enumerate([4.0, -2.0, -2.0, 6.0]):
        db.add(_trade(acct.id, pnl, hours_ago=40 - i * 8, lesson="ok"))
    acct.cash += 6.0
    db.commit()
    p = _perf(signed_in, acct.id)
    a = p["all"]
    assert a["trades"] == 4 and a["winRate"] == 50.0 and a["net"] == 6.0
    assert a["avgWin"] == 5.0 and a["avgLoss"] == -2.0 and a["payoff"] == 2.5 and a["expectancy"] == 1.5
    assert a["avgR"] == pytest.approx(0.75) and a["longestLosingRun"] == 2
    values = [pt["value"] for pt in p["curve"]]
    assert values[:5] == [200, 204, 202, 200, 206]
    assert p["maxDrawdownPct"] == pytest.approx(2.0, abs=0.05)  # 204 down to 200 (1.96%, shown to 1 place)
    assert [pt["time"] for pt in p["curve"]] == sorted(pt["time"] for pt in p["curve"])


def test_habit_feedback(signed_in, account):
    db, acct = account
    # losses three times the wins, a widened stop, a revenge trade, winners cut short, no lessons
    for i in range(6):
        db.add(_trade(acct.id, -6.0, hours_ago=100 - i * 10))
    for i in range(5):
        db.add(_trade(acct.id, 0.5, hours_ago=95 - i * 10, exit_reason="Closed by you", target=1.03))
    db.add(_trade(acct.id, -6.0, hours_ago=5, flags=["Moved the stop-loss further away"]))
    db.add(_trade(acct.id, -2.0, hours_ago=3, flags=["Opened within 30 minutes of a losing trade"]))
    db.commit()
    titles = [f["title"] for f in _perf(signed_in, acct.id)["feedback"]]
    assert titles[0] in ("Losses much bigger than wins", "Stops moved further away")
    for expected in ("Losses much bigger than wins", "Stops moved further away", "Trading straight after a loss",
                     "Winners closed early", "Journal gaps"):
        assert expected in titles, (expected, titles)
    assert any(t.startswith("Rule score") for t in titles)


def test_clean_record_and_breakdown(signed_in, account):
    db, acct = account
    for i in range(12):
        db.add(_trade(acct.id, 3.0 if i % 2 else -2.0, hours_ago=200 - i * 12, lesson="fine",
                      source="auto" if i < 6 else "manual"))
    db.commit()
    p = _perf(signed_in, acct.id)
    assert p["feedback"][-1]["title"] in ("No bad habits spotted", "Rule score 100")
    labels = {b["label"] for b in p["breakdown"]}
    assert labels == {"Your own trades", "Breakout"}
    assert p["manual"]["trades"] == 6 and p["auto"]["trades"] == 6


def test_coach_export(signed_in, account):
    db, acct = account
    db.add(_trade(acct.id, 3.0, lesson="Waited | for the close"))
    db.commit()
    text = signed_in.get(f"/api/paper/accounts/{acct.id}/coach-export").json()["text"]
    assert text.startswith("# GandyTrade paper account") and "Last 20 closed trades" in text
    assert "Waited / for the close" in text  # table-safe
    assert "token" not in text.lower()


def test_other_users_account_is_private(signed_in):
    assert signed_in.get("/api/paper/accounts/9999/performance").status_code == 404
