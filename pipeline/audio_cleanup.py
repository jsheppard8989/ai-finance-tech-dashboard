#!/usr/bin/env python3
"""Conservative cleanup for downloaded podcast source audio.

Only direct children of the generated source-audio directories are considered:
workspace/audio, workspace/whisper_queue, and pipeline/audio. Website debate and
archive audio is never a cleanup target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from workspace_paths import (
    AUDIO_DIR,
    DB_PATH,
    PIPELINE_AUDIO_DIR,
    PIPELINE_DIR,
    SITE_DATA_DIR,
    SITE_DIR,
    TRANSCRIPT_DIR,
    WHISPER_QUEUE_DIR,
)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
SOURCE_AUDIO_DIRS = (AUDIO_DIR, WHISPER_QUEUE_DIR, PIPELINE_AUDIO_DIR)
PUBLISHED_EPISODE_RE = re.compile(r'"podcast_episode_id"\s*:\s*(\d+)')


@dataclass
class AudioDecision:
    path: str
    bytes: int
    action: str
    reason: str
    episode_id: int | None = None


def _safe_filename_stem(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", (value or "").lower())
    value = re.sub(r"[-\s]+", "_", value).strip("_")[:32]
    return value or "ep"


def _normalized_stems(value: str) -> set[str]:
    """Filename stem variants used by current and legacy downloaders."""
    if not value:
        return set()
    raw = Path(value).stem
    decoded = unquote(raw)
    return {candidate.casefold() for candidate in (raw, decoded) if candidate}


def published_episode_ids(site_data: Path = SITE_DATA_DIR) -> set[int]:
    """Episode IDs present in the validated/pushed website bundle."""
    data_js = site_data / "data.js"
    if not data_js.is_file():
        return set()
    text = data_js.read_text(encoding="utf-8", errors="replace")
    return {int(match) for match in PUBLISHED_EPISODE_RE.findall(text)}


def _resolve_transcript(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path.strip()).expanduser()
    candidates = [path] if path.is_absolute() else [PIPELINE_DIR / path, TRANSCRIPT_DIR / path.name]
    if path.is_absolute():
        # Handles DB rows migrated from the former OpenClaw workspace.
        candidates.append(TRANSCRIPT_DIR / path.name)
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".txt":
            return candidate.resolve()
    return None


def _curate_filename_stem(podcast: str, title: str, audio_url: str) -> str:
    safe_podcast = "".join(char if char.isalnum() else "_" for char in (podcast or "").lower())[:40]
    safe_title = "".join(char if char.isalnum() else "_" for char in (title or "").lower())[:60]
    digest = hashlib.md5((audio_url or "").encode("utf-8")).hexdigest()[:8]
    return f"{safe_podcast}_{safe_title}_{digest}".casefold()


def _episode_metadata(row: sqlite3.Row, transcript_dir: Path) -> dict:
    raw_path = str(row["transcript_path"] or "").strip()
    if not raw_path:
        return {}
    candidates = [Path(raw_path).with_suffix(".meta.json"), transcript_dir / f"{Path(raw_path).stem}.meta.json"]
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _episode_aliases(row: sqlite3.Row, transcript_dir: Path = TRANSCRIPT_DIR) -> set[str]:
    aliases = _normalized_stems(row["transcript_path"] or "")
    metadata = _episode_metadata(row, transcript_dir)
    audio_url = row["audio_url"] or metadata.get("audio_url") or ""
    if audio_url:
        aliases.update(_normalized_stems(Path(urlparse(audio_url).path).name))
        aliases.add(
            _curate_filename_stem(
                str(metadata.get("podcast_name") or row["podcast_name"] or ""),
                str(metadata.get("episode_title") or row["episode_title"] or ""),
                str(audio_url),
            )
        )

    published = str(
        row["published_date"] or metadata.get("published_date") or row["episode_date"] or ""
    ).replace("-", "")[:8]
    guid = row["rss_guid"] or metadata.get("rss_guid") or ""
    title = str(metadata.get("episode_title") or row["episode_title"] or "")
    podcast = str(metadata.get("podcast_name") or row["podcast_name"] or "")
    unique = _safe_filename_stem(guid) if guid and len(guid) < 50 and "/" not in guid else _safe_filename_stem(title)
    pod_slug = _safe_filename_stem(podcast)[:20]
    if published:
        aliases.add(f"{pod_slug}_{published}_{unique}".casefold())
    return aliases


def _load_episode_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            pe.*,
            li.id AS insight_id,
            ddc.id AS deep_dive_id,
            ddc.overview AS deep_dive_overview,
            EXISTS (
                SELECT 1 FROM processing_queue pq
                WHERE pq.item_type = 'podcast'
                  AND pq.item_id = pe.id
                  AND pq.status != 'completed'
            ) AS active_processing,
            EXISTS (
                SELECT 1 FROM deep_dive_generation_failures dgf
                WHERE dgf.podcast_episode_id = pe.id
                  AND COALESCE(dgf.status, 'pending_retry') != 'resolved'
            ) AS active_deep_dive_failure
        FROM podcast_episodes pe
        LEFT JOIN latest_insights li ON li.podcast_episode_id = pe.id
        LEFT JOIN deep_dive_content ddc
          ON ddc.insight_id = li.id
         AND (ddc.podcast_episode_id = pe.id OR ddc.podcast_episode_id IS NULL)
        ORDER BY pe.id DESC
        """
    ).fetchall()


