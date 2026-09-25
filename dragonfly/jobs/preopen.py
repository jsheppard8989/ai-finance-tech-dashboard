"""Pre-open job: 08:05 CT on the session day. READY is its LAST step.

Steps (each failure is loud; after a failure READY is never written):
  1. Session = --date, else today (CT). A non-session day logs and exits 0.
     A --date that is not today needs --now (same rule as the engine loop).
  2. Load guards (real clock) and one pre-open at a time (job lock).
  3. Pull dragonfly-private. Require <handoff root>/<date>/prep.json and
     measurements.json, committed, for this session. Missing -> fail, no READY.
     READY already present -> refuse.
  4. Load and validate the live book (engine_book.schema.json) and apply the
     book_stale rule (as_of at or after the previous session's close). Stale ->
     fail, no READY.
  5. Pre-market quotes for the admitted names only (the prep's tickers), cache
     first (state/live/cache/quotes/), resolved with risk_math.resolve_quote
     (modeled $0.05 mid, paper only). Zero usable quotes -> fail, no READY.
  6. Write quotes.json and book.json (the book snapshot agents read), commit,
     push. Then write_ready() -- the very last step.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from dragonfly import market_calendar as mc
from dragonfly import risk_math as rm
from dragonfly.engine import core
from dragonfly.engine.gitops import PrivateRepo
from dragonfly.jobs.common import JobError, job_lock, read_json, to_float, write_json

log = logging.getLogger("dragonfly.jobs")

QUOTES_SCHEMA = "dragonfly.preopen_quotes/1"
BOOK_SNAPSHOT_SCHEMA = "dragonfly.book_snapshot/1"
QUOTE_CACHE_MINUTES = 10
MARKET_CONTEXT = ("SPY", "QQQ", "^VIX")  # best effort; never blocks READY
QUOTE_WORKERS = 6


def _epoch(value) -> Optional[float]:
    f = to_float(value)
    return f if f and f > 0 else None


def yahoo_preopen_quote(ticker: str) -> dict:
    """One guarded yfinance info call: bid/ask plus the freshest last trade
    (pre-market, regular or post-market, whichever printed last)."""
    from dragonfly import guards

    guards.before_fetch()  # pipeline lock + daemon window, real clock
    import yfinance as yf  # lazy: tests never import it

    info = yf.Ticker(ticker).info or {}
    candidates = [
        ("pre_market", info.get("preMarketPrice"), info.get("preMarketTime")),
        ("regular", info.get("regularMarketPrice") or info.get("currentPrice"), info.get("regularMarketTime")),
        ("post_market", info.get("postMarketPrice"), info.get("postMarketTime")),
    ]
    usable = [(src, to_float(p), _epoch(t)) for src, p, t in candidates if to_float(p) and _epoch(t)]
    last_src, last, qt = (max(usable, key=lambda c: c[2]) if usable else (None, None, None))
    return {
        "bid": info.get("bid"),
        "ask": info.get("ask"),
        "last": last,
        "last_source": last_src,
        "quote_time": qt,
        "previous_close": info.get("regularMarketPreviousClose") or info.get("previousClose"),
        "market_state": info.get("marketState"),
        "halted": None,  # Yahoo has no reliable per-name halt flag; unknown, never fabricated
    }


def _iso_epoch(ts) -> Optional[str]:
    f = _epoch(ts)
    return core.iso(datetime.fromtimestamp(f, tz=timezone.utc)) if f else None


def resolve_row(ticker: str, raw: Mapping, prev_close: Optional[float], now: datetime) -> dict:
    q = rm.resolve_quote(raw.get("bid"), raw.get("ask"), raw.get("last"))
    row = {
        "ticker": ticker,
        "usable": bool(q.get("usable")),
        "bid": to_float(q.get("bid")),
        "ask": to_float(q.get("ask")),
        "mid": to_float(q.get("mid")),
        "spread": to_float(q.get("spread")),
        "spread_source": q.get("spread_source"),
        "mid_source": q.get("mid_source"),
        "fallback_reason": q.get("fallback_reason"),
        "yahoo_bid": to_float(raw.get("bid")),
        "yahoo_ask": to_float(raw.get("ask")),
        "last_trade": to_float(raw.get("last")),
        "last_source": raw.get("last_source"),
        "quote_time": raw.get("quote_time"),
        "quote_time_ct": _iso_epoch(raw.get("quote_time")),
        "market_state": raw.get("market_state"),
        "halted": raw.get("halted"),
        "previous_close": prev_close,
        "provisional": True,
    }
    if not row["usable"]:
        row["reason"] = q.get("reason")
    if row["mid"] and prev_close:
        row["gap_pct"] = round(row["mid"] / prev_close - 1.0, 6)
    return row


class QuoteCache:
    """state/live/cache/quotes/<date>.json: raw quotes by ticker with fetched_at (real clock)."""

    def __init__(self, path: Path, max_age: timedelta = timedelta(minutes=QUOTE_CACHE_MINUTES)):
        self.path = path
        self.max_age = max_age
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, ticker: str, real_now: datetime) -> Optional[dict]:
        e = self.data.get(ticker)
        if not e:
            return None
        try:
            fetched = core.parse_iso(e["fetched_at"])
        except (KeyError, ValueError, core.EngineError):
            return None
        if timedelta(0) <= real_now - fetched < self.max_age:
            return e["raw"]
        return None

    def put(self, ticker: str, raw: dict, real_now: datetime) -> None:
        self.data[ticker] = {"fetched_at": core.iso(real_now), "raw": raw}

    def save(self) -> None:
        write_json(self.path, self.data)


def fetch_quotes(tickers: List[str], quote_fn: Callable[[str], dict], cache: QuoteCache,
                 real_now: Callable[[], datetime]) -> Dict[str, dict]:
    """Cache first; one fetch per missing ticker. Returns {ticker: raw or {"error": ...}}."""
    from dragonfly import guards

    out: Dict[str, dict] = {}
    todo = []
    for t in tickers:
        hit = cache.get(t, real_now())
        if hit is not None:
            out[t] = dict(hit, cache_hit=True)
        else:
            todo.append(t)

    def one(t):
        try:
            return t, quote_fn(t), None
        except guards.GuardBlocked:
            raise
        except Exception as exc:  # provider failure: recorded, fail closed per name
            return t, None, f"{type(exc).__name__}: {exc}"

    if todo:
        with ThreadPoolExecutor(max_workers=QUOTE_WORKERS) as pool:
            for t, raw, err in pool.map(one, todo):
                if raw is None:
                    out[t] = {"error": err}
                else:
                    cache.put(t, raw, real_now())
                    out[t] = dict(raw, cache_hit=False)
        cache.save()
    return out


def require_prep(repo: PrivateRepo, repo_path: Path, rel_dir: str, ds: str) -> dict:
    prep_path = Path(repo_path) / rel_dir / "prep.json"
    meas_path = Path(repo_path) / rel_dir / "measurements.json"
    missing = [p.name for p in (prep_path, meas_path) if not p.exists()]
    if missing:
        raise JobError(f"PREP MISSING: {rel_dir}/{' and '.join(missing)} not in dragonfly-private; "
                       "the 15:30 prep did not land. No quotes, no READY.")
    dirty = repo.dirty([f"{rel_dir}/prep.json", f"{rel_dir}/measurements.json"])
    if dirty:
        raise JobError(f"prep files are not committed: {dirty}; no READY")
    try:
        prep = read_json(prep_path)
        meas = read_json(meas_path)
    except (OSError, ValueError) as exc:
        raise JobError(f"prep unreadable: {exc}; no READY") from exc
    for name, doc in (("prep.json", prep), ("measurements.json", meas)):
        if not isinstance(doc, dict) or doc.get("session_date") != ds:
            raise JobError(f"{rel_dir}/{name} is not for {ds} (session_date {doc.get('session_date') if isinstance(doc, dict) else None}); no READY")
    return {"prep": prep, "measurements": meas}


def run_preopen(
    repo_path: Path,
    *,
    now_fn: Callable[[], datetime],
    date_arg: Optional[str] = None,
    simulated: bool = False,
    handoff_root: str = core.DEFAULT_HANDOFF_ROOT,
    pull: bool = True,
    push: bool = True,
    state: Optional[Path] = None,
    book_path: Optional[Path] = None,
    preflight: Optional[Callable[[], None]] = None,
    quote_fn: Optional[Callable[[str], dict]] = None,
    ready_fn: Optional[Callable] = None,
    real_now: Callable[[], datetime] = core.now_ct,
) -> dict:
    from dragonfly import guards
    from dragonfly.engine.markers import write_ready

    quote_fn = quote_fn or yahoo_preopen_quote
    now = now_fn()
    session = date.fromisoformat(date_arg) if date_arg else now.date()
    ds = session.isoformat()
    if session != now.date() and not simulated:
        raise JobError(f"--date {ds} is not today ({now.date()}); pass --now {ds}T08:05:00-05:00 for a dry run")
    try:
        if not mc.is_session(session):
            log.info("not_session: %s (%s); nothing to do", ds, mc.holiday_name(session) or "weekend")
            return {"session_date": ds, "not_session": True}
    except mc.CalendarNotCovered as exc:
        raise JobError(str(exc)) from exc
    (preflight or guards.preflight)()
    state = Path(state) if state else core.state_dir()
    book_path = Path(book_path) if book_path else core.default_book_path()
    with job_lock("preopen", state):
        repo = PrivateRepo(Path(repo_path))
        if pull:
            repo.sync()
        rel_dir = f"{handoff_root}/{ds}"
        out_dir = Path(repo_path) / rel_dir
        if (out_dir / "READY").exists():
            raise JobError(f"{rel_dir}/READY already exists; the pre-open already ran")
        docs = require_prep(repo, Path(repo_path), rel_dir, ds)
        # ---- book: schema + book_stale
        book = core.load_book(book_path)  # EngineError if missing / invalid
        fresh = core.book_freshness(book, session)
        if not fresh["fresh"]:
            raise JobError(f"BOOK STALE: book.json as_of {fresh.get('book_as_of')} is before the previous close "
                           f"{fresh.get('required_at_or_after')} ({fresh.get('detail', 'book_stale')}); no READY")
        raw_book = read_json(book_path)
        # ---- quotes (admitted names only)
        meas_rows = {r["ticker"]: r for r in docs["measurements"].get("names", []) if isinstance(r, dict) and r.get("ticker")}
        tickers = [t for t in docs["prep"].get("tickers") or list(meas_rows)]
        if not tickers:
            raise JobError("prep lists no admitted tickers; no READY")
        suffix = "" if handoff_root == core.DEFAULT_HANDOFF_ROOT else f".{handoff_root}"
        cache = QuoteCache(state / "cache" / "quotes" / f"{ds}{suffix}.json")
        raws = fetch_quotes(tickers, quote_fn, cache, real_now)
        rows = []
        for t in tickers:
            raw = raws.get(t) or {"error": "not fetched"}
            prev_close = to_float((meas_rows.get(t) or {}).get("price"))
            if "error" in raw:
                rows.append({"ticker": t, "usable": False, "reason": "quote_fetch_failed", "error": raw["error"],
                             "previous_close": prev_close, "provisional": True})
            else:
                row = resolve_row(t, raw, prev_close, now)
                row["cache_hit"] = raw.get("cache_hit", False)
                rows.append(row)
        usable = sum(1 for r in rows if r["usable"])
        if usable == 0:
            raise JobError(f"no usable pre-market quote for any of {len(tickers)} admitted names; no READY")
        market = {}
        mraws = fetch_quotes(list(MARKET_CONTEXT), quote_fn, cache, real_now)
        for t in MARKET_CONTEXT:
            raw = mraws.get(t) or {"error": "not fetched"}
            if "error" in raw:
                market[t] = {"usable": False, "error": raw["error"]}
            else:
                market[t] = resolve_row(t, raw, to_float(raw.get("previous_close")), now)
        as_of = core.iso(now)
        quotes = {
            "schema": QUOTES_SCHEMA,
            "session_date": ds,
            "as_of": as_of,
            "fetched_at_real": core.iso(real_now()),
            "source": "yahoo",
            "provisional": True,
            "quote_model": "risk_math.resolve_quote: Yahoo bid/ask if it passes the spread gate, else modeled $0.05 "
                           "around the mid or the freshest last trade (paper only; live-blocked)",
            "last_trade_rule": "freshest of pre-market, regular and post-market prints (last_source)",
            "counts": {"names": len(rows), "usable": usable, "cache_hits": sum(1 for r in rows if r.get("cache_hit"))},
            "names": rows,
            "market_context": {"note": "best effort, not a contract input", "quotes": market},
        }
        snapshot = {
            "schema": BOOK_SNAPSHOT_SCHEMA,
            "session_date": ds,
            "as_of": as_of,
            "source": "Mac live book (engine of record); agents read, never write",
            "freshness": fresh,
            "summary": {
                "book": raw_book["book"], "equity": raw_book["equity"], "cash": raw_book["cash"],
                "open_heat": core.to_json_number(book["open_heat"]), "gross_long": core.to_json_number(book["gross_long"]),
                "positions": len(raw_book["positions"]), "day_pnl_pct": raw_book["day_pnl_pct"],
                "week_pnl_pct": raw_book["week_pnl_pct"], "drawdown_pct": raw_book["drawdown_pct"],
                "consecutive_full_losses": raw_book["consecutive_full_losses"],
            },
            "book": raw_book,
        }
        write_json(out_dir / "quotes.json", quotes)
        write_json(out_dir / "book.json", snapshot)
        paths = [f"{rel_dir}/quotes.json", f"{rel_dir}/book.json"]
        repo.commit_and_push(paths, f"pre-open {ds}: quotes ({usable}/{len(rows)}) + book ({handoff_root})", push=push)
        log.info("pre-open %s: quotes %d/%d usable, book fresh; committed%s", ds, usable, len(rows),
                 " and pushed" if push else "")
        # ---- READY: the very last step
        ready = (ready_fn or write_ready)(Path(repo_path), session, now=now_fn(), pull=pull, push=push,
                                          handoff_root=handoff_root)
        log.info("READY %s/READY written (%d files)", rel_dir, len(ready["files"]))
        return {"session_date": ds, "handoff": rel_dir, "usable": usable, "names": len(rows),
                "ready": f"{rel_dir}/READY", "ready_files": [f["path"] for f in ready["files"]],
                "ready_as_of": ready["as_of"], "pushed_at_real": core.iso(real_now())}
