"""Prep job: 15:30 CT on the trading day before the target session.

Steps (each failure is loud; nothing is committed after a failure):
  1. Target session = --date, else the next NYSE session after today
     (dragonfly/market_calendar.py). The previous session (whose close the
     measurements use) must already have closed.
  2. Load guards (dragonfly/guards.py, real clock): refuse inside a pipeline
     daemon window; bounded wait on the pipeline lock. 15:30 is outside every
     window. One prep at a time (job lock).
  3. Pull dragonfly-private. Refuse if <handoff root>/<date>/READY exists.
  4. Watchlist through the existing gates (build_watchlist.build). Universe
     membership is re-fetched only when it is 7+ days old (ndx_universe). The
     job works on state copies (state/live/universe.json, state/live/watchlist.json)
     so the run clone stays clean for its ff-only pull.
  5. Bars cache refreshed for every admitted name so it holds the previous
     session's completed bar (fetched after that close).
  6. Per-name measurements in the engine's measurements.json contract
     (dragonfly/engine/measure.py load_prep): sector, spread, spread_source,
     provisional, bars; plus price/atr/adv_dollars/relative_volume/bar_date as
     computed by setup_gates.core_measurements (informational: the engine
     recomputes them from the bars).
  7. Write <handoff root>/<date>/prep.json + measurements.json, commit, push.
  8. Mark the book (real runs only): a FLAT paper book is re-stamped as of now
     (equity = cash, nothing to price). A book with open positions is NOT
     marked (no fill ledger yet); the pre-open job then fails book_stale.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from dragonfly import market_calendar as mc
from dragonfly import setup_gates as sg
from dragonfly.engine import core
from dragonfly.engine.gitops import PrivateRepo
from dragonfly.jobs.common import JobError, job_lock, read_json, to_float, write_json

log = logging.getLogger("dragonfly.jobs")

PREP_SCHEMA = "dragonfly.prep/1"
MEASUREMENTS_SCHEMA = "dragonfly.prep_measurements/1"
BARS_KEEP = 130            # >= the longest gate lookback (compression: 60 + 10 + 14) with room
CLOSE_SETTLE = timedelta(minutes=5)  # a cache fetched before close + 5 min may hold a partial bar
PREP_NAME = "prep.json"
MEASUREMENTS_NAME = "measurements.json"
READY_NAME = "READY"


def target_session(now: datetime, date_arg: Optional[str]) -> date:
    """--date, else the next NYSE session after `now`'s date. Must be a session."""
    if date_arg:
        d = date.fromisoformat(date_arg)
    else:
        try:
            d = mc.next_session(now.date())
        except mc.CalendarNotCovered as exc:
            raise JobError(str(exc)) from exc
    try:
        ok = mc.is_session(d)
    except mc.CalendarNotCovered as exc:
        raise JobError(str(exc)) from exc
    if not ok:
        raise JobError(f"{d} is not an NYSE session ({mc.holiday_name(d) or 'weekend'}); no prep")
    return d


def _default_build(out: Path, universe_path: Path) -> dict:
    from dragonfly import build_watchlist as bw

    return bw.build(bw.DEFAULT_CAP, out, universe_path, 8, 6, spread_mode="modeled", refresh_universe=False)


def _default_refresh(ticker: str) -> dict:
    from dragonfly import bars as bars_mod

    return bars_mod.refresh(ticker, max_age_minutes=None)


def _default_load(ticker: str) -> Optional[dict]:
    from dragonfly import bars as bars_mod

    return bars_mod.load_cache(ticker)


def _fetched_at(payload: Mapping) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(payload.get("fetched_at")))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.astimezone()


def ensure_bars(ticker: str, prev: date, prev_close: datetime, load_fn: Callable, refresh_fn: Callable
                ) -> Tuple[Optional[List[dict]], str]:
    """Bars holding `prev`'s completed bar. Returns (bars, mode) or (None, reason)."""
    payload = load_fn(ticker)
    mode = "cache"
    need = True
    if payload and payload.get("bars"):
        dates = {b["date"] for b in payload["bars"]}
        fetched = _fetched_at(payload)
        need = prev.isoformat() not in dates or fetched is None or fetched < prev_close + CLOSE_SETTLE
    if need:
        try:
            payload = refresh_fn(ticker)
            mode = "refreshed"
        except Exception as exc:  # BarsUnavailable, GuardBlocked (re-raised below)
            from dragonfly import guards

            if isinstance(exc, guards.GuardBlocked):
                raise
            return None, f"bars_unavailable: {exc}"
    if not payload or not payload.get("bars"):
        return None, "bars_unavailable: empty cache"
    return sorted(payload["bars"], key=lambda b: b["date"]), mode


