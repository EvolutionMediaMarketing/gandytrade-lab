"""Alpha Vantage, read-only: London Stock Exchange shares on the free plan.

Free plan limits (2026): 25 requests a day, 5 a minute. Daily candles come as the
latest 100 trading days; weekly and monthly candles include the full history.
No intraday data for London shares. Prices are as quoted on the LSE, which for
most shares is pence (GBX), not pounds.

Alpha Vantage only accepts the key in the URL, so the HTTP client logs are kept
at WARNING level and every log line is scrubbed of `apikey=` (see logsafe.py).
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone

from ..symbols import Symbol
from ..timeframes import Timeframe
from .base import Bar, ProviderError
from .http import safe_client

BASE_URL = "https://www.alphavantage.co/query"
PER_MINUTE = 5
PER_DAY = 25

FUNCTIONS = {
    "1d": ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    "1w": ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    "1M": ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}
SUPPORTED_TIMEFRAMES = set(FUNCTIONS)


class _Budget:
    """Keeps us inside the free plan, so one busy afternoon can't use up the day's allowance."""

    def __init__(self) -> None:
        self.minute: deque[float] = deque()
        self.day = ""
        self.used_today = 0
        self.lock = threading.Lock()

    def try_acquire(self) -> str | None:
        with self.lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if today != self.day:
                self.day, self.used_today = today, 0
            now = time.monotonic()
            while self.minute and now - self.minute[0] > 60:
                self.minute.popleft()
            if self.used_today >= PER_DAY:
                return "UK share data: today's free allowance (25 requests) is used up. Saved prices are shown; new ones tomorrow."
            if len(self.minute) >= PER_MINUTE:
                return "UK share data: free plan allows 5 requests a minute. Try again shortly."
            self.minute.append(now)
            self.used_today += 1
            return None


budget = _Budget()


def fetch_candles(api_key: str, symbol: Symbol, tf: Timeframe, count: int, client=None) -> list[Bar]:
    if not api_key:
        raise ProviderError("Alpha Vantage key not set.")
    if tf.code not in FUNCTIONS:
        raise ProviderError("UK shares are available daily, weekly and monthly on the free data feed (no intraday).")
    blocked = budget.try_acquire()
    if blocked:
        raise ProviderError(blocked)

    function, series_key = FUNCTIONS[tf.code]
    params = {"function": function, "symbol": symbol.provider_symbol, "apikey": api_key}
    own = client is None
    client = client or safe_client()
    try:
        resp = client.get(BASE_URL, params=params)
    except Exception as exc:
        raise ProviderError(f"Couldn't reach Alpha Vantage: {exc.__class__.__name__}.") from exc
    finally:
        if own:
            client.close()

    if resp.status_code != 200:
        raise ProviderError(f"Alpha Vantage returned an error ({resp.status_code}).")
    data = resp.json()
    if "Error Message" in data:
        raise ProviderError(f"Alpha Vantage doesn't recognise {symbol.name} ({symbol.code}).")
    if series_key not in data:
        # Rate-limit and premium notices come back as "Note" or "Information".
        raise ProviderError("UK share data: Alpha Vantage's free limit was reached. Saved prices are shown.")

    bars: list[Bar] = []
    for day, v in data[series_key].items():
        try:
            ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            bars.append(Bar(ts, float(v["1. open"]), float(v["2. high"]), float(v["3. low"]),
                            float(v["4. close"]), float(v.get("5. volume") or 0)))
        except (KeyError, ValueError):
            continue
    bars.sort(key=lambda b: b.ts)
    return bars[-count:]
