#!/usr/bin/env python3
"""Read-only quote normalizer & fallback loader for the home-page paper scoreboard.

Design:
  Robinhood quotes come from the user-Robinhood MCP connector (read-only calls ONLY:
  `get_equity_quotes` and `get_option_quotes`; NEVER place/review/simulate orders or
  touch accounts). Because MCP lives on the agent host rather than inside a bare Mac CLI,
  the nightly routine (or Wed test) calls those two read-only MCP tools, writes the JSON
  result (or passes --robinhood-json / --equity-json + --option-json), and this script
  normalizes, validates, and falls back to saved quotes if the live pull failed.

Fallback order when live Robinhood JSON is missing, unreadable, or incomplete:
  1. saved_legs.csv (if it includes bid/ask price columns)
  2. Newest dated YYYY-MM-DD.csv in the quotes directory (or --fallback-csv,
     copied from /workspace/cos/quotes/YYYY-MM-DD.csv)
  Fallback quotes are always flagged `is_fallback: true` with their exact quote time
  so the scoreboard page labels them clearly.

Usage:
  # List exact read-only MCP tool inputs needed for open book positions:
  python3 pipeline/pull_scoreboard_quotes.py --list-requests --book pipeline/state/paper_book.json

  # Normalize a live Robinhood JSON payload (with saved-quote fallback):
  python3 pipeline/pull_scoreboard_quotes.py \\
    --book pipeline/state/paper_book.json \\
    --robinhood-json pipeline/state/robinhood_raw.json \\
    --fallback-csv pipeline/state/fallback_quotes.csv \\
    --out pipeline/state/scoreboard_quotes.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOOK = ROOT / "pipeline" / "state" / "paper_book.json"
DEFAULT_SAVED_LEGS = ROOT / "pipeline" / "state" / "saved_legs.csv"
DEFAULT_FALLBACK_CSV = ROOT / "pipeline" / "state" / "fallback_quotes.csv"
DEFAULT_OUT = ROOT / "pipeline" / "state" / "scoreboard_quotes.json"
COS_BOOK_DIR = Path("/workspace/cos/paper_book")
COS_QUOTES_DIR = Path("/workspace/cos/quotes")

STALE_DAYS = 5  # covers 3-day holiday weekends (e.g. Thanksgiving Thu -> Wed 3 PM)
WIDE_PCT = 0.50


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_ct_timestamp(raw: Any) -> datetime | None:
    """Parse ISO UTC/offset timestamps or 'YYYY-MM-DD HH:MM:SS CST/CDT' into CT."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Handle "2026-11-24 14:59:59 CST" or "CDT"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(CST|CDT|CT)$", s, re.I)
    if m:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        tz = m.group(3).upper()
        if tz == "CST":
            return dt.replace(tzinfo=timezone.utc).astimezone(CT) if False else datetime(
                dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=ZoneInfo("Etc/GMT+6")
            ).astimezone(CT)
        if tz == "CDT":
            return datetime(
                dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=ZoneInfo("Etc/GMT+5")
            ).astimezone(CT)
        return dt.replace(tzinfo=CT)
    # Handle ISO 8601 (with Z or explicit offset)
    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CT)
    return dt.astimezone(CT)


def format_ct_label(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CT)
    hour_str = local.strftime("%I:%M %p").lstrip("0")
    return f"{local.strftime('%b')} {local.day}, {hour_str} CT"


