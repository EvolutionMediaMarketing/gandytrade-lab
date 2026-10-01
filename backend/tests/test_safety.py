"""Safety check: real-money order code may only exist in the live gateway.

Phase 6 (optional live trading) will add backend/app/live/. Until then, and
everywhere outside that folder forever, any reference to a broker's order,
trade or position endpoints, or to a live trading host, fails the build.
"""

import re
from pathlib import Path

from app.market.providers import oanda

REPO = Path(__file__).resolve().parents[2]
ALLOWED_DIR = REPO / "backend" / "app" / "live"
SCANNED = [REPO / "backend" / "app", REPO / "frontend" / "src", REPO / "deploy"]
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".sh", ".conf", ".container", ".env", ".html"}

FORBIDDEN = [
    re.compile(r"api-fxtrade\.oanda\.com", re.I),  # OANDA live host
    re.compile(r"/v3/accounts/[^\s\"']*/(orders|trades|positions)", re.I),  # OANDA order endpoints
    re.compile(r"/api/v1/(positions|workingorders|orders)", re.I),  # Capital.com order endpoints
    re.compile(r"\bplace_?order\b", re.I),  # Interactive Brokers style
    re.compile(r"api-capital\.backend-capital\.com", re.I),  # Capital.com live host
]


def _files():
    for root in SCANNED:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SUFFIXES and ALLOWED_DIR not in path.parents:
                if "node_modules" in path.parts or "dist" in path.parts:
                    continue
                yield path


def test_no_order_code_outside_live_gateway():
    offenders = []
    for path in _files():
        text = path.read_text(errors="ignore")
        for pattern in FORBIDDEN:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO)}: {pattern.pattern}")
    assert not offenders, "Broker order code found outside the live gateway:\n" + "\n".join(offenders)


def test_data_feed_is_fixed_to_practice_host():
    assert oanda.PRACTICE_HOST == "https://api-fxpractice.oanda.com"
    assert oanda.CANDLES_PATH.endswith("/candles")


def test_outbound_calls_only_through_the_allowlisted_client():
    """Every internet request must use safe_client(), which only reaches the two data hosts."""
    app_dir = REPO / "backend" / "app"
    allowed = {app_dir / "market" / "providers" / "http.py"}
    pattern = re.compile(
        r"httpx\.(Client|AsyncClient|get|post|put|delete|request|stream)\s*\("
        r"|^\s*(import|from)\s+(requests|urllib\.request|urllib3|aiohttp|http\.client|socket)\b"
    )
    offenders = []
    for path in app_dir.rglob("*.py"):
        if path in allowed or ALLOWED_DIR in path.parents:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not offenders, "Outbound HTTP outside safe_client():\n" + "\n".join(offenders)
