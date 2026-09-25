"""Mac-side recomputation of every governor and setup-gate measurement.

Sources, read-only, never the network:
  bars      dragonfly/state/live/cache/bars/<TICKER>.json (the #266 cache),
            else a `bars` list on the ticker's row in handoff/<date>/measurements.json
  spread, spread_source, sector, provisional
            the ticker's row in handoff/<date>/measurements.json,
            else the ticker's entry in dragonfly/watchlist.json (Mac-built)

The draft's own measurements are compared against these and never used for a
decision. Anything required that the Mac cannot compute is
`measurement_unavailable`; a draft value outside tolerance is
`measurement_mismatch`. Both are structural blocks.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from dragonfly import market_calendar as mc
from dragonfly import risk_math as rm
from dragonfly import setup_gates as sg
from dragonfly.engine.core import EngineError

SIGNAL_NOTE_AGE_SESSIONS = 5  # an older signal session is recorded as a note, never blocked


def default_bars_dir() -> Path:
    from dragonfly.engine.core import state_dir

    return state_dir() / "cache" / "bars"


def load_prep(repo: Path, session_date: date, handoff_root: str = "handoff"):
    """<handoff root>/<date>/measurements.json -> ({TICKER: row}, relpath or None)."""
    rel = f"{handoff_root}/{session_date.isoformat()}/measurements.json"
    path = Path(repo) / rel
    if not path.exists():
        return {}, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"{rel} unreadable: {exc}") from exc
    names = doc.get("names") if isinstance(doc, dict) else None
    out: Dict[str, dict] = {}
    if isinstance(names, dict):
        for k, v in names.items():
            if isinstance(v, dict):
                out[str(k).upper()] = v
    elif isinstance(names, list):
        for v in names:
            if isinstance(v, dict) and v.get("ticker"):
                out[str(v["ticker"]).upper()] = v
    return out, rel


def load_watchlist(path: Optional[Path]) -> Dict[str, dict]:
    if path is None or not Path(path).exists():
        return {}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names = doc.get("names") if isinstance(doc, dict) else None
    out: Dict[str, dict] = {}
    if isinstance(names, list):
        for v in names:
            if isinstance(v, dict) and v.get("ticker"):
                out[str(v["ticker"]).upper()] = dict(v, _watchlist_provisional=doc.get("provisional", True))
    return out


def _load_bars(ticker: str, bars_dir: Path, prep_row: Optional[Mapping]):
    path = Path(bars_dir) / f"{ticker.upper()}.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict) and payload.get("bars"):
            return sorted(payload["bars"], key=lambda b: b["date"]), f"bars_cache:{path.name}"
    if prep_row and isinstance(prep_row.get("bars"), list) and prep_row["bars"]:
        return sorted(prep_row["bars"], key=lambda b: b["date"]), "prep_bars"
    return None, None


def resolve(draft: Mapping, session_date: date, *, bars_dir: Path, prep: Mapping[str, dict],
            prep_rel: Optional[str], watchlist: Mapping[str, dict], now=None) -> Dict[str, Any]:
    """Recompute, compare, and run the setup gates. Returns a result dict:

    values       Mac numbers used for the governor (price, atr, adv_dollars, spread, sector, ...)
    blocks       structural block codes (measurement_unavailable, measurement_mismatch,
                 setup gate codes, catalyst record codes)
    details      what was computed, sources, mismatches, gate measurements, and
                 non-blocking `notes` (recorded, never a block)
    """
    ticker = draft["ticker"].upper()
    dm = draft["measurements"]
    instrument = draft["instrument"]
    prep_row = prep.get(ticker)
    wl_row = watchlist.get(ticker)
    blocks: List[str] = []
    unavailable: List[str] = []
    mismatches: List[dict] = []
    notes: List[dict] = []
    details: Dict[str, Any] = {"sources": {}, "unavailable": unavailable, "mismatches": mismatches, "notes": notes}
    values: Dict[str, Any] = {"reference_level": dm.get("reference_level"), "base_level": dm.get("base_level")}

    # ---- signal session: the bar must be in the Mac's bars (else unavailable).
    # Its age is recorded, not blocked (no age limit in the plan).
    prev = mc.previous_session(session_date)
    recent = [d.isoformat() for d in mc.previous_sessions(session_date, SIGNAL_NOTE_AGE_SESSIONS)]
    signal_day = dm["signal_session"]
    if signal_day not in recent:
        notes.append({"note": "signal_session_old", "signal_session": signal_day,
                      "detail": f"older than the last {SIGNAL_NOTE_AGE_SESSIONS} sessions (recorded only)"})
    details["previous_session"] = prev.isoformat()

    # ---- bars
    bars, bars_src = _load_bars(ticker, bars_dir, prep_row)
    details["sources"]["bars"] = bars_src
    latest = signal = None
    if bars is None:
        unavailable.append("bars: no cache and no prep bars")
    else:
        try:
            latest = sg.bars_through(bars, prev.isoformat())
        except sg.MeasurementUnavailable as exc:
            unavailable.append(f"bars: cache stale ({exc.detail})")
        try:
            signal = sg.bars_through(bars, signal_day)
        except sg.MeasurementUnavailable as exc:
            unavailable.append(f"bars: {exc.detail}")
    if latest is not None and signal is not None:
        try:
            values.update(sg.core_measurements(latest, signal))
        except sg.MeasurementUnavailable as exc:
            unavailable.append(str(exc))

    # ---- non-bar fields
    def pick(field: str):
        for src_name, row in (("prep", prep_row), ("watchlist", wl_row)):
            if row and row.get(field) is not None:
                return row[field], (prep_rel if src_name == "prep" else "dragonfly/watchlist.json")
        return None, None

    sector, src = pick("sector")
    values["sector"] = sector
    details["sources"]["sector"] = src
    if sector is None:
        unavailable.append("sector")
    if instrument == "stock":
        spread, src = pick("spread")
        values["spread"] = spread
        details["sources"]["spread"] = src
        if spread is None:
            unavailable.append("spread")
    else:
        values["spread"] = None
    spread_source, _ = pick("spread_source")
    values["spread_source"] = spread_source
    # Provenance: only an explicit provisional=False on the prep row counts as
    # non-provisional. Bars are Yahoo (provisional). The draft's claim is ignored.
    values["provisional"] = not (bars_src == "prep_bars" and prep_row.get("provisional") is False)

    # ---- compare with the draft's measurements block (only fields the draft states)
    if not unavailable:
        fields = ["price", "atr", "adv_dollars", "sector"] + (["spread"] if instrument == "stock" else [])
        for field in fields:
            if field not in dm:
                continue
            dv, mv = dm[field], values[field]
            if dv is None and field == "spread":
                continue   # draft did not observe a spread; the Mac's value is used
            if not sg.within(field, dv, mv):
                mismatches.append({"field": field, "draft": dv, "mac": mv, "tolerance": sg.TOLERANCES[field]})
        # evidence.relative_volume is outside the measurements block: recorded, not blocked.
        rv_claim = (draft.get("evidence") or {}).get("relative_volume")
        if rv_claim is not None and not sg.within("relative_volume", rv_claim, values["relative_volume"]):
            notes.append({"note": "evidence_relative_volume_differs", "draft": rv_claim,
                          "mac": values["relative_volume"], "tolerance": sg.TOLERANCES["relative_volume"]})
    if unavailable:
        blocks.append("measurement_unavailable")
    if mismatches:
        blocks.append("measurement_mismatch")

    # ---- setup gates (only on Mac numbers)
    if signal is not None and "atr" in values:
        entry_ref = float(draft["entry"]["price"]) if instrument == "stock" else values["price"]
        stop_underlying = float(draft["stop"]) if instrument == "stock" else float(draft["option"]["underlying_stop"])
        try:
            gate_blocks, gate_detail = sg.evaluate(
                draft["setup"], signal, entry_ref=entry_ref, level=dm.get("reference_level"),
                atr_now=values["atr"], stop_underlying=stop_underlying, base_level=dm.get("base_level"),
                instrument=instrument)
            blocks.extend(gate_blocks)
            details["gates"] = gate_detail
        except sg.MeasurementUnavailable as exc:
            unavailable.append(f"gate: {exc}")
            if "measurement_unavailable" not in blocks:
                blocks.append("measurement_unavailable")
    # ---- catalyst record (dated, sourced; primary within the last 5 sessions)
    cat_blocks, cat_detail = sg.catalyst_checks(draft["catalyst"], session_date, now=now)
    blocks.extend(cat_blocks)
    details["catalyst"] = cat_detail

    # ---- gap_history warning (Mac-measured; can only add a warning)
    if latest is not None:
        if instrument == "stock":
            stop_distance = float(rm.max_buy_fill(draft["entry"]["price"])) - float(draft["stop"])
        else:
            stop_distance = float(values.get("price", 0.0)) - float(draft["option"]["underlying_stop"])
        try:
            flag, gd = sg.gap_history(latest, stop_distance)
            details["gap_history"] = dict(gd, flag=flag)
        except sg.MeasurementUnavailable as exc:
            # cannot measure -> count the warning (fail closed: tightens size only)
            details["gap_history"] = {"flag": True, "unavailable": str(exc)}
    return {"values": values, "blocks": list(dict.fromkeys(blocks)), "details": details}
