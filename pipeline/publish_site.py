#!/usr/bin/env python3
"""
Gated site publish: export → validate bundle → git commit/push (site/ only).

Fails closed: if validation fails, nothing is committed. Uses the same iMessage
notifications as auto_pipeline on git failure.

Usage:
  python3 publish_site.py              # export + validate + push
  python3 publish_site.py --dry-run    # export + validate only (no git)
  python3 publish_site.py --no-export  # validate existing site/data + push (no re-export)

Env: GITHUB_PUSH_TOKEN, GITHUB_USERNAME (see auto_pipeline / .env.example)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from workspace_paths import PIPELINE_DIR, SITE_DATA_DIR, STATE_DIR, WORKSPACE_ROOT as WORKSPACE

PIPELINE = PIPELINE_DIR
SITE_DATA = SITE_DATA_DIR
LAST_PUBLISH = STATE_DIR / "last_publish.json"
LAST_ATTEMPT = STATE_DIR / "last_publish_attempt.json"

# Minimum size so we never push an empty or truncated bundle
MIN_DATA_JS_BYTES = 800

# Required substrings in data.js (contract between export_data.generate_website_js and the UI)
# NOTE: tickerScores removed — Alpha/Atrophy UI retired in PR #98 (replaced by Trap Map)
REQUIRED_MARKERS = (
    "const dashboardData",
    "schemaVersion",
    "generatedAt",
    "mainContent",
    "pundits",
)


def _write_attempt(ok: bool, detail: str, extra: dict | None = None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail[:2000],
    }
    if extra:
        payload.update(extra)
    path = LAST_PUBLISH if ok else LAST_ATTEMPT
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_site_bundle(site_data: Path) -> tuple[bool, str]:
    """Return (ok, message). Structural checks only — no JS execution."""
    data_js = site_data / "data.js"
    if not data_js.is_file():
        return False, f"Missing {data_js}"
    raw = data_js.read_bytes()
    if len(raw) < MIN_DATA_JS_BYTES:
        return False, f"data.js too small ({len(raw)} bytes < {MIN_DATA_JS_BYTES})"
    text = raw.decode("utf-8", errors="replace")
    missing = [m for m in REQUIRED_MARKERS if m not in text]
    if missing:
        return False, "data.js missing markers: " + ", ".join(missing)

    status_path = site_data / "status.json"
    if not status_path.is_file():
        return False, f"Missing {status_path}"
    try:
        st = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"status.json invalid JSON: {e}"
    if not st.get("last_pipeline_run"):
        return False, "status.json missing last_pipeline_run"

    pundits_path = site_data / "pundits.json"
    if not pundits_path.is_file():
        return False, f"Missing {pundits_path}"

    # Banner contract: data.js priceSnapshot must include QQQ + BTC (or BTC-USD)
    try:
        js = text
        marker = "priceSnapshot:"
        idx = js.find(marker)
        if idx < 0:
            return False, "data.js missing priceSnapshot"
        brace = js.find("{", idx)
        depth = 0
        end = None
        for i, c in enumerate(js[brace:], brace):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return False, "data.js priceSnapshot braces unbalanced"
        snap = json.loads(js[brace:end])
    except Exception as e:
        return False, f"data.js priceSnapshot unreadable: {e}"
    qqq = snap.get("QQQ") if isinstance(snap, dict) else None
    btc = (snap.get("BTC") or snap.get("BTC-USD")) if isinstance(snap, dict) else None
    def _price_ok(entry) -> bool:
        return isinstance(entry, dict) and entry.get("price") is not None
    if not _price_ok(qqq) or not _price_ok(btc):
        return False, (
            "priceSnapshot missing QQQ and/or BTC — refuse publish "
            f"(QQQ={'ok' if _price_ok(qqq) else 'MISSING'}, "
            f"BTC={'ok' if _price_ok(btc) else 'MISSING'}). "
            "Run fetch_prices.py before export."
        )

    # Fail-closed: conflict markers or invalid Pages JSON/JS/HTML must never ship
    try:
        from market_data_io import scan_site_for_conflict_or_bad_json
        from workspace_paths import SITE_DIR
        ok_scan, scan_msg = scan_site_for_conflict_or_bad_json(SITE_DIR)
        if not ok_scan:
            return False, scan_msg
    except Exception as e:
        return False, f"site conflict/JSON scan failed: {e}"

    return True, "Bundle OK (data.js + status.json + pundits.json + QQQ/BTC + no conflict markers)"


def run_export() -> None:
    sys.path.insert(0, str(PIPELINE))
    from export_data import export_website_data, generate_website_js

    export_website_data()
    generate_website_js()


def main() -> int:
    ap = argparse.ArgumentParser(description="Export, validate, and push site/ only.")
    ap.add_argument("--dry-run", action="store_true", help="Export + validate; do not git push.")
    ap.add_argument("--no-export", action="store_true", help="Skip export; validate existing files then push.")
    args = ap.parse_args()

    print("=" * 60)
    print("Publish site (gated)")
    print("=" * 60)

    if not args.no_export:
        try:
            run_export()
        except Exception as e:
            _write_attempt(False, f"export failed: {e}")
            print(f"✗ Export failed: {e}")
            return 1
    else:
        print("Skipping export (--no-export).")

    ok, msg = validate_site_bundle(SITE_DATA)
    if not ok:
        _write_attempt(False, msg)
        print(f"✗ Validation failed: {msg}")
        try:
            from auto_pipeline import send_notification

            send_notification(
                "Publish site: validation failed",
                msg[:900],
                priority=1,
            )
        except Exception:
            pass
        return 1

    print(f"✓ {msg}")

    if args.dry_run:
        _write_attempt(True, "dry-run: validated only")
        print("Dry run — not pushing.")
        return 0

    sys.path.insert(0, str(PIPELINE))
    from auto_pipeline import git_push

    commit = f"Publish site: validated export ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC)"
    pushed = git_push(commit, pathspecs=["site"])
    if not pushed:
        _write_attempt(False, "git push failed (see notification)")
        return 1

    try:
        from fetch_latest import cleanup_audio_for_site_published_episodes

        cleanup_audio_for_site_published_episodes()
    except Exception as e:
        print(f"  ⚠ Post-publish audio cleanup: {e}")

    sha = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            sha = (r.stdout or "").strip()
    except Exception:
        pass

    _write_attempt(True, "pushed", {"git_head": sha})
    print(f"✓ Publish complete. Recorded in {LAST_PUBLISH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
