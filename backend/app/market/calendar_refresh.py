"""Keeping the economic calendar up to date from the publishers' own schedule pages.

Each publisher's page is fetched (read only, through the app's allowlisted client) and its dates read with a
small, strict reader for that page's layout. Dates are kept only if they pass sanity checks: a weekday, within
about two years of today, enough of them found, and for the Bank of England the named weekday must match the
date. New dates are added to those built into the code; nothing is ever deleted. If a page can't be fetched or
its layout has changed, that publisher keeps the dates it already had and the check says what went wrong.

Runs weekly in the worker, and on demand from Settings → Economic calendar.
"""

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarCheck, CalendarDate
from . import calendar
from .providers.http import safe_client

log = logging.getLogger(__name__)
USER_AGENT = "Mozilla/5.0 (compatible; GandyTradeLab/1.0; +https://gandytrade.co.uk) economic-calendar-check"
EVERY = timedelta(days=7)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


class ReadError(ValueError):
    """The page didn't contain what we expected: its layout may have changed."""


def month_number(text: str) -> int:
    t = text.lower().rstrip(".")[:3]
    for i, m in enumerate(MONTHS):
        if m.startswith(t):
            return i + 1
    raise ReadError(f"Unknown month {text!r}")


def page_text(html: str) -> str:
    """The page's visible text, with tags and extra spaces removed."""
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8211;", "-").replace("&ndash;", "-")
    return re.sub(r"\s+", " ", text)


def _years(text: str, pattern: str) -> list[tuple[int, int]]:
    """Positions of the year headings, as (position, year)."""
    return [(m.start(), int(m.group(1))) for m in re.finditer(pattern, text)]


def _year_at(heads: list[tuple[int, int]], pos: int) -> int | None:
    year = None
    for p, y in heads:
        if p <= pos:
            year = y
    return year


# --- One reader per publisher: page text → announcement days ---------------------------------------

def read_fed(text: str) -> list[date]:
    """'2026 FOMC Meetings … January 27-28 … March 17-18* …' (and 'April/May 30-1' across months)."""
    heads = _years(text, r"(20\d\d) FOMC Meetings")
    out = []
    for m in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                         r"(?:/(January|February|March|April|May|June|July|August|September|October|November|December))?"
                         r"\s+(\d{1,2})-(\d{1,2})\*?", text):
        year = _year_at(heads, m.start())
        if year:
            out.append(date(year, month_number(m.group(2) or m.group(1)), int(m.group(4))))
    return out


def read_boe(text: str) -> list[date]:
    """'2026 … Thursday 5 February … Thursday 19 March …': the weekday must match the date."""
    heads = _years(text, r"\b(20\d\d)\b")
    out = []
    for m in re.finditer(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday) (\d{1,2}) "
                         r"(January|February|March|April|May|June|July|August|September|October|November|December)\b", text):
        year = _year_at(heads, m.start())
        if not year:
            continue
        d = date(year, month_number(m.group(3)), int(m.group(2)))
        if d.strftime("%A") != m.group(1):
            raise ReadError(f"{m.group(0)} {year} isn't a {m.group(1)}: the page layout may have changed")
        out.append(d)
    return out


