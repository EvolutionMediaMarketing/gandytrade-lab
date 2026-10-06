"""News alerts: a Telegram message when a story breaks about a market you hold a paper trade in.

Information only. Nothing here opens, closes or changes a trade, and a headline is never a signal.

The only free source is Alpha Vantage's news feed (NEWS_SENTIMENT), within its 25-requests-a-day
plan, so the watch is deliberately frugal:
  * at most PER_DAY lookups a day (counted in the database, so restarts don't reset it), at most
    PER_PASS per worker pass, and each feed no more often than every CHECK_HOURS;
  * markets share feeds where they can. US shares and funds use their own ticker; currencies use
    Alpha Vantage's FOREX:<currency> tag; metals, oil, crops, indices and bonds use a broad topic
    feed (one lookup covers them all) and keep only headlines that name the market in the title.

"Major" means the story is about the market, not a passing mention: for ticker feeds Alpha Vantage
must rate the article at least MIN_RELEVANCE relevant to that ticker; for topic feeds the market's
name must be in the headline. Coverage of commodities and indices is thin, because the free feed
is mostly about US companies. UK shares aren't covered at all.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import alerts
from ..config import get_settings
from ..models import NewsLookup, NewsSeen, PaperAccount, PaperTrade
from .directory import lookup
from .providers import alphavantage
from .providers.base import ProviderError
from .symbols import Symbol

log = logging.getLogger(__name__)

PER_DAY = 8  # of Alpha Vantage's 25 a day; the rest stay for the hover card and UK share prices
PER_PASS = 2
CHECK_HOURS = 3
FIRST_LOOK_HOURS = 6  # a feed's first check only reports stories from the last few hours, not a backlog
MAX_AGE_HOURS = 24
MIN_RELEVANCE = 0.5
PER_MESSAGE = 3
KEEP_DAYS = 14

# Instrument prefix -> (topic feed, headline words that mean the story is about it)
TOPIC_WORDS: dict[str, tuple[str, str]] = {
    "XAU": ("financial_markets", r"gold|bullion"),
    "XAG": ("financial_markets", r"silver"),
    "XPT": ("financial_markets", r"platinum"),
    "XPD": ("financial_markets", r"palladium"),
    "XCU": ("financial_markets", r"copper"),
    "BCO": ("energy_transportation", r"oil|crude|brent|opec\+?"),
    "WTICO": ("energy_transportation", r"oil|crude|wti|opec\+?"),
    "NATGAS": ("energy_transportation", r"natural gas|lng|gas prices"),
    "CORN": ("financial_markets", r"corn|maize|grains?|wasde"),
    "WHEAT": ("financial_markets", r"wheat|grains?|wasde"),
    "SOYBN": ("financial_markets", r"soybeans?|soy|wasde"),
    "SUGAR": ("financial_markets", r"sugar"),
    "SPX500": ("financial_markets", r"s&p 500|s&p|wall street"),
    "NAS100": ("financial_markets", r"nasdaq"),
    "US30": ("financial_markets", r"dow jones|the dow|dow"),
    "US2000": ("financial_markets", r"russell 2000|small[- ]caps?"),
    "UK100": ("financial_markets", r"ftse|london stocks|uk stocks"),
    "DE30": ("financial_markets", r"dax|german stocks"),
    "DE40": ("financial_markets", r"dax|german stocks"),
    "FR40": ("financial_markets", r"cac 40|cac|french stocks"),
    "EU50": ("financial_markets", r"euro stoxx|stoxx|european stocks"),
    "JP225": ("financial_markets", r"nikkei|japanese stocks"),
    "AU200": ("financial_markets", r"asx|australian stocks"),
    "HK33": ("financial_markets", r"hang seng|hong kong stocks"),
    "CHINAH": ("financial_markets", r"hang seng|hong kong stocks"),
    "CN50": ("financial_markets", r"china stocks|chinese stocks|shanghai composite|csi 300"),
    "NL25": ("financial_markets", r"aex|dutch stocks"),
    "CH20": ("financial_markets", r"swiss stocks|\bsmi"),
    "ESPIX": ("financial_markets", r"ibex|spanish stocks"),
    "IN50": ("financial_markets", r"nifty|sensex|indian stocks"),
    "TWIX": ("financial_markets", r"taiwan stocks|taiex"),
    "USB02Y": ("economy_monetary", r"treasur(?:y|ies)|bond yields?|yields"),
    "USB05Y": ("economy_monetary", r"treasur(?:y|ies)|bond yields?|yields"),
    "USB10Y": ("economy_monetary", r"treasur(?:y|ies)|bond yields?|yields"),
    "USB30Y": ("economy_monetary", r"treasur(?:y|ies)|bond yields?|yields"),
    "UK10YB": ("economy_monetary", r"gilts?|uk bonds?|uk borrowing"),
    "DE10YB": ("economy_monetary", r"bunds?|german bonds?"),
}

TOPIC_NAMES = {"financial_markets": "financial markets", "energy_transportation": "energy",
               "economy_monetary": "interest rates and bonds"}


@dataclass(frozen=True)
class Watch:
    """How one market is watched: which feed, and what in an article counts as about it."""

    feed: str  # "ticker:AAPL", "ticker:FOREX:GBP" or "topic:financial_markets"
    ticker: str = ""  # for ticker feeds: the tag whose relevance score is checked
    words: str = ""  # for topic feeds: a regex the headline must match

    @property
    def describe(self) -> str:
        if self.feed.startswith("topic:"):
            return f"headlines in Alpha Vantage's {TOPIC_NAMES.get(self.feed[6:], self.feed[6:])} news that name it"
        if self.ticker.startswith("FOREX:"):
            return f"Alpha Vantage's news tagged {self.ticker[6:]}"
        return f"Alpha Vantage's news about {self.ticker}"


def watch_for(symbol: Symbol) -> Watch | None:
    """How to watch a market, or None if the free feed doesn't cover it."""
    if symbol.asset_class in ("stock", "etf") and symbol.provider == "twelvedata":
        t = symbol.provider_symbol.upper()
        return Watch(f"ticker:{t}", ticker=t)
    if symbol.asset_class == "forex":
        parts = symbol.code.split("_")
        if len(parts) != 2:
            return None
        # The US dollar's feed is about everything, so watch the other currency.
        ccy = parts[1] if parts[0] == "USD" else parts[0]
        return Watch(f"ticker:FOREX:{ccy}", ticker=f"FOREX:{ccy}")
    prefix = symbol.code.split("_")[0]
    if prefix in TOPIC_WORDS:
        topic, words = TOPIC_WORDS[prefix]
        return Watch(f"topic:{topic}", words=words)
    return None


