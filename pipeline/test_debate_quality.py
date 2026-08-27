#!/usr/bin/env python3
"""Tests for debate contract publish quality gates."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from debate_weekly import (
    build_speech_evidence_context,
    generate_speeches,
    load_editorial_contract,
    validate_speeches,
)
from debate_quality import (
    prompt_similarity,
    validate_contract_publishable,
    validate_debaters,
    validate_prompt_not_repetitive,
    validate_spx_strike_plausible,
)


class TestDebateQuality(unittest.TestCase):
    def test_speech_prompt_requires_truth_seeking_and_grounded_evidence(self):
        generated = {
            "yes_speech": (
                "Alice Smith.\n\nThe long of it is grounded in the supplied evidence and a clear "
                "causal mechanism.\n\nConcession. I would update if the mechanism fails."
            ),
            "no_speech": (
                "Bob Jones.\n\nThe short of it is grounded in the supplied evidence and a clear "
                "causal mechanism.\n\nConcession. I would update if the mechanism holds."
            ),
        }
        with patch("debate_weekly.llm_chat_json", return_value=generated) as chat:
            generate_speeches(
                "test",
                object(),
                "Will the policy pass?",
                "policy",
                "Alice Smith",
                "Bob Jones",
                evidence_context='{"fact": "Officially verified."}',
            )
        system_prompt = chat.call_args.args[2]
        user_prompt = chat.call_args.args[3]
        self.assertIn("Maximize truth and understanding", system_prompt)
        self.assertIn("first principles", system_prompt)
        self.assertIn("Never invent evidence", system_prompt)
        self.assertIn("Officially verified.", user_prompt)

    def test_speech_evidence_uses_only_contract_attached_material(self):
        context = build_speech_evidence_context(
            {
                "editorial_note": "Editor-reviewed context.",
                "evidence_brief": [{"fact": "Verified fact.", "source": "Official source"}],
                "unreviewed_field": "Do not include this.",
            }
        )
        self.assertIn("Verified fact.", context)
        self.assertIn("Editor-reviewed context.", context)
        self.assertNotIn("Do not include this.", context)

    def test_speech_structure_validation(self):
        validate_speeches(
            "Alice Smith.\n\nThe long of it is the mechanism matters.\n\nConcession. This could be wrong.",
            "Bob Jones.\n\nThe short of it is the tradeoff matters.\n\nConcession. This could be wrong.",
            "Alice Smith",
            "Bob Jones",
        )
        with self.assertRaisesRegex(ValueError, "Concession"):
            validate_speeches(
                "Alice Smith.\n\nThe long of it is the mechanism matters.",
                "Bob Jones.\n\nThe short of it is the tradeoff matters.\n\nConcession. This could be wrong.",
                "Alice Smith",
                "Bob Jones",
            )

    def test_speech_validation_rejects_non_english_paragraph(self):
        with self.assertRaisesRegex(ValueError, "entirely in English"):
            validate_speeches(
                "Alice Smith.\n\nThe long of it is the mechanism matters.\n\nConcession. This could be wrong.",
                (
                    "Bob Jones.\n\nThe short of it is the tradeoff matters.\n\n"
                    "这是一整段不应该发送到语音合成器的中文内容。\n\n"
                    "Concession. This could be wrong."
                ),
                "Alice Smith",
                "Bob Jones",
            )

    def test_loads_editorial_contract_only_for_scheduled_friday(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            path.write_text(
                json.dumps({"friday_iso": "2026-08-28", "prompt": "Approved?"}),
                encoding="utf-8",
            )
            self.assertIsNotNone(load_editorial_contract("2026-08-28", path))
            self.assertIsNone(load_editorial_contract("2026-09-04", path))

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
