"""Oct 27 2026 follow-up 2 (G, sweep_1027 leftovers): id-keyed cuts of the ep-614 takeaway that
re-quotes 'abandon the lousy places fast' (new 'drop_takeaways'), Jack Farley's 'combined lab AR'
line in deepDive 622 evidence, and the 'fewer thinking tokens' line in deepDive 623 evidence."""
import copy, json
import export_data

TK = ('Ian Quigley said stronger models "abandon the lousy places fast," suggesting capability shows up '
      'as faster rejection of unproductive search neighborhoods.')
L622 = ("Jack Farley: If you're relying on the combined lab AR to be $500 billion, and that's where you're "
        "underwriting your kind of assumptions of what gets handled back into infrastructure. If it ends up "
        "being 300, then that's a disaster.")
L623 = "James Sun: One is it is a little bit faster on average because it uses fewer thinking tokens to do the same task."


def _payload():
    return {
        "summaries": [
            {"id": 614, "podcast_name": "Latent Space", "episode_title": "⚡ An Eval for AI Scientists",
             "key_takeaways": ["Keep one.", TK, "Keep two."]},
            {"id": 998, "podcast_name": "Other", "episode_title": "Other", "key_takeaways": [TK]},
        ],
        "deepDives": {
            "622": {"id": 622, "insight_id": 622, "podcast_episode_id": 611, "insight_title": "x",
                    "episode_evidence": "Jack Farley: Before.\n" + L622 + "\nJack Farley: After."},
            "623": {"id": 623, "insight_id": 623, "podcast_episode_id": 612, "insight_title": "y",
                    "episode_evidence": L623 + "\nJames Sun: If you look at the system card for it."},
            "999": {"id": 999, "insight_id": 999, "podcast_episode_id": 998, "insight_title": "z",
                    "episode_evidence": "A.\n" + L622 + "\n" + L623 + "\nB."},
        },
    }


def test_leftovers_cut_by_id_and_idempotent():
    data = _payload()
    export_data._apply_summary_overrides(data)
    assert data["summaries"][0]["key_takeaways"] == ["Keep one.", "Keep two."]
    assert data["deepDives"]["622"]["episode_evidence"] == "Jack Farley: Before.\nJack Farley: After."
    assert data["deepDives"]["623"]["episode_evidence"] == "James Sun: If you look at the system card for it."
    # scoped: other episodes keep the same text
    assert data["summaries"][1]["key_takeaways"] == [TK]
    assert data["deepDives"]["999"] == _payload()["deepDives"]["999"]
    once = copy.deepcopy(data)
    export_data._apply_summary_overrides(data)
    assert data == once


def test_drop_takeaways_handles_json_string():
    data = {"summaries": [{"id": 614, "podcast_name": "Latent Space", "episode_title": "⚡ An Eval",
                           "key_takeaways": json.dumps(["Keep.", TK])}]}
    export_data._apply_summary_overrides(data)
    assert json.loads(data["summaries"][0]["key_takeaways"]) == ["Keep."]
