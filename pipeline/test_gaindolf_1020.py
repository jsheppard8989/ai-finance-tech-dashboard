"""Oct 20 2026 G(ai)ndolf fixes: cards 601 (ep 590), 602 (ep 591), 598 (ep 587).

Pins the durable overrides (so the next export keeps them) and the shipped site data.
"""
import copy
import json
import unittest
from pathlib import Path

import export_data
from publish_guard import parse_data_js

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
OLD_601 = "What Happens When Al Agents Can Spend Your Money?"
NEW_601 = "Why a $1M Startup Wasn't Worth Building in the Age of AI"
TITLE_591 = "When AI Agents Start Spending Your Money | Alex Rampell & Terry Angelos"
QUOTE_48 = "Because I read your quarterly report after that announcement, you guys grew 48% year over year."


def _strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _fixture():
    return {
        "insights": [
            {"id": 601, "podcast_episode_id": 590, "title": OLD_601, "guest_name": "Jean Denigrez",
             "summary": "Alex Rampell interviews Jean Denigrez about Town.",
             "notable_quotes": [
                 {"speaker": "Jean Denigrez", "quote": "What if open AI is not the best model provider?"},
                 {"speaker": "Jean Denigrez", "quote": "contacts that's being created on time and so..."}]},
            # A different episode that happens to share the old title: must stay untouched.
            {"id": 591, "podcast_episode_id": 581, "title": OLD_601, "summary": "open AI created on time"},
            {"id": 602, "podcast_episode_id": 591, "title": "Dylan Field: Is AI Replacing Designers?",
             "summary": "after Anthropic\u2019s \"cloud design\" announcement, Figma\u2019s business did not "
                        "meaningfully suffer and the company grew 48% year over year in the referenced quarter.",
             "notable_quotes": json.dumps([
                 {"speaker": "Dylan Field", "quote": "Design is the new code."},
                 {"speaker": "Dylan Field", "quote": QUOTE_48 + " And the business basically accelerated."}])},
            {"id": 598, "podcast_episode_id": 587, "title": "Flying Tesla Car | #303",
             "notable_quotes": [{"speaker": "Peter Diamandis",
                                 "quote": "fell from $2.36 in July to 30% in September, 84% drop."}]},
        ],
        "episodes": [
            {"id": 591, "podcast_name": "All-In", "episode_title": "Dylan Field: Is AI Replacing Designers?",
             "key_takeaways": ["Field said Anthropic's \"cloud design\" announcement did not materially hurt "
                               "Figma's business and referenced 48% year-over-year growth in the quarter."]},
            {"id": 587, "podcast_name": "Moonshots", "episode_title": "Flying Tesla Car | #303",
             "key_takeaways": ["Peter Diamandis said Tesla unveiled a flying Roadster in Wakeo, Texas.",
                               "Dr. Don Musalam said 45% of dementia is preventable.",
                               "Don Musalam spoke too."]},
        ],
        "deepDives": {"601": {"insight_id": 601, "podcast_episode_id": 590, "insight_title": OLD_601,
                              "episode_evidence": "Jean Denigrez: What if open AI is not the best?"}},
        "overton": [
            {"id": 270, "term": "Taste", "last_mentioned_episode_id": 590,
             "last_mentioned_episode_title": OLD_601, "last_mentioned_speaker": "Jean Denigrez"},
            {"id": 999, "term": "Other", "last_mentioned_episode_id": 581,
             "last_mentioned_episode_title": OLD_601},
            {"id": 114, "term": "AI Agents", "last_mentioned_speaker": "Nusha Ansari, Salim Ismail, Dr. Don Musalam",
             "description": "Garman described agents as changing cloud design because they need fast APIs."},
        ],
        "pundits": [
            {"name": "Jean Denigrez", "last_podcast_name": "The a16z Show", "last_episode_date": "2026-10-19",
             "last_episode_title": OLD_601,
             "last_proof_cite": "The a16z Show \u2022 2026-10-19 \u2022 " + OLD_601},
            {"name": "Someone", "last_podcast_name": "The a16z Show", "last_episode_date": "2026-10-15",
             "last_episode_title": OLD_601,
             "last_proof_cite": "The a16z Show \u2022 2026-10-15 \u2022 " + OLD_601},
            {"name": "Dr. Don Musalam", "last_proof_snippet": "Last night, in Wakeo, Texas, Tesla unveiled"},
        ],
    }


class OverridesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = export_data._apply_summary_overrides(copy.deepcopy(_fixture()))

    def test_601_title_scoped_by_id(self):
        o = self.out
        self.assertEqual(o["insights"][0]["title"], NEW_601)
        self.assertEqual(o["deepDives"]["601"]["insight_title"], NEW_601)
        self.assertEqual(o["overton"][0]["last_mentioned_episode_title"], NEW_601)
        self.assertEqual(o["pundits"][0]["last_episode_title"], NEW_601)
        self.assertEqual(o["pundits"][0]["last_proof_cite"], "The a16z Show \u2022 2026-10-19 \u2022 " + NEW_601)
        # Same text on another episode (or another date) is NOT retitled.
        self.assertEqual(o["insights"][1]["title"], OLD_601)
        self.assertEqual(o["overton"][1]["last_mentioned_episode_title"], OLD_601)
        self.assertEqual(o["pundits"][1]["last_episode_title"], OLD_601)

    def test_601_quotes_scoped_to_card(self):
        q = self.out["insights"][0]["notable_quotes"]
        self.assertIn("What if OpenAI is", q[0]["quote"])
        self.assertIn("created on Town", q[1]["quote"])
        self.assertEqual(self.out["insights"][1]["summary"], "open AI created on time")
        self.assertIn("What if OpenAI is", self.out["deepDives"]["601"]["episode_evidence"])

    def test_jean_denis_greze_everywhere(self):
        s = list(_strings(self.out))
        self.assertFalse([x for x in s if "Denigrez" in x])
        self.assertEqual(self.out["overton"][0]["last_mentioned_speaker"], "Jean-Denis Greze")
        self.assertEqual(self.out["insights"][0]["notable_quotes"][0]["speaker"], "Jean-Denis Greze")

    def test_602_claude_design_and_interviewer(self):
        card = self.out["insights"][2]
        self.assertIn("Anthropic\u2019s \"Claude Design\" announcement", card["summary"])
        self.assertIn("did not meaningfully suffer, and the interviewer noted the company grew 48%", card["summary"])
        quotes = json.loads(card["notable_quotes"])
        self.assertEqual([q["quote"] for q in quotes], ["Design is the new code."])
        tk = self.out["episodes"][0]["key_takeaways"][0]
        self.assertIn("\"Claude Design\"", tk)
        self.assertIn("Figma's business, and the interviewer cited 48% year-over-year growth", tk)

    def test_overton_114_garman_cloud_point_untouched(self):
        self.assertIn("changing cloud design because", self.out["overton"][2]["description"])

    def test_598_mussallem_waco_and_38_cents(self):
        tks = self.out["episodes"][1]["key_takeaways"]
        self.assertIn("Waco, Texas", tks[0])
        self.assertTrue(tks[1].startswith("Dr. Dawn Mussallem said"))
        self.assertTrue(tks[2].startswith("Dawn Mussallem spoke"))
        self.assertEqual(self.out["overton"][2]["last_mentioned_speaker"],
                         "Nusha Ansari, Salim Ismail, Dr. Dawn Mussallem")
        self.assertEqual(self.out["pundits"][2]["name"], "Dr. Dawn Mussallem")
        self.assertIn("in Waco, Texas", self.out["pundits"][2]["last_proof_snippet"])
        self.assertIn("$2.36 in July to 38 cents in September", self.out["insights"][3]["notable_quotes"][0]["quote"])

    def test_idempotent(self):
        again = export_data._apply_summary_overrides(copy.deepcopy(self.out))
        self.assertEqual(again, self.out)


class SiteDataTests(unittest.TestCase):
    OLD = [OLD_601, "Denigrez", "Musalam", "Wakeo", "created on time", "30% in September", QUOTE_48[:40],
           "What if open AI", "suffer and the company grew 48%", "business and referenced 48%"]

    @classmethod
    def setUpClass(cls):
        cls.files = {"data.js": parse_data_js((SITE / "data.js").read_text(encoding="utf-8"))}
        for f in ("archive.json", "pundits.json", "podcast_guests.json", "podcast_summaries.json"):
            cls.files[f] = json.loads((SITE / f).read_text(encoding="utf-8"))
        d = cls.files["data.js"]
        # suggestedTerms are on hold (G asked us not to touch the ranking); not part of this fix.
        cls.public = {k: v for k, v in d.items() if k != "suggestedTerms"}

    def test_no_old_strings(self):
        for name, data in list(self.files.items()) + [("data.js(public)", self.public)]:
            if name == "data.js":
                continue
            for s in _strings(data):
                for old in self.OLD:
                    self.assertNotIn(old, s, f"{old!r} still in {name}")
                if "cloud design" in s:
                    self.assertIn("Garman", s, f"'cloud design' outside overton 114 in {name}")

    def test_card_titles(self):
        d = self.files["data.js"]
        titles = {i["id"]: i["title"] for sec in ("archive", "mainContent") for i in d[sec]["insights"]}
        self.assertEqual(titles[601], NEW_601)
        if 591 in titles:
            self.assertEqual(titles[591], TITLE_591)
        self.assertEqual(d["deepDives"]["601"]["insight_title"], NEW_601)
        taste = [o for o in d["mainContent"]["overton"] if o.get("term") == "Taste"][0]
        self.assertEqual(taste["last_mentioned_episode_title"], NEW_601)

    def test_602_quote_dropped(self):
        d = self.files["data.js"]
        for sec in ("archive", "mainContent"):
            for i in d[sec]["insights"]:
                if i["id"] == 602:
                    self.assertFalse([q for q in i["notable_quotes"] if "quarterly report" in q["quote"]])

    def test_new_strings_present(self):
        blob = "\n".join(_strings(self.files))
        for new in (NEW_601, "Jean-Denis Greze", "Dr. Dawn Mussallem", "Waco, Texas", "created on Town",
                    "38 cents in September", "Claude Design", "What if OpenAI",
                    "the interviewer noted the company grew 48%", "the interviewer cited 48%"):
            self.assertIn(new, blob)


if __name__ == "__main__":
    unittest.main()
