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
# Public bot names (RULES.md). Filing aliases map to the bot they filed for.
ALIASES = {"Ditka89": "Compound Wealth"}
PATH_RE = re.compile(r"(?:/[\w.\-]+)+/?|\bproof/\S+|\b[\w.\-]+\.(?:json|md|log|png|py)\b")
PRIVATE_RE = re.compile(r"(?i)dragonfly\s*")


def canon(name: str) -> str:
    n = (name or "").split(" (")[0].strip()
    return ALIASES.get(n, n)


def clean(text) -> str | None:
    if text is None:
        return None
    t = PATH_RE.sub("", str(text))
    t = PRIVATE_RE.sub("", t)
    t = re.sub(r"\s*;\s*;", ";", re.sub(r"\(\s*\)", "", t))
    t = re.sub(r"\s{2,}", " ", t).strip(" ;,")
    try:
        t = sanitize_public_text(t)
    except Exception:
        pass
    # Belt and braces: the site never calls anything a bet.
    t = re.sub(r"\b[Bb]ets?\b", lambda m: "call" if m.group(0).islower() else "Call", t)
    return t or None


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


def build(src: Path, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))
    md_path = src / "scoreboard.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    marks, mark_files = latest_marks(src)
    as_of = marks.get("date") if marks else None

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
        for t in trades:
            if t["player"] == name and as_of and t["t"].startswith(as_of):
                reason, why_null = trade_reason(t["action"])
                today.append({
                    "time_ct": t["t"][11:16] or None,
                    "action": side_of(t["action"]),
                    "ticker": t["ticker"],
                    "fill": fill_price(t["fill"]),
                    "reason": clean(reason),
                    **({"reason_missing": why_null} if reason is None else {}),
                })
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
        "week": clean(re.search(r"Week 1 runs ([^.]+)\.", md).group(1)) if re.search(r"Week 1 runs ([^.]+)\.", md) else None,
        "as_of": as_of,
        "as_of_reason": None if as_of else "no daily close marks found yet",
        "marks_captured_ct": (marks or {}).get("captured_ct"),
        "marks_source": clean((marks or {}).get("source")),
        "scoreboard_updated_ct": dt.datetime.fromtimestamp(md_path.stat().st_mtime, now.tzinfo).isoformat(timespec="seconds") if md_path.exists() else None,
        "generated_at_ct": now.isoformat(timespec="seconds"),
        "scorekeeper": "Watcher",
        "bots": rows,
    }
    hits = find_style_gate_hits(out)
    if hits:
        raise SystemExit(f"leaderboard export blocked: style gate hit {hits[0]}")
    return out


def write(out: dict, path: Path) -> bool:
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
