#!/usr/bin/env python3
"""Spoken-form scrubber for ElevenLabs debate TTS."""

import unittest

from tts_spoken_text import spoken_for_tts


class SpokenForTtsTest(unittest.TestCase):
    def test_trailing_zero_percent_is_not_five_hundred(self):
        out = spoken_for_tts("print at or above 5.00% on any observation")
        self.assertIn("five percent", out)
        self.assertNotIn("5.00%", out)
        self.assertNotIn("5.0%", out)

    def test_keeps_meaningful_percent_decimals(self):
        out = spoken_for_tts("DGS10 sat at 4.79% and later 4.98%.")
        self.assertIn("four point seven nine percent", out)
        self.assertIn("four point nine eight percent", out)

    def test_strips_trailing_zeros_on_percent(self):
        out = spoken_for_tts("closes below 4.90% heading into October")
        self.assertIn("four point nine percent", out)
        self.assertNotIn("4.90%", out)

    def test_whole_percent_and_basis_points(self):
        out = spoken_for_tts("a 5% move and 21 bp scare")
        self.assertIn("five percent", out)
        self.assertIn("twenty-one basis points", out)

    def test_dollar_amount(self):
        out = spoken_for_tts("a $100B niche and $2.5 million raise")
        self.assertIn("one hundred billion dollars", out)
        self.assertIn("two point five million dollars", out)

    def test_leaves_years_and_clocks(self):
        src = "Friday 23 Oct 2026 12:00 PM CT"
        out = spoken_for_tts(src)
        self.assertIn("2026", out)
        self.assertIn("12:00", out)

    def test_host_line_from_current_scripts(self):
        src = (
            "Will the 10-year Treasury constant-maturity yield "
            "(FRED DGS10 official daily) print at or above 5.00% "
            "on any observation through Friday 23 Oct 2026 12:00 PM CT?"
        )
        out = spoken_for_tts(src)
        self.assertIn("five percent", out)
        self.assertNotIn("5.00%", out)


if __name__ == "__main__":
    unittest.main()
