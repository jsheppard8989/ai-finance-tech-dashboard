"""Nov 5 2026 (G, a16z insight 656): ASR 'David Paulen' -> David Pawlan; count
'more than 147 assistants' -> 'more than 140 AI assistants'. Durable via
global_name_replacements + global_replacements (PR #493 pattern)."""
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent


def _site():
    return publish_guard.parse_data_js((ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8"))


def test_site_data_paulsen_gone_pawlan_present():
    blob = (ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8")
    assert "David Paulen" not in blob
    assert "more than 147 assistants" not in blob
    assert "david-paulen" not in blob
    assert blob.count("David Pawlan") >= 15
    assert "more than 140 AI assistants" in blob
    # Quoted source count phrasing preserved (not the summary wrong-count phrase)
    assert "over 147 different assistants" in blob


def test_insight_656_and_pundit_614():
    site = _site()
    ins = next(i for i in site["mainContent"]["insights"] if i["id"] == 656)
    assert "David Pawlan" in ins["summary"]
    assert "more than 140 AI assistants" in ins["summary"]
    assert "David Paulen" not in json.dumps(ins)
    assert all(q["speaker"] != "David Paulen" for q in ins.get("notable_quotes", []))
    assert any(q["speaker"] == "David Pawlan" for q in ins.get("notable_quotes", []))
    pundit = next(p for p in site["pundits"] if p["id"] == 614)
    assert pundit["name"] == "David Pawlan" and pundit["slug"] == "david-pawlan"


def test_rules_idempotent_on_fresh_record():
    rec = {
        "id": 656,
        "summary": "David Paulen says trust is the main fear in his analysis of more than 147 assistants.",
        "notable_quotes": [{"speaker": "David Paulen", "quote": "From over 147 different assistants that have come across my plates so far."}],
    }
    data = {
        "mainContent": {"insights": [rec]},
        "pundits": [{"id": 614, "name": "David Paulen", "slug": "david-paulen", "mention_score": 1, "bio": "x"}],
    }
    export_data._apply_summary_overrides(data)
    once = json.dumps(data)
    export_data._apply_summary_overrides(data)
    assert json.dumps(data) == once
    assert "David Paulen" not in once
    assert "more than 147 assistants" not in once
    assert "David Pawlan" in once
    assert "more than 140 AI assistants" in once
    # quote body count phrasing untouched
    assert "over 147 different assistants" in once
    assert data["pundits"][0]["name"] == "David Pawlan"
    assert data["pundits"][0]["slug"] == "david-pawlan"
