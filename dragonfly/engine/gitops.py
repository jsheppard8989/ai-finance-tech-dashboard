"""Git plumbing for the local dragonfly-private checkout.

Cheap change detection with `git ls-remote`; pull (rebase) only when the
remote ref moved. Pushes retry on non-fast-forward with a rebase. The engine
only ever stages paths it owns (handoff/<date>/cards/ and READY), so a rebase
over box-agent inbox commits cannot conflict; if one does, it aborts loudly.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from dragonfly.engine.core import EngineError

log = logging.getLogger("dragonfly.engine")

PUSH_RETRIES = 5
_NON_FF_MARKERS = ("non-fast-forward", "fetch first", "rejected", "failed to push", "stale info")


class GitError(EngineError):
    pass


class PrivateRepo:
    def __init__(self, path: Path, remote: str = "origin", branch: Optional[str] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.path = Path(path)
        self.remote = remote
        self.sleep = sleep
        if not (self.path / ".git").exists():
            raise GitError(f"{self.path} is not a git checkout of dragonfly-private")
        self.branch = branch or self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if self.branch == "HEAD":
            raise GitError(f"{self.path} is on a detached HEAD")

    # -------------------------------------------------------------- basics
    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=str(self.path), capture_output=True, text=True,
            env=None, timeout=120,
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(self.path), capture_output=True, text=True, timeout=120)

    def remote_sha(self) -> str:
        out = self.git("ls-remote", self.remote, f"refs/heads/{self.branch}")
        line = out.strip().split("\n")[0] if out.strip() else ""
        if not line:
            raise GitError(f"remote {self.remote} has no branch {self.branch}")
        return line.split()[0]

    def tracking_sha(self) -> Optional[str]:
        proc = self._run("rev-parse", "--verify", "--quiet", f"refs/remotes/{self.remote}/{self.branch}")
        return proc.stdout.strip() or None

    def head_sha(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    # -------------------------------------------------------------- sync
    def sync(self) -> bool:
        """Pull only when the remote ref moved (cheap ls-remote). True if it pulled."""
        sha = self.remote_sha()
        if sha == self.tracking_sha():
            return False
        self.pull_rebase()
        return True

    def is_ancestor(self, a: str, b: str) -> bool:
        return self._run("merge-base", "--is-ancestor", a, b).returncode == 0

    def pull_rebase(self) -> None:
        proc = self._run("pull", "--rebase", "--quiet", self.remote, self.branch)
        if proc.returncode != 0:
            self._run("rebase", "--abort")
            raise GitError(f"git pull --rebase failed: {proc.stderr.strip() or proc.stdout.strip()}")

    # -------------------------------------------------------------- write
    def dirty(self, paths: Sequence[str]) -> List[str]:
        out = self.git("status", "--porcelain", "--untracked-files=all", "--", *paths)
        return [line for line in out.splitlines() if line.strip()]

    def commit_paths(self, paths: Sequence[str], message: str) -> bool:
        """Stage and commit only `paths`. False when there was nothing to commit."""
        if not self.dirty(paths):
            return False
        self.git("add", "-A", "--", *paths)
        proc = self._run("diff", "--cached", "--quiet", "--", *paths)
        if proc.returncode == 0:
            return False
        self.git("commit", "--quiet", "-m", message, "--", *paths)
        return True

    def ahead(self) -> bool:
        tracking = self.tracking_sha()
        if tracking is None:
            return True
        return self.head_sha() != tracking and not self.is_ancestor("HEAD", tracking)

    def push(self) -> None:
        """Push HEAD; on non-fast-forward, rebase onto the remote and retry."""
        last = ""
        for attempt in range(1, PUSH_RETRIES + 1):
            proc = self._run("push", "--quiet", self.remote, f"HEAD:refs/heads/{self.branch}")
            if proc.returncode == 0:
                self._run("fetch", "--quiet", self.remote, self.branch)
                return
            last = (proc.stderr or proc.stdout).strip()
            if not any(k in last for k in _NON_FF_MARKERS):
                raise GitError(f"git push failed: {last}")
            log.warning("push rejected (attempt %d/%d), rebasing: %s", attempt, PUSH_RETRIES, last.splitlines()[-1] if last else "")
            self.pull_rebase()
            self.sleep(min(2.0 * attempt, 10.0))
        raise GitError(f"git push still rejected after {PUSH_RETRIES} rebases: {last}")

    def commit_and_push(self, paths: Sequence[str], message: str, push: bool = True) -> bool:
        committed = self.commit_paths(paths, message)
        if push and (committed or self.ahead()):
            self.push()
        return committed
