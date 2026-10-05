"""Automatic paper trading: runs act only on new finished candles, follow the rules exactly,
wait for closed markets, and never get round the account's safeguards."""

import time

import pandas as pd
import pytest

from app.market.providers.base import Bar
from app.paper import auto
from app.paper import service as paper
from app.strategies.base import Param, Rules, Side, Strategy
from app.strategies.library import STRATEGIES

HOUR = 3600
NOW = int(time.time())


def _above(df: pd.DataFrame, _p: dict) -> Rules:
    """Test rules: buy while the close is above 100, short while below; exit when it crosses back."""
    c = df["close"]
    long = Side({"Close above 100": c > 100}, exit=c < 100, stop=c - 1.0, exit_label="Close below 100")
    short = Side({"Close below 100": c < 100}, exit=c > 100, stop=c + 1.0, exit_label="Close above 100")
    return Rules(long, short)


RULE = Strategy("test_above", "Above 100", "test", [], "", "", "", [Param("n", "n", 1, 1, 5)], _above)


class Feed:
    """The finished candles and current price the run sees."""

    def __init__(self):
        self.closes = [99.0] * 80
        self.mid = 99.0
        self.fresh = True

    def bars(self):
        start = (NOW // HOUR) * HOUR - 100 * HOUR  # each added candle is one hour later
        return [Bar(start + i * HOUR, c, c + 0.2, c - 0.2, c, 0) for i, c in enumerate(self.closes)]

    def add(self, close: float, mid: float | None = None):
        self.closes.append(close)
        self.mid = close if mid is None else mid


@pytest.fixture()
def feed(monkeypatch):
    f = Feed()
    monkeypatch.setitem(STRATEGIES, RULE.key, RULE)
    monkeypatch.setattr(auto, "_finished_bars", lambda db, symbol, tf: (f.bars(), False))
    monkeypatch.setattr(auto.backtests, "run", lambda db, req: {
        "metrics": {"returnPct": 5.0, "annualPct": 2.0, "trades": 40, "winRate": 45.0, "avgR": 0.2,
                    "profitFactor": 1.2, "maxDrawdownPct": 8.0, "years": 4.0},
        "buyHold": {"returnPct": 3.0}})

    def quote(db, symbol):
        ts = NOW if f.fresh else NOW - 3 * 86400
        return paper.Quote(f.mid, ts, "oanda", False, [Bar(ts - 60, f.mid, f.mid, f.mid, f.mid, 0)], "1m")

    monkeypatch.setattr(paper, "latest_quote", quote)
    return f


def _accounts(client):
    return {a["mode"]: a for a in client.get("/api/paper/accounts").json()["accounts"]}


def _start(client, account_id, **kw):
    body = {"account_id": account_id, "symbol": "GBP_USD", "timeframe": "1h", "strategy": RULE.key, "direction": "both"}
    body.update(kw)
    return client.post("/api/paper/auto", json=body)


def _step(run_id):
    from app.db import new_session
    from app.models import AutoRun

    db = new_session()
    try:
        run = db.get(AutoRun, run_id)
        out = auto.step(db, run)
        db.commit()
        return out, run.last_message
    finally:
        db.close()


def _trades(client, account_id):
    d = client.get(f"/api/paper/accounts/{account_id}").json()
    return d["open"], d["closed"]


def test_decide_follows_the_rules():
    f = Feed()
    f.add(101)
    d = auto.decide(f.bars(), RULE, {}, "both", 0)
    assert d.entry == (1, 100.0, None) and not d.exit_label
    d = auto.decide(f.bars(), RULE, {}, "both", 1)  # already holding the buy: nothing new
    assert d.entry is None and not d.exit_label
    f.add(98)
    d = auto.decide(f.bars(), RULE, {}, "both", 1)  # exit the buy, and the same candle sets up a short
    assert d.exit_label == "Close below 100" and d.entry == (-1, 99.0, None)
    d = auto.decide(f.bars(), RULE, {}, "long", 1)  # long-only runs never short
    assert d.exit_label and d.entry is None


def test_run_ignores_old_signals_and_trades_new_ones(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    feed.closes[-1] = 101  # a setup that was already there before the run started
    r = _start(signed_in, cfd)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "running" and run["backtest"]["trades"] == 40
    assert _step(run["id"])[0] == ""  # nothing new yet
    assert _trades(signed_in, cfd)[0] == []

    feed.add(101.5)
    out, _ = _step(run["id"])
    assert "opened a buy" in out
    opened, _ = _trades(signed_in, cfd)
    assert len(opened) == 1
    t = opened[0]
    assert t["source"] == "auto" and t["strategy"] == RULE.key and t["autoRunId"] == run["id"]
    assert t["stop"] == pytest.approx(100.5) and t["ruleScore"] == 100
    assert t["riskGbp"] == pytest.approx(2.0, rel=0.05)  # 1% of £200

    feed.add(102)  # still above: hold
    out, msg = _step(run["id"])
    assert out == "" and "holding" in msg

    feed.add(99.5)  # crosses below: exit the buy and go short
    out, _ = _step(run["id"])
    assert "closed the buy" in out and "opened a short" in out
    opened, closed = _trades(signed_in, cfd)
    assert closed[0]["exitReason"] == "Exit rule: Close below 100"
    assert opened[0]["side"] == "short"

    listed = signed_in.get(f"/api/paper/auto?account_id={cfd}").json()["runs"][0]
    assert listed["live"]["trades"] == 1 and listed["openTradeId"] == opened[0]["id"]


def test_waits_for_a_closed_market(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    feed.add(101)
    feed.fresh = False
    out, msg = _step(run["id"])
    assert out == "" and "market is closed" in msg
    assert _trades(signed_in, cfd)[0] == []
    feed.fresh = True  # it opens: the same candle is acted on
    out, _ = _step(run["id"])
    assert "opened a buy" in out


def test_safeguards_still_apply(signed_in, feed):
    from app.db import new_session
    from app.models import PaperAccount

    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    db = new_session()
    acct = db.get(PaperAccount, cfd)
    acct.halted, acct.halt_reason = True, "Paused: test"
    db.commit()
    db.close()
    feed.add(101)
    out, _ = _step(run["id"])
    assert "safeguards stopped it" in out and "Paused: test" in out
    assert _trades(signed_in, cfd)[0] == []


def test_real_shares_account_only_buys(signed_in, feed):
    cash = _accounts(signed_in)["cash"]["id"]
    run = _start(signed_in, cash, direction="both").json()
    assert run["direction"] == "long"
    feed.add(98)  # a short setup: ignored
    out, msg = _step(run["id"])
    assert out == "" and "no setup" in msg


def test_setup_checks(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    assert _start(signed_in, cfd, symbol="AAPL", timeframe="5m").status_code == 400  # too short for the US share allowance
    assert _start(signed_in, cfd, strategy="london_breakout", timeframe="1d").status_code == 400  # scalpers need short candles
    assert _start(signed_in, cfd, strategy="buy_hold").status_code == 400
    assert _start(signed_in, cfd).status_code == 200
    r = _start(signed_in, cfd)  # same market on the same account: results would mix
    assert r.status_code == 400 and "separate paper account" in r.json()["detail"]
    opts = signed_in.get("/api/paper/auto/options").json()
    assert all(s["key"] not in ("buy_hold", "support_resistance") for s in opts["strategies"])


def test_pause_resume_stop(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    feed.add(101)
    _step(run["id"])
    r = signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "pause"}).json()
    assert r["status"] == "paused" and "stays open" in r["message"]
    feed.add(98)  # while paused: ignored, even after resuming
    r = signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "resume"}).json()
    assert r["status"] == "running"
    assert _step(run["id"])[0] == ""
    r = signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "stop", "close_open": True}).json()
    assert r["status"] == "stopped" and "closed" in r["message"]
    opened, closed = _trades(signed_in, cfd)
    assert opened == [] and len(closed) == 1
    assert signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "resume"}).status_code == 400


