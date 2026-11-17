"""Nov 16 2026 (G, Tony's #834 follow-up): caption speaker turns never fail silently.
Each skip prints one 'WARN caption turns: <reason>' line."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import caption_turns as ct  # noqa: E402

ALLIN = "All-In with Chamath, Jason, Sacks & Friedberg"


def _warns(capsys):
    return [l.strip() for l in capsys.readouterr().out.splitlines() if "WARN caption turns:" in l]


def test_yt_dlp_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("YT_CAPTIONS", raising=False)
    monkeypatch.setattr(ct, "_yt_dlp", lambda: None)
    tp = tmp_path / "ep.txt"
    assert ct.fetch_youtube_captions(tp, ALLIN, "Some episode") is None
    w = _warns(capsys)
    assert len(w) == 1 and w[0].startswith("WARN caption turns: yt-dlp missing")


def test_load_turn_map_warns_once_when_yt_dlp_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("YT_CAPTIONS", raising=False)
    monkeypatch.setattr(ct, "_yt_dlp", lambda: None)
    tp = tmp_path / "ep.txt"
    assert ct.load_turn_map_for_transcript(tp, "text", ALLIN, episode_title="Ep") is None
    assert len(_warns(capsys)) == 1


def test_no_captions_when_fetch_off(tmp_path, capsys):
    tp = tmp_path / "ep.txt"
    assert ct.load_turn_map_for_transcript(tp, "text", ALLIN, fetch=False) is None
    w = _warns(capsys)
    assert len(w) == 1 and w[0].startswith("WARN caption turns: no captions:")


def _fake_run(returncode, stdout="", stderr=""):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run


def test_no_captions_for_video(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("YT_CAPTIONS", raising=False)
    monkeypatch.setattr(ct, "_yt_dlp", lambda: "/bin/yt-dlp")
    monkeypatch.setattr(ct.subprocess, "run", _fake_run(0))
    assert ct.fetch_youtube_captions(tmp_path / "ep.txt", ALLIN, "Ep", video_id="abc123") is None
    w = _warns(capsys)
    assert w == ["WARN caption turns: no captions: no English captions for video abc123"]


def test_no_matching_video(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("YT_CAPTIONS", raising=False)
    monkeypatch.setattr(ct, "_yt_dlp", lambda: "/bin/yt-dlp")
    monkeypatch.setattr(ct.subprocess, "run", _fake_run(0, stdout="xyz\tCompletely different video\n"))
    assert ct.fetch_youtube_captions(tmp_path / "ep.txt", ALLIN, "Jensen Ousted, Bank of Nvidia") is None
    w = _warns(capsys)
    assert len(w) == 1 and w[0].startswith("WARN caption turns: no captions: no YouTube video matches")


def test_fetch_failed_exit_code_and_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("YT_CAPTIONS", raising=False)
    monkeypatch.setattr(ct, "_yt_dlp", lambda: "/bin/yt-dlp")
    monkeypatch.setattr(ct.subprocess, "run", _fake_run(1, stderr="ERROR: Sign in to confirm you're not a bot"))
    assert ct.fetch_youtube_captions(tmp_path / "ep.txt", ALLIN, "Ep", video_id="abc123") is None
    w = _warns(capsys)
    assert len(w) == 1 and w[0].startswith("WARN caption turns: fetch failed: yt-dlp exit 1 for video abc123")

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 90)
    monkeypatch.setattr(ct.subprocess, "run", boom)
    assert ct.fetch_youtube_captions(tmp_path / "ep2.txt", ALLIN, "Ep", video_id="abc123") is None
    w = _warns(capsys)
    assert len(w) == 1 and w[0].startswith("WARN caption turns: fetch failed:")


def test_disabled_by_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("YT_CAPTIONS", "0")
    assert ct.fetch_youtube_captions(tmp_path / "ep.txt", ALLIN, "Ep") is None
    assert _warns(capsys) == ["WARN caption turns: captions disabled (YT_CAPTIONS=0)"]