def _source_audio_files(source_dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in source_dirs:
        if not directory.is_dir():
            continue
        files.extend(
            path for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        )
    return sorted(files, key=lambda path: str(path))


def _meta_episode_id(path: Path, rows: list[sqlite3.Row]) -> int | None:
    candidates = [path.with_suffix(".meta.json"), TRANSCRIPT_DIR / f"{path.stem}.meta.json"]
    meta = None
    for candidate in candidates:
        try:
            if candidate.is_file():
                meta = json.loads(candidate.read_text(encoding="utf-8"))
                break
        except (OSError, json.JSONDecodeError):
            continue
    if not isinstance(meta, dict):
        return None

    guid = str(meta.get("rss_guid") or "").strip()
    if guid:
        matches = [int(row["id"]) for row in rows if str(row["rss_guid"] or "").strip() == guid]
        if len(set(matches)) == 1:
            return matches[0]

    podcast = str(meta.get("podcast_name") or meta.get("podcast") or "").strip().casefold()
    title = str(meta.get("episode_title") or meta.get("title") or "").strip().casefold()
    matches = [
        int(row["id"])
        for row in rows
        if podcast
        and title
        and str(row["podcast_name"] or "").strip().casefold() == podcast
        and str(row["episode_title"] or "").strip().casefold() == title
    ]
    return matches[0] if len(set(matches)) == 1 else None


def _retention_reason(row: sqlite3.Row, published_ids: set[int]) -> str | None:
    if _resolve_transcript(row["transcript_path"]) is None:
        return "pending_transcription_or_missing_transcript"
    if not bool(row["is_processed"]) or bool(row["active_processing"]):
        return "pending_or_failed_analysis"
    if (
        row["insight_id"] is None
        or row["deep_dive_id"] is None
        or not str(row["deep_dive_overview"] or "").strip()
        or bool(row["active_deep_dive_failure"])
    ):
        return "pending_or_failed_deep_dive"
    if int(row["id"]) not in published_ids:
        return "not_in_published_site_bundle"
    return None


def plan_audio_cleanup(
    *,
    db_path: Path = DB_PATH,
    site_data: Path = SITE_DATA_DIR,
    source_dirs: Iterable[Path] = SOURCE_AUDIO_DIRS,
    transcript_dir: Path = TRANSCRIPT_DIR,
) -> list[AudioDecision]:
    """Classify every generated source-audio file without modifying disk."""
    published_ids = published_episode_ids(site_data)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = _load_episode_rows(conn)
    finally:
        conn.close()

    rows_by_id = {int(row["id"]): row for row in rows}
    ids_by_alias: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        for alias in _episode_aliases(row, transcript_dir):
            ids_by_alias[alias].add(int(row["id"]))

    decisions: list[AudioDecision] = []
    for path in _source_audio_files(source_dirs):
        size = path.stat().st_size
        matching_ids: set[int] = set()
        for stem in _normalized_stems(path.name):
            matching_ids.update(ids_by_alias.get(stem, set()))
        meta_id = _meta_episode_id(path, rows)
        if meta_id is not None:
            matching_ids.add(meta_id)

        if not matching_ids:
            decisions.append(AudioDecision(str(path), size, "retain", "unmatched_source_audio"))
            continue
        if len(matching_ids) != 1:
            decisions.append(AudioDecision(str(path), size, "retain", "ambiguous_episode_match"))
            continue

        episode_id = next(iter(matching_ids))
        reason = _retention_reason(rows_by_id[episode_id], published_ids)
        decisions.append(
            AudioDecision(
                str(path),
                size,
                "delete" if reason is None else "retain",
                "eligible_published_episode" if reason is None else reason,
                episode_id,
            )
        )
    return decisions


def execute_audio_cleanup(decisions: Iterable[AudioDecision], *, dry_run: bool = True) -> dict:
    """Apply a reviewed plan and return exact counts/bytes."""
    decisions = list(decisions)
    deleted_count = 0
    deleted_bytes = 0
    errors: list[str] = []
    for decision in decisions:
        if decision.action != "delete" or dry_run:
            continue
        path = Path(decision.path)
        try:
            size = path.stat().st_size
            path.unlink()
            deleted_count += 1
            deleted_bytes += size
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    reasons = Counter(decision.reason for decision in decisions if decision.action == "retain")
    eligible = [decision for decision in decisions if decision.action == "delete"]
    return {
        "dry_run": dry_run,
        "source_audio_files": len(decisions),
        "eligible_files": len(eligible),
        "eligible_bytes": sum(decision.bytes for decision in eligible),
        "deleted_files": deleted_count,
        "deleted_bytes": deleted_bytes,
        "retained_files": sum(reasons.values()),
        "retained_by_reason": dict(sorted(reasons.items())),
        "errors": errors,
        "decisions": [asdict(decision) for decision in decisions],
    }


def protected_site_audio_summary(site_dir: Path = SITE_DIR) -> dict:
    """Report website audio that is explicitly outside cleanup scope."""
    root = site_dir / "audio"
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ] if root.is_dir() else []
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def cleanup_published_episode_audio(*, dry_run: bool = True) -> dict:
    decisions = plan_audio_cleanup()
    report = execute_audio_cleanup(decisions, dry_run=dry_run)
    report["protected_site_audio"] = protected_site_audio_summary()
    return report


def _print_report(report: dict) -> None:
    mode = "DRY RUN" if report["dry_run"] else "EXECUTED"
    print(f"Audio cleanup {mode}")
    print(
        f"  source={report['source_audio_files']} eligible={report['eligible_files']} "
        f"eligible_bytes={report['eligible_bytes']} deleted={report['deleted_files']} "
        f"deleted_bytes={report['deleted_bytes']}"
    )
    for reason, count in report["retained_by_reason"].items():
        print(f"  retained {count}: {reason}")
    protected = report["protected_site_audio"]
    print(f"  protected site audio: {protected['files']} file(s), {protected['bytes']} bytes")
    for error in report["errors"]:
        print(f"  ERROR: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report or delete eligible downloaded podcast audio.")
    parser.add_argument("--execute", action="store_true", help="Delete eligible files; default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable report.")
    args = parser.parse_args()
    report = cleanup_published_episode_audio(dry_run=not args.execute)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
