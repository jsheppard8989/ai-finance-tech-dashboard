"""Nov 3 2026 follow-up to #734: no 'grading source' in Deep Dive 632 'what would change our view'
lines, and the guest-list-only rename Tutor Intelligence -> Josh Gruenstein (Tutor Intelligence)."""
import json
import re
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
GUEST = "Josh Gruenstein (Tutor Intelligence)"


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
    names = [g["name"] for g in d["podcastGuests"]]
    assert GUEST in names and "Tutor Intelligence" not in names
    pj = json.loads((ROOT / "site" / "data" / "podcast_guests.json").read_text(encoding="utf-8"))
    assert GUEST in [g["name"] for g in pj]
    # pundit bios untouched
    assert "Co-founder and CEO of Tutor Intelligence." in (ROOT / "site" / "data" / "pundits.json").read_text()


def test_guest_list_rename_mechanism():
    gov = json.loads((ROOT / "pipeline" / "guest_overrides.json").read_text(encoding="utf-8"))
    assert gov["guest_list_renames"] == {"Tutor Intelligence": GUEST}
    assert "Tutor Intelligence" not in gov["fixes"]  # fixes are also site-wide name swaps
    guests = [{"name": "Tutor Intelligence", "last_episode_title": "x | Tutor Intelligence"}]
    mc, out = export_data._apply_guest_export_overrides({"insights": []}, guests)
    assert out[0]["name"] == GUEST and out[0]["last_episode_title"] == "x | Tutor Intelligence"
    export_data._apply_guest_list_renames(out, gov)
    assert out[0]["name"] == GUEST
