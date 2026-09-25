"""READY marker for the 08:05 CT pre-open job.

`write_ready()` must be the job's LAST step: it refuses to run while any file
under handoff/<date>/ is uncommitted or untracked, so READY can never be
visible before the files it lists. It lists every file present (path, bytes,
sha256), then commits and pushes READY on its own.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dragonfly.engine import core
from dragonfly.engine.core import EngineError, iso
from dragonfly.engine.gitops import PrivateRepo

log = logging.getLogger("dragonfly.engine")

READY_NAME = "READY"


def _is_ours(status_line: str, rel_dir: str) -> bool:
    path = status_line[3:].strip().strip('"')
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path == f"{rel_dir}/{READY_NAME}" or path.startswith(f"{rel_dir}/cards/")


def ready_document(repo_path: Path, session_date: date, now: datetime) -> dict:
    rel_dir = f"handoff/{session_date.isoformat()}"
    base = Path(repo_path) / rel_dir
    files = []
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = path.relative_to(base).as_posix()
        if rel == READY_NAME or rel.startswith("cards/") or path.name.startswith("."):
            continue
        data = path.read_bytes()
        files.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {
        "schema_version": "1.0.0",
        "marker": "READY",
        "session_date": session_date.isoformat(),
        "as_of": iso(now),
        "files": files,
    }


def write_ready(repo_path: Path, session_date: date, now: Optional[datetime] = None,
                pull: bool = True, push: bool = True) -> dict:
    repo = PrivateRepo(Path(repo_path))
    rel_dir = f"handoff/{session_date.isoformat()}"
    base = Path(repo_path) / rel_dir
    if not base.is_dir():
        raise EngineError(f"{rel_dir}/ does not exist; nothing to mark READY")
    dirty = [line for line in repo.dirty([rel_dir]) if not _is_ours(line, rel_dir)]
    if dirty:
        raise EngineError(
            "READY refused: handoff files are not committed yet. Commit (and push) every other "
            f"handoff file first; READY is the last step. Dirty: {dirty}"
        )
    if pull:
        repo.sync()
    doc = ready_document(Path(repo_path), session_date, now or core.now_ct())
    if not doc["files"]:
        raise EngineError(f"READY refused: {rel_dir}/ has no files")
    errs = core.schema_errors("engine_ready.schema.json", doc)
    if errs:
        raise EngineError(f"READY marker failed its schema: {errs}")
    path = base / READY_NAME
    path.write_text(core.dumps(doc), encoding="utf-8")
    repo.commit_and_push([f"{rel_dir}/{READY_NAME}"], f"pre-open {session_date}: READY ({len(doc['files'])} files)", push=push)
    log.info("READY written for %s with %d files", session_date, len(doc["files"]))
    return doc
