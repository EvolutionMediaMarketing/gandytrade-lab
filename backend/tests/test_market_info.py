"""Hover-card background: hand-written notes, Wikipedia summaries, Alpha Vantage details and
headlines, saving, and the daily allowance kept for UK share prices."""

from types import SimpleNamespace

import httpx
import pytest

from app.market import info
from app.market.providers import alphavantage
from app.market.providers.http import host_allowed
from app.market.symbols import Symbol

AAPL = Symbol("AAPL", "Apple Inc.", "stock", "twelvedata", "AAPL", 2, 190.0)


class Web:
    """Fake Wikipedia and Alpha Vantage, counting calls."""

    def __init__(self):
        self.calls = []
        self.av_overview = {"Symbol": "AAPL", "Name": "Apple Inc", "Sector": "TECHNOLOGY", "Industry": "ELECTRONIC COMPUTERS",
                            "Exchange": "NASDAQ", "Country": "USA", "Description": "Apple designs phones.",
                            "MarketCapitalization": "3500000000000", "PERatio": "30.1", "DividendYield": "0.0045",
                            "AnalystTargetPrice": "999"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url)
        host, path = request.url.host, request.url.path
        if host == "en.wikipedia.org" and path.endswith("/search/title"):
            return httpx.Response(200, json={"pages": [
                {"key": "Apple", "title": "Apple", "description": "Fruit of the apple tree"},
                {"key": "Apple_Inc.", "title": "Apple Inc.", "description": "American multinational technology company"}]})
        if host == "en.wikipedia.org" and "/page/summary/" in path:
            title = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"type": "standard", "title": title.replace("_", " "), "description": "x",
                                             "extract": f"{title} summary.",
                                             "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title}"}}})
        if host == "www.alphavantage.co":
            fn = request.url.params["function"]
            if fn == "OVERVIEW":
                return httpx.Response(200, json=self.av_overview)
            if fn == "NEWS_SENTIMENT":
                return httpx.Response(200, json={"feed": [
                    {"title": "Apple unveils thing", "url": "https://news.example.com/a", "source": "Example",
                     "time_published": "20261005T101500", "overall_sentiment_label": "Bullish"},
                    {"title": "Not https", "url": "http://bad.example.com", "source": "X", "time_published": "20261005T090000"}]})
        return httpx.Response(404, json={})


@pytest.fixture()
def web(monkeypatch):
    w = Web()
    make = lambda timeout=20: httpx.Client(transport=httpx.MockTransport(w.handler))  # noqa: E731
    monkeypatch.setattr(info, "safe_client", make)
    monkeypatch.setattr(alphavantage, "safe_client", make)
    monkeypatch.setattr(info, "get_settings", lambda: SimpleNamespace(alphavantage_key="k"))
    monkeypatch.setattr(alphavantage, "budget", alphavantage._Budget())
    return w


def test_wikipedia_is_allowed_and_names_are_cleaned():
    assert host_allowed("en.wikipedia.org") and not host_allowed("wikipedia.org.evil.com")
    assert info.company_search_name("Agilent Technologies Inc.") == "Agilent Technologies"
    assert info.company_search_name("Ares Acquisition Corp. III Class A Ordinary Shares") == "Ares Acquisition"
    assert info.company_search_name("Vodafone Group Plc") == "Vodafone"


def test_notes_for_markets_that_are_not_companies():
    fx = info.note_for(Symbol("EUR_GBP", "Euro / British Pound", "forex", "oanda", "EUR_GBP", 5, 0.85))
    assert "euro priced in British pounds" in fx["text"] and len(fx["drivers"]) == 2
    gold_gbp = info.note_for(Symbol("XAU_GBP", "Gold/GBP", "metal", "oanda", "XAU_GBP", 2, 1.0))
    assert "GBP an ounce" in gold_gbp["text"] and gold_gbp["wikiTitle"] == "Gold as an investment"
    assert info.note_for(Symbol("ZZZ_USD", "Something", "index", "oanda", "ZZZ_USD", 2, 1.0))["text"].startswith("A stock market index")
    assert info.note_for(AAPL) is None


def test_company_card_picks_the_company_article_and_saves(signed_in, web):
    from app.db import new_session

    db = new_session()
    out = info.info(db, AAPL, full=False)
    assert out["wiki"]["title"] == "Apple Inc." and out["profile"] is None  # no allowance used on a plain hover
    assert not any(u.host == "www.alphavantage.co" for u in web.calls)
    out = info.info(db, AAPL, full=True)
    p = out["profile"]
    assert p["sector"] == "Technology" and p["industry"] == "Electronic Computers" and p["marketCap"] == 3.5e12
    assert "AnalystTargetPrice" not in p and "analystTarget" not in str(p)  # evidence, not opinions
    n = len(web.calls)
    info.info(db, AAPL, full=True)
    assert len(web.calls) == n  # saved: no new requests
    h = info.headlines(db, AAPL)
    assert [i["title"] for i in h["news"]["items"]] == ["Apple unveils thing"]  # only https links
    assert "Bullish" not in str(h)  # no sentiment verdicts
    assert out["allowanceLeft"] <= alphavantage.INFO_PER_DAY
    db.close()


def test_info_allowance_leaves_room_for_prices(web):
    b = alphavantage.budget
    b.minute.clear()
    for _ in range(alphavantage.INFO_PER_DAY):
        assert b.try_acquire(info=True) is None
        b.minute.clear()
    assert "used up" in b.try_acquire(info=True)
    assert b.try_acquire() is None  # prices can still be fetched
    assert b.info_left() == 0


def test_api(signed_in, web):
    r = signed_in.get("/api/markets/info", params={"symbol": "XAU_USD"}).json()
    assert r["kind"] == "Metal" and "ounce" in r["note"]["text"] and r["wiki"]["title"] == "Gold as an investment"
    assert not r["canProfile"] and not r["canNews"]
    assert signed_in.post("/api/markets/info/news", params={"symbol": "XAU_USD"}).status_code == 400
    assert signed_in.get("/api/markets/info", params={"symbol": "NOPE"}).status_code == 404
