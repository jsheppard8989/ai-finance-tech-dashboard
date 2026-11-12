"""Evening export restore must clear leftover generated chart PNGs (NVDA Nov 10, BTC Nov 8)."""
import subprocess
from unittest import mock

import auto_pipeline


def _run(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


def test_restore_clears_modified_and_untracked_charts(tmp_path):
    repo = tmp_path
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "t")
    (repo / "site" / "charts").mkdir(parents=True)
    (repo / "site" / "charts" / "NVDA_chart.png").write_bytes(b"old")
    _run(repo, "add", ".")
    _run(repo, "commit", "-qm", "base")
    (repo / "site" / "charts" / "NVDA_chart.png").write_bytes(b"new")
    (repo / "site" / "charts" / "BTC_chart.png").write_bytes(b"leftover")
    with mock.patch.object(auto_pipeline, "WORKSPACE", repo), \
         mock.patch.object(auto_pipeline, "send_notification"):
        dest = auto_pipeline._backup_and_discard_generated()
    assert dest
    assert (repo / "site" / "charts" / "NVDA_chart.png").read_bytes() == b"old"
    assert not (repo / "site" / "charts" / "BTC_chart.png").exists()