def measurement_row(name: Mapping, bars: Optional[List[dict]], prev: date, bars_note: str) -> dict:
    """One row of measurements.json (engine contract + informational fields)."""
    row = {
        "ticker": name["ticker"],
        "sector": name.get("sector"),
        "sector_rank": name.get("sector_rank"),
        "market_cap": name.get("market_cap"),
        "origin": list(name.get("origin") or []),
        "spread": to_float(name.get("spread")),
        "spread_source": name.get("spread_source"),
        "mid": to_float(name.get("mid")),
        "mid_source": name.get("mid_source"),
        "bid": to_float(name.get("bid")),
        "ask": to_float(name.get("ask")),
        "last_trade": to_float(name.get("last_trade")),
        "quote_time": name.get("quote_time"),
        "source": "yahoo",
        "provisional": True,
        "bars_status": bars_note,
    }
    if bars is None:
        row["unavailable"] = [bars_note]
        return row
    try:
        latest = sg.bars_through(bars, prev.isoformat())
    except sg.MeasurementUnavailable as exc:
        row["unavailable"] = [f"bars: {exc.detail}"]
        row["bars"] = bars[-BARS_KEEP:]
        return row
    try:
        row.update(sg.core_measurements(latest, latest))
    except sg.MeasurementUnavailable as exc:
        row["unavailable"] = [str(exc)]
    row["bars"] = latest[-BARS_KEEP:]
    return row


def mark_flat_book(book_path: Path, now_real: datetime, prev_close: datetime) -> dict:
    """Re-stamp a flat book's as_of. Returns a record of what happened (never raises for policy)."""
    if not book_path.exists():
        return {"marked": False, "reason": "book_missing", "path": str(book_path)}
    raw = read_json(book_path)
    errs = core.schema_errors("engine_book.schema.json", raw)
    if errs:
        return {"marked": False, "reason": "book_invalid", "errors": errs}
    if raw.get("positions"):
        return {"marked": False, "reason": "open_positions_not_marked",
                "detail": "Phase 1 has no fill ledger to price positions; the pre-open job will fail book_stale "
                          "until the book is marked by hand"}
    if now_real < prev_close:
        return {"marked": False, "reason": "before_close"}
    before = raw.get("as_of")
    raw["as_of"] = core.iso(now_real)
    raw["marked_by"] = "dragonfly.jobs.prep (flat book: equity = cash; nothing to price)"
    errs = core.schema_errors("engine_book.schema.json", raw)
    if errs:
        return {"marked": False, "reason": "book_invalid_after_mark", "errors": errs}
    write_json(book_path, raw)
    return {"marked": True, "as_of_before": before, "as_of": raw["as_of"]}


