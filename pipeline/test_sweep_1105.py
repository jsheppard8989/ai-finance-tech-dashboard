"""Nov 5 2026 daily check (sweep_1105): Deep Dive for insight 132 (All-In, Mar 27 2026)
key_takeaways_detailed[0] garble 'the new agente system' -> 'the new agentic system'."""
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent


def _site():
    return publish_guard.parse_data_js((ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8"))


def test_deep_dive_132_agentic():
    dd = _site()["deepDives"]["132"]
    assert "the new agentic system" in dd["key_takeaways_detailed"][0]
    assert "agente" not in json.dumps(dd)


def test_rule_idempotent_on_fresh_record():
    rec = {"insight_id": 132, "podcast_episode_id": 117,
           "key_takeaways_detailed": ["Claude Code and the new agente system for enterprise"]}
    data = {"deepDives": {"132": rec}}
    export_data._apply_summary_overrides(data)
    once = json.dumps(data)
    export_data._apply_summary_overrides(data)
    assert json.dumps(data) == once and "the new agentic system" in once and "agente" not in once
