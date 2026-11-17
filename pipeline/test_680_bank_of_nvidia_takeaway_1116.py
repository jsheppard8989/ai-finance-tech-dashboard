"""Nov 16 2026 (G): ep 680 (All-In 'Jensen Ousted') key_takeaways[3] credits the
'bank of Nvidia' line to Chamath, matching both the stored DB text ('Jason Friedberg said')
and the post-name-fix live text ('David Friedberg said')."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE = 'Jensen Ousted as Nvidia CEO: "Spy" Scandal, Export Restrictions, Market Impact'
TAIL = ("The bank of Nvidia ran through Jensen and it's not clear what happens now,\u201d "
        "underscoring leadership concentration risk.")
WANT = "Chamath Palihapitiya said, \u201c" + TAIL


def _rec(who):
    return {"id": 680, "podcast_name": "All-In with Chamath, Jason, Sacks & Friedberg",
            "episode_title": TITLE, "key_takeaways": ["x", "y", "z", f"{who} said, \u201c" + TAIL]}


def test_stored_form_jason_friedberg():
    r = _rec("Jason Friedberg")
    export_data._apply_summary_overrides([r])
    assert r["key_takeaways"][3] == WANT


def test_live_form_david_friedberg():
    r = _rec("David Friedberg")
    export_data._apply_summary_overrides([r])
    assert r["key_takeaways"][3] == WANT


def test_insight_card_form():
    r = {"id": 690, "podcast_episode_id": 680, "title": TITLE,
         "key_takeaways": ["Jason Friedberg said, \u201c" + TAIL]}
    export_data._apply_summary_overrides([r])
    assert r["key_takeaways"][0] == WANT
