#!/usr/bin/env python3
"""
Fetch a free, machine-readable H100/B200 GPU forward curve for the Compute Forward card.

Source: AI Compute Tracker forward-curves.json (CC BY 4.0)
  https://aicomputetracker.com/forward-curves.json
It reconstructs a monthly forward curve (USD per GPU-hour) from Kalshi's
"H100 Monthly" / "B200 Monthly" contract ladders, which settle on the Ornn
Compute Price Index (OCPI). Values are market-implied medians, not executable quotes,
and the ladders are thin, so the card labels them as indicative.

Writes market_data['compute_forward_curve'] (a separate key, so the SemiAnalysis
fetcher, which replaces market_data['compute_forward'] wholesale, never clobbers it).
Fail-closed: on any error the previous curve is kept and marked stale.
"""

import json
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional

from workspace_paths import SITE_DATA_DIR
from market_data_io import load_market_data, save_market_data

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"
API_URL = "https://aicomputetracker.com/forward-curves.json"
SOURCE_URL = "https://aicomputetracker.com/"
KALSHI_URL = "https://kalshi.com/markets/kxh100ms"
CHIPS = ("h100", "b200")
# Tenors surfaced on the card: front month, +2 months, and the far end (~10 months out).
CARD_TENOR_INDEXES = (1, 3, 9)


def fetch_json() -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(API_URL, headers={
            "User-Agent": "ai-finance-tech-dashboard/1.0 (+https://jsheppard8989.github.io/ai-finance-tech-dashboard/)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  ✗ forward-curves.json fetch failed: {e}")
        return None


def parse(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tenors = raw.get("tenors") or []
    as_of = raw.get("asOf")
    if not tenors or not as_of:
        return None
    out: Dict[str, Any] = {
        "_comment": "Kalshi-implied monthly GPU forward curve via AI Compute Tracker (CC BY 4.0). Indicative, not executable.",
        "_source_url": SOURCE_URL,
        "_api_url": API_URL,
        "_settles_on": "Ornn Compute Price Index (OCPI)",
        "_license": (raw.get("license") or {}).get("attribution", "AI Compute Tracker (aicomputetracker.com), CC BY 4.0"),
        "as_of": as_of,
        "unit": raw.get("unit", "USD per GPU-hour"),
        "methodology": raw.get("methodologyVersion"),
        "last_fetched": datetime.now().isoformat(),
    }
    for chip in raw.get("chips", []):
        cid = chip.get("id")
        if cid not in CHIPS:
            continue
        curve = chip.get("curve") or []
        if len(curve) != len(tenors) or any(v is None for v in curve):
            continue
        prov = chip.get("provenance") or {}
        out[cid] = {
            "points": [{"tenor": t.replace("\u2019", "'"), "price": round(float(v), 2)}
                       for t, v in zip(tenors, curve)][1:],  # drop "Anchor" (dupe of front month)
            "card": [{"tenor": tenors[i].replace("\u2019", "'"), "price": round(float(curve[i]), 2)}
                     for i in CARD_TENOR_INDEXES if i < len(curve)],
            "two_sided_markets": prov.get("twoSidedMarketCount"),
            "liquidity_usd": round(prov.get("totalLiquidityUsd") or 0),
            "kalshi_series": prov.get("monthlySeriesTicker"),
        }
    return out if "h100" in out else None


def main() -> int:
    md, note = load_market_data(MARKET_DATA_FILE, repair=True)
    if not isinstance(md, dict):
        md = {}
    raw = fetch_json()
    data = parse(raw) if raw else None
    if not data:
        prev = md.get("compute_forward_curve")
        if isinstance(prev, dict):
            prev["_stale"] = True
            prev["_stale_reason"] = "forward-curves.json fetch/parse failed"
            md["compute_forward_curve"] = prev
            save_market_data(md, MARKET_DATA_FILE)
        print("  ✗ forward curve unavailable; previous value kept (stale)")
        return 1
    md["compute_forward_curve"] = data
    ok, msg = save_market_data(md, MARKET_DATA_FILE)
    if not ok:
        print(f"  ✗ save failed: {msg}")
        return 1
    h = data["h100"]["card"]
    print("H100 fwd: " + " · ".join(f"{p['tenor']} ${p['price']:.2f}" for p in h) + f" (as of {data['as_of']})")
    return 0


if __name__ == "__main__":
    exit(main())
