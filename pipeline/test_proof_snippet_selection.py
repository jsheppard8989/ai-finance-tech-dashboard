"""Oct 25 2026 (sweep item 11 follow-up): pundit proof snippets end on a sentence boundary and
skip leading ad/intro text, without overriding the item 11 pundit_overrides. Temp files only;
no database is opened."""
import json
from pathlib import Path

import db_manager as dm
import export_data

ROOT = Path(__file__).resolve().parent.parent
BODY = ("Rates are going to stay higher for longer than the market thinks. "
        "That is a real problem for regional banks! ")


def _t(tmp_path, text, name="show_20261020_abc.txt"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_skips_sponsor_and_intro_and_ends_on_sentence(tmp_path):
    txt = ("This episode is brought to you by Acme Cloud. Welcome back to the show. "
           "I'm joined today by Jane Doe. " + BODY + "And this last one runs on and on " + "x" * 300)
    s = dm._transcript_proof_snippet(_t(tmp_path, txt))
    assert s == BODY.strip()
    assert len(s) <= 240 and s[-1] in ".?!"


def test_no_sentence_boundary_gives_empty_not_a_cut(tmp_path):
    assert dm._transcript_proof_snippet(_t(tmp_path, "word " * 200)) == ""
    assert dm._transcript_proof_snippet(str(tmp_path / "missing.txt")) == ""
    assert dm._transcript_proof_snippet(None) == ""


def test_macrovoices_intro_skipped(tmp_path):
    txt = "This is MacroVoices, the free weekly financial podcast. " + BODY
    assert dm._transcript_proof_snippet(_t(tmp_path, txt)) == BODY.strip()


def test_takeaway_fallback_ends_on_boundary(monkeypatch):
    monkeypatch.setattr(export_data, "_load_override_rules", lambda: {})
    take = "Power is the binding constraint for data centers. " + "Grid queues run years long and " * 20
    s = dm._select_proof_snippet(1, None, take)
    assert s == "Power is the binding constraint for data centers."


def test_new_snippet_used_when_no_override(tmp_path, monkeypatch):
    monkeypatch.setattr(export_data, "_load_override_rules", lambda: {})
    txt = "Welcome to the show. " + BODY + "y" * 300
    assert dm._select_proof_snippet(7, _t(tmp_path, txt), None) == BODY.strip()


def test_item11_override_still_wins(tmp_path, monkeypatch):
    txt = "Welcome to the show. " + BODY + "y" * 300
    legacy = " ".join(txt.split())[:240].strip()
    rules = {"pundit_overrides": [{"id": 7, "replacements": [[legacy, "Hand-fixed sentence."]]}]}
    monkeypatch.setattr(export_data, "_load_override_rules", lambda: rules)
    snip = dm._select_proof_snippet(7, _t(tmp_path, txt), None)
    assert snip == legacy  # kept so the exact-text rule matches on export
    rec = [{"id": 7, "slug": "x", "mention_score": 1, "last_proof_snippet": snip}]
    export_data._apply_summary_overrides(rec)
    assert rec[0]["last_proof_snippet"] == "Hand-fixed sentence."
    # a different pundit is unaffected by that rule
    assert dm._select_proof_snippet(8, _t(tmp_path, txt), None) == BODY.strip()


def test_every_real_item11_rule_is_honoured():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["pundit_overrides"]
    item11 = [r for r in rules if "item 11:" in r.get("_note", "")]
    assert len(item11) == 263  # Oct 26 2026: #333/#418/#226 moved to id-keyed unset rules; Oct 27: #538 too
    for r in item11:
        (old, _new), = r["replacements"]
        assert dm._overridden_legacy(r["id"], old), r["id"]


def test_override_matched_after_global_swaps():
    # #466's rule text is post-round-2 (global rule drops the "Sam Elan" sentence first)
    raw = ("Dario Amodei, CEO of Anthropic, published a 3,800-word essay titled We Must Pace the Frontier. "
           "Three hours later, Sam Elan said, you're right. Monday, President Trump called it a hoax and "
           "China called it a cold war trick. Nothing less than a")
    assert dm._overridden_legacy(466, raw)
    assert not dm._overridden_legacy(466, "A brand new episode quote about chips.")