def test_worker_runs_due_runs_and_pauses_after_repeated_problems(signed_in, feed, monkeypatch):
    from app import worker
    from app.db import new_session
    from app.models import AutoRun

    monkeypatch.setattr(auto, "next_open", lambda provider: None)  # treat the market as open, whatever day the test runs
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    feed.add(101)
    looked: dict = {}
    worker.run_once({}, looked)
    assert len(_trades(signed_in, cfd)[0]) == 1
    worker.run_once({}, looked)  # looked at a moment ago: not due again yet
    assert looked[run["id"]] > 0

    def broken(db, symbol, tf):
        raise ValueError("price service down")

    monkeypatch.setattr(auto, "_finished_bars", broken)
    db = new_session()
    for _ in range(auto.MAX_ERRORS):
        auto.run_due(db, {}, time.time() + 10 * HOUR)
    r = db.get(AutoRun, run["id"])
    assert r.status == "paused" and "problems in a row" in r.last_message
    db.close()


def test_closed_market_is_not_polled(feed, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.models import AutoRun

    run = AutoRun(id=7, timeframe="1h", last_bar_ts=NOW - 10 * HOUR)
    monkeypatch.setattr(auto, "next_open", lambda provider: datetime.now(timezone.utc) + timedelta(days=1))
    assert not auto.due(run, "oanda", {}, time.time())
    monkeypatch.setattr(auto, "next_open", lambda provider: None)
    assert auto.due(run, "oanda", {}, time.time())
    assert not auto.due(run, "oanda", {7: time.time()}, time.time())  # looked a moment ago


def test_missed_candles_close_late_but_never_enter_late():
    f = Feed()
    f.add(101)
    first_new = len(f.closes)
    f.add(98)   # exit met here, but the run missed this candle
    f.add(99)   # the latest: still below 100
    d = auto.decide(f.bars(), RULE, {}, "long", 1, first_new)
    assert d.exit_label and d.late_exit and d.entry is None
    d = auto.decide(f.bars(), RULE, {}, "both", 1, first_new)  # flat after the late exit: the short is still set up now
    assert d.entry == (-1, 100.0, None)
    g = Feed()
    first_new = len(g.closes)
    g.add(101)  # an entry on a missed candle...
    g.add(99)   # ...but not on the latest: nothing is opened late
    d = auto.decide(g.bars(), RULE, {}, "long", 0, first_new)
    assert d.entry is None


def test_step_reports_missed_candles(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd, direction="long").json()
    feed.add(101)
    _step(run["id"])
    feed.add(98)
    feed.add(98.5)
    out, _ = _step(run["id"])
    assert "missed" in out and "closed late" in out


def test_uk_shares_cannot_run_automatically(signed_in, feed):
    cash = _accounts(signed_in)["cash"]["id"]
    r = _start(signed_in, cash, symbol="BP.LON", timeframe="1d")
    assert "UK shares" in r.json()["detail"]
    assert r.status_code == 400, r.text


def test_delete_account_needs_its_name_and_removes_everything(signed_in, feed):
    from app.db import new_session
    from app.models import AutoRun, PaperEvent, PaperTrade, SecurityEvent

    cfd = _accounts(signed_in)["cfd"]
    run = _start(signed_in, cfd["id"]).json()
    feed.add(101)
    _step(run["id"])
    r = signed_in.post(f"/api/paper/accounts/{cfd['id']}/delete", json={"confirm_name": "wrong"})
    assert r.status_code == 400 and "nothing was deleted" in r.json()["detail"]
    r = signed_in.post(f"/api/paper/accounts/{cfd['id']}/delete", json={"confirm_name": cfd["name"]})
    assert r.status_code == 200 and r.json()["trades"] == 1 and r.json()["runs"] == 1
    assert "cfd" not in _accounts(signed_in)
    db = new_session()
    assert db.query(PaperTrade).count() == 0 and db.query(PaperEvent).count() == 0 and db.query(AutoRun).count() == 0
    assert db.query(SecurityEvent).filter(SecurityEvent.event == "paper_account_deleted").count() == 1
    db.close()


def test_account_list_counts_runs(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    run = _start(signed_in, cfd).json()
    assert _accounts(signed_in)["cfd"]["autoRunning"] == 1
    signed_in.post(f"/api/paper/auto/{run['id']}", json={"action": "pause"})
    a = _accounts(signed_in)["cfd"]
    assert a["autoRunning"] == 0 and a["autoPaused"] == 1


def test_basket_starts_all_or_nothing_and_can_stop_old_runs(signed_in, feed):
    cfd = _accounts(signed_in)["cfd"]["id"]
    old = _start(signed_in, cfd, symbol="EUR_USD").json()
    other = signed_in.post("/api/paper/accounts", json={"name": "New basket", "starting_balance": 200, "mode": "cfd"}).json()["id"]
    body = {"account_id": other, "markets": ["GBP_USD", "EUR_USD", "XAU_USD"], "timeframe": "1h",
            "strategy": RULE.key, "params": {"n": 3}, "direction": "long"}
    # One market that can't trade automatically: nothing starts.
    bad = signed_in.post("/api/paper/auto/basket", json={**body, "markets": ["GBP_USD", "AAPL"], "timeframe": "5m"})
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Nothing was started")
    assert signed_in.get(f"/api/paper/auto?account_id={other}").json()["runs"] == []
    # Too many runs at once is refused before anything changes.
    monkey_max = auto.MAX_RUNNING
    auto.MAX_RUNNING = 3
    try:
        r = signed_in.post("/api/paper/auto/basket", json=body)
        assert r.status_code == 400 and "but the most at once is 3" in r.json()["detail"]
        # ...unless the old run is stopped in the same go.
        r = signed_in.post("/api/paper/auto/basket", json={**body, "stop_run_ids": [old["id"]]})
        assert r.status_code == 200, r.text
    finally:
        auto.MAX_RUNNING = monkey_max
    runs = r.json()["runs"]
    assert {x["symbol"] for x in runs} == {"GBP_USD", "EUR_USD", "XAU_USD"}
    assert all(x["params"] == {"n": 3} and x["accountId"] == other and x["status"] == "running" for x in runs)
    olds = signed_in.get(f"/api/paper/auto?account_id={cfd}").json()["runs"]
    assert olds[0]["status"] == "stopped" and "new basket" in olds[0]["message"]
    # The same basket again on the same account would mix results.
    again = signed_in.post("/api/paper/auto/basket", json=body)
    assert again.status_code == 400 and "Nothing was started" in again.json()["detail"]


def test_basket_new_account_is_made_only_if_everything_starts(signed_in, feed):
    before = len(signed_in.get("/api/paper/accounts").json()["accounts"])
    body = {"account_id": None, "new_account_name": "My basket", "markets": ["GBP_USD", "AAPL"], "timeframe": "5m",
            "strategy": RULE.key, "direction": "long"}
    bad = signed_in.post("/api/paper/auto/basket", json=body)
    assert bad.status_code == 400 and "Nothing was started" in bad.json()["detail"]
    assert len(signed_in.get("/api/paper/accounts").json()["accounts"]) == before  # no empty account left behind
    ok = signed_in.post("/api/paper/auto/basket", json={**body, "markets": ["GBP_USD", "EUR_USD"], "timeframe": "1h"})
    assert ok.status_code == 200, ok.text
    accts = signed_in.get("/api/paper/accounts").json()["accounts"]
    made = next(a for a in accts if a["name"] == "My basket")
    assert all(r["accountId"] == made["id"] for r in ok.json()["runs"]) and made["mode"] == "cfd"
    # The same name again is refused, rather than making a look-alike account.
    again = signed_in.post("/api/paper/auto/basket", json={**body, "markets": ["GBP_USD", "EUR_USD"], "timeframe": "1h"})
    assert again.status_code == 400 and "already have a paper account called" in again.json()["detail"]
    dup = signed_in.post("/api/paper/accounts", json={"name": "my basket", "starting_balance": 200, "mode": "cfd"})
    assert dup.status_code == 400
