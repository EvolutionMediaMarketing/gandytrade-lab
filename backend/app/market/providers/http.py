"""The only way the app talks to the internet: an HTTP client limited to an allowlist.

Market data comes from three read-only services (OANDA's practice prices, Twelve Data and Alpha Vantage);
Wikipedia supplies read-only background summaries; six official publishers' schedule pages are read (never
written to) to keep the economic calendar's dates up to date. Any request to another host, or
over plain HTTP, is refused before it leaves the app. Adding a host here is a
deliberate, reviewed change; the live trading gateway (Phase 6) will have its
own separate client, in its own container, on its own server.
"""

import re

import httpx

ALLOWED_HOSTS = frozenset({
    "api-fxpractice.oanda.com",  # OANDA practice: price history and the market list
    "stream-fxpractice.oanda.com",  # OANDA practice: live price stream (receive only)
    "api.twelvedata.com",
    "www.alphavantage.co",
    "api.telegram.org",  # alerts to your own Telegram bot (sending messages only)
    "en.wikipedia.org",  # read-only company and market summaries for the chart's hover card
    # Economic calendar: official schedule pages, read only (app/market/calendar_refresh.py)
    "www.federalreserve.gov",
    "www.bankofengland.co.uk",
    "www.ecb.europa.eu",
    "www.boj.or.jp",
    "www.bls.gov",
    "www.ons.gov.uk",
})


# Off-server backups: Backblaze B2's S3-compatible endpoints, one per storage region
# (e.g. s3.eu-central-003.backblazeb2.com). Uploads only; the key used can't read or delete.
ALLOWED_HOST_PATTERNS = (re.compile(r"^s3\.[a-z]{2}-[a-z]+-\d{3}\.backblazeb2\.com$"),)


def host_allowed(host: str) -> bool:
    return host in ALLOWED_HOSTS or any(p.match(host) for p in ALLOWED_HOST_PATTERNS)


class BlockedHost(httpx.HTTPError):
    pass


def check_request(request: httpx.Request) -> None:
    if request.url.scheme != "https" or not host_allowed(request.url.host):
        raise BlockedHost(f"Outbound request to {request.url.scheme}://{request.url.host} is not allowed.")


def safe_client(timeout: float = 20) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        event_hooks={"request": [check_request]},
    )
