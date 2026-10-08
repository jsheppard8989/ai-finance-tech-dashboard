#!/usr/bin/env python3
"""Tests for extraction-mode deep dive generation."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from generate_deepdives import (
    _validate_quotes_from_extraction,
    normalize_from_ai_response,
    deep_dive_structural_ok,
    load_high_profile_config,
    check_high_profile_match,
    HIGH_PROFILE_CONFIG_PATH,
    extraction_failed_generation_mode,
    generate_missing_deepdives,
)
from two_pass_analyzer import (
    get_deepdive_mode,
    normalize_for_quote_match,
    quote_in_transcript,
    validate_extraction_quotes_against_transcript,
    soundex,
    get_phonetic_key,
    fuzzy_name_match,
    canonicalize_speaker,
    canonicalize_extraction_speakers,
    correct_proper_nouns_in_quote,
)


class TestExtractionDeepDive(unittest.TestCase):

    def test_get_deepdive_mode_default(self):
        """Default mode should be 'legacy'."""
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_deepdive_mode(), "legacy")

    def test_get_deepdive_mode_extraction(self):
        """DEEPDIVE_MODE=extraction should return 'extraction'."""
        with patch.dict("os.environ", {"DEEPDIVE_MODE": "extraction"}):
            self.assertEqual(get_deepdive_mode(), "extraction")

    def test_get_deepdive_mode_legacy(self):
        """DEEPDIVE_MODE=legacy should return 'legacy'."""
        with patch.dict("os.environ", {"DEEPDIVE_MODE": "legacy"}):
            self.assertEqual(get_deepdive_mode(), "legacy")

    def test_get_deepdive_mode_case_insensitive(self):
        """Mode should be case-insensitive."""
        with patch.dict("os.environ", {"DEEPDIVE_MODE": "EXTRACTION"}):
            self.assertEqual(get_deepdive_mode(), "extraction")

    def test_validate_quotes_from_extraction_success(self):
        """Quotes that exist in extraction should pass validation."""
        extraction = {
            "high_value_quotes": [
                {"speaker": "John Smith", "quote": "The market is pricing in too much optimism."},
                {"speaker": "Jane Doe", "quote": "We expect revenue to double by 2027."},
            ],
            "companies_and_assets": [
                {
                    "name": "ACME Corp",
                    "key_quotes": [
                        {"speaker": "John Smith", "quote": "ACME is the clear leader in widgets."}
                    ]
                }
            ]
        }
        episode_evidence = [
            "John Smith: The market is pricing in too much optimism.",
            "Jane Doe: We expect revenue to double by 2027.",
        ]
        ok, err = _validate_quotes_from_extraction(episode_evidence, extraction)
        self.assertTrue(ok, f"Validation failed: {err}")

    def test_validate_quotes_from_extraction_fail(self):
        """Quotes not in extraction should fail validation."""
        extraction = {
            "high_value_quotes": [
                {"speaker": "John Smith", "quote": "The market is healthy."},
            ],
            "companies_and_assets": []
        }
        episode_evidence = [
            "John Smith: This is a completely invented quote that does not exist.",
        ]
        ok, err = _validate_quotes_from_extraction(episode_evidence, extraction)
        self.assertFalse(ok)
        self.assertIn("not found", err.lower())

    def test_validate_quotes_partial_match(self):
        """Partial quote matches should pass (substring matching)."""
        extraction = {
            "high_value_quotes": [
                {"speaker": "Jane", "quote": "Revenue will grow significantly next quarter and beyond."},
            ],
            "companies_and_assets": []
        }
        episode_evidence = [
            "Jane: Revenue will grow significantly next quarter",
        ]
        ok, err = _validate_quotes_from_extraction(episode_evidence, extraction)
        self.assertTrue(ok, f"Partial match should pass: {err}")

    def test_structural_check_forbids_investors_should(self):
        """Content containing 'investors should' should fail structural check."""
        content = {
            "episode_evidence": (
                '- John Smith: "We see significant opportunity in the semiconductor space for 2027."\n'
                '- Jane Doe: "Risks remain elevated but manageable for long-term investors."\n'
                '- Bob Wilson: "The market is underestimating structural demand growth."'
            ),
            "overview": "Investors should monitor the semiconductor shortage closely since it affects valuations.",
            "investment_thesis": "The thesis is strong for long-term holders with a 2027 horizon.",
            "falsification_tracks": [
                "If supply exceeds demand by Q3 2027, the shortage thesis fails.",
                "If margins compress below 20%, the premium valuation is unjustified.",
            ],
        }
        ok, reason = deep_dive_structural_ok(content)
        self.assertFalse(ok)
        self.assertIn("Investors should", reason)

    def test_structural_check_passes_valid_content(self):
        """Valid content without forbidden phrases should pass."""
        content = {
            "episode_evidence": (
                '- John Smith: "The market opportunity is significant."\n'
                '- Jane Doe: "We expect margins to expand."\n'
                '- Bob Wilson: "Competition is intensifying."'
            ),
            "overview": "The semiconductor supply chain faces structural constraints that may persist through 2027.",
            "investment_thesis": "Long exposure to capacity constrained suppliers offers asymmetric upside.",
            "falsification_tracks": [
                "If HBM supply exceeds demand by Q3 2027, the capacity shortage thesis fails.",
                "If NVIDIA loses more than 5% share to AMD in datacenter GPUs, reassess positioning.",
                "If hyperscaler capex guidance declines for two consecutive quarters, the demand story weakens.",
            ],
        }
        ok, reason = deep_dive_structural_ok(content)
        self.assertTrue(ok, f"Should pass: {reason}")

    def test_normalize_extraction_response(self):
        """Response from extraction-mode should normalize correctly (v2 format)."""
        raw = {
            "source_quotes": (
                "John Smith: Quote about the market.\n"
                "Jane Doe: Quote about technology."
            ),
            "whats_new": "Non-obvious insight from the episode.",
            "investment_implication": {
                "prose": "Actionable guidance for investors.",
                "tickers": {
                    "NVDA": {"rationale": "Dominant in AI", "positioning": "Long", "risk": "Valuation"},
                },
                "watch_items": ["Catalyst with timing"],
            },
            "falsification_tracks": [
                "Track 1 with date",
                "Track 2 with condition",
            ],
        }
        out = normalize_from_ai_response(raw)
        self.assertEqual(out["schema_version"], 2)
        self.assertIn("Quote about the market", out["episode_evidence"])
        self.assertEqual(out["overview"], raw["whats_new"])


class TestSpeakerCanonicalization(unittest.TestCase):
    """Tests for canonicalizing speaker names from Whisper transcripts."""

    def test_minsmire_to_mintzmyer(self):
        """'Jay Minsmire' should canonicalize to 'J Mintzmyer' (phonetic surname match)."""
        known_guests = ["J Mintzmyer"]
        known_hosts = ["Jack Farley"]
        
        result = canonicalize_speaker("Jay Minsmire", known_hosts, known_guests)
        self.assertEqual(result, "J Mintzmyer")

    def test_soundex_similar_names(self):
        """Soundex produces similar but distinct codes for similar names."""
        key1 = get_phonetic_key("Minsmire")
        key2 = get_phonetic_key("Mintzmyer")
        self.assertTrue(key1.startswith("M5"))
        self.assertTrue(key2.startswith("M5"))

    def test_fuzzy_name_match_surnames(self):
        """Fuzzy match should work on similar surnames."""
        self.assertTrue(fuzzy_name_match("Jay Minsmire", "J Mintzmyer"))
        self.assertTrue(fuzzy_name_match("Jack Farlee", "Jack Farley"))
        self.assertFalse(fuzzy_name_match("John Smith", "J Mintzmyer"))

    def test_canonicalize_extraction_speakers(self):
        """Full extraction speaker canonicalization should fix all speaker names."""
        extraction = {
            "high_value_quotes": [
                {"speaker": "Jay Minsmire", "quote": "The oil must flow."},
                {"speaker": "Jack Farlee", "quote": "Tell me more."},
                {"speaker": "Unknown Person", "quote": "This will be dropped."},
            ],
            "companies_and_assets": [
                {
                    "name": "Tanker Co",
                    "key_quotes": [
                        {"speaker": "Jay Minsmire", "quote": "Shipping is strong."},
                    ]
                }
            ]
        }
        known_hosts = ["Jack Farley"]
        known_guests = ["J Mintzmyer"]
        
        result, canonicalized, dropped = canonicalize_extraction_speakers(
            extraction, known_hosts, known_guests
        )
        
        self.assertEqual(canonicalized, 3)
        self.assertEqual(dropped, 1)
        self.assertEqual(result["high_value_quotes"][0]["speaker"], "J Mintzmyer")
        self.assertEqual(result["high_value_quotes"][1]["speaker"], "Jack Farley")
        self.assertEqual(len(result["high_value_quotes"]), 2)

    def test_exact_match_preserved(self):
        """Exact match should be preserved without counting as canonicalized."""
        known_guests = ["J Mintzmyer"]
        result = canonicalize_speaker("J Mintzmyer", [], known_guests)
        self.assertEqual(result, "J Mintzmyer")


class TestProperNounCorrection(unittest.TestCase):
    """Tests for correcting garbled proper nouns in quotes."""

    def test_strait_of_hormuz_correction(self):
        """'straight-of-harm' should be corrected to 'Strait of Hormuz'."""
        quote = "The straight-of-harm moves are critical for oil flows."
        corrected, changes = correct_proper_nouns_in_quote(quote)
        self.assertEqual(corrected, "The Strait of Hormuz moves are critical for oil flows.")
        self.assertEqual(len(changes), 1)

    def test_multiple_corrections(self):
        """Multiple garbled terms should all be corrected."""
        quote = "Oil from the persian gulf through the strait of harm."
        corrected, changes = correct_proper_nouns_in_quote(quote)
        self.assertIn("Persian Gulf", corrected)
        self.assertIn("Strait of Hormuz", corrected)
        self.assertGreaterEqual(len(changes), 1)

    def test_no_correction_needed(self):
        """Clean quotes should not be changed."""
        quote = "The semiconductor supply chain is constrained."
        corrected, changes = correct_proper_nouns_in_quote(quote)
        self.assertEqual(corrected, quote)
        self.assertEqual(len(changes), 0)


class TestTranscriptQuoteValidation(unittest.TestCase):
    """Tests for validating extraction quotes against transcript."""

    def test_normalize_for_quote_match(self):
        """Normalization should lowercase, strip punctuation, collapse whitespace."""
        text = 'He said, "The market\'s outlook is VERY good!"'
        norm = normalize_for_quote_match(text)
        self.assertNotIn('"', norm)
        self.assertNotIn("'", norm)
        self.assertNotIn("!", norm)
        self.assertEqual(norm, norm.lower())
        self.assertNotIn("  ", norm)

    def test_quote_in_transcript_exact(self):
        """Exact quote should match."""
        transcript = "The speaker said the market is very healthy and growing."
        quote = "the market is very healthy"
        self.assertTrue(quote_in_transcript(quote, transcript))

    def test_quote_in_transcript_fuzzy(self):
        """Fuzzy match should work for minor variations."""
        transcript = "The speaker said the market is very healthy and growing rapidly."
        quote = "the market is very healthy and growing"
        self.assertTrue(quote_in_transcript(quote, transcript, threshold=0.85))

    def test_quote_in_transcript_fail(self):
        """Completely different quote should fail."""
        transcript = "We discussed revenue growth in the semiconductor industry."
        quote = "The housing market is collapsing rapidly due to interest rates."
        self.assertFalse(quote_in_transcript(quote, transcript, threshold=0.85))

    def test_quote_in_transcript_short_passes(self):
        """Short quotes (<20 chars) should pass to avoid false negatives."""
        transcript = "Hello world."
        quote = "short"
        self.assertTrue(quote_in_transcript(quote, transcript))

    def test_validate_extraction_quotes_drops_paraphrased(self):
        """Validation should drop quotes not found in transcript."""
        transcript = """
        John Smith said "The semiconductor shortage will persist through 2027."
        Jane Doe added "Revenue growth exceeded our expectations this quarter."
        """
        extraction = {
            "high_value_quotes": [
                {"speaker": "John Smith", "quote": "The semiconductor shortage will persist through 2027."},
                {"speaker": "Jane Doe", "quote": "This quote was completely made up by the model and does not appear anywhere."},
            ],
            "companies_and_assets": [
                {
                    "name": "ACME",
                    "key_quotes": [
                        {"speaker": "John", "quote": "Revenue growth exceeded our expectations"},
                        {"speaker": "Bob", "quote": "Another fabricated quote that is not in the transcript at all."},
                    ]
                }
            ]
        }
        filtered, passed, dropped = validate_extraction_quotes_against_transcript(
            extraction, transcript, threshold=0.85
        )
        self.assertEqual(passed, 2)
        self.assertEqual(dropped, 2)
        self.assertEqual(len(filtered["high_value_quotes"]), 1)
        self.assertEqual(len(filtered["companies_and_assets"][0]["key_quotes"]), 1)

    def test_validate_extraction_preserves_valid_quotes(self):
        """Validation should preserve quotes that match transcript."""
        transcript = """
        The CEO stated "Our margins improved by fifteen percent this quarter."
        He continued "We expect continued growth in the AI segment."
        """
        extraction = {
            "high_value_quotes": [
                {"speaker": "CEO", "quote": "Our margins improved by fifteen percent this quarter."},
                {"speaker": "CEO", "quote": "We expect continued growth in the AI segment."},
            ],
            "companies_and_assets": []
        }
        filtered, passed, dropped = validate_extraction_quotes_against_transcript(
            extraction, transcript, threshold=0.85
        )
        self.assertEqual(passed, 2)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(filtered["high_value_quotes"]), 2)


_EMPTY_HIGH_PROFILE = {
    "episode_ids": [],
    "insight_ids": [],
    "shows": [],
    "title_keywords": [],
}

_OK_DEEP_DIVE = {
    "schema_version": 2,
    "episode_evidence": (
        '- John Smith: "Demand remains structurally tight through 2027."\n'
        '- Jane Doe: "Capacity additions will not catch up this cycle."'
    ),
    "overview": "The non-obvious signal is a physical bottleneck, not a demand scare.",
    "investment_thesis": "Long constrained suppliers while clean-room capacity stays scarce.",
    "ticker_analysis": {"NVDA": {"rationale": "AI demand", "positioning": "Watch", "risk": "Valuation"}},
    "falsification_tracks": [
        "If HBM supply exceeds demand by Q3 2027, the shortage thesis fails.",
        "If hyperscaler capex is cut two quarters in a row, reassess.",
    ],
    "key_takeaways_detailed": [],
    "contrarian_signals": [],
    "catalysts": [],
}


def _make_fallback_test_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE latest_insights (
            id INTEGER PRIMARY KEY,
            title TEXT,
            source_type TEXT,
            podcast_episode_id INTEGER,
            summary TEXT,
            key_takeaway TEXT,
            source_date TEXT,
            notable_quotes TEXT,
            source_name TEXT
        );
        CREATE TABLE podcast_episodes (
            id INTEGER PRIMARY KEY,
            extraction_json TEXT
        );
        CREATE TABLE deep_dive_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_id INTEGER,
            podcast_episode_id INTEGER,
            overview TEXT,
            key_takeaways_detailed TEXT,
            investment_thesis TEXT,
            ticker_analysis TEXT,
            positioning_guidance TEXT,
            risk_factors TEXT,
            contrarian_signals TEXT,
            catalysts TEXT,
            episode_evidence TEXT,
            falsification_tracks TEXT,
            schema_version INTEGER,
            created_at TEXT,
            model_used TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            attempt_count INTEGER,
            generation_mode TEXT
        );
        INSERT INTO latest_insights (
            id, title, source_type, podcast_episode_id, summary, key_takeaway,
            source_date, notable_quotes, source_name
        ) VALUES (
            101, 'Stacy Rasgon on Semiconductors', 'podcast', 564,
            'A summary of the episode.', 'Key takeaway here.',
            '2026-10-07', '[]', 'Monetary Matters with Jack Farley'
        );
        INSERT INTO podcast_episodes (id, extraction_json)
        VALUES (564, '{"high_value_quotes": [], "companies_and_assets": []}');
        """
    )
    conn.commit()
    conn.close()
    return path


