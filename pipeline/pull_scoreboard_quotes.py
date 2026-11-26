#!/usr/bin/env python3
"""Read-only quote loader for the paper-trade scoreboard.

Robinhood quotes come from the user-Robinhood MCP connector, READ-ONLY calls only:
`get_equity_quotes` and `get_option_quotes`. Never place, review or simulate orders,
and never touch account settings. MCP tools run inside a Grok Bot turn on the box, so
the box routine saves each tool result to a file and passes the files here.

What this module does:
  * parse raw Robinhood tool output (the saved file may be wrapped in a fence; the
    first JSON object in the file is used),
  * keep only quotes that a closing-side mark can use: two-sided, not wider than 50%
    of mid, and stamped inside a regular session (8:30 AM to 3:00 PM CT, 12:00 PM CT
    on early-close days, plus 15 minutes for ETF options). After-hours stock bid/ask
    is NOT used for marks,
  * pick, per instrument, the newest usable quote across the live pull and every
    dated /workspace/cos/quotes/YYYY-MM-DD.csv read,
  * record a live pull: append rows to the dated CSV (same columns the three-a-day
    read has used since Nov 13), write an audit JSON, and append SPY official closes
    to spy_closes.csv for the benchmark line.

Freshness is decided by trading sessions, not calendar days: a mark is "older than
1 trading day" once the next full session after it has closed (market_calendar.py).

Usage:
  # Tool arguments the routine must call (read-only):
  python3 pipeline/pull_scoreboard_quotes.py --list-requests

  # Record a live pull and write normalized quotes:
  python3 pipeline/pull_scoreboard_quotes.py \\
      --equity-json /workspace/cos/quotes/raw/2026-11-27_0835_equity.json \\
      --option-json /workspace/cos/quotes/raw/2026-11-27_0835_options.json \\
      --record --out pipeline/state/scoreboard_quotes.json
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

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import market_calendar as mc  # noqa: E402

CT = ZoneInfo("America/Chicago")
ROOT = _HERE.parent
DEFAULT_BOOK = ROOT / "pipeline" / "state" / "paper_book.json"
DEFAULT_OUT = ROOT / "pipeline" / "state" / "scoreboard_quotes.json"
COS_BOOK_DIR = Path("/workspace/cos/paper_book")
COS_QUOTES_DIR = Path("/workspace/cos/quotes")

# A mark is flagged once it is older than this many trading sessions.
STALE_TRADING_DAYS = 1
WIDE_PCT = 0.50
BENCHMARK_SYMBOL = "SPY"
CSV_COLUMNS = [
    "time_ct", "symbol_leg", "bid", "ask", "last", "quote_timestamp", "modeled_fill_mark",
    "side", "instrument_id", "mid", "bid_size", "ask_size", "volume", "staleness_sec",
    "stop_or_exit_rule", "alert",
]
DATED_CSV_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")


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
    """Parse ISO (Z or offset, any fraction length) or 'YYYY-MM-DD HH:MM:SS CST/CDT' into CT."""
    if not raw:
        return None
    s = str(raw).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(CST|CDT|CT)$", s, re.I)
    if m:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        tz = m.group(3).upper()
        if tz == "CST":
            return dt.replace(tzinfo=ZoneInfo("Etc/GMT+6")).astimezone(CT)
        if tz == "CDT":
            return dt.replace(tzinfo=ZoneInfo("Etc/GMT+5")).astimezone(CT)
        return dt.replace(tzinfo=CT)
    # Trim nanosecond fractions to microseconds for fromisoformat.
    s2 = re.sub(r"(\.\d{6})\d+", r"\1", s)
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CT)
    return dt.astimezone(CT)


def format_ct_label(dt: datetime | None, weekday: bool = True) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CT)
    hour_str = local.strftime("%I:%M %p").lstrip("0")
    day = f"{local.strftime('%a')} " if weekday else ""
    return f"{day}{local.strftime('%b')} {local.day}, {hour_str} CT"


def closing_mark(bid: float, ask: float, qty_sign: int) -> float:
    """Closing side: a long sells at bid + (ask-bid)/3, a short buys back at ask - (ask-bid)/3."""
    return bid + (ask - bid) / 3.0 if qty_sign > 0 else ask - (ask - bid) / 3.0


def quote_problems(label: str, q: dict[str, Any] | None) -> list[str]:
    """Reasons a quote cannot be used for a closing-side mark (empty list = usable)."""
    if not q:
        return [f"{label}: no quote"]
    bid, ask = _float(q.get("bid")), _float(q.get("ask"))
    if bid is None or bid <= 0:
        return [f"{label}: no bid ({bid}/{ask})"]
    if ask is None or ask <= 0:
        return [f"{label}: no ask ({bid}/{ask})"]
    if bid > ask:
        return [f"{label}: bid above ask ({bid}/{ask})"]
    out: list[str] = []
    mid = (bid + ask) / 2.0
    if mid > 0 and (ask - bid) > WIDE_PCT * mid:
        out.append(f"{label}: spread {bid}/{ask} wider than {int(WIDE_PCT * 100)}% of mid")
    ts = parse_ct_timestamp(q.get("quote_time_ct"))
    if ts is None:
        out.append(f"{label}: quote has no timestamp")
    elif not mc.in_regular_session(ts):
        out.append(f"{label}: quote stamped outside the regular session ({format_ct_label(ts)})")
    return out


def find_newest_dated_file(directory: Path, pattern: str) -> Path | None:
    if not directory.is_dir():
        return None
    rx = re.compile(pattern)
    matches = sorted((m.group(1), p) for p in directory.iterdir() if p.is_file() and (m := rx.match(p.name)))
    return matches[-1][1] if matches else None


def resolve_book_path(book_arg: Path | None) -> Path:
    if book_arg is not None:
        return Path(book_arg)
    newest = find_newest_dated_file(COS_BOOK_DIR, r"^(\d{4}-\d{2}-\d{2})_book\.json$")
    return newest if newest is not None else DEFAULT_BOOK


def load_saved_legs(path: Path | None) -> list[dict[str, str]]:
    if path is None or not Path(path).is_file():
        return []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_mcp_requests(book: dict[str, Any], saved_legs: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Read-only user-Robinhood MCP arguments for every open book position plus SPY.

    Option instrument ids come from the book legs and from saved_legs.csv rows whose
    position_id is still open in the book (closed positions are not re-read)."""
    equity: list[str] = []
    options: list[str] = []
    for pos in book.get("open") or []:
        t = str(pos.get("ticker") or "").strip().upper()
        if t and t not in equity:
            equity.append(t)
        legs = pos.get("legs")
        for leg in (legs.values() if isinstance(legs, dict) else legs or []):
            uid = str((leg or {}).get("instrument_id") or "").strip() if isinstance(leg, dict) else ""
            if uid and uid not in options:
                options.append(uid)
    open_ids = {str(p.get("id") or "") for p in book.get("open") or []}
    for row in saved_legs or []:
        if str(row.get("position_id") or "") not in open_ids:
            continue
        uid = str(row.get("instrument_id") or "").strip()
        if uid and uid not in options:
            options.append(uid)
    if BENCHMARK_SYMBOL not in equity:
        equity.append(BENCHMARK_SYMBOL)
    return {
        "read_only": True,
        "tools": [
            {"namespace": "user-Robinhood", "tool": "get_equity_quotes", "arguments": {"symbols": equity}},
            {"namespace": "user-Robinhood", "tool": "get_option_quotes", "arguments": {"instrument_ids": options}},
        ],
        "equity_symbols": equity,
        "option_instrument_ids": options,
    }


