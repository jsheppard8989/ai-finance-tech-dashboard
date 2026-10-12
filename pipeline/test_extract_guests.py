#!/usr/bin/env python3
"""Tests for podcast guest name extraction heuristics."""

import unittest

from extract_guests import extract_guest_name, is_plausible_person_name


class TestGuestExtraction(unittest.TestCase):
    def test_accepts_real_guest_with_topic(self):
        name = extract_guest_name(
            "China's Endgame: ASI Timelines with Alvin Graylin | #281",
            "Guest Alvin Graylin discusses AI.",
            "Dwarkesh Podcast",
        )
        self.assertEqual(name, "Alvin Graylin")

    def test_rejects_title_fragment(self):
        self.assertIsNone(
            extract_guest_name(
                "Ground Infrastructure",
                "Episode about data centers.",
                "The a16z Show",
            )
        )
        self.assertFalse(is_plausible_person_name("also touches"))

    def test_rejects_quoted_headline(self):
        self.assertFalse(is_plausible_person_name('"The Best Time to Invest"'))
        self.assertIsNone(
            extract_guest_name(
                '"I Don\'t Believe the Stagflation Narrative"',
                "",
                "Monetary Matters with Jack Farley",
            )
        )

    def test_strips_role_prefix_fix(self):
        name = extract_guest_name(
            "Rates outlook with banking specialist Chris Wayland",
            "",
            "Monetary Matters with Jack Farley",
        )
        self.assertEqual(name, "Chris Wayland")

    def test_rejects_openclaw_product_name(self):
        self.assertIsNone(extract_guest_name("OpenClaw", "OpenClaw demo.", "Moonshots with Peter Diamandis"))

class TestOct2026GuestFixes(unittest.TestCase):
    """Cards 571/574/577: names must survive re-extraction and export."""

    def test_extractor_strips_org_possessive_before_colon(self):
        self.assertEqual(extract_guest_name("Google X's Astro Teller: Big Ideas", "", "Moonshots"), "Astro Teller")

    def test_extractor_reads_trailing_pipe_guest(self):
        self.assertEqual(extract_guest_name("Chips and Power | Jane Doe", "", "The a16z Show"), "Jane Doe")

    def test_override_titles(self):
        self.assertEqual(extract_guest_name(
            "Google X's Astro Teller: The $1B Bet No CEO Will Back, Moonshots 3x Cheaper in 16 Yrs, and Clean Water at 1\u00a2/L| EP #300",
            "", "Moonshots with Peter Diamandis"), "Astro Teller")
        self.assertEqual(extract_guest_name(
            "Synthesis Superintelligence: from Semiconductors to Superconductors \u2014 Periodic Labs\u2019 Liam Fedus and Ekin Dogus Cubuk",
            "", "Latent Space: The AI Engineer Podcast"), "Liam Fedus and Ekin Do\u011fu\u015f \u00c7ubuk")
        self.assertEqual(extract_guest_name("Chips, Memory, and Power | Pat Gelsinger", "", "The a16z Show"), "Pat Gelsinger")

    def test_export_stamps_insight_guest_names(self):
        from export_data import _apply_guest_export_overrides
        mc = {"insights": [{"id": 571, "guest_name": "Google X's Astro Teller"},
                           {"id": 574, "guest_name": "Synthesis Superintelligence"},
                           {"id": 577, "guest_name": None}]}
        guests = [{"name": "Synthesis Superintelligence"}, {"name": "Google X's Astro Teller"}, {"name": "Pat Gelsinger"}]
        mc, guests = _apply_guest_export_overrides(mc, guests)
        self.assertEqual([i["guest_name"] for i in mc["insights"]],
                         ["Astro Teller", "Liam Fedus and Ekin Do\u011fu\u015f \u00c7ubuk", "Pat Gelsinger"])
        names = [g["name"] for g in guests]
        self.assertNotIn("Synthesis Superintelligence", names)
        self.assertNotIn("Google X's Astro Teller", names)


if __name__ == "__main__":
    unittest.main()
