"""Oct 26 2026: evening export put back 'Garing and Rozencwajg' and 'David Sachs'.

Root cause: one pass of _apply_summary_overrides runs the exact global_replacements
BEFORE the whole-word name swaps, so 'Garing and Rosenswag' (raw DB text) only became
'Garing and Rozencwajg' after the exact fix had already run; and 'David Sachs' sat only in
name_replacements, which deliberately skips raw transcript snippets (last_proof_snippet).
Files written by a single override pass (pundits.json, archive.json, data.js archive and
deep dives) kept the bad text and publish_guard blocked the publish.
"""
import copy
import json

import export_data
from export_data import _apply_summary_overrides, _apply_summary_overrides_to_files

RAW_BIO = ("Adam Rosenswag is a prominent figure in the global energy markets. He is the "
           "co-founder of Garing and Rosenswag, an investment firm.")
RAW_SNIPPET = ("Yeah, five years went by so quickly with us today. David Sachs is back.")
CALACANIS_522 = ("All right, everybody, welcome back to the number one podcast in the world. The all-in "
                 "podcast with me, the core four, be original, quartet, Chumapai Hoppetia, David Sachs, "
                 "Dave Freeberg, I'm Jason Calcantison. We have a doc at How's Everybo")


def _pundit(pid, name, **kw):
    row = {"id": pid, "slug": name.lower().replace(" ", "-"), "name": name, "mention_score": 2}
    row.update(kw)
    return row


def _pundits():
    return [
        _pundit(168, "Adam Rosenswag", bio=RAW_BIO, pundit_profile={
            "cliff_notes": "He co-founded Garing and Rosenswag, an investment firm.",
            "lead_paragraphs": ["He co-founded Garing and Rosenswag, an investment firm."],
            "derived": {"current_role": "Co-founder, Garing and Rosenswag"}}),
        _pundit(81, "Elon Musk", last_proof_snippet=RAW_SNIPPET),
        _pundit(522, "Jason Calacanis", last_proof_snippet=CALACANIS_522),
    ]


def _archive():
    return {"insights": [{"title": "MacroVoices #527 Adam Rozencwajg: What next",
                          "summary": "Interviews with Adam Rosenswag, co-founder of Garing and Rosenswag, and more."}],
            "deep_dives": [{"episode_title": "MacroVoices #527",
                            "overview": "Adam Rosenswag, co-founder of Garing and Rosenswag, who discusses oil."}]}


def _assert_clean(text):
    assert "Garing and Rozencwajg" not in text
    assert "Rosenswag" not in text
    assert "David Sachs" not in text


def test_single_override_pass_fixes_both_names():
    pundits = _pundits()
    _apply_summary_overrides(pundits)
    by_id = {p["id"]: p for p in pundits}
    _assert_clean(json.dumps(pundits))
    assert "Goehring & Rozencwajg" in by_id[168]["bio"]
    assert by_id[168]["pundit_profile"]["derived"]["current_role"] == "Co-founder, Goehring & Rozencwajg"
    # Oct 26 2026 quote fix: Musk's snippet was the All-In host intro, so it is unset (with its cite).
    assert "last_proof_snippet" not in by_id[81] and "last_proof_cite" not in by_id[81]
    # The hand-written cut for Calacanis (written against the raw 'David Sachs' text) still fires.
    assert not by_id[522]["last_proof_snippet"]

    arch = _archive()
    _apply_summary_overrides(arch)
    _assert_clean(json.dumps(arch))
    assert "Goehring & Rozencwajg" in arch["insights"][0]["summary"]
    # title fields untouched
    assert arch["insights"][0]["title"] == "MacroVoices #527 Adam Rozencwajg: What next"


def test_override_pass_is_stable():
    once = _pundits()
    _apply_summary_overrides(once)
    twice = copy.deepcopy(once)
    _apply_summary_overrides(twice)
    assert once == twice


def test_files_written_after_overrides_are_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(export_data, "report_style_gate_misses", lambda *a, **k: None)
    (tmp_path / "pundits.json").write_text(json.dumps(_pundits()), encoding="utf-8")
    (tmp_path / "archive.json").write_text(json.dumps(_archive()), encoding="utf-8")
    _apply_summary_overrides_to_files(tmp_path)
    for name in ("pundits.json", "archive.json"):
        _assert_clean((tmp_path / name).read_text(encoding="utf-8"))
