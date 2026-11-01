"""Oct 31 2026 PREVIEW: R41 rev2 'investors should' strip runs at export from r41_investors_should_rules.json."""
import json
from pathlib import Path
import export_data
from investors_should_strip import apply_investors_should_strip, load_rules

T = " Investors should watch margins."


def test_strips_only_listed_tail_and_is_idempotent():
    d = {"7": {"overview": "Margins rose. Other sentence." + T, "summary": "Investors should hold."}}
    rules = {"7": ["Investors should watch margins."]}
    apply_investors_should_strip(d, rules)
    assert d["7"]["overview"] == "Margins rose. Other sentence."
    assert "Investors should watch margins" not in d["7"]["overview"]
    assert d["7"]["summary"] == "Investors should hold."  # not listed
    snap = json.dumps(d)
    apply_investors_should_strip(d, rules)
    assert json.dumps(d) == snap


def test_skips_card_that_would_blank_or_lose_only_takeaway():
    d = {"7": {"key_takeaways_detailed": ["Investors should watch margins."],
               "ticker_analysis": {"X": {"positioning": "Investors should watch margins."}}}}
    before = json.dumps(d)
    done, skipped = apply_investors_should_strip(d, {"7": ["Investors should watch margins."]})
    assert json.dumps(d) == before and skipped


def test_quotes_untouched():
    q = 'He said "Investors should watch margins." Done.'
    d = {"7": {"overview": q}}
    apply_investors_should_strip(d, {"7": ["Investors should watch margins."]})
    assert d["7"]["overview"] == q


def test_rules_file_shape():
    r = load_rules()
    assert len(r) == 286 and sum(len(v) for v in r.values()) == 393


def test_card_632_has_no_grading_wording():
    rules = json.loads((Path(__file__).parent / "summary_overrides.json").read_text())
    d = {"632": {"id": 632, "insight_id": 632, "podcast_episode_id": 621, "insight_title": "t",
                 "falsification_tracks": [
                     "A; grading source: 10-Q and earnings release.",
                     "B, using the company's 10-Q and earnings release as the grading source.",
                     "C; grading source: company filings or earnings materials."]}}
    export_data._apply_summary_overrides(d)
    s = json.dumps(d)
    assert "grading" not in s.lower()
