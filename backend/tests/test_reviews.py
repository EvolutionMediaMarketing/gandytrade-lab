"""Weekly review: which week is under review, the week's facts, saving answers, history and the reminder."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import reviews
from app.models import Alert, PaperAccount, User, WeeklyReview
from test_performance import _trade

UK = ZoneInfo("Europe/London")


def test_which_week_is_under_review():
    assert reviews.week_start(date(2026, 10, 9)) == date(2026, 10, 5)  # Friday: this week
    assert reviews.week_start(date(2026, 10, 11)) == date(2026, 10, 5)  # Sunday: this week
    assert reviews.week_start(date(2026, 10, 12)) == date(2026, 10, 5)  # Monday: still last week
    assert reviews.week_start(date(2026, 10, 15)) == date(2026, 10, 5)  # Thursday: still last week
    assert reviews.week_start(date(2026, 10, 16)) == date(2026, 10, 12)  # Friday: the new week


@pytest.fixture()
def db_user(signed_in):
    from app.db import new_session

    signed_in.get("/api/paper/accounts")
    db = new_session()
    user = db.query(User).first()
    acct = db.query(PaperAccount).filter(PaperAccount.mode == "cfd").first()
    yield db, user, acct
    db.close()


def test_facts_cover_only_the_week(signed_in, db_user):
    db, user, acct = db_user
    monday = reviews.week_start(datetime.now(UK).date())
    in_week = datetime.combine(monday + timedelta(days=2), datetime.min.time(), tzinfo=UK)
    hours_ago = lambda d: (datetime.now(UK) - d).total_seconds() / 3600  # noqa: E731
    db.add(_trade(acct.id, 5.0, hours_ago=hours_ago(in_week + timedelta(hours=10)), lesson="Patience"))
    db.add(_trade(acct.id, -2.0, hours_ago=hours_ago(in_week + timedelta(hours=12)),
                  flags=["Moved the stop-loss further away"]))
    db.add(_trade(acct.id, 9.0, hours_ago=hours_ago(in_week - timedelta(days=9))))  # the week before
    db.commit()
    f = reviews.facts(db, user, monday)
    assert f["closed"] == 2 and f["net"] == 3.0
    assert f["best"]["pnl"] == 5.0 and f["best"]["lesson"] == "Patience"
    assert f["worst"]["pnl"] == -2.0
    assert len(f["broken"]) == 1 and f["ruleScore"] == round((100 + 75) / 2)
    assert f["accounts"][0]["name"] == acct.name


def test_save_complete_history_and_next_week(signed_in, db_user):
    r = signed_in.get("/api/reviews/current").json()
    week = r["week"]
    assert not r["completed"] and r["previousFocus"] is None
    bad = signed_in.put(f"/api/reviews/{week}", json={"answers": {}, "focus": "", "complete": True})
    assert bad.status_code == 400 and "focus" in bad.json()["detail"]
    draft = signed_in.put(f"/api/reviews/{week}", json={"answers": {"best": "Waited for the close"}, "focus": "", "complete": False}).json()
    assert draft["answers"]["best"] == "Waited for the close" and not draft["completed"]
    assert signed_in.put(f"/api/reviews/{week}", json={"answers": {"stuck": "maybe"}, "complete": False}).status_code == 400
    done = signed_in.put(f"/api/reviews/{week}", json={"answers": {"best": "Waited for the close"},
                                                       "focus": "No trades in the first 15 minutes after a loss",
                                                       "complete": True}).json()
    assert done["completed"] and done["facts"]["week"] == week
    hist = signed_in.get("/api/reviews").json()["reviews"]
    assert hist[0]["focus"].startswith("No trades") and hist[0]["stuck"] is None
    # Next week asks about this focus.
    next_monday = date.fromisoformat(week) + timedelta(days=7)
    nxt = reviews.current(db_user[0], db_user[1], next_monday + timedelta(days=4))
    assert nxt["previousFocus"]["focus"].startswith("No trades")
    text = signed_in.get(f"/api/reviews/{week}/coach").json()["text"]
    assert "Focus for next week: No trades" in text and "What went well: Waited for the close" in text
    assert signed_in.put("/api/reviews/2026-10-06", json={"answers": {}, "complete": False}).status_code == 404  # not a Monday
    future = (date.fromisoformat(week) + timedelta(days=21)).isoformat()
    assert signed_in.put(f"/api/reviews/{future}", json={"answers": {}, "complete": False}).status_code == 400


def test_sunday_reminder_once(signed_in, db_user):
    db, user, _acct = db_user
    sunday_evening = datetime(2026, 10, 11, 18, 0, tzinfo=UK)
    assert reviews.remind(db, datetime(2026, 10, 11, 12, 0, tzinfo=UK)) == 0  # too early
    assert reviews.remind(db, datetime(2026, 10, 10, 18, 0, tzinfo=UK)) == 0  # Saturday
    assert reviews.remind(db, sunday_evening) == 1
    assert reviews.remind(db, sunday_evening + timedelta(hours=1)) == 0  # once a week
    alert = db.query(Alert).order_by(Alert.id.desc()).first()
    assert alert.kind == "reviews" and "weekly review" in alert.text
    # A completed review gets no reminder.
    row = db.query(WeeklyReview).filter(WeeklyReview.week == "2026-10-12").first()
    assert row is None
    db.add(WeeklyReview(user_id=user.id, week="2026-10-12", answers={}, facts={}, focus="x",
                        completed_at=datetime.now(UK)))
    db.commit()
    assert reviews.remind(db, datetime(2026, 10, 18, 18, 0, tzinfo=UK)) == 0
