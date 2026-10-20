"""Oct 20 2026 G(ai)ndolf decisions: hosts hidden by id + corrected name, duplicate pundits merged,
wrong-person net worth removed, Waymo on Dolgov's card."""
import copy
import json
import unittest
from math import isclose
from pathlib import Path

import export_data
from publish_guard import parse_data_js
from pundit_exclusions import EXCLUDED_PUNDIT_IDS, is_excluded_pundit

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
RULES = json.loads((Path(__file__).parent / "summary_overrides.json").read_text(encoding="utf-8"))
HOST_NAMES = {"David Friedberg", "Alex Wissner-Gross", "Dave Blundin", "Marc Andreessen", "Salim Ismail",
              "Peter Diamandis", "David Sacks"}


def _p(pid, name, **kw):
    base = {"id": pid, "name": name, "slug": name.lower().replace(" ", "-"), "mention_score": 1,
            "mention_score_decayed": 1.0, "bio": "", "last_seen": "2026-01-01 00:00:00"}
    base.update(kw)
    return base


class ExclusionTests(unittest.TestCase):
    def test_ids_and_corrected_names(self):
        self.assertTrue({132, 36, 193} <= EXCLUDED_PUNDIT_IDS)
        self.assertTrue(is_excluded_pundit(132, "anything"))
        self.assertTrue(is_excluded_pundit(None, "David Friedberg"))
        self.assertFalse(is_excluded_pundit(1, "Tyler Cowen"))

    def test_misspelled_host_hidden_after_name_override(self):
        # "Jason Friedberg" is not on the blocked list, but the export corrects it to David
        # Friedberg first, and the corrected name is then blocked (any id).
        rows = [_p(9999, "Jason Friedberg"), _p(9998, "Alex Weiser Gross"), _p(1, "Tyler Cowan")]
        out = export_data._apply_summary_overrides(rows)
        self.assertEqual([p["name"] for p in out], ["Tyler Cowen"])


class MergeTests(unittest.TestCase):
    def test_merge_sum_latest_and_presence(self):
        rows = [_p(289, "Brad Gerstner", bio="CEO of Altimeter Capital", mention_score=1, mention_score_decayed=0.06,
                   last_seen="2026-06-17 04:37:46", last_episode_title="june ep"),
                _p(461, "Brad Gerstner", bio="other bio", mention_score=1, mention_score_decayed=0.47,
                   last_seen="2026-09-17 10:37:49", last_episode_title="new ep"),
                _p(64, "Brad Gerstner", bio="other bio", mention_score=2, mention_score_decayed=0.46,
                   last_seen="2026-08-17 03:01:06", last_episode_title="old ep")]
        out = export_data._apply_summary_overrides(rows)
        self.assertEqual(len(out), 1)
        g = out[0]
        self.assertEqual((g["id"], g["bio"], g["mention_score"], g["last_episode_title"]),
                         (289, "CEO of Altimeter Capital", 4, "new ep"))
        self.assertTrue(isclose(g["mention_score_decayed"], 1.88))
        # idempotent: a second pass doesn't add the counts again
        self.assertEqual(export_data._apply_summary_overrides(copy.deepcopy(out)), out)

    def test_merge_union_of_episodes_no_double_count(self):
        rows = [_p(192, "Deiya Pernas", _guest_episode_ids=[167, 392], mention_score=2, mention_score_decayed=0.02,
                   last_seen="2026-04-20 10:05:33"),
                _p(390, "Deiya Pernas", _guest_episode_ids=[392], mention_score=1, mention_score_decayed=0.19,
                   last_seen="2026-08-08 04:38:55", last_episode_title="Misunderstood Stocks")]
        out = export_data._apply_summary_overrides(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["mention_score"], 2)  # shared episode 392 counted once
        self.assertTrue(isclose(out[0]["mention_score_decayed"], 0.38))
        self.assertEqual(out[0]["last_episode_title"], "Misunderstood Stocks")
        self.assertNotIn("_guest_episode_ids", out[0])

    def test_merged_away_ids_also_in_excludes(self):
        ex = {e["id"] for e in RULES["pundit_excludes"]}
        for m in RULES["pundit_merges"]:
            self.assertTrue(set(m["merge"]) <= ex)
            self.assertNotIn(m["keep"], ex)


class SiteDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dj = parse_data_js((SITE / "data.js").read_text(encoding="utf-8"))
        cls.pj = json.loads((SITE / "pundits.json").read_text(encoding="utf-8"))

    def test_hosts_and_dupes_hidden(self):
        for rows in (self.dj["pundits"], self.pj):
            ids = {p["id"] for p in rows}
            self.assertFalse({132, 36, 193, 461, 64, 205, 171, 323, 431, 390} & ids)
            self.assertFalse(HOST_NAMES & {p["name"] for p in rows})
            names = [p["name"] for p in rows]
            for n in ("Brad Gerstner", "Steven Sinofsky", "Deiya Pernas"):
                self.assertEqual(names.count(n), 1, n)
            self.assertFalse([p for p in rows if "_guest_episode_ids" in p])
        self.assertEqual(len(self.dj["pundits"]), len(self.pj))

    def test_merged_numbers(self):
        by = {p["id"]: p for p in self.pj}
        self.assertEqual(by[289]["mention_score"], 4)   # episodes 64, 290, 406, 488
        self.assertEqual(by[184]["mention_score"], 7)   # 150, 161, 178, 255, 334, 437, 504
        self.assertEqual(by[192]["mention_score"], 2)   # 167, 392
        self.assertIn("Altimeter", by[289]["bio"])
        self.assertIn("Windows", by[184]["bio"])
        self.assertGreaterEqual(by[289]["last_seen"], "2026-09-17")
        self.assertGreaterEqual(by[184]["last_seen"], "2026-09-22")
        self.assertGreaterEqual(by[192]["last_seen"], "2026-08-08")

    def test_net_worth_na_and_waymo(self):
        for rows in (self.dj["pundits"], self.pj):
            by = {p["id"]: p for p in rows}
            for i in (395, 165, 156, 192):
                self.assertIsNone(by[i]["net_worth_usd"])
                self.assertFalse(by[i]["net_worth_source"])
                self.assertNotIn("net_worth", by[i])
        self.assertNotIn("daya-net-worth", json.dumps(self.dj["pundits"]) + json.dumps(self.pj))
        self.assertNotIn("Wemo", json.dumps(self.dj) + json.dumps(self.pj))


if __name__ == "__main__":
    unittest.main()
