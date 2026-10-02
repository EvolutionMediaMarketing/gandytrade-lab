"""The full list of markets: everything the free data feeds actually serve.

* OANDA practice feed: every instrument on your demo account (forex, metals,
  commodities, indices, bonds). Read-only list; no trading endpoints are used.
* Twelve Data free plan: every US-listed stock and ETF marked as available on
  the free ("Basic") plan.

The list is saved in the database and refreshed in the background once a week
(about 3 data requests in total), or on demand with `python -m app.cli refresh-markets`.
The hand-picked markets in symbols.py stay as the "popular" shortlist and as a
fallback when no data keys are set.
"""

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Instrument
from .providers.base import ProviderError
from .providers.http import safe_client
from . import uk_shares
from .symbols import SYMBOLS, Symbol

log = logging.getLogger(__name__)

OANDA_HOST = "https://api-fxpractice.oanda.com"
TWELVEDATA_HOST = "https://api.twelvedata.com"
REFRESH_EVERY = timedelta(days=7)
# US exchanges only (Twelve Data's free plan covers US markets).
US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE ARCA", "ARCA", "AMEX", "NYSE AMERICAN", "CBOE", "BATS", "CBOE BZX"}
EXCHANGE_PREFERENCE = ["NASDAQ", "NYSE", "NYSE ARCA", "ARCA", "NYSE AMERICAN", "AMEX", "CBOE", "CBOE BZX", "BATS"]
FREE_PLAN = "basic"

COMMODITIES = {
    "BCO_USD", "WTICO_USD", "NATGAS_USD", "XCU_USD", "CORN_USD", "WHEAT_USD", "SOYBN_USD", "SUGAR_USD",
}
# Government bonds, e.g. USB10Y_USD, UK10YB_GBP (but not the JP225Y_JPY index).
BOND_PATTERN = re.compile(r"[A-Z]+\d{1,2}YB?")
ASSET_TAGS = {
    "CURRENCY": "forex", "METAL": "metal", "COMMODITY": "commodity", "COMMODITIES": "commodity",
    "INDEX": "index", "INDICES": "index", "BOND": "bond", "BONDS": "bond",
}

_lock = threading.Lock()
_running = False


# --- Fetching the provider lists -------------------------------------------------------

def _oanda_class(item: dict) -> str:
    for tag in item.get("tags") or []:
        if tag.get("type") == "ASSET_CLASS" and tag.get("name", "").upper() in ASSET_TAGS:
            return ASSET_TAGS[tag["name"].upper()]
    kind, code = item.get("type", ""), item.get("name", "")
    if kind == "CURRENCY":
        return "forex"
    if kind == "METAL":
        return "metal"
    if code in COMMODITIES:
        return "commodity"
    if BOND_PATTERN.fullmatch(code.split("_")[0]):
        return "bond"
    return "index"


def fetch_oanda(token: str, client=None) -> list[dict]:
    """All instruments on the OANDA demo account (read-only list)."""
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    own = client is None
    client = client or safe_client()
    try:
        accounts = client.get(f"{OANDA_HOST}/v3/accounts", headers=headers)
        if accounts.status_code != 200:
            raise ProviderError(f"OANDA account list failed ({accounts.status_code}).")
        items = accounts.json().get("accounts") or []
        if not items:
            raise ProviderError("No OANDA demo account found for this token.")
        account_id = items[0]["id"]
        resp = client.get(f"{OANDA_HOST}/v3/accounts/{account_id}/instruments", headers=headers)
        if resp.status_code != 200:
            raise ProviderError(f"OANDA instrument list failed ({resp.status_code}).")
        out = []
        for item in resp.json().get("instruments", []):
            code = item.get("name")
            if not code:
                continue
            out.append({
                "code": code,
                "name": item.get("displayName") or code.replace("_", "/"),
                "asset_class": _oanda_class(item),
                "provider": "oanda",
                "provider_symbol": code,
                "precision": int(item.get("displayPrecision", 5)),
                "exchange": "OANDA",
            })
        return out
    finally:
        if own:
            client.close()


def _free_plan(item: dict) -> bool:
    access = item.get("access")
    if not isinstance(access, dict):
        return True  # no plan info: let the chart try, it will explain if not available
    plan = str(access.get("plan") or access.get("global") or "").lower()
    return plan in ("", FREE_PLAN)


def fetch_twelvedata(api_key: str, client=None) -> list[dict]:
    """US stocks and ETFs available on the free plan."""
    if not api_key:
        return []
    headers = {"Authorization": f"apikey {api_key}"}
    own = client is None
    client = client or safe_client(timeout=60)
    best: dict[str, dict] = {}
    try:
        for path, asset_class in (("/stocks", "stock"), ("/etfs", "etf")):
            resp = client.get(
                TWELVEDATA_HOST + path,
                params={"country": "United States", "show_plan": "true"},
                headers=headers,
            )
            if resp.status_code != 200:
                raise ProviderError(f"Twelve Data list {path} failed ({resp.status_code}).")
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("status") == "error":
                raise ProviderError(f"Twelve Data: {payload.get('message', 'list failed')}")
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            for item in rows:
                symbol = (item.get("symbol") or "").strip().upper()
                exchange = (item.get("exchange") or "").strip().upper()
                if not symbol or len(symbol) > 16 or exchange not in US_EXCHANGES or not _free_plan(item):
                    continue
                row = {
                    "code": symbol,
                    "name": (item.get("name") or symbol)[:160],
                    "asset_class": asset_class,
                    "provider": "twelvedata",
                    "provider_symbol": symbol,
                    "precision": 2,
                    "exchange": exchange,
                }
                current = best.get(symbol)
                rank = EXCHANGE_PREFERENCE.index(exchange) if exchange in EXCHANGE_PREFERENCE else 99
                if current is None or (current["asset_class"] == "stock" and asset_class == "etf") or (
                    current["asset_class"] == asset_class and rank < current["_rank"]
                ):
                    best[symbol] = {**row, "_rank": rank}
        return [{k: v for k, v in r.items() if k != "_rank"} for r in best.values()]
    finally:
        if own:
            client.close()


