#!/usr/bin/env python3
"""Offline public-retirement checks; private content validation is explicit opt-in.

Public CI needs only the location/checksum pointer, never private records or network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "pipeline"
ARCHIVE = Path(os.environ.get("TRAP_MAP_PRIVATE_ARCHIVE", "/workspace/cos/trap_map_archive_2026-11-05")).expanduser().resolve()
TEXT_SUFFIXES = {".html", ".js", ".json", ".css", ".xml", ".txt", ".svg", ".webmanifest"}
RETIRED_REFERENCE = re.compile(r"trap(?:-|_|%2d|%5f)map(?:\.|%2e)(?:html|json)|trap-map-strip|TRAP_STRIP", re.I)
REQUIRED = {"trap_map.json", "trap-map.html", "index.html", "portfolio.json"}
LOCATOR_FIELDS = {"schema_version", "retired_date_CT", "private_repository", "private_archive_path", "private_commit", "ops_archive_path", "manifest_sha256", "public_historical_portfolio_sha256"}


def private_archive_path() -> Path:
    """Resolve a local private fixture, rejecting any location inside this public repo."""
    if ARCHIVE.is_relative_to(ROOT.resolve()):
        raise ValueError("Trap Map records must be outside the public repository")
    return ARCHIVE


def check_locator(pipeline: Path) -> list[str]:
    """Validate public metadata only; deliberately do not open the private archive."""
    errors = []
    try:
        locator = json.loads((pipeline / "trap_map_archive_locator.json").read_text(encoding="utf-8"))
        if set(locator) != LOCATOR_FIELDS:
            errors.append("Private archive locator must contain metadata only, with all required fields")
        required = {"schema_version": 1, "retired_date_CT": "2026-11-05", "private_repository": "jsheppard8989/dragonfly-private", "private_archive_path": "trap_map_archive_2026-11-05", "ops_archive_path": "/workspace/cos/trap_map_archive_2026-11-05"}
        for key, value in required.items():
            if locator.get(key) != value:
                errors.append(f"Private archive locator has invalid {key}")
        for key, length in (("private_commit", 40), ("manifest_sha256", 64), ("public_historical_portfolio_sha256", 64)):
            if not isinstance(locator.get(key), str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, locator[key]):
                errors.append(f"Private archive locator has invalid {key}")
        text = (pipeline / "TRAP_MAP_RETIREMENT.md").read_text(encoding="utf-8")
        for value in ("2026-11-05", "jsheppard8989/dragonfly-private", "trap_map_archive_2026-11-05", "/workspace/cos/trap_map_archive_2026-11-05", "Nothing historical was deleted"):
            if value not in text:
                errors.append("Private archive locator document omits the retirement/preservation location")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"Private archive locator missing or invalid: {exc}")
    return errors


def check_archive(archive: Path, baselines: dict | None = None) -> list[str]:
    """Validate frozen byte hashes, all record ids/totals and the pre-retirement baseline."""
    errors = []
    if archive.resolve().is_relative_to(ROOT.resolve()):
        return ["Private archive must not be stored in the public repository"]
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
        if path.name.lower() in ("trap-map.html", "trap_map.json", "trap_map_home.json"):
            errors.append(f"Retired Trap Map public file remains: {path.relative_to(site)}")
        if path.suffix.lower() in TEXT_SUFFIXES and RETIRED_REFERENCE.search(path.read_text(encoding="utf-8", errors="replace")):
            errors.append(f"Retired Trap Map public reference remains: {path.relative_to(site)}")
    return errors


def check_repository_absence(repo: Path) -> list[str]:
    """No record/archive files may remain anywhere in the public checkout, not just Pages."""
    errors = []
    if (repo / "pipeline/private_archive/trap_map").exists():
        errors.append("Trap Map record archive still exists in the public repository")
    for directory, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__", ".pytest_cache")]
        for name in files:
            if name.lower() in ("trap_map.json", "trap-map.html", "trap_map_home.json"):
                errors.append(f"Trap Map record payload remains in public repository: {(Path(directory) / name).relative_to(repo)}")
    return errors


def check_retirement(site: Path, pipeline: Path = PIPELINE, baselines: dict | None = None) -> list[str]:
    """Public-only, offline guard. Never read or fetch the private historical records."""
    errors = check_locator(pipeline) + check_public_absence(site) + check_repository_absence(pipeline.parent)
    try:
        locator = json.loads((pipeline / "trap_map_archive_locator.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256((site / "data/portfolio.json").read_bytes()).hexdigest()
        if digest != locator["public_historical_portfolio_sha256"]:
            errors.append("Public portfolio.json differs from the frozen historical basket record")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Frozen public historical record/locator missing or invalid: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Public/offline pointer and absence checks")
    parser.add_argument("--check-private", action="store_true", help="Also verify local private records; never fetches")
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    parser.add_argument("--pipeline", type=Path, default=PIPELINE)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    errors = check_retirement(args.site, args.pipeline)
    if args.check_private:
        errors += check_archive(args.archive)
        try:
            locator = json.loads((args.pipeline / "trap_map_archive_locator.json").read_text(encoding="utf-8"))
            if hashlib.sha256((args.archive / "manifest.json").read_bytes()).hexdigest() != locator["manifest_sha256"]:
                errors.append("Private archive manifest differs from the pinned manifest-of-record")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Private manifest-of-record check failed: {exc}")
    for error in errors:
        print("ALERT archive guard:", error)
    if not errors:
        print("Private archive locator preserved; no Trap Map records in public repository or Pages")
        if args.check_private:
            print("Local private archive and original SHA-256 manifest verified")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
