"""Economic calendar: the high-impact events that move markets most, from official published schedules.

The dates below were copied from each publisher's own schedule (links in SOURCES) and checked on CHECKED.
Times are each publisher's announcement time, converted to UTC here so British Summer Time and US daylight
saving are handled. The schedule is kept in the code rather than fetched live, so the server needs no new web
access; the app warns when it's within a month of running out, as a reminder to add the next dates.

Information only. Nothing here opens, closes or changes a trade; the only automatic effect is the optional
event pause on automatic runs, which stops new entries and nothing else.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .events import tags_for
from .symbols import Symbol

CHECKED = "2026-10-06"
NY, LONDON, FRANKFURT, TOKYO = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Europe/Berlin"), ZoneInfo("Asia/Tokyo")

SOURCES = {
    "fed": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "boe": "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
    "ecb": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    "boj": "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
    "us_cpi": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "us_jobs": "https://www.bls.gov/schedule/news_release/empsit.htm",
    "uk_cpi": "https://www.ons.gov.uk/releasecalendar",
}


@dataclass(frozen=True)
class Series:
    key: str
    title: str
    country: str
    what: str  # why it matters, in plain words
    tags: tuple[str, ...]  # which markets it moves (as in events.py)
    zone: ZoneInfo
    at: time  # local announcement time
    approx: bool = False  # no fixed time: roughly when


SERIES = {
    "fed": Series("fed", "US interest rate decision (Federal Reserve)", "US",
                  "The Fed sets US interest rates. A surprise moves the dollar, US shares, gold and almost everything else.",
                  ("all",), NY, time(14, 0)),
    "boe": Series("boe", "UK interest rate decision (Bank of England)", "UK",
                  "The Bank of England sets UK interest rates; the pound and UK shares react most.",
                  ("gbp", "uk_equities"), LONDON, time(12, 0)),
    "ecb": Series("ecb", "Euro-area interest rate decision (ECB)", "EU",
                  "The European Central Bank sets rates for the euro; the euro and European shares react most.",
                  ("eur", "eu_equities"), FRANKFURT, time(14, 15)),
    "boj": Series("boj", "Japan interest rate decision (Bank of Japan)", "JP",
                  "The Bank of Japan's decision moves the yen and Japanese shares. It has no fixed time; usually around midday in Tokyo.",
                  ("jpy", "japan"), TOKYO, time(12, 0), approx=True),
    "us_cpi": Series("us_cpi", "US inflation (CPI)", "US",
                     "Monthly US consumer price inflation. A surprise changes what traders expect from the Fed.",
                     ("usd", "equities", "gold", "silver", "metals"), NY, time(8, 30)),
    "us_jobs": Series("us_jobs", "US jobs report (non-farm payrolls)", "US",
                      "Monthly US employment figures, one of the most market-moving releases of the month.",
                      ("usd", "equities", "gold", "silver", "metals"), NY, time(8, 30)),
    "uk_cpi": Series("uk_cpi", "UK inflation (CPI)", "UK",
                     "Monthly UK consumer price inflation; shapes what's expected from the Bank of England.",
                     ("gbp", "uk_equities"), LONDON, time(7, 0)),
}

# Announcement days (for two-day meetings, the day of the decision).
DATES: dict[str, list[str]] = {
    "fed": ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
            "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"],
    "boe": ["2026-02-05", "2026-03-19", "2026-04-30", "2026-06-18", "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
            "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-17", "2027-07-29", "2027-09-16", "2027-11-04", "2027-12-16"],
    "ecb": ["2026-10-29", "2026-12-17",
            "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10", "2027-07-22", "2027-09-09", "2027-10-28"],
    "boj": ["2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16", "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18",
            "2027-01-22", "2027-03-18", "2027-04-28", "2027-06-11", "2027-07-22", "2027-09-22", "2027-10-29", "2027-12-17"],
    "us_cpi": ["2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
               "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10", "2027-01-13"],
    "us_jobs": ["2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
                "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"],
    "uk_cpi": ["2026-10-21", "2026-11-18", "2026-12-16"],
}

TENTATIVE = {("fed", d) for d in DATES["fed"] if d.startswith("2027")}  # the Fed confirms each date at the meeting before
WARN_DAYS = 30


@dataclass(frozen=True)
class Event:
    series: Series
    when: datetime  # UTC
    tentative: bool

    def to_dict(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        return {
            "key": self.series.key, "title": self.series.title, "country": self.series.country, "what": self.series.what,
            "time": int(self.when.timestamp()), "approx": self.series.approx, "tentative": self.tentative,
            "inSeconds": int((self.when - now).total_seconds()), "source": SOURCES[self.series.key],
        }


# Dates found later on the publishers' pages (Settings → Economic calendar, or the worker's weekly check),
# loaded from the database and merged with the ones above.
EXTRA: dict[str, set[str]] = {}
EXTRA_TENTATIVE: set[tuple[str, str]] = set()
_loaded = 0.0
RELOAD_SECONDS = 600


def all_events() -> list[Event]:
    out = []
    for key in SERIES:
        s = SERIES[key]
        for d in sorted(set(DATES[key]) | EXTRA.get(key, set())):
            local = datetime.combine(date.fromisoformat(d), s.at, tzinfo=s.zone)
            out.append(Event(s, local.astimezone(timezone.utc), (key, d) in TENTATIVE or (key, d) in EXTRA_TENTATIVE))
    return sorted(out, key=lambda e: e.when)


EVENTS = all_events()


def reload(db=None) -> None:
    """Merge in the dates saved from the publishers' pages."""
    global EVENTS, _loaded
    import time as _time

    from sqlalchemy import select

    from ..models import CalendarDate

    own = db is None
    if own:
        from ..db import new_session

        db = new_session()
    try:
        extra: dict[str, set[str]] = {}
        tentative: set[tuple[str, str]] = set()
        for r in db.scalars(select(CalendarDate)):
            if r.series in SERIES:
                extra.setdefault(r.series, set()).add(r.day)
                if r.tentative:
                    tentative.add((r.series, r.day))
        EXTRA.clear()
        EXTRA.update(extra)
        EXTRA_TENTATIVE.clear()
        EXTRA_TENTATIVE.update(tentative)
        EVENTS = all_events()
    finally:
        _loaded = _time.time()
        if own:
            db.close()


