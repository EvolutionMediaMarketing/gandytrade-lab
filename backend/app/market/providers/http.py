"""The only way the app talks to the internet: an HTTP client limited to an allowlist.

Market data comes from three read-only services. Any request to another host, or
over plain HTTP, is refused before it leaves the app. Adding a host here is a
deliberate, reviewed change; the live trading gateway (Phase 6) will have its
own separate client, in its own container, on its own server.
"""

import httpx

ALLOWED_HOSTS = frozenset({"api-fxpractice.oanda.com", "api.twelvedata.com", "www.alphavantage.co"})


class BlockedHost(httpx.HTTPError):
    pass


def check_request(request: httpx.Request) -> None:
    if request.url.scheme != "https" or request.url.host not in ALLOWED_HOSTS:
        raise BlockedHost(f"Outbound request to {request.url.scheme}://{request.url.host} is not allowed.")


def safe_client(timeout: float = 20) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        event_hooks={"request": [check_request]},
    )
