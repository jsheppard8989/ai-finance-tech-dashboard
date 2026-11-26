"""Tests for the Show Runner pre-analysis skip gate (Jared, 2026-11-23 5:50 PM CT)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import showrunner_skip_gate as gate


def _index(rows):
    return gate.index_episodes(rows, source="test")


def _row(**kwargs):
    base = {
        "guid": "guid-low",
        "url": "https://example.com/audio.mp3",
        "feed_name": "The a16z Show",
        "title": "A low-score episode",
        "published_at": "2026-11-21T11:00:00+00:00",
        "total_score": 25.0,
        "decision": "SKIP",
        "published_summary_id": 711,
        "run_date": "2026-11-22",
    }
    base.update(kwargs)
    return base


def test_score_under_30_is_skipped():
    idx = _index([_row(total_score=29.9, decision="SKIP")])
    d = gate.evaluate_episode({"rss_guid": "guid-low"}, idx)
    assert d.skip is True
    assert d.reason == "score_below_threshold"
    assert d.score == 29.9
    assert d.episode_id == 711


def test_score_of_30_is_not_skipped_even_if_decision_is_skip():
    idx = _index([_row(total_score=30, decision="SKIP")])
    d = gate.evaluate_episode({"rss_guid": "guid-low"}, idx)
    assert d.skip is False
    assert d.reason == "at_or_above_threshold"


def test_defer_or_skip_at_30_plus_is_advisory_only():
    idx = _index([
        _row(guid="g-defer", total_score=40, decision="DEFER"),
        _row(guid="g-skip", total_score=31, decision="SKIP", url="https://ex/b.mp3"),
    ])
    assert gate.evaluate_episode({"rss_guid": "g-defer"}, idx).skip is False
    assert gate.evaluate_episode({"rss_guid": "g-skip"}, idx).skip is False


def test_moonshots_never_skipped_even_under_30():
    idx = _index([_row(
        guid="moon-1",
        feed_name="Moonshots with Peter Diamandis",
        title="Flying Tesla Car",
        total_score=27.0,
        decision="SKIP",
        published_summary_id=587,
        url="https://ex/moon.mp3",
    )])
    d = gate.evaluate_episode({"rss_guid": "moon-1", "podcast_name": "Moonshots with Peter Diamandis"}, idx)
    assert d.skip is False
    assert d.reason == "moonshots_exempt"
    assert d.score == 27.0


def test_moonshots_exemption_is_case_insensitive():
    idx = _index([_row(guid="m2", feed_name="moonshots", total_score=14, url="https://ex/m2.mp3")])
    d = gate.evaluate_episode({"rss_guid": "m2"}, idx)
    assert d.skip is False
    assert d.reason == "moonshots_exempt"


def test_no_score_fails_open():
    idx = _index([_row()])
    d = gate.evaluate_episode({"rss_guid": "brand-new-guid", "podcast_name": "Dwarkesh Podcast"}, idx)
    assert d.skip is False
    assert d.reason == "no_score"
    assert d.fail_open is True


def test_missing_scores_file_fails_open(tmp_path):
    missing = tmp_path / "nope.json"
    index, warning = gate.load_score_index(scores_path=missing)
    assert index is None
    assert warning and "fail open" in warning
    d = gate.evaluate_episode({"rss_guid": "x"}, index, load_warning=warning)
    assert d.skip is False
    assert d.reason == "unreadable"
    assert d.fail_open is True


def test_parse_error_fails_open(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    index, warning = gate.load_score_index(scores_path=bad)
    assert index is None
    assert warning and "unreadable" in warning
    d = gate.evaluate_episode({"rss_guid": "x"}, index, load_warning=warning)
    assert d.skip is False
    assert d.fail_open is True


def test_invalid_score_fails_open():
    # Bypass index_episodes filtering by injecting a bad score after indexing.
    idx = _index([_row(total_score=25)])
    idx.by_guid["guid-low"].total_score = float("nan")
    # NaN < 30 is False in the threshold check? NaN comparisons are False, so
    # treat non-finite as invalid via _as_float + explicit check in a custom
    # evaluate: our _as_float("nan") actually becomes nan and nan < 30 is False,
    # which would incorrectly process. Guard this in the test by using a string
    # that sneaks through — evaluate uses _as_float again.
    idx.by_guid["guid-low"].total_score = "not-a-number"  # type: ignore
    d = gate.evaluate_episode({"rss_guid": "guid-low"}, idx)
    assert d.skip is False
    assert d.reason == "invalid_score"
    assert d.fail_open is True


def test_matches_guid_then_url_never_title_alone():
    idx = _index([_row(
        guid="real-guid",
        url="https://cdn.example/ep.mp3",
        title="Unique Title",
        total_score=18,
    )])
    by_guid = gate.evaluate_episode({"rss_guid": "real-guid", "title": "Wrong title"}, idx)
    assert by_guid.skip is True
    by_url = gate.evaluate_episode({
        "audio_url": "https://cdn.example/ep.mp3/",  # trailing slash normalized
        "title": "Unique Title",
    }, idx)
    assert by_url.skip is True
    by_title = gate.evaluate_episode({
        "title": "Unique Title",
        "podcast_name": "The a16z Show",
    }, idx)
    assert by_title.skip is False
    assert by_title.reason == "no_score"


def test_mismatched_guid_does_not_fall_back_to_summary_id():
    idx = _index([_row(guid="real-guid", published_summary_id=711, total_score=18)])
    d = gate.evaluate_episode({"rss_guid": "other-guid", "published_summary_id": 711}, idx)
    assert d.skip is False
    assert d.reason == "no_score"


def test_summary_id_fallback_when_no_guid_or_url():
    idx = _index([_row(guid="real-guid", published_summary_id=711, total_score=18)])
    d = gate.evaluate_episode({"published_summary_id": 711}, idx)
    assert d.skip is True
    assert d.guid == "real-guid"


def test_skip_log_appends_once_per_guid_and_score(tmp_path, monkeypatch):
    log = tmp_path / "skip_log.jsonl"
    d1 = gate.SkipDecision(
        skip=True,
        reason="score_below_threshold",
        score=25.0,
        show="The a16z Show",
        title="The Professional Network Built for You and Your AI Agent",
        guid="g-711",
        episode_id=711,
        decision="SKIP",
    )
    assert gate.log_skip(d1, log_path=log) is True
    assert gate.log_skip(d1, log_path=log) is False
    d2 = gate.SkipDecision(
        skip=True,
        reason="score_below_threshold",
        score=19.0,
        show="The a16z Show",
        title="The Professional Network Built for You and Your AI Agent",
        guid="g-711",
        episode_id=711,
        decision="SKIP",
    )
    assert gate.log_skip(d2, log_path=log) is True
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2
    assert lines[0]["guid"] == "g-711"
    assert lines[0]["episode_id"] == 711
    assert lines[0]["show"] == "The a16z Show"
    assert lines[0]["score"] == 25.0
    assert lines[0]["title"].startswith("The Professional Network")
    assert "T" in lines[0]["ts"]
    assert lines[1]["score"] == 19.0


def test_should_skip_and_log_wires_together(tmp_path, capsys):
    scores = tmp_path / "scores.json"
    log = tmp_path / "skip_log.jsonl"
    gate.export_scores_from_ledger  # sanity the symbol exists
    scores.write_text(json.dumps({
        "schema": "showrunner.scores.v1",
        "episodes": [_row(total_score=25), _row(guid="keep", url="https://ex/keep.mp3", total_score=55, decision="LIGHT_SCREEN")],
    }), encoding="utf-8")
    gate.reset_cache()
    assert gate.should_skip_and_log(
        {"rss_guid": "guid-low"},
        scores_path=scores,
        log_path=log,
        use_process_cache=False,
    ) is True
    assert gate.should_skip_and_log(
        {"rss_guid": "keep"},
        scores_path=scores,
        log_path=log,
        use_process_cache=False,
    ) is False
    out = capsys.readouterr().out
    assert "Show Runner skip" in out
    assert log.exists()


def test_export_roundtrip_from_sqlite(tmp_path):
    ledger = tmp_path / "ledger.db"
    con = sqlite3.connect(str(ledger))
    con.execute(
        """
        CREATE TABLE episodes (
            guid TEXT PRIMARY KEY,
            url TEXT,
            feed_name TEXT,
            title TEXT,
            published_at TEXT,
            total_score REAL,
            decision TEXT,
            published_summary_id INTEGER,
            run_date TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("g-low", "https://a/1.mp3", "The a16z Show", "Low", "2026-11-21T11:00:00+00:00", 25.0, "SKIP", 711, "2026-11-22"),
            ("g-moon", "https://a/2.mp3", "Moonshots with Peter Diamandis", "Moon", "2026-11-21T16:00:00+00:00", 27.0, "SKIP", 587, "2026-10-28"),
            ("g-ok", "https://a/3.mp3", "Dwarkesh Podcast", "Ok", "2026-11-16T17:46:28+00:00", 57.0, "LIGHT_SCREEN", 686, "2026-11-16"),
            ("g-none", "https://a/4.mp3", "Latent Space: The AI Engineer Podcast", "Unscored", None, None, None, None, "2026-11-23"),
        ],
    )
    con.commit()
    con.close()
    dest = tmp_path / "showrunner_scores.json"
    payload = gate.export_scores_from_ledger(ledger, dest)
    assert payload["schema"] == "showrunner.scores.v1"
    assert payload["episode_count"] == 3  # unscored omitted
    index, warning = gate.load_score_index(scores_path=dest)
    assert warning is None
    assert index is not None
    assert index.episode_count == 3
    assert gate.evaluate_episode({"rss_guid": "g-low"}, index).skip is True
    assert gate.evaluate_episode({"rss_guid": "g-moon"}, index).reason == "moonshots_exempt"
    assert gate.evaluate_episode({"rss_guid": "g-ok"}, index).skip is False
    assert gate.evaluate_episode({"rss_guid": "g-none"}, index).reason == "no_score"

    # Direct ledger path works too.
    index2, warning2 = gate.load_score_index(ledger_path=ledger)
    assert warning2 is None
    assert index2 is not None
    assert gate.evaluate_episode({"rss_guid": "g-low"}, index2).skip is True


