"""Oct 30 2026: G-approved pundit-row text fixes (pundit_overrides, exact swaps, idempotent)."""
import copy

from export_data import _apply_summary_overrides

FIX = {
    600: ("last_proof_snippet", "On average, a Woop member wears Woop 23. 6 hours a day", "On average, a [WHOOP] member wears [WHOOP] 23.6 hours a day"),
    596: ("last_main_idea", "Defense-led capex is de-risking new U.S. industrial capacity.", "Defense spending is making new U.S. factories less risky to build."),
    597: ("last_main_idea", "Defense-led capex is de-risking new U.S. industrial capacity.", "Defense spending is making new U.S. factories less risky to build."),
    591: ("last_main_idea", "is enough to support the capex cycle.", "is enough to keep the data center building going."),
    78: ("last_proof_snippet", "We don't need to compete with anthropic and open AI on models right now.", "We don't need to compete with [Anthropic] and [OpenAI] on models right now."),
    424: ("last_proof_snippet", "compete with anthropic and open AI on models", "compete with [Anthropic] and [OpenAI] on models"),
    176: ("last_proof_snippet", "compete with anthropic and open AI on models", "compete with [Anthropic] and [OpenAI] on models"),
}


def _row(i, **kw):
    r = {"id": i, "name": f"P{i}", "slug": f"p{i}", "mention_score": 1, "bio": None}
    r.update(kw)
    return r


def test_pundit_row_swaps_exact_and_idempotent():
    rows = [_row(i, **{k: old}) for i, (k, old, _) in FIX.items()]
    rows.append(_row(599, last_main_idea="NuBank’s model works.", supporting_takeaway="He says NuBank has scale."))
    rows.append(_row(5, last_proof_snippet="compete with anthropic and open AI on models"))  # other row untouched
    _apply_summary_overrides(rows)
    by = {r["id"]: r for r in rows}
    for i, (k, _, new) in FIX.items():
        assert by[i][k] == new
    assert by[599]["last_main_idea"] == "Nubank’s model works."
    assert by[599]["supporting_takeaway"] == "He says Nubank has scale."
    assert by[5]["last_proof_snippet"] == "compete with anthropic and open AI on models"
    once = copy.deepcopy(rows)
    _apply_summary_overrides(rows)
    assert rows == once

