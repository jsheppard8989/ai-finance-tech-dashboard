#!/usr/bin/env python3
"""Tests for extraction-mode deep dive generation."""

import json
import unittest
from unittest.mock import MagicMock, patch

from generate_deepdives import (
    _validate_quotes_from_extraction,
    normalize_from_ai_response,
    deep_dive_structural_ok,
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
