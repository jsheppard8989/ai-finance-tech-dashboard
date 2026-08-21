#!/usr/bin/env python3
"""Focused regression check for website pundit ordering."""

import unittest

from db_manager import _sort_pundits_for_site


class PunditOrderingTest(unittest.TestCase):
    def test_recency_precedes_frequency_and_frequency_breaks_ties(self):
        pundits = [
            {
                "id": 1,
                "name": "Frequent but stale",
                "last_seen": "2026-05-14 18:46:46",
                "mention_score": 6,
            },
            {
                "id": 2,
                "name": "Recent once",
                "last_seen": "2026-08-14 18:36:52",
                "mention_score": 1,
            },
            {
                "id": 3,
                "name": "Recent twice",
                "last_seen": "2026-08-14 18:36:52",
                "mention_score": 2,
            },
        ]

        ordered = _sort_pundits_for_site(pundits)

        self.assertEqual(
            [pundit["name"] for pundit in ordered],
            ["Recent twice", "Recent once", "Frequent but stale"],
        )


if __name__ == "__main__":
    unittest.main()
