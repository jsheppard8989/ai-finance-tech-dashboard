"""Red Team audit 2026-10-14: ticker renames/drops, names, Long & Short grading."""
import json
import unittest
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

BAD = {"PQ&T", "PQT", "LTCM", "SQUARE", "SQ", "WORK", "ZEN", "NVIDIA", "CROWD", "E-TORO", "FIGMA",
       "TENABLE", "VALERO", "MARATHON PETROLEUM", "TALEN ENERGY", "ZOOM", "VISA", "UPWORK", "SMP-500",
       "SNP 500", "LVMA", "GEONET", "ALTIAS", "N/A", "C.O.R.N", "ARBOMB", "SPACEX", "OPENAI",
       "ANTHROPIC", "THROPIC"}


def _section(raw, name):
    i = raw.index(f"\n  {name}: ") + len(f"\n  {name}: ")
    return json.JSONDecoder().raw_decode(raw, i)[0]


def _tickers(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("tickers_mentioned", "key_tickers"):
                vv = json.loads(v) if isinstance(v, str) and v.startswith("[") else v
                out.extend(vv if isinstance(vv, list) else [])
            elif k == "ticker_analysis":
                vv = json.loads(v) if isinstance(v, str) and v.startswith("{") else v
                out.extend(vv.keys() if isinstance(vv, dict) else [])
            else:
                _tickers(v, out)
    elif isinstance(o, list):
        for v in o:
            _tickers(v, out)
    return out


class TickerOverrideTests(unittest.TestCase):
    def test_global_rename_and_drop(self):
        rec = {"title": "Any", "tickers_mentioned": ["SQ", "NVIDIA", "OPENAI", "AAPL", "SPACEX"],
               "ticker_analysis": {"SQ": {"r": 1}, "PQNT": {"r": 2}}, "summary": "SQL and Square stay"}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(rec["tickers_mentioned"], ["XYZ", "NVDA", "AAPL", "SPCX"])
        self.assertEqual(list(rec["ticker_analysis"]), ["XYZ", "PQNT"])
        self.assertEqual(rec["summary"], "SQL and Square stay")

    def test_json_string_tickers(self):
        rec = {"title": "Any", "tickers_mentioned": '["SQUARE", "SQ", "N/A"]'}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(json.loads(rec["tickers_mentioned"]), ["XYZ"])

    def test_per_card_workday(self):
        rec = {"insight_title": "Workday’s Last Workday? AI and the Future of Enterprise Software",
               "key_tickers": ["WORK"]}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(rec["key_tickers"], ["WDAY"])
        other = {"title": "Is Software Losing Its Head?", "key_tickers": ["WORK", "SAP"]}
        export_data._apply_summary_overrides(other)
        self.assertEqual(other["key_tickers"], ["SAP"])

    def test_real_pictet_etfs_kept(self):
        rec = {"title": "Any", "key_tickers": ["PQNT", "PQUS"]}
        export_data._apply_summary_overrides(rec)
        self.assertEqual(rec["key_tickers"], ["PQNT", "PQUS"])

    def test_published_data_clean(self):
        raw = (SITE / "data" / "data.js").read_text(encoding="utf-8")
        found = []
        for sec in ("archive", "mainContent", "deepDives"):
            found += _tickers(_section(raw, sec), [])
        for name in ("archive.json", "podcast_summaries.json"):
            found += _tickers(json.loads((SITE / "data" / name).read_text(encoding="utf-8")), [])
        self.assertEqual(sorted({t for t in found if str(t).upper() in BAD}), [])


class NameAndDebateTests(unittest.TestCase):
    def test_names(self):
        blob = (SITE / "data" / "pundits.json").read_text(encoding="utf-8") + (SITE / "debate_history.json").read_text(encoding="utf-8")
        for bad in ("Gwen Shotwell", "CEO of Space X", "Ben Harwitz", "Victor Hagani"):
            self.assertNotIn(bad, blob)

    def test_september_cdt(self):
        h = json.loads((SITE / "debate_history.json").read_text(encoding="utf-8"))
        for w in h["weeks"]:
            if w.get("resolves_iso", "").startswith("2026-09"):
                self.assertIn("CDT", w["expires_rule"])

    def test_contract_graded_yes(self):
        c = json.loads((SITE / "audio" / "debate_contract.json").read_text(encoding="utf-8"))
        self.assertEqual((c["bet_status"], c["resolution_status"]), ("yes", "yes"))
        self.assertIn("5.00 on Tue Sep 15, 2026", c["resolution_notes"])

    def test_debait_labels(self):
        html = (SITE / "debait.html").read_text(encoding="utf-8")
        self.assertNotIn("Bet status", html)
        self.assertNotIn("bet status", html)
        self.assertIn("Call status: ", html)
        self.assertIn("Prior weeks &amp; call status", html)
        self.assertIn(">SpaceX Model</a>", (SITE / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
