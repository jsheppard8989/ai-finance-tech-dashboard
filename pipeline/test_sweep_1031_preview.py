"""Oct 31 2026 PREVIEW (sweep_1031 R66 review, card 632/528 extras). Quote-safe, idempotent, term labels kept."""
import copy
import export_data


def _run(d):
    export_data._apply_summary_overrides(d)
    return d


def _p():
    return {"archive": {"insights": [
        {"id": 1, "summary": "Hyperscaler capex investments rose. \"The capex boom is real,\" he said."},
        {"id": 2, "summary": "Every competitive moat analysis changes; a durable moat matters; high-ROIC software."},
    ], "overton": [{"id": 155, "term": "Compute as moat", "description": "Compute as moat is tracked."}]},
        "deepDives": {"632": {"id": 632, "insight_id": 632, "podcast_episode_id": 621, "insight_title": "t",
                              "falsification_tracks": ["MSFT cuts guidance; grading source: 10-Q and earnings release."]},
                      "78": {"id": 78, "insight_id": 78, "podcast_episode_id": 9078, "insight_title": "u",
                             "overview": "Big capex spending and capital expenditures (capex) climb."}}}


def test_phrase_rewrites_and_no_doubling():
    d = _run(_p())
    s0 = d["archive"]["insights"][0]["summary"]
    assert s0.startswith("Hyperscaler capital spending rose.")
    assert '"The capex boom is real,"' in s0  # quote untouched
    s1 = d["archive"]["insights"][1]["summary"]
    assert "Every analysis of lasting competitive edge" in s1 and "a lasting competitive edge matters" in s1
    assert "high-return software" in s1
    assert d["deepDives"]["78"]["overview"] == "Big capital spending and capital spending climb."


def test_term_label_kept_and_632_grading_wording():
    d = _run(_p())
    assert d["archive"]["overton"][0]["term"] == "Compute as moat"
    assert d["deepDives"]["632"]["falsification_tracks"][0] == "MSFT cuts guidance; source: 10-Q and earnings release."


def test_idempotent_and_no_banned_words():
    d = _run(_p())
    again = _run(copy.deepcopy(d))
    assert again == d
    import json, re
    s = json.dumps(d)
    assert not re.search(r"\b(bet|thin)\b", s, re.I)
    for bad in ("capital spending spending", "competitive lasting competitive", "durable lasting"):
        assert bad not in s
