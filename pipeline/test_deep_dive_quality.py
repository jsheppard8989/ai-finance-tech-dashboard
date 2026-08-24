#!/usr/bin/env python3
"""Tests for Deep Dive v2 normalization and validation helpers."""

import unittest

from generate_deepdives import (
    CANNED_PHRASES,
    count_canned_phrases,
    normalize_from_ai_response,
    strip_recap_opening,
    evidence_vs_card_overlap,
)


class TestDeepDiveQuality(unittest.TestCase):
    def test_strip_recap_opening(self):
        raw = (
            "The podcast episode delves into Anthropic.\n"
            '- Dario: "Regulation is not the same as capture."\n'
            '- Host: "Markets are pricing safety premium."'
        )
        cleaned = strip_recap_opening(raw)
        self.assertNotIn("podcast episode", cleaned.lower())
        self.assertIn("Dario", cleaned)

    def test_count_canned_phrases(self):
        n = count_canned_phrases(
            "The unresolved tension and competitive dynamic imply allocator-relevant risk."
        )
        self.assertGreaterEqual(n, 2)

    def test_normalize_v2_response(self):
        raw = {
            "source_quotes": '- Guest: "We doubled buybacks."\n- Host: "Yields moved."',
            "whats_new": "Treasury buybacks are acting as a soft yield cap while AI capex pulls credit.",
            "falsification_tracks": [
                "If 10Y yields fall 50bp without new buybacks, the soft-cap narrative weakens.",
                "If AI capex guidance is cut two quarters in a row, the crowding-out story fades.",
            ],
            "investment_implication": {
                "prose": "Bond volatility stays elevated over the next 12 months if fiscal absorption continues.",
                "tickers": {"TLT": "Most direct expression of long-end yield stress."},
                "watch_items": ["Next Treasury refunding announcement"],
            },
        }
        out = normalize_from_ai_response(raw)
        self.assertEqual(out["schema_version"], 2)
        self.assertEqual(out["overview"], raw["whats_new"])
        self.assertIn("TLT", out["ticker_analysis"])
        self.assertEqual(out["key_takeaways_detailed"], [])

    def test_evidence_vs_card_overlap(self):
        card = "The podcast episode features a discussion on Anthropic and regulation."
        ev = "The podcast episode delves into Anthropic and its regulatory approach."
        sim = evidence_vs_card_overlap(card, "", ev)
        self.assertGreater(sim, 0.35)


if __name__ == "__main__":
    unittest.main()
