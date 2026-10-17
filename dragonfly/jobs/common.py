"""Shared plumbing for the prep and pre-open jobs."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from dragonfly.engine import core
from dragonfly.engine.core import EngineError

log = logging.getLogger("dragonfly.jobs")

ENV_REPO = "DRAGONFLY_PRIVATE_DIR"
ENV_BOOK = "DRAGONFLY_BOOK"


class JobError(EngineError):
    """Loud job failure: nothing further is written (and never READY)."""


class _CTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802
        return datetime.fromtimestamp(record.created, core.tz()).isoformat(timespec="seconds")


def setup_logging(verbose: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_CTFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for name in ("dragonfly.jobs", "dragonfly.engine"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [handler]
        lg.setLevel(logging.DEBUG if verbose else logging.INFO)
        lg.propagate = False


def default_repo() -> Path:
    return Path(os.environ.get(ENV_REPO) or Path.home() / "projects" / "dragonfly-private")


def default_book_path() -> Path:
    """$DRAGONFLY_BOOK, else <state dir>/book.json (dragonfly/state/live/book.json)."""
    override = os.environ.get(ENV_BOOK)
    return Path(override) if override else core.default_book_path()


def now_fn(start_at: Optional[str]) -> Callable[[], datetime]:
    """--now shifts the clock: reads start_at at launch, then advances in real time.

    Same semantics as `python3 -m dragonfly.engine --now`. It only moves the
    job's session clock (dates, as_of stamps). The load guards
    (dragonfly/guards.py) always use the real wall clock.
    """
    if not start_at:
        return core.now_ct
    offset = core.parse_iso(start_at) - core.now_ct()
    return lambda: (core.now_ct() + offset).replace(microsecond=0)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    atomic_write(path, json.dumps(obj, indent=1, default=str) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@contextmanager
def job_lock(name: str, state: Optional[Path] = None) -> Iterator[Path]:
    """One instance per job at a time (a non-blocking flock in <state>/jobs/)."""
    root = Path(state) if state else core.state_dir()
    path = root / "jobs" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobError(f"another {name} job holds {path}; refusing to run twice") from exc
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield path
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f
