"""Nov 17 2026 (G): card 699 / ep 688 wording swap.

One global_replacements pair covers four copies of the same sentence:
card 699 key_takeaway (G referred to this as the card summary; the long
summary field does not contain the sentence), ep 688 investment_thesis,
and last_main_idea for pundits 674 (Andreas Blattmann) and 675 (Dustin
Podell).

Stored DB text and the current live export use the same string (straight
quotes, same spacing). Tests cover both forms so a later drift is caught.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

OLD = "Black Forest Labs is betting that one multimodal model can extend"
NEW = "Black Forest Labs believes one multimodal model can extend"
REST = (
    " from images to video, action, and robotics, with controllability "
    "and data quality as the key bottlenecks."
)
STORED = OLD + REST
LIVE = STORED  # confirmed against dashboard.db and the Nov 16 live export
FIXED = NEW + REST

TITLE = (
    "Building Visual Intelligence — Andreas Blattmann & Dustin Podell, "
    "Black Forest Labs"
)

# Long card/episode summary does not contain the sentence and must stay put.
SUMMARY = (
    "Andreas Blattmann and Dustin Podell frame Black Forest Labs as much "
    "more than an image model shop."
)


def _card(text):
    return {
        "id": 699,
        "podcast_episode_id": 688,
        "title": TITLE,
        "summary": SUMMARY,
        "key_takeaway": text,
    }


def _episode(text):
    return {
        "id": 688,
        "episode_title": TITLE,
        "summary": SUMMARY,
        "investment_thesis": text,
    }


def _pundit(pid, name, text):
    return {
        "id": pid,
        "slug": name.lower().replace(" ", "-"),
        "mention_score": 1,
        "name": name,
        "last_main_idea": text,
    }


def _four(text):
    return [
        _card(text),
        _episode(text),
        _pundit(674, "Andreas Blattmann", text),
        _pundit(675, "Dustin Podell", text),
    ]


def _assert_fixed(rows):
    card, ep, p674, p675 = rows
    assert card["key_takeaway"] == FIXED
    assert ep["investment_thesis"] == FIXED
    assert p674["last_main_idea"] == FIXED
    assert p675["last_main_idea"] == FIXED
    blob = " ".join(
        [
            card["key_takeaway"],
            ep["investment_thesis"],
            p674["last_main_idea"],
            p675["last_main_idea"],
        ]
    )
    assert "is betting" not in blob
    assert OLD not in blob
    assert NEW in blob
    # Long summary and title are unchanged.
    assert card["summary"] == SUMMARY
    assert ep["summary"] == SUMMARY
    assert card["title"] == TITLE
    assert p674["name"] == "Andreas Blattmann"
    assert p675["name"] == "Dustin Podell"


def test_stored_form_four_copies():
    rows = _four(STORED)
    export_data._apply_summary_overrides(rows)
    _assert_fixed(rows)


def test_live_form_four_copies():
    rows = _four(LIVE)
    export_data._apply_summary_overrides(rows)
    _assert_fixed(rows)