def read_ecb(text: str) -> list[date]:
    """'29/10/2026 Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference'."""
    marks = list(re.finditer(r"\b(\d{2})/(\d{2})/(20\d\d)\b", text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else min(len(text), m.end() + 300)
        what = text[m.end():end].lower()
        if "monetary policy meeting" in what and "non-monetary" not in what and ("day 2" in what or "press conference" in what):
            out.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
    return out


def read_boj(text: str) -> list[date]:
    """'2026 … Jan. 22 (Thurs.), 23 (Fri.) … Apr. 30 (Thurs.), May 1 (Fri.)': the second day is the decision."""
    heads = _years(text, r"\b(20\d\d)\b")
    out = []
    for m in re.finditer(_MONTH + r"\s+(\d{1,2})\s*\([A-Za-z]+\.?\),\s*(?:" + _MONTH + r"\s+)?(\d{1,2})\s*\(([A-Za-z]+)\.?\)",
                         text, re.I):
        year = _year_at(heads, m.start())
        if not year:
            continue
        d = date(year, month_number(m.group(3) or m.group(1)), int(m.group(4)))
        if not d.strftime("%A").lower().startswith(m.group(5).lower()[:3]):
            raise ReadError(f"{m.group(0)} {year} doesn't match its weekday: the page layout may have changed")
        out.append(d)
    return out


def read_bls(text: str) -> list[date]:
    """BLS release tables: 'Oct. 14, 2026 08:30 AM' (the release date, then its time)."""
    out = []
    for m in re.finditer(_MONTH + r"\s+(\d{1,2}),\s+(20\d\d)\s+0?8:30\s*AM", text, re.I):
        out.append(date(int(m.group(3)), month_number(m.group(1)), int(m.group(2))))
    return out


def read_ons(text: str) -> list[date]:
    """An ONS release page: 'Release date: 21 October 2026 7:00am'."""
    m = re.search(r"Release date:\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d\d)", text)
    return [date(int(m.group(3)), month_number(m.group(2)), int(m.group(1)))] if m else []


READERS: dict[str, tuple[str, Callable[[str], list[date]], int]] = {
    # series: (page, reader, fewest dates a healthy page shows)
    "fed": (calendar.SOURCES["fed"], read_fed, 6),
    "boe": (calendar.SOURCES["boe"], read_boe, 6),
    "ecb": (calendar.SOURCES["ecb"], read_ecb, 1),
    "boj": (calendar.SOURCES["boj"], read_boj, 6),
    "us_cpi": (calendar.SOURCES["us_cpi"], read_bls, 6),
    "us_jobs": (calendar.SOURCES["us_jobs"], read_bls, 6),
}


def sane(days: list[date], today: date) -> list[date]:
    """Weekdays only, from a year ago to two years ahead, no repeats, in order."""
    keep = {d for d in days if d.weekday() < 5 and today - timedelta(days=400) <= d <= today + timedelta(days=760)}
    return sorted(keep)


# --- Fetching and saving ------------------------------------------------------------------------------

def _get(client: httpx.Client, url: str) -> str:
    r = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    if r.status_code in (403, 429):
        raise ReadError(f"The site refused the request (HTTP {r.status_code}); it may block automated checks.")
    if r.status_code != 200:
        raise ReadError(f"The page answered HTTP {r.status_code}.")
    return r.text


def _ons_days(client: httpx.Client, today: date) -> list[date]:
    """ONS has one page per release: try each coming month's UK CPI release until two in a row aren't announced yet."""
    out, misses = [], 0
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    for _ in range(14):
        url = f"https://www.ons.gov.uk/releases/consumerpriceinflationuk{MONTHS[m - 1]}{y}"
        r = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        if r.status_code == 200:
            out += read_ons(page_text(r.text))
            misses = 0
        elif r.status_code in (403, 429):
            raise ReadError(f"The ONS site refused the request (HTTP {r.status_code}).")
        else:
            misses += 1
            if misses >= 2:
                break
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def _save(db: Session, series: str, days: list[date], tentative_from: date | None = None) -> int:
    have = {r.day for r in db.scalars(select(CalendarDate).where(CalendarDate.series == series))} | set(calendar.DATES[series])
    added = 0
    for d in days:
        key = d.isoformat()
        if key not in have:
            db.add(CalendarDate(series=series, day=key, tentative=bool(tentative_from and d >= tentative_from)))
            added += 1
    return added


def _record(db: Session, series: str, ok: bool, found: int, added: int, message: str) -> None:
    row = db.get(CalendarCheck, series) or CalendarCheck(series=series)
    row.checked_at, row.ok, row.found, row.added, row.message = datetime.now(timezone.utc), ok, found, added, message[:300]
    db.merge(row)


def refresh(db: Session, client: httpx.Client | None = None, today: date | None = None) -> dict:
    """Check every publisher. Returns {series: {ok, found, added, message}}."""
    today = today or datetime.now(timezone.utc).date()
    own = client is None
    client = client or safe_client(timeout=20)
    results = {}
    try:
        for series in calendar.SERIES:
            try:
                if series == "uk_cpi":
                    days, minimum = _ons_days(client, today), 1
                else:
                    url, reader, minimum = READERS[series]
                    days = reader(page_text(_get(client, url)))
                days = sane(days, today)
                if len(days) < minimum:
                    raise ReadError(f"Found {len(days)} date(s), fewer than expected: the page layout may have changed.")
                # The Fed confirms each date only at the meeting before, so dates beyond the next year are tentative.
                tentative_from = date(today.year + 1, 1, 1) if series == "fed" else None
                added = _save(db, series, days, tentative_from)
                msg = f"Found {len(days)} dates; {added} new." if added else f"Found {len(days)} dates; nothing new."
                results[series] = {"ok": True, "found": len(days), "added": added, "message": msg}
            except (ReadError, httpx.HTTPError, ValueError) as exc:
                text = str(exc) if isinstance(exc, ReadError) else f"Couldn't reach the page ({type(exc).__name__})."
                results[series] = {"ok": False, "found": 0, "added": 0, "message": text + " Kept the dates already saved."}
            r = results[series]
            _record(db, series, r["ok"], r["found"], r["added"], r["message"])
            db.commit()
    finally:
        if own:
            client.close()
    calendar.reload(db)
    return results


def due(db: Session, now: datetime | None = None) -> bool:
    """A weekly check is due if any publisher hasn't been checked for a week."""
    now = now or datetime.now(timezone.utc)
    checks = {c.series: c for c in db.scalars(select(CalendarCheck))}
    for series in calendar.SERIES:
        c = checks.get(series)
        when = c.checked_at if c and c.checked_at.tzinfo else (c.checked_at.replace(tzinfo=timezone.utc) if c else None)
        if when is None or now - when >= EVERY:
            return True
    return False


def status(db: Session) -> list[dict]:
    """Per publisher: how far ahead its dates go, and its last check."""
    checks = {c.series: c for c in db.scalars(select(CalendarCheck))}
    cover = calendar.coverage()["until"]
    out = []
    for key, s in calendar.SERIES.items():
        c = checks.get(key)
        out.append({
            "key": key, "title": s.title, "until": cover.get(key), "source": calendar.SOURCES[key],
            "checkedAt": (c.checked_at if c.checked_at.tzinfo else c.checked_at.replace(tzinfo=timezone.utc)).isoformat() if c else None,
            "ok": c.ok if c else None, "message": c.message if c else "Not checked yet.",
        })
    return out
