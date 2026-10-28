"""Permanent Deep Dive skips (Oct 28 2026, Wendy): insight 429 / ep 414 blocked by the provider
content filter since 2026-08-23 is skipped via deepdive_permanent_skips.json, never via the DB."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import check_blocked_deepdives as cbd
import deepdive_skips
import generate_deepdives

HERE = Path(__file__).resolve().parent


# ---- config ---------------------------------------------------------------------------------

def test_repo_config_has_429_with_reason_and_undo():
    skips = deepdive_skips.load_permanent_skips()
    e = skips[429]
    assert e["podcast_episode_id"] == 414
    assert e["reason"] == "blocked by provider content filter since 2026-08-23 (3 retries)"
    assert e["approved_by"] == "Wendy (CoS) 2026-10-28"
    assert e["undo"] == "remove this entry"
    # 616/625/628 are awaiting review, not skipped
    assert not {616, 625, 628} & set(skips)


def test_missing_config_means_no_skips(tmp_path):
    assert deepdive_skips.load_permanent_skips(tmp_path / "nope.json") == {}


def test_malformed_config_fails_loud(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    with pytest.raises(ValueError):
        deepdive_skips.load_permanent_skips(p)


def test_filter_skipped_ids():
    skips = {429: {"insight_id": 429}}
    assert deepdive_skips.filter_skipped_ids([616, 429, 628], skips) == ([616, 628], [429])
    assert deepdive_skips.filter_skipped_ids([616, 429], skips, force=True) == ([616, 429], [])


# ---- check_blocked_deepdives.py -------------------------------------------------------------

def _skips_file(tmp_path, ids=(429,)):
    p = tmp_path / "skips.json"
    p.write_text(json.dumps({"skips": [
        {"insight_id": i, "podcast_episode_id": 414, "reason": "blocked by provider content filter since 2026-08-23 (3 retries)",
         "approved_by": "Wendy (CoS) 2026-10-28", "undo": "remove this entry"} for i in ids]}))
    return p


def _make_db(path, *, blocked_429=True, blocked_628=False, stale_429=False):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE latest_insights (id INTEGER PRIMARY KEY, title TEXT, podcast_episode_id INTEGER,
            added_date DATE, archived_date DATE);
        CREATE TABLE deep_dive_content (id INTEGER PRIMARY KEY, insight_id INTEGER);
        CREATE TABLE deep_dive_generation_failures (insight_id INTEGER UNIQUE, insight_title TEXT,
            source_type TEXT, podcast_episode_id INTEGER, failure_reason TEXT, failure_detail TEXT,
            last_attempt_at TIMESTAMP, retry_count INTEGER, next_retry_after TIMESTAMP, status TEXT);
    """)
    if blocked_429 or stale_429:
        c.execute("INSERT INTO latest_insights VALUES (429, 'China''s Endgame: ASI Timelines', 414, '2026-08-20', NULL)")
    if blocked_429:
        c.execute("INSERT INTO deep_dive_generation_failures VALUES (429, 'China''s Endgame: ASI Timelines', 'podcast', 414, "
                  "'content_filter', 'content_filter: blocked by provider safety filter', '2026-08-23T22:10:00', 3, NULL, 'blocked')")
    if blocked_628:
        c.execute("INSERT INTO latest_insights VALUES (628, 'Anthropic', 616, '2026-10-27', NULL)")
        c.execute("INSERT INTO deep_dive_generation_failures VALUES (628, 'Anthropic', 'podcast', 616, 'generation_failed', "
                  "'source_quotes need two named lines', '2026-10-28T05:17:16', 3, NULL, 'blocked')")
    c.commit()
    c.close()


