"""Red Team audit 2026-10-16: name fixes (Anthropic/OpenAI/Theo Jaffee/Joshua Achiam/Aalo),
guest lines 589/590/593, debait self-match hold, ASTS Oct 15 close, Trap Map last_monitored."""
import json
import re
import unittest
from datetime import date
from pathlib import Path

import debate_quality
import export_data
import name_normalizer

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PIPE = ROOT / "pipeline"


class RedTeam1016Tests(unittest.TestCase):
    def test_name_replacements(self):
        name_normalizer.reload_known()
        rec = {"summary": "Theojaffee interviews Joshua Ahoyom, chief futurist at Open AI, on Anthropics' "
                          "growth, Anthropics Opus 4.7 and Alo Atomics. 'Open AI spent $34 billion'"}
        name_normalizer.apply_to_cards(rec)
        s = rec["summary"]
        self.assertIn("Theo Jaffee interviews Joshua Achiam, chief futurist at OpenAI", s)
        self.assertIn("Anthropic's growth, Anthropic's Opus 4.7 and Aalo Atomics", s)
        self.assertIn("'Open AI spent $34 billion'", s)  # direct quote untouched
        again = dict(rec)
        name_normalizer.apply_to_cards(again)
        self.assertEqual(again["summary"], s)  # idempotent (no "AAalo")

    def test_site_has_no_misspellings_outside_quotes(self):
        raw = (SITE / "data" / "data.js").read_text(encoding="utf-8")
        for bad in ("Theojaffee", "Ahoyom", "Alo Atomics", '"guest_name": "Husband Billy Evans"'):
            self.assertNotIn(bad, raw)

    def test_guest_overrides(self):
        g = json.loads((PIPE / "guest_overrides.json").read_text(encoding="utf-8"))
        self.assertEqual(g["insight_guest_by_id"]["589"], "Billy Evans")
        self.assertEqual(g["insight_guest_by_id"]["590"], "Ian Quigley")
        self.assertEqual(g["insight_guest_by_id"]["593"], "Yasir Arafat")
        self.assertEqual(g["fixes"]["Husband Billy Evans"], "Billy Evans")

    def test_debate_contract_not_held_against_itself(self):
        c = json.loads((SITE / "audio" / "debate_contract.json").read_text(encoding="utf-8"))
        h = json.loads((SITE / "debate_history.json").read_text(encoding="utf-8"))
        own = c["friday_iso"]
        prior = [w["prompt"] for w in h["weeks"] if w.get("prompt") and w.get("friday_iso") != own]
        out = debate_quality.stamp_contract_publishable(c, prior)
        self.assertTrue(out["publishable"], out.get("publish_block_reason"))
        self.assertNotIn("publish_block_reasons", out)
        self.assertTrue(c["publishable"])
        html = (SITE / "debait.html").read_text(encoding="utf-8")
        self.assertIn("No new contract this week. The last contract", html)
        src = (PIPE / "export_data.py").read_text(encoding="utf-8")
        self.assertIn('str(w.get("friday_iso") or "").strip() == own', src)

    def test_trap_map_asts_and_last_monitored(self):
        t = (SITE / "trap-map.html").read_text(encoding="utf-8")
        self.assertIn("Oct 15 close ($44.46), ASTS fell about 26.7%", t)
        self.assertIn("$777.22 to $771.79, down about 0.7%", t)
        self.assertNotIn("lender test on leased capacity around Nov 10", t)
        for f in (SITE / "data" / "trap_map_home.json", PIPE / "trap_home_override.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            for row in d["last_monitored"]:
                m = re.fullmatch(r"Checked (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2})", row["updated_at"])
                self.assertIsNotNone(m, row)


if __name__ == "__main__":
    unittest.main()
