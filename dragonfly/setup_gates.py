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

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from dragonfly import market_calendar as mc
from dragonfly.bars import adv_dollars, atr, relative_volume

# ---------------------------------------------------------------- thresholds
# Operating plan section 6 ("Setups"). Values stated in the plan are marked
# PLAN. Values the plan leaves open are marked ASSUMPTION and use the most
# permissive reasonable reading (Jared, 2026-09-25: no blocks beyond the plan
# text in Phase 1). Changing a PLAN value is a written amendment from Jared.
BREAKOUT_MIN_RVOL = 1.8           # PLAN A: breakout-session volume >= 1.8x the 20-day average
BREAKOUT_MAX_ENTRY_ATR = 1.0      # PLAN A: entry within 1.0 ATR of the named breakout level
PULLBACK_MIN_RET20 = 0.08         # PLAN B: 20-session return > 8% ...
PULLBACK_SMA_FAST = 20            # PLAN B: ... or price above a rising 20-day average
PULLBACK_SMA_SLOW = 50            # PLAN B:     that is itself above the 50-day
PULLBACK_RISING_LOOKBACK = 1      # ASSUMPTION B: "rising" = SMA20 above the prior session's SMA20
PULLBACK_MIN_DEPTH_ATR = 0.4      # PLAN B: pullback 0.4 ...
PULLBACK_MAX_DEPTH_ATR = 1.5      # PLAN B: ... to 1.5 ATR off the recent swing high
PULLBACK_SWING_LOOKBACK = 20      # ASSUMPTION B: "recent swing high" = any local high in the 20 sessions
                                  #   before the pullback bar; the gate passes if ANY candidate passes
PULLBACK_IMPULSE_WINDOW = 5       # ASSUMPTION B: impulse volume = mean of the 5 sessions ending at the swing high
BREAKDOWN_RECLAIM_SESSIONS = 2    # PLAN C: support broken and reclaimed within two sessions
BREAKDOWN_MIN_RVOL = 1.5          # PLAN C: reversal-session volume >= 1.5x the 20-day average
COMPRESSION_WINDOW = 10           # PLAN D: 10-day range or ATR ...
COMPRESSION_LOOKBACK = 60         # PLAN D: ... in the lowest quartile of the trailing 60 sessions
COMPRESSION_QUARTILE = 0.25       # PLAN D: lowest quartile. ASSUMPTION: share of the 60 values strictly
                                  #   below today's <= 25% (ties count in favour of compression)
EXPANSION_MIN_RANGE_MULT = 1.5    # PLAN D: expansion range > 1.5x the prior 10-day average range
EXPANSION_MIN_RVOL = 1.5          # PLAN D: expansion volume >= 1.5x (ASSUMPTION: the 20-day average)

# Red-team warning the Mac can measure (plan section 9, "Red-team warning
# flags"; confirmed by Ditka 2026-09-25): gap_history is true when a gap in the
# last 60 sessions exceeded 1.5x the planned stop distance. gap = |open -
# previous close|. The engine ORs this into the red team's flags (it can add
# the warning, never remove it; counted when it cannot be measured).
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


def _share_below(values: Sequence[float], current: float) -> float:
    """Share of `values` strictly below `current` (ties do not count against it), 0..1."""
    return sum(1 for v in values if v < current - 1e-12) / len(values)


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
    """A. rvol >= 1.8x on the breakout session; price confirmation; entry within 1.0 ATR of the level.

    ASSUMPTION (price confirmation): the breakout session traded above the
    named level (high > level). A close above it is not required.
    """
    rv = relative_volume(signal)
    if rv is None:
        raise MeasurementUnavailable("relative_volume", "breakout session")
    bar = signal[-1]
    entry_atr = abs(entry_ref - level) / atr_now
    blocks = []
    if rv < BREAKOUT_MIN_RVOL:
        blocks.append("breakout_rvol_low")
    if bar["high"] <= level:
        blocks.append("breakout_not_confirmed")
    if entry_atr > BREAKOUT_MAX_ENTRY_ATR:
        blocks.append("breakout_entry_far")
    return blocks, {"rvol": round(rv, 4), "signal_high": bar["high"], "signal_close": bar["close"], "level": level,
                    "entry_distance_atr": round(entry_atr, 4)}


