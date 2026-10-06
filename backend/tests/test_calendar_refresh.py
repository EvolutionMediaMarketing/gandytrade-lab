"""Reading official schedule pages: each reader on page text in the publisher's layout, the sanity checks,
saving only new dates, and keeping what we had when a page fails."""

from datetime import date

import httpx
import pytest

from app.market import calendar, calendar_refresh as cr

TODAY = date(2026, 10, 6)

FED = """<h4>2026 FOMC Meetings</h4><div><strong>October</strong></div><div>27-28</div>
<div><strong>December</strong></div><div>8-9*</div><p>(Released November 18, 2026)</p>
<h4>2027 FOMC Meetings</h4><div><strong>January</strong></div><div>26-27</div><div><strong>Apr/May</strong></div>
<div><strong>March</strong></div><div>16-17*</div><div><strong>April/May</strong></div><div>30-1</div>"""
BOE = "<h2>2026</h2><li>Thursday 5 November</li><li>Thursday 17 December</li><h2>2027</h2><li>Thursday 4 February</li>"
BOE_BAD = "<h2>2026</h2><li>Friday 5 November</li>"
ECB = """<dt>28/10/2026</dt><dd>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 1)</dd>
<dt>29/10/2026</dt><dd>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference</dd>
<dt>25/11/2026</dt><dd>Governing Council of the ECB: non-monetary policy meeting (in Frankfurt)</dd>
<dt>17/12/2026</dt><dd>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference</dd>"""
BOJ = "<h3>2026</h3><td>Oct. 29 (Thurs.), 30 (Fri.)</td><td>Dec. 17 (Thurs.), 18 (Fri.)</td><h3>2027</h3><td>Apr. 29 (Thurs.), 30 (Fri.)</td>"
BLS = "<tr><td>September 2026</td><td>Oct. 14, 2026</td><td>08:30 AM</td></tr><tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr><p>Last modified Sept. 3, 2025</p>"
ONS = "<p>Release date: 21 October 2026 7:00am</p>"


@pytest.fixture(autouse=True)
def built_in_dates_afterwards():
    """Dates found in one test mustn't leak into others (the calendar keeps them in memory)."""
    yield
    calendar.EXTRA.clear()
    calendar.EXTRA_TENTATIVE.clear()
    calendar.EVENTS = calendar.all_events()


def text(html):
    return cr.page_text(html)


def test_readers():
    assert cr.read_fed(text(FED)) == [date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27), date(2027, 3, 17), date(2027, 5, 1)]
    assert cr.read_boe(text(BOE)) == [date(2026, 11, 5), date(2026, 12, 17), date(2027, 2, 4)]
    assert cr.read_ecb(text(ECB)) == [date(2026, 10, 29), date(2026, 12, 17)]
    assert cr.read_boj(text(BOJ)) == [date(2026, 10, 30), date(2026, 12, 18), date(2027, 4, 30)]
    assert cr.read_bls(text(BLS)) == [date(2026, 10, 14), date(2026, 11, 10)]  # not the "last modified" date
    assert cr.read_ons(text(ONS)) == [date(2026, 10, 21)]


def test_a_weekday_that_doesnt_match_means_the_page_changed():
    with pytest.raises(cr.ReadError):
        cr.read_boe(text(BOE_BAD))
    with pytest.raises(cr.ReadError):
        cr.read_boj(text("<h3>2026</h3>Oct. 29 (Thurs.), 31 (Fri.)"))


def test_sanity_drops_weekends_and_far_dates():
    kept = cr.sane([date(2026, 10, 10), date(2026, 10, 12), date(2031, 1, 6), date(2024, 1, 2), date(2026, 10, 12)], TODAY)
    assert kept == [date(2026, 10, 12)]


def fake_client(pages: dict[str, tuple[int, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        code, body = pages.get(str(request.url), (404, ""))
        return httpx.Response(code, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_refresh_adds_new_dates_and_keeps_the_rest_when_a_page_fails(client, monkeypatch):
    from app.db import new_session

    fed_2028 = FED + "<h4>2028 FOMC Meetings</h4><div><strong>January</strong></div><div>25-26</div>"
    pages = {
        calendar.SOURCES["fed"]: (200, fed_2028 + "<div><strong>June</strong></div><div>8-9*</div>"),
        calendar.SOURCES["boe"]: (200, BOE * 3),
        calendar.SOURCES["ecb"]: (200, ECB),
        calendar.SOURCES["boj"]: (403, "Access denied"),
        calendar.SOURCES["us_cpi"]: (200, "<p>Nothing here any more</p>"),
        calendar.SOURCES["us_jobs"]: (200, BLS * 3),
        "https://www.ons.gov.uk/releases/consumerpriceinflationukjanuary2027": (200, "<p>Release date: 17 February 2027 7:00am</p>"),
    }
    monkeypatch.setattr(cr, "READERS", {**cr.READERS, "fed": (calendar.SOURCES["fed"], cr.read_fed, 3),
                                        "boe": (calendar.SOURCES["boe"], cr.read_boe, 3),
                                        "us_jobs": (calendar.SOURCES["us_jobs"], cr.read_bls, 2)})
    db = new_session()
    before = len(calendar.EVENTS)
    got = cr.refresh(db, fake_client(pages), today=TODAY)
    assert got["boj"]["ok"] is False and "refused" in got["boj"]["message"] and "Kept" in got["boj"]["message"]
    assert got["us_cpi"]["ok"] is False and "fewer than expected" in got["us_cpi"]["message"]
    assert got["fed"]["ok"] and got["fed"]["added"] == 2  # 1 May 2027 (the test page's cross-month meeting) and 2028
    assert got["us_jobs"]["ok"] and got["us_jobs"]["added"] == 2  # the test page's two dates aren't jobs-report days
    assert got["boe"]["ok"] and got["boe"]["added"] == 0  # all already known
    # UK CPI pages are tried month by month from last month; two missing in a row ends the search.
    assert got["uk_cpi"]["ok"] is False
    assert len(calendar.EVENTS) == before + 4
    assert any(e.series.key == "fed" and e.when.year == 2028 and e.tentative for e in calendar.EVENTS)
    status = {s["key"]: s for s in cr.status(db)}
    assert status["boj"]["ok"] is False and status["fed"]["ok"] is True
    assert not cr.due(db)  # just checked
    db.close()


def test_refresh_endpoint_is_rate_limited(signed_in, monkeypatch):
    monkeypatch.setattr(cr, "refresh", lambda db, client=None, today=None: {})
    from app.routes import calendar as route

    route._last_manual.clear()
    assert signed_in.post("/api/calendar/refresh").status_code == 200
    assert signed_in.post("/api/calendar/refresh").status_code == 429
    s = signed_in.get("/api/calendar/status").json()
    assert {x["key"] for x in s["series"]} == set(calendar.SERIES)
