import httpx

from app.market.providers import oanda, twelvedata
from app.market.symbols import get_symbol
from app.market.timeframes import get_timeframe


def test_catalogue(signed_in):
    data = signed_in.get("/api/catalogue").json()
    codes = {s["code"] for s in data["symbols"]}
    assert {"EUR_USD", "XAU_USD", "BCO_USD", "AAPL", "SPY"} <= codes
    assert any(i["type"] == "ichimoku" for i in data["indicators"])
    assert data["dataSources"] == {"oanda": False, "twelvedata": False, "alphavantage": False}


def test_chart_uses_labelled_sample_data_without_keys(signed_in):
    r = signed_in.post("/api/chart", json={"symbol": "EUR_USD", "timeframe": "1h", "limit": 300})
    assert r.status_code == 200
    data = r.json()
    assert data["sample"] is True and data["source"] == "sample"
    assert "not real prices" in data["warnings"][0]
    assert len(data["bars"]) == 300
    times = [b["time"] for b in data["bars"]]
    assert times == sorted(times)


def test_chart_indicators_and_ichimoku_projection(signed_in):
    body = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "style": "heikin_ashi",
        "limit": 300,
        "indicators": [
            {"id": "a", "type": "sma", "params": {"length": 20}},
            {"id": "b", "type": "ichimoku", "params": {}},
            {"id": "c", "type": "rsi", "params": {"length": 9999}},
            {"id": "d", "type": "vwap"},
            {"id": "e", "type": "macd"},
        ],
    }
    data = signed_in.post("/api/chart", json=body).json()
    by_id = {i["id"]: i for i in data["indicators"]}
    assert len(by_id["a"]["lines"][0]["values"]) == 300 - 19
    assert by_id["c"]["params"]["length"] == 100  # clamped to the allowed range
    assert by_id["d"]["note"]  # VWAP is intraday-only
    assert len(data["futureTimes"]) == 25
    lead_a = next(l for l in by_id["b"]["lines"] if l["key"] == "lead_a")
    assert lead_a["values"][-1]["time"] == data["futureTimes"][-1]
    assert by_id["b"]["fill"]["twoTone"] is True


def test_chart_rejects_unknown_symbol(signed_in):
    assert signed_in.post("/api/chart", json={"symbol": "NOPE"}).status_code == 400


def test_oanda_only_calls_practice_candles():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"candles": [
                {"time": "2024-01-02T10:00:00.000000000Z", "volume": 42, "complete": True,
                 "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"}},
            ]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bars = oanda.fetch_candles("token", get_symbol("EUR_USD"), get_timeframe("1h"), 10, client=client)
    assert bars[0].close == 1.15 and bars[0].ts == 1704189600
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert req.url.host == "api-fxpractice.oanda.com"
    assert req.url.path == "/v3/instruments/EUR_USD/candles"


def test_twelvedata_parse_and_error():
    def ok(request):
        return httpx.Response(200, json={"status": "ok", "values": [
            {"datetime": "2024-01-03", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"},
            {"datetime": "2024-01-02", "open": "1", "high": "2", "low": "0.5", "close": "1.2", "volume": "10"},
        ]})

    twelvedata.limiter.calls.clear()
    bars = twelvedata.fetch_candles("key", get_symbol("AAPL"), get_timeframe("1d"), 10,
                                    client=httpx.Client(transport=httpx.MockTransport(ok)))
    assert [b.close for b in bars] == [1.2, 1.5]

    def err(request):
        return httpx.Response(200, json={"status": "error", "message": "bad symbol"})

    import pytest

    from app.market.providers.base import ProviderError

    with pytest.raises(ProviderError):
        twelvedata.fetch_candles("key", get_symbol("AAPL"), get_timeframe("1d"), 10,
                                 client=httpx.Client(transport=httpx.MockTransport(err)))