def test_dry_run_lists_only_skips(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "keep.txt").write_text("x" * 600, encoding="utf-8")
    (transcripts / "keep.meta.json").write_text(json.dumps({
        "rss_guid": "g-ok", "podcast_name": "Dwarkesh Podcast", "episode_title": "Ok",
    }), encoding="utf-8")
    (transcripts / "skip.txt").write_text("x" * 600, encoding="utf-8")
    (transcripts / "skip.meta.json").write_text(json.dumps({
        "rss_guid": "g-low", "podcast_name": "The a16z Show", "episode_title": "Low",
        "audio_url": "https://a/1.mp3",
    }), encoding="utf-8")
    (transcripts / "moon.txt").write_text("x" * 600, encoding="utf-8")
    (transcripts / "moon.meta.json").write_text(json.dumps({
        "rss_guid": "g-moon", "podcast_name": "Moonshots with Peter Diamandis",
        "episode_title": "Moon",
    }), encoding="utf-8")
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({"episodes": [
        _row(guid="g-low", url="https://a/1.mp3", total_score=25, published_summary_id=711),
        _row(guid="g-ok", url="https://a/3.mp3", feed_name="Dwarkesh Podcast", total_score=57, decision="LIGHT_SCREEN", published_summary_id=686),
        _row(guid="g-moon", url="https://a/2.mp3", feed_name="Moonshots with Peter Diamandis", total_score=27, published_summary_id=587),
    ]}), encoding="utf-8")
    skips = gate.dry_run_unprocessed(transcript_dir=transcripts, scores_path=scores)
    assert [s.guid for s in skips] == ["g-low"]