def test_only_skipped_blocked_is_ok_exit0(tmp_path, capsys):
    db = tmp_path / "d.db"
    _make_db(db)
    assert cbd.main(["--db", str(db), "--skips", str(_skips_file(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK: 0 blocked (1 permanently skipped)")
    assert ("SKIPPED (permanent) insight 429 | ep 414 | reason: blocked by provider content filter since 2026-08-23 "
            "(3 retries) | approved: Wendy (CoS) 2026-10-28 | was blocked | retries: 3 | last tried: 2026-08-23 22:10 CT") in out
    assert "BLOCKED insight 429" not in out and "ALERT" not in out


def test_skipped_listed_separately_others_still_alert(tmp_path, capsys):
    db = tmp_path / "d.db"
    _make_db(db, blocked_628=True)
    assert cbd.main(["--db", str(db), "--skips", str(_skips_file(tmp_path))]) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "ALERT: 1 blocked deep dive(s), 0 insight(s) >48h old with no deep dive"
    assert "BLOCKED insight 628 | ep 616" in out
    assert "BLOCKED insight 429" not in out
    assert "SKIPPED (permanent) insight 429" in out


def test_without_skip_entry_429_alerts(tmp_path, capsys):
    """Undo = remove the entry: 429 goes back to being an alert."""
    db = tmp_path / "d.db"
    _make_db(db)
    assert cbd.main(["--db", str(db), "--skips", str(tmp_path / "none.json")]) == 1
    assert "BLOCKED insight 429 | ep 414" in capsys.readouterr().out


def test_stale_skipped_insight_not_alerted():
    stale = [{"insight_id": 429, "podcast_episode_id": 414, "insight_title": "x", "added_date": "2026-08-20"}]
    blocked, stale_left, skipped = cbd.split_skipped([], stale, {429: {"reason": "r"}})
    assert blocked == [] and stale_left == [] and [s["state"] for s in skipped] == ["no deep dive"]


def test_check_still_read_only(tmp_path):
    db = tmp_path / "d.db"
    _make_db(db, blocked_628=True)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    cbd.main(["--db", str(db), "--skips", str(_skips_file(tmp_path))])
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


# ---- generate_deepdives.py: never retried unless --force ------------------------------------

def _gen_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE latest_insights (id INTEGER PRIMARY KEY, title TEXT, source_type TEXT, podcast_episode_id INTEGER,
            summary TEXT, key_takeaway TEXT, source_date TEXT, notable_quotes TEXT, source_name TEXT);
        CREATE TABLE deep_dive_content (id INTEGER PRIMARY KEY, insight_id INTEGER);
        INSERT INTO latest_insights VALUES (429, 'China', 'podcast', 414, 's', 'k', '2026-08-20', '[]', 'show');
    """)
    c.commit()
    c.close()


def test_generate_missing_skips_permanent_even_if_not_blocked(tmp_path):
    db = tmp_path / "g.db"
    _gen_db(db)
    with patch("generate_deepdives.DB_PATH", db), \
         patch("generate_deepdives.load_permanent_skips", return_value={429: {"reason": "r"}}), \
         patch("generate_deepdives.get_ai_clients", return_value=[]) as clients:
        assert generate_deepdives.generate_missing_deepdives() == (0, 0, 0)
        assert generate_deepdives.generate_missing_deepdives([429]) == (0, 0, 0)
        clients.assert_not_called()
        # force_skipped: the insight is considered again (no AI client here, so nothing is generated)
        assert generate_deepdives.generate_missing_deepdives([429], force_skipped=True) == (0, 1, 0)


def test_generate_missing_bad_config_does_not_crash(tmp_path):
    db = tmp_path / "g.db"
    _gen_db(db)
    with patch("generate_deepdives.DB_PATH", db), \
         patch("generate_deepdives.load_permanent_skips", side_effect=ValueError("bad")), \
         patch("generate_deepdives.get_ai_clients", return_value=[]):
        assert generate_deepdives.generate_missing_deepdives() == (0, 1, 0)


def _cli(tmp_path, *args):
    env = dict(os.environ, WORKSPACE_ROOT=str(tmp_path))  # never the real dashboard.db
    return subprocess.run([sys.executable, str(HERE / "generate_deepdives.py"), *args],
                          capture_output=True, text=True, env=env, cwd=str(HERE), timeout=120)


def test_cli_insight_ids_only_skipped_warns_and_exits_without_db(tmp_path):
    r = _cli(tmp_path, "--insight-ids", "429")
    assert r.returncode == 0, r.stderr
    assert "Insight 429 is a permanent skip" in r.stdout and "--force" in r.stdout
    assert "Nothing to do" in r.stdout
    assert not (tmp_path / "pipeline" / "dashboard.db").exists()


def test_cli_force_ids_only_skipped_never_deletes(tmp_path):
    r = _cli(tmp_path, "--force-ids", "429")
    assert r.returncode == 0, r.stderr
    assert "Removed Deep Dive" not in r.stdout and "Nothing to do" in r.stdout
