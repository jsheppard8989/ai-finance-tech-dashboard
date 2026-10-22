"""Alerts are log-only: send_notification must never shell out to iMessage."""
from unittest import mock

import auto_pipeline


def test_send_notification_logs_and_never_texts(tmp_path, capsys):
    with mock.patch.object(auto_pipeline, "PIPELINE_DIR", tmp_path), \
         mock.patch.object(auto_pipeline.subprocess, "run") as run:
        auto_pipeline.send_notification("ALERT publish guard: site publish blocked", "style gate: 1 hit", priority=1)
    run.assert_not_called()
    assert "ALERT publish guard" in capsys.readouterr().out
    assert "ALERT publish guard: site publish blocked: style gate" in (tmp_path / "logs" / "alerts.log").read_text()