def _momentum_at(closes: Sequence[float], i: int) -> Tuple[bool, dict]:
    """B momentum at bar i: 20-session return > 8%, or close > rising SMA20 > SMA50."""
    ret20 = closes[i] / closes[i - 20] - 1
    sma20 = _mean(closes[i - PULLBACK_SMA_FAST + 1: i + 1])
    j = i - PULLBACK_RISING_LOOKBACK
    sma20_prior = _mean(closes[j - PULLBACK_SMA_FAST + 1: j + 1])
    sma50 = _mean(closes[i - PULLBACK_SMA_SLOW + 1: i + 1])
    trend_ok = closes[i] > sma20 and sma20 > sma20_prior and sma20 > sma50
    ok = ret20 > PULLBACK_MIN_RET20 or trend_ok
    return ok, {"ret20": round(ret20, 4), "sma20": round(sma20, 4), "sma20_prior": round(sma20_prior, 4),
                "sma50": round(sma50, 4), "trend_ok": trend_ok}


def gate_momentum_pullback(signal, *, base_level, **_) -> Tuple[List[str], dict]:
    """B. Move underway; pullback 0.4-1.5 ATR off a recent swing high; no close
    back through the prior breakout base; pullback volume below impulse volume.

    ASSUMPTIONS: momentum counts if it holds at the pullback bar OR at the swing
    high; any local high (high >= both neighbours) in the 20 sessions before the
    pullback bar is a candidate swing high and the gate passes if ANY candidate
    passes; depth passes if either the close or the pullback low is 0.4-1.5 ATR
    below the swing high.
    """
    need = PULLBACK_SMA_SLOW + PULLBACK_RISING_LOOKBACK + PULLBACK_SWING_LOOKBACK + 1
    _need(signal, need, "momentum_pullback trend")
    if base_level is None:
        raise MeasurementUnavailable("base_level", "momentum_pullback needs measurements.base_level")
    closes = [b["close"] for b in signal]
    last = len(signal) - 1
    atr_sig = atr(signal)
    if atr_sig is None:
        raise MeasurementUnavailable("atr", "at the pullback session")
    mom_sig, mom_sig_d = _momentum_at(closes, last)
    candidates = []
    for i in range(last - 1, last - PULLBACK_SWING_LOOKBACK - 1, -1):   # most recent first
        h = signal[i]["high"]
        if h >= signal[i - 1]["high"] and h >= signal[i + 1]["high"]:
            candidates.append(i)
    detail: Dict[str, object] = {"momentum_at_signal": mom_sig_d, "base_level": base_level,
                                 "candidates": len(candidates)}
    if not candidates:
        return (["pullback_not_formed"] + ([] if mom_sig else ["pullback_no_momentum"])), detail
    best = None
    for i in candidates:
        swing_high = signal[i]["high"]
        after = signal[i + 1:]
        mom_swing, _ = _momentum_at(closes, i)
        close_depth = (swing_high - closes[-1]) / atr_sig
        low_depth = (swing_high - min(b["low"] for b in after)) / atr_sig
        depth_ok = any(PULLBACK_MIN_DEPTH_ATR <= d <= PULLBACK_MAX_DEPTH_ATR for d in (close_depth, low_depth))
        pull_vol = _mean([b["volume"] for b in after])
        imp = signal[max(0, i - PULLBACK_IMPULSE_WINDOW + 1): i + 1]
        imp_vol = _mean([b["volume"] for b in imp])
        blocks = []
        if not (mom_sig or mom_swing):
            blocks.append("pullback_no_momentum")
        if not depth_ok:
            blocks.append("pullback_depth_out_of_range")
        if any(b["close"] < base_level for b in after):
            blocks.append("pullback_broke_base")
        if pull_vol >= imp_vol:
            blocks.append("pullback_volume_not_lower")
        cand = {"swing_date": signal[i]["date"], "swing_high": swing_high, "close_depth_atr": round(close_depth, 4),
                "low_depth_atr": round(low_depth, 4), "momentum_at_swing": mom_swing,
                "pullback_volume": round(pull_vol, 1), "impulse_volume": round(imp_vol, 1), "blocks": blocks}
        if best is None or len(blocks) < len(best["blocks"]):
            best = cand
        if not blocks:
            break
    detail["swing"] = best
    return list(best["blocks"]), detail


