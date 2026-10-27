"""Oct 27 2026: G's id-keyed 'bet' wording fixes for episodes 613 (insight 625) and 615 (insight 626)
re-apply on export, stay scoped to those episodes, and are idempotent."""
import copy, json
import export_data
import publish_guard

OLD_625 = ("Supabase is betting that long-running compute plus compatibility-first storage and operator "
           "rewrites will let it serve a future where AI apps drive billions of database launches monthly.")
NEW_625 = ("Supabase is counting on long-running compute plus compatibility-first storage and operator "
           "rewrites to let it serve a future where AI apps drive billions of database launches monthly.")
OLD_626 = ("The episode also surfaces a structural bet: if a school can control the daily schedule, student "
           "agency, and peer context, then AI can become a systems layer that compounds with culture rather "
           "than replacing teachers in place.")
NEW_626 = ("The episode also lays out a structural idea: if a school can control the daily schedule, student "
           "agency, and peer context, then AI can become a systems layer that compounds with culture rather "
           "than replacing teachers in place.")
PRE, POST = "Alpha School is trying something new. ", " Rest of the overview stays."


def _payload():
    return {
        "archive": {"insights": [
            {"id": 625, "podcast_episode_id": 613, "title": "Supabase’s Plan for a Billion AI-Built Apps",
             "key_takeaway": OLD_625},
            {"id": 999, "podcast_episode_id": 998, "title": "Other", "key_takeaway": OLD_625},
        ]},
        "deepDives": {
            "626": {"id": 625, "insight_id": 626, "podcast_episode_id": 615, "insight_title": "x",
                    "overview": PRE + OLD_626 + POST},
            "999": {"id": 998, "insight_id": 999, "podcast_episode_id": 998, "insight_title": "y",
                    "overview": OLD_626},
        },
    }


def test_bet_wording_fixed_by_id_and_idempotent():
    data = _payload()
    export_data._apply_summary_overrides(data)
    assert data["archive"]["insights"][0]["key_takeaway"] == NEW_625
    assert data["deepDives"]["626"]["overview"] == PRE + NEW_626 + POST
    # id-scoped: another episode with the same text is untouched
    assert data["archive"]["insights"][1]["key_takeaway"] == OLD_625
    assert data["deepDives"]["999"]["overview"] == OLD_626
    once = copy.deepcopy(data)
    export_data._apply_summary_overrides(data)
    assert data == once


def test_fixed_cards_pass_style_gate():
    data = _payload()
    export_data._apply_summary_overrides(data)
    fixed = {"a": data["archive"]["insights"][0], "d": data["deepDives"]["626"]}
    assert publish_guard.find_style_gate_hits(fixed) == []
    assert publish_guard.find_style_gate_hits(_payload()["deepDives"]["626"])  # old text is a hit
