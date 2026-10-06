#!/usr/bin/env python3
"""Unit tests for pre-export checkout safety (auto_pipeline._ensure_main_before_export)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import auto_pipeline


class TestPreExportCheckout(unittest.TestCase):
    """Test the pre-export main branch check and stash logic."""

    def test_git_head_branch_returns_branch_name(self):
        with patch("auto_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            result = auto_pipeline._git_head_branch()
            self.assertEqual(result, "main")

    def test_git_head_branch_returns_none_on_failure(self):
        with patch("auto_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = auto_pipeline._git_head_branch()
            self.assertIsNone(result)

    def test_has_uncommitted_site_changes_true(self):
        with patch("auto_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=" M site/data/data.js\n")
            result = auto_pipeline._has_uncommitted_site_changes()
            self.assertTrue(result)

    def test_has_uncommitted_site_changes_false(self):
        with patch("auto_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = auto_pipeline._has_uncommitted_site_changes()
            self.assertFalse(result)

    def test_ensure_main_before_export_already_on_main(self):
        with patch("auto_pipeline._git_head_branch", return_value="main"):
            result = auto_pipeline._ensure_main_before_export()
            self.assertTrue(result)

    def test_ensure_main_before_export_switches_to_main_no_changes(self):
        with patch("auto_pipeline._git_head_branch", return_value="feature/test"), \
             patch("auto_pipeline._has_uncommitted_site_changes", return_value=False), \
             patch("auto_pipeline.subprocess.run") as mock_run, \
             patch("auto_pipeline.send_notification"):
            mock_run.return_value = MagicMock(returncode=0)
            result = auto_pipeline._ensure_main_before_export()
            self.assertTrue(result)
            checkout_calls = [c for c in mock_run.call_args_list 
                              if "checkout" in str(c) and "main" in str(c)]
            self.assertEqual(len(checkout_calls), 1)

    def test_ensure_main_before_export_stashes_then_switches(self):
        with patch("auto_pipeline._git_head_branch", return_value="cursor/some-branch"), \
             patch("auto_pipeline._has_uncommitted_site_changes", return_value=True), \
             patch("auto_pipeline.subprocess.run") as mock_run, \
             patch("auto_pipeline.send_notification"):
            mock_run.return_value = MagicMock(returncode=0)
            result = auto_pipeline._ensure_main_before_export()
            self.assertTrue(result)
            stash_calls = [c for c in mock_run.call_args_list if "stash" in str(c)]
            checkout_calls = [c for c in mock_run.call_args_list 
                              if "checkout" in str(c) and "main" in str(c)]
            self.assertEqual(len(stash_calls), 1)
            self.assertEqual(len(checkout_calls), 1)

    def test_ensure_main_before_export_fails_on_checkout_error(self):
        with patch("auto_pipeline._git_head_branch", return_value="cursor/some-branch"), \
             patch("auto_pipeline._has_uncommitted_site_changes", return_value=False), \
             patch("auto_pipeline.subprocess.run") as mock_run, \
             patch("auto_pipeline.send_notification") as mock_notify:
            mock_run.return_value = MagicMock(
                returncode=1, 
                stderr="error: pathspec 'main' did not match any file(s) known to git"
            )
            result = auto_pipeline._ensure_main_before_export()
            self.assertFalse(result)
            self.assertTrue(mock_notify.called)


if __name__ == "__main__":
    unittest.main()
