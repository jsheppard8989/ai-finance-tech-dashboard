#!/usr/bin/env python3
"""
Bot Paper Game leaderboard export (Oct 16 2026).

Reads Watcher's public scorekeeping (scoreboard.md + proof/<date>/daily_close_marks_<date>.json)
from the bot game folder and writes site/data/leaderboard.json for site/leaderboard.html.

  python3 pipeline/export_leaderboard.py              # write site/data/leaderboard.json here
  python3 pipeline/export_leaderboard.py --check      # build + print summary, write nothing
  python3 pipeline/export_leaderboard.py --publish    # build in a temp worktree off origin/main,
                                                      # PR + squash-merge (never commits from this checkout)

Source dir: --source DIR, else $BOT_GAME_DIR, else /workspace/cos/bot_game.
Public output only: no file paths, proof paths, private state files or secrets. Text is run
through site_text_sanitize (no 'bet' wording) and the publish guard's style gate. Missing
values are null with a *_reason field.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from site_text_sanitize import find_style_gate_hits, sanitize_public_text  # noqa: E402

START = 1000.0
DEFAULT_SOURCE = "/workspace/cos/bot_game"
OUT_REL = "site/data/leaderboard.json"
# Public bot names. "Compound Wealth" is the group chat name; the bot is Ditka89 (Oct 16).
ALIASES = {"Compound Wealth": "Ditka89"}
# <date>_[<HHMM>_]<Player>_<TICKER>_<entry|exit>.md (time optional, Oct 16 v2)
REASON_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(?:(\d{4})_)?(.+?)_([A-Z.]+)_(entry|exit)\.md$")
WEEK_RE = re.compile(r"Week (\d+) runs ([^.]+)\.")
ARCHIVE_REL = "site/data/leaderboard_archive"
PATH_RE = re.compile(r"(?<![\w/])(?:~|\.)?/(?:[\w.\-]+/)*[\w.\-]*[A-Za-z_][\w.\-]*|\bproof/\S+|\b[\w.\-]+\.(?:json|md|log|png|py)\b")
PRIVATE_RE = re.compile(r"(?i)dragonfly\s*")


def canon(name: str) -> str:
    n = (name or "").split(" (")[0].strip()
    return ALIASES.get(n, n)


# Public wording (G, Oct 16): no personal names for game rules; clarify the agency name.
WORDING = [
    (re.compile(r"\bJared(?:'|\u2019)s\s+(?:approved\s+)?(?:[A-Z]{2,5}\s+)?fallback(?:\s+rule)?"), "the game's fallback rule"),
    (re.compile(r"\bJared(?:'|\u2019)s\s+((?:[\w:.\-]+\s+){0,4}?)rule\b"), r"the game's \1rule"),
    (re.compile(r"\bJared(?:'|\u2019)s\b"), "the game's"),
    (re.compile(r"\bJared\b"), "the game"),
    (re.compile(r"\bDepartment of War\b(?!\s*\(Defense\))"), "Department of War (Defense)"),
]


def apply_wording(t: str) -> str:
    for rx, rep in WORDING:
        t = rx.sub(rep, t)
    # Capitalize a rewritten phrase at the start of a sentence.
    return re.sub(r"(^|[.!?]\s+)the game", lambda m: m.group(1) + "The game", t)


def clean(text) -> str | None:
    if text is None:
        return None
    t = PATH_RE.sub("", str(text))
    t = PRIVATE_RE.sub("", t)
    t = apply_wording(t)
    t = re.sub(r"\s*;\s*;", ";", re.sub(r"\(\s*\)", "", t))
    t = re.sub(r"\s{2,}", " ", t).strip(" ;,")
    try:
        t = sanitize_public_text(t)
    except Exception:
        pass
    # Belt and braces: the site never calls anything a bet.
    t = re.sub(r"\b[Bb]ets?\b", lambda m: "call" if m.group(0).islower() else "Call", t)
    return t or None


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _first_sentences(text: str, limit: int = 240) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for p in parts:
        if out and len(out) + len(p) + 1 > limit:
            break
        out = (out + " " + p).strip()
    return out[:limit].rstrip()


def parse_reason_md(text: str) -> dict:
    """Public reasons channel file -> {why, stop, target, wrong_if}. Bullet lines only."""
    r = {"why": None, "stop": None, "target": None, "wrong_if": None}
    for line in text.splitlines():
        m = re.match(r"\s*-\s*([A-Za-z /]+?):\s*(.+)", line)
        if not m:
            continue
        k, v = m.group(1).strip().lower(), m.group(2).strip()
        if k == "why":
            r["why"] = _first_sentences(v)
        elif k.startswith("stop"):
            # Keep the whole bullet (e.g. Ric's stop moved to breakeven); split off an inline Target.
            stop, _, rest = v.partition("Target:")
            r["stop"] = stop.strip() or None
            if rest:
                r["target"] = rest.strip()
            if "target" in k and not rest:
                r["target"] = r["stop"]
        elif k == "target":
            r["target"] = v
        elif k.startswith("wrong if"):
            r["wrong_if"] = v
    return {k: clean(v) for k, v in r.items()}


def load_reason_files(src: Path, bot_names) -> dict:
    """(bot, date, TICKER, kind) -> [(HHMM or None, parsed reason)], sorted (untimed files last
    within a key, then by name). Accepts <date>_<Player>_... and <date>_<HHMM>_<Player>_..."""
    keys = {_key(b): b for b in bot_names}
    out: dict = {}
    for f in sorted((src / "reasons").glob("*.md")) if (src / "reasons").is_dir() else []:
        m = REASON_FILE_RE.match(f.name)
        if not m:
            continue
        day, hhmm, who, tk, kind = m.groups()
        k = _key(ALIASES.get(who, who))
        bot = keys.get(k) or next((b for kk, b in keys.items() if kk.startswith(k) or k.startswith(kk)), None)
        if not bot:
            continue
        try:
            parsed = parse_reason_md(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.setdefault((bot, day, tk.upper(), kind), []).append((hhmm, f.name, parsed))
    for v in out.values():
        v.sort(key=lambda x: (x[0] is None, x[0] or "", x[1]))
    return out


def match_reasons(trades: list, files: dict) -> dict:
    """trade index -> parsed reason. A timed file matches the trade with the same HHMM (received
    or fill bar). Untimed files go to the remaining trades with that key in time order, so two
    same-ticker round trips on one day no longer collide."""
    out, used = {}, set()
    groups: dict = {}
    for i, t in enumerate(trades):
        groups.setdefault((t["bot"], t["date"], t["ticker"].upper(), t["kind"]), []).append(i)
    for key, idxs in groups.items():
        cands = files.get(key, [])
        left = []
        for i in idxs:
            hit = next((j for j, (hh, _, _) in enumerate(cands)
                        if hh and j not in used and hh in (trades[i]["hhmm"], trades[i].get("bar_hhmm"))), None)
            if hit is not None:
                used.add(hit); out[i] = cands[hit][2]
            else:
                left.append(i)
        untimed = [j for j, (hh, _, _) in enumerate(cands) if hh is None]
        for i, j in zip(left, untimed):
            out[i] = cands[j][2]
        used = set()
    return out


# Correction records (<source>/corrections.json): public-text fixes to a logged trade, keyed by
# bot/date/ticker/kind and the Watcher receipt HH:MM. Only display fields may change; fills,
# fees and P&L always come from the proof files.
CORRECTABLE = ("time_ct", "why", "stop", "target", "wrong_if")


def load_corrections(src: Path) -> list:
    data = _load_json(src / "corrections.json")
    recs = data.get("corrections", []) if isinstance(data, dict) else (data or [])
    out = []
    for c in recs:
        if not isinstance(c, dict) or not isinstance(c.get("set"), dict):
            continue
        bad = set(c["set"]) - set(CORRECTABLE)
        if bad:
            raise SystemExit(f"corrections.json: field(s) {sorted(bad)} cannot be corrected here")
        out.append(c)
    return out


def apply_corrections(log: list, matched: dict, corrections: list) -> dict:
    """trade index -> {field: value} overrides. Reason fields also patch the matched reason so the
    open-position card shows the same text."""
    over: dict = {}
    for c in corrections:
        for i, t in enumerate(log):
            if (canon(c.get("bot", "")) == t["bot"] and c.get("date") == t["date"]
                    and str(c.get("ticker", "")).upper() == t["ticker"] and c.get("kind", "entry") == t["kind"]
                    and c.get("received_hhmm", t["time_ct"]) == t["time_ct"]):
                fix = {k: clean(v) if k != "time_ct" else v for k, v in c["set"].items()}
                over.setdefault(i, {}).update(fix)
                rf = matched.get(i)
                if rf is not None:
                    matched[i] = {**rf, **{k: v for k, v in fix.items() if k != "time_ct"}}
    return over


def load_reasons(src: Path, bot_names) -> dict:
    """(bot, date, TICKER, kind) -> latest parsed reason (back-compat helper)."""
    return {k: v[-1][2] for k, v in load_reason_files(src, bot_names).items()}


def md_table(md: str, header: str) -> list[list[str]]:
    i = md.find(header)
    if i < 0:
        return []
    rows, started = [], False
    for line in md[i:].splitlines()[1:]:
        if line.startswith("|"):
            started = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]


def latest_marks(src: Path) -> tuple[dict | None, list[str]]:
    files = sorted(glob.glob(str(src / "proof" / "*" / "daily_close_marks_*.json")))
    return (json.loads(Path(files[-1]).read_text(encoding="utf-8")) if files else None), files


def trade_reason(action: str) -> tuple[str | None, str | None]:
    a = action.lower()
    if "stop" in a and ("exit" in a or "cover" in a):
        return "Exited on its stop", None
    if "target" in a and ("exit" in a or "cover" in a):
        return "Exited at its target", None
    if "fallback" in a:
        return "Moved into the fallback pick", None
    if a.startswith("exit"):
        return "Closed the position", None
    if a.startswith("re-entry"):
        return "Re-entered with the cash from the earlier exit", None
    if a.startswith("entry"):
        return None, "no public reason filed with Watcher (entries are locked at receipt)"
    return None, "no public reason filed"


def side_of(action: str) -> str | None:
    a = action.lower()
    if a.startswith("exit"):
        return "cover" if "cover" in a else "sell"
    if "short" in a:
        return "short"
    if a.startswith(("entry", "re-entry")):
        return "buy"
    return None


def fill_price(s: str):
    m = re.match(r"\s*([\d.]+)", s or "")
    return float(m.group(1)) if m else None


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def fee_rate(px: float) -> float:
    """RULES.md tiers on the per-share fill price (same as Watcher's bar_fill.py)."""
    return 0.0025 if px < 5 else 0.001 if px < 10 else 0.0005 if px < 20 else 0.0


def week_span_dates(span: str | None):
    m = re.findall(r"([A-Z][a-z]{2}) (\d{1,2}) (\d{4})", span or "")
    if len(m) >= 2:
        try:
            a, b = (dt.datetime.strptime(" ".join(x), "%b %d %Y").date() for x in m[:2])
            return a.isoformat(), b.isoformat()
        except ValueError:
            pass
    return None, None


def build_trade_log(src: Path, md: str, start: str | None = None, end: str | None = None):
    """Watcher's Trades log + proof bar files -> (trades, closed_by_bot, open_by_bot).
    Prices come from the fill proof (scoreboard text as fallback). Exit fees are recomputed as
    rate x (shares x exit price): some exit proofs stored the fee on the $1,000 basis (CIFR 10/15
    stored $1.00; Watcher's corrected figure is $0.85)."""
    trades, closed, open_pos = [], {}, {}
    rows = [r for r in md_table(md, "## Trades log") if len(r) >= 5 and re.match(r"\d{4}-\d{2}-\d{2}", r[0])]
    if start:
        rows = [r for r in rows if start <= r[0][:10] <= end]
    for r in sorted(rows, key=lambda r: r[0]):
        received, player, action, ticker, fill_txt = r[:5]
        proof_rel = r[6] if len(r) > 6 else ""
        bot = canon(player)
        kind = "exit" if action.lower().startswith("exit") else "entry"
        pf = _load_json(src / proof_rel) if proof_rel and not proof_rel.startswith("/") and ".." not in proof_rel else None
        px = (pf or {}).get("fill_price")
        px = float(px) if px is not None else fill_price(fill_txt)
        bar = (pf or {}).get("bar_start_ct") or ""
        t = {"date": received[:10], "time_ct": received[11:16] or None, "bot": bot,
             "action": side_of(action), "ticker": ticker.upper(), "fill": px,
             "fee_usd": None, "kind": kind, "hhmm": received[11:16].replace(":", ""),
             "bar_hhmm": bar[11:16].replace(":", "") if bar else None, "received": received}
        note = None
        if kind == "entry":
            amt = (pf or {}).get("notional_usd")
            if amt is None:
                m = re.search(r"\$([\d,]+(?:\.\d+)?)", action)
                amt = float(m.group(1).replace(",", "")) if m else None
            fee = (pf or {}).get("fee_usd")
            if fee is None and px is not None:
                fee = round((amt or 0) * fee_rate(px), 2) if amt is not None else None
            t["fee_usd"] = fee
            side = "short" if "short" in action.lower() else "long"
            shares = (pf or {}).get("shares") or ((amt / px) if amt and px else None)
            open_pos[bot] = {"ticker": t["ticker"], "side": side, "entry": px, "amount_usd": amt,
                             "entry_fee": fee or 0.0, "shares": shares, "entry_time_ct": received}
        else:
            pos = open_pos.pop(bot, None)
            if pos and pos["ticker"] == t["ticker"] and px is not None and pos["entry"]:
                shares = pos["shares"] or (pos["amount_usd"] / pos["entry"])
                if pos["side"] == "short":
                    gross = pos["amount_usd"] * (2 - px / pos["entry"])
                else:
                    gross = shares * px
                # Fee = tier rate x exit notional (shares x exit price), never the $1,000 basis.
                fee = round(shares * px * fee_rate(px), 2)
                t["fee_usd"] = fee
                cost = pos["amount_usd"] + pos["entry_fee"]
                pnl = gross - fee - cost
                closed.setdefault(bot, []).append({
                    "ticker": pos["ticker"], "side": pos["side"], "entry": pos["entry"], "exit": px,
                    "entry_time_ct": pos["entry_time_ct"], "exit_time_ct": received,
                    "fees_usd": round(pos["entry_fee"] + fee, 2),
                    "realized_pnl_usd": round(pnl, 2), "realized_pnl_pct": round(pnl / cost * 100, 2)})
            else:
                note = "exit has no matching open entry in Watcher's log"
                t["fee_usd"] = (pf or {}).get("fee_usd")
        if t["fee_usd"] is None:
            t["fee_usd_reason"] = "no fee on file for this fill"
        if note:
            t["note"] = note
        trades.append(t)
    return trades, closed, open_pos


def build(src: Path, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))
    md_path = src / "scoreboard.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    wk = WEEK_RE.search(md)
    week_no = int(wk.group(1)) if wk else None
    week_span = wk.group(2) if wk else None
    wk_start, wk_end = week_span_dates(week_span)
    mark_files = sorted(glob.glob(str(src / "proof" / "*" / "daily_close_marks_*.json")))
    all_marks = [m for m in (_load_json(Path(f)) for f in mark_files) if isinstance(m, dict) and m.get("date")]
    if wk_start:
        all_marks = [m for m in all_marks if wk_start <= m["date"] <= wk_end]
    marks = all_marks[-1] if all_marks else None
    as_of = marks.get("date") if marks else None
    history = [{"date": m["date"], "values": {canon(p.get("player")): p.get("value") for p in m.get("positions", [])}}
               for m in all_marks]
    log, closed_by_bot, open_by_bot = build_trade_log(src, md, wk_start, wk_end)

    trades = [dict(t=r[0], player=canon(r[1]), action=r[2], ticker=r[3], fill=r[4])
              for r in md_table(md, "## Trades log") if len(r) >= 5]
    fines: dict[str, list] = {}
    for r in md_table(md, "## Fines"):
        if len(r) >= 3 and r[0]:
            amt = fill_price(r[2].replace("$", "").replace(",", ""))
            fines.setdefault(canon(r[1]), []).append({"day": r[0], "amount_usd": amt})

    standings = {canon(r[0]): r for r in md_table(md, "## Standings") if r}
    players = {}
    for p in (marks or {}).get("positions", []):
        players[canon(p["player"])] = p
    for name in standings:
        players.setdefault(name, None)

    reason_files = load_reason_files(src, list(players) + [t["bot"] for t in log])
    matched = match_reasons(log, reason_files)
    overrides = apply_corrections(log, matched, load_corrections(src))
    reasons = {k: v[-1][2] for k, v in reason_files.items()}
    full_trades = []
    for i, t in enumerate(log):
        rf = matched.get(i)
        filed = bool(rf and rf.get("why"))
        row = {k: t[k] for k in ("date", "time_ct", "bot", "action", "ticker", "fill", "fee_usd")}
        row["reason_filed"] = filed
        for k in ("why", "stop", "target", "wrong_if"):
            row[k] = rf.get(k) if rf else None
        if not filed:
            row["reason_missing"] = "no reason filed in the public reasons channel"
        for k in ("fee_usd_reason", "note"):
            if k in t:
                row[k] = t[k]
        if "time_ct" in overrides.get(i, {}):
            row["time_ct"] = overrides[i]["time_ct"]
        full_trades.append(row)
    rows = []
    for name, p in players.items():
        bal = p.get("value") if p else None
        if bal is None and name in standings:
            try:
                bal = float(re.sub(r"[^\d.\-]", "", standings[name][6].split("(")[0]))
            except Exception:
                bal = None
        side = (p or {}).get("side")
        flat = side == "cash" or (p or {}).get("ticker") == "FLAT"
        position = None if not p else {
            "ticker": None if flat else p.get("ticker"),
            "side": "flat" if flat else side,
            "entry": p.get("entry"),
            "close": p.get("close"),
            "shares": p.get("shares"),
        }
        today = []
        for t in full_trades:
            if t["bot"] == name and as_of and t["date"] == as_of:
                today.append({
                    "time_ct": t["time_ct"], "action": t["action"], "ticker": t["ticker"], "fill": t["fill"],
                    "fee_usd": t["fee_usd"], "reason": t["why"], "reason_filed": t["reason_filed"],
                    **({"reason_missing": t["reason_missing"]} if not t["reason_filed"] else {}),
                    **({k: t[k] for k in ("stop", "target", "wrong_if") if t.get(k)}),
                })
        if position and position.get("ticker"):
            # Reason for the open position = the reason matched to its latest entry in the log.
            idx = [i for i, t in enumerate(log) if t["bot"] == name and t["kind"] == "entry"
                   and t["ticker"] == position["ticker"].upper()]
            rf = matched.get(idx[-1]) if idx else None
            if rf is None:
                cands = sorted(k for k in reasons if k[0] == name and k[2] == position["ticker"].upper() and k[3] == "entry")
                rf = reasons[cands[-1]] if cands else None
            if rf:
                position["reason"] = rf
            else:
                position["reason"] = None
                position["reason_missing"] = "no public reason filed yet"
            op = open_by_bot.get(name)
            if op and op["ticker"] == position["ticker"]:
                amt = op["amount_usd"]
                position["amount_usd"] = amt
                close, entry = position.get("close"), op["entry"]
                if amt and close is not None and entry:
                    mval = amt * (2 - close / entry) if op["side"] == "short" else amt * close / entry
                    cost = amt + (op["entry_fee"] or 0)
                    position["open_pnl_usd"] = round(mval - cost, 2)
                    position["open_pnl_pct"] = round((mval - cost) / cost * 100, 2)
                else:
                    position["open_pnl_usd"] = position["open_pnl_pct"] = None
                    position["open_pnl_reason"] = "no close mark for this position"
            else:
                position["amount_usd"] = position["open_pnl_usd"] = position["open_pnl_pct"] = None
                position["open_pnl_reason"] = "open entry not found in Watcher's log"
            position["mark_time_ct"] = f"{as_of}T15:00:00-05:00" if as_of and position.get("close") is not None else None
            position["mark_source"] = "official close (Yahoo Finance via yfinance)" if position["mark_time_ct"] else None
        f = fines.get(name, [])
        row = {
            "bot": name,
            "balance_usd": round(bal, 2) if bal is not None else None,
            "pnl_usd": round(bal - START, 2) if bal is not None else None,
            "pnl_pct": round((bal - START) / START * 100, 2) if bal is not None else None,
            "day_pnl_usd": (p or {}).get("day_pl"),
            "position": position,
            "today_trades": today,
            "fines_usd": round(sum(x["amount_usd"] or 0 for x in f), 2),
            "fines": f,
            "note": clean((p or {}).get("note")),
            "closed_positions": closed_by_bot.get(name, []),
        }
        if bal is None:
            row["balance_reason"] = "no close mark for this bot yet"
        if not p:
            row["position_reason"] = "not in the latest close marks"
        rows.append(row)

    rows.sort(key=lambda r: -(r["balance_usd"] if r["balance_usd"] is not None else -1e18))
    for i, r in enumerate(rows, 1):
        r["rank"] = i if r["balance_usd"] is not None else None
    rows = [{"rank": r.pop("rank"), **r} for r in rows]

    out = {
        "game": "Weekly Bot Paper Game",
        "paper_only": True,
        "disclaimer": "Paper game. No real orders are placed. Not advice.",
        "starting_balance_usd": START,
        "week": clean(week_span),
        "week_number": week_no,
        "as_of": as_of,
        "as_of_reason": None if as_of else "no daily close marks found yet",
        "marks_captured_ct": (marks or {}).get("captured_ct"),
        "marks_source": clean((marks or {}).get("source")),
        "scoreboard_updated_ct": dt.datetime.fromtimestamp(md_path.stat().st_mtime, now.tzinfo).isoformat(timespec="seconds") if md_path.exists() else None,
        "generated_at_ct": now.isoformat(timespec="seconds"),
        "scorekeeper": "Watcher",
        "bots": rows,
        "history": history,
        "trades": full_trades,
    }
    name_hits = re.findall(r"(?i)\bjared\b", json.dumps(out, ensure_ascii=False))
    if name_hits:
        raise SystemExit(f"leaderboard export blocked: {len(name_hits)} 'Jared' hit(s) left in public text")
    hits = find_style_gate_hits(out)
    if hits:
        raise SystemExit(f"leaderboard export blocked: style gate hit {hits[0]}")
    return out


