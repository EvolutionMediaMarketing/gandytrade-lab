"""OANDA price candles, read-only, from the demo ("fxTrade Practice") environment only.

Safety: this module only ever calls the candles endpoint on the practice host.
The host is fixed here, not configurable, so a live account can never be
reached by the data feed. Order placement does not exist in this codebase.
"""

from datetime import datetime

import httpx

from ..symbols import Symbol
from ..timeframes import Timeframe
from .base import Bar, ProviderError

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
CANDLES_PATH = "/v3/instruments/{instrument}/candles"


def _parse_time(value: str) -> int:
    # OANDA returns RFC 3339 with nanoseconds, e.g. 2024-01-02T10:00:00.000000000Z
    trimmed = value.split(".")[0].rstrip("Z")
    return int(datetime.fromisoformat(trimmed + "+00:00").timestamp())


def fetch_candles(
    token: str,
    symbol: Symbol,
    tf: Timeframe,
    count: int,
    client: httpx.Client | None = None,
) -> list[Bar]:
    if not token:
        raise ProviderError("OANDA token not set.")
    url = PRACTICE_HOST + CANDLES_PATH.format(instrument=symbol.provider_symbol)
    params = {"granularity": tf.oanda, "count": min(count, 5000), "price": "M"}
    headers = {"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"}
    own_client = client is None
    client = client or httpx.Client(timeout=20)
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
            bars.append(
                Bar(
                    ts=_parse_time(c["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(c.get("volume", 0)),
                )
            )
        except (KeyError, ValueError):
            continue
    return bars
