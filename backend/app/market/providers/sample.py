"""Made-up prices, used only when no data key is set, and always labelled as sample data.

This lets the site be tried out before the free OANDA and Twelve Data accounts
are connected. Sample prices are a random walk and mean nothing.
"""

import hashlib
import math
import random
import time

from ..symbols import Symbol
from ..timeframes import Timeframe
from .base import Bar


# Always build the same long path and show its most recent part, so a short chart
# and a long backtest of the same market agree with each other.
SAMPLE_SPAN = 6000


def generate(symbol: Symbol, tf: Timeframe, count: int, now: float | None = None) -> list[Bar]:
    return _path(symbol, tf, max(count, SAMPLE_SPAN), now)[-count:]


def _path(symbol: Symbol, tf: Timeframe, count: int, now: float | None) -> list[Bar]:
    now = time.time() if now is None else now
    last_open = int(now // tf.seconds) * tf.seconds
    seed = int(hashlib.sha256(f"{symbol.code}:{tf.code}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)

    # Volatility per bar scales with the square root of bar length.
    daily_vol = 0.006 if symbol.asset_class == "forex" else 0.014
    vol = daily_vol * math.sqrt(tf.seconds / 86400)

    price = symbol.base_price
    bars: list[Bar] = []
    start = last_open - (count - 1) * tf.seconds
    for i in range(count):
        ts = start + i * tf.seconds
        # A gentle wave so sample charts show trends, plus a pull back towards
        # the base price so made-up prices stay in a believable range.
        drift = vol * 0.15 * math.sin(i / 80.0) - 0.01 * math.log(price / symbol.base_price)
        o = price
        c = o * math.exp(drift + rng.gauss(0, vol))
        high = max(o, c) * (1 + abs(rng.gauss(0, vol * 0.6)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol * 0.6)))
        volume = round(1000 * (1 + abs(rng.gauss(0, 1))), 0)
        bars.append(Bar(ts, o, high, low, c, volume))
        price = c
    return bars