def run_prep(
    repo_path: Path,
    *,
    now: datetime,
    date_arg: Optional[str] = None,
    handoff_root: str = core.DEFAULT_HANDOFF_ROOT,
    pull: bool = True,
    push: bool = True,
    state: Optional[Path] = None,
    book_path: Optional[Path] = None,
    mark_book: bool = True,
    preflight: Optional[Callable[[], None]] = None,
    build_fn: Optional[Callable[[Path, Path], dict]] = None,
    load_fn: Optional[Callable] = None,
    refresh_fn: Optional[Callable] = None,
    real_now: Callable[[], datetime] = core.now_ct,
) -> dict:
    from dragonfly import guards

    build_fn = build_fn or _default_build
    load_fn = load_fn or _default_load
    refresh_fn = refresh_fn or _default_refresh
    session = target_session(now, date_arg)
    ds = session.isoformat()
    prev = mc.previous_session(session)
    prev_close = mc.session_close(prev)
    if real_now() < prev_close:
        raise JobError(f"prep for {ds} needs {prev}'s close ({core.iso(prev_close)}); it is {core.iso(real_now())}")
    (preflight or guards.preflight)()  # real clock: daemon windows + bounded wait on the pipeline lock
    state = Path(state) if state else core.state_dir()
    dry = handoff_root != core.DEFAULT_HANDOFF_ROOT
    with job_lock("prep", state):
        repo = PrivateRepo(Path(repo_path))
        if pull:
            repo.sync()
        rel_dir = f"{handoff_root}/{ds}"
        out_dir = Path(repo_path) / rel_dir
        if (out_dir / READY_NAME).exists():
            raise JobError(f"{rel_dir}/READY already exists; prep will not change files READY already listed")
        # ---- watchlist through the gates, on state copies (run clone stays clean)
        universe_state = state / "universe.json"
        if not universe_state.exists():
            universe_state.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(core.ROOT / "dragonfly" / "universe.json", universe_state)
        watchlist_path = state / "watchlist.json"
        log.info("prep %s (previous session %s): building the watchlist", ds, prev)
        wl = build_fn(watchlist_path, universe_state)
        names = list(wl.get("names") or [])
        if not names:
            raise JobError("watchlist admitted no names; prep not written")
        # ---- bars for admitted names + measurements
        rows: List[dict] = []
        refreshed = unavailable = 0
        for n in names:
            bars, note = ensure_bars(n["ticker"], prev, prev_close, load_fn, refresh_fn)
            refreshed += note == "refreshed"
            row = measurement_row(n, bars, prev, note)
            unavailable += "unavailable" in row
            rows.append(row)
        if unavailable == len(rows):
            raise JobError(f"no admitted name has usable bars through {prev}; prep not written")
        as_of = core.iso(now)
        measurements = {
            "schema": MEASUREMENTS_SCHEMA,
            "session_date": ds,
            "previous_session": prev.isoformat(),
            "as_of": as_of,
            "source": "yahoo",
            "provisional": True,
            "contract": ("engine reads sector, spread, spread_source, provisional and bars per row "
                         "(dragonfly/engine/measure.py); price/atr/adv_dollars/relative_volume are "
                         "setup_gates.core_measurements through previous_session, informational"),
            "counts": {"names": len(rows), "bars_refreshed": refreshed, "unavailable": unavailable},
            "names": rows,
        }
        wl_snapshot = {k: v for k, v in wl.items() if k != "names"}
        wl_snapshot["names"] = [
            {k: n.get(k) for k in ("ticker", "rank", "sector", "sector_rank", "market_cap", "origin", "price",
                                   "adv20_dollars", "mid", "spread", "spread_source", "mid_source", "provisional")}
            for n in names
        ]
        prep = {
            "schema": PREP_SCHEMA,
            "session_date": ds,
            "previous_session": prev.isoformat(),
            "previous_close": core.iso(prev_close),
            "as_of": as_of,
            "handoff_root": handoff_root,
            "dry_run": dry,
            "tickers": [n["ticker"] for n in names],
            "measurements_file": MEASUREMENTS_NAME,
            "measurement_problems": {r["ticker"]: r["unavailable"] for r in rows if "unavailable" in r},
            "watchlist": wl_snapshot,
        }
        write_json(out_dir / MEASUREMENTS_NAME, measurements)
        write_json(out_dir / PREP_NAME, prep)
        paths = [f"{rel_dir}/{PREP_NAME}", f"{rel_dir}/{MEASUREMENTS_NAME}"]
        repo.commit_and_push(paths, f"prep {ds}: {len(rows)} names ({handoff_root})", push=push)
        log.info("prep %s committed%s: %d names, %d refreshed, %d unavailable",
                 ds, " and pushed" if push else "", len(rows), refreshed, unavailable)
        # ---- book mark (real runs only; never in a dry run)
        if dry or not mark_book:
            book = {"marked": False, "reason": "dry_run" if dry else "disabled"}
        else:
            book = mark_flat_book(Path(book_path) if book_path else core.default_book_path(), real_now(), prev_close)
        log.info("book mark: %s", book)
        return {"session_date": ds, "handoff": rel_dir, "files": paths, "names": len(rows),
                "bars_refreshed": refreshed, "unavailable": unavailable, "book_mark": book}
