"""Oct 20 2026 G(ai)ndolf whole-site pundit sweep: names, bios, placeholder rows, transcript spellings."""
import copy
import json
import unittest
from pathlib import Path

import export_data
from publish_guard import parse_data_js

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
RULES = json.loads((Path(__file__).parent / "summary_overrides.json").read_text(encoding="utf-8"))
EXCLUDED = {291, 261, 442, 380, 381, 379, 303}
FIXED = {279: "Tyler Cowen", 461: "Brad Gerstner", 64: "Brad Gerstner", 481: "Eddy Lazzarin", 183: "Aaron Levie",
         205: "Steven Sinofsky", 184: "Steven Sinofsky", 132: "David Friedberg", 36: "David Friedberg",
         428: "Samo Burja", 187: "Luke Gromen", 293: "Satya Nadella", 186: "Anish Acharya", 395: "Neil Patil",
         236: "Louis-Vincent Gave", 232: "Harris Kupperman", 165: "Guillaume Verdon", 77: "Vishal Misra",
         192: "Deiya Pernas", 390: "Deiya Pernas", 391: "Dean Pernas", 215: "Kieran Cavanna"}
HIDDEN_LATER = {132, 36, 193, 461, 64, 205, 390}
OLD = ["Tyler Cowan", "Gershner", "Gersner", "Eddie Lazaran", "Aaron Levy", "Synopski", "Steve Sinofsky",
       "David Freiberg", "Jason Friedberg", "Samo Buria", "Luke Groman", "Sartina Della", "Anisha Charya",
       "Gavcal", "Prytorian", "Extrapic", "Stone X", "Sarah Fryer", "Pernos", "Pairness", "Shal Misra",
       "a16z partner Aaron", "Open AI released", "worse business than Open AI", "'Open AI spent",
       "If Open AI closes", "Anthropics Opus", "Anthropics revenue", "Neil Patel", "Groman", "Helden",
       "Synopski", "Copperman", "Pajarni", "Dugov", "Rosenswag", "Kieran Kavanaugh", "Kavanaugh's",
       "Finley-Finley", "Wissner-Wissner", "Levy argues", "Wolff", "Open AI's CFO"]


def _strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _p(pid, name, **kw):
    return dict({"id": pid, "name": name, "slug": name.lower().replace(" ", "-"), "mention_score": 1, "bio": ""}, **kw)


class MechanismTests(unittest.TestCase):
    def test_excludes_by_id_only(self):
        rows = [_p(261, "John Doe"), _p(1, "Real Person"), _p(303, "Grace One")]
        guests = [{"id": 261, "name": "Guest with colliding id", "slug": "g"}]  # not a pundit row
        out = export_data._apply_summary_overrides({"pundits": rows, "podcastGuests": guests})
        self.assertEqual([p["id"] for p in out["pundits"]], [1])
        self.assertEqual(len(out["podcastGuests"]), 1)

    def test_pundit_override_scoped(self):
        rows = [_p(268, "Sarah Friar", last_proof_snippet="Open AI's CFO, Sarah Fryer. Hi", bio="Fryer's expertise"),
                _p(2, "Other", last_proof_snippet="Open AI's CFO said")]
        out = export_data._apply_summary_overrides(rows)
        self.assertEqual(out[0]["last_proof_snippet"], "OpenAI's CFO, Sarah Friar. Hi")
        self.assertEqual(out[0]["bio"], "Friar's expertise")
        self.assertEqual(out[1]["last_proof_snippet"], "Open AI's CFO said")

    def test_neil_patel_not_global(self):
        out = export_data._apply_summary_overrides([{"summary": "Marketer Neil Patel spoke.", "podcast_episode_id": 1}])
        self.assertEqual(out[0]["summary"], "Marketer Neil Patel spoke.")
        out = export_data._apply_summary_overrides([_p(395, "Neil Patel")])
        self.assertEqual(out[0]["name"], "Neil Patil")

    def test_whole_word_names(self):
        out = export_data._apply_summary_overrides({"summary": "Tyler Cowan and Luke Groman's view; Tyler Cowane."})
        self.assertEqual(out["summary"], "Tyler Cowen and Luke Gromen's view; Tyler Cowane.")

    def test_surname_swap_idempotent_with_hyphen(self):
        # #193 (Alex Wissner-Gross) is hidden as a host since Oct 20; test the swap itself.
        rec = {"bio": "Gross has been vocal. Wissner-Gross agrees."}
        export_data._pundit_word_swap(rec, [["Gross", "Wissner-Gross"]])
        self.assertEqual(rec["bio"], "Wissner-Gross has been vocal. Wissner-Gross agrees.")
        rows = [_p(154, "Ed Finley Richardson", bio="Richardson's work.")]
        once = export_data._apply_summary_overrides(copy.deepcopy(rows))
        self.assertEqual(once[0]["bio"], "Finley-Richardson's work.")
        self.assertEqual(export_data._apply_summary_overrides(copy.deepcopy(once)), once)

    def test_rules_present(self):
        self.assertTrue(EXCLUDED <= {e["id"] for e in RULES["pundit_excludes"]})
        olds = {o for o, _ in RULES["global_name_replacements"]}
        for o in ("Tyler Cowan", "Jason Friedberg", "Aaron Levy", "Sartina Della", "Shal Misra"):
            self.assertIn(o, olds)
        self.assertNotIn("Neil Patel", olds)


class SiteDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dj = parse_data_js((SITE / "data.js").read_text(encoding="utf-8"))
        cls.files = {"data.js": {k: v for k, v in cls.dj.items() if k != "suggestedTerms"}}
        for f in ("archive.json", "pundits.json", "podcast_guests.json", "podcast_summaries.json"):
            cls.files[f] = json.loads((SITE / f).read_text(encoding="utf-8"))

    def test_old_strings_gone(self):
        for name, data in self.files.items():
            for s in _strings(data):
                for old in OLD:
                    self.assertNotIn(old, s, f"{old!r} still in {name}")

    def test_excluded_rows_gone_and_counts_match(self):
        for rows in (self.dj["pundits"], self.files["pundits.json"]):
            self.assertFalse(EXCLUDED & {p["id"] for p in rows})
        self.assertEqual(len(self.dj["pundits"]), len(self.files["pundits.json"]))

    def test_fixed_names_and_bios(self):
        for rows in (self.dj["pundits"], self.files["pundits.json"]):
            by = {p["id"]: p for p in rows}
            for pid, name in FIXED.items():
                if pid in HIDDEN_LATER:  # hosts / merged duplicates hidden on Oct 20 (G's decisions)
                    self.assertNotIn(pid, by)
                    continue
                self.assertEqual(by[pid]["name"], name)
            self.assertIn("CEO of Box", by[183]["bio"])
            self.assertNotIn("a16z", by[183]["bio"] + (by[183]["known_for"] or ""))
            self.assertEqual(by[186]["bio"], by[156]["bio"])
            self.assertEqual(by[293]["bio"], by[459]["bio"])
            self.assertIn("Gavekal", by[236]["bio"])
            self.assertIn("Praetorian Capital", by[232]["bio"])
            self.assertIn("Extropic", by[165]["bio"])
            self.assertIn("StoneX", by[105]["bio"])
            snip = by[268]["last_proof_snippet"] or ""
            if "CFO, Sarah" in snip:  # the export may pick a different snippet for this pundit
                self.assertIn("OpenAI's CFO, Sarah Friar", snip)


if __name__ == "__main__":
    unittest.main()
