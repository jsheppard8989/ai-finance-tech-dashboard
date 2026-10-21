"""Oct 21 2026: G(ai)ndolf fixes for cards 603/605 re-apply on export (from pre-fix archive)."""
import json, subprocess
from pathlib import Path
import export_data

ROOT = Path(__file__).resolve().parent.parent


def test_re_export_reapplies_603_605():
    old = subprocess.run(["git", "show", "2f2f8208930df420984fed129c265c48184bfb64:site/data/archive.json"],
                         cwd=ROOT, capture_output=True, text=True)
    if old.returncode != 0:
        import pytest; pytest.skip("pre-fix archive not available")
    out = export_data._apply_summary_overrides(json.loads(old.stdout))
    out = out if out is not None else json.loads(old.stdout)
    recs = {r["id"]: r for r in (out["insights"] if isinstance(out, dict) else out) if isinstance(r, dict)}
    c603, c605 = json.dumps(recs[603]), recs[605]
    assert "GPT-6 Luna" in c603 and "GPT-5.6 Sol" in c603 and "Sol Sol" not in c603
    assert "GP-6" not in c603 and "Advent Health" not in c603 and "HealthBench Professional" in c603
    assert c605["sentiment"] == "neutral"
    assert "unssecured" not in json.dumps(c605) and "RAMP adoption" not in json.dumps(c605)
