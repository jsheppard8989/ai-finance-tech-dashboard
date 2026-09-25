"""Build dragonfly/watchlist.json: the Phase 1 liquid watchlist (cap 200).

Candidates: S&P 500 + Nasdaq-100 constituents (Wikipedia tables, fetched at
build time; or --candidates-file). Gates are the EXISTING universe gates from
dragonfly/risk_math.py via `universe_reasons` (not re-typed here):
  price >= $10, 20-day ADV >= $25M, spread <= max($0.05, 0.15% of price).

Order of work:
  1. Bars for every candidate (dragonfly/bars.py; one history call per name,
     cached). Price and 20-day ADV gates run on every candidate.
  2. Survivors are ranked by ADV, descending.
  3. Spread gate (Yahoo bid/ask) runs down that ranked shortlist, in rank
     order, until `cap` names pass. Fail closed:
       - a name whose bid/ask fetch fails or is unusable -> excluded
         (spread_unavailable);
       - a name that is never spread-checked because the cap filled first
         -> excluded (not_spread_checked). It is never admitted.
     Only names that were spread-checked and passed are admitted.

Output is stamped source="yahoo", provisional=True, with an as_of and the gate
parameters. The scanner must read only `names` from this file.

Python 3.9 compatible. Run (market hours, so bid/ask is live):
  python3 dragonfly/build_watchlist.py [--cap 200] [--out dragonfly/watchlist.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonfly import bars as bars_mod  # noqa: E402
from dragonfly.risk_math import (  # noqa: E402
    MAX_STOCK_SPREAD_ABS,
    MAX_STOCK_SPREAD_PCT,
    MIN_ADV_DOLLARS,
    MIN_PRICE,
    D,
    stock_spread_limit,
    universe_reasons,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "dragonfly" / "watchlist.json"
DEFAULT_CAP = 200
SOURCES = {
    # S&P 500: Wikipedia constituents table (has GICS sector).
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    # Nasdaq-100: Nasdaq's own index list (Wikipedia no longer carries the table).
    "ndx100": "https://api.nasdaq.com/api/quote/list-type/nasdaq100",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

Quote = Tuple[Optional[float], Optional[float]]  # (bid, ask)


# ------------------------------------------------------------ constituents

class _TableParser(HTMLParser):
    """Collect the rows of every top-level `wikitable` on the page."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.tables: List[Tuple[Optional[str], List[List[str]]]] = []
        self._rows: Optional[List[List[str]]] = None
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if self.depth == 0 and "wikitable" in (a.get("class") or ""):
                self.depth = 1
                self._rows = []
                self.tables.append((a.get("id"), self._rows))
            elif self.depth:
                self.depth += 1
        elif self.depth == 1 and tag == "tr":
            self._row = []
        elif self.depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self._rows = None
        elif self.depth == 1 and tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self.depth == 1 and tag == "tr" and self._row is not None:
            if self._row and self._rows is not None:
                self._rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


_SYMBOL_HEADERS = ("symbol", "ticker")


def _pick_table(tables) -> List[List[str]]:
    """Prefer id="constituents"; else the largest wikitable with a Symbol/Ticker header."""
    for tid, rows in tables:
        if tid == "constituents" and rows:
            return rows
    best: List[List[str]] = []
    for _tid, rows in tables:
        if rows and any(h.lower() in _SYMBOL_HEADERS for h in rows[0]) and len(rows) > len(best):
            best = rows
    return best


def parse_constituents(html: str) -> List[Dict[str, Optional[str]]]:
    p = _TableParser()
    p.feed(html)
    rows = _pick_table(p.tables)
    if len(rows) < 51:
        raise ValueError("constituents table not found")
    header = [h.lower() for h in rows[0]]
    sym_idx = next(i for i, h in enumerate(header) if h in _SYMBOL_HEADERS)
    sec_idx = next((i for i, h in enumerate(header) if h in ("gics sector", "icb industry")), None)
    name_idx = next((i for i, h in enumerate(header) if h in ("security", "company")), None)
    out = []
    for row in rows[1:]:
        if len(row) != len(header):
            continue
        sym = row[sym_idx].strip().upper().replace(".", "-")
        if not sym or not sym.replace("-", "").isalnum():
            continue
        out.append(
            {
                "ticker": sym,
                "name": row[name_idx] if name_idx is not None else None,
                "sector": row[sec_idx] if sec_idx is not None else None,
            }
        )
    return out


