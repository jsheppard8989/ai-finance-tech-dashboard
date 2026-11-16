"""Nov 15 2026 (G, Jared-approved attribution fixes; decisions.md Nov 15 4:32 PM CT):
All-In ep 680 / insight 690 and Moonshots #311 ep 679 / insight 691. Every line re-verified
against the episode transcript (cos/fixes/g_verify_2026-11-15.md). These tests pin the
override rules on fresh records, so they hold before and after the next export."""
import copy
import json

import export_data

OV = json.loads((export_data.Path(export_data.__file__).parent / "summary_overrides.json").read_text(encoding="utf-8"))
GOV = json.loads((export_data.Path(export_data.__file__).parent / "guest_overrides.json").read_text(encoding="utf-8"))


def _rule(insight_id):
    return next(r for r in OV["summaries"] if r.get("insight_id") == insight_id and r.get("podcast_episode_id"))


def test_all_in_680_rule_fixes_speakers_and_keeps_quotes_verbatim():
    rec = {
        "podcast_episode_id": 680,
        "key_takeaways": [
            "Chamath Palihapitiya said Nvidia’s stock had already been “crushed down 15% in the last week,” x",
            "David Friedberg said, “The bank of Nvidia ran through Jensen and it’s not clear”",
            "David Sacks warned that future legislation could force every AI chip, computer, and data center to have telemetry and a connection back to a central state system.",
        ],
        "notable_quotes": [
            {"speaker": "Chamath Palihapitiya", "quote": "Nvidia reports earnings next Tuesday, and the stock has been crushed down 15% in the last week"},
            {"speaker": "Chamath Palihapitiya", "quote": "Anthropic is building the Microsoft killer and every SaaS company killer by bundling."},
        ],
    }
    before_quotes = [q["quote"] for q in rec["notable_quotes"]]
    r = _rule(690)
    data = {"x": [copy.deepcopy(rec)]}
    orig = export_data._load_override_rules
    export_data._load_override_rules = lambda: {"summaries": [r]}
    try:
        export_data._apply_summary_overrides(data)
    finally:
        export_data._load_override_rules = orig
    out = data["x"][0]
    assert out["key_takeaways"][0].startswith("Jason Calacanis said")
    assert out["key_takeaways"][1].startswith("Chamath Palihapitiya said")
    assert out["key_takeaways"][2].startswith("David Friedberg warned") and "a switch and" in out["key_takeaways"][2]
    assert [q["speaker"] for q in out["notable_quotes"]] == ["Jason Calacanis", "Jason Calacanis"]
    assert [q["quote"] for q in out["notable_quotes"]] == before_quotes


def test_term_rules_gated_to_their_episode():
    rules = [t for t in OV["terms"] if t.get("when", {}).get("last_mentioned_episode_id") in (679, 680)]
    assert len(rules) == 11
    terms = [{"id": 254, "last_mentioned_episode_id": 679, "last_mentioned_speaker": "Demis Hassabis, Paul Christiano, Will Marshall"},
             {"id": 254, "last_mentioned_episode_id": 700, "last_mentioned_speaker": "Someone Else"}]
    export_data._apply_term_overrides(terms, rules)
    assert terms[0]["last_mentioned_speaker"] == "Peter Diamandis, Alex Wissner-Gross"
    assert terms[1]["last_mentioned_speaker"] == "Someone Else"


def test_guest_overrides_blank_title_fragment():
    assert GOV["insight_guest_by_id"].get("690") == ""
    assert "Jensen Ousted as Nvidia CEO" in GOV["blocklist"]


def test_no_bet_wording_and_unapproved_calls_not_applied():
    import re
    for iid in (690, 691):
        r = _rule(iid)
        for _old, new in r["replacements"]:
            assert not re.search(r"\bbets?\b", new, re.I)
        assert "drop_list_items" not in r  # '1 billion unit' falsification track not approved


def test_690_bank_of_nvidia_stored_form_is_chamath():
    """Nov 15 2026 (G, PR #833): the stored Deep Dive evidence reads 'Jason Friedberg: The bank...'.
    The later name fix turns that into David Friedberg, so the 690 rule has to match the stored form.
    Source: All-In ep 680, Friedberg asks at 31:22 ('Chamath, you're pretty close to this'),
    Chamath answers at 32:01 (Mac transcript ALLIN-E297_Ch.txt L430-435)."""
    import export_data
    for label in ("Jason Friedberg", "David Friedberg"):
        rec = {"insight_id": 690, "podcast_episode_id": 680,
               "episode_evidence": f"Jason Calacanis: Nvidia reports earnings next Tuesday.\n"
                                   f"{label}: The bank of Nvidia ran through Jensen and it's not clear what happens now."}
        export_data._apply_summary_overrides(rec)
        export_data._apply_summary_overrides(rec)  # idempotent
        assert ("Chamath Palihapitiya: The bank of Nvidia ran through Jensen and it's not clear what happens now."
                in rec["episode_evidence"]), label
        assert "Friedberg: The bank" not in rec["episode_evidence"]