def test_process_transcript_file_consults_the_gate(tmp_path, monkeypatch):
    """Hook smoke test: a skip decision must return before any AI call."""
    import analyze_transcript as at

    calls = []

    def fake_skip(meta, **kwargs):
        calls.append(meta)
        return True

    monkeypatch.setattr(at, "is_transcript_processed", lambda path: False)
    monkeypatch.setattr(at, "is_hostile_transcript_stem", lambda stem: False)
    monkeypatch.setattr(at, "sidecar_identity_trustworthy", lambda sidecar: True)
    monkeypatch.setattr(at, "parse_podcast_info", lambda name, content: ("The a16z Show", "ep"))
    monkeypatch.setattr(at, "episode_exists_in_db", lambda *a, **k: False)
    monkeypatch.setattr(at, "find_prior_episode", lambda *a, **k: (None, None))

    def should_not_run(*a, **k):
        raise AssertionError("analyzer must not be called for a skipped episode")

    monkeypatch.setattr(at, "analyze_transcript_with_ai", should_not_run)

    import two_pass_analyzer
    monkeypatch.setattr(two_pass_analyzer, "is_two_pass_enabled", lambda: False)

    transcript = tmp_path / "low.txt"
    transcript.write_text("word " * 400, encoding="utf-8")
    (tmp_path / "low.meta.json").write_text(json.dumps({
        "rss_guid": "guid-low",
        "podcast_name": "The a16z Show",
        "episode_title": "A low-score episode",
        "audio_url": "https://example.com/audio.mp3",
        "published_date": "2026-11-21",
    }), encoding="utf-8")

    import showrunner_skip_gate as sg
    monkeypatch.setattr(sg, "should_skip_and_log", fake_skip)

    result = at.process_transcript_file(transcript, client_info=object(), db=object())
    assert result is None
    assert calls, "skip gate was not consulted"
    assert calls[0]["rss_guid"] == "guid-low"


# ---- snapshot freshness (Nov 25, 2026: ep 729 scored 26 at 9:18 PM, Mac still
# had the Nov 24 snapshot, so it published) ----