def quote_problems(label: str, q: dict[str, Any], now: datetime) -> list[str]:
    bid = _float(q.get("bid"))
    ask = _float(q.get("ask"))
    if bid is None or bid <= 0:
        return [f"{label}: no bid ({bid}/{ask})"]
    if ask is None or ask <= 0:
        return [f"{label}: no ask ({bid}/{ask})"]
    if bid > ask:
        return [f"{label}: bid above ask ({bid}/{ask})"]
    out: list[str] = []
    vol = _int(q.get("volume"))
    oi = _int(q.get("open_interest") if q.get("open_interest") is not None else q.get("oi"))
    if not vol and not oi and (vol is not None or oi is not None):
        out.append(f"{label}: zero volume and zero open interest")
    mid = (bid + ask) / 2.0
    if mid > 0 and (ask - bid) > WIDE_PCT * mid:
        out.append(f"{label}: spread {bid}/{ask} wider than {int(WIDE_PCT * 100)}% of mid")
    ts = parse_ct_timestamp(q.get("quote_time_ct") or q.get("ts"))
    if ts is not None and (now.astimezone(CT) - ts).total_seconds() > STALE_DAYS * 86400:
        out.append(f"{label}: quote is stale ({format_ct_label(ts)})")
    return out


def find_newest_dated_file(directory: Path, pattern: str) -> Path | None:
    if not directory.is_dir():
        return None
    matches: list[tuple[str, Path]] = []
    rx = re.compile(pattern)
    for p in directory.iterdir():
        if p.is_file():
            m = rx.match(p.name)
            if m:
                matches.append((m.group(1), p))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def resolve_book_path(book_arg: Path | None) -> Path:
    if book_arg is not None:
        return Path(book_arg)
    cos_newest = find_newest_dated_file(COS_BOOK_DIR, r"^(\d{4}-\d{2}-\d{2})_book\.json$")
    if cos_newest is not None:
        return cos_newest
    return DEFAULT_BOOK