def load_tool_json(path: Path | None) -> Any:
    """Load a saved MCP tool result. Tolerates a wrapper around the JSON (first object wins)."""
    if path is None or not Path(path).is_file():
        return None
    text = Path(path).read_text(encoding="utf-8")
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def _results(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict):
            for k in ("results", "quotes", "equity", "options"):
                if isinstance(data.get(k), list):
                    return [x for x in data[k] if isinstance(x, dict)]
            return [data]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def parse_robinhood_payload(raw_eq: Any, raw_opt: Any) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Return (equity quotes, option quotes, official closes by symbol) from raw tool output."""
    eq: dict[str, dict] = {}
    opt: dict[str, dict] = {}
    closes: dict[str, dict] = {}
    for item in _results(raw_eq):
        q = item.get("quote") if isinstance(item.get("quote"), dict) else item
        sym = str(q.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ts = parse_ct_timestamp(q.get("venue_bid_time") or q.get("venue_ask_time") or q.get("updated_at"))
        last_ts = parse_ct_timestamp(q.get("venue_last_trade_time"))
        eq[sym] = {
            "symbol": sym,
            "bid": _float(q.get("bid_price", q.get("bid"))),
            "ask": _float(q.get("ask_price", q.get("ask"))),
            "last": _float(q.get("last_trade_price", q.get("last"))),
            "last_time_ct": last_ts.isoformat(timespec="seconds") if last_ts else None,
            "quote_time_ct": ts.isoformat(timespec="seconds") if ts else None,
            "source": "Robinhood get_equity_quotes (read-only)",
        }
        close = item.get("close") if isinstance(item.get("close"), dict) else None
        if close and close.get("date") and _float(close.get("price")) is not None:
            closes[sym] = {"date": str(close["date"])[:10], "close": _float(close["price"]),
                           "source": str(close.get("source") or "robinhood close")}
    for item in _results(raw_opt):
        q = item.get("quote") if isinstance(item.get("quote"), dict) else item
        uid = str(q.get("instrument_id") or q.get("id") or "").strip()
        if uid.startswith("http"):
            uid = uid.rstrip("/").rsplit("/", 1)[-1]
        if not uid:
            continue
        ts = parse_ct_timestamp(q.get("updated_at"))
        opt[uid] = {
            "instrument_id": uid,
            "bid": _float(q.get("bid_price", q.get("bid"))),
            "ask": _float(q.get("ask_price", q.get("ask"))),
            "bid_size": _int(q.get("bid_size")),
            "ask_size": _int(q.get("ask_size")),
            "volume": _int(q.get("volume")),
            "open_interest": _int(q.get("open_interest")),
            "quote_time_ct": ts.isoformat(timespec="seconds") if ts else None,
            "source": "Robinhood get_option_quotes (read-only)",
        }
    return eq, opt, closes


def parse_quotes_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Every priced row of a dated three-a-day read CSV, as quote records."""
    if not Path(csv_path).is_file():
        return []
    with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out: list[dict[str, Any]] = []
    for row in rows:
        bid, ask = _float(row.get("bid")), _float(row.get("ask"))
        if bid is None or ask is None:
            continue
        ts = parse_ct_timestamp(row.get("quote_timestamp")) or parse_ct_timestamp(row.get("time_ct"))
        uid = (row.get("instrument_id") or "").strip()
        leg = (row.get("symbol_leg") or "").strip()
        rec = {
            "bid": bid,
            "ask": ask,
            "last": _float(row.get("last")),
            "quote_time_ct": ts.isoformat(timespec="seconds") if ts else None,
            "read_time_ct": (parse_ct_timestamp(row.get("time_ct")) or ts).isoformat(timespec="seconds") if ts else None,
            "symbol_leg": leg,
            "source": f"three-a-day read, {Path(csv_path).name}",
        }
        if uid:
            rec["instrument_id"] = uid
        else:
            rec["symbol"] = (leg.split()[0] if leg else "").upper()
        out.append(rec)
    return out


