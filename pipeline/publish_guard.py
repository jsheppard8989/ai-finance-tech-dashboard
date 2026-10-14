#!/usr/bin/env python3
"""
Evening publish guard (decisions log 2026-10-14 8:27 AM CT, packet item #4):
block any export that regresses public site content. Built after the 10/13
11:04 PM publish (c11bf113) wiped the Trap Map card ids and the
open-linked-card script, which #411 had to restore.

Runs in the publish path before anything is staged, committed or pushed:
  - publish_site.main() right after validate_site_bundle (also on --dry-run)
  - auto_pipeline.git_push() after fetch/pull --rebase, before `git add`

Fails closed. Each failure prints one line starting with
"ALERT publish guard:" plus the reason; the caller then refuses to publish.

Checks (candidate = working-tree site/, baseline = committed HEAD and
origin/main, i.e. what is live):
  1. Trap Map card ids: every <details class="ev" id=...> in the baseline
     trap-map.html, and every id pinned by pipeline/trap_home_override.json /
     site/data/trap_map_home.json, is still a card in trap-map.html.
  2. The open-linked-card script (hash -> open the matching <details>) is
     still in trap-map.html.
  3. No override fix undone: for every [old, new] pair in
     summary_overrides.json name_replacements, global_replacements and
     summaries[].replacements, the count of `old` in public site files is not
     higher than in the baseline. The Moonshots fix (#413) stays applied: no
     global "Moonshots Live" guest fix, and no record tying Cathie Wood to a
     Moonshots Live episode other than EP #296.
  4. Style gate: zero 'bet' wording hits (site_text_sanitize rules) in
     data.js, site/data/*.json and the Trap Map card text.
  5. data.js generatedAt present and non-empty.
  6. data.js priceSnapshot present and non-empty.

CLI: python3 publish_guard.py [--site DIR] [--repo DIR]   (exit 1 = blocked)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from site_text_sanitize import find_style_gate_hits, style_gate_hits  # noqa: E402

ALERT = "ALERT publish guard"
CARD_ID_RE = re.compile(r"<details\b[^>]*\bclass=\"ev\"[^>]*\bid=\"([^\"]+)\"|<details\b[^>]*\bid=\"([^\"]+)\"[^>]*\bclass=\"ev\"")
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
BASELINE_REFS = ("HEAD", "origin/main")


# ---------------------------------------------------------------- helpers
def _git_show(repo: Path, ref: str, relpath: str) -> str | None:
    try:
        r = subprocess.run(["git", "show", f"{ref}:{relpath}"], cwd=repo,
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def _git_ls(repo: Path, ref: str, reldir: str) -> list[str]:
    try:
        r = subprocess.run(["git", "ls-tree", "--name-only", f"{ref}:{reldir}"], cwd=repo,
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    return r.stdout.split() if r.returncode == 0 else []


def card_ids(page: str) -> set[str]:
    return {a or b for a, b in CARD_ID_RE.findall(page or "")}


def has_open_linked_card_script(page: str) -> bool:
    for body in SCRIPT_RE.findall(page or ""):
        if ("location.hash" in body and "getElementById" in body
                and re.search(r"\.open\s*=\s*true", body) and "hashchange" in body):
            return True
    return False


def parse_data_js(text: str) -> dict:
    """Parse site/data/data.js (`const dashboardData = {...};`) into a dict."""
    a = text.index("{", text.index("const dashboardData"))
    b = text.index("\n};", a)
    body = re.sub(r"(?m)^\s*//.*$", "", text[a:b + 2])
    body = re.sub(r"(?m)^(\s*)([A-Za-z_]\w*):", r'\1"\2":', body)
    return json.loads(body)


def _public_rel_files(site: Path) -> list[str]:
    rel = ["data/data.js"] + sorted(f"data/{p.name}" for p in (site / "data").glob("*.json"))
    return rel + sorted(p.name for p in site.glob("*.html"))


def _pairs(overrides: dict) -> list[tuple[str, str, str]]:
    out = []
    for key in ("name_replacements", "global_replacements"):
        for pair in overrides.get(key) or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                out.append((key, str(pair[0]), str(pair[1])))
    for rule in overrides.get("summaries") or []:
        for pair in (rule or {}).get("replacements") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                out.append((f"summaries[{rule.get('insight_id', '?')}]", str(pair[0]), str(pair[1])))
    # A swap whose old text survives inside the new text can't be counted.
    return [(k, o, n) for k, o, n in out if o and o not in n]


def _walk(obj, parent_title: str = ""):
    if isinstance(obj, dict):
        title = ""
        for k in ("last_episode_title", "episode_title", "title"):
            if isinstance(obj.get(k), str):
                title = obj[k]
                break
        yield obj, title or parent_title
        for v in obj.values():
            yield from _walk(v, title or parent_title)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, parent_title)


# ---------------------------------------------------------------- checks
def check_trap_map(site: Path, pipeline: Path, baselines: dict[str, dict[str, str]]) -> list[str]:
    reasons = []
    page_path = site / "trap-map.html"
    if not page_path.is_file():
        return ["site/trap-map.html is missing"]
    page = page_path.read_text(encoding="utf-8", errors="replace")
    have = card_ids(page)

    want: dict[str, str] = {}
    for ref, files in baselines.items():
        for cid in card_ids(files.get("trap-map.html") or ""):
            want.setdefault(cid, f"live trap-map.html ({ref})")
    for label, path in (("pipeline/trap_home_override.json", pipeline / "trap_home_override.json"),
                        ("site/data/trap_map_home.json", site / "data" / "trap_map_home.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in (d.get("last_monitored") or []) + (d.get("upcoming_watches") or []):
            cid = (e or {}).get("id") or (e or {}).get("trap_id")
            if cid:
                want.setdefault(str(cid), label)
    missing = sorted(c for c in want if c not in have)
    if missing:
        reasons.append("Trap Map card ids dropped from trap-map.html: "
                       + ", ".join(f"#{c} (in {want[c]})" for c in missing))
    if not has_open_linked_card_script(page):
        reasons.append("trap-map.html lost the open-linked-card script (#id link no longer opens its card)")

    # Style gate on the visible card text.
    text = html.unescape(re.sub(r"<[^>]+>", " ", SCRIPT_RE.sub(" ", page)))
    hits = style_gate_hits(text)
    if hits:
        reasons.append(f"style gate: {len(hits)} 'bet' wording hit(s) in trap-map.html, e.g. {hits[0]!r}")
    return reasons


def check_overrides(site: Path, pipeline: Path, baselines: dict[str, dict[str, str]]) -> list[str]:
    reasons = []
    try:
        ov = json.loads((pipeline / "summary_overrides.json").read_text(encoding="utf-8"))
    except Exception as e:
        return [f"pipeline/summary_overrides.json unreadable: {e}"]
    pairs = _pairs(ov)
    if baselines:
        undone = []
        for rel in _public_rel_files(site):
            try:
                cand = (site / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            base_texts = [b[rel] for b in baselines.values() if b.get(rel) is not None]
            if not base_texts:
                continue
            for key, old, _new in pairs:
                c = cand.count(old)
                if c and c > min(t.count(old) for t in base_texts):
                    undone.append(f"{key} {old!r} back in site/{rel}")
        if undone:
            reasons.append(f"override fix undone ({len(undone)}): " + "; ".join(undone[:8]))

    # Moonshots fix (#413): guest fix scoped to EP #296 only.
    try:
        gov = json.loads((pipeline / "guest_overrides.json").read_text(encoding="utf-8"))
        for section, m in gov.items():
            if isinstance(m, dict) and section != "episode_title_guest" and "Moonshots Live" in m:
                reasons.append(f"Moonshots fix undone: guest_overrides.json {section} has a global 'Moonshots Live' guest fix")
    except Exception as e:
        reasons.append(f"pipeline/guest_overrides.json unreadable: {e}")
    bad = set()
    for rel in ("data/podcast_guests.json", "data/podcast_summaries.json", "data/archive.json"):
        try:
            obj = json.loads((site / rel).read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec, title in _walk(obj):
            if "Moonshots Live" in title and "#296" not in title:
                vals = [rec.get(k) for k in ("name", "guest", "guest_name", "guests")]
                if any(isinstance(v, str) and "Cathie Wood" in v for v in vals):
                    bad.add(f"{title[:70]!r} in site/{rel}")
    if bad:
        reasons.append("Moonshots fix undone: Cathie Wood named as guest of non-#296 Moonshots Live episode(s): "
                       + "; ".join(sorted(bad)[:4]))
    return reasons


def check_data(site: Path) -> list[str]:
    reasons = []
    try:
        data = parse_data_js((site / "data" / "data.js").read_text(encoding="utf-8"))
    except Exception as e:
        return [f"data.js unreadable for guard checks: {e}"]
    if not str(data.get("generatedAt") or "").strip():
        reasons.append("data.js generatedAt is missing or empty")
    snap = data.get("priceSnapshot")
    if not isinstance(snap, dict) or not snap:
        reasons.append("data.js priceSnapshot is missing or empty")
    hits = [("data.js", p, s) for p, s in find_style_gate_hits(data)]
    for p in sorted((site / "data").glob("*.json")):
        try:
            hits += [(p.name, hp, s) for hp, s in find_style_gate_hits(json.loads(p.read_text(encoding="utf-8")))]
        except Exception:
            continue
    if hits:
        f, hp, s = hits[0]
        reasons.append(f"style gate: {len(hits)} 'bet' wording hit(s) in public data, e.g. {f}{hp}: {s!r}")
    return reasons


def load_baselines(repo: Path, site_rel: str = "site", refs: Iterable[str] = BASELINE_REFS) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for ref in refs:
        page = _git_show(repo, ref, f"{site_rel}/trap-map.html")
        if page is None:
            continue
        files = {"trap-map.html": page}
        for name in _git_ls(repo, ref, f"{site_rel}/data"):
            if name == "data.js" or name.endswith(".json"):
                t = _git_show(repo, ref, f"{site_rel}/data/{name}")
                if t is not None:
                    files[f"data/{name}"] = t
        for name in _git_ls(repo, ref, site_rel):
            if name.endswith(".html") and name != "trap-map.html":
                t = _git_show(repo, ref, f"{site_rel}/{name}")
                if t is not None:
                    files[name] = t
        out[ref] = files
    return out


def run_publish_guard(site: Path, pipeline: Path | None = None, repo: Path | None = None,
                      baselines: dict | None = None) -> tuple[bool, list[str]]:
    """Return (ok, reasons). Prints one 'ALERT publish guard: ...' line per reason."""
    site = Path(site)
    pipeline = Path(pipeline) if pipeline else site.parent / "pipeline"
    repo = Path(repo) if repo else site.parent
    if baselines is None:
        baselines = load_baselines(repo, site.name)
    reasons = []
    if not baselines:
        print("  ⚠ publish guard: no git baseline (HEAD/origin/main); running absolute checks only")
    for fn in (check_trap_map, check_overrides):
        try:
            reasons += fn(site, pipeline, baselines)
        except Exception as e:
            reasons.append(f"{fn.__name__} crashed: {e}")
    try:
        reasons += check_data(site)
    except Exception as e:
        reasons.append(f"check_data crashed: {e}")
    for r in reasons:
        print(f"{ALERT}: {r}")
    if not reasons:
        print("✓ publish guard: Trap Map ids + open-linked-card script, override fixes, style gate, generatedAt, priceSnapshot OK")
    return (not reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--site", default=str(_HERE.parent / "site"))
    ap.add_argument("--repo", default=str(_HERE.parent))
    a = ap.parse_args()
    ok, _ = run_publish_guard(Path(a.site), _HERE, Path(a.repo))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
