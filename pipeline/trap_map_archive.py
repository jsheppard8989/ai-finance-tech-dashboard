#!/usr/bin/env python3
"""Fail-closed preservation and public-absence checks for the retired Trap Map.

The archive is outside Pages, not access-controlled: the GitHub repository is public.
No quotes, network access, database access or writes are performed by this checker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "pipeline/private_archive/trap_map"
TEXT_SUFFIXES = {".html", ".js", ".json", ".css", ".xml", ".txt", ".svg", ".webmanifest"}
RETIRED_REFERENCE = re.compile(r"trap(?:-|_|%2d|%5f)map(?:\.|%2e)(?:html|json)|trap-map-strip|TRAP_STRIP", re.I)
REQUIRED = {"trap_map.json", "trap-map.html", "index.html", "portfolio.json"}


def check_archive(archive: Path, baselines: dict | None = None) -> list[str]:
    """Validate frozen byte hashes, all record ids/totals and the pre-retirement baseline."""
    errors = []
    try:
        manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        if manifest["schema_version"] != 1 or manifest["retired_date_CT"] != "2026-11-05":
            return ["Trap Map archive manifest has an invalid version/date"]
        if not REQUIRED.issubset(files):
            return ["Trap Map archive manifest omits required records or rendered outputs"]
        if len([name for name in files if name.startswith("sources/")]) < 5:
            errors.append("Trap Map archive original source snapshots are missing")
        for name, digest in files.items():
            path = archive / name
            if not path.resolve().is_relative_to(archive.resolve()) or path.is_symlink():
                errors.append(f"Trap Map archive contains unsafe path {name}")
            elif not path.is_file():
                errors.append(f"Trap Map archive file missing: {name}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append(f"Trap Map archive hash mismatch: {name}")
        records = json.loads((archive / "trap_map.json").read_text(encoding="utf-8"))
        if [r["id"] for r in records["rows"]] != manifest["record_ids"]:
            errors.append("Trap Map archive record ids do not match the preserved snapshot")
        if records["totals"] != manifest["snapshot_totals"]:
            errors.append("Trap Map archive totals do not match the preserved snapshot")
        # During the removal PR, the live baseline still has the public records/page.
        # Require byte preservation, not merely a replacement with an empty archive.
        for ref, baseline in (baselines or {}).items():
            for public_name, archived_name in (("data/trap_map.json", "trap_map.json"),
                                               ("trap-map.html", "trap-map.html")):
                old = baseline.get(public_name)
                if old is not None and hashlib.sha256(old.encode("utf-8")).hexdigest() != files[archived_name]:
                    errors.append(f"Trap Map archive does not preserve {public_name} from {ref}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Trap Map archive missing or invalid: {exc}")
    return errors


def check_public_absence(site: Path) -> list[str]:
    errors = []
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        if path.name in ("trap-map.html", "trap_map.json", "trap_map_home.json"):
            errors.append(f"Retired Trap Map public file remains: {path.relative_to(site)}")
        if path.suffix.lower() in TEXT_SUFFIXES and RETIRED_REFERENCE.search(path.read_text(encoding="utf-8", errors="replace")):
            errors.append(f"Retired Trap Map public reference remains: {path.relative_to(site)}")
    return errors


def check_retirement(site: Path, archive: Path, baselines: dict | None = None) -> list[str]:
    errors = check_archive(archive, baselines) + check_public_absence(site)
    try:
        frozen = (archive / "portfolio.json").read_bytes()
        if (site / "data/portfolio.json").read_bytes() != frozen:
            errors.append("Public portfolio.json differs from the frozen historical basket record")
    except OSError as exc:
        errors.append(f"Frozen historical portfolio.json missing: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    errors = check_retirement(args.site, args.archive)
    for error in errors:
        print("ALERT archive guard:", error)
    if not errors:
        print("Trap Map archive preserved; no retired public files or references")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
