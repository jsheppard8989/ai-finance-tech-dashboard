"""Style gate: public text never calls anything a 'bet' (Oct 2026 rule). Warn-only."""
import json
import re
import subprocess
import unittest
from pathlib import Path

import export_data
from site_text_sanitize import (
    STYLE_GATE_MISSES, apply_style_gate, find_style_gate_hits, report_style_gate_misses, style_gate_hits,
)

SITE = Path(__file__).resolve().parent.parent / "site" / "data"


class StyleGateTests(unittest.TestCase):
    def test_flags_plain_wording(self):
        self.assertTrue(style_gate_hits("He is betting on robots."))
        self.assertTrue(style_gate_hits("a big bet on AI"))

    def test_exemptions(self):
        self.assertEqual(style_gate_hits('He said "big bets" matter.'), [])
        self.assertEqual(style_gate_hits("The host says 'The labs are betting that RL works.'"), [])
        self.assertEqual(style_gate_hits("Alphabet's Other Bets losses grew."), [])
        self.assertEqual(style_gate_hits("Better alphabet between Tibet beta."), [])
        rec = {"title": "The $1B Bet", "insight_title": "Betting on America",
               "notable_quotes": [{"quote": "big bets", "speaker": "X"}],
               "net_worth_source": "https://x.com/blockchain-bets/", "summary": "fine"}
        self.assertEqual(find_style_gate_hits(rec), [])

    def test_warn_only_never_mutates_or_raises(self):
        rec = {"summary": "a bet on AI"}
        out = apply_style_gate(rec)
        self.assertEqual(out, {"summary": "a bet on AI"})
        self.assertEqual(report_style_gate_misses(), 1)
        self.assertEqual(STYLE_GATE_MISSES, [])

    def test_overrides_route_swaps(self):
        rec = {"title": "Elon's $60B Cursor Bet", "summary": "investors who bet against Wirecard"}
        export_data._apply_summary_overrides([rec])
        self.assertEqual(rec["summary"], "investors who shorted Wirecard")
        self.assertEqual(rec["title"], "Elon's $60B Cursor Bet")

    def test_overrides_do_not_touch_bet_free_or_exempt_text(self):
        rules = export_data._load_override_rules()
        bet = re.compile(r"\b(bets?|betting)\b", re.I)
        for old, new in rules["global_replacements"]:
            if bet.search(old):
                self.assertNotIn("Other Bets", old)
                self.assertFalse(bet.search(new), new)

    def test_published_files_clean(self):
        for name in ("archive", "podcast_summaries", "pundits", "podcast_guests"):
            data = json.loads((SITE / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(find_style_gate_hits(data), [], name)
        js = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(require(process.argv[1])))",
                             str(SITE / "data.js")], capture_output=True, text=True, check=True).stdout
        self.assertEqual(find_style_gate_hits(json.loads(js)), [])


if __name__ == "__main__":
    unittest.main()
