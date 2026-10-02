"""Live price stream: parsing, which markets are streamed, and the API."""

import time

import httpx
import pytest

from app.market import stream as stream_mod
from app.market.providers import http as safe_http
from app.market.stream import PriceStream, Tick, parse_line


def test_parse_price_and_ignore_heartbeats():
    line = ('{"type":"PRICE","time":"2026-10-02T10:53:01.123456789Z","bids":[{"price":"0.98780","liquidity":1}],'
            '"asks":[{"price":"0.98792","liquidity":1}],"instrument":"AUD_CAD","tradeable":true}')
    code, tick = parse_line(line)
    assert code == "AUD_CAD" and tick.bid == 0.98780 and tick.mid == pytest.approx(0.98786)
    assert parse_line('{"type":"HEARTBEAT","time":"2026-10-02T10:53:05.000000000Z"}') is None
    assert parse_line("not json") is None and parse_line("") is None


def test_interest_expires_and_open_trades_stay_pinned(monkeypatch):
    s = PriceStream()
    monkeypatch.setattr(s, "_ensure_thread", lambda: None)
    s.want(["EUR_USD"])
    s.pin({"AUD_CAD"})
    assert s.wanted() == {"EUR_USD", "AUD_CAD"}
    s.interest["EUR_USD"] -= stream_mod.INTEREST_SECONDS + 1
    assert s.wanted() == {"AUD_CAD"}


def test_stream_host_is_allowed_but_only_the_practice_one():
    for url in ("https://stream-fxpractice.oanda.com/v3/x", "https://api-fxpractice.oanda.com/v3/x"):
        safe_http.check_request(httpx.Request("GET", url))
    for url in ("https://stream-fxtrade.oanda.com/v3/x", "https://api-fxtrade.oanda.com/v3/x"):
        with pytest.raises(safe_http.BlockedHost):
            safe_http.check_request(httpx.Request("GET", url))


def test_live_endpoint_returns_cached_prices(signed_in, monkeypatch):
    monkeypatch.setattr(stream_mod.stream, "_ensure_thread", lambda: None)
    stream_mod.stream.prices["EUR_USD"] = Tick(1.1000, 1.1002, time.time())
    r = signed_in.get("/api/live", params={"symbols": "EUR_USD,AAPL,NOPE"})
    assert r.status_code == 200
    d = r.json()
    assert set(d["prices"]) == {"EUR_USD"}  # shares and unknown codes aren't streamed
    assert d["prices"]["EUR_USD"]["mid"] == pytest.approx(1.1001)


def test_listen_reads_prices_from_the_stream(monkeypatch):
    from app import config

    monkeypatch.setenv("GT_OANDA_TOKEN", "practice-token")
    config.get_settings.cache_clear()
    lines = [
        '{"type":"PRICE","time":"2026-10-02T10:53:01.000000000Z","bids":[{"price":"1.10000"}],"asks":[{"price":"1.10020"}],"instrument":"EUR_USD","tradeable":true}',
        '{"type":"HEARTBEAT","time":"2026-10-02T10:53:05.000000000Z"}',
        '{"type":"PRICE","time":"2026-10-02T10:53:06.000000000Z","bids":[{"price":"1.10010"}],"asks":[{"price":"1.10030"}],"instrument":"EUR_USD","tradeable":true}',
    ]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.method == "GET" and request.headers["authorization"] == "Bearer practice-token"
        if request.url.host == "api-fxpractice.oanda.com":
            return httpx.Response(200, json={"accounts": [{"id": "101-004-1-001"}]})
        assert request.url.host == "stream-fxpractice.oanda.com"
        assert request.url.path == "/v3/accounts/101-004-1-001/pricing/stream"
        assert request.url.params["instruments"] == "EUR_USD"
        return httpx.Response(200, content="\n".join(lines).encode())

    def fake_client(timeout=20):
        return httpx.Client(transport=httpx.MockTransport(handler), event_hooks={"request": [safe_http.check_request]})

    monkeypatch.setattr(stream_mod, "safe_client", fake_client)
    s = PriceStream()
    s.interest["EUR_USD"] = time.time()  # someone is watching EUR/USD
    s.last_start = time.time()
    s._listen(frozenset({"EUR_USD"}))
    assert s.prices["EUR_USD"].mid == pytest.approx(1.1002)
    assert s.status == "streaming"
    config.get_settings.cache_clear()
