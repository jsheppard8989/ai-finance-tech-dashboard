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
