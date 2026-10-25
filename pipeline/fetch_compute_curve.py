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
import compute_outlook

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"
API_URL = "https://aicomputetracker.com/forward-curves.json"
SOURCE_URL = "https://aicomputetracker.com/"
KALSHI_URL = "https://kalshi.com/markets/kxh100ms"
CHIPS = ("a100", "h100", "b200", "h200")  # chart shows A100/H100/B200; H200 kept for later
# Indexes into the monthly points (Anchor dropped): front month, +2 months, +8 months.
CARD_TENOR_INDEXES = (0, 2, 8)


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


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def tenor_label(tenor_key: str) -> Optional[str]:
    """'2027-06' -> "Jun '27". Year comes from the data's tenorKey, never hardcoded."""
    try:
        y, m = tenor_key.split("-")
        return f"{MONTHS[int(m) - 1]} '{int(y) % 100:02d}"
    except Exception:
        return None


def is_placeholder(p: Dict[str, Any]) -> bool:
    """True when the tracker's value is a placeholder, not a price (Oct 25 2026 sweep, item 9).

    Per forward-curves.json's own note: when no quote sets the level, "a closed bracket gives
    its midpoint, and an open one only a placeholder ... that the site never shows as a price".
    So a point whose evidence.valueSource is "bracket" with either side open (loOpen/hiOpen)
    is a placeholder (e.g. H100 Jun/Jul/Aug '27 $3.88/$3.91/$1.35 on Oct 25 2026). An explicit
    placeholder flag, if the tracker ever adds one, is honoured too.
    """
    ev = p.get("evidence") or {}
    if p.get("placeholder") is True or ev.get("placeholder") is True:
        return True
    return ev.get("valueSource") == "bracket" and bool(ev.get("loOpen") or ev.get("hiOpen"))


def chip_points(chip: Dict[str, Any], dropped: Optional[list] = None):
    """Monthly points with tenor_key/label/price, skipping the Anchor (dupe of front month)
    and any tracker placeholder (its tenor_key is appended to `dropped`)."""
    pts = []
    for p in chip.get("points") or []:
        ev = p.get("evidence") or {}
        key = ev.get("tenorKey") or None
        price = p.get("priceUsdPerGpuHour")
        label = tenor_label(key) if key else None
        if not label or price is None:
            continue
        if is_placeholder(p):
            if dropped is not None:
                dropped.append(key)
            continue
        pt = {"tenor_key": key, "tenor": label, "price": round(float(price), 2),
              "quality": p.get("quality")}
        if isinstance(ev.get("identified"), bool):
            pt["identified"] = ev["identified"]
        pts.append(pt)
    pts.sort(key=lambda x: x["tenor_key"])
    return pts


def parse(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    as_of = raw.get("asOf")
    if not as_of:
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
        dropped: list = []
        pts = chip_points(chip, dropped)
        if not pts:
            continue
        prov = chip.get("provenance") or {}
        out[cid] = {
            "points": pts,
            "placeholders_dropped": sorted(dropped),
            "card": [pts[i] for i in CARD_TENOR_INDEXES if i < len(pts)],
            "two_sided_markets": prov.get("twoSidedMarketCount"),
            "liquidity_usd": round(prov.get("totalLiquidityUsd") or 0),
            "kalshi_series": prov.get("monthlySeriesTicker"),
            "last_trade_at": prov.get("latestMarketAt"),
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
            compute_outlook.apply(md)
            save_market_data(md, MARKET_DATA_FILE)
        print("  ✗ forward curve unavailable; previous value kept (stale)")
        return 1
    md["compute_forward_curve"] = data
    line = compute_outlook.apply(md)
    if line:
        print(f"Outlook: {line}")
    ok, msg = save_market_data(md, MARKET_DATA_FILE)
    if not ok:
        print(f"  ✗ save failed: {msg}")
        return 1
    h = data["h100"]["card"]
    print("H100 fwd: " + " · ".join(f"{p['tenor']} ${p['price']:.2f}" for p in h) + f" (as of {data['as_of']})")
    return 0


if __name__ == "__main__":
    exit(main())
