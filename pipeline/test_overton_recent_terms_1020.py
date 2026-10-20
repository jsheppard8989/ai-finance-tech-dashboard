"""Oct 20 2026 (Jared YES 1:46 PM CT): Overton recent slots + suggested-terms extractor fix."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import db_manager
import export_data
from manage_suggested_terms import SuggestedTermsManager
from publish_guard import parse_data_js

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "t.db")
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE definitions (id INTEGER PRIMARY KEY, term TEXT)")
        self.m = SuggestedTermsManager(db_path=self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def terms(self, text):
        return [t["term"] for t in self.m.extract_terms_from_content(text, "podcast", "src")]

    def test_bare_whitespace_quote_is_not_a_term(self):
        self.assertEqual(self.terms('it does not raise the "ceiling" of quality for anyone at all'), [])
        self.assertEqual(self.terms('after Anthropic\u2019s "cloud design" announcement, Figma grew'), [])
        self.assertEqual(self.terms('a new "super intelligence," force chaired by the director'), [])

    def test_definition_syntax_matches(self):
        self.assertEqual(self.terms('"Reward hacking": when a model games its objective function'),
                         ["Reward hacking"])
        self.assertEqual(self.terms('"Return to Tangibles" - a shift of capital into physical assets'),
                         ["Return to Tangibles"])
        self.assertEqual(self.terms('\u201cCompute glut\u201d \u2014 too much AI capacity chasing demand'),
                         ["Compute glut"])

    def test_punctuation_stripped_and_generic_words_skipped(self):
        self.assertEqual(self.m.normalize_term('"super intelligence,"'), "super intelligence")
        self.assertEqual(self.terms('"floor": the minimum level anyone can reach today'), [])
        self.assertEqual(self.terms('"Design": the new code for every single team'), [])

    def test_repeat_scans_count_distinct_sources(self):
        rec = {"term": "Reward hacking", "definition": "x" * 20, "source_context": "Show A - Ep 1"}
        self.assertTrue(self.m._add_or_update_term(dict(rec), "auto_extracted"))
        for _ in range(5):  # same summary rescanned on later runs
            self.m._add_or_update_term(dict(rec), "auto_extracted")
        self.m._add_or_update_term(dict(rec, source_context="Show B - Ep 9"), "auto_extracted")
        with sqlite3.connect(self.db) as c:
            mc, sd = c.execute("SELECT mention_count, source_diversity FROM suggested_terms").fetchone()
        self.assertEqual((mc, sd), (2, 2))


class RecentOvertonTests(unittest.TestCase):
    def test_recent_window(self):
        today = date(2026, 10, 20)
        self.assertTrue(db_manager._is_recent_first_heard("2026-09-20", 30, today))
        self.assertFalse(db_manager._is_recent_first_heard("2026-09-19", 30, today))
        self.assertFalse(db_manager._is_recent_first_heard(None, 30, today))

    def test_candidates_drop_fragments_and_duplicates(self):
        rows = [
            {"term": "super intelligence,", "mention_count": 36, "novelty_score": 9},
            {"term": "Super intelligence", "mention_count": 3, "novelty_score": 5},
            {"term": "Return to Tangibles", "mention_count": 5, "novelty_score": 2.5},
            {"term": "One-off", "mention_count": 1, "novelty_score": 8},
            {"term": "AGI", "mention_count": 9, "novelty_score": 7, "is_established": True},
        ]
        out = db_manager.select_recent_overton_candidates(rows, [{"term": "Superintelligence"}])
        self.assertEqual([r["term"] for r in out], ["Return to Tangibles"])
        self.assertTrue(out[0]["first_heard_recent"])


class OverrideAndSiteTests(unittest.TestCase):
    def test_term_overrides(self):
        terms = [{"id": 945, "term": "floor"}, {"id": 946, "term": "cloud design", "definition": "old"},
                 {"id": 859, "term": "super intelligence,"}, {"id": 947, "term": "Health bench"}]
        rules = [r for r in export_data._load_override_rules()["terms"] if r.get("scope", "suggested") == "suggested"]
        export_data._apply_term_overrides(terms, rules)
        self.assertEqual([t["id"] for t in terms], [946, 947])
        self.assertEqual(terms[0]["term"], "Claude Design")
        self.assertIn("interviewer noted the company grew 48%", terms[0]["definition"])
        mc = {"overton": [{"id": 305, "term": "super intelligence,"}, {"id": 1, "term": "Taste"}]}
        export_data._apply_overton_term_overrides(mc)
        self.assertEqual([o["term"] for o in mc["overton"]], ["Taste"])

    def test_hand_picked_terms_unchanged(self):
        cur = json.loads((SITE / "data" / "curated_overton.json").read_text())["curated"]
        self.assertEqual([c["term"] for c in cur if c["status"] == "active"],
                         ["Reserve scarcity regime", "Treasury basis trade", "Compute glut",
                          "Gating mechanism", "Ton-miles"])

    def test_index_reserves_two_of_four_slots(self):
        html = (SITE / "index.html").read_text()
        self.assertIn("const AUTO_SLOTS = 4, RECENT_SLOTS = 2, RECENT_DAYS = 30;", html)
        self.assertIn("main.overton_recent", html)

    def test_shipped_data(self):
        d = parse_data_js((SITE / "data" / "data.js").read_text(encoding="utf-8"))
        ids = {t["id"] for t in d["suggestedTerms"]}
        self.assertFalse(ids & {945, 859})
        for t in d["suggestedTerms"]:
            self.assertNotEqual(t["term"], "cloud design")
        self.assertGreaterEqual(len(d["mainContent"].get("overton_recent", [])), 2)
        for sec in ("archive", "mainContent"):
            for o in d[sec].get("overton", []):
                self.assertNotEqual(o["term"], "super intelligence,")


if __name__ == "__main__":
    unittest.main()
