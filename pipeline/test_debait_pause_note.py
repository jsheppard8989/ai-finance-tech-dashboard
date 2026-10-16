"""Fix 3 (Oct 16 2026): series pause note on debait.html + series_status in debate_history.json."""
import json
import unittest
from pathlib import Path

import debate_weekly

REPO = Path(__file__).resolve().parent.parent
NOTE = ("Weekly contract paused since Sep 4. No contracts were posted for Aug 28, Sep 11, Sep 18, "
        "Sep 25, Oct 2, or Oct 9. The last contract (Week of 2026-09-04) resolved YES on Sep 15 "
        "(FRED DGS10 \u2265 5.00%).")


class PauseNote(unittest.TestCase):
    def test_history_series_status(self):
        h = json.loads((REPO / "site" / "debate_history.json").read_text(encoding="utf-8"))
        self.assertEqual(h["series_status"]["note"], NOTE)
        self.assertEqual(h["series_status"]["state"], "paused")
        fridays = {w.get("friday_iso") for w in h["weeks"]}
        for f in h["series_status"]["missing_fridays"]:
            self.assertNotIn(f, fridays)  # no stub contracts

    def test_page_note_exact(self):
        page = (REPO / "site" / "debait.html").read_text(encoding="utf-8")
        self.assertIn(NOTE.replace("\u2265", "\\u2265"), page)
        self.assertEqual(page.count("Weekly contract paused since Sep 4."), 1)

    def test_save_history_keeps_series_status(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "debate_history.json"
        src = json.loads((REPO / "site" / "debate_history.json").read_text(encoding="utf-8"))
        tmp.write_text(json.dumps(src), encoding="utf-8")
        old = debate_weekly.HISTORY_PATH
        orig_manifest = debate_weekly.write_archive_manifest
        try:
            debate_weekly.HISTORY_PATH = tmp
            debate_weekly.write_archive_manifest = lambda *a, **k: None
            h = debate_weekly.load_history()
            debate_weekly.save_history(h)
            self.assertEqual(json.loads(tmp.read_text(encoding="utf-8"))["series_status"]["note"], NOTE)
        finally:
            debate_weekly.HISTORY_PATH = old
            debate_weekly.write_archive_manifest = orig_manifest


if __name__ == "__main__":
    unittest.main()
