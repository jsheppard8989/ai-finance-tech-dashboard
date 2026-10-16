"""Oct 15 decision: history gets settled past results only (Sep 4 YES, Aug 21 NO); debates stay paused."""
import json
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


class DebateHistory1015Tests(unittest.TestCase):
    def setUp(self):
        self.weeks = json.loads((SITE / "debate_history.json").read_text(encoding="utf-8"))["weeks"]
        self.by = {w["friday_iso"]: w for w in self.weeks}

    def test_settled_rows(self):
        self.assertEqual(self.by["2026-09-04"]["resolution_status"], "yes")
        self.assertIn("5.00 on Tue Sep 15", self.by["2026-09-04"]["resolution_notes"])
        self.assertEqual(self.by["2026-08-21"]["resolution_status"], "no")
        self.assertIn("7,764.70", self.by["2026-08-21"]["resolution_notes"])

    def test_no_pending_or_unrecovered_weeks(self):
        for w in self.weeks:
            self.assertNotEqual(w.get("resolution_status"), "pending", w["friday_iso"])
        for missing in ("2026-08-28", "2026-09-11", "2026-09-18", "2026-09-25", "2026-10-02", "2026-10-09"):
            self.assertNotIn(missing, self.by)
        isos = [w["friday_iso"] for w in self.weeks]
        self.assertEqual(isos, sorted(isos, reverse=True))

    def test_page_does_not_promise_new_contract(self):
        h = (SITE / "debait.html").read_text(encoding="utf-8")
        for phrase in ("No newer contract has been posted yet", "weekly pundit episode",
                       "Regenerate after contract changes", "paused"):
            self.assertNotIn(phrase, h)


if __name__ == "__main__":
    unittest.main()
