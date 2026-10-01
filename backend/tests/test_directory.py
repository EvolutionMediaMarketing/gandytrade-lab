"""The full market list: fetching, filtering, saving and searching."""

import httpx

from app.market import directory


def _oanda_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api-fxpractice.oanda.com"
        assert request.method == "GET"
        if request.url.path == "/v3/accounts":
            return httpx.Response(200, json={"accounts": [{"id": "101-004-1-001"}]})
        assert request.url.path == "/v3/accounts/101-004-1-001/instruments"
        return httpx.Response(200, json={"instruments": [
            {"name": "EUR_USD", "type": "CURRENCY", "displayName": "EUR/USD", "displayPrecision": 5},
            {"name": "XAU_USD", "type": "METAL", "displayName": "Gold", "displayPrecision": 3},
            {"name": "UK100_GBP", "type": "CFD", "displayName": "UK 100", "displayPrecision": 1},
            {"name": "JP225Y_JPY", "type": "CFD", "displayName": "Japan 225 (JPY)", "displayPrecision": 0},
            {"name": "USB10Y_USD", "type": "CFD", "displayName": "US 10Y T-Note", "displayPrecision": 3},
            {"name": "SOYBN_USD", "type": "CFD", "displayName": "Soybeans", "displayPrecision": 3},
        ]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_oanda_list_is_classified():
    rows = {r["code"]: r for r in directory.fetch_oanda("tok", client=_oanda_transport())}
    assert rows["EUR_USD"]["asset_class"] == "forex"
    assert rows["XAU_USD"]["asset_class"] == "metal"
    assert rows["UK100_GBP"]["asset_class"] == "index"
    assert rows["JP225Y_JPY"]["asset_class"] == "index"
    assert rows["USB10Y_USD"]["asset_class"] == "bond"
    assert rows["SOYBN_USD"]["asset_class"] == "commodity"
    assert rows["UK100_GBP"]["precision"] == 1


def test_twelvedata_keeps_only_free_us_listings():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "apikey k"
        assert "apikey" not in str(request.url)
        if request.url.path == "/stocks":
            return httpx.Response(200, json={"data": [
                {"symbol": "AAPL", "name": "Apple Inc", "exchange": "NASDAQ", "access": {"plan": "Basic"}},
                {"symbol": "PRO1", "name": "Paid Only Corp", "exchange": "NYSE", "access": {"plan": "Pro"}},
                {"symbol": "OTCX", "name": "Pink Sheet Co", "exchange": "OTC", "access": {"plan": "Basic"}},
                {"symbol": "DUAL", "name": "Dual Listed", "exchange": "CBOE", "access": {"plan": "Basic"}},
                {"symbol": "DUAL", "name": "Dual Listed", "exchange": "NYSE", "access": {"plan": "Basic"}},
            ]})
        return httpx.Response(200, json={"data": [
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "exchange": "NYSE ARCA", "access": {"plan": "Basic"}},
        ]})

    rows = {r["code"]: r for r in directory.fetch_twelvedata("k", client=httpx.Client(transport=httpx.MockTransport(handler)))}
    assert set(rows) == {"AAPL", "DUAL", "SPY"}
    assert rows["DUAL"]["exchange"] == "NYSE"
    assert rows["SPY"]["asset_class"] == "etf"


def _seed(client):
    from app.db import new_session

    db = new_session()
    directory.save(db, "oanda", directory.fetch_oanda("tok", client=_oanda_transport()))
    directory.save(db, "twelvedata", [
        {"code": "AMD", "name": "Advanced Micro Devices", "asset_class": "stock", "provider": "twelvedata",
         "provider_symbol": "AMD", "precision": 2, "exchange": "NASDAQ"},
        {"code": "AMDX", "name": "Another Company", "asset_class": "stock", "provider": "twelvedata",
         "provider_symbol": "AMDX", "precision": 2, "exchange": "NASDAQ"},
        {"code": "XAU_USD", "name": "Clash", "asset_class": "stock", "provider": "twelvedata",
         "provider_symbol": "XAU_USD", "precision": 2, "exchange": "NYSE"},
    ])
    db.close()


def test_empty_refresh_never_wipes_the_list(signed_in):
    _seed(signed_in)
    from app.db import new_session

    db = new_session()
    assert directory.save(db, "oanda", []) == 0
    assert directory.lookup(db, "UK100_GBP").name == "UK 100"
    db.close()


def test_search_ranks_exact_code_first(signed_in):
    _seed(signed_in)
    results = signed_in.get("/api/markets/search", params={"q": "amd"}).json()["results"]
    assert [r["code"] for r in results][:2] == ["AMD", "AMDX"]


def test_search_by_name_and_slash_code(signed_in):
    _seed(signed_in)
    assert signed_in.get("/api/markets/search", params={"q": "uk 100"}).json()["results"][0]["code"] == "UK100_GBP"
    codes = [r["code"] for r in signed_in.get("/api/markets/search", params={"q": "eur/usd"}).json()["results"]]
    assert codes[0] == "EUR_USD"


def test_search_filters_by_class(signed_in):
    _seed(signed_in)
    results = signed_in.get("/api/markets/search", params={"class": "bond"}).json()["results"]
    assert [r["code"] for r in results] == ["USB10Y_USD"]


def test_builtin_markets_findable_before_list_loads(signed_in):
    results = signed_in.get("/api/markets/search", params={"q": "gold"}).json()["results"]
    assert results[0]["code"] == "XAU_USD"


def test_ticker_clashing_with_builtin_is_skipped(signed_in):
    _seed(signed_in)
    from app.db import new_session

    db = new_session()
    assert directory.lookup(db, "XAU_USD").provider == "oanda"
    db.close()


def test_chart_works_for_directory_market(signed_in):
    _seed(signed_in)
    r = signed_in.post("/api/chart", json={"symbol": "UK100_GBP", "timeframe": "1d", "limit": 100})
    assert r.status_code == 200
    assert r.json()["symbol"]["asset_class"] == "index"


def test_catalogue_reports_counts(signed_in):
    _seed(signed_in)
    counts = signed_in.get("/api/catalogue").json()["marketCounts"]
    assert counts["index"] == 2 and counts["bond"] == 1 and counts["stock"] >= 2


def test_search_requires_sign_in(client):
    assert client.get("/api/markets/search", params={"q": "a"}).status_code == 401