def not_covered_reason(symbol: Symbol) -> str:
    if symbol.asset_class == "ukstock":
        return "Alpha Vantage's free news feed doesn't cover London-listed shares."
    return "Alpha Vantage's free news feed has nothing that reliably covers this market."


# --- Reading the feed ---------------------------------------------------------------------------------

def _when(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def fetch(feed: str, since: datetime, client=None) -> list[dict]:
    """One Alpha Vantage lookup. Returns articles (title, source, url, time, tickers with relevance)."""
    params = {"function": "NEWS_SENTIMENT", "sort": "LATEST", "limit": "50",
              "time_from": since.strftime("%Y%m%dT%H%M")}
    if feed.startswith("ticker:"):
        params["tickers"] = feed[7:]
    else:
        params["topics"] = feed[6:]
    data = alphavantage.query_info(get_settings().alphavantage_key, params, client)
    out = []
    for a in data.get("feed", []) or []:
        when = _when(str(a.get("time_published") or ""))
        url = str(a.get("url") or "")
        title = " ".join(str(a.get("title") or "").split())
        if when is None or not url.startswith("https://") or not title:
            continue
        rel = {}
        for t in a.get("ticker_sentiment") or []:
            try:
                rel[str(t.get("ticker", "")).upper()] = float(t.get("relevance_score"))
            except (TypeError, ValueError):
                continue
        out.append({"title": title[:200], "source": str(a.get("source") or "")[:60], "url": url[:500],
                    "time": when, "relevance": rel})
    return out


def matches(article: dict, watch: Watch) -> bool:
    if watch.ticker:
        return article["relevance"].get(watch.ticker, 0.0) >= MIN_RELEVANCE
    return re.search(rf"\b(?:{watch.words})\b", article["title"], re.I) is not None


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:40]


# --- The worker's pass -------------------------------------------------------------------------------

