"""Strategy research: scans run in slices, every result gets the five checks, and the suggestions
come only from results that pass them."""

import math
import random
from types import SimpleNamespace

import pytest

from app import research
from app.market.providers.base import Bar
from app.strategies.library import STRATEGIES

DAY = 86400


def _bars(n=1200, drift=0.0006, seed=3):
    rnd = random.Random(seed)
    price, out, ts = 100.0, [], 1_500_000_000
    for i in range(n):
        o = price
        price = max(1.0, price * math.exp(drift + rnd.gauss(0, 0.012)))
        hi, lo = max(o, price) * (1 + abs(rnd.gauss(0, 0.004))), min(o, price) * (1 - abs(rnd.gauss(0, 0.004)))
        out.append(Bar(ts + i * DAY, o, hi, lo, price, 0))
    return out


@pytest.fixture()
def history(monkeypatch):
    calls = []

    def fake(db, symbol, tf, limit=5000):
        calls.append(symbol.code)
        return SimpleNamespace(bars=_bars(seed=len(symbol.code)), sample=False, warnings=[], source="oanda")

    monkeypatch.setattr(research, "get_history", fake)
    return calls


def test_robustness_variants_change_lengths_not_levels():
    rsi = STRATEGIES["rsi_reversal"]
    short, long = research.variants(rsi)
    assert short["length"] == round(14 * 0.75) and long["length"] == 21
    assert short["oversold"] == long["oversold"] == 30 and short["exit_level"] == 55
    assert short["stop_atr"] == 2.0
    br = research.variants(STRATEGIES["breakout"])
    assert [v["entry_len"] for v in br] == [15, 30]


def test_scan_market_checks_every_result(client, history):
    from app.db import new_session

    db = new_session()
    rows, note = research.scan_market(db, "XAU_USD", "1d")
    db.close()
    assert note == ""
    expected = sum(2 if s.can_short else 1 for s in research.strategies() if not s.intraday_only)
    assert len(rows) == expected
    for r in rows:
        assert set(r["checks"]) == set(research.CHECKS)
        assert r["passed"] == sum(r["checks"].values())
        assert r["checks"]["profitable"] == (r["returnPct"] > 0)
        assert r["checks"]["enoughTrades"] == (r["trades"] >= research.MIN_TRADES)
        assert r["checks"]["robust"] == all(v > 0 for v in r["variantReturns"])
        assert r["buyHoldReturnPct"] is not None
    assert {r["strategy"] for r in rows}.isdisjoint({"buy_hold", "support_resistance"})


def test_only_oanda_markets_are_scanned(client, history):
    from app.db import new_session

    db = new_session()
    rows, note = research.scan_market(db, "AAPL", "1d")
    db.close()
    assert rows == [] and "OANDA" in note


def test_scan_runs_in_slices_and_suggests(signed_in, history, monkeypatch):
    r = signed_in.post("/api/research", json={"markets": ["XAU_USD", "XAG_USD", "AAPL"], "timeframes": ["1d"]})
    assert r.status_code == 200, r.text
    job = r.json()
    daily = sum(1 for s in research.strategies() if not s.intraday_only)
    assert job["status"] == "queued" and job["total"] == 3 * daily
    assert signed_in.post("/api/research", json={}).status_code == 400  # one at a time

    from app.db import new_session

    db = new_session()
    assert research.work(db, budget=0)  # a zero budget still does one market per pass
    db.close()
    mid = signed_in.get(f"/api/research/{job['id']}").json()
    assert mid["status"] == "running" and mid["done"] == 1

    db = new_session()
    while research.work(db, budget=60):
        pass
    db.close()
    done = signed_in.get(f"/api/research/{job['id']}").json()
    assert done["status"] == "done" and done["finishedAt"]
    assert any(s["market"] == "AAPL" for s in done["skipped"])
    summary = done["summary"]
    assert summary["tested"] == len(done["rows"]) > 0
    assert all(r["passed"] == len(research.CHECKS) for r in summary["shortlist"])
    assert all(a["held"] >= 2 for a in summary["acrossMarkets"])
    assert signed_in.get("/api/research").json()["jobs"][0]["id"] == job["id"]


def test_unknown_market_refused(signed_in):
    assert signed_in.post("/api/research", json={"markets": ["NOT_A_MARKET"]}).status_code == 400


def test_summary_ranks_and_groups():
    def row(market, strategy, passed_all, score, robust=True):
        checks = {k: True for k in research.CHECKS}
        if not passed_all:
            checks["recent"] = False
        checks["robust"] = robust
        return {"market": market, "name": market, "timeframe": "1d", "strategy": strategy, "strategyName": strategy,
                "direction": "long", "checks": checks, "passed": sum(checks.values()), "score": score,
                "annualPct": 2.0, "tradesPerYear": 4.0, "returnPct": 10.0}

    rows = [row("A", "x", True, 1.0), row("B", "x", True, 3.0), row("C", "x", False, 9.0), row("D", "y", True, 2.0, robust=False)]
    s = research.summarise(rows)
    assert [r["market"] for r in s["shortlist"]] == ["B", "A"]
    assert [r["market"] for r in s["nearMisses"]] == ["C", "D"]
    assert s["acrossMarkets"][0]["strategy"] == "x" and s["acrossMarkets"][0]["held"] == 3
    assert all(a["strategy"] != "y" for a in s["acrossMarkets"])  # held on only one market


def test_weekly_scan(signed_in, monkeypatch):
    from app import config
    from app.db import new_session
    from app.models import ResearchJob

    db = new_session()
    research.schedule_weekly(db)  # no price feed key: nothing queued
    assert db.query(ResearchJob).count() == 0
    monkeypatch.setattr(research, "get_settings", lambda: SimpleNamespace(oanda_token="x"))
    research.schedule_weekly(db)
    jobs = db.query(ResearchJob).all()
    assert len(jobs) == 1 and jobs[0].automatic
    jobs[0].status = "done"
    db.commit()
    research.schedule_weekly(db)  # less than a week since the last one
    assert db.query(ResearchJob).count() == 1
    db.close()
    config.get_settings.cache_clear()
