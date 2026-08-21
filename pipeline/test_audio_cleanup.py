#!/usr/bin/env python3
"""Focused regression tests for conservative podcast source-audio cleanup."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from audio_cleanup import (
    _curate_filename_stem,
    execute_audio_cleanup,
    plan_audio_cleanup,
    protected_site_audio_summary,
)


class AudioCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "audio"
        self.queue = self.root / "whisper_queue"
        self.pipeline_audio = self.root / "pipeline_audio"
        self.transcripts = self.root / "transcripts"
        self.site_data = self.root / "site" / "data"
        self.site_audio = self.root / "site" / "audio"
        for directory in (
            self.audio,
            self.queue,
            self.pipeline_audio,
            self.transcripts,
            self.site_data,
            self.site_audio,
        ):
            directory.mkdir(parents=True)

        self.db_path = self.root / "test.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE podcast_episodes (
                id INTEGER PRIMARY KEY,
                podcast_name TEXT,
                episode_title TEXT,
                episode_date TEXT,
                published_date TEXT,
                audio_url TEXT,
                transcript_path TEXT,
                rss_guid TEXT,
                is_processed INTEGER
            );
            CREATE TABLE latest_insights (
                id INTEGER PRIMARY KEY,
                podcast_episode_id INTEGER
            );
            CREATE TABLE deep_dive_content (
                id INTEGER PRIMARY KEY,
                insight_id INTEGER,
                podcast_episode_id INTEGER,
                overview TEXT
            );
            CREATE TABLE processing_queue (
                item_type TEXT,
                item_id INTEGER,
                status TEXT
            );
            CREATE TABLE deep_dive_generation_failures (
                podcast_episode_id INTEGER,
                status TEXT
            );
            """
        )
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def _episode(
        self,
        episode_id,
        stem,
        *,
        processed=1,
        deep_dive=True,
        published=True,
        transcript=True,
        audio_url=None,
    ):
        transcript_path = self.transcripts / f"{stem}.txt"
        if transcript:
            transcript_path.write_text("retained transcript", encoding="utf-8")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO podcast_episodes
                (id, podcast_name, episode_title, episode_date, published_date,
                 audio_url, transcript_path, rss_guid, is_processed)
            VALUES (?, 'Test Podcast', ?, '2026-08-20', '2026-08-20', ?, ?, ?, ?)
            """,
            (
                episode_id,
                f"Episode {episode_id}",
                audio_url,
                str(transcript_path),
                f"guid-{episode_id}",
                processed,
            ),
        )
        insight_id = 1000 + episode_id
        conn.execute(
            "INSERT INTO latest_insights (id, podcast_episode_id) VALUES (?, ?)",
            (insight_id, episode_id),
        )
        if deep_dive:
            conn.execute(
                """
                INSERT INTO deep_dive_content
                    (id, insight_id, podcast_episode_id, overview)
                VALUES (?, ?, ?, 'Completed source-grounded Deep Dive')
                """,
                (2000 + episode_id, insight_id, episode_id),
            )
        conn.commit()
        conn.close()
        if published:
            with (self.site_data / "data.js").open("a", encoding="utf-8") as handle:
                handle.write(f'{{"podcast_episode_id": {episode_id}}}\n')
        return transcript_path

    def _plan(self):
        return plan_audio_cleanup(
            db_path=self.db_path,
            site_data=self.site_data,
            source_dirs=(self.audio, self.queue, self.pipeline_audio),
            transcript_dir=self.transcripts,
        )

    def test_deletes_only_fully_complete_published_source_audio(self):
        transcript = self._episode(1, "eligible")
        source = self.audio / "eligible.mp3"
        source.write_bytes(b"x" * 25)
        site_asset = self.site_audio / "archive" / "debate_2026-08-20.mp3"
        site_asset.parent.mkdir()
        site_asset.write_bytes(b"s" * 40)

        report = execute_audio_cleanup(self._plan(), dry_run=False)

        self.assertEqual(report["deleted_files"], 1)
        self.assertEqual(report["deleted_bytes"], 25)
        self.assertFalse(source.exists())
        self.assertTrue(transcript.exists())
        self.assertTrue(site_asset.exists())
        self.assertEqual(
            protected_site_audio_summary(self.root / "site"),
            {"files": 1, "bytes": 40},
        )

    def test_retains_work_in_progress_unpublished_and_unmatched_audio(self):
        cases = (
            (2, "analysis_pending", {"processed": 0}, "pending_or_failed_analysis"),
            (3, "deep_dive_pending", {"deep_dive": False}, "pending_or_failed_deep_dive"),
            (4, "unpublished", {"published": False}, "not_in_published_site_bundle"),
            (5, "transcript_missing", {"transcript": False}, "pending_transcription_or_missing_transcript"),
        )
        for episode_id, stem, kwargs, _reason in cases:
            self._episode(episode_id, stem, **kwargs)
            (self.audio / f"{stem}.mp3").write_bytes(b"x")
        (self.queue / "worker_still_transcribing.mp3").write_bytes(b"x")

        decisions = self._plan()
        reasons = {Path(item.path).stem: item.reason for item in decisions}
        for _episode_id, stem, _kwargs, reason in cases:
            self.assertEqual(reasons[stem], reason)
        self.assertEqual(reasons["worker_still_transcribing"], "unmatched_source_audio")

        report = execute_audio_cleanup(decisions, dry_run=False)
        self.assertEqual(report["deleted_files"], 0)
        self.assertEqual(report["retained_files"], 5)

    def test_matches_legacy_audio_url_stem_when_transcript_stem_changed(self):
        self._episode(
            6,
            "renamed_transcript",
            audio_url="https://cdn.example.com/original-download-name.mp3?token=old",
        )
        source = self.pipeline_audio / "original-download-name.mp3"
        source.write_bytes(b"legacy")

        decisions = self._plan()

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].episode_id, 6)
        self.assertEqual(decisions[0].action, "delete")

    def test_matches_curate_hash_filename_from_transcript_metadata(self):
        transcript = self._episode(8, "worker_output_name")
        audio_url = "https://cdn.example.com/audio/default.mp3?episode=8"
        metadata = transcript.with_suffix(".meta.json")
        metadata.write_text(
            """
            {
              "podcast_name": "Test Podcast",
              "episode_title": "Episode 8",
              "audio_url": "https://cdn.example.com/audio/default.mp3?episode=8"
            }
            """,
            encoding="utf-8",
        )
        stem = _curate_filename_stem("Test Podcast", "Episode 8", audio_url)
        source = self.audio / f"{stem}.mp3"
        source.write_bytes(b"curate")

        decisions = self._plan()

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].episode_id, 8)
        self.assertEqual(decisions[0].action, "delete")

    def test_dry_run_reports_without_deleting(self):
        self._episode(7, "dry_run")
        source = self.audio / "dry_run.mp3"
        source.write_bytes(b"1234567")

        report = execute_audio_cleanup(self._plan(), dry_run=True)

        self.assertTrue(source.exists())
        self.assertEqual(report["eligible_files"], 1)
        self.assertEqual(report["eligible_bytes"], 7)
        self.assertEqual(report["deleted_files"], 0)


if __name__ == "__main__":
    unittest.main()
