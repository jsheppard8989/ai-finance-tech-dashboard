"""Dragonfly Cockpit v1 (plan section 12): a LOCAL, PRIVATE static HTML page.

    python3 -m dragonfly.cockpit [--state-dir DIR] [--handoff-dir DIR] [--inbox-dir DIR] [--out FILE]

Writes dragonfly/state/live/cockpit.html (gitignored). Never under site/, never
on Pages. Stdlib only, Python 3.9. No external CSS/JS/CDN: inline CSS, inline
SVG for the one chart.

Inputs (every one optional; a missing file renders as an empty state):
  state dir (default $DRAGONFLY_STATE_DIR or dragonfly/state/live):
    book.json                     engine_book.schema.json
    journal/*.json | journal.jsonl  journal_entry.schema.json, one per closed trade
    trades/*.json                 card-shaped trade records (versions, watcher)
    equity_history.json           optional [{"date", "equity"}] for month / YTD
    cache/bars/SPY.json           optional SPY bars (SPY beside the book)
  handoff date dir (default: latest YYYY-MM-DD under <private>/handoff):
    cards/*.json, cards/DONE, prep.json
    ../weekly/<friday>/weekly_review.json  (weekly_review.schema.json)
  inbox date dir (default: <private>/inbox/<same date>):
    drafts, *.redteam.json, market_read.json or regime_snapshot.json, brief*.json

Performance numbers are queries over the journal records only. Nothing is
estimated: a missing input shows a dash or "no closed trades yet".
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dragonfly import market_calendar as mc  # noqa: E402
from dragonfly import risk_math as rm  # noqa: E402

SEED_EQUITY = 100000.0  # plan section 2: paper book seed
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRADE_ID_RE = re.compile(r"^DF-\d{4}-\d{4}")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
R_BINS = ((None, -1.0, "< -1R"), (-1.0, -0.5, "-1 to -0.5"), (-0.5, 0.0, "-0.5 to 0"), (0.0, 0.5, "0 to 0.5"),
          (0.5, 1.0, "0.5 to 1"), (1.0, 2.0, "1 to 2"), (2.0, None, "> 2R"))
DASH = "\u2014"
REDTEAM_FLAGS = ("crowded_options", "sector_lagging", "wide_spread_but_legal", "contradictory_filing",
                 "valuation_extreme", "gap_history", "event_just_outside_window")


# ------------------------------------------------------------------ loading

def default_state_dir() -> Path:
    env = os.environ.get("DRAGONFLY_STATE_DIR")
    return Path(env) if env else ROOT / "dragonfly" / "state" / "live"


def default_private_dir() -> Path:
    return Path(os.environ.get("DRAGONFLY_PRIVATE_DIR") or Path.home() / "projects" / "dragonfly-private")


def latest_date_dir(root: Path) -> Optional[Path]:
    if not root.is_dir():
        return None
    dates = sorted(p for p in root.iterdir() if p.is_dir() and DATE_RE.match(p.name))
    return dates[-1] if dates else None


def read_json(path: Optional[Path], problems: List[str]) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        problems.append(f"{path}: unreadable ({exc})")
        return None


def load_journal(state: Path, problems: List[str]) -> List[dict]:
    out: List[dict] = []
    jdir = state / "journal"
    if jdir.is_dir():
        for p in sorted(jdir.glob("*.json")):
            obj = read_json(p, problems)
            if isinstance(obj, list):
                out.extend(x for x in obj if isinstance(x, dict))
            elif isinstance(obj, dict):
                out.append(obj)
    jl = state / "journal.jsonl"
    if jl.exists():
        for n, line in enumerate(jl.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    problems.append(f"{jl}:{n}: unreadable ({exc})")
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    good = []
    for e in out:
        if isinstance(e.get("r_multiple"), (int, float)) and isinstance(e.get("trade_id"), str):
            good.append(e)
        else:
            problems.append(f"journal entry without trade_id / r_multiple skipped: {str(e)[:80]}")
    return good


def load_cards_dir(cards_dir: Optional[Path], problems: List[str]) -> List[dict]:
    if cards_dir is None or not cards_dir.is_dir():
        return []
    out = []
    for p in sorted(cards_dir.glob("*.json")) + sorted((cards_dir / "unidentified").glob("*.json")):
        obj = read_json(p, problems)
        if isinstance(obj, dict):
            obj.setdefault("_file", str(p))
            out.append(obj)
    return out


def load_inputs(state_dir: Path, handoff_dir: Optional[Path], inbox_dir: Optional[Path],
                book_path: Optional[Path] = None) -> dict:
    problems: List[str] = []
    missing: List[str] = []

    def need(path: Optional[Path], label: str) -> Optional[Path]:
        if path is None or not path.exists():
            missing.append(f"{label}: {path if path else 'no folder found'}")
            return None
        return path

    book = read_json(need(book_path or state_dir / "book.json", "book.json"), problems)
    journal = load_journal(state_dir, problems)
    trades = []
    tdir = state_dir / "trades"
    if tdir.is_dir():
        for p in sorted(tdir.glob("*.json")):
            obj = read_json(p, problems)
            if isinstance(obj, dict):
                obj.setdefault("_file", str(p))
                trades.append(obj)
    equity_history = read_json(state_dir / "equity_history.json", problems)
    spy = read_json(state_dir / "cache" / "bars" / "SPY.json", problems)

    cards: List[dict] = []
    done = prep = None
    history_cards: List[dict] = []
    weekly = None
    session = None
    if need(handoff_dir, "handoff folder"):
        session = handoff_dir.name if DATE_RE.match(handoff_dir.name) else None
        cards = load_cards_dir(handoff_dir / "cards", problems)
        done = read_json(need(handoff_dir / "cards" / "DONE", "cards/DONE"), problems)
        prep = read_json(handoff_dir / "prep.json", problems)
        parent = handoff_dir.parent
        for sib in sorted(p for p in parent.iterdir() if p.is_dir() and DATE_RE.match(p.name) and p != handoff_dir):
            history_cards.extend(load_cards_dir(sib / "cards", problems))
        wdir = latest_date_dir(parent / "weekly")
        if wdir is not None:
            weekly = read_json(wdir / "weekly_review.json", problems)

    drafts: Dict[str, dict] = {}
    redteam: Dict[str, dict] = {}
    regime = regime_src = brief = market_read = None
    if need(inbox_dir, "inbox folder"):
        for p in sorted(inbox_dir.iterdir()):
            if not p.is_file() or not p.name.endswith(".json"):
                continue
            if p.name.endswith(".redteam.json"):
                obj = read_json(p, problems)
                if isinstance(obj, dict):
                    redteam[str(obj.get("trade_id") or p.name[: -len(".redteam.json")])] = obj
            elif p.name.endswith(".draft.json") or TRADE_ID_RE.match(p.name):
                obj = read_json(p, problems)
                if isinstance(obj, dict):
                    drafts[p.name] = obj
            elif p.name.startswith("brief") or p.name == "daily_brief.json":
                brief = read_json(p, problems)
        snap = read_json(inbox_dir / "regime_snapshot.json", problems)
        market_read = read_json(inbox_dir / "market_read.json", problems)
        if isinstance(snap, dict):
            regime, regime_src = snap, "regime_snapshot.json"
        elif isinstance(market_read, dict) and isinstance(market_read.get("regime"), dict):
            regime, regime_src = market_read["regime"], "market_read.json#regime"
        if session is None and DATE_RE.match(inbox_dir.name):
            session = inbox_dir.name
    return {"book": book if isinstance(book, dict) else None, "journal": journal, "trades": trades,
            "equity_history": equity_history if isinstance(equity_history, list) else None,
            "spy": spy if isinstance(spy, dict) else None, "cards": cards, "history_cards": history_cards,
            "done": done if isinstance(done, dict) else None, "prep": prep if isinstance(prep, dict) else None,
            "weekly": weekly if isinstance(weekly, dict) else None, "drafts": drafts, "redteam": redteam,
            "regime": regime, "regime_src": regime_src, "brief": brief if isinstance(brief, dict) else None,
            "market_read": market_read if isinstance(market_read, dict) else None,
            "session": session, "problems": problems, "missing": missing,
            "state_dir": str(state_dir), "handoff_dir": str(handoff_dir) if handoff_dir else None,
            "inbox_dir": str(inbox_dir) if inbox_dir else None}


# ------------------------------------------------------------------ journal queries

def _mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _entry_date(trade_id: str, cards_by_id: Dict[str, dict]) -> Optional[date]:
    c = cards_by_id.get(trade_id)
    try:
        return date.fromisoformat(c["time_stop"]["entry_session_date"]) if c else None
    except (KeyError, TypeError, ValueError):
        return None


def journal_stats(entries: Sequence[dict]) -> dict:
    """Pure queries over journal records. Empty -> n 0 and None everywhere."""
    rs = [float(e["r_multiple"]) for e in entries]
    wins = [e for e in entries if float(e["r_multiple"]) > 0]
    losses = [e for e in entries if float(e["r_multiple"]) <= 0]
    equity, peak, max_dd = SEED_EQUITY, SEED_EQUITY, 0.0
    for e in entries:
        equity += float(e.get("net_pnl") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

    def f(key, rows):
        return _mean([float(r[key]) for r in rows if isinstance(r.get(key), (int, float))])

    return {
        "n": len(entries),
        "win_rate": (len(wins) / len(entries)) if entries else None,
        "avg_win_r": _mean([float(e["r_multiple"]) for e in wins]),
        "avg_loss_r": _mean([float(e["r_multiple"]) for e in losses]),
        "avg_win_usd": f("net_pnl", wins),
        "avg_loss_usd": f("net_pnl", losses),
        "expectancy_r": _mean(rs),
        "r_sum": sum(rs) if rs else None,
        "net_pnl": sum(float(e.get("net_pnl") or 0) for e in entries) if entries else None,
        "max_drawdown_pct": max_dd if entries else None,
        "avg_hold": f("hold_sessions", entries),
        "avg_mae_r": f("mae_r", entries),
        "avg_mfe_r": f("mfe_r", entries),
        "avg_mae_r_winners": f("mae_r", wins),
        "avg_mfe_r_losers": f("mfe_r", losses),
        "r_hist": r_histogram(rs),
    }


def r_histogram(rs: Sequence[float]) -> List[Tuple[str, int]]:
    out = []
    for lo, hi, label in R_BINS:
        out.append((label, sum(1 for r in rs if (lo is None or r >= lo) and (hi is None or r < hi))))
    return out


def group_stats(entries: Sequence[dict], key_fn) -> List[Tuple[str, dict]]:
    groups: Dict[str, List[dict]] = {}
    for e in entries:
        groups.setdefault(key_fn(e), []).append(e)
    return [(k, journal_stats(v)) for k, v in sorted(groups.items())]


def spy_change(spy: Optional[dict], start: Optional[date], end: Optional[date]) -> Optional[float]:
    """SPY close-to-close % from the last bar at/before start to the last at/before end. None if unknown."""
    if not spy or start is None or end is None:
        return None
    bars = [b for b in spy.get("bars") or [] if isinstance(b, dict) and b.get("date") and b.get("close")]
    before = [b for b in bars if b["date"] <= start.isoformat()]
    upto = [b for b in bars if b["date"] <= end.isoformat()]
    if not before or not upto:
        return None
    a, b = float(before[-1]["close"]), float(upto[-1]["close"])
    return (b / a - 1) if a else None


def equity_change(history: Optional[list], equity: Optional[float], since: date) -> Optional[float]:
    if not history or equity is None:
        return None
    rows = sorted((r for r in history if isinstance(r, dict) and r.get("date") and r.get("equity")),
                  key=lambda r: r["date"])
    base = [r for r in rows if r["date"] < since.isoformat()]
    if not base:
        return None
    b = float(base[-1]["equity"])
    return equity / b - 1 if b else None


# ------------------------------------------------------------------ html helpers

def e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def pct(x: Optional[float], digits: int = 2) -> str:
    return DASH if x is None else f"{x * 100:+.{digits}f}%"


def num(x: Optional[float], fmt: str = "{:+.2f}") -> str:
    return DASH if x is None else fmt.format(x)


def usd(x: Optional[float]) -> str:
    if x is None:
        return DASH
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], empty: str, cls: str = "") -> str:
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def kv(pairs: Sequence[Tuple[str, str]]) -> str:
    return '<div class="kv">' + "".join(f'<div><span>{e(k)}</span><b>{v}</b></div>' for k, v in pairs) + "</div>"


def bar_svg(hist: Sequence[Tuple[str, int]]) -> str:
    total = sum(c for _, c in hist)
    if not total:
        return '<p class="empty">No closed trades yet</p>'
    w, h, pad = 560, 160, 24
    bw = (w - 2 * pad) / len(hist)
    top = max(c for _, c in hist)
    parts = [f'<svg class="chart" viewBox="0 0 {w} {h + 36}" width="{w}" height="{h + 36}" role="img" '
             f'aria-label="R distribution">']
    for i, (label, c) in enumerate(hist):
        bh = (h - pad) * c / top if top else 0
        x = pad + i * bw
        color = "#c0392b" if i < 3 else "#1e8449"
        parts.append(f'<rect x="{x + 4:.1f}" y="{h - bh:.1f}" width="{bw - 8:.1f}" height="{bh:.1f}" fill="{color}"/>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - bh - 4:.1f}" text-anchor="middle">{c}</text>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h + 16}" text-anchor="middle" class="lbl">{e(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def pill(text: str, kind: str) -> str:
    return f'<span class="pill {e(kind)}">{e(text)}</span>'


# ------------------------------------------------------------------ views

def today_mode(inp: dict) -> Tuple[Optional[str], str]:
    for c in inp["cards"]:
        rd = c.get("risk_decision") or {}
        if rd.get("risk_mode"):
            return rd["risk_mode"], "engine (card risk_decision)"
    r = inp["regime"]
    if isinstance(r, dict):
        try:
            return rm.regime_to_mode(r["trend"], r["risk_appetite"], r["volatility"], r["persistence"]), \
                "regime_to_mode() (no cards; breakers not applied)"
        except (KeyError, ValueError):
            pass
    return None, "no regime"


def applied_tier(card: dict, session_mode: Optional[str]) -> Tuple[Optional[str], Optional[float], str]:
    """(tier, name cap $, source) for the caps this card was actually sized under.

    risk_decision.risk_mode is the SESSION mode; two or more red team warnings
    pull a normal-mode card to the cautious caps. Source of truth, in order:
    engine.inputs.warnings_tightened (what the engine applied), else the
    card's sizing.name_heat_cap matched against caps(equity_at_decision, mode),
    else the session mode (fallback, labeled as such)."""
    rd = card.get("risk_decision") or {}
    mode = rd.get("risk_mode") or session_mode
    s = card.get("sizing") or {}
    cap = _f(s.get("name_heat_cap"))
    tightened = ((card.get("engine") or {}).get("inputs") or {}).get("warnings_tightened")
    if isinstance(tightened, bool) and mode:
        return (rm.CAUTIOUS if tightened and mode == rm.NORMAL else mode), cap, "engine warnings_tightened"
    eq = _f(s.get("equity_at_decision"))
    if cap is not None and eq:
        for tier in (rm.NORMAL, rm.CAUTIOUS, rm.STAND_DOWN):
            try:
                if abs(float(rm.caps(eq, tier)["name_heat_cap"]) - cap) < 0.005:
                    return tier, cap, "sizing.name_heat_cap"
            except ValueError:
                continue
    return mode, None, "session mode (card has no applied-cap field)"


def risk_label(card: dict, session_mode: Optional[str]) -> str:
    rd = card.get("risk_decision") or {}
    tier, cap, src = applied_tier(card, session_mode)
    decision = rd.get("decision", DASH)
    if cap is not None and src != "session mode (card has no applied-cap field)":
        return f"{decision} ({tier or DASH}, {usd(cap).replace('.00', '')} cap)"
    return f"{decision} ({tier or DASH}, session mode)"


def view_book(inp: dict, mode: Optional[str], as_of: date) -> str:
    b = inp["book"]
    if not b:
        return '<p class="empty">No book.json in the state folder yet.</p>'
    equity = float(b.get("equity") or 0)
    hist = inp["equity_history"]
    month = equity_change(hist, equity, as_of.replace(day=1))
    ytd = equity_change(hist, equity, date(as_of.year, 1, 1))
    heat = float(b.get("open_heat") or 0)
    cap = None
    try:
        cap = float(rm.caps(equity, mode or rm.NORMAL)["book_heat_cap"])
    except ValueError:
        pass
    used = (heat / cap) if cap else None
    bar = ""
    if cap:
        wpct = max(0.0, min(1.0, used or 0.0)) * 100
        bar = (f'<div class="heat"><div style="width:{wpct:.1f}%"></div></div>'
               f'<small>{usd(heat)} of {usd(cap)} book heat cap ({e(mode or rm.NORMAL)} mode)</small>')
    rows = []
    for p in b.get("positions") or []:
        r = None
        try:
            entry, stop = float(p["entry_price"]), float(p["stop"])
            mark = float(p.get("mark", p.get("last")))
            r = (mark - entry) / (entry - stop) if entry > stop else None
        except (KeyError, TypeError, ValueError):
            r = None
        days = DASH
        try:
            ed = date.fromisoformat(p["entry_session_date"])
            days = str(max(0, len(mc.sessions_between(ed, as_of)) - 1))
        except (KeyError, TypeError, ValueError, mc.CalendarNotCovered):
            pass
        rows.append([e(p.get("trade_id")), e(p.get("ticker")), e(p.get("setup")), e(p.get("instrument")),
                     usd(p.get("heat")), num(r, "{:+.2f}R"), days])
    return (kv([("Equity", usd(equity)), ("vs $100K seed", f"{usd(equity - SEED_EQUITY)} ({pct(equity / SEED_EQUITY - 1)})"),
                ("Day", pct(_f(b.get("day_pnl_pct")))), ("Week", pct(_f(b.get("week_pnl_pct")))),
                ("Month", pct(month)), ("YTD", pct(ytd)), ("Drawdown", pct(_f(b.get("drawdown_pct")))),
                ("Book as of", e(b.get("as_of")))])
            + bar
            + "<h3>Open trades</h3>"
            + table(["Trade", "Ticker", "Setup", "Instrument", "Heat", "Open R", "Sessions held"], rows,
                    "No open positions."))


def _f(x: Any) -> Optional[float]:
    """Book pct fields are fractions (0.01 = 1%)."""
    return float(x) if isinstance(x, (int, float)) else None


def funnel(inp: dict) -> List[Tuple[str, Optional[int]]]:
    prep, mr, done, brief = inp["prep"], inp["market_read"], inp["done"], inp["brief"]
    screened = len(prep["tickers"]) if prep and isinstance(prep.get("tickers"), list) else None
    flagged = None
    if brief and isinstance(brief.get("funnel"), dict):
        screened = brief["funnel"].get("universe", screened)
        flagged = brief["funnel"].get("unusual")
    elif mr and isinstance(mr.get("price_flow"), dict) and isinstance(mr["price_flow"].get("top15"), list):
        flagged = len(mr["price_flow"]["top15"])
    counts = (done or {}).get("counts") or {}
    drafted = len(inp["drafts"]) if inp["inbox_dir"] else None
    sized = counts.get("sized")
    rejected = counts.get("rejected")
    late = counts.get("late")
    if done is None and inp["cards"]:
        outs = [((c.get("engine") or {}).get("outcome")) for c in inp["cards"]]
        sized, rejected, late = outs.count("sized"), outs.count("rejected"), outs.count("late")
    skipped = len(done.get("skipped_files") or []) if done else None
    return [("Screened", screened), ("Flagged", flagged), ("Drafted", drafted), ("Sized", sized),
            ("Rejected", rejected), ("Late", late), ("Skipped files", skipped)]


def view_today(inp: dict, mode: Optional[str], mode_src: str) -> str:
    r = inp["regime"]
    regime = DASH
    if isinstance(r, dict):
        regime = " / ".join(e(r.get(k)) for k in ("trend", "risk_appetite", "volatility", "persistence"))
    pending = [c for c in inp["cards"] if c.get("status") == "pending_human" and not c.get("human_decision")]
    state = "REVIEW" if pending else "NO_TRADE"
    fun = "".join(f'<div class="step"><b>{DASH if v is None else v}</b><span>{e(k)}</span></div>' for k, v in funnel(inp))
    rows = []
    for c in pending:
        s = c.get("sizing") or {}
        ent = c.get("entry") or {}
        rows.append([e(c.get("trade_id")), e(c.get("ticker")), e(c.get("setup")), e(risk_label(c, mode)),
                     f'{e(ent.get("trigger"))} {num(_f(ent.get("price")), "{:.2f}")} (max {num(_f(ent.get("max_fill")), "{:.2f}")})',
                     num(_f(c.get("stop")), "{:.2f}"), e(s.get("units")), usd(s.get("planned_loss")),
                     usd(s.get("name_heat_cap")), e(", ".join((c.get("red_team") or {}).get("warnings") or []) or "none")])
    done = inp["done"]
    skipped = ""
    if done and done.get("skipped_files"):
        skipped = "<h3>Skipped inbox files</h3>" + table(
            ["File", "Reason"], [[e(x.get("file")), e(x.get("reason"))] for x in done["skipped_files"]], "")
    return (kv([("Session", e(inp["session"] or DASH)), ("Regime", regime),
                ("Regime source", e(inp["regime_src"] or DASH)), ("Mode", e(mode or DASH)),
                ("Mode from", e(mode_src)), ("State", pill(state, "review" if pending else "notrade")),
                ("DONE", e(f"r{done.get('revision')} {done.get('as_of')}") if done else "not yet")])
            + f'<div class="funnel">{fun}</div>'
            + "<h3>Cards waiting on Jared</h3>"
            + table(["Trade", "Ticker", "Setup", "Risk decision", "Entry", "Stop", "Units", "Planned loss", "Name cap", "Warnings"],
                    rows, "No cards waiting on Jared.")
            + skipped)


def view_trades(inp: dict, mode: Optional[str] = None) -> str:
    cards = inp["cards"]
    if not cards and not inp["trades"]:
        return '<p class="empty">No cards for this session.</p>'
    history: Dict[str, List[dict]] = {}
    for c in inp["history_cards"] + inp["trades"] + cards:
        if c.get("trade_id"):
            history.setdefault(c["trade_id"], []).append(c)
    current: Dict[str, dict] = {}
    for c in cards + inp["trades"]:
        tid = c.get("trade_id") or c.get("_file")
        if tid not in current or (c.get("version") or 0) >= (current[tid].get("version") or 0):
            current[tid] = c
    out = []
    for tid, c in sorted(current.items()):
        eng = c.get("engine") or {}
        rt = c.get("red_team") or {}
        s = c.get("sizing") or {}
        ent = c.get("entry") or {}
        rd = c.get("risk_decision") or {}
        rtf = inp["redteam"].get(str(tid)) or {}
        flags = rtf.get("flags") if isinstance(rtf.get("flags"), dict) else None
        flag_html = " ".join(pill(f, "on" if (flags or {}).get(f) or f in (rt.get("warnings") or []) else "off")
                             for f in REDTEAM_FLAGS)
        vers = sorted(history.get(str(tid), [c]), key=lambda x: (x.get("version") or 0, str(x.get("created_at"))))
        seen = set()
        vrows = []
        for v in vers:
            k = (v.get("version"), v.get("status"), v.get("created_at"))
            if k in seen:
                continue
            seen.add(k)
            vrows.append([e(v.get("version")), e(v.get("status")), e(v.get("created_at")), e(v.get("frozen_at")),
                          e(Path(v.get("_file", "")).parent.parent.name if v.get("_file") else DASH)])
        w = c.get("watcher")
        watcher = pill(str(w.get("state", w) if isinstance(w, dict) else w).upper(),
                       str(w.get("state") if isinstance(w, dict) else w).lower()) if w else "null (not active)"
        blocks = ", ".join(rt.get("hard_blocks") or []) or "none"
        out.append(
            f'<div class="card"><h3>{e(tid)} {e(c.get("ticker"))} <small>{e(c.get("setup"))} / '
            f'{e(c.get("instrument"))}</small> {pill(str(c.get("status")), str(c.get("status")))}</h3>'
            + kv([("Outcome", e(eng.get("outcome") or DASH)), ("Risk decision", e(risk_label(c, mode))),
                  ("Entry", f'{e(ent.get("trigger"))} {num(_f(ent.get("price")), "{:.2f}")} / max {num(_f(ent.get("max_fill")), "{:.2f}")}'),
                  ("Stop", num(_f(c.get("stop")), "{:.2f}")),
                  ("Target", e(", ".join(str(t.get("price")) for t in c.get("targets") or []) or DASH)),
                  ("Time stop", e((c.get("time_stop") or {}).get("exit_session_date") or DASH)),
                  ("Units", e(s.get("units", DASH))), ("Planned loss", usd(s.get("planned_loss"))),
                  ("Heat", usd(s.get("heat_contribution"))), ("Name cap", usd(s.get("name_heat_cap"))),
                  ("Expected R", num(_f(s.get("expected_r")), "{:.2f}")), ("Hard blocks", e(blocks)),
                  ("Watcher", watcher), ("Human decision", e(c.get("human_decision") or "null"))])
            + f'<p><b>Red team flags</b> ({e(len(rt.get("warnings") or []))} counted): {flag_html}</p>'
            + (f'<details><summary>Why now / red team narrative</summary><p>{e(c.get("why_now"))}</p>'
               f'<p><i>{e(rt.get("narrative"))}</i></p></details>')
            + "<h4>Version history</h4>"
            + table(["Version", "Status", "Created", "Frozen", "Folder"], vrows, "")
            + "</div>")
    return "".join(out)


def view_journal(inp: dict) -> str:
    j = inp["journal"]
    if not j:
        return '<p class="empty">No closed trades yet.</p>'
    out = []
    for x in j:
        out.append(
            f'<div class="card"><h3>{e(x.get("trade_id"))} {e(x.get("ticker"))} <small>{e(x.get("setup"))} / '
            f'{e(x.get("instrument"))}</small> {pill(num(_f(x.get("r_multiple")), "{:+.2f}R"), "win" if (x.get("r_multiple") or 0) > 0 else "loss")}</h3>'
            + kv([("Entry", e(x.get("entry_price"))), ("Stop", e(x.get("stop"))), ("Target", e(x.get("target"))),
                  ("Exit", f'{e(x.get("exit_price"))} ({e(x.get("exit_reason"))})'), ("Initial risk", usd(x.get("initial_risk"))),
                  ("Net P&L", usd(x.get("net_pnl"))), ("MAE / MFE", f'{num(_f(x.get("mae_r")), "{:+.2f}R")} / {num(_f(x.get("mfe_r")), "{:+.2f}R")}'),
                  ("Hold", f'{e(x.get("hold_sessions"))} sessions'), ("Regime at entry", e(x.get("regime_at_entry"))),
                  ("Fill", e(x.get("fill_type"))), ("Mistake", e(x.get("mistake"))), ("Would repeat", e(x.get("would_repeat")))])
            + "".join(f'<p><b>{e(lbl)}</b> {e(x.get(k))}</p>' for lbl, k in (
                ("Why entered:", "why_entered"), ("What happened:", "what_happened"), ("What was right:", "what_was_right"),
                ("What was wrong:", "what_was_wrong"), ("Lesson:", "lesson")))
            + "</div>")
    return "".join(out)


def stats_rows(groups: Sequence[Tuple[str, dict]]) -> List[List[str]]:
    return [[e(k), str(s["n"]), pct(s["win_rate"], 0), num(s["avg_win_r"], "{:+.2f}R"), num(s["avg_loss_r"], "{:+.2f}R"),
             num(s["expectancy_r"], "{:+.2f}R"), num(s["avg_hold"], "{:.1f}"), num(s["avg_mae_r"], "{:+.2f}R"),
             num(s["avg_mfe_r"], "{:+.2f}R")] for k, s in groups]


def view_performance(inp: dict, cards_by_id: Dict[str, dict], as_of: date) -> str:
    j = inp["journal"]
    s = journal_stats(j)
    dates = [d for d in (_entry_date(x["trade_id"], cards_by_id) for x in j) if d]
    start = min(dates) if dates else None
    book_ret = (float(inp["book"]["equity"]) / SEED_EQUITY - 1) if inp["book"] and j else None
    spy = spy_change(inp["spy"], start, as_of) if j else None
    head = kv([("Closed trades", str(s["n"]) if s["n"] else "no closed trades yet"), ("Win rate", pct(s["win_rate"], 0)),
               ("Average winner", f'{num(s["avg_win_r"], "{:+.2f}R")} / {usd(s["avg_win_usd"])}'),
               ("Average loser", f'{num(s["avg_loss_r"], "{:+.2f}R")} / {usd(s["avg_loss_usd"])}'),
               ("Expectancy", num(s["expectancy_r"], "{:+.3f}R")), ("Max drawdown (closed)", pct(s["max_drawdown_pct"])),
               ("Average hold", num(s["avg_hold"], "{:.1f} sessions")), ("Average MAE", num(s["avg_mae_r"], "{:+.2f}R")),
               ("Average MFE", num(s["avg_mfe_r"], "{:+.2f}R")),
               ("Book vs SPY (since first entry)", f"{pct(book_ret)} vs SPY {pct(spy)}")])
    hdr = ["Group", "n", "Win", "Avg win", "Avg loss", "Expectancy", "Avg hold", "MAE", "MFE"]
    if not j:
        by = ""
    else:
        wd = group_stats(j, lambda x: WEEKDAYS[_entry_date(x["trade_id"], cards_by_id).weekday()]
                         if _entry_date(x["trade_id"], cards_by_id) else "unknown")
        by = ("<h3>By setup</h3>" + table(hdr, stats_rows(group_stats(j, lambda x: str(x.get("setup")))), "")
              + "<h3>By regime at entry</h3>" + table(hdr, stats_rows(group_stats(j, lambda x: str(x.get("regime_at_entry")))), "")
              + "<h3>By entry weekday</h3>" + table(hdr, stats_rows(wd), "")
              + '<p class="note">Weekday comes from the card\'s entry_session_date (the journal has no date field); '
                "\"unknown\" when no card is on disk.</p>")
    return head + "<h3>R distribution</h3>" + bar_svg(s["r_hist"]) + by


def weekly_block(inp: dict, cards_by_id: Dict[str, dict], as_of: date) -> str:
    """Section 11 scoreboard: trades, sum of R, expectancy, net $ and %. No target-gap field."""
    w = inp["weekly"]
    if w and isinstance(w.get("scoreboard"), dict):
        sb, label = w["scoreboard"], f'weekly_review.json, week ending {w.get("week_ending", DASH)}'
    else:
        monday = as_of - timedelta(days=as_of.weekday())
        rows = [x for x in inp["journal"] if (_entry_date(x["trade_id"], cards_by_id) or date.min) >= monday]
        b = rm.weekly_scoreboard([x["r_multiple"] for x in rows],
                                 (inp["book"] or {}).get("equity") or SEED_EQUITY,
                                 sum(float(x.get("net_pnl") or 0) for x in rows))
        sb = {k: (float(v) if v is not None and not isinstance(v, bool) else v) for k, v in b.items()}
        label = f"weekly_scoreboard() over journal entries entered since {monday.isoformat()}"
    n = sb.get("trades") or 0
    return (kv([("Trades", str(n)), ("Sum of R", num(_f(sb.get("r_sum")), "{:+.2f}R") if n else DASH),
                ("Expectancy", num(_f(sb.get("expectancy_r")), "{:+.3f}R") if n else DASH),
                ("Net", usd(_f(sb.get("net_pnl"))) if n else DASH),
                ("Net %", pct(_f(sb.get("net_pnl_pct"))) if n else DASH)])
            + f'<p class="note">Source: {e(label)}. R is the score; a flat week is a success.</p>')


CSS = """
body{font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f4f5f7;color:#1c1f24}
header{background:#111827;color:#fff;padding:14px 24px;position:sticky;top:0;z-index:2}
header h1{margin:0;font-size:18px} header small{color:#9ca3af}
nav a{color:#93c5fd;margin-right:14px;text-decoration:none;font-weight:600}
main{padding:12px 24px 40px;max-width:1200px}
section{background:#fff;border-radius:8px;padding:12px 18px;margin:14px 0;box-shadow:0 1px 2px rgba(0,0,0,.08)}
section>h2{margin:4px 0 10px;font-size:17px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}
h3{font-size:15px;margin:14px 0 6px} h4{margin:10px 0 4px;font-size:13px}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:6px 14px}
.kv div{display:flex;flex-direction:column;background:#f9fafb;border-radius:6px;padding:6px 8px}
.kv span{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.03em}
table{border-collapse:collapse;width:100%;margin:4px 0;font-size:13px}
th,td{border-bottom:1px solid #eef0f3;padding:4px 6px;text-align:left} th{background:#f3f4f6}
.empty{color:#6b7280;font-style:italic} .note{color:#6b7280;font-size:12px}
.heat{height:10px;background:#e5e7eb;border-radius:5px;overflow:hidden;margin:10px 0 2px;max-width:420px}
.heat div{height:100%;background:#f59e0b}
.funnel{display:flex;gap:6px;margin:12px 0;flex-wrap:wrap}
.step{background:#eef2ff;border-radius:6px;padding:6px 12px;text-align:center;min-width:80px}
.step b{display:block;font-size:20px} .step span{font-size:11px;color:#4b5563}
.card{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;margin:10px 0}
.pill{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;margin:1px;background:#e5e7eb;color:#374151}
.pill.on,.pill.red,.pill.loss,.pill.blocked,.pill.risk_rejected{background:#fee2e2;color:#991b1b}
.pill.off{background:#f3f4f6;color:#9ca3af} .pill.review,.pill.pending_human,.pill.yellow{background:#fef3c7;color:#92400e}
.pill.notrade{background:#e0e7ff;color:#3730a3} .pill.win,.pill.green,.pill.active,.pill.approved{background:#dcfce7;color:#166534}
.chart text{font-size:11px;fill:#374151} .chart .lbl{font-size:10px;fill:#6b7280}
details{margin:6px 0} summary{cursor:pointer;color:#2563eb}
.problems{background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;padding:6px 10px;font-size:12px}
"""


def render(inp: dict, generated_at: Optional[datetime] = None) -> str:
    generated_at = generated_at or datetime.now().astimezone()
    try:
        as_of = date.fromisoformat(inp["session"]) if inp["session"] else generated_at.date()
    except ValueError:
        as_of = generated_at.date()
    mode, mode_src = today_mode(inp)
    cards_by_id: Dict[str, dict] = {}
    for c in inp["history_cards"] + inp["trades"] + inp["cards"]:
        if c.get("trade_id"):
            cards_by_id[c["trade_id"]] = c
    sections = [
        ("book", "Book", view_book(inp, mode, as_of)),
        ("today", "Today", view_today(inp, mode, mode_src)),
        ("trade", "Trade", view_trades(inp, mode)),
        ("journal", "Journal", view_journal(inp)),
        ("performance", "Performance", view_performance(inp, cards_by_id, as_of)),
        ("weekly", "Weekly scoreboard", weekly_block(inp, cards_by_id, as_of)),
    ]
    nav = "".join(f'<a href="#{k}">{e(t)}</a>' for k, t, _ in sections)
    body = "".join(f'<section id="{k}"><h2>{e(t)}</h2>{c}</section>' for k, t, c in sections)
    notes = inp["missing"] + inp["problems"]
    probs = ""
    if notes:
        probs = ('<div class="problems"><b>Missing or unreadable inputs</b> (shown as empty states):<ul>'
                 + "".join(f"<li>{e(n)}</li>" for n in notes) + "</ul></div>")
    src = f'state {inp["state_dir"]} · handoff {inp["handoff_dir"] or DASH} · inbox {inp["inbox_dir"] or DASH}'
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>Dragonfly Cockpit</title>"
            f"<style>{CSS}</style></head><body><header><h1>Dragonfly Cockpit "
            f"<small>session {e(inp['session'] or DASH)} · generated {e(generated_at.replace(microsecond=0).isoformat())}"
            f" · local and private</small></h1><nav>{nav}</nav></header><main>{probs}"
            f'<p class="note">{e(src)}</p>{body}</main></body></html>')


# ------------------------------------------------------------------ entry points

def resolve_dirs(handoff_dir: Optional[Path], inbox_dir: Optional[Path], private_dir: Optional[Path] = None,
                 handoff_root: str = "handoff", inbox_root: str = "inbox") -> Tuple[Optional[Path], Optional[Path]]:
    priv = private_dir or default_private_dir()
    if handoff_dir is None:
        if inbox_dir is not None and DATE_RE.match(inbox_dir.name):
            handoff_dir = priv / handoff_root / inbox_dir.name
        else:
            handoff_dir = latest_date_dir(priv / handoff_root)
    if inbox_dir is None and handoff_dir is not None:
        inbox_dir = priv / inbox_root / handoff_dir.name
    return handoff_dir, inbox_dir


def generate(out: Path, state_dir: Optional[Path] = None, handoff_dir: Optional[Path] = None,
             inbox_dir: Optional[Path] = None, generated_at: Optional[datetime] = None,
             book_path: Optional[Path] = None) -> Path:
    if "site" in out.resolve().parts:
        raise ValueError(f"refusing to write the cockpit under site/: {out}")
    inp = load_inputs(state_dir or default_state_dir(), handoff_dir, inbox_dir, book_path)
    text = render(inp, generated_at)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(out))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m dragonfly.cockpit", description=__doc__.split("\n\n")[0])
    ap.add_argument("--state-dir", type=Path, default=None, help="default $DRAGONFLY_STATE_DIR or dragonfly/state/live")
    ap.add_argument("--private-dir", type=Path, default=None, help="dragonfly-private clone (default $DRAGONFLY_PRIVATE_DIR or ~/projects/dragonfly-private)")
    ap.add_argument("--handoff-root", default="handoff", help="handoff folder name for the default date (e.g. handoff-replay)")
    ap.add_argument("--inbox-root", default="inbox", help="inbox folder name for the default date")
    ap.add_argument("--handoff-dir", type=Path, default=None, help="a handoff date folder (default: latest date under the handoff root)")
    ap.add_argument("--inbox-dir", type=Path, default=None, help="an inbox date folder (default: same date under the inbox root)")
    ap.add_argument("--book", type=Path, default=None, help="book.json (default <state-dir>/book.json)")
    ap.add_argument("--out", type=Path, default=None, help="default <state-dir>/cockpit.html")
    args = ap.parse_args(argv)
    state = args.state_dir or default_state_dir()
    h, i = resolve_dirs(args.handoff_dir, args.inbox_dir, args.private_dir, args.handoff_root, args.inbox_root)
    try:
        out = generate(args.out or state / "cockpit.html", state, h, i, book_path=args.book)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
