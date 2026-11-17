"""Nov 16 2026 (G): export-unblock fixes for the publish_guard dry-run on main
after #833/#834. 'bet' swaps on card 698 (ep 687, Figure AI / Brett Adcock),
both our-voice paraphrases, not quotes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402
from site_text_sanitize import find_style_gate_hits  # noqa: E402

SUMMARY = ("The speaker says Figure uses Hark for voice AI and makes a speculative bet that Hark "
           "could become bigger than Figure within sub-six months")
KT = ("Figure\u2019s bet is that scalable home robotics will come from better hands, larger models, "
      "and massive compute, not from flashy demos or teleoperated tricks.")


def test_698_bet_wording_swapped_everywhere():
    data = {
        "mainContent": {"insights": [{"id": 698, "summary": SUMMARY, "key_takeaway": KT}]},
        "archive": {"insights": [{"id": 698, "summary": SUMMARY, "key_takeaway": KT}]},
        "pundits": [{"name": "Brett Adcock", "last_main_idea": KT}],
    }
    assert find_style_gate_hits(data)
    export_data._apply_summary_overrides(data)
    assert find_style_gate_hits(data) == []
    ins = data["mainContent"]["insights"][0]
    assert "makes a speculative call that Hark could become bigger than Figure" in ins["summary"]
    assert ins["key_takeaway"].startswith("Figure\u2019s view is that scalable home robotics will come")
    assert data["pundits"][0]["last_main_idea"] == ins["key_takeaway"]


def test_698_straight_apostrophe_variant():
    rec = [{"investment_thesis": KT.replace("\u2019", "'")}]
    export_data._apply_summary_overrides(rec)
    assert rec[0]["investment_thesis"].startswith("Figure's view is that")


COWEN = ("You're giving me for anthropic an open AI? And no one had an answer for that question.")


def test_696_cowen_quote_and_ramp_card_scoped():
    card = {"id": 696, "podcast_episode_id": 685,
            "notable_quotes": [{"speaker": "Tyler Cowen", "quote": COWEN}],
            "falsification_tracks": ["By Q1 2027, the RAMP dataset shows token prices falling. Source: RAMP dataset."]}
    export_data._apply_summary_overrides([card])
    assert card["notable_quotes"][0]["quote"] == "You're giving me for Anthropic [and] OpenAI? And no one had an answer for that question."
    assert card["falsification_tracks"][0] == "By Q1 2027, the Ramp dataset shows token prices falling. Source: Ramp dataset."


def test_574_guest_card_outside_card_scope_is_fixed():
    old = ("Periodic\u2019s core claim is that materials discovery will be accelerated most by physically grounded RL, "
           "instrument intelligence, and lineage-rich experimental data\u2014not by simulations or model scale alone.")
    guests = [{"name": "Liam Fedus and Ekin Do\u011fu\u015f \u00c7ubuk", "last_main_idea": old,
               "last_episode_title": "Synthesis Superintelligence: from Semiconductors to Superconductors \u2014 Periodic Labs\u2019 Liam Fedus and Ekin Dogus Cubuk"}]
    export_data._apply_summary_overrides(guests)
    s = guests[0]["last_main_idea"]
    assert "instrument intelligence" not in s
    assert "reinforcement learning built on real lab experiments and instrument data" in s


def test_684_jan_van_eck_name():
    recs = [{"podcast_episode_id": 684, "summary": "Yon Venek says the recent rise in Treasury yields is a bond squeeze.",
             "notable_quotes": [{"speaker": "Yon Venek", "quote": "x"}],
             "episode_evidence": "Yon Venek: I think that tenure interest rates want to",
             "episode_title": "The Bond Squeeze | Jan van Eck on >5% Treasury Yields, Semis, Anthropic, and Gold"}]
    export_data._apply_summary_overrides(recs)
    r = recs[0]
    assert r["summary"].startswith("Jan van Eck says")
    assert r["notable_quotes"][0]["speaker"] == "Jan van Eck"
    assert r["episode_evidence"].startswith("Jan van Eck: ")
