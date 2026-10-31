"""Oct 31 2026 (G, sweep_1031 R5-R40): ASR name fixes, pundit merges/excludes, the R27 bracket-only
fix inside a direct quote, and the 'Kimi Catches Up' title-fragment guest. Robert Caro (R7) and
Doug Bernauer (R18) are intentionally NOT included (weak sources)."""
import copy, json
from pathlib import Path
import export_data

OV = json.loads((Path(__file__).parent / "summary_overrides.json").read_text(encoding="utf-8"))
GOV = json.loads((Path(__file__).parent / "guest_overrides.json").read_text(encoding="utf-8"))
QUOTE = "'I predict that this is going to move SpaceX XAI and cursor to the front of the line,' he said."


def _payload():
    return {"archive": {"insights": [
        {"id": 641, "title": "Interview with J. Madesh", "summary": "J. Madesh says the market is big. Madesh: yes.",
         "notable_quotes": [{"speaker": "J. Madesh", "quote": "We grow."}]},
        {"id": 635, "title": "t", "summary": "Aaron Price and Drew Beglino talk. Price says that in the first half of 2026 "
         "orders rose, while Price highlights risk."},
        {"id": 700, "title": "t", "summary": "The integration of cursor into X.AI and the merger of SpaceX and XAI. " + QUOTE},
    ]}}


def test_names_fixed_titles_untouched_and_idempotent():
    d = _payload()
    export_data._apply_summary_overrides(d)
    a, b, c = d["archive"]["insights"]
    assert a["title"] == "Interview with J. Madesh"  # publisher titles never change
    assert a["summary"] == "Jay Madheswaran says the market is big. Madheswaran: yes."
    assert a["notable_quotes"][0]["speaker"] == "Jay Madheswaran"
    assert a["notable_quotes"][0]["quote"] == "We grow."
    assert b["summary"] == ("Erin Price-Wright and Drew Baglino talk. Price-Wright says that in the first half of 2026 "
                            "orders rose, while Price-Wright highlights risk.")
    assert "integration of Cursor into xAI" in c["summary"] and "merger of SpaceX and xAI" in c["summary"]
    once = copy.deepcopy(d)
    export_data._apply_summary_overrides(d)
    assert d == once


def test_r27_quote_gets_brackets_only():
    d = _payload()
    export_data._apply_summary_overrides(d)
    s = d["archive"]["insights"][2]["summary"]
    assert "'I predict that this is going to move SpaceX [xAI] and [Cursor] to the front of the line,' he said." in s


def test_skipped_names_not_in_rules():
    olds = {o for o, _ in OV["global_name_replacements"] + OV["global_replacements"]}
    assert "Robert Carroll" not in olds and "Doug Burnower" not in olds


def test_pundit_merges_and_excludes():
    merges = {m["keep"]: m["merge"] for m in OV["pundit_merges"]}
    assert merges[247] == [142] and merges[124] == [246] and merges[178] == [356] and merges[78] == [427]
    ex = {e["id"] for e in OV["pundit_excludes"]}
    assert {142, 246, 356, 427, 446, 159} <= ex
    assert 594 not in ex  # Robert Carroll / Caro merge skipped


def test_pundit_bare_surnames():
    d = {"pundits": [{"id": 426, "name": "Ruggle Rugglerum", "bio": "Rugglerum leads.", "slug": "ruggle-rugglerum", "mention_score": 1}]}
    export_data._apply_summary_overrides(d)
    assert d["pundits"][0]["name"] == "Raghu Raghuram" and d["pundits"][0]["bio"] == "Raghuram leads."


def test_kimi_title_fragment_guest_blocked():
    assert "Kimi Catches Up" in GOV["blocklist"]
