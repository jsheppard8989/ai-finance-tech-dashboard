#!/usr/bin/env python3
"""
Fetch the Treasury coupon auction calendar + recent results from TreasuryDirect.

Source (public, no key): TreasuryDirect TA_WS
  - recent results:  /TA_WS/securities/auctioned?format=json&days=45
  - upcoming:        /TA_WS/securities/upcoming?format=json
  - announced:       /TA_WS/securities/announced?format=json&days=14 (sizes)
Next refunding (QRA) date is not in the API; it comes from Treasury's refunding
statements (QRA_SCHEDULE below). Past dates are always dropped.

Writes market_data.json -> treasury_calendar. Fail-closed: on fetch/parse
failure, the existing section is preserved and marked _stale.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from workspace_paths import SITE_DATA_DIR
from market_data_io import load_market_data, save_market_data

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"

TA_WS = "https://www.treasurydirect.gov/TA_WS/securities"
AUCTIONED_URL = f"{TA_WS}/auctioned?format=json&days=45"
UPCOMING_URL = f"{TA_WS}/upcoming?format=json"
ANNOUNCED_URL = f"{TA_WS}/announced?format=json&days=14"
SEARCH_URL = f"{TA_WS}/search?format=json"

# Official QRA (refunding statement) dates. Source: Treasury refunding
# statement of 2026-08-05 ("next refunding announcement Wednesday, Nov 4").
QRA_SCHEDULE: List[Tuple[str, str]] = [
    ("2026-11-04", "scheduled"),
]

RECENT_LIMIT = 10
UPCOMING_LIMIT = 8


def _get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (scarcityabundance dashboard; treasury calendar)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _d(s: Optional[str]) -> Optional[str]:
    return s[:10] if s else None


def _f(v: Any, nd: int = 3) -> Optional[float]:
    try:
        if v in (None, ""):
            return None
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _bn(v: Any) -> Optional[float]:
    x = _f(v, 0)
    return round(x / 1e9, 3) if x is not None else None


def _term_short(term: str) -> str:
    """'29-Year 10-Month' -> '29y10m'."""
    out = []
    for part in (term or "").split():
        num, _, unit = part.partition("-")
        out.append(num + (unit[:1].lower() if unit else ""))
    return "".join(out)


def security_label(x: Dict[str, Any]) -> str:
    orig = x.get("originalSecurityTerm") or x.get("securityTerm") or ""
    kind = x.get("securityType") or ""
    if x.get("tips") == "Yes":
        kind = "TIPS"
    elif x.get("floatingRate") == "Yes":
        kind = "FRN"
    label = f"{orig} {kind}".strip()
    if x.get("reopening") == "Yes":
        label += f" ({_term_short(x.get('securityTerm', ''))} reopening)"
    return label


def is_coupon(x: Dict[str, Any]) -> bool:
    return (x.get("securityType") or "") in ("Note", "Bond", "TIPS", "FRN")


def build_result(x: Dict[str, Any]) -> Dict[str, Any]:
    frn = x.get("floatingRate") == "Yes"
    accepted = _f(x.get("totalAccepted"), 0)
    indirect = _f(x.get("indirectBidderAccepted"), 0)
    btc = _f(x.get("bidToCoverRatio"), 2)
    r = {
        "date": _d(x.get("auctionDate")),
        "security": security_label(x),
        "cusip": x.get("cusip"),
        "size_billions": _bn(x.get("offeringAmount")),
        "issue_date": _d(x.get("issueDate")),
        "maturity_date": _d(x.get("maturityDate")),
        "high_yield_pct": None if frn else _f(x.get("highYield")),
        "high_discount_margin_pct": _f(x.get("highDiscountMargin")) if frn else None,
        "coupon_pct": _f(x.get("interestRate")),
        "bid_to_cover": btc,
        "allocation_at_high_pct": _f(x.get("allocationPercentage"), 2),
        "total_tendered_billions": _bn(x.get("totalTendered")),
        "total_accepted_billions": _bn(x.get("totalAccepted")),
        "primary_dealer_accepted_billions": _bn(x.get("primaryDealerAccepted")),
        "direct_accepted_billions": _bn(x.get("directBidderAccepted")),
        "indirect_accepted_billions": _bn(x.get("indirectBidderAccepted")),
        "results_pdf": x.get("pdfFilenameCompetitiveResults") or None,
        "source_url": f"{SEARCH_URL}&cusip={x.get('cusip')}",
    }
    note = []
    if btc is not None:
        note.append(f"BTC {btc:.2f}")
    if accepted and indirect is not None:
        note.append(f"indirect {indirect / accepted * 100:.0f}% of accepted")
    r["stranger_note"] = "; ".join(note) + "." if note else None
    return r


def build_upcoming(x: Dict[str, Any], sizes: Dict[Tuple[str, str], Any]) -> Dict[str, Any]:
    key = (x.get("cusip"), _d(x.get("auctionDate")))
    amt = x.get("offeringAmount") or sizes.get(key)
    return {
        "date": _d(x.get("auctionDate")),
        "security": security_label(x),
        "cusip": x.get("cusip"),
        "size_billions": _bn(amt),
        "announcement_date": _d(x.get("announcementDate")),
        "issue_date": _d(x.get("issueDate")),
    }


def next_qra(today: date) -> Dict[str, Any]:
    for d, status in QRA_SCHEDULE:
        if d >= today.isoformat():
            return {"date": d, "status": status,
                    "notes": "Quarterly Refunding Announcement (QRA), 8:30 AM ET; sets coupon sizes for next quarter"}
    # Fallback estimate: first Wednesday of the next Feb/May/Aug/Nov.
    y, m = today.year, today.month
    for _ in range(15):
        if m in (2, 5, 8, 11):
            d = date(y, m, 1)
            d += timedelta(days=(2 - d.weekday()) % 7)
            if d >= today:
                return {"date": d.isoformat(), "status": "estimated",
                        "notes": "Estimated (first Wednesday of refunding month); confirm with Treasury"}
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return {"date": None, "status": "unknown", "notes": None}


def build_calendar(
    auctioned: List[Dict[str, Any]],
    upcoming: List[Dict[str, Any]],
    announced: Optional[List[Dict[str, Any]]] = None,
    today: Optional[date] = None,
    prior: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    today = today or date.today()
    t = today.isoformat()
    sizes = {(a.get("cusip"), _d(a.get("auctionDate"))): a.get("offeringAmount")
             for a in (announced or []) if a.get("offeringAmount")}

    recent = [x for x in auctioned if is_coupon(x) and _d(x.get("auctionDate"))
              and _d(x.get("auctionDate")) <= t
              and (x.get("highYield") or x.get("highDiscountMargin"))]
    recent.sort(key=lambda x: (x.get("auctionDate") or "", x.get("securityTerm") or ""), reverse=True)

    seen = set()
    ups = []
    for x in sorted(upcoming, key=lambda x: x.get("auctionDate") or ""):
        d = _d(x.get("auctionDate"))
        if not d or d < t or not is_coupon(x):
            continue  # drop past dates and bills
        k = (x.get("cusip"), d)
        if k in seen:
            continue
        seen.add(k)
        ups.append(build_upcoming(x, sizes))

    prior = prior or {}
    return {
        "_comment": "Treasury coupon auction calendar + recent results. Source: TreasuryDirect TA_WS (fetch_treasury_calendar.py). Bills excluded.",
        "_fetch_url": UPCOMING_URL,
        "_results_url": AUCTIONED_URL,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": t,
        "next_refunding_announcement": next_qra(today),
        "upcoming_auctions": ups[:UPCOMING_LIMIT],
        "recent_auction_results": [build_result(x) for x in recent[:RECENT_LIMIT]],
        "refunding_context": prior.get("refunding_context") or {
            "_comment": "Key metrics from latest QRA",
            "net_coupon_issuance_q": None,
            "bills_vs_coupons_mix": None,
            "buyback_program_status": None,
        },
    }


def validate_calendar(cal: Dict[str, Any]) -> Tuple[bool, str]:
    if not cal.get("recent_auction_results"):
        return False, "no recent coupon results parsed"
    t = cal.get("as_of_date") or ""
    for a in cal.get("upcoming_auctions", []):
        if (a.get("date") or "") < t:
            return False, f"upcoming auction in the past: {a.get('date')}"
    return True, ""


def _write(md: Dict[str, Any], status: str) -> bool:
    md.setdefault("data_fetch_status", {})["treasury_calendar"] = status
    if status == "live":
        md["_updated"] = datetime.now().strftime("%Y-%m-%d")
    ok, msg = save_market_data(md, MARKET_DATA_FILE)
    if not ok:
        print(f"  ✗ Refused to write market_data.json: {msg}")
    return ok


def mark_stale(reason: str) -> bool:
    md, note = load_market_data(MARKET_DATA_FILE, repair=True)
    if not md:
        print(f"  ⚠ No usable market_data to mark stale ({note})")
        return False
    tc = md.get("treasury_calendar")
    if isinstance(tc, dict):
        tc["_stale"] = True
        tc["_stale_since"] = datetime.now().isoformat(timespec="seconds")
        tc["_stale_reason"] = reason
    return _write(md, "stale")


def main() -> int:
    print("=" * 60)
    print("Fetch Treasury auction calendar (TreasuryDirect TA_WS)")
    print("=" * 60)
    try:
        auctioned = _get_json(AUCTIONED_URL)
        upcoming = _get_json(UPCOMING_URL)
        try:
            announced = _get_json(ANNOUNCED_URL)
        except Exception as e:  # sizes are optional
            print(f"  ⚠ announced endpoint failed (sizes may be blank): {e}")
            announced = []
    except Exception as e:
        print(f"  ✗ TreasuryDirect fetch failed: {e}")
        mark_stale(f"fetch failed: {e}")
        return 1

    md, note = load_market_data(MARKET_DATA_FILE, repair=True)
    if not isinstance(md, dict) or not md:
        print(f"  ✗ market_data.json unusable ({note}); not writing")
        return 1
    cal = build_calendar(auctioned, upcoming, announced, prior=md.get("treasury_calendar"))
    ok, why = validate_calendar(cal)
    if not ok:
        print(f"  ✗ Validation failed: {why}")
        mark_stale(why)
        return 1
    md["treasury_calendar"] = cal
    if not _write(md, "live"):
        return 1
    print(f"  ✓ QRA {cal['next_refunding_announcement']['date']} ({cal['next_refunding_announcement']['status']})")
    for a in cal["upcoming_auctions"]:
        print(f"  ↑ {a['date']} {a['security']} {a['cusip']} size={a['size_billions']}")
    for r in cal["recent_auction_results"]:
        y = r["high_yield_pct"] if r["high_yield_pct"] is not None else f"DM {r['high_discount_margin_pct']}"
        print(f"  ✓ {r['date']} {r['security']} {y} BTC {r['bid_to_cover']} alloc {r['allocation_at_high_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
