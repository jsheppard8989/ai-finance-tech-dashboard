#!/usr/bin/env python3
"""
One-line GPU price outlook for the Compute Forward chart, regenerated on every refresh.

Per chip (B200, H100, A100) three signals, each a % change:
  - spot now vs ~30 days ago   (SemiAnalysis daily composite, compute_forward.spot_history)
  - spot now vs ~90 days ago
  - forward curve average (months after today) vs today's spot (AI Compute Tracker)
The chip's score is the mean of the signals it has: above +3% = rising, below -3% =
dropping, otherwise steady. Writes market_data['compute_outlook'].
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

CHIPS = ("b200", "h100", "a100")  # newest first
LABEL = {"b200": "B200", "h100": "H100", "a100": "A100"}
THRESHOLD = 3.0


def _pct(new: float, old: Optional[float]) -> Optional[float]:
    if old in (None, 0) or new is None:
        return None
    return round((new - old) / old * 100, 1)


def _value_days_ago(dates: List[str], vals: List[Optional[float]], days: int) -> Optional[float]:
    if not dates:
        return None
    target = date.fromisoformat(dates[-1]) - timedelta(days=days)
    best = None
    for d, v in zip(dates, vals):
        if v is None:
            continue
        if date.fromisoformat(d) <= target:
            best = v
        else:
            break
    return best


def classify(score: Optional[float]) -> str:
    if score is None:
        return "steady"
    if score > THRESHOLD:
        return "rising"
    if score < -THRESHOLD:
        return "dropping"
    return "steady"


def chip_signals(chip: str, hist: Dict[str, Any], curve: Dict[str, Any], today: str) -> Optional[Dict[str, Any]]:
    dates = hist.get("dates") or []
    vals = hist.get(chip) or []
    spot = next((v for v in reversed(vals) if v is not None), None)
    if spot is None:
        return None
    month = today[:7]
    fwd = [p["price"] for p in ((curve.get(chip) or {}).get("points") or []) if p.get("tenor_key", "") > month]
    s30 = _pct(spot, _value_days_ago(dates, vals, 30))
    s90 = _pct(spot, _value_days_ago(dates, vals, 90))
    fv = _pct(sum(fwd) / len(fwd), spot) if fwd else None
    parts = [x for x in (s30, s90, fv) if x is not None]
    score = round(sum(parts) / len(parts), 1) if parts else None
    return {"spot": spot, "spot_30d_pct": s30, "spot_90d_pct": s90, "forward_vs_spot_pct": fv,
            "score": score, "trend": classify(score)}


def _names(chips: List[str]) -> str:
    n = [LABEL[c] for c in chips]
    return n[0] if len(n) == 1 else " and ".join([", ".join(n[:-1]), n[-1]])


def overall_clause(trends: Dict[str, str]) -> str:
    order = [c for c in CHIPS if c in trends]
    vals = {trends[c] for c in order}
    if vals == {"rising"}:
        return "demand running ahead of supply across every generation."
    if vals == {"dropping"}:
        return "supply catching up across every generation."
    if vals == {"steady"}:
        return "prices holding across every generation."
    rising = [c for c in order if trends[c] == "rising"]
    dropping = [c for c in order if trends[c] == "dropping"]
    steady = [c for c in order if trends[c] == "steady"]
    newest = order[0]
    bits = []
    if rising:
        who = "the newest chips" if rising == [newest] else _names(rising)
        bits.append(f"demand strong for {who}")
    if dropping:
        older = all(order.index(c) > order.index(r) for c in dropping for r in rising) if rising else False
        who = "older ones" if older and rising else _names(dropping)
        bits.append(f"supply catching up on {who}")
    if steady and not (rising and dropping):
        bits.append(f"{_names(steady)} holding")
    return ", ".join(bits) + "."


def build_outlook(md: Dict[str, Any], today: Optional[str] = None) -> Optional[Dict[str, Any]]:
    hist = (md.get("compute_forward") or {}).get("spot_history") or {}
    curve = md.get("compute_forward_curve") or {}
    if not hist.get("dates"):
        return None
    today = today or hist.get("end") or date.today().isoformat()
    chips = {}
    for c in CHIPS:
        sig = chip_signals(c, hist, curve, today)
        if sig:
            chips[c] = sig
    if not chips:
        return None
    trends = {c: v["trend"] for c, v in chips.items()}
    head = ", ".join(f"{LABEL[c]} {trends[c]}" for c in CHIPS if c in trends)
    return {
        "line": f"{head}: {overall_clause(trends)}",
        "chips": chips,
        "rule": "mean of spot 30d %, spot 90d % and forward avg vs today %; >+3% rising, <-3% dropping, else steady",
        "as_of": today,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def apply(md: Dict[str, Any]) -> Optional[str]:
    out = build_outlook(md)
    if out:
        md["compute_outlook"] = out
        return out["line"]
    return None
