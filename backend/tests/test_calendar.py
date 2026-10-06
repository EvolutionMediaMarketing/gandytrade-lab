"""Economic calendar: official dates turned into UTC times, matched to markets, and the event pause."""

from datetime import datetime, timedelta, timezone

import pytest

from app.market import calendar
from app.market.symbols import get_symbol
from tests.test_auto import _accounts, _start, _step, _trades, feed  # noqa: F401


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def when(key, day):
    return next(e.when for e in calendar.EVENTS if e.series.key == key and e.when.date().isoformat() == day)


def test_times_follow_each_country_clocks_changes():
    assert when("fed", "2026-10-28") == utc(2026, 10, 28, 18, 0)  # 2pm New York, still on summer time
    assert when("fed", "2026-12-09") == utc(2026, 12, 9, 19, 0)  # 2pm New York in winter
    assert when("boe", "2026-11-05") == utc(2026, 11, 5, 12, 0)  # noon London (GMT)
    assert when("boe", "2026-09-17") == utc(2026, 9, 17, 11, 0)  # noon London (BST)
    assert when("ecb", "2026-10-29") == utc(2026, 10, 29, 13, 15)  # 14:15 Frankfurt (winter time from 25 Oct)
    assert when("us_cpi", "2026-10-14") == utc(2026, 10, 14, 12, 30)
    assert when("us_cpi", "2026-11-10") == utc(2026, 11, 10, 13, 30)
    assert when("uk_cpi", "2026-10-21") == utc(2026, 10, 21, 6, 0)  # 7am BST
    assert when("boj", "2026-10-30") == utc(2026, 10, 30, 3, 0)  # midday Tokyo (approximate)


def test_events_reach_the_markets_they_move():
    gbp, gold, yen = get_symbol("GBP_USD"), get_symbol("XAU_USD"), get_symbol("USD_JPY")
    boe = next(e for e in calendar.EVENTS if e.series.key == "boe")
    fed = next(e for e in calendar.EVENTS if e.series.key == "fed")
    boj = next(e for e in calendar.EVENTS if e.series.key == "boj")
    us_cpi = next(e for e in calendar.EVENTS if e.series.key == "us_cpi")
    assert calendar.affects(boe, gbp) and not calendar.affects(boe, gold)
    assert all(calendar.affects(fed, s) for s in (gbp, gold, yen))
    assert calendar.affects(boj, yen) and not calendar.affects(boj, gbp)
    assert calendar.affects(us_cpi, gold) and calendar.affects(us_cpi, gbp)


def test_soon_and_the_pause_window():
    gbp = get_symbol("GBP_USD")
    boe = when("boe", "2026-11-05")
    assert calendar.next_for(gbp, boe - timedelta(hours=5)).series.key == "boe"
    assert calendar.next_for(gbp, boe - timedelta(hours=30)) is None or calendar.next_for(gbp, boe - timedelta(hours=30)).series.key != "boe"
    assert calendar.blocking(gbp, boe - timedelta(hours=1)).series.key == "boe"
    assert calendar.blocking(gbp, boe + timedelta(hours=1, minutes=59)).series.key == "boe"
    assert calendar.blocking(gbp, boe + timedelta(hours=3)) is None


def test_coverage_warns_before_the_schedule_runs_out():
    assert calendar.coverage(utc(2026, 10, 6))["runningOut"] == []
    late = calendar.coverage(utc(2026, 11, 20))["runningOut"]
    assert "UK inflation (CPI)" in late and "US jobs report (non-farm payrolls)" in late
    assert calendar.coverage()["checked"] == calendar.CHECKED


def test_every_listed_date_is_in_order_and_on_a_weekday():
    for key, days in calendar.DATES.items():
        assert days == sorted(days), key
        for d in days:
            assert datetime.fromisoformat(d).weekday() < 5, (key, d)


def test_calendar_api(signed_in):
    r = signed_in.get("/api/calendar?symbol=GBP_USD&days=120&past_days=30").json()
    assert set(r) == {"events", "soon", "coverage"}
    assert all({"title", "time", "affects", "source", "what"} <= set(e) for e in r["events"])
    assert any(e["key"] == "boe" and e["affects"] for e in r["events"]) or not r["events"]
    assert signed_in.get("/api/calendar?symbol=NOPE").status_code == 400


def test_event_pause_holds_back_new_entries(signed_in, feed, monkeypatch):
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    assert run["eventPause"] is False
    r = signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "event_pause", "on": True})
    assert r.status_code == 200 and r.json()["eventPause"] is True
    boe = next(e for e in calendar.EVENTS if e.series.key == "boe")
    monkeypatch.setattr(calendar, "blocking", lambda symbol, now=None, hours=2.0: boe)
    feed.add(101.5)
    out, _ = _step(run["id"])
    assert "event pause held it back" in out and "Bank of England" in out
    assert _trades(signed_in, cfd)[0] == []
    assert signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "event_pause", "on": False}).json()["eventPause"] is False


@pytest.mark.parametrize("key", list(calendar.SERIES))
def test_every_series_has_dates_and_a_source(key):
    assert calendar.DATES[key] and calendar.SOURCES[key].startswith("https://")
