"""Tests for pipeline/summary_overrides.json handling in export_data.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE = "Martin Shkreli: Big Pharma's Blind Spot, Betting Against Quantum & What Prison Taught Him"


def test_takeaways_list_and_string_are_overridden():
    rec = {
        "episode_title": TITLE,
        "summary": "x",
        "key_takeaways": ["saying MATMO-style systems could outperform GPUs and that H100-class Nvidia chips"],
        "key_takeaway": "MATMO-style systems",
    }
    export_data._apply_summary_overrides({"items": [rec]})
    assert rec["key_takeaways"][0] == "saying matrix-multiplication systems could outperform GPUs and that H100-class Nvidia chips"
    assert rec["key_takeaway"] == "matrix-multiplication systems"


def test_takeaways_repr_string_is_overridden():
    rec = {"title": TITLE, "key_takeaways": "['MATMO-style systems and H100-class']"}
    export_data._apply_summary_overrides([rec])
    assert rec["key_takeaways"] == "['matrix-multiplication systems and H100-class']"


def test_other_episodes_untouched():
    rec = {"title": "Other", "key_takeaways": ["MATMO-style systems"]}
    export_data._apply_summary_overrides([rec])
    assert rec["key_takeaways"] == ["MATMO-style systems"]


def test_term_override():
    terms = [{"id": 888, "term": "MATMO", "definition": "old"}, {"term": "Other", "definition": "keep"}]
    export_data._apply_term_overrides(terms)
    assert terms[0]["term"] == "Photonic matrix-multiplication cores"
    assert "MATMO" not in json.dumps(terms)
    assert terms[1] == {"term": "Other", "definition": "keep"}


def test_site_data_has_no_matmo():
    data_dir = Path(__file__).parent.parent / "site" / "data"
    for name in ("data.js", "podcast_summaries.json", "archive.json"):
        assert "MATMO" not in (data_dir / name).read_text(encoding="utf-8"), name


ALLIN = "Is Claude Conscious? Pope Rejects, Model Welfare Movement, OpenAI's Math Backlash, France Riots"
BOSTROM = "Nick Bostrom: How Should We Navigate Superintelligence?"


def test_whole_card_quotes_speakers_and_tickers():
    rec = {
        "id": 579, "title": ALLIN,
        "summary": "Jason Kaltenson says GroqBot",
        "notable_quotes": [{"speaker": "Jason Kaltenson", "quote": "Andthropic has been lobbying"}],
        "tickers_mentioned": "[\"GROQ\", \"NVDA\"]",
    }
    export_data._apply_summary_overrides([rec])
    assert rec["summary"] == "Jason Calacanis says Grok Bot"
    assert rec["notable_quotes"] == [{"speaker": "Jason Calacanis", "quote": "Anthropic has been lobbying"}]
    assert json.loads(rec["tickers_mentioned"]) == ["NVDA"]
    assert rec["title"] == ALLIN
    rec2 = {"title": ALLIN, "tickers_mentioned": ["GROQ"]}
    export_data._apply_summary_overrides([rec2])
    assert rec2["tickers_mentioned"] == []


def test_deep_dive_matched_by_insight_title():
    dd = {"581": {"insight_title": BOSTROM,
                  "investment_thesis": "rather than in simple bets on either unrestricted scaling or blanket moratoria",
                  "episode_evidence": "our life expectancy would maybe be 12,400, 1400 years or so.",
                  "falsification_tracks": ["x"]}}
    export_data._apply_summary_overrides(dd)
    assert "simple calls on" in dd["581"]["investment_thesis"]
    assert dd["581"]["episode_evidence"] == "our life expectancy would maybe be 1,400 years or so."


def test_global_replacements_cover_pundits_and_overton():
    pundits = [{"name": "Charles Le Manides", "last_main_idea": "Le Manides thinks", "last_episode_title": "keep"}]
    overton = {"overton": [{"last_mentioned_speaker": "Davile Agida, Owen He"}], "speakers": ["Jason Kaltenson"]}
    export_data._apply_summary_overrides(pundits)
    export_data._apply_summary_overrides(overton)
    assert pundits[0]["name"] == "Charles Lemonides" and pundits[0]["last_main_idea"] == "Lemonides thinks"
    assert overton["overton"][0]["last_mentioned_speaker"] == "Dhaval Adjodah, Owen He"
    assert overton["speakers"] == ["Jason Calacanis"]


def test_guest_overrides_stamp_names_and_block_title_fragment():
    mc = {"insights": [{"id": 580, "guest_name": "What Makes a Great Entrepreneur?"}, {"id": 584, "guest_name": None}]}
    guests = [{"name": "What Makes a Great Entrepreneur?"}, {"name": "Pat Gelsinger"}]
    mc, guests = export_data._apply_guest_export_overrides(mc, guests)
    assert [i["guest_name"] for i in mc["insights"]] == ["Ben Horowitz", "Charles Lemonides"]
    assert guests == [{"name": "Pat Gelsinger"}]


def test_site_data_has_no_known_bad_strings():
    data_dir = Path(__file__).parent.parent / "site" / "data"
    bad = ["Charles Le Manides", "Jason Kaltenson", "Andthropic", "GroqBot", "Davile Agida",
           "wifio moment", "11labs", "single macro bet", "betting that cheaper compute", "simple bets on",
           "polling at 43%", "paid-for results", "12,400"]
    for name in ("data.js", "podcast_summaries.json", "archive.json", "pundits.json", "podcast_guests.json"):
        text = (data_dir / name).read_text(encoding="utf-8")
        for s in bad:
            assert s not in text, (name, s)
