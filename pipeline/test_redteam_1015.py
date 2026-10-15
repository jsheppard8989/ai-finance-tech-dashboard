"""Red Team audit 2026-10-15: Long & Short resolved label, basket % label, Trap Map dates/as-ofs,
SpaceX IPO catalyst graded, SMP-500 retired."""
import json
import re
import unittest
from pathlib import Path

import export_data
import fetch_prices

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def _section(raw, name):
    i = raw.index(f"\n  {name}: ") + len(f"\n  {name}: ")
    return json.JSONDecoder().raw_decode(raw, i)[0]


class RedTeam1015Tests(unittest.TestCase):
    def test_spacex_ipo_catalyst_override(self):
        rec = {"insight_title": "SpaceX/xAI $1.25T Super-Entity",
               "catalysts": ["H2 2026: Potential IPO of combined entity per management comments"]}
        export_data._apply_summary_overrides(rec)
        self.assertIn("SPCX on Jun 12, 2026", rec["catalysts"][0])
        other = {"title": "SpaceX-xAI Merger Forms $1.25T AI-Space Super-Entity",
                 "summary": "H2 2026: Potential IPO of combined entity per management comments"}
        export_data._apply_summary_overrides(other)
        self.assertIn("Potential IPO", other["summary"])  # rule is scoped to the one card

    def test_site_has_no_stale_ipo_line_or_smp500(self):
        raw = (SITE / "data" / "data.js").read_text(encoding="utf-8")
        self.assertNotIn("H2 2026: Potential IPO", raw)
        self.assertNotIn("SMP-500", raw)
        self.assertNotIn("SMP-500", (SITE / "price_data.json").read_text(encoding="utf-8"))
        self.assertIn("SPX", _section(raw, "priceSnapshot"))

    def test_smp500_retired_in_fetcher(self):
        self.assertNotIn("SMP-500", fetch_prices.YAHOO_SYMBOL_MAP)
        self.assertIn("SMP-500", fetch_prices.RETIRED_KEYS)

    def test_contract_resolved_and_note_not_stale(self):
        c = json.loads((SITE / "audio" / "debate_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(c["resolution_status"], "yes")
        self.assertNotIn("comfortably above", c["editorial_note"])
        self.assertNotIn("right now", c["editorial_note"])

    def test_debait_resolved_label(self):
        h = (SITE / "debait.html").read_text(encoding="utf-8")
        self.assertIn("Last contract (resolved)", h)
        self.assertIn("resolved-yes", h)
        self.assertNotIn("After the first Friday rollover", h)

    def test_basket_label_since_start(self):
        h = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertIn("since ${startDate}", h)

    def test_trap_map_dates(self):
        t = (SITE / "trap-map.html").read_text(encoding="utf-8")
        self.assertNotIn("Sun Dec 6", t)
        self.assertIn("Dec 6 (Sunday; payment due next business day, Dec 7)", t)
        self.assertIn("§113", t)
        self.assertNotIn("−15.2%", t)
        self.assertIn("Oct 14 close ($42.14)", t)
        self.assertNotIn("As of Oct 12, Telesat", t)
        self.assertNotIn("checked Oct 3", t)
        for f in (SITE / "data" / "trap_map_home.json", ROOT / "pipeline" / "trap_home_override.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            labels = {u["trap_id"]: u["date_label"] for u in d["upcoming_watches"]}
            self.assertFalse(labels["tsat"].startswith("Sun"))
            self.assertEqual(labels["hims"], "Mon Nov 9")


if __name__ == "__main__":
    unittest.main()
