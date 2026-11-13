"""Nov 3 2026 follow-up to #734: no 'grading source' in Deep Dive 632 'what would change our view'
lines, and the guest-list rename for Josh Gruenstein (Tutor Intelligence CEO).

Nov 5 2026: G kept the plain guest-list name "Josh Gruenstein" (no company parenthetical;
consistent with other guest records; the bio / episode title already name Tutor Intelligence).
The dead guest_list_renames entry Tutor Intelligence -> Josh Gruenstein (Tutor Intelligence)
was removed because later exports mint a person-named row (id 109640), so that rename can
never fire. Scope rule unchanged: guest_list_renames must not leak into body text or
name_normalizer (unlike 'fixes').
"""
import json
import re
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
GUEST = "Josh Gruenstein"
GUEST_ID = 109640
GUEST_SLUG = "josh-gruenstein"


def _site():
    return publish_guard.parse_data_js((ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8"))


def test_no_grading_in_any_falsification_track():
    for k, dd in _site()["deepDives"].items():
        for line in dd.get("falsification_tracks") or []:
            assert not re.search(r"\b(grading|graded)\b", line), (k, line)


def test_dd_632_lines_rewritten():
    tracks = " ".join(_site()["deepDives"]["632"]["falsification_tracks"])
    assert "using the company's 10-Q and earnings release." in tracks
    for s in ("; source: 10-Q and earnings release.", "; source: company filings or earnings materials.",
              "; source: Silicon Data term-curve output."):
        assert s in tracks


def test_dd_632_rule_reapplies_on_fresh_export_idempotent():
    dd = {"insight_id": 632, "podcast_episode_id": 621, "falsification_tracks": [
        "or lower, using the company's 10-Q and earnings release as the grading source.",
        "prior guidance; grading source: 10-Q and earnings release."]}
    data = {"deepDives": {"632": dd}}
    export_data._apply_summary_overrides(data)
    once = json.dumps(data)
    assert dd["falsification_tracks"] == ["or lower, using the company's 10-Q and earnings release.",
                                         "prior guidance; source: 10-Q and earnings release."]
    export_data._apply_summary_overrides(data)
    assert json.dumps(data) == once


def test_guest_list_rename_live_and_scoped():
    d = _site()
    guests = d["podcastGuests"]
    names = [g["name"] for g in guests]
    assert GUEST in names
    assert "Tutor Intelligence" not in names
    assert "Josh Gruenstein (Tutor Intelligence)" not in names
    row = next(g for g in guests if g["id"] == GUEST_ID)
    assert row["name"] == GUEST and row["slug"] == GUEST_SLUG
    pj = json.loads((ROOT / "site" / "data" / "podcast_guests.json").read_text(encoding="utf-8"))
    pj_row = next(g for g in pj if g["id"] == GUEST_ID)
    assert pj_row["name"] == GUEST and pj_row["slug"] == GUEST_SLUG
    assert "Josh Gruenstein (Tutor Intelligence)" not in [g["name"] for g in pj]
    # pundit bios untouched (company name stays in bio text; guest_list_renames never rewrote it)
    assert "Co-founder and CEO of Tutor Intelligence." in (ROOT / "site" / "data" / "pundits.json").read_text()


def test_guest_list_rename_mechanism():
    """guest_list_renames is scoped to the guest-list name field only (not body text or
    name_normalizer, unlike 'fixes'). Tutor Intelligence stays unrenamed (person row already
    minted). Nov 12 2026: 'Deep Dive' -> Jamin Ball is the live rename for guest 116896.
    """
    gov = json.loads((ROOT / "pipeline" / "guest_overrides.json").read_text(encoding="utf-8"))
    renames = gov.get("guest_list_renames") or {}
    assert "Tutor Intelligence" not in renames
    assert renames.get("Deep Dive") == "Jamin Ball"
    assert "Tutor Intelligence" not in (gov.get("fixes") or {})
    # Mechanism still scoped: episode title / other fields untouched; only exact name match.
    guests = [{"name": "Tutor Intelligence", "last_episode_title": "x | Tutor Intelligence"}]
    synthetic = {"guest_list_renames": {"Tutor Intelligence": "Josh Gruenstein (Tutor Intelligence)"}}
    out = export_data._apply_guest_list_renames(guests, synthetic)
    assert out[0]["name"] == "Josh Gruenstein (Tutor Intelligence)"
    assert out[0]["last_episode_title"] == "x | Tutor Intelligence"
    # Live overrides leave a person-named row alone (no parenthetical rewrite).
    live = [{"name": GUEST, "id": GUEST_ID, "slug": GUEST_SLUG,
             "last_episode_title": "The Robots Already Working in American Factories | Tutor Intelligence"}]
    export_data._apply_guest_list_renames(live, gov)
    assert live[0]["name"] == GUEST
