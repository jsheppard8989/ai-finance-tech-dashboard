"""Cost fixes 2026-10-16: pre-analysis dedupe (no re-analysis loop) and OpenAI Flex tier."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import analyze_transcript as at
import openai_flex as fx

TRANSCRIPT = "Ben Horowitz talks about xAI. " * 60


def _db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE podcast_episodes (id INTEGER PRIMARY KEY, podcast_name TEXT, episode_title TEXT,
                    transcript_path TEXT, rss_guid TEXT, is_processed INTEGER DEFAULT 0)""")
    conn.executemany("INSERT INTO podcast_episodes (id, podcast_name, episode_title, transcript_path, rss_guid) VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class PreAnalysisDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dbp = self.tmp / "dash.db"
        _db(self.dbp, [(23, "Moonshots with Peter Diamandis", "Ben Horowitz: xAI Executive Exodus | #232",
                        "/Users/x/.openclaw/workspace/pipeline/transcripts/DVVTS5786783285.txt", None)])
        self.tdir = self.tmp / "transcripts"; self.tdir.mkdir()
        self.mdir = self.tmp / "processed"; self.mdir.mkdir()
        self.p = patch.multiple(at, DB_PATH=self.dbp, PROCESSED_MARKER_DIR=self.mdir)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_moonshots_232_never_reaches_the_api(self):
        """Same file name stored from an old directory: skipped BEFORE pass 1, marker makes it permanent."""
        f = self.tdir / "DVVTS5786783285.txt"
        f.write_text(TRANSCRIPT)
        with patch.dict(os.environ, {"ANALYZER_MODE": "two_pass", "OPENAI_API_KEY": "x"}), \
             patch("two_pass_analyzer.analyze_transcript_two_pass", side_effect=AssertionError("API called")) as two, \
             patch.object(at, "episode_exists_in_db", return_value=False):
            self.assertIsNone(at.process_transcript_file(f, None, None))
            two.assert_not_called()
        meta = json.loads((self.mdir / "DVVTS5786783285.processed").read_text())
        self.assertEqual(meta["duplicate_of"], 23)
        self.assertTrue(at.is_transcript_processed(f))  # next run skips at the very first check

    def test_content_hash_catches_renamed_copy(self):
        at.record_transcript_hash(TRANSCRIPT, 23, "/old/a.txt")
        f = self.tdir / "renamed_copy.txt"
        f.write_text(TRANSCRIPT)
        self.assertEqual(at.find_prior_episode(f, TRANSCRIPT), (23, "content_sha256"))

    def test_guid_and_sidecar_title(self):
        conn = sqlite3.connect(self.dbp)
        conn.execute("UPDATE podcast_episodes SET rss_guid='g-232' WHERE id=23"); conn.commit(); conn.close()
        f = self.tdir / "other.txt"
        self.assertEqual(at.find_prior_episode(f, "different text", rss_guid="g-232")[0], 23)
        self.assertEqual(at.find_prior_episode(f, "different text", podcast_name="Moonshots with Peter Diamandis",
                                               sidecar_title="Ben Horowitz: xAI Executive Exodus | #232")[0], 23)

    def test_new_episode_is_not_skipped(self):
        f = self.tdir / "brand_new.txt"
        self.assertEqual(at.find_prior_episode(f, "a brand new transcript", rss_guid="new-guid"), (0, None))

    def test_old_minus_one_marker_without_duplicate_of_still_rechecks(self):
        f = self.tdir / "x.txt"
        at.mark_transcript_processed(f, -1)
        self.assertFalse(at.is_transcript_processed(f))
        at.mark_transcript_processed(f, -1, duplicate_of=23)
        self.assertTrue(at.is_transcript_processed(f))


class _Err(Exception):
    pass


class Flex(unittest.TestCase):
    def _client(self, side_effect):
        c = MagicMock()
        c.with_options.return_value = c
        c.chat.completions.create.side_effect = side_effect
        return c

    def _resp(self, tier):
        return SimpleNamespace(service_tier=tier, usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000),
                               choices=[])

    def test_flex_requested_and_half_price(self):
        c = self._client([self._resp("flex")])
        start = len(fx.LEDGER)
        resp, tier = fx.create_chat(c, model="gpt-5.4-mini", messages=[])
        self.assertEqual(tier, "flex")
        self.assertEqual(c.chat.completions.create.call_args.kwargs["service_tier"], "flex")
        c.with_options.assert_called_with(timeout=fx.FLEX_TIMEOUT_S)
        self.assertAlmostEqual(fx.ledger_cost(start), (0.75 + 4.50) / 2)

    def test_resource_unavailable_retries_then_standard_same_model(self):
        busy = _Err("Error code: 429 - Resource Unavailable")
        c = self._client([busy, busy, busy, self._resp("default")])
        resp, tier = fx.create_chat(c, sleep=lambda s: None, model="gpt-5.4-nano", messages=[])
        calls = c.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertNotIn("service_tier", calls[-1].kwargs)
        self.assertTrue(all(k.kwargs["model"] == "gpt-5.4-nano" for k in calls))  # never another model
        self.assertEqual(tier, "default")

    def test_quota_error_raises_immediately(self):
        c = self._client([_Err("Error code: 429 - insufficient_quota credit_balance_exhausted")])
        with self.assertRaises(_Err):
            fx.create_chat(c, sleep=lambda s: None, model="gpt-5.4-mini", messages=[])
        self.assertEqual(c.chat.completions.create.call_count, 1)

    def test_unsupported_tier_goes_standard(self):
        c = self._client([_Err("Error code: 400 - Unsupported value: 'service_tier' flex"), self._resp(None)])
        resp, tier = fx.create_chat(c, model="gpt-5.4-mini", messages=[])
        self.assertEqual(tier, "default")

    def test_flex_off_env(self):
        c = self._client([self._resp(None)])
        with patch.dict(os.environ, {"OPENAI_FLEX": "0"}):
            fx.create_chat(c, model="gpt-5.4-mini", messages=[])
        self.assertNotIn("service_tier", c.chat.completions.create.call_args.kwargs)

    def test_price_table(self):
        self.assertAlmostEqual(fx.price("gpt-5.4-nano", 1_000_000, 1_000_000), 1.45)
        self.assertAlmostEqual(fx.price("gpt-5.4-nano", 1_000_000, 1_000_000, "flex"), 0.725)
        self.assertAlmostEqual(fx.price("gpt-5.5", 1_000_000, 0), 5.0)


if __name__ == "__main__":
    unittest.main()
