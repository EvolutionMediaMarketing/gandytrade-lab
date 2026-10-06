"""News alerts: which markets are watched and how, the daily allowance, only-new stories, and that
nothing about a trade ever changes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.market import news_watch
from app.market.providers.base import ProviderError
from app.market.symbols import SYMBOLS

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%M%S")


class FakeFeed:
    def __init__(self):
        self.calls: list[dict] = []
        self.articles: dict[str, list[dict]] = {}
        self.fail = False

    def __call__(self, key, params, client=None):
        self.calls.append(params)
        if self.fail:
            raise ProviderError("Alpha Vantage's free limit was reached; try again later.")
        feed = "ticker:" + params["tickers"] if "tickers" in params else "topic:" + params["topics"]
        return {"feed": self.articles.get(feed, [])}


def _article(title, url, at=NOW - timedelta(hours=1), tickers=None):
    return {"title": title, "url": url, "source": "Reuters", "time_published": _stamp(at),
            "ticker_sentiment": [{"ticker": t, "relevance_score": str(r)} for t, r in (tickers or {}).items()]}


@pytest.fixture()
def setup(client, user, monkeypatch):
    from app.db import new_session
    from app.models import AlertSettings, PaperAccount, PaperTrade, User

    fake = FakeFeed()
    monkeypatch.setattr(news_watch.alphavantage, "query_info", fake)
    monkeypatch.setattr(news_watch, "get_settings", lambda: SimpleNamespace(alphavantage_key="k"))
    db = new_session()
    uid = db.query(User).first().id
    db.add(AlertSettings(user_id=uid, chat_id="42", chat_name="me", kinds=["trades", "news"]))
    acct = PaperAccount(user_id=uid, name="Basket", mode="cfd", starting_balance=1000, cash=1000, peak_equity=1000)
    db.add(acct)
    db.commit()

    def hold(code):
        db.add(PaperTrade(account_id=acct.id, symbol=code, side=1, status="open", units=1, entry_price=1, entry_mid=1,
                          entry_quote_ts=0, stop=0.5, initial_stop=0.5, risk_gbp=10))
        db.commit()

    yield SimpleNamespace(db=db, fake=fake, hold=hold, uid=uid)
    db.close()


def _queued(db):
    from app.models import Alert

    return [a for a in db.query(Alert).order_by(Alert.id) if a.kind == "news"]


def test_how_each_kind_of_market_is_watched():
    assert news_watch.watch_for(SYMBOLS["AAPL"]).feed == "ticker:AAPL"
    assert news_watch.watch_for(SYMBOLS["GBP_USD"]).feed == "ticker:FOREX:GBP"
    gold = news_watch.watch_for(SYMBOLS["XAU_USD"])
    assert gold.feed == "topic:financial_markets"
    assert news_watch.matches({"title": "Gold hits record as dollar slides", "relevance": {}}, gold)
    assert not news_watch.matches({"title": "Goldman Sachs raises forecast", "relevance": {}}, gold)
    # US dollar pairs watch the other currency.
    assert news_watch.watch_for(SYMBOLS["USD_JPY"]).ticker == "FOREX:JPY"


def test_only_new_relevant_stories_about_held_markets_alert(setup):
    setup.hold("XAU_USD")
    setup.hold("AAPL")
    setup.fake.articles = {
        "topic:financial_markets": [
            _article("Gold jumps after Fed signals cuts", "https://example.com/gold"),
            _article("Silver miners rally", "https://example.com/silver"),  # not held
            _article("Gold story from yesterday", "https://example.com/old", at=NOW - timedelta(hours=20)),
        ],
        "ticker:AAPL": [
            _article("Apple unveils new chip", "https://example.com/apple", tickers={"AAPL": 0.9}),
            _article("Tech shares mixed", "https://example.com/mention", tickers={"AAPL": 0.1}),  # passing mention
        ],
    }
    got = news_watch.run(setup.db, now=NOW)
    assert got["lookups"] == 2
    texts = [a.text for a in _queued(setup.db)]
    joined = "\n".join(texts)
    assert "Gold jumps" in joined and "Apple unveils" in joined
    assert "Silver" not in joined and "yesterday" not in joined and "Tech shares" not in joined
    assert all("information only" in t for t in texts)

    # The next pass within three hours makes no lookups; later, the same stories aren't sent again.
    assert news_watch.run(setup.db, now=NOW + timedelta(hours=1))["lookups"] == 0
    got = news_watch.run(setup.db, now=NOW + timedelta(hours=4))
    assert got["lookups"] == 2 and got["alerts"] == 0


def test_daily_allowance_and_errors(setup, monkeypatch):
    monkeypatch.setattr(news_watch, "CHECK_HOURS", 0)
    setup.hold("XAU_USD")
    setup.fake.fail = True
    total = 0
    for i in range(12):
        total += news_watch.run(setup.db, now=NOW + timedelta(minutes=i))["lookups"]
    assert total == news_watch.PER_DAY
    assert news_watch.status(setup.db, setup.uid)["markets"][0]["error"].startswith("Alpha Vantage")
    # A new day, a new allowance.
    assert news_watch.run(setup.db, now=NOW + timedelta(days=1))["lookups"] == 1


def test_nothing_spent_when_switched_off_or_not_covered(setup):
    from app.models import AlertSettings

    setup.hold("XAU_USD")
    row = setup.db.query(AlertSettings).first()
    row.kinds = ["trades"]
    setup.db.commit()
    assert news_watch.run(setup.db, now=NOW)["skipped"] == "off"
    assert setup.fake.calls == []


def test_trades_are_never_touched(setup):
    from app.models import PaperTrade

    setup.hold("XAU_USD")
    setup.fake.articles = {"topic:financial_markets": [_article("Gold crashes 10%", "https://example.com/crash")]}
    before = [(t.status, t.stop, t.target, t.units) for t in setup.db.query(PaperTrade)]
    news_watch.run(setup.db, now=NOW)
    setup.db.expire_all()
    assert [(t.status, t.stop, t.target, t.units) for t in setup.db.query(PaperTrade)] == before


def test_settings_shows_coverage(setup, signed_in):
    setup.hold("XAU_USD")
    r = signed_in.get("/api/alerts")
    assert r.status_code == 200
    news = r.json()["news"]
    assert news["perDay"] == news_watch.PER_DAY
    assert news["markets"][0]["covered"] and "name it" in news["markets"][0]["how"]
    assert "news" in r.json()["kindLabels"]