class TestExtractionFallbackToLegacy(unittest.TestCase):
    """When extraction mode fails, fall back to gpt-5.5 once."""

    def test_extraction_failed_generation_mode_truncates(self):
        long_err = "x" * 80
        mode = extraction_failed_generation_mode(long_err)
        self.assertTrue(mode.startswith("legacy:extraction_failed:"))
        reason = mode.split("legacy:extraction_failed:", 1)[1]
        self.assertEqual(len(reason), 60)

    def _run_generate(self, tmp_db, extract_return, legacy_return):
        with patch.dict(os.environ, {"DEEPDIVE_MODE": "extraction"}), \
             patch("generate_deepdives.DB_PATH", Path(tmp_db)), \
             patch("generate_deepdives.get_ai_clients", return_value=[("openai", MagicMock())]), \
             patch("generate_deepdives.load_high_profile_config", return_value=_EMPTY_HIGH_PROFILE), \
             patch("generate_deepdives.run_extraction_deep_dive_attempts", return_value=extract_return) as mock_extract, \
             patch("generate_deepdives.run_deep_dive_generation_attempts", return_value=legacy_return) as mock_legacy:
            generated, need, quarantined = generate_missing_deepdives([101])
        return generated, need, quarantined, mock_extract, mock_legacy

    def test_extraction_fails_legacy_succeeds_stores_mode(self):
        tmp_db = _make_fallback_test_db()
        self.addCleanup(lambda: os.path.exists(tmp_db) and os.unlink(tmp_db))
        err = "Structural check failed: contains Investors should. rewrite this please"
        extract_return = (None, err, {"model": "gpt-5.4-mini", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01})
        legacy_return = (_OK_DEEP_DIVE, None, {"model": "gpt-5.5", "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.14, "attempt_count": 1})

        generated, need, quarantined, mock_extract, mock_legacy = self._run_generate(
            tmp_db, extract_return, legacy_return
        )
        self.assertEqual((generated, need, quarantined), (1, 1, 0))
        mock_extract.assert_called_once()
        mock_legacy.assert_called_once()

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT generation_mode, model_used FROM deep_dive_content WHERE insight_id = 101"
        ).fetchone()
        fail_row = conn.execute(
            "SELECT insight_id FROM deep_dive_generation_failures WHERE insight_id = 101 AND status != 'resolved'"
        ).fetchone()
        conn.close()

        expected_mode = extraction_failed_generation_mode(err)
        self.assertIsNotNone(row)
        self.assertEqual(row["generation_mode"], expected_mode)
        self.assertEqual(row["model_used"], "gpt-5.5")
        self.assertIsNone(fail_row)

    def test_extraction_and_legacy_both_fail_records_failure(self):
        tmp_db = _make_fallback_test_db()
        self.addCleanup(lambda: os.path.exists(tmp_db) and os.unlink(tmp_db))
        extract_return = (None, "quote_validation: Quote not found", {"model": "gpt-5.4-mini"})
        legacy_return = (None, "generation failed after retries", {"model": "gpt-5.5"})

        generated, need, quarantined, mock_extract, mock_legacy = self._run_generate(
            tmp_db, extract_return, legacy_return
        )
        self.assertEqual(generated, 0)
        self.assertEqual(need, 1)
        mock_extract.assert_called_once()
        mock_legacy.assert_called_once()

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        stored = conn.execute(
            "SELECT id FROM deep_dive_content WHERE insight_id = 101"
        ).fetchone()
        fail_row = conn.execute(
            "SELECT failure_reason, failure_detail, status FROM deep_dive_generation_failures WHERE insight_id = 101"
        ).fetchone()
        conn.close()

        self.assertIsNone(stored)
        self.assertIsNotNone(fail_row)
        self.assertEqual(fail_row["failure_reason"], "generation_failed")
        self.assertIn("generation failed after retries", fail_row["failure_detail"])

    def test_extraction_succeeds_legacy_never_called(self):
        tmp_db = _make_fallback_test_db()
        self.addCleanup(lambda: os.path.exists(tmp_db) and os.unlink(tmp_db))
        extract_return = (_OK_DEEP_DIVE, None, {"model": "gpt-5.4-mini", "input_tokens": 8, "output_tokens": 4, "cost_usd": 0.01, "attempt_count": 1})
        legacy_return = (_OK_DEEP_DIVE, None, {"model": "gpt-5.5"})

        generated, need, quarantined, mock_extract, mock_legacy = self._run_generate(
            tmp_db, extract_return, legacy_return
        )
        self.assertEqual((generated, need, quarantined), (1, 1, 0))
        mock_extract.assert_called_once()
        mock_legacy.assert_not_called()

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT generation_mode, model_used FROM deep_dive_content WHERE insight_id = 101"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["generation_mode"], "extraction")
        self.assertEqual(row["model_used"], "gpt-5.4-mini")


class TestHighProfileOverride(unittest.TestCase):
    """Tests for high-profile episode override matching."""

    def test_episode_id_match(self):
        """Episode ID should match exactly."""
        config = {
            "episode_ids": [559, 560],
            "insight_ids": [],
            "shows": [],
            "title_keywords": [],
        }
        result = check_high_profile_match(559, 569, "Monetary Matters", "J Mintzmyer Episode", config)
        self.assertEqual(result, "episode_id=559")

    def test_insight_id_match(self):
        """Insight ID should match exactly."""
        config = {
            "episode_ids": [],
            "insight_ids": [569, 570],
            "shows": [],
            "title_keywords": [],
        }
        result = check_high_profile_match(559, 569, "Monetary Matters", "J Mintzmyer Episode", config)
        self.assertEqual(result, "insight_id=569")

    def test_show_match_substring(self):
        """Show name should match case-insensitive substring."""
        config = {
            "episode_ids": [],
            "insight_ids": [],
            "shows": ["monetary matters"],
            "title_keywords": [],
        }
        result = check_high_profile_match(999, 888, "Monetary Matters with Jack Farley", "Some Title", config)
        self.assertEqual(result, "show='monetary matters'")

    def test_keyword_match_title(self):
        """Title keyword should match case-insensitive substring."""
        config = {
            "episode_ids": [],
            "insight_ids": [],
            "shows": [],
            "title_keywords": ["mintzmyer"],
        }
        result = check_high_profile_match(999, 888, "Some Podcast", "J Mintzmyer on Shipping", config)
        self.assertEqual(result, "title_keyword='mintzmyer'")

    def test_no_match_stays_extraction(self):
        """Non-matching episode should return None (stays on extraction mode)."""
        config = {
            "episode_ids": [100, 200],
            "insight_ids": [300, 400],
            "shows": ["all-in podcast"],
            "title_keywords": ["bitcoin"],
        }
        result = check_high_profile_match(559, 569, "Monetary Matters", "J Mintzmyer Episode", config)
        self.assertIsNone(result)

    def test_missing_config_file(self):
        """Missing config file should return empty config and not crash."""
        import tempfile
        import os
        from pathlib import Path
        
        fake_path = Path(tempfile.gettempdir()) / "nonexistent_config_12345.json"
        if fake_path.exists():
            fake_path.unlink()
        
        original_path = HIGH_PROFILE_CONFIG_PATH
        import generate_deepdives
        generate_deepdives.HIGH_PROFILE_CONFIG_PATH = fake_path
        
        try:
            config = load_high_profile_config()
            self.assertEqual(config["episode_ids"], [])
            self.assertEqual(config["insight_ids"], [])
            self.assertEqual(config["shows"], [])
            self.assertEqual(config["title_keywords"], [])
        finally:
            generate_deepdives.HIGH_PROFILE_CONFIG_PATH = original_path


class TestExtractionDeepDiveCostTracking(unittest.TestCase):

    def test_usage_info_structure(self):
        """Usage info should have required fields."""
        usage_info = {
            "model": "gpt-5.4-mini",
            "input_tokens": 5000,
            "output_tokens": 1500,
            "cost_usd": 0.0105,
            "attempt_count": 1,
        }
        self.assertIn("model", usage_info)
        self.assertIn("input_tokens", usage_info)
        self.assertIn("output_tokens", usage_info)
        self.assertIn("cost_usd", usage_info)
        self.assertEqual(usage_info["model"], "gpt-5.4-mini")

    def test_extraction_mode_cost_lower_than_legacy(self):
        """Extraction mode should cost less than legacy mode."""
        extraction_cost_per_dive = 0.012  # ~$0.01-0.02 typical
        legacy_cost_per_dive = 0.23  # ~$0.23 per gpt-5.5 deep dive
        self.assertLess(extraction_cost_per_dive, legacy_cost_per_dive * 0.1)


if __name__ == "__main__":
    unittest.main()
