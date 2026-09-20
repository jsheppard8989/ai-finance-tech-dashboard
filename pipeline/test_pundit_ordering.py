#!/usr/bin/env python3
"""Focused regression check for website pundit ordering."""

import unittest

from db_manager import _sort_pundits_for_site


class PunditOrderingTest(unittest.TestCase):
    def test_presence_precedes_recency_and_recency_breaks_ties(self):
        """Sort by mention_score_decayed (Presence) DESC, recency as tiebreaker."""
        pundits = [
            {
                "id": 1,
                "name": "High presence stale",
                "last_seen": "2026-05-14 18:46:46",
                "mention_score": 6,
                "mention_score_decayed": 4.5,
            },
            {
                "id": 2,
                "name": "Low presence recent",
                "last_seen": "2026-08-14 18:36:52",
                "mention_score": 1,
                "mention_score_decayed": 1.0,
            },
            {
                "id": 3,
                "name": "Medium presence recent",
                "last_seen": "2026-08-14 18:36:52",
                "mention_score": 2,
                "mention_score_decayed": 2.0,
            },
        ]

        ordered = _sort_pundits_for_site(pundits)

        # High presence first (4.5), then medium (2.0), then low (1.0)
        self.assertEqual(
            [pundit["name"] for pundit in ordered],
            ["High presence stale", "Medium presence recent", "Low presence recent"],
        )

    def test_recency_breaks_presence_ties(self):
        """When Presence (decayed) is equal, more recent pundit wins."""
        pundits = [
            {
                "id": 1,
                "name": "Same presence older",
                "last_seen": "2026-07-14 18:46:46",
                "mention_score_decayed": 2.0,
            },
            {
                "id": 2,
                "name": "Same presence newer",
                "last_seen": "2026-08-14 18:36:52",
                "mention_score_decayed": 2.0,
            },
        ]

        ordered = _sort_pundits_for_site(pundits)

        # Same decayed score, but newer last_seen wins
        self.assertEqual(
            [pundit["name"] for pundit in ordered],
            ["Same presence newer", "Same presence older"],
        )


if __name__ == "__main__":
    unittest.main()