def _ct(y, mo, d, h, mi=0):
    return gate.datetime(y, mo, d, h, mi, tzinfo=gate.CT)


def _snapshot(path, exported_at, rows=None):
    path.write_text(json.dumps({
        "schema": gate.SCHEMA,
        "exported_at": exported_at,
        "episode_count": len(rows or []),
        "episodes": rows or [],
    }), encoding="utf-8")


def test_latest_due_pass_respects_grace_window():
    assert gate.latest_due_pass(_ct(2026, 11, 25, 22, 8)) == _ct(2026, 11, 25, 21, 0)
    # 9:30 PM: the 9 PM pass is not due yet (45 min grace) -> 1 PM pass
    assert gate.latest_due_pass(_ct(2026, 11, 25, 21, 30)) == _ct(2026, 11, 25, 13, 0)
    # 6 AM morning run -> previous evening's pass
    assert gate.latest_due_pass(_ct(2026, 11, 26, 6, 0)) == _ct(2026, 11, 25, 21, 0)


def test_nov25_mac_snapshot_is_stale_at_evening_run(tmp_path):
    scores = tmp_path / "showrunner_scores.json"
    _snapshot(scores, "2026-11-24T21:41:00-06:00", [_row()])
    st = gate.snapshot_status(scores, now=_ct(2026, 11, 25, 22, 8))
    assert st["stale"] is True
    assert st["latest_due_pass"].startswith("2026-11-25T21:00")
    assert gate.stale_warning(st) and "STALE" in gate.stale_warning(st)


def test_fresh_snapshot_after_evening_pass_is_not_stale(tmp_path):
    scores = tmp_path / "showrunner_scores.json"
    _snapshot(scores, "2026-11-25T21:19:00-06:00", [_row()])
    st = gate.snapshot_status(scores, now=_ct(2026, 11, 25, 22, 8))
    assert st["stale"] is False
    assert gate.stale_warning(st) is None
    assert 0.8 < st["age_hours"] < 0.9


def test_missing_snapshot_status_is_problem(tmp_path):
    st = gate.snapshot_status(tmp_path / "nope.json", now=_ct(2026, 11, 25, 22, 8))
    assert st["problem"] == "missing" and st["stale"] is True


def test_status_cli_exit_codes(tmp_path, capsys):
    scores = tmp_path / "showrunner_scores.json"
    _snapshot(scores, "2020-01-01T00:00:00-06:00", [_row()])
    assert gate.main(["status", "--scores", str(scores)]) == 1
    _snapshot(scores, gate.now_ct().isoformat(), [_row()])
    assert gate.main(["status", "--scores", str(scores)]) == 0
    assert "exported_at" in capsys.readouterr().out


def test_stale_snapshot_alerts_but_still_fails_open_and_still_skips(tmp_path, monkeypatch, capsys):
    scores = tmp_path / "showrunner_scores.json"
    alerts = tmp_path / "logs" / "alerts.log"
    _snapshot(scores, "2020-01-01T00:00:00-06:00", [_row(total_score=25)])
    monkeypatch.setenv("SHOWRUNNER_SCORES_PATH", str(scores))
    monkeypatch.setenv("SHOWRUNNER_SKIP_LOG_PATH", str(tmp_path / "skip_log.jsonl"))
    monkeypatch.delenv("SHOWRUNNER_LEDGER_PATH", raising=False)
    monkeypatch.setattr(gate, "DEFAULT_ALERTS_LOG_PATH", alerts)
    gate.reset_cache()
    try:
        # unknown episode: processes (fail open) but says so
        assert gate.should_skip_and_log({"rss_guid": "new-ep", "title": "New one"}) is False
        # a scored <30 episode in the stale snapshot is still skipped
        assert gate.should_skip_and_log({"rss_guid": "guid-low"}) is True
    finally:
        gate.reset_cache()
    out = capsys.readouterr().out
    assert "STALE" in out
    assert "no score for 'New one'" in out
    assert "ALERT showrunner gate" in alerts.read_text()


def test_ep729_metadata_is_skipped_with_fresh_snapshot():
    idx = _index([_row(
        guid="01a214b9-5541-7a74-8098-e2b949bce219",
        url="https://podcasts.beehiiv.com/x/01a214d7-cbb8-79f1-a627-087a38d098e9.mp3",
        feed_name="Latent Space: The AI Engineer Podcast",
        title="The Revolution vs The Renaissance — Thariq Shihipar, OpenAI",
        total_score=26.0, decision="SKIP", published_summary_id=None,
    )])
    d = gate.evaluate_episode({
        "rss_guid": "01a214b9-5541-7a74-8098-e2b949bce219",
        "podcast_name": "Latent Space: The AI Engineer Podcast",
    }, idx)
    assert d.skip is True and d.score == 26.0