def gate_failed_breakdown(signal, *, level, stop_underlying, **_) -> Tuple[List[str], dict]:
    """C. Broke the named support and reclaimed it within two sessions; reversal
    rvol >= 1.5x; stop below the reversal bar.

    ASSUMPTIONS: "broke" = a low below support on the reversal session or one
    of the 2 sessions before it, with the session before the first such low
    closing at or above support; "reclaimed" = reversal close at or above support.
    """
    n = BREAKDOWN_RECLAIM_SESSIONS + 1
    _need(signal, 21 + n, "failed_breakdown")
    start = len(signal) - n
    first_break = next((i for i in range(start, len(signal)) if signal[i]["low"] < level), None)
    broke = first_break is not None and signal[first_break - 1]["close"] >= level
    rv = relative_volume(signal)
    reversal = signal[-1]
    blocks = []
    if not broke:
        blocks.append("breakdown_not_found")
    if reversal["close"] < level:
        blocks.append("reclaim_not_confirmed")
    if rv is None or rv < BREAKDOWN_MIN_RVOL:
        blocks.append("reversal_rvol_low")
    if stop_underlying >= reversal["low"]:
        blocks.append("stop_not_below_reversal_bar")
    return blocks, {"support": level,
                    "break_date": signal[first_break]["date"] if first_break is not None else None,
                    "window_low": min(b["low"] for b in signal[start:]), "reversal_close": reversal["close"],
                    "reversal_low": reversal["low"], "rvol": round(rv, 4) if rv is not None else None}


def _range10(bars: Sequence[Mapping], end_idx: int) -> float:
    w = bars[end_idx - COMPRESSION_WINDOW + 1: end_idx + 1]
    return max(b["high"] for b in w) - min(b["low"] for b in w)


def gate_compression_expansion(signal, *, stop_underlying, instrument="stock", **_) -> Tuple[List[str], dict]:
    """D. 10-day range or ATR in the lowest quartile of the trailing 60 sessions;
    expansion range > 1.5x the prior 10-day average range; volume >= 1.5x;
    direction follows the expansion; stop outside the compression range.

    ASSUMPTIONS: compression measured on the session before the expansion;
    expansion range = the expansion session's true range (counts a gap); prior
    average = mean high-low of the 10 sessions before; direction: stock/call
    need an up expansion (close above the prior close or above the open), put
    a down one, debit_spread is not checked (its direction is not in the
    draft); compression range = the 10 sessions before the expansion.
    """
    pre = signal[:-1]
    _need(pre, COMPRESSION_LOOKBACK + COMPRESSION_WINDOW + 14, "compression_expansion")
    last = len(pre) - 1
    idxs = list(range(last - COMPRESSION_LOOKBACK + 1, last + 1))
    ranges = [_range10(pre, i) for i in idxs]
    atrs = [atr(pre[: i + 1]) for i in idxs]
    range_pct = _share_below(ranges, ranges[-1])
    atr_pct = _share_below(atrs, atrs[-1])
    compressed = range_pct <= COMPRESSION_QUARTILE or atr_pct <= COMPRESSION_QUARTILE
    exp = signal[-1]
    prior = pre[-COMPRESSION_WINDOW:]
    avg_range = _mean([b["high"] - b["low"] for b in prior])
    pc = pre[-1]["close"]
    exp_range = max(exp["high"] - exp["low"], abs(exp["high"] - pc), abs(exp["low"] - pc))
    rv = relative_volume(signal)
    comp_low = min(b["low"] for b in prior)
    comp_high = max(b["high"] for b in prior)
    up = exp["close"] > pc or exp["close"] > exp["open"]
    down = exp["close"] < pc or exp["close"] < exp["open"]
    blocks = []
    if not compressed:
        blocks.append("no_compression")
    if exp_range <= EXPANSION_MIN_RANGE_MULT * avg_range:
        blocks.append("expansion_range_small")
    if rv is None or rv < EXPANSION_MIN_RVOL:
        blocks.append("expansion_rvol_low")
    if (instrument == "put" and not down) or (instrument in ("stock", "call") and not up):
        blocks.append("expansion_direction_mismatch")
    if instrument == "put":
        if stop_underlying <= comp_high:
            blocks.append("stop_not_outside_compression")
    elif stop_underlying >= comp_low:
        blocks.append("stop_not_outside_compression")
    return blocks, {"range10": round(ranges[-1], 4), "range10_share_below": round(range_pct, 4),
                    "atr_share_below": round(atr_pct, 4), "expansion_true_range": round(exp_range, 4),
                    "prior_avg_range": round(avg_range, 4), "rvol": round(rv, 4) if rv is not None else None,
                    "compression_low": comp_low, "compression_high": comp_high, "direction_up": up}


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
    "no_compression", "expansion_range_small", "expansion_rvol_low", "expansion_direction_mismatch",
    "stop_not_outside_compression",
)