def _fresh() -> None:
    """Reload saved dates every few minutes, so the app and the worker both see new ones."""
    import time as _time

    if _time.time() - _loaded < RELOAD_SECONDS:
        return
    try:
        reload()
    except Exception:  # no database yet (tests, start-up): use the built-in dates
        globals()["_loaded"] = _time.time()


def affects(e: Event, symbol: Symbol | None) -> bool:
    return symbol is None or bool(tags_for(symbol) & set(e.series.tags))


def between(start: datetime, end: datetime, symbol: Symbol | None = None) -> list[Event]:
    _fresh()
    return [e for e in EVENTS if start <= e.when <= end and affects(e, symbol)]


def next_for(symbol: Symbol, now: datetime | None = None, within: timedelta = timedelta(hours=24)) -> Event | None:
    now = now or datetime.now(timezone.utc)
    soon = between(now, now + within, symbol)
    return soon[0] if soon else None


def blocking(symbol: Symbol, now: datetime | None = None, hours: float = 2.0) -> Event | None:
    """An event affecting this market within `hours` before or after now (the event pause window)."""
    now = now or datetime.now(timezone.utc)
    near = between(now - timedelta(hours=hours), now + timedelta(hours=hours), symbol)
    return near[0] if near else None


def coverage(now: datetime | None = None) -> dict:
    """How far ahead the schedule goes, per series, and whether any runs out within a month."""
    _fresh()
    now = now or datetime.now(timezone.utc)
    last = {k: max(e.when for e in EVENTS if e.series.key == k) for k in SERIES}
    short = [SERIES[k].title for k, t in last.items() if t < now + timedelta(days=WARN_DAYS)]
    return {"checked": CHECKED, "until": {k: t.date().isoformat() for k, t in last.items()}, "runningOut": short}
