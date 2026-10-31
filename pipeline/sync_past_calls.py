"""Sync past calls from G's record into the Trap Map, and report (never fix) row differences.

  python3 pipeline/sync_past_calls.py            # --preview (default): writes ONLY under /tmp/preview
  python3 pipeline/sync_past_calls.py --apply    # writes site/data/trap_map.json, then rebuild with build_trap_map.py

Source: /workspace/cos/grading/past_calls.json (override with --source). Every entry must pass
trap_map_check.check_past_calls (ticker, outcome_text, exit_reason, evidence_url). --apply publishes only
entries that pass and lists the held-back ones; --preview renders every entry, marking missing evidence.
The row reconcile compares the site's open rows with the local row-trades file and only prints differences.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_trap_map as btm  # noqa: E402
import trap_map_check  # noqa: E402

SOURCE = Path("/workspace/cos/grading/past_calls.json")
ROW_TRADES = Path("/workspace/cos/trapmap/row_trades_2026-10-29.md")
PREVIEW = Path("/tmp/preview")
PUBLIC = ("ticker", "outcome_text", "exit_reason", "evidence_url")


def load_source(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["past_calls"] if isinstance(raw, dict) else raw


def split_publishable(calls: list[dict]) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    ok, held = [], []
    for c in calls:
        errs = trap_map_check.check_past_calls([c])
        if errs:
            held.append((c, errs))
        else:
            ok.append({k: c[k] for k in PUBLIC})
    return ok, held


def reconcile_rows(d: dict, md_text: str | None) -> list[str]:
    """Report-only: which open rows the local row-trades file names, and tickers on one side only."""
    if md_text is None:
        return ["row reconcile: local row-trades file not found; nothing compared"]
    site = {r["ticker"].upper() for r in d["rows"] if r.get("status") != "closed"}
    local = set(re.findall(r"^\|\s*([A-Z]{2,5}) \((?:Positive|Negative)\)", md_text, flags=re.M))
    out = []
    for t in sorted(site - local - {"BASKET"}):
        out.append(f"row reconcile: {t} is on the site but not in the local row-trades file")
    for t in sorted(local - site):
        out.append(f"row reconcile: {t} is in the local row-trades file but not on the site")
    return out or ["row reconcile: same tickers on both sides"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--preview", action="store_true", default=True)
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--out", type=Path, default=PREVIEW)
    ap.add_argument("--row-trades", type=Path, default=ROW_TRADES)
    a = ap.parse_args(argv)

    calls = load_source(a.source)
    ok, held = split_publishable(calls)
    d = json.loads(btm.DATA.read_text(encoding="utf-8"))
    report = [f"{len(calls)} past calls in source; {len(ok)} pass the check; {len(held)} held back"]
    report += [f"  held: #{c.get('n', '?')} {c.get('ticker')}: {'; '.join(e)}" for c, e in held]
    md = a.row_trades.read_text(encoding="utf-8") if a.row_trades.is_file() else None
    report += reconcile_rows(d, md)

    if a.apply:
        d["past_calls"] = ok
        btm.DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        report.append(f"applied: wrote {len(ok)} past calls to {btm.DATA}; run build_trap_map.py next")
    else:
        out = a.out
        out.mkdir(parents=True, exist_ok=True)
        data, page, index = out / "trap_map.json", out / "trap-map.html", out / "index.html"
        d["past_calls"] = ok
        data.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copy(btm.INDEX, index)
        btm.build(write=True, data=data, page_path=page, index=index)
        # Preview shows every call, including ones still waiting for an evidence link.
        built = json.loads(data.read_text(encoding="utf-8"))
        html = page.read_text(encoding="utf-8")
        allc = [{**{k: c.get(k) for k in PUBLIC}} for c in calls]
        start = html.find("<h2>Past calls</h2>")
        new = btm.render_past_calls(allc, preview=True)
        if start >= 0:
            end = html.find("</table>", start) + len("</table>")
            html = html[:start] + new + html[end:]
        else:
            html = html.replace("</main>", new + "</main>", 1) if "</main>" in html else html.replace("</body>", new + "</body>", 1)
        page.write_text(html, encoding="utf-8")
        report.append(f"preview: {page} (not site/); {len(built['rows'])} rows, {len(allc)} past calls shown")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