def evaluate(setup: str, signal: Sequence[Mapping], *, entry_ref: float, level: Optional[float], atr_now: float,
             stop_underlying: float, base_level: Optional[float] = None,
             instrument: str = "stock") -> Tuple[List[str], dict]:
    """Blocks for one setup. Raises MeasurementUnavailable when history is too
    short or a level the setup needs is missing (A/C need reference_level)."""
    fn = GATES.get(setup)
    if fn is None:
        return ["unknown_setup"], {}
    if setup in LEVEL_SETUPS and level is None:
        raise MeasurementUnavailable("reference_level", f"{setup} needs measurements.reference_level")
    return fn(list(signal), entry_ref=float(entry_ref), level=None if level is None else float(level),
              atr_now=float(atr_now), stop_underlying=float(stop_underlying),
              base_level=None if base_level is None else float(base_level), instrument=instrument)


LEVEL_SETUPS = ("catalyst_breakout", "failed_breakdown")   # setups whose gates use the named level


# ---- catalyst record (plan section 6, "Catalyst quality"; confirmed by Ditka 2026-09-25)
# "A catalyst record needs a source URL or filing accession, a timestamp, and
#  one sentence on the mechanism." primary = "a dated, sourced event in the
#  last five sessions". Future-dated records are blocked.
# ASSUMPTIONS: "last five sessions" = at or after the close of the 6th NYSE
# session before the session date (an after-hours event belongs to the next
# session) through now; "future" = more than 5 minutes after the engine's clock
# (agent clock skew). The mechanism sentence is the Red Team's to judge.
CATALYST_PRIMARY_MAX_SESSIONS = 5
CATALYST_FUTURE_SKEW_MINUTES = 5
ACCESSION_RE = re.compile(r"^\d{10}-?\d{2}-?\d{6}$")   # SEC accession, e.g. 0001193125-26-123456
CATALYST_BLOCKS = ("catalyst_unsourced", "catalyst_undated", "catalyst_stale", "catalyst_date_invalid")


def catalyst_source(catalyst: Mapping) -> Optional[str]:
    """The record's source: a URL, or an SEC filing accession (in
    `filing_accession`, or given as `source_url`). None if neither."""
    for key in ("source_url", "filing_accession"):
        v = str(catalyst.get(key) or "").strip()
        if v:
            return v
    return None


def catalyst_checks(catalyst: Mapping, session_date: date, now: Optional[datetime] = None) -> Tuple[List[str], dict]:
    """Machine-checkable parts of the catalyst record. `absent` is not checked
    here (structural_blocks decides whether the setup allows it)."""
    from zoneinfo import ZoneInfo

    quality = catalyst.get("quality")
    detail: Dict[str, object] = {"quality": quality}
    if quality not in ("primary", "secondary"):
        return [], detail
    blocks: List[str] = []
    src = catalyst_source(catalyst)
    detail["source"] = src
    detail["source_is_accession"] = bool(src and ACCESSION_RE.match(src))
    if src is None:
        blocks.append("catalyst_unsourced")
    observed = catalyst.get("observed_at")
    if observed is None:
        blocks.append("catalyst_undated")
        return blocks, detail
    try:
        when = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("naive")
    except ValueError:
        return blocks + ["catalyst_date_invalid"], detail
    ct = ZoneInfo(mc.CT)
    when = when.astimezone(ct)
    detail["observed_at_ct"] = when.isoformat()
    limit = (now.astimezone(ct) if now is not None
             else datetime.combine(session_date, datetime.max.time(), tzinfo=ct))
    if when > limit + timedelta(minutes=CATALYST_FUTURE_SKEW_MINUTES):
        blocks.append("catalyst_date_invalid")
    elif quality == "primary":
        anchor = mc.previous_sessions(session_date, CATALYST_PRIMARY_MAX_SESSIONS + 1)[0]
        window_start = mc.session_close(anchor)
        detail["primary_window_start"] = window_start.isoformat()
        if when < window_start:
            blocks.append("catalyst_stale")
    return blocks, detail

