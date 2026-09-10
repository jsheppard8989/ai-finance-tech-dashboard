#!/usr/bin/env python3
"""Regression tests for transcript analysis duplicate checks and failure recording."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze_transcript as at
from export_data import stage_reason_missing


class EpisodeExistsGuidTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            CREATE TABLE podcast_episodes (
                id INTEGER PRIMARY KEY,
                podcast_name TEXT,
                episode_title TEXT,
                transcript_path TEXT,
                rss_guid TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO podcast_episodes (podcast_name, episode_title, transcript_path, rss_guid)
            VALUES (?, ?, ?, ?)
            """,
            (
                "The a16z Show",
                "The New Economics of AI Infrastructure and Talent",
                "/tmp/a16z_new_economics.txt",
                "guid-episode-one",
            ),
        )
        conn.commit()
        conn.close()
        self.db_patch = patch.object(at, "DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_shared_title_prefix_different_guids_is_not_duplicate(self):
        exists = at.episode_exists_in_db(
            None,
            "The a16z Show",
            "The New Economics of AI Agents and Labor",
            rss_guid="guid-episode-two",
            transcript_stem="a16z_agents_labor",
        )
        self.assertFalse(exists)

    def test_same_guid_is_duplicate(self):
        exists = at.episode_exists_in_db(
            None,
            "The a16z Show",
            "Unrelated title",
            rss_guid="guid-episode-one",
            transcript_stem="other_stem",
        )
        self.assertTrue(exists)


class AnalysisFailureRecordingTest(unittest.TestCase):
    def test_none_is_recorded_and_caps_as_blocked(self):
        failures = {}
        rec = at.record_analysis_failure(failures, "ep_stem", "analysis_error", "AI analysis failed")
        self.assertEqual(rec["attempt_count"], 1)
        self.assertEqual(rec["reason_code"], "analysis_error")
        self.assertFalse(at.analysis_retry_exhausted(failures, "ep_stem"))

        for _ in range(at.ANALYSIS_RETRY_CAP - 1):
            at.record_analysis_failure(failures, "ep_stem", "analysis_error", "AI analysis failed")

        self.assertEqual(failures["ep_stem"]["attempt_count"], at.ANALYSIS_RETRY_CAP)
        self.assertEqual(failures["ep_stem"]["reason_code"], "blocked_analysis")
        self.assertTrue(at.analysis_retry_exhausted(failures, "ep_stem"))

    def test_process_all_records_raised_none_as_failure(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        transcript_dir = root / "transcripts"
        state_dir = root / "state"
        transcript_dir.mkdir()
        state_dir.mkdir()
        txt = transcript_dir / "stuck_episode.txt"
        txt.write_text("x" * 600)

        def _raise(*_args, **_kwargs):
            raise ValueError("AI analysis failed")

        try:
            with patch.object(at, "TRANSCRIPT_DIR", transcript_dir), patch.object(
                at, "STATE_DIR", state_dir
            ), patch.object(at, "get_ai_clients", return_value=[("openai", object())]), patch.object(
                at, "get_db", return_value=object()
            ), patch.object(
                at, "is_transcript_processed", return_value=False
            ), patch.object(
                at, "process_transcript_file", side_effect=_raise
            ):
                result = at.process_all_transcripts()
            self.assertEqual(result["errors"], 1)
            failures = json.loads((state_dir / "analysis_failures.json").read_text())
            self.assertIn("stuck_episode", failures)
            self.assertEqual(failures["stuck_episode"]["reason_code"], "analysis_error")
            self.assertIn("AI analysis failed", failures["stuck_episode"]["reason_detail"])
        finally:
            temp.cleanup()

    def test_success_clears_recorded_failure(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        transcript_dir = root / "transcripts"
        state_dir = root / "state"
        transcript_dir.mkdir()
        state_dir.mkdir()
        txt = transcript_dir / "ok_episode.txt"
        txt.write_text("x" * 600)
        (state_dir / "analysis_failures.json").write_text(
            json.dumps(
                {
                    "ok_episode": {
                        "reason_code": "analysis_error",
                        "reason_detail": "prior fail",
                        "attempt_count": 2,
                    }
                }
            )
        )
        try:
            with patch.object(at, "TRANSCRIPT_DIR", transcript_dir), patch.object(
                at, "STATE_DIR", state_dir
            ), patch.object(at, "get_ai_clients", return_value=[("openai", object())]), patch.object(
                at, "get_db", return_value=object()
            ), patch.object(
                at, "is_transcript_processed", return_value=False
            ), patch.object(
                at, "process_transcript_file", return_value=42
            ):
                result = at.process_all_transcripts()
            self.assertEqual(result["processed"], 1)
            failures = json.loads((state_dir / "analysis_failures.json").read_text())
            self.assertNotIn("ok_episode", failures)
        finally:
            temp.cleanup()


class HealthReasonTest(unittest.TestCase):
    def test_transcript_without_db_row_points_at_analysis(self):
        msg = stage_reason_missing("analyzed", False, transcript_on_disk=True)
        self.assertIn("analysis did not insert a podcast_episodes row", msg)
        self.assertIn("analysis_failures.json", msg)
        self.assertIn("--analyze-only", msg)
        self.assertNotIn("Usually fixed by", msg)

    def test_stale_whisper_queue_is_blocked_transcription(self):
        msg = stage_reason_missing("transcribed", False, stale_whisper=True)
        self.assertIn("blocked_transcription", msg)


class AsciiFoldTest(unittest.TestCase):
    def test_folds_smart_quotes_then_passes_ascii_check(self):
        folded = at._fold_to_ascii({"summary": "Casado said \u201cthe value\u201d is shifting."})
        self.assertEqual(folded["summary"], 'Casado said "the value" is shifting.')
        self.assertFalse(at._has_non_ascii(folded))


if __name__ == "__main__":
    unittest.main()
