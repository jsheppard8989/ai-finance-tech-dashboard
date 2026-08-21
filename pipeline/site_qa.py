#!/usr/bin/env python3
"""
Site QA — checks the podcast dashboard bundle (export + homepage).

Usage:
  python3 site_qa.py
  python3 site_qa.py --notify
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from workspace_paths import SITE_DATA_DIR, SITE_DIR, STATE_DIR

WORKSPACE = SITE_DIR.parent
INDEX_HTML = SITE_DIR / "index.html"
REPORT_PATH = STATE_DIR / "site_qa_report.json"
LIVE_STATUS_URL = "https://jsheppard8989.github.io/ai-finance-tech-dashboard/data/status.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def run_checks() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    score = 100

    def add(severity: str, area: str, message: str, fix: str = "") -> None:
        nonlocal score
        findings.append({"severity": severity, "area": area, "message": message, "fix": fix})
        if severity == "fail":
            score -= 15
        elif severity == "warn":
            score -= 5

    data_js = SITE_DATA_DIR / "data.js"
    if not data_js.is_file():
        add("fail", "data", "site/data/data.js missing", "python3 pipeline/export_data.py")
    elif data_js.stat().st_size < 800:
        add("fail", "data", f"data.js too small ({data_js.stat().st_size} bytes)", "Re-run export")

    status_path = SITE_DATA_DIR / "status.json"
    if not status_path.is_file():
        add("warn", "data", "status.json missing", "python3 pipeline/export_data.py")
    else:
        try:
            local_status = json.loads(status_path.read_text(encoding="utf-8"))
            local_run = _parse_timestamp(local_status["last_pipeline_run"])
            request = Request(LIVE_STATUS_URL, headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=15) as response:
                live_status = json.load(response)
            live_run = _parse_timestamp(live_status["last_pipeline_run"])
            lag_hours = (local_run - live_run).total_seconds() / 3600
            if lag_hours > 2:
                add(
                    "fail",
                    "deployment",
                    f"Live site is {lag_hours:.1f} hours behind the local export",
                    "Check the Deploy to GitHub Pages workflow and github-pages environment",
                )
            live_age_hours = (datetime.now(timezone.utc) - live_run).total_seconds() / 3600
            if live_age_hours > 30:
                add(
                    "fail",
                    "deployment",
                    f"Live site has not updated for {live_age_hours:.1f} hours",
                    "Check the pipeline scheduler and Pages deployment workflow",
                )
        except Exception as exc:
            add("warn", "deployment", f"Could not verify live site freshness: {exc}")

    if INDEX_HTML.is_file():
        html = INDEX_HTML.read_text(encoding="utf-8", errors="replace")
        if "Latest insights" not in html:
            add("fail", "homepage", "Homepage missing Latest insights section", "")
        if "debait.html" not in html or "home-debate-listen" not in html:
            add("warn", "homepage", "Homepage missing debate listen links", "Restore Long & Short nav + home-debate-listen")
    else:
        add("fail", "homepage", "site/index.html missing", "")

    if not (SITE_DIR / "debait.html").is_file():
        add("warn", "site", "debait.html missing", "Restore site/debait.html for The Long and Short of It")

    fails = sum(1 for f in findings if f["severity"] == "fail")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    ok = fails == 0

    return {
        "ok": ok,
        "score": max(0, score),
        "checked_at": _now(),
        "fail_count": fails,
        "warn_count": warns,
        "findings": findings,
        "summary": "Site QA passed." if ok else f"{fails} blocking issue(s), {warns} warning(s).",
    }


def write_report(report: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


def print_brief(report: dict[str, Any]) -> None:
    print(f"\n=== Site QA ({report['checked_at']}) ===")
    print(report["summary"])
    print(f"Score: {report['score']}/100\n")
    for item in report["findings"]:
        print(f"[{item['severity'].upper()}] {item['area']}: {item['message']}")
        if item.get("fix"):
            print(f"       → {item['fix']}")
    print()


def notify_pushover(report: dict[str, Any]) -> None:
    if report.get("ok"):
        return
    script = WORKSPACE / "pushover.sh"
    if not script.is_file():
        return
    subprocess.run(
        [str(script), "Site QA failed", report["summary"][:900]],
        check=False,
        cwd=str(WORKSPACE),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="QA the podcast dashboard site.")
    ap.add_argument("--notify", action="store_true")
    args = ap.parse_args()
    report = run_checks()
    write_report(report)
    print_brief(report)
    if args.notify:
        notify_pushover(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