def load_saved_legs(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_mcp_requests(book: dict[str, Any], saved_legs_rows: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Return read-only user-Robinhood MCP arguments for all open positions."""
    equity_symbols: list[str] = []
    option_ids: list[str] = []
    seen_eq: set[str] = set()
    seen_opt: set[str] = set()

    def add_eq(sym: str | None) -> None:
        s = (sym or "").strip().upper()
        if s and s not in seen_eq:
            seen_eq.add(s)
            equity_symbols.append(s)

    def add_opt(uid: str | None) -> None:
        u = (uid or "").strip()
        if u and u not in seen_opt:
            seen_opt.add(u)
            option_ids.append(u)

    for pos in book.get("open") or []:
        add_eq(pos.get("ticker"))
        legs = pos.get("legs")
        if isinstance(legs, dict):
            for leg in legs.values():
                if isinstance(leg, dict):
                    add_opt(leg.get("instrument_id"))
        elif isinstance(legs, list):
            for leg in legs:
                if isinstance(leg, dict):
                    add_opt(leg.get("instrument_id"))

    for row in saved_legs_rows or []:
        add_eq(row.get("underlying"))
        add_opt(row.get("instrument_id"))

    return {
        "read_only": True,
        "tools": [
            {"namespace": "user-Robinhood", "tool": "get_equity_quotes", "arguments": {"symbols": equity_symbols}},
            {"namespace": "user-Robinhood", "tool": "get_option_quotes", "arguments": {"instrument_ids": option_ids}},
        ],
        "equity_symbols": equity_symbols,
        "option_instrument_ids": option_ids,
    }


def _extract_list(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in keys:
            val = payload.get(k)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        # Maybe single-item dict
        if any(k in payload for k in ("symbol", "instrument_id", "id", "bid", "bid_price")):
            return [payload]
    return []


def parse_robinhood_payload(
    raw_eq: Any,
    raw_opt: Any,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Parse raw user-Robinhood MCP JSON outputs into normalized equity and option quote maps."""
    eq_map: dict[str, dict[str, Any]] = {}
    opt_map: dict[str, dict[str, Any]] = {}

    for item in _extract_list(raw_eq, "equity", "quotes", "results", "data"):
        sym = str(item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        bid = _float(item.get("bid") if item.get("bid") is not None else item.get("bid_price"))
        ask = _float(item.get("ask") if item.get("ask") is not None else item.get("ask_price"))
        last = _float(
            item.get("last")
            if item.get("last") is not None
            else item.get("last_trade_price") or item.get("last_extended_hours_trade_price")
        )
        prev_close = _float(item.get("adjusted_previous_close") or item.get("previous_close_official") or item.get("previous_close"))
        ts = parse_ct_timestamp(
            item.get("quote_timestamp_ct")
            or item.get("venue_bid_ask_utc")
            or item.get("updated_at")
            or item.get("last_trade_timestamp_ct")
            or item.get("venue_last_trade_utc")
        ) or now.astimezone(CT)
        eq_map[sym] = {
            "symbol": sym,
            "bid": bid,
            "ask": ask,
            "last": last,
            "previous_close": prev_close,
            "quote_time_ct": ts.isoformat(timespec="seconds"),
            "quote_time_label": format_ct_label(ts),
            "quote_source": "Robinhood (live read-only)",
            "is_fallback": False,
        }

    for item in _extract_list(raw_opt, "options", "quotes", "results", "data"):
        uid = str(item.get("instrument_id") or item.get("instrument") or item.get("id") or "").strip()
        # Handle Robinhood instrument URLs like https://api.robinhood.com/options/instruments/<uuid>/
        if uid.startswith("http"):
            uid = uid.rstrip("/").rsplit("/", 1)[-1]
        if not uid:
            continue
        bid = _float(item.get("bid") if item.get("bid") is not None else item.get("bid_price"))
        ask = _float(item.get("ask") if item.get("ask") is not None else item.get("ask_price"))
        last = _float(item.get("last") if item.get("last") is not None else item.get("last_trade_price") or item.get("mark_price"))
        vol = _int(item.get("volume"))
        oi = _int(item.get("open_interest") if item.get("open_interest") is not None else item.get("oi"))
        ts = parse_ct_timestamp(
            item.get("quote_timestamp_ct") or item.get("updated_at_utc") or item.get("updated_at")
        ) or now.astimezone(CT)
        opt_map[uid] = {
            "instrument_id": uid,
            "bid": bid,
            "ask": ask,
            "last": last,
            "volume": vol,
            "open_interest": oi,
            "quote_time_ct": ts.isoformat(timespec="seconds"),
            "quote_time_label": format_ct_label(ts),
            "quote_source": "Robinhood (live read-only)",
            "is_fallback": False,
        }

    return eq_map, opt_map


def parse_quotes_csv(csv_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Parse saved_legs.csv (if priced) or YYYY-MM-DD.csv into equity + option maps (newest row wins)."""
    if not csv_path.is_file():
        return {}, {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}, {}
    # Check whether this CSV actually carries bid/ask prices
    cols = set(rows[0].keys())
    if "bid" not in cols or "ask" not in cols:
        return {}, {}

    eq_map: dict[str, tuple[datetime, dict[str, Any]]] = {}
    opt_map: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for row in rows:
        bid = _float(row.get("bid"))
        ask = _float(row.get("ask"))
        if bid is None or ask is None:
            continue
        ts = (
            parse_ct_timestamp(row.get("quote_timestamp"))
            or parse_ct_timestamp(row.get("time_ct"))
            or datetime.now(CT)
        )
        uid = (row.get("instrument_id") or "").strip()
        sym_leg = (row.get("symbol_leg") or row.get("underlying") or "").strip()
        last = _float(row.get("last"))
        q_label = format_ct_label(ts)
        if uid:
            rec = {
                "instrument_id": uid,
                "symbol_leg": sym_leg,
                "bid": bid,
                "ask": ask,
                "last": last,
                "volume": _int(row.get("volume")),
                "open_interest": _int(row.get("open_interest")),
                "quote_time_ct": ts.isoformat(timespec="seconds"),
                "quote_time_label": q_label,
                "quote_source": f"Saved quotes ({q_label})",
                "is_fallback": True,
            }
            prev = opt_map.get(uid)
            if prev is None or ts >= prev[0]:
                opt_map[uid] = (ts, rec)
        elif sym_leg:
            ticker = (row.get("underlying") or sym_leg.split()[0]).strip().upper()
            rec = {
                "symbol": ticker,
                "bid": bid,
                "ask": ask,
                "last": last,
                "quote_time_ct": ts.isoformat(timespec="seconds"),
                "quote_time_label": q_label,
                "quote_source": f"Saved quotes ({q_label})",
                "is_fallback": True,
            }
            prev = eq_map.get(ticker)
            if prev is None or ts >= prev[0]:
                eq_map[ticker] = (ts, rec)

    return {k: v for k, (_, v) in eq_map.items()}, {k: v for k, (_, v) in opt_map.items()}


def normalize_quotes(
    book: dict[str, Any],
    robinhood_raw: Any = None,
    equity_raw: Any = None,
    option_raw: Any = None,
    saved_legs_path: Path | None = None,
    fallback_csv_path: Path | None = None,
    quotes_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combine live Robinhood quotes with saved-quote fallback cleanly."""
    now = (now or datetime.now(CT)).astimezone(CT)
    if saved_legs_path is None:
        saved_legs_path = DEFAULT_SAVED_LEGS if DEFAULT_SAVED_LEGS.is_file() else (COS_QUOTES_DIR / "saved_legs.csv")
    saved_rows = load_saved_legs(saved_legs_path)
    saved_by_uid = {
        str(r.get("instrument_id") or "").strip(): r
        for r in saved_rows
        if str(r.get("instrument_id") or "").strip()
    }
    reqs = build_mcp_requests(book, saved_rows)

    if robinhood_raw is not None and isinstance(robinhood_raw, dict):
        if equity_raw is None:
            equity_raw = robinhood_raw.get("equity") or robinhood_raw.get("equity_quotes")
        if option_raw is None:
            option_raw = robinhood_raw.get("options") or robinhood_raw.get("option_quotes")
        if equity_raw is None and option_raw is None:
            # Flat results list?
            equity_raw = robinhood_raw
            option_raw = robinhood_raw

    live_eq, live_opt = parse_robinhood_payload(equity_raw, option_raw, now)

    # Build fallback candidates: saved_legs.csv (if priced) -> fallback_csv_path -> newest YYYY-MM-DD.csv
    fb_eq: dict[str, dict[str, Any]] = {}
    fb_opt: dict[str, dict[str, Any]] = {}
    for candidate in [
        saved_legs_path,
        fallback_csv_path,
        find_newest_dated_file(quotes_dir or COS_QUOTES_DIR, r"^(\d{4}-\d{2}-\d{2})\.csv$"),
    ]:
        if candidate is not None and candidate.is_file():
            ceq, copt = parse_quotes_csv(candidate)
            for k, v in ceq.items():
                fb_eq.setdefault(k, v)
            for k, v in copt.items():
                fb_opt.setdefault(k, v)

    final_eq: dict[str, dict[str, Any]] = {}
    final_opt: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    used_fallback = False

    # Check open positions' needed equity symbols & option ids
    needed_eq = {str(p.get("ticker") or "").strip().upper() for p in (book.get("open") or []) if p.get("ticker")}
    for sym in sorted(needed_eq):
        q = live_eq.get(sym)
        probs = quote_problems(sym, q, now) if q else [f"{sym}: missing live Robinhood quote"]
        if q and not probs:
            final_eq[sym] = q
        else:
            errors.extend(probs)
            fb = fb_eq.get(sym)
            if fb:
                final_eq[sym] = fb
                used_fallback = True
            elif q:
                final_eq[sym] = q

    for uid in reqs["option_instrument_ids"]:
        q = live_opt.get(uid)
        probs = quote_problems(uid, q, now) if q else [f"{uid}: missing live Robinhood option quote"]
        chosen = None
        if q and not probs:
            chosen = dict(q)
        else:
            errors.extend(probs)
            fb = fb_opt.get(uid)
            if fb:
                chosen = dict(fb)
                used_fallback = True
            elif q:
                chosen = dict(q)
        if chosen is not None:
            meta = saved_by_uid.get(uid) or {}
            desc = meta.get("symbol_leg") or meta.get("leg_description")
            if not chosen.get("symbol_leg") and desc:
                chosen["symbol_leg"] = desc
            final_opt[uid] = chosen

    # Also keep any extra live/fallback equity quotes (e.g. GOOGL/TLT underlying last)
    for sym, q in live_eq.items():
        final_eq.setdefault(sym, q)
    for sym, q in fb_eq.items():
        if sym not in final_eq:
            final_eq[sym] = q

    all_times = [
        parse_ct_timestamp(q.get("quote_time_ct"))
        for q in list(final_eq.values()) + list(final_opt.values())
        if q.get("quote_time_ct")
    ]
    all_times = [t for t in all_times if t is not None]
    newest_dt = max(all_times) if all_times else now
    any_live = any(not q.get("is_fallback") for q in list(final_eq.values()) + list(final_opt.values()))
    is_fallback = used_fallback or not any_live
    q_label = format_ct_label(newest_dt)
    source_label = (
        f"Saved quote fallback ({q_label})" if is_fallback else f"Robinhood read-only ({q_label})"
    )

    return {
        "generated_at_ct": now.isoformat(timespec="seconds"),
        "quote_time_ct": newest_dt.isoformat(timespec="seconds"),
        "quote_time_label": q_label,
        "quote_source": source_label,
        "is_fallback": is_fallback,
        "equity": final_eq,
        "options": final_opt,
        "errors": errors,
    }


def _load_json_opt(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Normalize read-only Robinhood scoreboard quotes with saved fallback.")
    ap.add_argument("--book", type=Path, default=None, help="Path to paper_book JSON (default: newest /workspace/cos/paper_book or pipeline/state/paper_book.json)")
    ap.add_argument("--saved-legs", type=Path, default=DEFAULT_SAVED_LEGS, help="Path to saved_legs.csv")
    ap.add_argument("--fallback-csv", type=Path, default=DEFAULT_FALLBACK_CSV, help="Path to dated quote CSV fallback")
    ap.add_argument("--quotes-dir", type=Path, default=COS_QUOTES_DIR, help="Directory with YYYY-MM-DD.csv snapshots")
    ap.add_argument("--robinhood-json", type=Path, default=None, help="Combined Robinhood MCP read-only quote JSON")
    ap.add_argument("--equity-json", type=Path, default=None, help="Robinhood get_equity_quotes JSON")
    ap.add_argument("--option-json", type=Path, default=None, help="Robinhood get_option_quotes JSON")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Normalized output path")
    ap.add_argument("--list-requests", action="store_true", help="Print exact read-only MCP arguments and exit")
    args = ap.parse_args(argv)

    book_path = resolve_book_path(args.book)
    if not book_path.is_file():
        print(f"ERROR: paper book not found: {book_path}", file=sys.stderr)
        return 1
    book = json.loads(book_path.read_text(encoding="utf-8"))

    saved_legs_path = args.saved_legs
    if not saved_legs_path.is_file() and (COS_QUOTES_DIR / "saved_legs.csv").is_file():
        saved_legs_path = COS_QUOTES_DIR / "saved_legs.csv"

    if args.list_requests:
        reqs = build_mcp_requests(book, load_saved_legs(saved_legs_path))
        print(json.dumps(reqs, indent=2))
        return 0

    rh_raw = _load_json_opt(args.robinhood_json)
    eq_raw = _load_json_opt(args.equity_json)
    opt_raw = _load_json_opt(args.option_json)

    out_data = normalize_quotes(
        book=book,
        robinhood_raw=rh_raw,
        equity_raw=eq_raw,
        option_raw=opt_raw,
        saved_legs_path=saved_legs_path,
        fallback_csv_path=args.fallback_csv,
        quotes_dir=args.quotes_dir,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(args.out)
    print(f"Wrote {args.out} ({out_data['quote_source']}, {len(out_data['equity'])} equity, {len(out_data['options'])} options, fallback={out_data['is_fallback']})")
    for err in out_data["errors"]:
        print(f"  WARN quote: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