# --- Storing ----------------------------------------------------------------------------

def save(db: Session, provider: str, rows: list[dict]) -> int:
    """Replace one provider's list. An empty result never wipes a good list."""
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    reserved = set(SYMBOLS) if provider == "twelvedata" else set()
    seen: set[str] = set()
    db.execute(delete(Instrument).where(Instrument.provider == provider))
    for r in rows:
        code = r["code"]
        if code in seen:
            continue
        # A ticker that clashes with a built-in code from the other provider is skipped.
        if code in reserved and SYMBOLS[code].provider != provider:
            continue
        seen.add(code)
        db.add(Instrument(updated_at=now, **r))
    db.commit()
    return len(seen)


def last_updated(db: Session, provider: str) -> datetime | None:
    value = db.scalar(select(func.max(Instrument.updated_at)).where(Instrument.provider == provider))
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def ensure_fixed_lists(db: Session, force: bool = False) -> int:
    """London shares: a fixed list kept in the code, so no data requests are needed.
    Returns how many were saved, or 0 if the stored list was already up to date."""
    uk = uk_shares.rows()
    have = db.scalar(select(func.count()).select_from(Instrument).where(Instrument.provider == "alphavantage"))
    if force or have != len(uk):
        return save(db, "alphavantage", uk)
    return 0


def refresh(db: Session, force: bool = False) -> dict[str, int | str]:
    """Refresh any provider list that's missing or over a week old."""
    settings = get_settings()
    result: dict[str, int | str] = {}
    now = datetime.now(timezone.utc)
    uk_count = ensure_fixed_lists(db, force)
    if uk_count:
        result["alphavantage"] = uk_count
    jobs = (("oanda", settings.oanda_token, fetch_oanda), ("twelvedata", settings.twelvedata_key, fetch_twelvedata))
    for provider, key, fetch in jobs:
        if not key:
            continue
        updated = last_updated(db, provider)
        if not force and updated is not None and now - updated < REFRESH_EVERY:
            continue
        try:
            result[provider] = save(db, provider, fetch(key))
        except Exception as exc:  # a failed refresh keeps the old list
            db.rollback()
            log.warning("Market list refresh for %s failed: %s", provider, exc)
            result[provider] = f"failed: {exc}"
    return result


def refresh_in_background() -> None:
    """Start a refresh if one is due, without making anyone wait."""
    global _running
    with _lock:
        if _running:
            return
        _running = True

    def run() -> None:
        global _running
        from ..db import new_session

        db = new_session()
        try:
            refresh(db)
        finally:
            db.close()
            with _lock:
                _running = False

    threading.Thread(target=run, name="market-list-refresh", daemon=True).start()


# --- Looking up and searching -------------------------------------------------------------

def _to_symbol(row: Instrument) -> Symbol:
    return Symbol(row.code, row.name, row.asset_class, row.provider, row.provider_symbol, row.precision, 100.0)


def lookup(db: Session, code: str) -> Symbol:
    if code in SYMBOLS:
        return SYMBOLS[code]
    row = db.get(Instrument, code)
    if row is None:
        raise ValueError(f"Unknown market '{code}'.")
    return _to_symbol(row)


def counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Instrument.asset_class, func.count()).group_by(Instrument.asset_class)).all()
    out = {cls: n for cls, n in rows}
    for s in SYMBOLS.values():  # built-ins not (yet) in the directory
        if db.get(Instrument, s.code) is None:
            out[s.asset_class] = out.get(s.asset_class, 0) + 1
    return out


def search(db: Session, query: str, asset_class: str = "", limit: int = 50) -> list[dict]:
    q = query.strip().lower().replace("/", "_")
    limit = max(1, min(limit, 100))
    results: dict[str, dict] = {}

    stmt = select(Instrument)
    if asset_class:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    if q:
        like = f"%{q}%"
        code_l, name_l = func.lower(Instrument.code), func.lower(Instrument.name)
        stmt = stmt.where(or_(code_l.like(like), name_l.like(like), code_l.like(f"%{q.replace('_', '')}%")))
        rank = case(
            (code_l == q, 0),
            (code_l.like(f"{q}%"), 1),
            (name_l.like(f"{q}%"), 2),
            (name_l.like(f"% {q}%"), 3),
            else_=4,
        )
        stmt = stmt.order_by(rank, func.length(Instrument.code), Instrument.code)
    else:
        stmt = stmt.order_by(Instrument.asset_class, Instrument.code)
    for row in db.scalars(stmt.limit(limit)):
        results[row.code] = _to_symbol(row).to_dict()

    # Built-in markets are always findable, even before the full list has loaded.
    for s in SYMBOLS.values():
        if s.code in results or (asset_class and s.asset_class != asset_class):
            continue
        hay = f"{s.code} {s.name}".lower()
        if not q or q in hay or q.replace("_", "") in hay.replace("_", ""):
            results[s.code] = s.to_dict()

    def score(d: dict) -> tuple:
        code, name = d["code"].lower(), d["name"].lower()
        if not q:
            return (0, code)
        return (
            0 if code == q else 1 if code.startswith(q) else 2 if name.startswith(q) else 3 if f" {q}" in f" {name}" else 4,
            len(code),
            code,
        )

    return sorted(results.values(), key=score)[:limit]
