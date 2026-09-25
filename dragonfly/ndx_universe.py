"""Dragonfly Phase 1 universe: the 5 largest Nasdaq-100 names by market cap in
each sector. Membership is refreshed WEEKLY and persisted; daily builds reuse it
and only re-run the gates and quotes.

Sources (api.nasdaq.com, the same host the security-type lookup uses):
  - Constituents + market cap: the Nasdaq-100 list
    (`/api/quote/list-type/nasdaq100`, field `marketCap`). That feed's own
    `sector` field is blank for every row, so it cannot be used.
  - Sector: the Nasdaq stock screener (`/api/screener/stocks`, field
    `sector`). This is Nasdaq's sector label as api.nasdaq.com reports it (the
    same value as the quote page "Sector"). Its labels use ICB industry names
    (Technology, Telecommunications, Consumer Discretionary, ...) but it is
    Nasdaq's own mapping: api.nasdaq.com exposes no separate ICB code.

Ranking: market cap descending within each sector (ties by ticker), top 5 per
sector; a sector with fewer than 5 members contributes what it has. A
constituent with a missing/blank sector or an unparseable/non-positive market
cap is excluded from ranking with a reason (sector_missing /
market_cap_missing). Fail closed.

No backfill happens here or downstream: gates (type, price, ADV, quote) run on
the persisted top-5 members only, and a member that fails a gate leaves its
slot empty.

Python 3.9 compatible.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

NDX_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
SCHEMA = "dragonfly.ndx_universe/1"
PER_SECTOR = 5
MAX_AGE_DAYS = 7
SECTOR_FIELD = (
    "api.nasdaq.com screener `sector` (Nasdaq's sector label, ICB-style industry names; "
    "the Nasdaq-100 list's own `sector` field is blank)"
)
MARKET_CAP_FIELD = "api.nasdaq.com Nasdaq-100 list `marketCap`"
MIN_CONSTITUENTS = 90


def norm_symbol(sym) -> str:
    return str(sym or "").strip().upper().replace("/", "-").replace(".", "-")


def parse_market_cap(value) -> Optional[float]:
    """'4,965,888,657,700' / '48728583125.00' / 1.2e9 -> float; else None."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    if v != v or v <= 0:
        return None
    return v


def parse_members(ndx_payload: Mapping, screener_payload: Mapping) -> List[dict]:
    """Join NDX constituents (market cap) with screener sectors."""
    rows = ((ndx_payload.get("data") or {}).get("data") or {}).get("rows") or []
    screener_rows = ((screener_payload.get("data") or {}).get("rows")) or []
    sectors = {}
    for r in screener_rows:
        sym = norm_symbol(r.get("symbol"))
        if sym:
            sectors[sym] = (r.get("sector") or "").strip() or None
    out = []
    for r in rows:
        sym = norm_symbol(r.get("symbol"))
        if not sym or not sym.replace("-", "").isalnum():
            continue
        out.append(
            {
                "ticker": sym,
                "name": r.get("companyName"),
                "market_cap": parse_market_cap(r.get("marketCap")),
                "sector": sectors.get(sym),
            }
        )
    if len(out) < MIN_CONSTITUENTS:
        raise ValueError(f"nasdaq-100 list too short ({len(out)})")
    return out


def rank_by_sector(members: List[Mapping], per_sector: int = PER_SECTOR) -> dict:
    """Top `per_sector` by market cap in each sector. Pure."""
    excluded: Dict[str, str] = {}
    groups: Dict[str, List[Mapping]] = {}
    for m in members:
        if not m.get("sector"):
            excluded[m["ticker"]] = "sector_missing"
        elif parse_market_cap(m.get("market_cap")) is None:
            excluded[m["ticker"]] = "market_cap_missing"
        else:
            groups.setdefault(m["sector"], []).append(m)
    sectors: Dict[str, List[dict]] = {}
    sizes: Dict[str, int] = {}
    for sector in sorted(groups):
        ranked = sorted(groups[sector], key=lambda m: (-parse_market_cap(m["market_cap"]), m["ticker"]))
        sizes[sector] = len(ranked)
        sectors[sector] = [
            {
                "ticker": m["ticker"],
                "name": m.get("name"),
                "sector": sector,
                "sector_rank": i + 1,
                "market_cap": parse_market_cap(m["market_cap"]),
            }
            for i, m in enumerate(ranked[:per_sector])
        ]
    return {
        "per_sector": per_sector,
        "sectors": sectors,
        "sector_sizes": sizes,
        "members": [m for s in sectors.values() for m in s],
        "excluded": dict(sorted(excluded.items())),
        "constituents": len(members),
    }


def _as_of_date(doc: Mapping) -> Optional[date]:
    try:
        return date.fromisoformat(str(doc.get("as_of_date")))
    except (TypeError, ValueError):
        return None


def universe_age_days(doc: Optional[Mapping], today: date) -> Optional[int]:
    d = _as_of_date(doc or {})
    return None if d is None else (today - d).days


def is_stale(doc: Optional[Mapping], today: date, max_age_days: int = MAX_AGE_DAYS, per_sector: int = PER_SECTOR) -> bool:
    """Stale (must refresh) if missing, malformed, a different per-sector N,
    dated in the future, or `max_age_days` or more days old."""
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        return True
    if doc.get("per_sector") != per_sector or not isinstance(doc.get("members"), list) or not doc["members"]:
        return True
    age = universe_age_days(doc, today)
    return age is None or age < 0 or age >= max_age_days


def load(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fetch_and_rank(get_json: Callable[[str], Mapping], now: datetime, per_sector: int = PER_SECTOR) -> dict:
    members = parse_members(get_json(NDX_URL), get_json(SCREENER_URL))
    ranked = rank_by_sector(members, per_sector)
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(timespec="seconds"),
        "as_of_date": now.date().isoformat(),
        "refresh": f"weekly: reused until {MAX_AGE_DAYS} or more days old, or --refresh-universe",
        "sources": {"constituents_market_cap": NDX_URL, "sector": SCREENER_URL},
        "sector_field": SECTOR_FIELD,
        "market_cap_field": MARKET_CAP_FIELD,
        "rank_key": "market_cap desc within sector (ties by ticker)",
        **ranked,
    }


def get_universe(
    path: Path,
    get_json: Callable[[str], Mapping],
    now: datetime,
    refresh: bool = False,
    max_age_days: int = MAX_AGE_DAYS,
    per_sector: int = PER_SECTOR,
) -> dict:
    """Reuse the persisted membership unless stale or `refresh`; otherwise
    fetch, rank, and persist. A failed refresh raises (no silent reuse of a
    stale membership). Returns the doc plus `reused` and `age_days`."""
    doc = load(path)
    if not refresh and not is_stale(doc, now.date(), max_age_days, per_sector):
        return {**doc, "reused": True, "age_days": universe_age_days(doc, now.date())}
    doc = fetch_and_rank(get_json, now, per_sector)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return {**doc, "reused": False, "age_days": 0}