def archive_previous_week(out: dict, path: Path) -> Path | None:
    """At the weekly reset, keep the last published JSON of the previous week as
    leaderboard_archive/week-<n>.json (written once, never overwritten)."""
    if not path.exists():
        return None
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    old_no = old.get("week_number")
    if old_no is None:
        m = re.match(r"\s*Wed Oct 14 2026", old.get("week") or "")
        old_no = 1 if m else None  # pre-v2 files had no week_number; week 1 started Oct 14
    new_no = out.get("week_number")
    if old_no is None or new_no is None or old_no == new_no:
        return None
    dest = path.parent / "leaderboard_archive" / f"week-{old_no}.json"
    if dest.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def write(out: dict, path: Path) -> bool:
    archived = archive_previous_week(out, path)
    if archived:
        print(f"archived previous week -> {archived.name}")
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old is not None:
        try:
            a, b = json.loads(old), json.loads(text)
            a.pop("generated_at_ct", None); b.pop("generated_at_ct", None)
            if a == b:
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def sh(*cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(cmd[:3])} failed: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def publish(out: dict) -> int:
    sh("git", "fetch", "-q", "origin", "main", cwd=REPO)
    wt = Path(tempfile.mkdtemp(prefix="leaderboard_pub_"))
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    branch = f"data/leaderboard-{stamp}"
    sh("git", "worktree", "add", "-q", "-b", branch, str(wt), "origin/main", cwd=REPO)
    try:
        if not write(out, wt / OUT_REL):
            print("leaderboard.json unchanged on origin/main; nothing to publish.")
            return 0
        sys.path.insert(0, str(wt / "pipeline"))
        from publish_guard import run_publish_guard
        ok, reasons = run_publish_guard(wt / "site", wt / "pipeline", wt)
        if not ok:
            print("✗ publish guard blocked the leaderboard publish.")
            return 1
        sh("git", "add", "-f", OUT_REL, cwd=wt)
        if (wt / ARCHIVE_REL).is_dir():
            sh("git", "add", "-f", ARCHIVE_REL, cwd=wt)
        name = sh("git", "config", "user.name", cwd=wt, check=False) or sh("git", "log", "-1", "--format=%an", cwd=wt)
        email = sh("git", "config", "user.email", cwd=wt, check=False) or sh("git", "log", "-1", "--format=%ae", cwd=wt)
        sh("git", "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m",
           f"Bot game leaderboard {out.get('as_of')} (export_leaderboard.py)", cwd=wt)
        sh("git", "push", "-q", "-u", "origin", branch, cwd=wt)
        url = sh("gh", "pr", "create", "--base", "main", "--head", branch, "--title",
                 f"Bot game leaderboard {out.get('as_of')}", "--body",
                 "Automated: pipeline/export_leaderboard.py --publish (site/data/leaderboard.json only).", cwd=wt)
        print(url)
        r = subprocess.run(["gh", "pr", "merge", branch, "--squash", "--delete-branch"], cwd=wt, text=True, capture_output=True)
        state = sh("gh", "pr", "view", branch, "--json", "state", "-q", ".state", cwd=wt, check=False)
        if state != "MERGED":
            print(f"✗ PR not merged ({r.stderr.strip()[:200]}); left open: {url}")
            return 1
        subprocess.run(["git", "push", "-q", "origin", "--delete", branch], cwd=wt, capture_output=True)
        print(f"✓ merged {url}")
        return 0
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO, capture_output=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bot game leaderboard export")
    ap.add_argument("--source", default=os.environ.get("BOT_GAME_DIR", DEFAULT_SOURCE))
    ap.add_argument("--out", default=str(REPO / OUT_REL))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)
    out = build(Path(a.source))
    print(f"leaderboard: as_of={out['as_of']} bots={len(out['bots'])} leader="
          f"{out['bots'][0]['bot'] if out['bots'] else None}")
    if a.check:
        return 0
    if a.publish:
        return publish(out)
    print("wrote" if write(out, Path(a.out)) else "unchanged", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
