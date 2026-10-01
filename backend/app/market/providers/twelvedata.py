"""Twelve Data time series, read-only. The free plan allows 8 requests a minute."""

import threading
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from ..symbols import Symbol
from ..timeframes import Timeframe
from .base import Bar, ProviderError
from .http import safe_client

BASE_URL = "https://api.twelvedata.com/time_series"
REQUESTS_PER_MINUTE = 8


class _RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self.lock:
            now = time.monotonic()
            while self.calls and now - self.calls[0] > 60:
                self.calls.popleft()
            if len(self.calls) >= self.per_minute:
                return False
            self.calls.append(now)
            return True


limiter = _RateLimiter(REQUESTS_PER_MINUTE)


def _parse_time(value: str) -> int:
    fmt = "%Y-%m-%d %H:%M:%S" if " " in value else "%Y-%m-%d"
    return int(datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp())


def fetch_candles(
    api_key: str,
    symbol: Symbol,
    tf: Timeframe,
    count: int,
    client: httpx.Client | None = None,
) -> list[Bar]:
    if not api_key:
        raise ProviderError("Twelve Data key not set.")
    if not limiter.try_acquire():
        raise ProviderError("Free plan limit reached (8 requests a minute). Try again shortly.")
    params = {
        "symbol": symbol.provider_symbol,
        "interval": tf.twelvedata,
        "outputsize": min(count, 5000),
        "timezone": "UTC",
        "order": "ASC",
    }
    # The key goes in a header, not the URL, so it can't end up in anyone's logs.
    headers = {"Authorization": f"apikey {api_key}"}
    own_client = client is None
    client = client or safe_client()
    try:
        resp = client.get(BASE_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Couldn't reach Twelve Data: {exc.__class__.__name__}.") from exc
    finally:
        if own_client:
            client.close()

    if resp.status_code != 200:
        raise ProviderError(f"Twelve Data returned an error ({resp.status_code}).")
    data = resp.json()
    if data.get("status") == "error":
        raise ProviderError(f"Twelve Data: {data.get('message', 'unknown error')}")

    bars: list[Bar] = []
    for v in data.get("values", []):
        try:
            bars.append(
                Bar(
                    ts=_parse_time(v["datetime"]),
                    open=float(v["open"]),
                    high=float(v["high"]),
                    low=float(v["low"]),
                    close=float(v["close"]),
                    volume=float(v.get("volume") or 0),
                )
            )
        except (KeyError, ValueError):
            continue
    bars.sort(key=lambda b: b.ts)
    return bars