def load_csv_history(quotes_dir: Path | None) -> list[dict[str, Any]]:
    qd = Path(quotes_dir) if quotes_dir else COS_QUOTES_DIR
    if not qd.is_dir():
        return []
    recs: list[dict[str, Any]] = []
    for p in sorted(qd.iterdir()):
        if p.is_file() and DATED_CSV_RE.match(p.name):
            recs.extend(parse_quotes_csv(p))
    return recs


def _newest_usable(cands: list[dict[str, Any]], label: str) -> tuple[dict[str, Any] | None, list[str]]:
    usable, problems = [], []
    for c in cands:
        p = quote_problems(label, c)
        if p:
            problems.extend(p)
        else:
            usable.append(c)
    if not usable:
        return None, problems
    usable.sort(key=lambda c: parse_ct_timestamp(c.get("quote_time_ct")))
    return usable[-1], problems


def normalize_quotes(
    book: dict[str, Any],
    live_eq: dict[str, dict] | None = None,
    live_opt: dict[str, dict] | None = None,
    quotes_dir: Path | None = None,
    now: datetime | None = None,
    saved_legs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Newest usable quote per open-book instrument across the live pull and saved reads."""
    now = (now or datetime.now(CT)).astimezone(CT)
    live_eq, live_opt = live_eq or {}, live_opt or {}
    history = load_csv_history(quotes_dir)
    reqs = build_mcp_requests(book, saved_legs)
    final_eq: dict[str, dict] = {}
    final_opt: dict[str, dict] = {}
    notes: list[str] = []
    for sym in reqs["equity_symbols"]:
        cands = [dict(r) for r in history if r.get("symbol") == sym]
        if sym in live_eq:
            cands.append(dict(live_eq[sym]))
        best, probs = _newest_usable(cands, sym)
        if sym in live_eq and quote_problems(sym, live_eq[sym]):
            notes.extend(quote_problems(f"live {sym}", live_eq[sym]))
        if best:
            final_eq[sym] = best
        elif sym != BENCHMARK_SYMBOL:
            notes.extend(probs or [f"{sym}: no usable quote"])
    for uid in reqs["option_instrument_ids"]:
        cands = [dict(r) for r in history if r.get("instrument_id") == uid]
        if uid in live_opt:
            cands.append(dict(live_opt[uid]))
        best, probs = _newest_usable(cands, uid)
        if uid in live_opt and quote_problems(uid, live_opt[uid]):
            notes.extend(quote_problems(f"live {uid}", live_opt[uid]))
        if best:
            final_opt[uid] = best
        else:
            notes.extend(probs or [f"{uid}: no usable quote"])
    return {
        "generated_at_ct": now.isoformat(timespec="seconds"),
        "equity": final_eq,
        "options": final_opt,
        "notes": notes,
    }


def _saved_leg_index(saved_legs: list[dict[str, str]]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_uid = {r["instrument_id"].strip(): r for r in saved_legs if (r.get("instrument_id") or "").strip()}
    by_sym = {r["underlying"].strip().upper(): r for r in saved_legs
              if not (r.get("instrument_id") or "").strip() and r.get("underlying")}
    return by_uid, by_sym


def record_live_read(
    quotes_dir: Path,
    live_eq: dict[str, dict],
    live_opt: dict[str, dict],
    closes: dict[str, dict],
    saved_legs: list[dict[str, str]],
    read_time: datetime,
    routine: str = "three-a-day-quote-read",
) -> dict[str, Path]:
    """Append a live read to YYYY-MM-DD.csv, write the audit JSON and SPY closes."""
    quotes_dir = Path(quotes_dir)
    quotes_dir.mkdir(parents=True, exist_ok=True)
    rt = read_time.astimezone(CT)
    csv_path = quotes_dir / f"{rt.date().isoformat()}.csv"
    by_uid, by_sym = _saved_leg_index(saved_legs)
    rows = []

    def ct_str(iso: str | None) -> str:
        dt = parse_ct_timestamp(iso)
        return dt.strftime("%Y-%m-%d %H:%M:%S ") + ("CDT" if dt.dst() else "CST") if dt else ""

    read_str = rt.strftime("%Y-%m-%d %H:%M:%S ") + ("CDT" if rt.dst() else "CST")
    for sym, meta in by_sym.items():
        q = live_eq.get(sym)
        if not q:
            continue
        qty = 1 if (meta.get("side") or "buy") == "buy" else -1
        mark = closing_mark(q["bid"], q["ask"], qty) if q.get("bid") and q.get("ask") else None
        ts = parse_ct_timestamp(q.get("quote_time_ct"))
        rows.append({
            "time_ct": read_str, "symbol_leg": meta.get("leg_description") or sym,
            "bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last"),
            "quote_timestamp": ct_str(q.get("quote_time_ct")),
            "modeled_fill_mark": round(mark, 6) if mark is not None else "",
            "side": meta.get("side") or "buy", "instrument_id": "",
            "mid": round((q["bid"] + q["ask"]) / 2, 4) if q.get("bid") and q.get("ask") else "",
            "bid_size": "", "ask_size": "", "volume": "",
            "staleness_sec": round((rt - ts).total_seconds(), 1) if ts else "",
            "stop_or_exit_rule": meta.get("stop_or_exit_rule") or "",
            "alert": "; ".join(quote_problems(sym, q)),
        })
    for uid, meta in by_uid.items():
        q = live_opt.get(uid)
        if not q:
            continue
        qty = 1 if (meta.get("side") or "buy") == "buy" else -1
        mark = closing_mark(q["bid"], q["ask"], qty) if q.get("bid") and q.get("ask") else None
        ts = parse_ct_timestamp(q.get("quote_time_ct"))
        rows.append({
            "time_ct": read_str, "symbol_leg": meta.get("leg_description") or uid,
            "bid": q.get("bid"), "ask": q.get("ask"), "last": "",
            "quote_timestamp": ct_str(q.get("quote_time_ct")),
            "modeled_fill_mark": round(mark, 6) if mark is not None else "",
            "side": meta.get("side") or "buy", "instrument_id": uid,
            "mid": round((q["bid"] + q["ask"]) / 2, 4) if q.get("bid") and q.get("ask") else "",
            "bid_size": q.get("bid_size") or "", "ask_size": q.get("ask_size") or "",
            "volume": q.get("volume") if q.get("volume") is not None else "",
            "staleness_sec": round((rt - ts).total_seconds(), 1) if ts else "",
            "stop_or_exit_rule": meta.get("stop_or_exit_rule") or "",
            "alert": "; ".join(quote_problems(uid, q)),
        })
    new_file = not csv_path.is_file()
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)

    audit_path = quotes_dir / f"{rt.strftime('%Y-%m-%d_%H%M')}CT_audit.json"
    audit = {
        "run_at_ct": rt.isoformat(timespec="seconds"),
        "routine": routine,
        "source": "Robinhood get_equity_quotes and get_option_quotes, read-only. No trades, order "
                  "simulations, transfers or account changes.",
        "modeled_fill_mark": "closing side: longs at bid + (ask-bid)/3, shorts at ask - (ask-bid)/3",
        "rows_written": len(rows),
        "csv": str(csv_path),
        "equity": live_eq,
        "options": live_opt,
        "official_closes": closes,
    }
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    spy_path = quotes_dir / "spy_closes.csv"
    if BENCHMARK_SYMBOL in closes:
        upsert_closes(spy_path, {closes[BENCHMARK_SYMBOL]["date"]: closes[BENCHMARK_SYMBOL]["close"]},
                      source="Robinhood get_equity_quotes official close (read-only)")
    return {"csv": csv_path, "audit": audit_path, "spy": spy_path}


def load_closes(path: Path | None) -> dict[str, float]:
    if path is None or not Path(path).is_file():
        return {}
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return {r["date"]: float(r["close"]) for r in csv.DictReader(f) if r.get("date") and r.get("close")}


def upsert_closes(path: Path, closes: dict[str, float], source: str) -> None:
    path = Path(path)
    existing: dict[str, dict[str, str]] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8", newline="") as f:
            existing = {r["date"]: r for r in csv.DictReader(f)}
    for d, c in closes.items():
        existing[d] = {"date": d, "close": f"{c:.4f}".rstrip("0").rstrip("."), "source": source}
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "close", "source"])
        w.writeheader()
        for d in sorted(existing):
            w.writerow(existing[d])


def closes_from_historicals(raw: Any, symbol: str = BENCHMARK_SYMBOL) -> dict[str, float]:
    """Daily regular-session closes from a get_equity_historicals day-bar result."""
    out: dict[str, float] = {}
    for item in _results(raw):
        if str(item.get("symbol") or "").upper() != symbol:
            continue
        for bar in item.get("bars") or []:
            if bar.get("interpolated"):
                continue
            d = str(bar.get("begins_at") or "")[:10]
            c = _float(bar.get("close_price"))
            if d and c is not None:
                out[d] = c
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only scoreboard quote loader.")
    ap.add_argument("--book", type=Path, default=None)
    ap.add_argument("--quotes-dir", type=Path, default=COS_QUOTES_DIR)
    ap.add_argument("--saved-legs", type=Path, default=None, help="default: <quotes-dir>/saved_legs.csv")
    ap.add_argument("--equity-json", type=Path, default=None, help="saved get_equity_quotes result")
    ap.add_argument("--option-json", type=Path, default=None, help="saved get_option_quotes result")
    ap.add_argument("--spy-historicals-json", type=Path, default=None,
                    help="saved get_equity_historicals SPY day bars, to seed spy_closes.csv")
    ap.add_argument("--record", action="store_true", help="append the live read to the dated CSV + audit")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--read-time", default=None, help="ISO time the tools were called (default: now)")
    ap.add_argument("--list-requests", action="store_true")
    args = ap.parse_args(argv)

    book_path = resolve_book_path(args.book)
    if not book_path.is_file():
        print(f"ERROR: paper book not found: {book_path}", file=sys.stderr)
        return 1
    book = json.loads(book_path.read_text(encoding="utf-8"))
    saved = load_saved_legs(args.saved_legs or (args.quotes_dir / "saved_legs.csv"))
    if args.list_requests:
        print(json.dumps(build_mcp_requests(book, saved), indent=2))
        return 0

    now = parse_ct_timestamp(args.read_time) if args.read_time else datetime.now(CT)
    live_eq, live_opt, closes = parse_robinhood_payload(load_tool_json(args.equity_json), load_tool_json(args.option_json))
    if args.spy_historicals_json:
        seeded = closes_from_historicals(load_tool_json(args.spy_historicals_json))
        upsert_closes(args.quotes_dir / "spy_closes.csv", seeded,
                      source="Robinhood get_equity_historicals day bar close (read-only)")
        print(f"Seeded {len(seeded)} SPY closes into {args.quotes_dir / 'spy_closes.csv'}")
    if args.record and (live_eq or live_opt):
        paths = record_live_read(args.quotes_dir, live_eq, live_opt, closes, saved, now)
        print(f"Recorded live read: {paths['csv']} and {paths['audit']}")
    out = normalize_quotes(book, live_eq, live_opt, args.quotes_dir, now, saved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}: {len(out['equity'])} equity, {len(out['options'])} options")
    for n in out["notes"]:
        print(f"  NOTE {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
