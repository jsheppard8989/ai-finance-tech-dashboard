"""Oct 25 2026 sweep (cos/sweep_1025/fixes.md) item 11: cut-off pundit proof snippets re-apply on export.

The rules are exact-text pundit_overrides replacements, so they fix only the cut-off snippet they
were written for: a pundit's next episode brings a new snippet and the old rule simply no-ops."""
import json, re, subprocess
from pathlib import Path
import pytest
import export_data

ROOT = Path(__file__).resolve().parent.parent
PRE = "2684146"  # origin/main before item 11
ENDS = re.compile(r"[.?!][\"”’')]*$")
NOTE = "item 11:"


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


def _rules():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["pundit_overrides"]
    return [r for r in rules if NOTE in r.get("_note", "") and "sweep_1025" in r.get("_note", "")]


def test_export_rerun_has_no_cut_off_snippets():
    pund = _old("site/data/pundits.json")
    before = [p["id"] for p in pund if (p.get("last_proof_snippet") or "").strip()
              and not ENDS.search(p["last_proof_snippet"].strip())]
    assert len(before) > 200
    export_data._apply_summary_overrides(pund)
    after = [p["id"] for p in pund if (p.get("last_proof_snippet") or "").strip()
             and not ENDS.search(p["last_proof_snippet"].strip())]
    assert after == []  # Musk's (#81) garbled host-intro snippet is unset (Oct 26 2026 quote fix)


HOST_INTRO_IDS = {333, 418, 226}  # Oct 26 2026: retired exact-text cuts, now id-keyed unset rules


def test_fixes_are_verbatim_and_match_the_site_files():
    site = {p["id"]: p for p in json.loads((ROOT / "site" / "data" / "pundits.json").read_text())}
    # The Oct 25 exact-text cuts for these three stopped matching once the export re-selected
    # (trimmed) their host-intro snippets; id-keyed unset rules replace them.
    assert not HOST_INTRO_IDS & {r["id"] for r in _rules()}
    for pid in HOST_INTRO_IDS:
        if pid in site:
            assert not site[pid].get("last_proof_snippet") and not site[pid].get("last_proof_cite"), pid
    names = {"Demisis Abbas": "Demis Hassabis",
             "Sergei Bren": "Sergey Brin", "Miramoradi": "Mira Murati"}
    restored = {548, 536, 546}
    for r in _rules():
        (old, new), = r["replacements"]
        if r["id"] in site:
            assert site[r["id"]].get("last_proof_snippet") == new
        if not new or r["id"] in restored:
            continue
        for a, b in names.items():
            new = new.replace(b, a) if a in old else new
        if r["id"] == 466:  # ambiguous sentence ('Sam Elan' = Sam Altman, or "Sam, Elon") dropped verbatim
            assert "Sam" not in new
            old = old.replace("Three hours later, Sam Elan said, you're right. ", "")
        assert new in old, r["id"]  # trims never invent wording
        assert ENDS.search(new)


def test_rules_ignore_a_new_snippet():
    r = _rules()[0]
    row = {"id": r["id"], "name": "x", "slug": "x", "mention_score": 1, "last_proof_snippet": "A new episode quote."}
    hit = dict(row, last_proof_snippet=r["replacements"][0][0])
    export_data._apply_pundit_rules([row, hit], [], [r])
    assert row["last_proof_snippet"] == "A new episode quote."
    assert hit["last_proof_snippet"] == r["replacements"][0][1]
