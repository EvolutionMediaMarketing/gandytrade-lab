"""Live prices from OANDA's practice price stream (read-only).

One background thread keeps a single streaming connection open to OANDA, for the markets
someone is looking at right now (asked for in the last minute) plus markets with open paper
trades. It only receives prices; nothing is ever sent to OANDA except the request to listen.
The browser picks up the latest price from the app every couple of seconds.

US and UK shares aren't included: their free data feeds don't offer live streaming.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass

import httpx

from ..config import get_settings
from .providers.http import safe_client

log = logging.getLogger(__name__)

STREAM_HOST = "https://stream-fxpractice.oanda.com"
REST_HOST = "https://api-fxpractice.oanda.com"
INTEREST_SECONDS = 60  # stop streaming a market a minute after the last request for it
MAX_INSTRUMENTS = 20  # keep the connection small
STALE_SECONDS = 30  # no message (not even a heartbeat) for this long means the connection is dead
RESTART_MIN_GAP = 5  # don't reconnect more often than this when the list of markets changes


@dataclass
class Tick:
    bid: float
    ask: float
    time: float  # Unix seconds

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def parse_line(line: str) -> tuple[str, Tick] | None:
    """One line of the stream. Prices become (instrument, Tick); heartbeats and anything else, None."""
    if not line.strip():
        return None
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if msg.get("type") != "PRICE" or not msg.get("tradeable", True):
        return None
    try:
        bid = float(msg["bids"][0]["price"])
        ask = float(msg["asks"][0]["price"])
        from datetime import datetime

        ts = datetime.fromisoformat(msg["time"].split(".")[0].rstrip("Z") + "+00:00").timestamp()
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return msg["instrument"], Tick(bid, ask, ts)


class PriceStream:
    def __init__(self) -> None:
        self.prices: dict[str, Tick] = {}
        self.interest: dict[str, float] = {}  # instrument -> last time someone asked
        self.pinned: set[str] = set()  # markets with open paper trades
        self.lock = threading.Lock()
        self.connected_to: frozenset[str] = frozenset()
        self.last_message = 0.0
        self.last_start = 0.0
        self.account_id: str | None = None
        self.thread: threading.Thread | None = None
        self.stopping = False
        self.status = "idle"

    # --- What to listen to -------------------------------------------------------------
    def want(self, instruments: list[str]) -> None:
        now = time.time()
        with self.lock:
            for code in instruments[:MAX_INSTRUMENTS]:
                self.interest[code] = now
        self._ensure_thread()

    def pin(self, instruments: set[str]) -> None:
        with self.lock:
            self.pinned = set(list(instruments)[:MAX_INSTRUMENTS])

    def wanted(self) -> frozenset[str]:
        now = time.time()
        with self.lock:
            for code, at in list(self.interest.items()):
                if now - at > INTEREST_SECONDS:
                    del self.interest[code]
            ranked = sorted(self.interest, key=lambda c: -self.interest[c])
            return frozenset((list(self.pinned) + ranked)[:MAX_INSTRUMENTS])

    def latest(self, instruments: list[str]) -> dict[str, Tick]:
        with self.lock:
            return {c: self.prices[c] for c in instruments if c in self.prices}

    @property
    def live(self) -> bool:
        return self.status == "streaming" and time.time() - self.last_message < STALE_SECONDS

    # --- The background connection --------------------------------------------------------
    def _ensure_thread(self) -> None:
        if not get_settings().oanda_token:
            return
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, name="oanda-price-stream", daemon=True)
            self.thread.start()

    def _account(self, client: httpx.Client, token: str) -> str:
        if self.account_id is None:
            r = client.get(f"{REST_HOST}/v3/accounts", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            self.account_id = r.json()["accounts"][0]["id"]
        return self.account_id

    def _run(self) -> None:
        backoff = 2.0
        idle_since = time.time()
        while not self.stopping:
            want = self.wanted()
            if not want:
                self.status = "idle"
                if time.time() - idle_since > 300:
                    return  # nobody's watching; the next request starts a new thread
                time.sleep(1)
                continue
            idle_since = time.time()
            wait = RESTART_MIN_GAP - (time.time() - self.last_start)
            if wait > 0:
                time.sleep(wait)
            self.last_start = time.time()
            try:
                self._listen(want)
                backoff = 2.0
            except Exception as exc:  # network trouble: wait a little longer each time, up to a minute
                self.status = "reconnecting"
                log.warning("Price stream interrupted: %s", exc.__class__.__name__)
                time.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    def _listen(self, want: frozenset[str]) -> None:
        token = get_settings().oanda_token
        timeout = httpx.Timeout(10.0, read=STALE_SECONDS)
        with safe_client(timeout=20) as client:
            account = self._account(client, token)
            url = f"{STREAM_HOST}/v3/accounts/{account}/pricing/stream"
            with client.stream("GET", url, params={"instruments": ",".join(sorted(want))},
                               headers={"Authorization": f"Bearer {token}"}, timeout=timeout) as resp:
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError("stream refused", request=resp.request, response=resp)
                self.connected_to = want
                self.status = "streaming"
                for line in resp.iter_lines():
                    self.last_message = time.time()
                    parsed = parse_line(line)
                    if parsed:
                        code, tick = parsed
                        with self.lock:
                            self.prices[code] = tick
                    # Reconnect when the markets being watched change (OANDA fixes them per connection).
                    if self.stopping or (self.wanted() != self.connected_to
                                         and time.time() - self.last_start > RESTART_MIN_GAP):
                        return


stream = PriceStream()
