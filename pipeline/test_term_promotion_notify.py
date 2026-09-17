#!/usr/bin/env python3
"""Tests for term_promotion_notify.py opt-in gating.

Verifies that iMessage notifications are DISABLED by default and only sent when
TERM_PROMOTION_IMESSAGE=1 is explicitly set.

The iMessage control plane for Overton YES/NO decisions is deprecated;
keep/drop decisions now stay in the Grok Bot / G lane.
"""

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


def test_notify_skipped_when_imessage_disabled():
    """Without TERM_PROMOTION_IMESSAGE=1, notify_promoted_term should NOT call send_imessage.sh."""
    with TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "state"
        state_dir.mkdir()
        workspace_dir = Path(tmpdir) / "workspace"
        workspace_dir.mkdir()

        fake_script = workspace_dir / "send_imessage.sh"
        fake_script.write_text("#!/bin/bash\necho sent\n")
        fake_script.chmod(0o755)

        log_file = state_dir / "term_promotion_notify_log.jsonl"

        with mock.patch.dict(os.environ, {}, clear=True):
            import importlib
            import term_promotion_notify
            importlib.reload(term_promotion_notify)
            
            with mock.patch.object(term_promotion_notify, "STATE_DIR", state_dir):
                with mock.patch.object(term_promotion_notify, "IMESSAGE_SCRIPT", fake_script):
                    with mock.patch.object(term_promotion_notify, "NOTIFY_LOG_FILE", log_file):
                        with mock.patch.object(term_promotion_notify.subprocess, "run") as mock_run:
                            term_promotion_notify.notify_promoted_term({"id": 1, "term": "Test Term"})
                            mock_run.assert_not_called()

        assert log_file.exists(), "Log file should be written"
        log_content = log_file.read_text()
        assert "skipped" in log_content
        assert "iMessage disabled" in log_content


def test_notify_skipped_logs_correct_reason():
    """Log entry should clearly state iMessage is disabled."""
    with TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "state"
        state_dir.mkdir()
        workspace_dir = Path(tmpdir) / "workspace"
        workspace_dir.mkdir()

        fake_script = workspace_dir / "send_imessage.sh"
        fake_script.write_text("#!/bin/bash\necho sent\n")
        fake_script.chmod(0o755)

        log_file = state_dir / "term_promotion_notify_log.jsonl"

        with mock.patch.dict(os.environ, {"TERM_PROMOTION_IMESSAGE": ""}, clear=True):
            import importlib
            import term_promotion_notify
            importlib.reload(term_promotion_notify)
            
            with mock.patch.object(term_promotion_notify, "STATE_DIR", state_dir):
                with mock.patch.object(term_promotion_notify, "IMESSAGE_SCRIPT", fake_script):
                    with mock.patch.object(term_promotion_notify, "NOTIFY_LOG_FILE", log_file):
                        term_promotion_notify.notify_promoted_term({"id": 42, "term": "Outcome-Based Pricing"})

        log_content = log_file.read_text()
        log_entry = json.loads(log_content.strip())
        assert log_entry["status"] == "skipped"
        assert "TERM_PROMOTION_IMESSAGE" in log_entry["reason"]
        assert log_entry["term"] == "Outcome-Based Pricing"
        assert log_entry["term_id"] == 42


def test_notify_enabled_when_env_set():
    """When TERM_PROMOTION_IMESSAGE=1 is set, notify should attempt to send (mocked)."""
    with TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "state"
        state_dir.mkdir()
        workspace_dir = Path(tmpdir) / "workspace"
        workspace_dir.mkdir()

        fake_script = workspace_dir / "send_imessage.sh"
        fake_script.write_text("#!/bin/bash\necho sent\n")
        fake_script.chmod(0o755)

        log_file = state_dir / "term_promotion_notify_log.jsonl"
        pending_file = state_dir / "pending_term_promotions.json"

        with mock.patch.dict(os.environ, {"TERM_PROMOTION_IMESSAGE": "1"}, clear=True):
            import importlib
            import term_promotion_notify
            importlib.reload(term_promotion_notify)

            with mock.patch.object(term_promotion_notify, "STATE_DIR", state_dir):
                with mock.patch.object(term_promotion_notify, "IMESSAGE_SCRIPT", fake_script):
                    with mock.patch.object(term_promotion_notify, "NOTIFY_LOG_FILE", log_file):
                        with mock.patch.object(term_promotion_notify, "PENDING_FILE", pending_file):
                            with mock.patch.object(term_promotion_notify.subprocess, "run") as mock_run:
                                mock_run.return_value = mock.Mock(returncode=0, stderr="", stdout="")

                                term_promotion_notify.notify_promoted_term({"id": 1, "term": "Test"})

                                mock_run.assert_called_once()
                                call_args = mock_run.call_args
                                assert call_args[0][0][0] == "osascript"


def test_sms_replies_disabled_by_default():
    """process_term_promotion_replies should exit early when TERM_PROMOTION_SMS_REPLIES is not set."""
    from io import StringIO
    
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            import importlib
            import process_term_promotion_replies
            importlib.reload(process_term_promotion_replies)
            
            process_term_promotion_replies.main()
            
            output = mock_stdout.getvalue()
            assert "SKIP" in output
            assert "TERM_PROMOTION_SMS_REPLIES" in output


def test_imessage_disabled_with_various_env_values():
    """Various non-truthy env values should all result in disabled behavior."""
    non_truthy_values = ["", "0", "false", "no", "FALSE", "NO", "off", "disabled"]
    
    for val in non_truthy_values:
        with mock.patch.dict(os.environ, {"TERM_PROMOTION_IMESSAGE": val}, clear=True):
            import importlib
            import term_promotion_notify
            importlib.reload(term_promotion_notify)
            
            result = term_promotion_notify._is_imessage_enabled()
            assert result is False, f"Expected False for TERM_PROMOTION_IMESSAGE='{val}'"


def test_imessage_enabled_with_truthy_values():
    """Truthy env values should enable iMessage notifications."""
    truthy_values = ["1", "true", "yes", "TRUE", "YES", "True", "Yes"]
    
    for val in truthy_values:
        with mock.patch.dict(os.environ, {"TERM_PROMOTION_IMESSAGE": val}, clear=True):
            import importlib
            import term_promotion_notify
            importlib.reload(term_promotion_notify)
            
            result = term_promotion_notify._is_imessage_enabled()
            assert result is True, f"Expected True for TERM_PROMOTION_IMESSAGE='{val}'"


if __name__ == "__main__":
    test_notify_skipped_when_imessage_disabled()
    print("✓ test_notify_skipped_when_imessage_disabled")

    test_notify_skipped_logs_correct_reason()
    print("✓ test_notify_skipped_logs_correct_reason")

    test_notify_enabled_when_env_set()
    print("✓ test_notify_enabled_when_env_set")

    test_sms_replies_disabled_by_default()
    print("✓ test_sms_replies_disabled_by_default")

    test_imessage_disabled_with_various_env_values()
    print("✓ test_imessage_disabled_with_various_env_values")

    test_imessage_enabled_with_truthy_values()
    print("✓ test_imessage_enabled_with_truthy_values")

    print("\nAll term promotion notify tests passed!")
