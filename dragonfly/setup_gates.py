"""Measurable setup gates from the Dragonfly 7 operating plan (section 6).

Pure functions over daily bars (the #266 bars cache format:
{"date","open","high","low","close","volume"}), using the bars module's own
ATR / ADV / relative-volume math so the Mac recomputes exactly what the scanner
sees. Nothing here fetches data. Each failed gate is a structural block code
the engine records on the card.

Also here: the machine-checkable parts of the catalyst record (sourced, dated,
primary within 5 sessions) and the Mac-measured gap_history warning.

Qualitative conditions (catalyst mechanism, "the continuation trigger is a
price, not a feeling", red-team narrative on an absent catalyst) are not coded
here; they stay with the Architect's card and the Red Team narrative
(listed in docs/dragonfly/ENGINE.md).

Python 3.9 compatible.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from dragonfly import market_calendar as mc
from dragonfly.bars import adv_dollars, atr, relative_volume

# ---------------------------------------------------------------- thresholds
# Operating plan section 6 ("Setups" and "Shared gates"). Changing one is a
# written amendment from Jared, then a plan version bump.
BREAKOUT_MIN_RVOL = 1.8           # A: breakout-session volume >= 1.8x 20-day average
BREAKOUT_MAX_ENTRY_ATR = 1.0      # A: entry within 1.0 ATR of the named breakout level
PULLBACK_MIN_RET20 = 0.08         # B: 20-session return > 8% ...
PULLBACK_SMA_FAST = 20            # B: ... or price above a rising 20-day average
PULLBACK_SMA_SLOW = 50            # B:     that is itself above the 50-day
PULLBACK_RISING_LOOKBACK = 5      # B: "rising" = SMA20 today > SMA20 five sessions earlier
PULLBACK_MIN_DEPTH_ATR = 0.4      # B: pullback 0.4 ... 
PULLBACK_MAX_DEPTH_ATR = 1.5      # B: ... to 1.5 ATR off the recent swing high
PULLBACK_SWING_WINDOW = 10        # B: "recent swing high" = highest high of the last 10 sessions
PULLBACK_IMPULSE_WINDOW = 5       # B: impulse volume = mean of the 5 sessions ending at the swing high
BREAKDOWN_RECLAIM_SESSIONS = 2    # C: support broken and reclaimed within two sessions
BREAKDOWN_MIN_RVOL = 1.5          # C: reversal-session volume >= 1.5x 20-day average
COMPRESSION_WINDOW = 10           # D: 10-day range or ATR ...
COMPRESSION_LOOKBACK = 60         # D: ... in the lowest quartile of the trailing 60 sessions
COMPRESSION_QUARTILE = 0.25       # mid-rank percentile <= 0.25 (ties count half)
EXPANSION_MIN_RANGE_MULT = 1.5    # D: expansion range > 1.5x prior 10-day average range
EXPANSION_MIN_RVOL = 1.5          # D: expansion volume >= 1.5x

# Red-team warning the Mac can measure (operating plan section 9): gap_history is
# true when a gap in the last 60 sessions exceeded 1.5x the planned stop distance.
# gap = |open - previous close|. The engine ORs this into the red team's flags
# (it can add the warning, never remove it).
GAP_HISTORY_LOOKBACK = 60
GAP_HISTORY_MULT = 1.5

# ---------------------------------------------------------------- tolerances
# Draft vs Mac recomputation. Beyond these the engine blocks
# (measurement_mismatch) and never trusts the draft's number.
TOLERANCES = {
    "price": {"rel": 0.005},             # previous-session close, 0.5%
    "atr": {"rel": 0.05},                # Wilder ATR(14), 5%
    "adv_dollars": {"rel": 0.05},        # 20-day average dollar volume, 5%
    "relative_volume": {"rel": 0.05, "abs": 0.05},  # signal-session rvol, 5% (min 0.05x)
    "spread": {"abs": 0.01},             # stock spread, $0.01
    "sector": {"exact": True},           # case-insensitive
}


class MeasurementUnavailable(Exception):
    def __init__(self, field: str, detail: str = ""):
        self.field = field
        self.detail = detail
        super().__init__(f"{field}: {detail}" if detail else field)


def within(field: str, draft_value, mac_value) -> bool:
    tol = TOLERANCES[field]
    if tol.get("exact"):
        return str(draft_value).strip().lower() == str(mac_value).strip().lower()
    if draft_value is None or mac_value is None:
        return draft_value is None and mac_value is None
    diff = abs(float(draft_value) - float(mac_value))
    allowed = max(tol.get("abs", 0.0), tol.get("rel", 0.0) * abs(float(mac_value)))
    return diff <= allowed + 1e-12


# ---------------------------------------------------------------- helpers
def bars_through(bars: Sequence[Mapping], day: str) -> List[Mapping]:
    """Bars up to and including `day` (ISO date). The bar for `day` must exist."""
    idx = None
    for i, b in enumerate(bars):
        if b["date"] == day:
            idx = i
            break
    if idx is None:
        raise MeasurementUnavailable("bars", f"no bar for {day}")
    return list(bars[: idx + 1])


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _need(bars: Sequence[Mapping], n: int, what: str) -> None:
    if len(bars) < n:
        raise MeasurementUnavailable("bars", f"{what} needs {n} bars, have {len(bars)}")


def _pct_below(values: Sequence[float], current: float) -> float:
    """Mid-rank percentile of `current` in `values` (ties count half), 0..1."""
    less = sum(1 for v in values if v < current - 1e-12)
    equal = sum(1 for v in values if abs(v - current) <= 1e-12)
    return (less + 0.5 * equal) / len(values)


def core_measurements(latest: Sequence[Mapping], signal: Sequence[Mapping]) -> Dict[str, float]:
    """Governor inputs recomputed by the Mac. `latest` ends at the previous session."""
    a = atr(latest)
    adv = adv_dollars(latest)
    rv = relative_volume(signal)
    if a is None:
        raise MeasurementUnavailable("atr", f"needs 15 bars, have {len(latest)}")
    if adv is None:
        raise MeasurementUnavailable("adv_dollars", f"needs 20 bars, have {len(latest)}")
    if rv is None:
        raise MeasurementUnavailable("relative_volume", f"needs 21 bars through the signal session, have {len(signal)}")
    return {
        "price": float(latest[-1]["close"]),
        "atr": float(a),
        "adv_dollars": float(adv),
        "relative_volume": float(rv),
        "bar_date": latest[-1]["date"],
        "signal_bar_date": signal[-1]["date"],
    }


# ---------------------------------------------------------------- gates per setup
def gate_catalyst_breakout(signal, *, entry_ref, level, atr_now, **_) -> Tuple[List[str], dict]:
    rv = relative_volume(signal)
    if rv is None:
        raise MeasurementUnavailable("relative_volume", "breakout session")
    close = signal[-1]["close"]
    entry_atr = abs(entry_ref - level) / atr_now
    blocks = []
    if rv < BREAKOUT_MIN_RVOL:
        blocks.append("breakout_rvol_low")
    if close <= level:
        blocks.append("breakout_not_confirmed")
    if entry_atr > BREAKOUT_MAX_ENTRY_ATR:
        blocks.append("breakout_entry_far")
    return blocks, {"rvol": round(rv, 4), "signal_close": close, "level": level, "entry_distance_atr": round(entry_atr, 4)}


def gate_momentum_pullback(signal, *, base_level, **_) -> Tuple[List[str], dict]:
    _need(signal, PULLBACK_SMA_SLOW + PULLBACK_RISING_LOOKBACK, "momentum_pullback trend")
    closes = [b["close"] for b in signal]
    ret20 = closes[-1] / closes[-21] - 1
    sma20 = _mean(closes[-PULLBACK_SMA_FAST:])
    sma20_prior = _mean(closes[-PULLBACK_SMA_FAST - PULLBACK_RISING_LOOKBACK: -PULLBACK_RISING_LOOKBACK])
    sma50 = _mean(closes[-PULLBACK_SMA_SLOW:])
    trend_ok = closes[-1] > sma20 and sma20 > sma20_prior and sma20 > sma50
    atr_sig = atr(signal)
    if atr_sig is None:
        raise MeasurementUnavailable("atr", "at the pullback session")
    window = signal[-PULLBACK_SWING_WINDOW:]
    swing_rel = max(range(len(window)), key=lambda i: (window[i]["high"], i))
    swing_idx = len(signal) - len(window) + swing_rel
    swing_high = signal[swing_idx]["high"]
    blocks = []
    if not (ret20 > PULLBACK_MIN_RET20 or trend_ok):
        blocks.append("pullback_no_momentum")
    detail = {"ret20": round(ret20, 4), "sma20": round(sma20, 4), "sma20_5ago": round(sma20_prior, 4),
              "sma50": round(sma50, 4), "trend_ok": trend_ok, "swing_high": swing_high,
              "swing_date": signal[swing_idx]["date"], "base_level": base_level}
    if swing_idx == len(signal) - 1:
        blocks.append("pullback_not_formed")
        return blocks, detail
    depth = (swing_high - closes[-1]) / atr_sig
    detail["depth_atr"] = round(depth, 4)
    if not (PULLBACK_MIN_DEPTH_ATR <= depth <= PULLBACK_MAX_DEPTH_ATR):
        blocks.append("pullback_depth_out_of_range")
    if base_level is None:
        raise MeasurementUnavailable("base_level", "momentum_pullback needs measurements.base_level")
    if any(b["close"] < base_level for b in signal[swing_idx + 1:]):
        blocks.append("pullback_broke_base")
    pull_vol = _mean([b["volume"] for b in signal[swing_idx + 1:]])
    imp = signal[max(0, swing_idx - PULLBACK_IMPULSE_WINDOW + 1): swing_idx + 1]
    imp_vol = _mean([b["volume"] for b in imp])
    detail.update({"pullback_volume": round(pull_vol, 1), "impulse_volume": round(imp_vol, 1)})
    if pull_vol >= imp_vol:
        blocks.append("pullback_volume_not_lower")
    return blocks, detail


def gate_failed_breakdown(signal, *, level, stop_underlying, **_) -> Tuple[List[str], dict]:
    n = BREAKDOWN_RECLAIM_SESSIONS + 1
    _need(signal, 21 + n, "failed_breakdown")
    window = signal[-n:]
    before = signal[-n - 1]
    rv = relative_volume(signal)
    broke = before["close"] >= level and any(b["low"] < level for b in window)
    reversal = signal[-1]
    blocks = []
    if not broke:
        blocks.append("breakdown_not_found")
    if reversal["close"] <= level:
        blocks.append("reclaim_not_confirmed")
    if rv is None or rv < BREAKDOWN_MIN_RVOL:
        blocks.append("reversal_rvol_low")
    if stop_underlying >= reversal["low"]:
        blocks.append("stop_not_below_reversal_bar")
    return blocks, {"support": level, "close_before_break": before["close"],
                    "window_low": min(b["low"] for b in window), "reversal_close": reversal["close"],
                    "reversal_low": reversal["low"], "rvol": round(rv, 4) if rv is not None else None}


def _range10(bars: Sequence[Mapping], end_idx: int) -> float:
    w = bars[end_idx - COMPRESSION_WINDOW + 1: end_idx + 1]
    return max(b["high"] for b in w) - min(b["low"] for b in w)


def gate_compression_expansion(signal, *, stop_underlying, **_) -> Tuple[List[str], dict]:
    pre = signal[:-1]
    _need(pre, COMPRESSION_LOOKBACK + COMPRESSION_WINDOW + 14, "compression_expansion")
    last = len(pre) - 1
    idxs = list(range(last - COMPRESSION_LOOKBACK + 1, last + 1))
    ranges = [_range10(pre, i) for i in idxs]
    atrs = [atr(pre[: i + 1]) for i in idxs]
    range_pct = _pct_below(ranges, ranges[-1])
    atr_pct = _pct_below(atrs, atrs[-1])
    compressed = range_pct <= COMPRESSION_QUARTILE or atr_pct <= COMPRESSION_QUARTILE
    exp = signal[-1]
    prior = pre[-COMPRESSION_WINDOW:]
    avg_range = _mean([b["high"] - b["low"] for b in prior])
    exp_range = exp["high"] - exp["low"]
    rv = relative_volume(signal)
    comp_low = min(b["low"] for b in prior)
    comp_high = max(b["high"] for b in prior)
    blocks = []
    if not compressed:
        blocks.append("no_compression")
    if exp_range <= EXPANSION_MIN_RANGE_MULT * avg_range:
        blocks.append("expansion_range_small")
    if rv is None or rv < EXPANSION_MIN_RVOL:
        blocks.append("expansion_rvol_low")
    if exp["close"] <= pre[-1]["close"]:
        blocks.append("expansion_not_up")
    if stop_underlying >= comp_low:
        blocks.append("stop_not_outside_compression")
    return blocks, {"range10": round(ranges[-1], 4), "range10_pct_rank": round(range_pct, 4),
                    "atr_pct_rank": round(atr_pct, 4), "expansion_range": round(exp_range, 4),
                    "prior_avg_range": round(avg_range, 4), "rvol": round(rv, 4) if rv is not None else None,
                    "compression_low": comp_low, "compression_high": comp_high}


def gap_history(latest: Sequence[Mapping], stop_distance: float) -> Tuple[bool, dict]:
    """Mac-measured gap_history flag on bars through the previous session."""
    _need(latest, GAP_HISTORY_LOOKBACK + 1, "gap_history")
    window = latest[-(GAP_HISTORY_LOOKBACK + 1):]
    try:
        gaps = [abs(float(window[i]["open"]) - float(window[i - 1]["close"])) for i in range(1, len(window))]
    except (KeyError, TypeError, ValueError):
        raise MeasurementUnavailable("gap_history", "bars lack open/close")
    biggest = max(gaps)
    threshold = GAP_HISTORY_MULT * float(stop_distance)
    return biggest > threshold, {"max_gap": round(biggest, 4), "stop_distance": round(float(stop_distance), 4),
                                 "threshold": round(threshold, 4), "lookback": GAP_HISTORY_LOOKBACK}


GATES = {
    "catalyst_breakout": gate_catalyst_breakout,
    "momentum_pullback": gate_momentum_pullback,
    "failed_breakdown": gate_failed_breakdown,
    "compression_expansion": gate_compression_expansion,
}

ALL_GATE_BLOCKS = (
    "breakout_rvol_low", "breakout_not_confirmed", "breakout_entry_far",
    "pullback_no_momentum", "pullback_not_formed", "pullback_depth_out_of_range",
    "pullback_broke_base", "pullback_volume_not_lower",
    "breakdown_not_found", "reclaim_not_confirmed", "reversal_rvol_low", "stop_not_below_reversal_bar",
    "no_compression", "expansion_range_small", "expansion_rvol_low", "expansion_not_up",
    "stop_not_outside_compression",
)


def evaluate(setup: str, signal: Sequence[Mapping], *, entry_ref: float, level: float, atr_now: float,
             stop_underlying: float, base_level: Optional[float] = None) -> Tuple[List[str], dict]:
    """Blocks for one setup. Raises MeasurementUnavailable when history is too short."""
    fn = GATES.get(setup)
    if fn is None:
        return ["unknown_setup"], {}
    return fn(list(signal), entry_ref=float(entry_ref), level=float(level), atr_now=float(atr_now),
              stop_underlying=float(stop_underlying), base_level=None if base_level is None else float(base_level))


# ---- catalyst record (operating plan section 6, "Catalyst quality")
# primary   = a dated, sourced event in the last five sessions
# secondary = a sector or peer event (sourced; no recency rule in the plan)
# A catalyst record needs a source URL or filing accession and a timestamp.
CATALYST_PRIMARY_MAX_SESSIONS = 5
CATALYST_BLOCKS = ("catalyst_unsourced", "catalyst_stale", "catalyst_date_invalid")


def catalyst_checks(catalyst: Mapping, session_date: date) -> Tuple[List[str], dict]:
    """Machine-checkable parts of the catalyst record. Mechanism and quality of
    the source stay with the Red Team narrative. `absent` is never checked here
    (structural_blocks decides whether the setup allows it)."""
    quality = catalyst.get("quality")
    detail: Dict[str, object] = {"quality": quality}
    if quality not in ("primary", "secondary"):
        return [], detail
    blocks: List[str] = []
    url = str(catalyst.get("source_url") or "").strip()
    if not url or catalyst.get("source_type") in (None, "none"):
        blocks.append("catalyst_unsourced")
    observed = catalyst.get("observed_at")
    if observed is None:
        blocks.append("catalyst_unsourced")   # undated
    else:
        try:
            when = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
            if when.tzinfo is None:
                raise ValueError("naive")
            from zoneinfo import ZoneInfo

            day = when.astimezone(ZoneInfo(mc.CT)).date()
        except ValueError:
            return list(dict.fromkeys(blocks + ["catalyst_date_invalid"])), detail
        detail["observed_date_ct"] = day.isoformat()
        if day > session_date:
            blocks.append("catalyst_date_invalid")
        elif quality == "primary":
            window = mc.previous_sessions(session_date, CATALYST_PRIMARY_MAX_SESSIONS)
            detail["primary_window_start"] = window[0].isoformat()
            if day < window[0]:
                blocks.append("catalyst_stale")
    return list(dict.fromkeys(blocks)), detail
