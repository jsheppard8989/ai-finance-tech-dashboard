"""Oct 13 2026 whole-site sweep: quote-safe name swaps, Deep Dive drop_tickers, Trap Map anchors."""
import json
import re
import subprocess
import unittest
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"


def _data_js():
    out = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(require(process.argv[1])))",
                          str(SITE / "data.js")], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class NameReplacementTests(unittest.TestCase):
    def test_quote_safe(self):
        reps = [["Kevin Worsh", "Kevin Warsh"]]
        rec = {"summary": "Kevin Worsh leads. He said, 'Kevin Worsh has talked about it, he's sure.' Kevin Worsh"}
        export_data._apply_name_replacements(rec, reps)
        self.assertEqual(rec["summary"], "Kevin Warsh leads. He said, 'Kevin Worsh has talked about it, he's sure.' Kevin Warsh")

    def test_protected_keys_and_transcript_lines(self):
        reps = [["Eric Townsend", "Erik Townsend"]]
        rec = {"title": "Eric Townsend show", "slug": "eric-townsend", "last_proof_snippet": "I'm Eric Townsend.",
               "notable_quotes": [{"quote": "Eric Townsend here", "speaker": "Eric Townsend"}],
               "episode_evidence": "Eric Townsend: I'm Eric Townsend.\nHost Eric Townsend asked.",
               "tags": ["Eric Townsend"]}
        export_data._apply_name_replacements(rec, reps)
        self.assertEqual(rec["title"], "Eric Townsend show")
        self.assertEqual(rec["last_proof_snippet"], "I'm Eric Townsend.")
        self.assertEqual(rec["notable_quotes"][0], {"quote": "Eric Townsend here", "speaker": "Erik Townsend"})
        self.assertEqual(rec["episode_evidence"], "Erik Townsend: I'm Eric Townsend.\nHost Erik Townsend asked.")
        self.assertEqual(rec["tags"], ["Erik Townsend"])

    def test_eric_swap_only_hits_townsend(self):
        rules = export_data._load_override_rules()
        for old, new in rules.get("name_replacements", []) + rules.get("global_replacements", []):
            if re.search(r"\bEric\b", old):
                # Only explicit full-name Eric swaps are allowed (never a bare first name).
                self.assertIn(old, ("Eric Townsend", "Eric Jeng"))
        rec = {"summary": "Eric Schmidt and Eric Weinstein met Eric Townsend."}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(rec["summary"], "Eric Schmidt and Eric Weinstein met Erik Townsend.")

    def test_no_global_moonshots_live_guest_fix(self):
        gov = json.loads((ROOT / "pipeline" / "guest_overrides.json").read_text())
        self.assertNotIn("Moonshots Live", gov.get("fixes", {}))

    def test_rejected_swaps_absent(self):
        rules = export_data._load_override_rules()
        olds = {o for o, _ in rules.get("name_replacements", []) + rules.get("global_replacements", [])}
        for bad in ("Saudi Ramco", "Warren Buffet would", "Shinyo Yamanaka"):
            self.assertNotIn(bad, olds)
        news = json.dumps(rules["summaries"])
        self.assertNotIn("Grok Bot is used as the example", news)

    def test_existing_rules_kept(self):
        rules = export_data._load_override_rules()
        ids = {s.get("insight_id") for s in rules["summaries"]}
        self.assertTrue({572, 579, 580, 581, 582, 584, 420, 573, 578}.issubset(ids))
        self.assertTrue(any(o == "Charles Le Manides" for s in rules["summaries"] for o, _ in s["replacements"]))
        self.assertGreaterEqual(len(rules["global_replacements"]), 44)


class DropTickerTests(unittest.TestCase):
    def test_deep_dive_ticker_analysis(self):
        self.assertEqual(export_data._drop_ticker_analysis({"GROQ": {}, "NVDA": {}}, ["groq"]), {"NVDA": {}})
        self.assertEqual(json.loads(export_data._drop_ticker_analysis('{"GROQ": {}}', ["GROQ"])), {})
        rec = {"insight_title": "Is Claude Conscious? Pope Rejects, Model Welfare Movement, X",
               "ticker_analysis": {"GROQ": {"positioning": "Watch"}}, "key_tickers": ["GROQ"]}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(rec["ticker_analysis"], {})
        self.assertEqual(rec["key_tickers"], [])

    def test_published_579_has_no_groq(self):
        dd = _data_js()["deepDives"]["579"]
        self.assertNotIn("GROQ", json.dumps(dd["ticker_analysis"]))
        self.assertNotIn("GROQ", json.dumps(dd.get("key_tickers")))


class PublishedSweepTests(unittest.TestCase):
    def test_names_fixed_and_slugs_kept(self):
        data = _data_js()
        pundits = json.loads((SITE / "pundits.json").read_text(encoding="utf-8"))
        p = next(x for x in pundits if x["id"] == 478)
        self.assertEqual((p["name"], p["slug"]), ("Amjad Masad", "amjag-masad"))
        blob = json.dumps(data["archive"]) + json.dumps(data["deepDives"])
        for bad in ("Mark Andrewson", "Patrick Suresne", "Talent Energy"):
            self.assertNotIn(bad, blob)

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "site" / "trap-map.html").exists(), "Trap Map retired 2026-10-22")
    def test_trap_home_links_resolve(self):
        html = (ROOT / "site" / "trap-map.html").read_text(encoding="utf-8")
        anchors = set(re.findall(r'\bid="([^"]+)"', html))
        home = json.loads((SITE / "trap_map_home.json").read_text(encoding="utf-8"))
        ids = [t["id"] for t in home.get("last_monitored", [])] + [w["trap_id"] for w in home.get("upcoming_watches", [])]
        for i in ids:
            self.assertIn(i, anchors)


if __name__ == "__main__":
    unittest.main()
