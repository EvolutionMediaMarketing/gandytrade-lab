"""OANDA price candles, read-only, from the demo ("fxTrade Practice") environment only.

Safety: this module only ever calls the candles endpoint on the practice host.
The host is fixed here, not configurable, so a live account can never be
reached by the data feed. Order placement does not exist in this codebase.
"""

from datetime import datetime, timezone

import httpx

from ..symbols import Symbol
from ..timeframes import Timeframe
from .base import Bar, ProviderError
from .http import safe_client

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
CANDLES_PATH = "/v3/instruments/{instrument}/candles"


def _parse_time(value: str) -> int:
    # OANDA returns RFC 3339 with nanoseconds, e.g. 2024-01-02T10:00:00.000000000Z
    trimmed = value.split(".")[0].rstrip("Z")
    return int(datetime.fromisoformat(trimmed + "+00:00").timestamp())


def _spread(bid: dict | None, ask: dict | None) -> float | None:
    """The wider of the open and close spreads, or None if OANDA didn't send bid and ask prices."""
    if not bid or not ask:
        return None
    try:
        gaps = [float(ask[k]) - float(bid[k]) for k in ("o", "c")]
    except (KeyError, ValueError, TypeError):
        return None
    widest = max(gaps)
    return widest if widest > 0 else None


def fetch_candles(
    token: str,
    symbol: Symbol,
    tf: Timeframe,
    count: int,
    client: httpx.Client | None = None,
    start: int | None = None,
) -> list[Bar]:
    """The latest `count` candles, or (with `start`, Unix seconds) up to `count` candles from that time on."""
    if not token:
        raise ProviderError("OANDA token not set.")
    url = PRACTICE_HOST + CANDLES_PATH.format(instrument=symbol.provider_symbol)
    # Short candles also fetch bid and ask prices, so costs use the spread OANDA actually had at the time.
    params: dict = {"granularity": tf.oanda, "count": min(count, 5000), "price": "MBA" if tf.intraday else "M"}
    if start is not None:
        params["from"] = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"}
    own_client = client is None
    client = client or safe_client()
    try:
        resp = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Couldn't reach OANDA: {exc.__class__.__name__}.") from exc
    finally:
        if own_client:
            client.close()

    if resp.status_code == 401:
        raise ProviderError("OANDA rejected the token. Check it's a demo (practice) account token.")
    if resp.status_code == 400 or resp.status_code == 404:
        raise ProviderError(f"OANDA doesn't offer {symbol.name} on this account.")
    if resp.status_code != 200:
        raise ProviderError(f"OANDA returned an error ({resp.status_code}).")

    bars: list[Bar] = []
    for c in resp.json().get("candles", []):
        mid = c.get("mid") or {}
        try:
            spread = _spread(c.get("bid"), c.get("ask"))
            bars.append(
                Bar(
                    ts=_parse_time(c["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(c.get("volume", 0)),
                    spread=spread,
                )
            )
        except (KeyError, ValueError):
            continue
    return bars
