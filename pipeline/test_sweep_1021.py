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
