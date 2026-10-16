"""Oct 16 2026 (G): Grepper -> Grepr (card 595) and context-gated bare 'Alo' -> 'Aalo' (card 593)."""
import copy
import json
import unittest
from pathlib import Path

import export_data
import name_normalizer as nn

REPO = Path(__file__).resolve().parent.parent


class ContextAlo(unittest.TestCase):
    def fix(self, card):
        c = copy.deepcopy(card)
        nn._apply_context_fixes(c)
        return c

    def test_bare_alo_fixed_in_aalo_card(self):
        c = self.fix({"id": 593, "overview": "Aalo Atomics builds reactors.",
                      "catalysts": ["First Alo factory commissioning milestones"],
                      "falsification_tracks": ["Alo is forced to depend on HALEU earlier"]})
        self.assertEqual(c["catalysts"][0], "First Aalo factory commissioning milestones")
        self.assertEqual(c["falsification_tracks"][0], "Aalo is forced to depend on HALEU earlier")
        self.assertIn("Aalo Atomics", c["overview"])

    def test_never_touches_halo_along_or_aalo(self):
        c = self.fix({"id": 1, "overview": "Aalo Atomics: Halo effect. Along the way, Alo grows. ALO ticker. Alonso.",})
        self.assertEqual(c["overview"], "Aalo Atomics: Halo effect. Along the way, Aalo grows. ALO ticker. Alonso.")

    def test_no_company_context_no_change(self):
        card = {"id": 2, "overview": "Alo is a yoga brand."}
        self.assertEqual(self.fix(card), card)

    def test_quotes_untouched(self):
        c = self.fix({"id": 3, "overview": "Aalo says \"Alo will win\" and Alo grows."})
        self.assertIn('"Alo will win"', c["overview"])
        self.assertTrue(c["overview"].endswith("and Aalo grows."))

    def test_idempotent(self):
        once = self.fix({"id": 4, "overview": "Aalo; Alo factory."})
        self.assertEqual(self.fix(once), once)


class Grepr(unittest.TestCase):
    def test_bet_to_thesis_then_grepr(self):
        obj = {"insights": [{"episode_title": "a16z: Jad Naous on observability",
                             "key_takeaway": "Grepper\u2019s core bet is that AI value moves to infra.",
                             "summary": "Grepper and Grepper's pipeline."}],
               "pundits": [{"name": "Jad Naous", "last_main_idea": "Grepper's core bet is cost."}]}
        export_data._apply_summary_overrides(obj)
        self.assertEqual(obj["insights"][0]["key_takeaway"], "Grepr\u2019s core thesis is that AI value moves to infra.")
        self.assertEqual(obj["insights"][0]["summary"], "Grepr and Grepr's pipeline.")
        self.assertEqual(obj["pundits"][0]["last_main_idea"], "Grepr's core thesis is cost.")

    def test_rules_present(self):
        so = json.loads((REPO / "pipeline" / "summary_overrides.json").read_text(encoding="utf-8"))
        reps = [tuple(p) for p in so["name_replacements"]]
        for p in [("Grepper", "Grepr"), ("Grepper\u2019s", "Grepr\u2019s")]:
            self.assertIn(p, reps)


if __name__ == "__main__":
    unittest.main()
