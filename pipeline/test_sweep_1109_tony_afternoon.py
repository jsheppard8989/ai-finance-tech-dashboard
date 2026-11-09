"""Nov 9 2026 Tony afternoon sweep (outside Insights cards G/#780 covered).

Confirmed durable fixes in summary_overrides.json:
- Amthropic -> Anthropic (DD 664 episode_evidence ASR)
- GDPX -> GDPx (SemiAnalysis GDPx; DD 658 catalysts/falsifiers + card 658 summary)
- pundit 616 slug/name Praveer Melwani
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parents[1]
OV = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())


class TestTonyAfternoonSweep1109(unittest.TestCase):
    def test_override_pairs_present(self):
        gn = {a: b for a, b in OV["global_name_replacements"]}
        self.assertEqual(gn.get("Amthropic"), "Anthropic")
        self.assertEqual(gn.get("GDPX"), "GDPx")
        nr = {a: b for a, b in OV["name_replacements"]}
        self.assertEqual(nr.get("Amthropic"), "Anthropic")
        rule_658 = next(s for s in OV["summaries"] if s.get("insight_id") == 658)
        reps = {a: b for a, b in rule_658["replacements"]}
        self.assertEqual(reps.get("Life Val and GDPX benchmarks"), "LifeVal and GDPx benchmarks")
        self.assertEqual(reps.get("LifeVal and GDPX benchmarks"), "LifeVal and GDPx benchmarks")
        self.assertNotIn("LifeVal and GDPX benchmarks", reps.values())
        po = next(p for p in OV["pundit_overrides"] if p.get("id") == 616)
        self.assertEqual(po["set"]["name"], "Praveer Melwani")
        self.assertEqual(po["set"]["slug"], "praveer-melwani")

    def test_apply_amthropic_and_gdpx(self):
        d = {
            "deepDives": {
                "664": {
                    "id": 664,
                    "insight_id": 664,
                    "insight_title": "Ramtin Naimi on the State of Venture Investing",
                    "episode_evidence": "Ramtin Naimi: It's SpaceX, Amthropic, and OpenAI, and Databricks",
                },
                "658": {
                    "id": 658,
                    "insight_id": 658,
                    "podcast_episode_id": 646,
                    "insight_title": "Big Tech’s $3T AI Bet, Claude Writes 90% of Anthropic’s Code",
                    "catalysts": [
                        "GDPX leaderboard updates over the next 12-24 months as the benchmark matures."
                    ],
                    "falsification_tracks": [
                        "By 2027-05-04, the official GDPX leaderboard shows top-model performance still below 25% on the benchmark, per GDPX official reports."
                    ],
                },
            },
            "archive": {
                "insights": [
                    {
                        "id": 658,
                        "podcast_episode_id": 646,
                        "title": "Big Tech’s $3T AI Bet, Claude Writes 90% of Anthropic’s Code",
                        "summary": "Diamandis cites Life Val and GDPX benchmarks to argue that AI is improving.",
                    }
                ]
            },
            "pundits": [
                {
                    "id": 616,
                    "name": "Praveer Mulwani",
                    "slug": "praveer-mulwani",
                    "mention_score": 1,
                    "last_proof_snippet": "Mulwani frames the organizational change",
                }
            ],
        }
        out = export_data._apply_summary_overrides(copy.deepcopy(d))
        self.assertIn("Anthropic", out["deepDives"]["664"]["episode_evidence"])
        self.assertNotIn("Amthropic", out["deepDives"]["664"]["episode_evidence"])
        self.assertIn("GDPx", out["deepDives"]["658"]["catalysts"][0])
        self.assertNotIn("GDPX", out["deepDives"]["658"]["catalysts"][0])
        self.assertNotIn("GDPX", out["deepDives"]["658"]["falsification_tracks"][0])
        self.assertIn("LifeVal and GDPx", out["archive"]["insights"][0]["summary"])
        self.assertNotIn("GDPX", out["archive"]["insights"][0]["summary"])
        self.assertNotIn("Life Val", out["archive"]["insights"][0]["summary"])
        p = out["pundits"][0]
        self.assertEqual(p["name"], "Praveer Melwani")
        self.assertEqual(p["slug"], "praveer-melwani")
        self.assertIn("Melwani", p["last_proof_snippet"])
        self.assertNotIn("Mulwani", p["last_proof_snippet"])


if __name__ == "__main__":
    unittest.main()
