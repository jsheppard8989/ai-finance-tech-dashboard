"""Scorecard layout (preview): header date, expiry exits, plain-words tags, closed rows from the side file."""
import copy
import json
import re
import unittest

import build_trap_map as b

DATA = b.compute(json.loads(b.DATA.read_text(encoding="utf-8")))
CLOSED = [{"ticker": "AAA", "company": "A Co", "direction": "Long", "call": "Long from $1.", "opened": "2026-10-20",
           "closed": "2026-10-26", "ended": "Stop", "how": "Closed at the stop.", "allocated": 1000,
           "result_usd": -10.5, "approx": True},
          {"ticker": "BBB", "company": "B Co", "direction": "Long", "call": "Long from $2.", "opened": "2026-10-21",
           "closed": "2026-10-29", "ended": "Target", "how": "Closed at the target.", "allocated": None, "result_usd": None}]


class Scorecard(unittest.TestCase):
    def page(self, closed=CLOSED):
        return b.render_page(copy.deepcopy(DATA), closed_extra=closed)

    def test_one_header_date_and_one_disclaimer(self):
        p = self.page()
        self.assertEqual(p.count("Quotes as of"), 1)
        self.assertIn(f"Quotes as of {b._fmt_full(b.newest_quote_time(DATA))}", p)
        self.assertEqual(p.count("not advice"), 1)
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", p, flags=re.S))
        self.assertNotRegex(text, r"(?i)\b(bet|thin|grade|graded|grades|grading)\b")
        self.assertNotRegex(text, r"\d+\.\d%")  # dollars only

    def test_expected_exit_is_option_expiry(self):
        p = self.page()
        for r in DATA["rows"]:
            if r["trade"].get("expiry"):
                card = re.search(rf'id="{r["id"]}".*?</details>', p, re.S).group(0)
                self.assertIn(f'<div class="ex">{b.fmt_date(r["trade"]["expiry"])}</div>', card)
        self.assertIn("Until a stop is hit", p)

    def test_plain_words(self):
        p = self.page()
        self.assertIn("Net short</span> <span class=\"exp\">We expect the stock to fall", p)
        self.assertIn("We expect these stocks to rise", p)

    def test_closed_rows_at_bottom_only_stated_money(self):
        p = self.page()
        self.assertLess(p.index("Open positions"), p.index("Closed positions"))
        self.assertGreater(p.index("AAA"), p.index("Closed positions"))
        self.assertIn("Hit stop", p)
        self.assertIn("Hit target", p)
        self.assertIn("\u2212$10.50", p)
        bbb = p[p.index("BBB"):]
        self.assertNotIn("Result", bbb[:bbb.index("</article>")])

    def test_closed_empty_state(self):
        self.assertIn("No closed positions yet", self.page(closed=[]))

    def test_spy_total_at_top(self):
        p = self.page()
        spy = DATA["totals"]["spy_value"] - sum(x["dollars"] for x in DATA["benchmark"]["buys"])
        self.assertLess(p.index("Same money in the S&amp;P 500"), p.index("Open positions"))
        self.assertIn(b._sg(round(spy, 2)), p)


if __name__ == "__main__":
    unittest.main()
