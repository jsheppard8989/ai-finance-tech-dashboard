#!/usr/bin/env python3
"""Tests for debate contract publish quality gates."""

import unittest

from debate_quality import (
    prompt_similarity,
    validate_contract_publishable,
    validate_debaters,
    validate_prompt_not_repetitive,
    validate_spx_strike_plausible,
)


class TestDebateQuality(unittest.TestCase):
    def test_rejects_duplicate_prompt(self):
        prior = ["Will the S&P 500 index close above 8,000 within the next 42 days?"]
        prompt = "Will the S&P 500 close above 8,000 in the next 42 days?"
        ok, err = validate_prompt_not_repetitive(prompt, prior)
        self.assertFalse(ok)
        self.assertIn("similar", err.lower())
        self.assertGreater(prompt_similarity(prompt, prior[0]), 0.72)

    def test_rejects_celebrity_debaters(self):
        ok, err = validate_debaters("Mark Zuckerberg", "Katherine Rooney Vera")
        self.assertFalse(ok)
        self.assertIn("Blocked", err)

    def test_rejects_trivial_spx_strike(self):
        ok, err = validate_spx_strike_plausible(
            "Will the S&P 500 index close above 6,000 within the next 42 days?",
            6400.0,
        )
        self.assertFalse(ok)
        self.assertIn("trivial", err.lower())

    def test_publishable_contract_sample(self):
        contract = {
            "prompt": "Will U.S. CPI core YoY print below 2.8% on the next official BLS release within the next 42 days?",
            "editorial_note": (
                "We picked this because recent podcast threads keep debating whether disinflation is "
                "real or a data artifact, and this contract forces a clean read on the next print."
            ),
            "resolution_clarity": {
                "source_of_truth": "BLS CPI report",
                "resolution_criteria": ["Resolves Yes if core CPI YoY is below 2.8% on the next scheduled release."],
            },
            "debater_a": "Katherine Rooney Vera",
            "debater_b": "Victor Hagani",
        }
        ok, err, _ = validate_contract_publishable(contract, ["Totally different prior question about tariffs?"])
        self.assertTrue(ok, err)


if __name__ == "__main__":
    unittest.main()
