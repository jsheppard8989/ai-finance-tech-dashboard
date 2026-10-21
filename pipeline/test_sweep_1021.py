"""Oct 21 2026 G(ai)ndolf live-site sweep: 6 fixes re-apply on export from pre-fix files."""
import json, re, subprocess
from pathlib import Path
import pytest
import export_data

ROOT = Path(__file__).resolve().parent.parent
PRE = "351217cd5566822a88019bfe12f63c95bd9989db"
OLD = ["Amadeh", "Anthropic's'", "ace-upplied", "SpaceX, and Rol.", "RAMP data",
       "declaration of anthropic", "actions against anthropic"]


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


@pytest.mark.parametrize("path", ["site/data/archive.json", "site/data/podcast_summaries.json",
                                  "site/data/pundits.json"])
def test_reexport_reapplies_sweep(path):
    obj = _old(path)
    before = json.dumps(obj, ensure_ascii=False)
    out = export_data._apply_summary_overrides(obj)
    text = json.dumps(out if out is not None else obj, ensure_ascii=False)
    hits = [s for s in OLD if s in before]
    assert hits, "fixture should contain at least one old string"
    for s in OLD:
        assert s not in text, f"{s!r} survived re-export of {path}"
    if "Rol." in before:
        assert "Anthropic, OpenAI and SpaceX." in text
    if "Amadeh" in before:
        assert "Amodei" in text


ROSENBERG_BIO = ("Founder of Rosenberg Research and author of Bear in the Bullring (Sutherland House), "
                 "published October 6, 2026. He also discussed his ROSY ETF, launched on the TSX on "
                 "September 10, 2026.")


def test_reexport_pins_pundit_495_bio():
    obj = _old("site/data/pundits.json")
    out = export_data._apply_summary_overrides(obj)
    out = out if out is not None else obj
    lst = out if isinstance(out, list) else out.get("pundits", [])
    rec = [p for p in lst if p.get("id") == 495][0]
    assert rec["bio"] == ROSENBERG_BIO
    assert "forthcoming" not in json.dumps(rec) and "Rosie ETF" not in json.dumps(rec)
