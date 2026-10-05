"""Scalping: UK session hours (with British Summer Time), one London breakout a day, profit targets
in the backtester, everything closed by the end of the session, and months of short-candle history."""

import math
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.backtest import engine
from app.backtest.costs import Costs
from app.market.fx import Converter
from app.market.providers.base import Bar
from app.risk.guard import RiskSettings
from app.strategies.base import Param, Rules, Side, Strategy, uk_clock
from app.strategies.library import STRATEGIES

UK = ZoneInfo("Europe/London")
FIVE = 300


def uk_ts(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=UK).timestamp())


def settings(**kw):
    base = dict(start_balance=1000.0, mode="cfd", direction="both", risk=RiskSettings(1.0, 50.0, 90.0).cleaned(),
                leverage=30.0, costs=Costs(0.0, 0.0))
    base.update(kw)
    return engine.Settings(**base)


class Flat(Converter):
    def __init__(self):
        pass

    def rate(self, ts):
        return 1.0


def day_of_bars(y, m, d, path):
    """5-minute candles from 07:00 to 13:00 UK; `path(t)` gives the close at UK minute t."""
    out, prev = [], None
    for minute in range(7 * 60, 13 * 60, 5):
        c = path(minute)
        o = prev if prev is not None else c
        out.append(Bar(uk_ts(y, m, d, minute // 60, minute % 60), o, max(o, c) + 0.01, min(o, c) - 0.01, c, 1))
        prev = c
    return out


def test_uk_clock_handles_summer_time():
    ts = [uk_ts(2026, 1, 15, 8, 0), uk_ts(2026, 7, 1, 8, 0), uk_ts(2026, 7, 1, 8, 5)]
    start, end, day, step = uk_clock(pd.DataFrame({"ts": ts}))
    assert list(start) == [480, 480, 485] and step == 5 and list(end)[1:] == [485, 490]
    assert datetime.fromtimestamp(ts[1], tz=timezone.utc).hour == 7  # 08:00 UK is 07:00 UTC in summer


def test_london_breakout_one_trade_a_day_with_target_and_session_exit():
    def summer(t):  # quiet range 100.0-100.2 until 08:30, breaks up at 09:00, then runs up
        if t < 8 * 60 + 30:
            return 100.1 + (0.1 if t % 10 == 0 else -0.1)
        if t < 9 * 60:
            return 100.1
        return 100.5 + (t - 9 * 60) * 0.01

    def winter(t):  # breaks down at 09:00, drifts sideways, never reaches the target
        if t < 8 * 60 + 30:
            return 100.1 + (0.1 if t % 10 == 0 else -0.1)
        if t < 9 * 60:
            return 100.1
        return 99.8 - (0.02 if t % 10 == 0 else 0.0)

    bars = day_of_bars(2026, 7, 1, summer) + day_of_bars(2026, 1, 15, winter)
    bars.sort(key=lambda b: b.ts)
    res = engine.run(bars, STRATEGIES["london_breakout"], {}, settings(), Flat())
    assert len(res.trades) == 2  # one a day, despite repeated closes outside the range
    jan, jul = res.trades  # January comes first in time
    assert jul.side == 1 and jul.exit_reason == "Target reached"
    assert jul.stop == pytest.approx(100.0 - 0.01, abs=0.02)  # the bottom of the opening range
    assert jan.side == -1 and jan.exit_reason.startswith("End of the session")
    exit_uk = datetime.fromtimestamp(jan.exit_ts, tz=UK)
    assert (exit_uk.hour, exit_uk.minute) == (12, 0)


def test_scalpers_only_trade_in_session_and_never_hold_overnight():
    rnd = random.Random(5)
    ts0, price, bars = uk_ts(2026, 3, 2, 0, 0), 1.10, []
    for i in range(12 * 24 * 10):  # ten days of 5-minute candles, around the clock
        o = price
        price *= math.exp(0.00003 * math.sin(i / 50) + rnd.gauss(0, 0.0007))
        bars.append(Bar(ts0 + i * FIVE, o, max(o, price) * 1.0002, min(o, price) * 0.9998, price, 1))
    for key, start_h, end_h in (("scalp_pullback", 8, 17), ("scalp_range_fade", 8, 16)):
        res = engine.run(bars, STRATEGIES[key], {}, settings(), Flat())
        assert res.trades, key
        for t in res.trades:
            entry = datetime.fromtimestamp(t.entry_ts, tz=UK)
            exit_ = datetime.fromtimestamp(t.exit_ts, tz=UK)
            assert start_h * 60 <= entry.hour * 60 + entry.minute <= end_h * 60, key
            assert entry.date() == exit_.date(), f"{key} held a trade overnight"
            assert exit_.hour * 60 + exit_.minute <= end_h * 60 + 5, key


def test_scalpers_do_nothing_on_daily_candles():
    bars = [Bar(1_700_000_000 + i * 86400, 100 + i, 101 + i, 99 + i, 100.5 + i, 1) for i in range(300)]
    for key in ("london_breakout", "scalp_pullback", "scalp_range_fade"):
        assert engine.run(bars, STRATEGIES[key], {}, settings(), Flat()).trades == []


def _one_trade(highs_lows, target=101.0):
    """A strategy that buys once at the first open with stop 99 and the given target."""
    n = len(highs_lows)

    def compute(df, _p):
        first = pd.Series([i == 0 for i in range(n)], index=df.index)
        return Rules(Side({"go": first}, exit=pd.Series(False, index=df.index), stop=pd.Series(99.0, index=df.index),
                          target=pd.Series(target, index=df.index)))

    s = Strategy("t", "t", "", [], "", "", "", [Param("x", "x", 1, 1, 2)], compute)
    bars = [Bar(1_700_000_000 + i * 3600, o, h, lo, c, 1) for i, (o, h, lo, c) in enumerate(highs_lows)]
    return engine.run(bars, s, {}, settings(direction="long"), Flat()).trades[0]


def test_target_hit_inside_a_candle():
    t = _one_trade([(100, 100.2, 99.9, 100), (100, 100.5, 99.8, 100.3), (100.3, 101.4, 100.2, 101.2), (101, 101, 101, 101)])
    assert t.exit_reason == "Target reached" and t.exit_mid == 101.0


def test_stop_counts_first_when_a_candle_reaches_both():
    t = _one_trade([(100, 100.2, 99.9, 100), (100, 100.5, 99.8, 100.3), (100.3, 101.4, 98.9, 100.0), (100, 100, 100, 100)])
    assert t.exit_reason == "Stop-loss"


def test_gap_through_target_fills_at_the_open():
    t = _one_trade([(100, 100.2, 99.9, 100), (100, 100.5, 99.8, 100.3), (101.6, 101.8, 101.5, 101.7), (101, 101, 101, 101)])
    assert t.exit_reason == "Target reached" and t.exit_mid == 101.6


def test_robustness_check_never_moves_session_hours():
    from app import research

    for v in research.variants(STRATEGIES["london_breakout"]):
        assert v["open_hour"] == 8 and v["exit_hour"] == 12
    fade = research.variants(STRATEGIES["scalp_range_fade"])
    assert {v["rsi_level"] for v in fade} == {20} and {v["adx_max"] for v in fade} == {20}
    assert [v["length"] for v in fade] == [15, 30]


def test_history_is_fetched_in_pages_for_short_timeframes(client, monkeypatch):
    from app.db import new_session
    from app.market import service
    from app.market.directory import lookup
    from app.market.timeframes import get_timeframe

    calls = []
    now = int(datetime.now(timezone.utc).timestamp())

    def fake_fetch(token, symbol, tf, count, client=None, start=None):
        calls.append(start)
        if start is None:
            begin = now - count * tf.seconds
        else:
            begin = start
        out = []
        for i in range(min(count, 5000)):
            ts = begin + i * tf.seconds
            if ts > now:
                break
            out.append(Bar(ts, 1, 1, 1, 1, 0))
        return out

    monkeypatch.setattr(service.oanda, "fetch_candles", fake_fetch)
    monkeypatch.setattr(service, "_provider_key", lambda symbol: "token")
    db = new_session()
    tf = get_timeframe("5m")
    sym = lookup(db, "EUR_USD")
    result = service.get_history(db, sym, tf)
    db.close()
    pages = [c for c in calls if c is not None]
    assert len(pages) >= 10  # about six months of 5-minute candles, 5,000 at a time
    assert len(result.bars) > 40_000
    assert service.history_cap(sym, tf) >= len(result.bars)
    assert service.history_cap(sym, get_timeframe("1d")) == service.MAX_HISTORY


def test_no_new_trade_in_the_last_minutes_of_a_session():
    def late_break(t):  # the range only breaks on the 11:50 candle
        if t < 8 * 60 + 30:
            return 100.1 + (0.1 if t % 10 == 0 else -0.1)
        return 100.1 if t < 11 * 60 + 50 else 100.6
    bars = day_of_bars(2026, 7, 1, late_break)
    assert engine.run(bars, STRATEGIES["london_breakout"], {}, settings(), Flat()).trades == []


def test_robustness_range_stays_on_its_steps():
    from app import research

    assert [v["range_minutes"] for v in research.variants(STRATEGIES["london_breakout"])] == [15, 45]


def test_long_gap_fill_is_capped(client, monkeypatch):
    from datetime import datetime, timezone

    from app.db import new_session
    from app.market import service
    from app.market.directory import lookup
    from app.market.timeframes import get_timeframe
    from app.models import PriceBar

    db = new_session()
    now = datetime.now(timezone.utc)
    old = int(now.timestamp()) - 400 * 86400
    db.add(PriceBar(source="oanda", symbol="EUR_USD", timeframe="1m", ts=old, open=1, high=1, low=1, close=1, volume=0))
    db.commit()
    start = service._page_start(db, lookup(db, "EUR_USD"), get_timeframe("1m"), 500, False, now)
    assert start >= int(now.timestamp()) - service.DEEP_DAYS["1m"] * 86400 - 5
    db.close()


def test_recorded_spreads_are_used_for_fills():
    from app.backtest.engine import Book

    book = Book(Costs(spread_pct=0.01, slippage_pct=0.0), Flat(), "cfd")
    assert book.fill(100.0, True) == pytest.approx(100.005)  # typical: half of 0.01%
    assert book.fill(100.0, True, 0.04) == pytest.approx(100.02)  # recorded: half of 0.04
    assert book.fill(100.0, False, 0.04) == pytest.approx(99.98)
    assert book.fill(100.0, True, float("nan")) == pytest.approx(100.005)  # missing: typical
    own = Book(Costs(spread_pct=0.01, slippage_pct=0.0), Flat(), "cfd", market_spreads=False)
    assert own.fill(100.0, True, 0.04) == pytest.approx(100.005)  # your own setting wins


def test_wide_recorded_spreads_cost_more():
    narrow = [(100, 100.2, 99.9, 100), (100, 100.5, 99.8, 100.3), (100.3, 101.4, 100.2, 101.2), (101, 101, 101, 101)]

    def run(spread):
        n = len(narrow)

        def compute(df, _p):
            first = pd.Series([i == 0 for i in range(n)], index=df.index)
            return Rules(Side({"go": first}, exit=pd.Series(False, index=df.index), stop=pd.Series(99.0, index=df.index),
                              target=pd.Series(101.0, index=df.index)))

        s = Strategy("t", "t", "", [], "", "", "", [Param("x", "x", 1, 1, 2)], compute)
        bars = [Bar(1_700_000_000 + i * 300, o, h, lo, c, 1, spread) for i, (o, h, lo, c) in enumerate(narrow)]
        return engine.run(bars, s, {}, settings(direction="long", costs=Costs(0.01, 0.0)), Flat()).trades[0]

    cheap, dear = run(0.01), run(0.2)
    assert dear.costs_gbp > cheap.costs_gbp * 5
    assert dear.entry_price == pytest.approx(100.1)  # opened at 100 mid + half of 0.2


def test_oanda_spread_parsing():
    from app.market.providers.oanda import _spread

    assert _spread({"o": "1.1000", "c": "1.1002"}, {"o": "1.1001", "c": "1.1005"}) == pytest.approx(0.0003)
    assert _spread(None, {"o": "1"}) is None
    assert _spread({"o": "1.2", "c": "1.2"}, {"o": "1.1", "c": "1.1"}) is None  # crossed: ignore


def test_weekly_history_never_asks_for_candles_before_2002(client, monkeypatch):
    """5,000 weekly candles would start in the 1920s, which OANDA refuses: the full download is capped."""
    from datetime import datetime, timezone

    from app.db import new_session
    from app.market import service
    from app.market.directory import lookup
    from app.market.providers.base import ProviderError
    from app.market.timeframes import get_timeframe

    now = int(datetime.now(timezone.utc).timestamp())
    asked = []

    def fake_fetch(token, symbol, tf, count, client=None, start=None):
        asked.append(count)
        if now - count * tf.seconds < 0:
            raise ProviderError("OANDA refused the request")
        return [Bar(now - (count - i) * tf.seconds, 1, 1, 1, 1, 0) for i in range(count)]

    monkeypatch.setattr(service.oanda, "fetch_candles", fake_fetch)
    monkeypatch.setattr(service, "_provider_key", lambda symbol: "token")
    week = get_timeframe("1w")
    assert 1200 < service.deep_count(week) < 1400
    assert 250 < service.deep_count(get_timeframe("1M")) < 350
    assert service.deep_count(get_timeframe("1d")) == service.MAX_HISTORY
    db = new_session()
    result = service.get_history(db, lookup(db, "XAU_USD"), week)
    db.close()
    assert asked[0] == service.deep_count(week)
    assert len(result.bars) > 1000 and not result.warnings
