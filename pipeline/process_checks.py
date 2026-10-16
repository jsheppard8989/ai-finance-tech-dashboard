#!/usr/bin/env python3
"""
Red Team process fixes (cw-process-critique-2026-10-13, Fixes 1-5; Jared yes 2026-10-16), wired into
publish_guard.run_publish_guard. All warn + log, except the FACT gate (Fix 5), which BLOCKS publish from
FACT_GATE_BLOCK_FROM. Log lines: "WARN publish guard process: ..." on stdout, plus one JSON line per run in
$PUBLISH_GUARD_LOG_DIR (default ~/.cache/publish_guard)/process-<date>.jsonl. Nothing here writes to site/.

  (a) check_wrong_if    Fix 1. Every wrong-if / falsifier line (trap-map.html "What would prove us wrong" +
                        span.wrong, trap_map.json drop_if / relegate_if / decisive_test, data.js
                        deepDives[].falsification_tracks) needs (i) a date or "by <date>", (ii) a number other
                        than the date, (iii) a named source (URL or a known source word). Trap-map cards may
                        take the source from their own "Date source" row. Scoped to items published on/after
                        WRONG_IF_SCOPE_FROM (2026-10-19; card data-published attr, trap updated_at, deep dive
                        created_at); older lines are a backlog number printed as INFO only. Warn.
  (b) check_derived     Fix 2. site/data/derived_figures.json (total <- parts; G maintains it). Recompute every
                        total from its parts; flag mismatches beyond tolerance, and a total_text that is no longer
                        on the site. Warn.
  (c) ungraded_items    Fix 3. Items dated before today with no outcome field (see ungraded_sweep.py, which
                        writes /workspace/cos/ungraded_guard_<date>.md daily). Count surfaced here. Warn.
  (d) check_fact_gate   Fix 5. An item labeled FACT (whole-word, upper case: "FACT:", "[FACT]", "label": "FACT")
                        with no http(s) URL fails unless it is written as PENDING with an owner and a due time
                        ("PENDING owner: X due: <time>"). BLOCKS from FACT_GATE_BLOCK_FROM.
  (e) check_stale       Fix 4. Tickets (tickets.json, see TICKETS_SCHEMA; missing file = INFO skip), trap cards
                        and portfolio.json positions: STALE when exit/exit_date/expiry is missing past 7 days
                        (tickets) / 21 days (cards), or expiry has passed while not closed. Report-only. Warn.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

WARN = "WARN publish guard process"
INFO = "INFO publish guard process"
# Measured 2026-10-16: 0 FACT-without-URL items on the live site, so the gate blocks from today.
# If live data ever needs a grace period, move this date (same pattern as CONTRACT_AGE_BLOCK_FROM).
FACT_GATE_BLOCK_FROM = date(2026, 10, 16)
# Wrong-if lint counts only items published on/after this date; older lines are a backlog number (info only).
WRONG_IF_SCOPE_FROM = date(2026, 10, 19)
TICKET_STALE_DAYS = 7
CARD_STALE_DAYS = 21
DERIVED_MAP = "derived_figures.json"

_MON = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?"
        r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b\.?")
DATE_RE = re.compile(
    r"(?i)\b(?:\d{4}-\d{2}-\d{2}"
    r"|" + _MON + r"\s+\d{1,2}(?:\s*[-\u2013]\s*\d{1,2})?(?:,?\s+\d{4})?"
    r"|\d{1,2}\s+" + _MON + r"(?:\s+\d{4})?"
    r"|" + _MON + r"\s+\d{4}"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|Q[1-4]\s*(?:FY)?\s*'?\d{2,4}|(?:FY|CY)\s*'?\d{2,4}|H[12]\s+\d{4}"
    r"|(?:end|mid|early|late)[- ](?:of[- ])?(?:20\d{2}|" + _MON + r"))\b")
NUM_RE = re.compile(r"[$\u20ac\u00a3]?\d[\d,]*(?:\.\d+)?\s*(?:%|x|bp|bps|[KMBT]\b|GW|MW|GWh|MWh|points?|pts)?", re.I)
URL_RE = re.compile(r"https?://\S+")
SOURCE_WORDS = re.compile(
    r"(?i)\b(SEC|EDGAR|10-?Q|10-?K|8-?K|20-?F|6-?K|S-1|424B\d?|proxy|filing|filed|docket|FERC|PJM|ERCOT|EIA|STEO|"
    r"BLS|BEA|FOMC|Fed\b|Treasury|CFTC|COT|IMF|OPEC|IEA|earnings|results|release|report|transcript|prospectus|"
    r"guidance|call|tariff|order|PUC|PUR-\d|Nasdaq|NYSE|S&P|Bloomberg|Reuters|WSJ|FT\b|CNBC|press release|"
    r"investor (?:day|presentation)|shareholder letter|annual report|survey|index|data|Research|Census|Bureau|Commission|"
    r"Agency|Institute|Association|IDC|Gartner|TrendForce|SEMI|SIA|10-?Q filings?|filings|Exchange|customs|statistics|Clarksons)\b")
FACT_RE = re.compile(r"(?:\[FACT\]|\bFACT\b\s*[:\-\u2014]|\"(?:label|tag|kind|type|claim_type)\"\s*:\s*\"FACT\"|^FACT\b)")
PENDING_OK_RE = re.compile(r"(?is)\bPENDING\b.*\bowner\b\s*[:=]?\s*\S+.*\bdue\b\s*[:=]?\s*\S+")
TAG_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def _today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        return date.today()


def _data_js(site: Path) -> dict:
    p = site / "data" / "data.js"
    if not p.exists():
        return {}
    try:
        from publish_guard import parse_data_js
        return parse_data_js(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- (a) wrong-if lint
def lint_line(text: str, extra_source: str = "") -> list[str]:
    """Return the missing parts of one wrong-if line: subset of ['date', 'number', 'source']."""
    t = _text(text)
    miss = []
    dates = list(DATE_RE.finditer(t))
    if not dates:
        miss.append("date")
    rest = SOURCE_WORDS.sub(" ", DATE_RE.sub(" ", t))
    if not NUM_RE.search(rest) or not re.search(r"\d", rest):
        miss.append("number")
    if not (URL_RE.search(text) or SOURCE_WORDS.search(t) or SOURCE_WORDS.search(_text(extra_source))
            or URL_RE.search(extra_source or "")):
        miss.append("source")
    return miss


def _iso(v) -> date | None:
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})", str(v or ""))
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError:
        return None


def wrong_if_lines(site: Path) -> list[tuple]:
    """(where, line, extra_source, published) for every wrong-if / falsifier line on the public site.
    published: trap-map card data-published="YYYY-MM-DD" attr; trap_map.json published_at/created_at/updated_at;
    deep dive created_at. None = unknown -> backlog."""
    out = []
    p = site / "trap-map.html"
    if p.exists():
        page = p.read_text(encoding="utf-8")
        for card in re.findall(r"<details\b[^>]*\bclass=\"ev\"[^>]*>.*?</details>", page, re.S):
            cid = (re.search(r"\bid=\"([^\"]+)\"", card) or [None, "?"])[1]
            pub = re.search(r"<details\b[^>]*\bdata-published=\"([^\"]+)\"", card)
            src = re.search(r"<dt>\s*Date source\s*</dt>\s*<dd>(.*?)</dd>", card, re.S)
            src = src.group(1) if src else ""
            m = re.search(r"<dt>\s*What would prove us wrong\s*</dt>\s*<dd>(.*?)</dd>", card, re.S)
            if m:
                out.append((f"trap-map.html#{cid} prove-us-wrong", m.group(1), src, _iso(pub.group(1) if pub else None)))
    tm = _json(site / "data" / "trap_map.json") or {}
    for tr in tm.get("traps") or []:
        srcs = " ".join(str(s) for s in tr.get("sources") or [])
        pub = _iso(tr.get("published_at") or tr.get("created_at") or tr.get("updated_at"))
        for k in ("drop_if", "relegate_if", "decisive_test"):
            if str(tr.get(k) or "").strip():
                out.append((f"trap_map.json {tr.get('id')}.{k}", str(tr[k]), srcs, pub))
    d = _data_js(site)
    dds = d.get("deepDives") or []
    for i, dd in (dds.items() if isinstance(dds, dict) else enumerate(dds)):
        pub = _iso((dd or {}).get("created_at"))
        for j, line in enumerate((dd or {}).get("falsification_tracks") or []):
            if isinstance(line, dict):
                line = " ".join(str(v) for v in line.values() if isinstance(v, str))
            if str(line).strip():
                out.append((f"data.js deepDives[{i}].falsification_tracks[{j}]", str(line), "", pub))
    return out


def _summ(rows):
    n, fails = len(rows), [r for r in rows if r["missing"]]
    by = {}
    for r in rows:
        s = r["where"].split(" ")[0].split("#")[0]
        b = by.setdefault(s, {"lines": 0, "failures": 0})
        b["lines"] += 1
        b["failures"] += bool(r["missing"])
    for b in by.values():
        b["pct_compliant"] = round(100.0 * (b["lines"] - b["failures"]) / b["lines"], 1)
    return {"lines": n, "failures": len(fails),
            "pct_compliant": None if n == 0 else round(100.0 * (n - len(fails)) / n, 1),
            "by_surface": by,
            "fail_list": [{"where": r["where"], "missing": r["missing"], "line": r["line"]} for r in fails]}


def check_wrong_if(site: Path, scope_from: date = None) -> dict:
    """In-scope = published on/after scope_from (WRONG_IF_SCOPE_FROM). Backlog = everything else (info only).
    pct_compliant None = N/A (no in-scope lines yet)."""
    scope_from = scope_from or WRONG_IF_SCOPE_FROM
    rows = [{"where": w, "line": _text(l)[:160], "missing": lint_line(l, x), "published": pub}
            for w, l, x, pub in wrong_if_lines(site)]
    inscope = [r for r in rows if r["published"] and r["published"] >= scope_from]
    backlog = [r for r in rows if not (r["published"] and r["published"] >= scope_from)]
    rep = _summ(inscope)
    rep["scope_from"] = scope_from.isoformat()
    b = _summ(backlog)
    rep["backlog"] = {k: b[k] for k in ("lines", "failures", "pct_compliant", "by_surface")}
    return rep


# ---------------------------------------------------------------- (b) derived figures
DERIVED_TEMPLATE = {
    "_schema_version": 1,
    "_comment": ("Derived-figure map (Red Team Fix 2, 2026-10-16). G maintains this file. Each figure is a total "
                 "built from parts. publish_guard recomputes every total from its parts on publish and warns on a "
                 "mismatch (warn only). When you edit a part anywhere on the site, edit it here too and re-check "
                 "the totals it feeds."),
    "_field_definitions": {
        "id": "stable slug",
        "total": "the number the site shows for the total (in `unit`)",
        "op": "sum (default) | product | diff (parts[0] - rest) | ratio (parts[0] / parts[1])",
        "parts": "list of {label, value} in the same unit; value may also be the id of another figure",
        "unit": "free text, e.g. 'M shares' or '$B'",
        "tolerance": "absolute slack for rounding (default 0.5% of total)",
        "total_text": "optional: exact text the site shows for the total (e.g. 'about 2.43B shares'); warns if it "
                      "is no longer found on the site, so a stale copy elsewhere gets noticed",
        "where": "optional: files/cards that show the total",
    },
    "_example": {
        "id": "spacex-l1-unlock-shares",
        "total": 2426.0, "unit": "M shares", "op": "sum", "tolerance": 5,
        "parts": [{"label": "tranche A", "value": 328.4}, {"label": "tranche B", "value": 1300.0},
                  {"label": "tranche C", "value": 797.6}],
        "total_text": "about 2.43B shares", "where": ["trap-map.html#spacex"],
    },
    "figures": [],
}


def _eval_fig(fig: dict, figs: dict, seen=()) -> float | None:
    vals = []
    for part in fig.get("parts") or []:
        v = part.get("value") if isinstance(part, dict) else part
        if isinstance(v, str) and v in figs and v not in seen:
            v = _eval_fig(figs[v], figs, seen + (v,))
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            return None
    if not vals:
        return None
    op = (fig.get("op") or "sum").lower()
    if op == "sum":
        return sum(vals)
    if op == "product":
        r = 1.0
        for v in vals:
            r *= v
        return r
    if op == "diff":
        return vals[0] - sum(vals[1:])
    if op == "ratio" and len(vals) == 2 and vals[1]:
        return vals[0] / vals[1]
    return None


def check_derived(site: Path, site_text: str | None = None) -> dict:
    p = site / "data" / DERIVED_MAP
    if not p.exists():
        return {"map": str(p), "present": False, "figures": 0, "mismatches": []}
    doc = _json(p)
    if not isinstance(doc, dict):
        return {"map": str(p), "present": True, "figures": 0, "mismatches": [{"id": None, "problem": "map unreadable"}]}
    figs = {f.get("id"): f for f in doc.get("figures") or [] if isinstance(f, dict)}
    if site_text is None:
        site_text = " ".join(_text(q.read_text(encoding="utf-8", errors="replace"))
                             for q in list(site.glob("*.html")) + [site / "data" / "data.js"] if q.exists())
    mm = []
    for fid, f in figs.items():
        calc = _eval_fig(f, figs, (fid,))
        try:
            total = float(f.get("total"))
        except (TypeError, ValueError):
            mm.append({"id": fid, "problem": "total missing or not a number"}); continue
        if calc is None:
            mm.append({"id": fid, "problem": "parts missing or not numbers"}); continue
        tol = float(f.get("tolerance") if f.get("tolerance") is not None else abs(total) * 0.005)
        if abs(calc - total) > tol:
            mm.append({"id": fid, "problem": f"total {total:g} {f.get('unit', '')} != recomputed {calc:g} (tolerance {tol:g})"})
        tt = f.get("total_text")
        if tt and _text(tt) not in site_text:
            mm.append({"id": fid, "problem": f"total_text {tt!r} not found on the site (edited without updating the map?)"})
    return {"map": str(p), "present": True, "figures": len(figs), "mismatches": mm}


# ---------------------------------------------------------------- (c) ungraded items
OUTCOME_KEYS = ("outcome", "result", "graded", "resolution", "resolution_status", "resolved_at")
DATE_KEYS = ("expected_date", "event_date", "deadline", "due", "date", "friday_iso")


def parse_date(s, today: date) -> date | None:
    """ISO date, or 'Mon DD[, YYYY]' / 'Wed Oct 21' (year = nearest to today). Ranges use the first day."""
    if not s:
        return None
    s = str(s)
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.search(r"(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?!\d)(?:\s*[-\u2013]\s*\d{1,2})?(?:,?\s+(20\d{2}))?", s)
    if not m:
        return None
    mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m[1][:3].lower()) + 1
    try:
        if m[3]:
            return date(int(m[3]), mon, int(m[2]))
        d = date(today.year, mon, int(m[2]))
        if d > today + timedelta(days=183):
            d = date(today.year - 1, mon, int(m[2]))
        elif d < today - timedelta(days=183):
            d = date(today.year + 1, mon, int(m[2]))
        return d
    except ValueError:
        return None


def ungraded_items(site: Path, today: date | None = None) -> list[dict]:
    today = today or _today()
    out = []
    p = site / "trap-map.html"
    if p.exists():
        for card in re.findall(r"<details\b[^>]*\bclass=\"ev\"[^>]*>.*?</details>", p.read_text(encoding="utf-8"), re.S):
            cid = (re.search(r"\bid=\"([^\"]+)\"", card) or [None, "?"])[1]
            dl = re.search(r"<span class=\"date\">(.*?)</span>", card, re.S)
            d = parse_date(_text(dl.group(1)) if dl else "", today)
            graded = re.search(r"(?i)<dt>\s*(Outcome|Result|Graded|Scored)\b|class=\"[^\"]*\boutcome\b", card)
            if d and d < today and not graded:
                out.append({"where": f"trap-map.html#{cid}", "date": d.isoformat(), "what": _text(dl.group(1)),
                            "missing": "Outcome row"})
    home = _json(site / "data" / "trap_map_home.json") or {}
    for w in home.get("upcoming_watches") or []:
        d = parse_date(w.get("date_iso") or w.get("date_label"), today)
        if d and d < today and not any(str(w.get(k) or "").strip() for k in OUTCOME_KEYS):
            out.append({"where": f"trap_map_home.json upcoming_watches {w.get('trap_id')}", "date": d.isoformat(),
                        "what": w.get("what"), "missing": "outcome"})
    tm = _json(site / "data" / "trap_map.json") or {}
    for tr in tm.get("traps") or []:
        nd = tr.get("next_datapoint") or {}
        d = parse_date(nd.get("expected_date") if isinstance(nd, dict) else None, today)
        if d and d < today and not any(str(tr.get(k) or "").strip() for k in OUTCOME_KEYS) \
                and not (isinstance(nd, dict) and any(str(nd.get(k) or "").strip() for k in OUTCOME_KEYS)):
            out.append({"where": f"trap_map.json {tr.get('id')}.next_datapoint", "date": d.isoformat(),
                        "what": (nd.get("label") or "")[:120], "missing": "outcome"})
    return out


# ---------------------------------------------------------------- (d) FACT gate
def _fact_units(site: Path):
    """(where, text) units that may carry a FACT label: every JSON string / dict (direct string values) in
    data.js + data/*.json, and every block element (li, dd, p, td, div) of the public html pages."""
    def walk(o, path):
        if isinstance(o, dict):
            direct = " ".join(f"\"{k}\": \"{v}\"" for k, v in o.items() if isinstance(v, str))
            if FACT_RE.search(direct):
                yield path, direct
            for k, v in o.items():
                if not isinstance(v, str):
                    yield from walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, str):
                    if FACT_RE.search(v):
                        yield f"{path}[{i}]", v
                else:
                    yield from walk(v, f"{path}[{i}]")
    d = _data_js(site)
    if d:
        yield from walk(d, "data.js")
    for p in sorted((site / "data").glob("*.json")):
        j = _json(p)
        if j is not None:
            yield from walk(j, p.name)
    for p in sorted(site.glob("*.html")):
        page = TAG_RE.sub(lambda m: m.group(0) if not m.group(1) else " ", p.read_text(encoding="utf-8", errors="replace"))
        for m in re.finditer(r"<(li|dd|p|td|div)\b[^>]*>(.*?)</\1>", page, re.S | re.I):
            if FACT_RE.search(_text(m.group(2))) or "[FACT]" in m.group(2):
                yield f"{p.name}", m.group(2)


def check_fact_gate(site: Path) -> list[dict]:
    bad = []
    for where, text in _fact_units(site):
        if URL_RE.search(text) or re.search(r"href=\"https?://", text):
            continue
        if PENDING_OK_RE.search(_text(text)):
            continue
        bad.append({"where": where, "text": _text(text)[:160]})
    return bad


# ---------------------------------------------------------------- (e) STALE
EXIT_KEYS = ("exit", "exit_date", "expiry")
CLOSED_STATUSES = {"closed", "exited", "graded", "done", "resolved", "cancelled", "canceled", "expired_graded"}
# tickets.json: first existing of $TICKETS_JSON, site/data/tickets.json, site/data/*ticket*.json, /workspace/cos/tickets.json
TICKETS_BOX_PATH = Path("/workspace/cos/tickets.json")
TICKETS_SCHEMA = {
    "file": "{\"_metadata\": {...}, \"tickets\": [ticket, ...]}  (a bare list of tickets is also accepted)",
    "ticket": {
        "id": "required, stable slug (falls back to ticker_or_name / ticker)",
        "created": "ISO date the ticket was opened (fallbacks: as_of, date); age is counted from it",
        "exit": "price or condition that closes it (string), null until set",
        "exit_date": "ISO date the exit is graded",
        "expiry": "ISO date; default created + 7 days for tickets",
        "status": "OPEN | WATCH | STALE | CLOSED/EXITED/GRADED/DONE/RESOLVED (closed ones are skipped)",
    },
    "rule": "STALE when (a) any of exit/exit_date/expiry is missing and the ticket is older than 7 days, or "
            "(b) expiry is before today and status is not closed. Report-only: the guard never rewrites the file.",
}


def _ticket_files(site: Path) -> list[Path]:
    env = os.environ.get("TICKETS_JSON")
    cands = ([Path(env)] if env else []) + [site / "data" / "tickets.json"] + sorted((site / "data").glob("*ticket*.json")) \
        + [TICKETS_BOX_PATH]
    seen, out = set(), []
    for c in cands:
        if c.is_file() and c.resolve() not in seen:
            seen.add(c.resolve()); out.append(c)
    return out


def _stale_reason(item: dict, created: date | None, max_days: int, today: date) -> tuple[str | None, int | None]:
    if str(item.get("status") or "").strip().lower() in CLOSED_STATUSES:
        return None, None
    age = (today - created).days if created else None
    missing = [k for k in EXIT_KEYS if not str(item.get(k) or "").strip()]
    exp = _iso(item.get("expiry"))
    if exp and exp < today:
        return f"expired {exp.isoformat()}", age
    if missing and age is not None and age > max_days:
        return "no " + "/".join(missing), age
    return None, age


def check_stale(site: Path, today: date | None = None) -> list[dict]:
    today = today or _today()
    out, info = [], []
    tm = _json(site / "data" / "trap_map.json") or {}
    for tr in tm.get("traps") or []:
        why, age = _stale_reason(tr, parse_date(tr.get("updated_at") or tm.get("as_of"), today), CARD_STALE_DAYS, today)
        if why:
            out.append({"where": f"trap_map.json {tr.get('id')}", "kind": "card", "label": "STALE", "age_days": age, "why": why,
                        "missing": [k for k in EXIT_KEYS if not tr.get(k)]})
    pf = _json(site / "data" / "portfolio.json") or {}
    for b in pf.get("baskets") or []:
        created = _iso(b.get("as_of"))
        for n in b.get("names") or []:
            why, age = _stale_reason(n, created, CARD_STALE_DAYS, today)
            if why:
                out.append({"where": f"portfolio.json {b.get('id')}/{n.get('ticker')}", "kind": "card", "label": "STALE",
                            "age_days": age, "why": why, "missing": [k for k in EXIT_KEYS if not n.get(k)]})
    files = _ticket_files(site)
    if not files:
        info.append("tickets.json not found (TICKETS_JSON, site/data/tickets.json, site/data/*ticket*.json, "
                    f"{TICKETS_BOX_PATH}); ticket STALE check skipped")
    for p in files:
        j = _json(p)
        tickets = j if isinstance(j, list) else (j or {}).get("tickets") if isinstance(j, dict) else None
        if not isinstance(tickets, list):
            info.append(f"{p}: no tickets list; skipped"); continue
        n_open = 0
        for t in tickets:
            if not isinstance(t, dict):
                continue
            created = _iso(t.get("created") or t.get("as_of") or t.get("date"))
            why, age = _stale_reason(t, created, TICKET_STALE_DAYS, today)
            n_open += why is None
            if why:
                tid = t.get("id") or t.get("ticker_or_name") or t.get("ticker")
                out.append({"where": f"{p.name} {tid}", "kind": "ticket", "label": "STALE", "age_days": age, "why": why,
                            "already_labeled": str(t.get("status") or "").upper() == "STALE",
                            "missing": [k for k in EXIT_KEYS if not str(t.get(k) or "").strip()]})
        info.append(f"tickets: read {p} ({len(tickets)} tickets)")
    check_stale.last_info = info
    return out


# ---------------------------------------------------------------- runner
def _log(today: date, rec: dict) -> None:
    try:
        d = Path(os.environ.get("PUBLISH_GUARD_LOG_DIR") or (Path.home() / ".cache" / "publish_guard"))
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"process-{today.isoformat()}.jsonl").open("a") as h:
            h.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def run_process_checks(site: Path, today: date | None = None, emit=print) -> tuple[list[str], list[str], dict]:
    """Return (blocking, warnings, report). Only the FACT gate can block, from FACT_GATE_BLOCK_FROM."""
    today = today or _today()
    site = Path(site)
    infos = []
    rep, warns, block = {"date": today.isoformat(), "at": datetime.now().isoformat(timespec="seconds")}, [], []
    for name, fn in (("wrong_if", lambda: check_wrong_if(site)), ("derived", lambda: check_derived(site)),
                     ("ungraded", lambda: ungraded_items(site, today)), ("fact", lambda: check_fact_gate(site)),
                     ("stale", lambda: check_stale(site, today))):
        try:
            rep[name] = fn()
        except Exception as e:  # a crashed warn check never blocks
            rep[name] = None
            warns.append(f"{name} check crashed: {e}")
    w = rep.get("wrong_if")
    if w:
        pct = "N/A" if w["pct_compliant"] is None else f"{w['pct_compliant']}%"
        bl = w["backlog"]
        infos.append(f"wrong-if lint scope (published >= {w['scope_from']}): {w['lines'] - w['failures']} of {w['lines']} compliant ({pct}); "
                     f"backlog (info only): {bl['lines'] - bl['failures']} of {bl['lines']} compliant ({bl['pct_compliant']}%)")
        if w["failures"]:
            warns.append(f"wrong-if lint: {w['failures']} of {w['lines']} in-scope lines miss a date, number or named source "
                         f"({pct} compliant); e.g. {w['fail_list'][0]['where']} missing {'/'.join(w['fail_list'][0]['missing'])}")
    dv = rep.get("derived")
    for m in (dv or {}).get("mismatches") or []:
        warns.append(f"derived figure {m['id']}: {m['problem']}")
    ug = rep.get("ungraded")
    if ug:
        warns.append(f"ungraded: {len(ug)} item(s) dated before {today} with no outcome, e.g. {ug[0]['where']} ({ug[0]['date']})")
    for s in rep.get("stale") or []:
        warns.append(f"STALE {s['kind']} {s['where']}: {s['why']} (age {s['age_days']} days)"
                     + (" [already labeled STALE in file]" if s.get("already_labeled") else ""))
    rep["_stale_info"] = list(getattr(check_stale, "last_info", []))
    fact = rep.get("fact") or []
    if fact:
        msgs = [f"FACT gate: {f['where']}: FACT with no URL and not PENDING owner/due: {f['text']!r}" for f in fact]
        if today >= FACT_GATE_BLOCK_FROM:
            block += msgs
        else:
            warns += [m + f" (blocks from {FACT_GATE_BLOCK_FROM})" for m in msgs]
    if rep.get("fact") is None:
        block.append("FACT gate crashed; refusing to publish without it")
    infos += rep.get("_stale_info") or []
    rep.pop("_stale_info", None)
    rep["warnings"], rep["blocking"], rep["info"] = warns, block, infos
    _log(today, rep)
    for x in infos:
        emit(f"{INFO}: {x}")
    for x in warns:
        emit(f"{WARN}: {x}")
    return block, warns, rep
