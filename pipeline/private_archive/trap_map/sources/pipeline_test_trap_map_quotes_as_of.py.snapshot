"""quotes_as_of follows the newest price timestamp written to trap_map.json (not a stale hand-set value)."""
import copy
import json
import unittest

import build_trap_map as b

DATA = json.loads(b.DATA.read_text(encoding="utf-8"))


class QuotesAsOf(unittest.TestCase):
    def _d(self):
        d = copy.deepcopy(DATA)
        d["quotes_as_of"] = "2026-10-30T11:16:00-05:00"
        open_rows = [r for r in d["rows"] if r["status"] != "graded"]
        for r in open_rows:
            r["trade"]["mid_time"] = "2026-10-30T15:00-05:00"
        open_rows[0]["trade"]["mid_time"] = "2026-10-31T09:56:00+00:00"  # 4:56 AM CT, written in UTC
        d["benchmark"]["spy_close_time"] = "2026-10-30T15:00-05:00"
        return d

    def test_newest_timestamp_wins_and_renders_in_ct(self):
        d = b.compute(self._d())
        self.assertEqual(d["quotes_as_of"], "2026-10-31T04:56:00-05:00")
        self.assertIn("Quotes as of Oct 31, 4:56 AM CT", b.render_strip(d))
        self.assertIn("4:56 AM CT", b.render_page(d))
        self.assertNotIn("11:16 AM", b.render_page(d))

    def test_spy_and_graded_rows(self):
        d = self._d()
        d["benchmark"]["spy_close_time"] = "2026-11-02T15:00-06:00"
        d["rows"][0]["status"] = "graded"  # graded rows do not count
        self.assertEqual(b.newest_quote_time(d), "2026-11-02T15:00:00-06:00")

    def test_values_untouched(self):
        d = b.compute(self._d())
        for r, r0 in zip(d["rows"], DATA["rows"]):
            self.assertEqual((r["trade"].get("value"), r["trade"].get("cost")), (r0["trade"].get("value"), r0["trade"].get("cost")))

    def test_committed_data_is_current(self):
        self.assertEqual(DATA["quotes_as_of"], b.newest_quote_time(DATA))


if __name__ == "__main__":
    unittest.main()
