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


if __name__ == "__main__":
    unittest.main()