def parse_nasdaq_list(payload: Mapping) -> List[Dict[str, Optional[str]]]:
    rows = ((payload.get("data") or {}).get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper().replace(".", "-").replace("/", "-")
        if sym and sym.replace("-", "").isalnum():
            out.append({"ticker": sym, "name": r.get("companyName"), "sector": r.get("sector") or None})
    if len(out) < 90:
        raise ValueError(f"nasdaq-100 list too short ({len(out)})")
    return out


def _get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_candidates() -> Tuple[List[Dict[str, Optional[str]]], Dict[str, int]]:
    """Union of S&P 500 and Nasdaq-100. Raises if either source fails."""
    lists = {
        "sp500": parse_constituents(_get(SOURCES["sp500"], "text/html").decode("utf-8", "replace")),
        "ndx100": parse_nasdaq_list(json.loads(_get(SOURCES["ndx100"], "application/json"))),
    }
    merged: Dict[str, Dict[str, Optional[str]]] = {}
    counts: Dict[str, int] = {}
    for key, rows in lists.items():
        counts[key] = len(rows)
        for r in rows:
            prior = merged.get(r["ticker"])
            if prior is None or (not prior.get("sector") and r.get("sector")):
                merged[r["ticker"]] = r
    counts["union"] = len(merged)
    return sorted(merged.values(), key=lambda r: r["ticker"]), counts


# ------------------------------------------------------------ quotes

def yahoo_quote(ticker: str) -> Quote:
    import yfinance as yf  # lazy

    info = yf.Ticker(ticker).info or {}
    return info.get("bid"), info.get("ask")


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
) -> dict:
    """Apply gates; spread-check the ADV-ranked shortlist until `cap` pass.

    rows: dicts with ticker, price, adv20_dollars (None allowed = unavailable).
    Only spread-checked, passing names are admitted. Everything else is
    excluded with a reason; unchecked names are `not_spread_checked`.
    """
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


# ------------------------------------------------------------ build

def gather_rows(
    candidates: Sequence[Mapping],
    workers: int = 8,
    fetcher=None,
) -> Tuple[List[dict], Dict[str, str]]:
    def one(c: Mapping) -> dict:
        try:
            m = bars_mod.ticker_metrics(c["ticker"], fetcher=fetcher)
            return {"ticker": c["ticker"], "sector": c.get("sector"), "price": m["last_price"], "adv20_dollars": m["adv20_dollars"]}
        except bars_mod.BarsUnavailable as exc:
            return {"ticker": c["ticker"], "sector": c.get("sector"), "error": exc.reason}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, candidates))
    rows = [r for r in results if "error" not in r]
    errors = {r["ticker"]: "bars_unavailable" for r in results if "error" in r}
    return rows, errors


def build(cap: int, out: Path, candidates_file: Optional[Path], bar_workers: int, quote_workers: int) -> dict:
    t0 = time.perf_counter()
    if candidates_file:
        candidates = json.loads(candidates_file.read_text())
        counts = {"file": len(candidates), "union": len(candidates)}
    else:
        candidates, counts = fetch_candidates()
    t1 = time.perf_counter()
    rows, bar_errors = gather_rows(candidates, workers=bar_workers)
    t2 = time.perf_counter()
    result = select_watchlist(rows, yahoo_quote, cap=cap, workers=quote_workers)
    t3 = time.perf_counter()
    result["excluded"].update(bar_errors)
    for k in bar_errors:
        result["excluded_summary"]["bars_unavailable"] = result["excluded_summary"].get("bars_unavailable", 0) + 1
    result["funnel"]["bars_unavailable"] = len(bar_errors)
    doc = {
        "schema": "dragonfly.watchlist/1",
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "yahoo",
        "provisional": True,
        "cap": cap,
        "rank_key": "adv20_dollars desc",
        "gates": {
            "min_price": str(MIN_PRICE),
            "min_adv20_dollars": str(MIN_ADV_DOLLARS),
            "adv_window_sessions": bars_mod.ADV_WINDOW,
            "max_spread": f"max({MAX_STOCK_SPREAD_ABS}, {MAX_STOCK_SPREAD_PCT} * mid)",
            "gate_source": "dragonfly.risk_math.universe_reasons",
            "spread_check": (
                "Yahoo bid/ask on the ADV-ranked shortlist, in rank order, until the cap fills. "
                "Names never spread-checked (not_spread_checked) or with a failed/unusable "
                "bid/ask (spread_unavailable) are excluded, never admitted."
            ),
            "not_halted": "not checked directly; a halted name has no live bid/ask and fails spread_unavailable",
        },
        "candidate_sources": {**SOURCES, "counts": counts} if not candidates_file else {"file": str(candidates_file), "counts": counts},
        "funnel": result["funnel"],
        "excluded_summary": result["excluded_summary"],
        "timing_seconds": {
            "candidates": round(t1 - t0, 2),
            "bars": round(t2 - t1, 2),
            "spread_quotes": round(t3 - t2, 2),
        },
        "names": result["names"],
        "excluded": dict(sorted(result["excluded"].items())),
    }
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--candidates-file", type=Path, default=None)
    ap.add_argument("--bar-workers", type=int, default=8)
    ap.add_argument("--quote-workers", type=int, default=6)
    args = ap.parse_args(argv)
    doc = build(args.cap, args.out, args.candidates_file, args.bar_workers, args.quote_workers)
    print(json.dumps({k: doc[k] for k in ("as_of", "funnel", "excluded_summary", "timing_seconds")}, indent=1))
    print(f"wrote {args.out} ({len(doc['names'])} names)")
    return 0 if doc["names"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
