#!/usr/bin/env python3
"""Tests for the evening run's clean-main prep and loud git failures (no stash/autostash).

Uses throwaway git repos in a temp dir; never touches the real checkout or dashboard.db.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import auto_pipeline


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


class CleanMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        sh(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.seed = self.tmp / "seed"
        sh(self.tmp, "clone", "-q", str(self.origin), str(self.seed))
        for repo in (self.seed,):
            sh(repo, "config", "user.email", "t@t"); sh(repo, "config", "user.name", "t")
        (self.seed / "site/data").mkdir(parents=True)
        (self.seed / "site/data/data.js").write_text("v1\n")
        (self.seed / "notes.md").write_text("user\n")
        sh(self.seed, "add", "-A"); sh(self.seed, "commit", "-qm", "v1"); sh(self.seed, "push", "-q", "origin", "main")
        self.work = self.tmp / "work"
        sh(self.tmp, "clone", "-q", str(self.origin), str(self.work))
        sh(self.work, "config", "user.email", "t@t"); sh(self.work, "config", "user.name", "t")
        self._p = [patch.object(auto_pipeline, "WORKSPACE", self.work),
                   patch.object(auto_pipeline, "send_notification")]
        for p in self._p:
            p.start()
        auto_pipeline._EVENING_GIT_ALERT.clear()

    def tearDown(self):
        for p in self._p:
            p.stop()
        auto_pipeline._EVENING_GIT_ALERT.clear()

    def _remote_commit(self, content):
        (self.seed / "site/data/data.js").write_text(content)
        sh(self.seed, "commit", "-qam", content.strip()); sh(self.seed, "push", "-q", "origin", "main")

    def test_recovers_from_stuck_stash_pop_conflict_in_data_js(self):
        # Reproduce the 10/12-10/20 jam: local edit + remote edit + stash pop conflict.
        (self.work / "site/data/data.js").write_text("local\n")
        sh(self.work, "stash")
        self._remote_commit("v2\n")
        sh(self.work, "pull", "-q", "origin", "main")
        (self.work / "site/data/data.js").write_text("local2\n")
        sh(self.work, "commit", "-qam", "x")  # noise commit so stash pop conflicts
        sh(self.work, "reset", "-q", "--hard", "origin/main")
        (self.work / "site/data/data.js").write_text("other\n"); sh(self.work, "commit", "-qam", "o")
        sh(self.work, "reset", "-q", "--hard", "HEAD~1")
        pop = sh(self.work, "stash", "pop")
        self.assertIn("CONFLICT", pop.stdout + pop.stderr)
        sh(self.work, "checkout", "-qb", "side")  # stuck off main too
        (self.work / "notes.md").write_text("user work\n")  # non-generated user work
        self._remote_commit("v3\n")
        out = io.StringIO()
        with redirect_stdout(out):
            ok = auto_pipeline._ensure_main_before_export()
        self.assertTrue(ok, out.getvalue())
        self.assertEqual(sh(self.work, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")
        self.assertEqual(sh(self.work, "rev-parse", "HEAD").stdout, sh(self.work, "rev-parse", "origin/main").stdout)
        self.assertEqual((self.work / "site/data/data.js").read_text(), "v3\n")
        self.assertEqual((self.work / "notes.md").read_text(), "user work\n")  # untouched
        self.assertIn("/tmp/evening-publish-backup-", out.getvalue())
        self.assertEqual(sh(self.work, "stash", "list").stdout.count("cursor-agent-auto-stash"), 0)

    def test_diverged_main_fails_loudly(self):
        (self.work / "notes.md").write_text("local commit\n"); sh(self.work, "commit", "-qam", "local")
        self._remote_commit("v2\n")
        out = io.StringIO()
        with redirect_stdout(out):
            ok = auto_pipeline._ensure_main_before_export()
        self.assertFalse(ok)
        self.assertIn("ALERT evening publish", out.getvalue())

    def test_main_exits_nonzero_on_git_alert(self):
        def fake():
            auto_pipeline._alert_evening_publish("push rejected")
        out = io.StringIO()
        with patch.object(auto_pipeline, "_main", fake), redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                auto_pipeline.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("ALERT evening publish", out.getvalue())

    def test_main_exits_zero_without_alert(self):
        with patch.object(auto_pipeline, "_main", lambda: None):
            auto_pipeline.main()


if __name__ == "__main__":
    unittest.main()