def _today_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def used_today(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return db.scalar(select(func.count()).select_from(NewsLookup).where(NewsLookup.at >= _today_start(now))) or 0


def _last(db: Session, feed: str) -> NewsLookup | None:
    return db.scalar(select(NewsLookup).where(NewsLookup.feed == feed).order_by(NewsLookup.at.desc()).limit(1))


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def held(db: Session) -> dict[str, dict]:
    """Markets with open paper trades: code -> {symbol, users}."""
    rows = db.execute(select(PaperTrade.symbol, PaperAccount.user_id)
                      .join(PaperAccount, PaperAccount.id == PaperTrade.account_id)
                      .where(PaperTrade.status == "open")).all()
    out: dict[str, dict] = {}
    for code, user_id in rows:
        if code not in out:
            try:
                out[code] = {"symbol": lookup(db, code), "users": set()}
            except ValueError:
                continue
        out[code]["users"].add(user_id)
    return out


def _wanted(db: Session) -> bool:
    """Only spend lookups when someone has news alerts switched on and a chat linked."""
    from ..models import AlertSettings

    return any("news" in (r.kinds or []) and r.chat_id for r in db.scalars(select(AlertSettings)))


def _message(articles: list[tuple[dict, list[str]]]) -> str:
    lines = ["News about a market you hold (information only: your trades are unchanged)"]
    for a, names in articles[:PER_MESSAGE]:
        when = a["time"].astimezone(_uk()).strftime("%a %d %b %H:%M")
        lines.append(f"\n{', '.join(names)}: {a['title']}\n{a['source']}, {when} UK\n{a['url']}")
    if len(articles) > PER_MESSAGE:
        lines.append(f"\n…and {len(articles) - PER_MESSAGE} more.")
    return "\n".join(lines)


def _uk():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Europe/London")


def run(db: Session, now: datetime | None = None, client=None) -> dict:
    """Check the feeds that are due for the markets you hold, and queue alerts for new stories."""
    now = now or datetime.now(timezone.utc)
    stats = {"lookups": 0, "alerts": 0, "skipped": ""}
    if not get_settings().alphavantage_key or not _wanted(db):
        stats["skipped"] = "off"
        return stats
    markets = held(db)
    feeds: dict[str, list[tuple[Watch, dict]]] = {}
    for m in markets.values():
        w = watch_for(m["symbol"])
        if w:
            feeds.setdefault(w.feed, []).append((w, m))
    if not feeds:
        stats["skipped"] = "nothing held is covered"
        return stats
    budget_left = PER_DAY - used_today(db, now)
    due = []
    for feed in feeds:
        last = _last(db, feed)
        if last is None or now - _aware(last.at) >= timedelta(hours=CHECK_HOURS):
            due.append((_aware(last.at) if last else None, feed))
    due.sort(key=lambda x: (x[0] is not None, x[0] or now))  # never-checked first, then oldest
    for last_at, feed in due[:max(0, min(PER_PASS, budget_left))]:
        since = max(last_at - timedelta(minutes=30) if last_at else now - timedelta(hours=FIRST_LOOK_HOURS),
                    now - timedelta(hours=MAX_AGE_HOURS))
        row = NewsLookup(feed=feed, at=now, found=0, error="")
        db.add(row)
        stats["lookups"] += 1
        try:
            articles = fetch(feed, since, client)
        except ProviderError as exc:
            row.error = str(exc)[:200]
            db.commit()
            log.info("News check for %s: %s", feed, exc)
            continue
        per_user: dict[int, list[tuple[dict, list[str]]]] = {}
        for a in sorted(articles, key=lambda a: a["time"], reverse=True):
            if a["time"] < since:
                continue
            hits = [(w, m) for w, m in feeds[feed] if matches(a, w)]
            if not hits:
                continue
            key = _key(a["url"])
            if db.get(NewsSeen, key) is not None:
                continue
            db.add(NewsSeen(key=key, at=now))
            row.found += 1
            users: dict[int, list[str]] = {}
            for _w, m in hits:
                for uid in m["users"]:
                    users.setdefault(uid, []).append(m["symbol"].name)
            for uid, names in users.items():
                per_user.setdefault(uid, []).append((a, sorted(set(names))))
        for uid, items in per_user.items():
            alerts.notify(db, uid, "news", _message(items))
            stats["alerts"] += 1
        db.commit()
    # Tidy: a fortnight of history is plenty.
    cutoff = now - timedelta(days=KEEP_DAYS)
    for old in db.scalars(select(NewsSeen).where(NewsSeen.at < cutoff)):
        db.delete(old)
    for old in db.scalars(select(NewsLookup).where(NewsLookup.at < cutoff)):
        db.delete(old)
    db.commit()
    return stats


def status(db: Session, user_id: int) -> dict:
    """For Settings: which of your held markets are watched, how, and when each feed was last checked."""
    markets = [m for m in held(db).values() if user_id in m["users"]]
    rows = []
    for m in sorted(markets, key=lambda m: m["symbol"].name):
        w = watch_for(m["symbol"])
        last = _last(db, w.feed) if w else None
        rows.append({"code": m["symbol"].code, "name": m["symbol"].name, "covered": w is not None,
                     "how": w.describe if w else not_covered_reason(m["symbol"]),
                     "checkedAt": int(_aware(last.at).timestamp()) if last else None,
                     "error": last.error if last and last.error else ""})
    return {"perDay": PER_DAY, "usedToday": used_today(db), "everyHours": CHECK_HOURS,
            "keyConfigured": bool(get_settings().alphavantage_key), "markets": rows}
