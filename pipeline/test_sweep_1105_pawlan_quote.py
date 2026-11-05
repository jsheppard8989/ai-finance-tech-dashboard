"""Nov 5 2026 (G, a16z insight 656 quote): ASR garble in Pawlan direct quote —
'plates'/'main year' -> 'plate'/'main fear'; keep spoken 147 in the quote."""
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent

OLD = (
    "From over 147 different assistants that have come across my plates so far, "
    "the number one fear that people talk about 22% of the messages are talking about trust as the main year."
)
NEW = (
    "From over 147 different assistants that have come across my plate so far, "
    "the number one fear that people talk about, 22% of the messages are talking about trust as the main fear."
)


def test_site_data_quote_corrected():
    blob = (ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8")
    assert blob.count(NEW) == 3
    assert OLD not in blob
    assert "main year" not in blob
    assert "plates so far" not in blob
    assert "my plate so far" in blob
    # summary marketing paraphrase from #758 stays
    assert "more than 140 AI assistants" in blob
    # spoken 147 retained in the direct quote
    assert "over 147 different assistants" in blob


def test_rule_idempotent_and_keeps_147():
    data = {
        "mainContent": {
            "insights": [{
                "id": 656,
                "summary": "David Pawlan says trust is the main fear in his analysis of more than 140 AI assistants.",
                "notable_quotes": [{"speaker": "David Pawlan", "quote": OLD}],
            }]
        },
        "deepDives": {
            "656": {"episode_evidence": f"David Pawlan: {OLD}\nJosh Elman: hi"}
        },
    }
    export_data._apply_summary_overrides(data)
    once = json.dumps(data)
    export_data._apply_summary_overrides(data)
    assert json.dumps(data) == once
    assert NEW in once and OLD not in once and "main year" not in once
    assert "more than 140 AI assistants" in once
    assert "over 147 different assistants" in once
