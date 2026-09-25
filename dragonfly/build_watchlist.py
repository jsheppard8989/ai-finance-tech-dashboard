"""Build dragonfly/watchlist.json: the Phase 1 watchlist.

Universe (dragonfly/ndx_universe.py): the 5 largest Nasdaq-100 companies by
market cap in each sector (Nasdaq-100 list `marketCap` + Nasdaq screener
`sector`, both from api.nasdaq.com), share classes collapsed to one per
company first (Alphabet keeps GOOGL; dropped: duplicate_share_class).
Plus PINNED names from dragonfly/universe_config.json (hand-edited, never
touched by the refresh): added on top, gated like everyone else, no sector
slot used, never displacing a top-5 member. Membership is persisted in dragonfly/universe.json
and refreshed WEEKLY: reused until it is 7 or more days old, or on
--refresh-universe. A daily build re-runs only the gates and quotes, so it
cannot reshuffle membership. The S&P 500 pool is gone.

NO BACKFILL. Gates run on the top-5 members only. A member that fails any gate
leaves its slot empty; the #6 name in a sector is never pulled in. Every
excluded member is recorded with its reason.

Gates are the EXISTING universe gates from dragonfly/risk_math.py via
`universe_reasons` (not re-typed here):
  price >= $10, 20-day ADV >= $25M, spread <= max($0.05, 0.15% of price).

Order of work:
  0. Security type: only US listed common stock. Depositary receipts (ADRs,
     ADSs, NY registry shares) are excluded (depositary_receipt); a name whose
     type cannot be determined is excluded (security_type_unknown).
  1. Bars for every remaining member (dragonfly/bars.py; one history call per
     name, cached). Price and 20-day ADV gates.
  2. Survivors are ordered by ADV, descending (the `rank` field).
  3. Quotes (Yahoo bid/ask/last) for each survivor. `--cap` is only a harmless
     upper bound now. Two modes (--spread-mode):
     modeled (default, PAPER ONLY, Jared 2026-09-25):
       - Yahoo bid/ask that passes the spread gate as-is -> used
         (spread_source "yahoo");
       - crossed / zero / missing / gate-fail -> modeled $0.05 spread around
         (bid+ask)/2 (spread_source "modeled_mid_0.05", provisional);
       - no usable mid, or mid more than the gate width from last trade ->
         modeled $0.05 around last trade ("modeled_last_0.05",
         mid_source "last_trade", provisional);
       - no usable mid and no usable last trade -> excluded
         (no_usable_mid_or_last). Fail closed.
       Price gate (on the resolved mid) and ADV gate stay exact.
     exact (the strict gate, as before):
       - a name whose bid/ask fetch fails or is unusable -> excluded
         (spread_unavailable);
       - a name that is never spread-checked because the cap filled first
         -> excluded (not_spread_checked). It is never admitted.
       Only names that were spread-checked and passed are admitted.

Output is stamped source="yahoo", provisional=True, with an as_of and the gate
parameters. The scanner must read only `names` from this file.

Guarded by dragonfly/guards.py: refuses inside the pipeline daemon windows
(05:00-07:59, 12:00-14:59, 22:00-23:59 CT) unless --allow-daemon-window, and
waits a bounded time then aborts while the site pipeline lock is held. A guard
stop mid-run aborts the build and writes nothing. Bars are cache-first.

Python 3.9 compatible. Run (market hours, outside daemon windows):
  python3 dragonfly/build_watchlist.py [--refresh-universe] [--spread-mode modeled|exact]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonfly import bars as bars_mod  # noqa: E402
from dragonfly import guards  # noqa: E402
from dragonfly import ndx_universe  # noqa: E402
from dragonfly.risk_math import (  # noqa: E402
    MAX_STOCK_SPREAD_ABS,
    MAX_STOCK_SPREAD_PCT,
    MIN_ADV_DOLLARS,
    MIN_PRICE,
    D,
    MODELED_SPREAD_SOURCES,
    SPREAD_SOURCE_YAHOO,
    resolve_quote,
    stock_spread_limit,
    universe_reasons,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "dragonfly" / "watchlist.json"
DEFAULT_UNIVERSE = ROOT / "dragonfly" / "universe.json"
DEFAULT_UNIVERSE_CONFIG = ROOT / "dragonfly" / "universe_config.json"  # pinned names (hand-edited)
# Harmless upper bound only: the universe is at most 5 names per NDX sector.
DEFAULT_CAP = 200
# Security type ("US listed common stock"): Nasdaq's security descriptor.
# 1) One screener call covering all US listings (name ends with the security
#    type, e.g. "Apple Inc. Common Stock", "PDD Holdings Inc. American
#    Depositary Shares"). 2) For names whose descriptor is blank there, the
#    per-symbol Nasdaq quote info `stockType`. 3) Explicit denylist below.
# Unknown after that -> excluded (security_type_unknown). Fail closed.
SCREENER_URL = ndx_universe.SCREENER_URL
QUOTE_INFO_URL = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks"
ETF_INFO_URL = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=etf"
# Belt-and-braces denylist of US-traded depositary receipts. Tightening only:
# a name here is excluded even if a feed calls it common stock.
KNOWN_DEPOSITARY_RECEIPTS = {
    "ARM": "Arm Holdings plc ADS",
    "ASML": "ASML Holding N.V. New York Registry Shares",
    "BABA": "Alibaba Group ADS",
    "BHP": "BHP Group ADS",
    "BIDU": "Baidu ADS",
    "BP": "BP p.l.c. ADS",
    "HSBC": "HSBC Holdings ADS",
    "JD": "JD.com ADS",
    "NTES": "NetEase ADS",
    "NVO": "Novo Nordisk ADS",
    "PDD": "PDD Holdings ADS",
    "RIO": "Rio Tinto ADS",
    "SAP": "SAP SE ADS",
    "SHEL": "Shell plc ADS",
    "SONY": "Sony Group ADS",
    "TCOM": "Trip.com ADS",
    "TM": "Toyota Motor ADS",
    "TSM": "Taiwan Semiconductor ADS",
    "UL": "Unilever PLC ADS",
}
_DR_RE = re.compile(r"depositary|\bADRs?\b|\bADSs?\b|\bGDRs?\b|registry shares", re.I)
_NOT_COMMON_RE = re.compile(r"preferred|warrants?\b|\bunits?\b|\brights?\b|notes?\b|debentures?|beneficial interest|limited partnership|\bETF\b|\bfund\b", re.I)
_COMMON_TRUST_RE = re.compile(r"common shares? of beneficial interest", re.I)
_COMMON_RE = re.compile(r"common stock|common shares?|ordinary shares?|voting shares?|capital stock", re.I)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

Quote = Tuple[Optional[float], Optional[float]]  # (bid, ask)


# ------------------------------------------------------------ http

def _get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


# ------------------------------------------------------------ security type

def classify_security(descriptor: Optional[str]) -> Optional[str]:
    """common | depositary_receipt | not_common_stock | None (unknown)."""
    if not descriptor or not str(descriptor).strip():
        return None
    d = str(descriptor)
    if _DR_RE.search(d):
        return "depositary_receipt"
    if _COMMON_TRUST_RE.search(d):
        return "common"  # e.g. REIT "Common Shares of Beneficial Interest"
    if _NOT_COMMON_RE.search(d):
        return "not_common_stock"
    if _COMMON_RE.search(d):
        return "common"
    return None


def _nasdaq_symbol(ticker: str) -> str:
    return ticker.replace("-", ".")


def _get_json(url: str) -> Mapping:
    return json.loads(_get(url, "application/json"))


def fetch_security_types(
    tickers: Sequence[str],
    get_json: Callable[[str], Mapping] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    """ticker -> {"class", "descriptor", "source"}; class None means unknown."""
    get_json = get_json or _get_json
    out: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        rows = ((get_json(SCREENER_URL).get("data") or {}).get("rows")) or []
    except Exception:
        rows = []
    screener = {}
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper().replace("/", "-").replace(".", "-")
        if sym:
            screener[sym] = r.get("name")
    for t in tickers:
        desc = screener.get(t)
        cls = classify_security(desc)
        src = "nasdaq_screener" if desc else None
        if cls is None:
            try:
                data = get_json(QUOTE_INFO_URL.format(symbol=_nasdaq_symbol(t))).get("data") or {}
                stock_type = data.get("stockType")
            except Exception:
                stock_type = None
            if stock_type:
                cls = classify_security(stock_type)
                desc = f"{desc or ''} [stockType: {stock_type}]".strip()
                src = "nasdaq_quote_info"
        if cls is None and not desc:
            # Not a listed stock on Nasdaq's feeds: probe the ETF asset class.
            # An ETF/fund resolves to not_common_stock (tightening only; an
            # unknown name is excluded either way).
            try:
                etf = get_json(ETF_INFO_URL.format(symbol=_nasdaq_symbol(t))).get("data") or {}
            except Exception:
                etf = {}
            if etf.get("symbol"):
                cls = "not_common_stock"
                desc = f"{etf.get('companyName') or t} [assetclass: etf]"
                src = "nasdaq_quote_info_etf"
        if t in KNOWN_DEPOSITARY_RECEIPTS:
            cls = "depositary_receipt"
            desc = desc or KNOWN_DEPOSITARY_RECEIPTS[t]
            src = (src + "+denylist") if src else "denylist"
        out[t] = {"class": cls, "descriptor": desc, "source": src}
    return out


def apply_security_types(
    candidates: Sequence[Mapping],
    types: Mapping[str, Mapping],
) -> Tuple[List[dict], Dict[str, str]]:
    """Keep only names positively typed as common stock. Everything else is excluded:
    depositary_receipt, not_common_stock, or security_type_unknown (fail closed)."""
    eligible: List[dict] = []
    excluded: Dict[str, str] = {}
    for c in candidates:
        info = types.get(c["ticker"]) or {}
        cls = info.get("class")
        if cls == "common":
            eligible.append(dict(c, security_type=info.get("descriptor")))
        elif cls in ("depositary_receipt", "not_common_stock"):
            excluded[c["ticker"]] = cls
        else:
            excluded[c["ticker"]] = "security_type_unknown"
    return eligible, excluded


# ------------------------------------------------------------ quotes

def yahoo_quote(ticker: str) -> Quote:
    guards.before_fetch()  # pipeline lock + daemon window
    import yfinance as yf  # lazy

    info = yf.Ticker(ticker).info or {}
    return info.get("bid"), info.get("ask")


def yahoo_quote_full(ticker: str) -> Dict[str, Optional[float]]:
    """bid, ask and last trade from one yfinance info call (guarded)."""
    guards.before_fetch()  # pipeline lock + daemon window
    import yfinance as yf  # lazy

    info = yf.Ticker(ticker).info or {}
    last = info.get("regularMarketPrice")
    if last is None:
        last = info.get("currentPrice")
    return {
        "bid": info.get("bid"),
        "ask": info.get("ask"),
        "last": last,
        # Epoch seconds of the last regular-session trade; the paper-fill
        # staleness check (risk_math.quote_blocks) uses it.
        "quote_time": info.get("regularMarketTime"),
        "market_state": info.get("marketState"),
        # Yahoo has no reliable per-name halt flag (`tradeable` is False even
        # for AAPL), so halt status is unknown here, never fabricated.
        "halted": None,
    }


def _quote_parts(q) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if q is None:
        return None, None, None
    if isinstance(q, Mapping):
        return q.get("bid"), q.get("ask"), q.get("last")
    q = tuple(q)
    return (q + (None, None, None))[:3]


def spread_from_quote(quote: Optional[Quote]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """(spread, mid) or (None, None) when the quote is missing or unusable."""
    if not quote:
        return None, None
    bid, ask = quote
    try:
        bid_d, ask_d = D(bid), D(ask)
    except Exception:
        return None, None
    if bid is None or ask is None or bid_d <= 0 or ask_d <= 0 or ask_d < bid_d:
        return None, None
    return ask_d - bid_d, (bid_d + ask_d) / 2


# ------------------------------------------------------------ selection (pure)

def select_watchlist(
    rows: Sequence[Mapping],
    quote_fn: Callable[[str], Quote],
    cap: int = DEFAULT_CAP,
    batch: int = 25,
    workers: int = 6,
    spread_mode: str = "exact",
) -> dict:
    """Apply gates; quote the ADV-ranked shortlist until `cap` names are admitted.

    rows: dicts with ticker, price, adv20_dollars (None allowed = unavailable).

    spread_mode="exact" (default, the strict gate): only names whose Yahoo
    bid/ask passes the spread gate are admitted; unchecked names are
    `not_spread_checked`, failed quotes `spread_unavailable`.

    spread_mode="modeled" (PAPER ONLY, Jared 2026-09-25): each name's quote is
    resolved by risk_math.resolve_quote. A Yahoo quote that passes the gate is
    used as-is; otherwise a modeled $0.05 spread around the quote mid (or the
    last trade, when the mid is unusable or far from last) is used. A name is
    excluded only when there is no usable mid and no usable last trade
    (`no_usable_mid_or_last`). Names ranked below the cap are `beyond_cap`.
    The price gate (on the resolved mid) and ADV gate stay exact.
    """
    if spread_mode not in ("exact", "modeled"):
        raise ValueError(f"unknown spread_mode {spread_mode!r}")
    if spread_mode == "modeled":
        return _select_modeled(rows, quote_fn, cap, batch, workers)
    excluded: Dict[str, str] = {}
    shortlist = []
    for r in rows:
        pre = [x for x in universe_reasons(r.get("price"), r.get("adv20_dollars"), None) if x != "spread_unavailable"]
        if pre:
            excluded[r["ticker"]] = pre[0]
        else:
            shortlist.append(r)
    shortlist.sort(key=lambda r: (-float(r["adv20_dollars"]), r["ticker"]))

    admitted: List[dict] = []
    checked = 0
    i = 0
    while i < len(shortlist) and len(admitted) < cap:
        chunk = shortlist[i : i + batch]
        i += len(chunk)

        def _safe(t: str) -> Optional[Quote]:
            try:
                return quote_fn(t)
            except guards.GuardBlocked:
                raise  # abort the build; never turn a guard stop into exclusions
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            quotes = list(pool.map(_safe, [r["ticker"] for r in chunk]))
        for r, q in zip(chunk, quotes):
            checked += 1
            if len(admitted) >= cap:
                excluded[r["ticker"]] = "beyond_cap"
                continue
            spread, mid = spread_from_quote(q)
            if spread is None:
                excluded[r["ticker"]] = "spread_unavailable"
                continue
            reasons = universe_reasons(mid, r["adv20_dollars"], spread)
            if reasons:
                excluded[r["ticker"]] = reasons[0]
                continue
            admitted.append(
                {
                    "ticker": r["ticker"],
                    "rank": len(admitted) + 1,
                    "sector": r.get("sector"),
                    "security_type": r.get("security_type"),
                    "price": r.get("price"),
                    "adv20_dollars": r.get("adv20_dollars"),
                    "bid": float(q[0]),
                    "ask": float(q[1]),
                    "spread": float(spread),
                    "spread_limit": float(stock_spread_limit(mid)),
                }
            )
    for r in shortlist[i:]:
        excluded[r["ticker"]] = "not_spread_checked"

    summary: Dict[str, int] = {}
    for reason in excluded.values():
        summary[reason] = summary.get(reason, 0) + 1
    return {
        "names": admitted,
        "excluded": excluded,
        "funnel": {
            "candidates": len(rows),
            "passed_price_adv": len(shortlist),
            "spread_checked": checked,
            "admitted": len(admitted),
        },
        "excluded_summary": dict(sorted(summary.items())),
    }


def _select_modeled(rows, quote_fn, cap, batch, workers) -> dict:
    excluded: Dict[str, str] = {}
    shortlist = []
    for r in rows:
        pre = [x for x in universe_reasons(r.get("price"), r.get("adv20_dollars"), None) if x != "spread_unavailable"]
        if pre:
            excluded[r["ticker"]] = pre[0]
        else:
            shortlist.append(r)
    shortlist.sort(key=lambda r: (-float(r["adv20_dollars"]), r["ticker"]))

    admitted: List[dict] = []
    fallbacks: Dict[str, str] = {}
    quoted = 0
    i = 0
    while i < len(shortlist) and len(admitted) < cap:
        chunk = shortlist[i : i + batch]
        i += len(chunk)

        def _safe(t: str):
            try:
                return quote_fn(t)
            except guards.GuardBlocked:
                raise  # abort the build; never turn a guard stop into exclusions
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            quotes = list(pool.map(_safe, [r["ticker"] for r in chunk]))
        for r, q in zip(chunk, quotes):
            quoted += 1
            if len(admitted) >= cap:
                excluded[r["ticker"]] = "beyond_cap"
                continue
            bid, ask, last = _quote_parts(q)
            res = resolve_quote(bid, ask, last)
            if not res["usable"]:
                excluded[r["ticker"]] = res["reason"]
                continue
            reasons = universe_reasons(res["mid"], r["adv20_dollars"], res["spread"])
            if reasons:
                excluded[r["ticker"]] = reasons[0]
                continue
            if res["fallback_reason"]:
                fallbacks[r["ticker"]] = res["fallback_reason"]
            admitted.append(
                {
                    "ticker": r["ticker"],
                    "rank": len(admitted) + 1,
                    "sector": r.get("sector"),
                    "security_type": r.get("security_type"),
                    "price": r.get("price"),
                    "adv20_dollars": r.get("adv20_dollars"),
                    "bid": float(res["bid"]),
                    "ask": float(res["ask"]),
                    "mid": float(res["mid"]),
                    "spread": float(res["spread"]),
                    "spread_limit": float(stock_spread_limit(res["mid"])),
                    "spread_source": res["spread_source"],
                    "mid_source": res["mid_source"],
                    "provisional": True,
                    "yahoo_bid": _float_or_none(bid),
                    "yahoo_ask": _float_or_none(ask),
                    "last_trade": _float_or_none(last),
                    "quote_time": q.get("quote_time") if isinstance(q, Mapping) else None,
                    "market_state": q.get("market_state") if isinstance(q, Mapping) else None,
                }
            )
    for r in shortlist[i:]:
        excluded[r["ticker"]] = "beyond_cap"

    summary: Dict[str, int] = {}
    for reason in excluded.values():
        summary[reason] = summary.get(reason, 0) + 1
    by_source: Dict[str, int] = {}
    for n in admitted:
        by_source[n["spread_source"]] = by_source.get(n["spread_source"], 0) + 1
    return {
        "names": admitted,
        "excluded": excluded,
        "fallbacks": dict(sorted(fallbacks.items())),
        "funnel": {
            "candidates": len(rows),
            "passed_price_adv": len(shortlist),
            "quoted": quoted,
            "admitted": len(admitted),
            "admitted_by_spread_source": dict(sorted(by_source.items())),
            "mid_from_last_trade": sum(1 for n in admitted if n["mid_source"] == "last_trade"),
            "mid_unverified": sum(1 for n in admitted if n["mid_source"] == "quote_mid_unverified"),
        },
        "excluded_summary": dict(sorted(summary.items())),
    }


def _float_or_none(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


# ------------------------------------------------------------ build

def gather_rows(
    candidates: Sequence[Mapping],
    workers: int = 8,
    fetcher=None,
) -> Tuple[List[dict], Dict[str, str]]:
    def one(c: Mapping) -> dict:
        try:
            m = bars_mod.ticker_metrics(c["ticker"], fetcher=fetcher, max_age_minutes=bars_mod.default_max_age_minutes())
            return {
                "ticker": c["ticker"],
                "sector": c.get("sector"),
                "security_type": c.get("security_type"),
                "price": m["last_price"],
                "adv20_dollars": m["adv20_dollars"],
            }
        except bars_mod.BarsUnavailable as exc:
            return {"ticker": c["ticker"], "sector": c.get("sector"), "error": exc.reason}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, candidates))
    rows = [r for r in results if "error" not in r]
    errors = {r["ticker"]: "bars_unavailable" for r in results if "error" in r}
    return rows, errors


def run_gates(
    universe: Mapping,
    types: Mapping[str, Mapping],
    quote_fn: Callable,
    spread_mode: str = "modeled",
    cap: int = DEFAULT_CAP,
    bar_workers: int = 8,
    quote_workers: int = 6,
    rows_fn: Callable = None,
    pinned: Optional[Sequence[Mapping]] = None,
) -> dict:
    """Gates on the persisted top-N-per-sector members plus the pinned names.

    No backfill: a top-N member that fails any gate leaves its slot empty, and
    nothing below the top N in a sector is ever considered. Pinned names
    (ndx_universe.resolve_pinned) are added on top: they pass the same gates,
    never use a sector slot, and never displace a top-N member. A pinned name
    already in the top N appears once with origin [ndx_top5, pinned]. A pinned
    name whose sector or market cap cannot be determined is excluded as
    security_type_unknown (fail closed). Every excluded name is recorded with
    its origin."""
    rows_fn = rows_fn or (lambda c: gather_rows(c, workers=bar_workers))
    top5 = [dict(m) for m in universe.get("members") or []]
    members = ndx_universe.merge_pinned(top5, list(pinned or []))
    by_ticker = {m["ticker"]: m for m in members}
    typed, type_excluded = apply_security_types(members, types)
    pinned_unknown: Dict[str, str] = {}
    eligible = []
    for m in typed:
        if ndx_universe.ORIGIN_TOP5 not in m["origin"] and (not m.get("sector") or m.get("market_cap") is None):
            pinned_unknown[m["ticker"]] = "security_type_unknown"
        else:
            eligible.append(m)
    rows, bar_errors = rows_fn(eligible)
    result = select_watchlist(rows, quote_fn, cap=cap, workers=quote_workers, spread_mode=spread_mode)
    for extra in (bar_errors, type_excluded, pinned_unknown):
        result["excluded"].update(extra)
        for reason in extra.values():
            result["excluded_summary"][reason] = result["excluded_summary"].get(reason, 0) + 1
    result["excluded_summary"] = dict(sorted(result["excluded_summary"].items()))
    for n in result["names"]:
        m = by_ticker.get(n["ticker"]) or {}
        n["sector"] = m.get("sector")
        n["sector_rank"] = m.get("sector_rank")
        n["market_cap"] = m.get("market_cap")
        n["origin"] = list(m.get("origin") or [])
    admitted = {n["ticker"]: n for n in result["names"]}
    sectors: Dict[str, List[dict]] = {}
    for sector, slots in (universe.get("sectors") or {}).items():
        sectors[sector] = []
        for m in slots:
            n = admitted.get(m["ticker"])
            entry = {
                "ticker": m["ticker"],
                "sector_rank": m["sector_rank"],
                "market_cap": m.get("market_cap"),
                "origin": list(by_ticker[m["ticker"]]["origin"]),
            }
            if n:
                entry.update(status="admitted", spread_source=n.get("spread_source"), mid_source=n.get("mid_source"))
            else:
                entry.update(status="excluded", reason=result["excluded"].get(m["ticker"], "unknown"))
            sectors[sector].append(entry)
    pinned_view = []
    for m in members:
        if ndx_universe.ORIGIN_PINNED not in m["origin"]:
            continue
        n = admitted.get(m["ticker"])
        entry = {"ticker": m["ticker"], "sector": m.get("sector"), "market_cap": m.get("market_cap"), "origin": list(m["origin"])}
        if n:
            entry.update(status="admitted", spread_source=n.get("spread_source"), mid_source=n.get("mid_source"))
        else:
            entry.update(status="excluded", reason=result["excluded"].get(m["ticker"], "unknown"))
        pinned_view.append(entry)
    excluded_members = {
        t: {
            "reason": r,
            "origin": list((by_ticker.get(t) or {}).get("origin") or []),
            "sector": (by_ticker.get(t) or {}).get("sector"),
            "sector_rank": (by_ticker.get(t) or {}).get("sector_rank"),
            "market_cap": (by_ticker.get(t) or {}).get("market_cap"),
        }
        for t, r in sorted(result["excluded"].items())
    }
    for t, kept in (universe.get("duplicate_share_classes") or {}).items():
        if t in excluded_members or t in admitted:
            continue  # e.g. a pinned class that was gated on its own
        km = by_ticker.get(kept) or {}
        excluded_members[t] = {
            "reason": "duplicate_share_class",
            "origin": [ndx_universe.ORIGIN_TOP5],
            "kept": kept,
            "sector": km.get("sector"),
            "sector_rank": None,
            "market_cap": None,
        }
    excluded_members = dict(sorted(excluded_members.items()))
    top5_admitted = sum(1 for n in result["names"] if ndx_universe.ORIGIN_TOP5 in n["origin"])
    pinned_members = [m for m in members if ndx_universe.ORIGIN_PINNED in m["origin"]]
    result["sectors"] = sectors
    result["pinned"] = pinned_view
    result["excluded_members"] = excluded_members
    result["type_excluded"] = type_excluded
    result["bar_errors"] = bar_errors
    result["funnel"] = {
        "universe_members": len(top5),
        "pinned": len(pinned_members),
        "pinned_also_top5": sum(1 for m in pinned_members if ndx_universe.ORIGIN_TOP5 in m["origin"]),
        "names_gated": len(members),
        "security_type_excluded": len(type_excluded) + len(pinned_unknown),
        "common_stock": len(eligible),
        "bars_unavailable": len(bar_errors),
        **{k: v for k, v in result["funnel"].items() if k != "candidates"},
        "admitted_top5": top5_admitted,
        "admitted_pinned_only": len(result["names"]) - top5_admitted,
        "empty_slots": len(top5) - top5_admitted,
    }
    return result


def _display_path(path: Path) -> str:
    rp = Path(path).resolve()
    try:
        return str(rp.relative_to(ROOT))
    except ValueError:
        return str(rp)


def _memo_get_json():
    cache: Dict[str, Mapping] = {}

    def get(url: str) -> Mapping:
        if url not in cache:
            cache[url] = _get_json(url)
        return cache[url]

    return get


def build(
    cap: int,
    out: Path,
    universe_path: Path,
    bar_workers: int,
    quote_workers: int,
    spread_mode: str = "modeled",
    refresh_universe: bool = False,
    config_path: Path = DEFAULT_UNIVERSE_CONFIG,
) -> dict:
    pinned_tickers = ndx_universe.load_pinned(config_path)  # before any fetch; malformed config aborts
    guards.preflight()  # refuse inside daemon windows; bounded wait on the pipeline lock
    t0 = time.perf_counter()
    get_json = _memo_get_json()  # one screener download serves sector + type lookups
    now = guards._now_ct()
    universe = ndx_universe.get_universe(universe_path, get_json, now, refresh=refresh_universe)
    try:
        screener = get_json(SCREENER_URL)
    except Exception:
        screener = None  # pinned sector/cap unknown -> excluded (fail closed)
    pinned = ndx_universe.resolve_pinned(pinned_tickers, screener)
    tickers = list(dict.fromkeys([m["ticker"] for m in universe["members"]] + pinned_tickers))
    types = fetch_security_types(tickers, get_json=get_json)
    t1 = time.perf_counter()
    quote_fn = yahoo_quote_full if spread_mode == "modeled" else yahoo_quote
    result = run_gates(
        universe,
        types,
        quote_fn,
        spread_mode=spread_mode,
        cap=cap,
        bar_workers=bar_workers,
        quote_workers=quote_workers,
        pinned=pinned,
    )
    t2 = time.perf_counter()
    type_excluded = result["type_excluded"]
    doc = {
        "schema": "dragonfly.watchlist/2",
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "yahoo",
        "provisional": True,
        "universe": {
            "definition": (
                f"top {universe['per_sector']} Nasdaq-100 companies by market cap in each sector (no backfill), "
                "plus the pinned names from the universe config; every name passes every gate"
            ),
            "pinned_config": _display_path(config_path),
            "pinned": pinned_tickers,
            "pinned_rule": (
                "added on top of the top-5 rule; not admitted unless every gate passes; no sector slot used; "
                "never displaces a top-5 member; already-top-5 names carry origin [ndx_top5, pinned]; sector / "
                "market cap from the Nasdaq screener, else security_type_unknown"
            ),
            "file": _display_path(universe_path),
            "as_of": universe["as_of"],
            "as_of_date": universe["as_of_date"],
            "reused": universe["reused"],
            "age_days": universe["age_days"],
            "refresh": universe.get("refresh"),
            "sector_field": universe.get("sector_field"),
            "market_cap_field": universe.get("market_cap_field"),
            "sector_sizes": universe.get("sector_sizes"),
            "ranking_excluded": universe.get("excluded"),
            "duplicate_share_classes": universe.get("duplicate_share_classes"),
            "share_class_rule": universe.get("share_class_rule"),
        },
        "cap": cap,
        "cap_note": "harmless upper bound; the universe is at most 5 names per sector",
        "rank_key": "adv20_dollars desc among admitted names (sector/sector_rank/market_cap carried per name)",
        "spread_mode": "modeled_mid_0.05 (paper only)" if spread_mode == "modeled" else "exact",
        "gates": {
            "min_price": str(MIN_PRICE),
            "min_adv20_dollars": str(MIN_ADV_DOLLARS),
            "adv_window_sessions": bars_mod.ADV_WINDOW,
            "max_spread": f"max({MAX_STOCK_SPREAD_ABS}, {MAX_STOCK_SPREAD_PCT} * mid)",
            "gate_source": "dragonfly.risk_math.universe_reasons",
            "no_backfill": "a top-5 member that fails any gate leaves its slot empty; lower-ranked names are never pulled in",
            "spread_check": (
                "Yahoo bid/ask for each universe member. Names with a failed/unusable bid/ask "
                "(spread_unavailable) are excluded, never admitted."
            )
            if spread_mode == "exact"
            else (
                "PAPER ONLY (Jared 2026-09-25). Yahoo bid/ask/last for each universe member. A quote that "
                "passes the spread gate as-is is used (spread_source yahoo). Otherwise a modeled $0.05 spread "
                "around the quote mid (modeled_mid_0.05), or around the last trade when bid/ask give no usable "
                "mid or the mid is more than the gate width from last (modeled_last_0.05). Excluded only with "
                "no usable mid and no usable last trade (no_usable_mid_or_last). Modeled names are provisional "
                "and blocked from live approval (provisional_source_live)."
            ),
            "not_halted": (
                "not checked directly; a halted name has no live bid/ask and fails spread_unavailable"
                if spread_mode == "exact"
                else "not checked directly; in modeled mode a halted name with a last trade can be admitted "
                "(modeled_last_0.05, provisional). Trigger-time checks must not rely on the watchlist for halts."
            ),
            "security_type": (
                "US listed common stock only (incl. ordinary / subordinate-voting shares of directly listed "
                "foreign issuers). Depositary receipts excluded (depositary_receipt); preferred/units/etc. "
                "excluded (not_common_stock); undeterminable type excluded (security_type_unknown). "
                "Source: Nasdaq screener descriptor -> Nasdaq quote-info stockType -> explicit denylist."
            ),
        },
        "security_type_exclusions": {
            t: {"reason": type_excluded[t], **(types.get(t) or {})} for t in sorted(type_excluded)
        },
        "funnel": result["funnel"],
        "excluded_summary": result["excluded_summary"],
        "timing_seconds": {"universe_and_types": round(t1 - t0, 2), "bars_and_quotes": round(t2 - t1, 2)},
        "sectors": result["sectors"],
        "pinned": result["pinned"],
        "names": result["names"],
        "quote_fallbacks": result.get("fallbacks", {}),
        "excluded": result["excluded_members"],
    }
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP, help="harmless upper bound (universe is <= 5 per sector)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE)
    ap.add_argument("--universe-config", type=Path, default=DEFAULT_UNIVERSE_CONFIG, help="pinned names config")
    ap.add_argument(
        "--refresh-universe",
        action="store_true",
        help="re-fetch and re-rank NDX membership now (otherwise reused until 7+ days old)",
    )
    ap.add_argument("--bar-workers", type=int, default=8)
    ap.add_argument("--quote-workers", type=int, default=6)
    ap.add_argument("--allow-daemon-window", action="store_true", help="explicit override of the daemon-window guard")
    ap.add_argument(
        "--spread-mode",
        choices=("modeled", "exact"),
        default="modeled",
        help="modeled (default, PAPER ONLY): $0.05 modeled spread when Yahoo's quote is junk; exact: strict gate",
    )
    args = ap.parse_args(argv)
    if args.allow_daemon_window:
        os.environ[guards.ENV_ALLOW_WINDOW] = "1"
    try:
        doc = build(
            args.cap,
            args.out,
            args.universe_file,
            args.bar_workers,
            args.quote_workers,
            args.spread_mode,
            args.refresh_universe,
            args.universe_config,
        )
    except guards.GuardBlocked as exc:
        print(json.dumps({"blocked": exc.reason, "detail": exc.detail}))
        print("watchlist NOT written")
        return 2
    print(json.dumps({k: doc[k] for k in ("as_of", "funnel", "excluded_summary", "timing_seconds")}, indent=1))
    u = doc["universe"]
    print(f"universe as_of {u['as_of_date']} ({'reused' if u['reused'] else 'refreshed'}, age {u['age_days']}d)")
    print(f"wrote {args.out} ({len(doc['names'])} names)")
    return 0 if doc["names"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
