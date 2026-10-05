"""Background on a market for the chart's hover card: who the company is, its sector, a short
summary and recent headlines; or, for currencies, commodities, indices and bonds, a short note on
what the market is and what tends to move it.

Sources, all free and read-only:
  * Alpha Vantage's company overview (US shares: sector, industry, size) and news feed, counted
    against a lower daily allowance (alphavantage.INFO_PER_DAY) so UK share prices keep some.
  * Wikipedia's page summaries (no key, no daily allowance), shown with a link to the article
    (Wikipedia's text is reusable with credit).
  * Hand-written notes in this file, for markets that aren't companies.

Everything is saved (company details and summaries for 30 days, headlines for 6 hours) and is
information only: nothing here places, closes or changes a trade.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Instrument, MarketInfo
from .providers import alphavantage
from .providers.base import ProviderError
from .providers.http import safe_client
from .symbols import Symbol

log = logging.getLogger(__name__)

PROFILE_DAYS = 30
WIKI_DAYS = 30
NEWS_HOURS = 6
RETRY_AFTER = timedelta(hours=12)  # after a failed lookup, before trying again
WIKI = "https://en.wikipedia.org"
USER_AGENT = "GandyTradeLab/1.0 (private, single-user research app; https://gandytrade.co.uk)"

CLASS_LABEL = {
    "forex": "Currency pair", "metal": "Metal", "commodity": "Commodity", "index": "Stock market index",
    "bond": "Government bond", "stock": "US share", "etf": "US fund (ETF)", "ukstock": "UK share",
}

# --- Hand-written notes for markets that aren't companies ----------------------------------------

CURRENCIES = {
    "USD": ("US dollar", "the world's main reserve currency; moved by US interest rates (the Federal Reserve), jobs and inflation figures, and tends to rise when markets are fearful"),
    "EUR": ("euro", "moved by European Central Bank rates, euro-area inflation and growth, and German data"),
    "GBP": ("British pound", "moved by Bank of England rates, UK inflation and jobs figures, and UK politics"),
    "JPY": ("Japanese yen", "moved by the Bank of Japan's very low rates and by fear: it often rises when markets fall"),
    "CHF": ("Swiss franc", "a 'safe haven' that often rises in a crisis; the Swiss National Bank sometimes steps in to weaken it"),
    "AUD": ("Australian dollar", "tied to commodity prices (iron ore, coal) and China's economy; tends to rise when markets are confident"),
    "NZD": ("New Zealand dollar", "tied to dairy and farm exports and risk appetite; moved by Reserve Bank of New Zealand rates"),
    "CAD": ("Canadian dollar", "closely tied to the oil price and the US economy; moved by Bank of Canada rates"),
    "SEK": ("Swedish krona", "moved by Riksbank rates and European growth"),
    "NOK": ("Norwegian krone", "closely tied to the oil price; moved by Norges Bank rates"),
    "DKK": ("Danish krone", "kept closely pegged to the euro"),
    "PLN": ("Polish zloty", "an emerging-market currency moved by Polish rates and European growth"),
    "HUF": ("Hungarian forint", "an emerging-market currency moved by Hungarian rates and politics"),
    "CZK": ("Czech koruna", "moved by Czech central bank rates and European growth"),
    "TRY": ("Turkish lira", "very volatile; moved by Turkish inflation and central bank policy, with large falls over many years"),
    "ZAR": ("South African rand", "a volatile emerging-market currency tied to metals prices and risk appetite"),
    "MXN": ("Mexican peso", "tied to US trade and oil, and attracts investors when its interest rates are high"),
    "SGD": ("Singapore dollar", "managed by Singapore's central bank against a basket of currencies"),
    "HKD": ("Hong Kong dollar", "pegged in a narrow band to the US dollar"),
    "CNH": ("Chinese yuan (offshore)", "managed by China's central bank; moved by China's economy and US-China trade"),
    "THB": ("Thai baht", "tied to tourism and exports, and to risk appetite in Asia"),
}

# Instrument prefix -> (Wikipedia article, what it is and what tends to move it)
NOTES = {
    "XAU": ("Gold as an investment", "Gold in US dollars an ounce. Often seen as a store of value: tends to rise when interest rates fall, the dollar weakens, or markets are fearful. Central bank buying has supported it in recent years."),
    "XAG": ("Silver as an investment", "Silver in US dollars an ounce. Moves with gold but more sharply, and half its demand is industrial (solar panels, electronics), so it also follows the economy."),
    "XPT": ("Platinum as an investment", "Platinum in US dollars an ounce. Mostly used in car exhaust catalysts and jewellery; supply is concentrated in South Africa and Russia."),
    "XPD": ("Palladium", "Palladium in US dollars an ounce. Mainly used in petrol car catalysts; a small, very volatile market."),
    "XCU": ("Copper", "Copper in US dollars a pound. Used in building, wiring and electric cars, so it follows global growth, especially China's."),
    "BCO": ("Brent Crude", "The world's main oil price benchmark, in US dollars a barrel. Moved by OPEC+ output decisions, global growth, stockpiles and conflict in oil regions."),
    "WTICO": ("West Texas Intermediate", "US oil, in US dollars a barrel. Moves closely with Brent; also moved by weekly US stockpile figures."),
    "NATGAS": ("Natural gas", "US natural gas (Henry Hub). Very volatile: driven by weather, storage levels and exports of liquefied gas."),
    "CORN": ("Maize", "Corn, in US dollars a bushel. Moved by US weather and harvests, ethanol demand, and the monthly US crop reports (WASDE)."),
    "WHEAT": ("Wheat", "Wheat, in US dollars a bushel. Moved by harvests in the US, Russia, Ukraine and elsewhere, the weather, and export restrictions."),
    "SOYBN": ("Soybean", "Soybeans, in US dollars a bushel. Moved by US and Brazilian harvests and Chinese demand."),
    "SUGAR": ("Sugar", "Raw sugar, in US dollars a pound. Moved by harvests in Brazil and India, and by how much Brazilian cane goes to ethanol."),
    "SPX500": ("S&P 500", "The 500 largest US companies. The main measure of the US stock market; moved by company profits, interest rates and the economy."),
    "NAS100": ("Nasdaq-100", "The 100 largest non-financial companies on the Nasdaq exchange, heavy in technology (Apple, Microsoft, NVIDIA). Rises and falls more than the S&P 500."),
    "US30": ("Dow Jones Industrial Average", "30 large US companies, weighted by share price rather than size. An older, narrower measure than the S&P 500."),
    "US2000": ("Russell 2000 Index", "2,000 smaller US companies; more sensitive to US interest rates and the domestic economy."),
    "UK100": ("FTSE 100 Index", "The 100 largest companies on the London Stock Exchange. Many earn abroad, so it often rises when the pound falls; heavy in oil, mining, banks and drug makers."),
    "DE30": ("DAX", "Germany's 40 largest companies (the DAX, formerly 30). Heavy in industry, cars and chemicals, so it follows exports and global growth."),
    "DE40": ("DAX", "Germany's 40 largest companies. Heavy in industry, cars and chemicals, so it follows exports and global growth."),
    "FR40": ("CAC 40", "France's 40 largest companies, including luxury goods makers that depend on Chinese demand."),
    "EU50": ("Euro Stoxx 50", "50 of the largest companies in the euro area."),
    "JP225": ("Nikkei 225", "225 large Japanese companies. Often rises when the yen weakens, which helps exporters."),
    "AU200": ("S&P/ASX 200", "Australia's 200 largest companies, heavy in banks and mining."),
    "HK33": ("Hang Seng Index", "Hong Kong's largest companies, many of them Chinese; moved by China's economy and policy."),
    "CHINAH": ("Hang Seng China Enterprises Index", "Chinese companies listed in Hong Kong."),
    "CN50": ("FTSE China A50 Index", "50 of the largest companies listed in mainland China."),
    "NL25": ("AEX index", "The Netherlands' 25 largest companies, including chip-equipment maker ASML."),
    "CH20": ("Swiss Market Index", "Switzerland's 20 largest companies, heavy in drug makers, food and banks; seen as defensive."),
    "ESPIX": ("IBEX 35", "Spain's 35 largest companies, heavy in banks and utilities."),
    "SG30": ("Straits Times Index", "Singapore's 30 largest companies."),
    "IN50": ("NIFTY 50", "India's 50 largest companies."),
    "TWIX": ("Taiwan Capitalization Weighted Stock Index", "Taiwan's stock market, dominated by chip maker TSMC."),
    "USB02Y": ("United States Treasury security", "US government 2-year bonds. Bond prices fall when interest rates rise; the 2-year follows expectations for Federal Reserve rates closely."),
    "USB05Y": ("United States Treasury security", "US government 5-year bonds. Prices fall when interest rates rise."),
    "USB10Y": ("United States Treasury security", "US government 10-year bonds, the benchmark for borrowing costs worldwide. Prices fall when rates or inflation expectations rise."),
    "USB30Y": ("United States Treasury security", "US government 30-year bonds. Very sensitive to long-term inflation expectations: prices swing a lot when rates change."),
    "UK10YB": ("Gilt", "UK government 10-year bonds (gilts). Prices fall when UK interest rates or inflation expectations rise."),
    "DE10YB": ("Bund", "German government 10-year bonds (Bunds), the euro area's benchmark."),
}

CLASS_NOTE = {
    "metal": "A metal priced in dollars (or another currency). Precious metals often rise when interest rates fall or markets are fearful.",
    "commodity": "A raw material traded worldwide; supply (weather, harvests, output decisions) matters as much as demand.",
    "index": "A stock market index: one price for a basket of a country's largest companies.",
    "bond": "A government bond. Bond prices move the opposite way to interest rates.",
}


def note_for(symbol: Symbol) -> dict | None:
    """What a non-company market is and what tends to move it (hand-written, no lookup needed)."""
    if symbol.asset_class == "forex":
        parts = symbol.code.split("_")
        if len(parts) != 2:
            return None
        base, quote_ = (CURRENCIES.get(p) for p in parts)
        bn = base[0] if base else parts[0]
        qn = quote_[0] if quote_ else parts[1]
        text = (f"The {bn} priced in {qn}s: the price rises when the {bn} strengthens against the {qn}.")
        drivers = [f"{name[0].upper()}{name[1:]}: {why}." for name, why in (base, quote_) if name]
        return {"text": text, "drivers": drivers, "wikiTitle": None}
    if symbol.asset_class in ("metal", "commodity", "index", "bond"):
        prefix = symbol.code.split("_")[0]
        if prefix in NOTES:
            title, text = NOTES[prefix]
            unit = symbol.code.split("_")[-1]
            if symbol.asset_class == "metal" and unit != "USD":
                text = text.replace("US dollars", unit).replace("in dollars", f"in {unit}")
            return {"text": text, "drivers": [], "wikiTitle": title}
        return {"text": CLASS_NOTE.get(symbol.asset_class, ""), "drivers": [], "wikiTitle": None}
    return None


# --- Wikipedia -----------------------------------------------------------------------------------

COMPANY_WORDS = re.compile(
    r"\b(company|corporation|conglomerate|manufacturer|maker|bank|insurer|insurance|retailer|chain|business|firm|"
    r"group|holding|plc|airline|developer|provider|operator|producer|supplier|brand|biotechnology|pharmaceutical|"
    r"utility|real estate|investment trust|reit|semiconductor|software|media|telecommunications|miner|mining|"
    r"restaurant|publisher|network|platform|agency|services|technology)\b", re.I)
SUFFIXES = re.compile(
    r"(,?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|p\.l\.c|llc|lp|sa|ag|nv|se|"
    r"holdings?|group)\.?)+$|\s+-\s+.*$|\s+(class|series)\s+[a-z].*$|\s+(ordinary|common|preferred)\s+(shares?|stock).*$|"
    r"\s+(adr|ads|american depositary.*)$|\s+\(.*\)$", re.I)


def company_search_name(name: str) -> str:
    """'Agilent Technologies Inc.' -> 'Agilent Technologies'; 'Ares Acquisition Corp. III Class A' -> 'Ares Acquisition'."""
    out = name.strip()
    for _ in range(4):
        cleaned = re.sub(r"\s+(I{1,3}|IV|V)$", "", SUFFIXES.sub("", out).strip(" ,.")).strip(" ,.")
        if cleaned == out or not cleaned:
            break
        out = cleaned
    return out or name


def _wiki_get(path: str, client: httpx.Client) -> dict:
    r = client.get(WIKI + path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    if r.status_code == 404:
        return {}
    if r.status_code != 200:
        raise ProviderError(f"Wikipedia returned an error ({r.status_code}).")
    return r.json()


def _summary(title: str, client: httpx.Client) -> dict | None:
    data = _wiki_get("/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe=""), client)
    if not data or data.get("type") == "disambiguation" or not data.get("extract"):
        return None
    extract = data["extract"]
    if len(extract) > 700:
        cut = extract[:700].rsplit(". ", 1)[0]
        extract = cut + "." if cut else extract[:700] + "…"
    return {"title": data.get("title", title), "description": data.get("description", ""), "extract": extract,
            "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", f"{WIKI}/wiki/{quote(title)}")}


def wiki_lookup(symbol: Symbol, client: httpx.Client | None = None) -> dict:
    """A Wikipedia summary for the market, or {'none': reason}. Only company-like articles for shares."""
    own = client is None
    client = client or safe_client(timeout=10)
    try:
        note = note_for(symbol)
        if note is not None:
            title = note.get("wikiTitle")
            found = _summary(title, client) if title else None
            return found or {"none": "No Wikipedia summary for this market."}
        if symbol.asset_class == "etf":
            return {"none": "Funds rarely have their own Wikipedia article."}
        name = company_search_name(symbol.name)
        hits = _wiki_get("/w/rest.php/v1/search/title?" + httpx.QueryParams({"q": name, "limit": 5}).__str__(), client)
        for page in hits.get("pages", []):
            desc = page.get("description") or ""
            if COMPANY_WORDS.search(desc):
                found = _summary(page.get("key") or page.get("title"), client)
                if found:
                    return found
        return {"none": f"No Wikipedia article found for {name}."}
    finally:
        if own:
            client.close()


# --- Alpha Vantage: company details and headlines --------------------------------------------------

def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # not NaN


def profile_lookup(symbol: Symbol, client=None) -> dict:
    data = alphavantage.query_info(get_settings().alphavantage_key,
                                   {"function": "OVERVIEW", "symbol": symbol.provider_symbol}, client)
    if not data or not data.get("Symbol"):
        return {"none": "Alpha Vantage has no company details for this share."}
    keep = {
        "name": data.get("Name", ""), "sector": (data.get("Sector") or "").title(), "industry": (data.get("Industry") or "").title(),
        "exchange": data.get("Exchange", ""), "country": data.get("Country", ""), "currency": data.get("Currency", ""),
        "description": (data.get("Description") or "")[:900], "website": data.get("OfficialSite") or "",
        "marketCap": _num(data.get("MarketCapitalization")), "peRatio": _num(data.get("PERatio")),
        "dividendYield": _num(data.get("DividendYield")), "high52": _num(data.get("52WeekHigh")),
        "low52": _num(data.get("52WeekLow")), "beta": _num(data.get("Beta")),
    }
    return {k: v for k, v in keep.items() if v not in ("", None, "None")}


def news_lookup(symbol: Symbol, client=None) -> dict:
    data = alphavantage.query_info(get_settings().alphavantage_key, {
        "function": "NEWS_SENTIMENT", "tickers": symbol.provider_symbol, "sort": "LATEST", "limit": "10"}, client)
    items = []
    for a in data.get("feed", [])[:6]:
        try:
            when = datetime.strptime(a["time_published"][:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        url = str(a.get("url") or "")
        if not url.startswith("https://"):
            continue
        items.append({"title": str(a.get("title") or "")[:200], "source": str(a.get("source") or "")[:60],
                      "time": int(when.timestamp()), "url": url[:500]})
    return {"items": items} if items else {"none": "No recent headlines for this share."}


# --- Putting it together ---------------------------------------------------------------------------

def _fresh(at: datetime | None, payload: dict | None, keep: timedelta) -> bool:
    if at is None or payload is None:
        return False
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - at
    return age < (RETRY_AFTER if "error" in payload else keep)


def _row(db: Session, code: str) -> MarketInfo:
    row = db.get(MarketInfo, code)
    if row is None:
        row = MarketInfo(code=code)
        db.add(row)
    return row


def has_company_details(symbol: Symbol) -> bool:
    return symbol.asset_class == "stock" and symbol.provider == "twelvedata"


def has_headlines(symbol: Symbol) -> bool:
    return symbol.asset_class in ("stock", "etf") and symbol.provider == "twelvedata"


def info(db: Session, symbol: Symbol, full: bool = False) -> dict:
    """Everything known about a market. Wikipedia (no allowance) is looked up when missing or old;
    Alpha Vantage company details only when `full` (the market you've chosen, or the ⓘ button)."""
    row = _row(db, symbol.code)
    changed = False
    if not _fresh(row.wiki_at, row.wiki, timedelta(days=WIKI_DAYS)):
        try:
            row.wiki = wiki_lookup(symbol)
        except (ProviderError, httpx.HTTPError, ValueError) as exc:
            log.info("Wikipedia lookup for %s failed: %s", symbol.code, exc)
            row.wiki = {"error": "Wikipedia couldn't be reached just now."}
        row.wiki_at = datetime.now(timezone.utc)
        changed = True
    if full and has_company_details(symbol) and not _fresh(row.profile_at, row.profile, timedelta(days=PROFILE_DAYS)):
        try:
            row.profile = profile_lookup(symbol)
            row.profile_at = datetime.now(timezone.utc)
        except ProviderError as exc:
            if row.profile is None or "error" in row.profile:
                row.profile = {"error": str(exc)}
                row.profile_at = datetime.now(timezone.utc)
        changed = True
    if changed:
        db.commit()
    inst = db.get(Instrument, symbol.code)
    news_ok = row.news is not None and _fresh(row.news_at, row.news, timedelta(hours=NEWS_HOURS))
    return {
        "code": symbol.code, "name": symbol.name, "assetClass": symbol.asset_class,
        "kind": CLASS_LABEL.get(symbol.asset_class, symbol.asset_class), "exchange": inst.exchange if inst else "",
        "note": note_for(symbol), "wiki": row.wiki, "profile": row.profile,
        "canProfile": has_company_details(symbol), "canNews": has_headlines(symbol),
        "news": row.news if news_ok else None, "newsAt": int(row.news_at.timestamp()) if news_ok and row.news_at else None,
        "allowanceLeft": alphavantage.budget.info_left(),
    }


def headlines(db: Session, symbol: Symbol) -> dict:
    """Recent headlines for a share (one Alpha Vantage request, saved for 6 hours)."""
    if not has_headlines(symbol):
        raise ProviderError("Headlines are available for US shares and funds only.")
    row = _row(db, symbol.code)
    if not _fresh(row.news_at, row.news, timedelta(hours=NEWS_HOURS)):
        try:
            row.news = news_lookup(symbol)
        except ProviderError as exc:
            row.news = {"error": str(exc)}
        row.news_at = datetime.now(timezone.utc)
        db.commit()
    return {"news": row.news, "newsAt": int(row.news_at.timestamp()), "allowanceLeft": alphavantage.budget.info_left()}
