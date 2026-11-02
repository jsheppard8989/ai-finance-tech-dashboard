"""Nov 2 2026 publish-guard block: 'capex intensity' back in Deep Dive 618 (All-In 'AI Cyber Panic')
META rationale after re-export, and 'venture-style bet' on the Bending Spoons card (episode 637).
Both are fixed via export-proof rules in summary_overrides.json."""
import json
from pathlib import Path

import export_data
import site_text_sanitize

ROOT = Path(__file__).resolve().parent.parent

BET = ("He frames this as a compounding model rather than a classic venture-style bet on repeated "
       "step-change invention, arguing that most companies")
CAPEX = ("The episode cites the stock being down after earnings, reinforcing skepticism around capex "
         "intensity versus near-term payoff.")


def _data():
    return {
        "archive": {"insights": [{"id": 648, "podcast_episode_id": 637,
                                  "title": "How Bending Spoons Built a $20 Billion Compounder | Luca Ferrari",
                                  "summary": BET}]},
        "mainContent": {"insights": [{"id": 648, "podcast_episode_id": 637,
                                      "title": "How Bending Spoons Built a $20 Billion Compounder | Luca Ferrari",
                                      "summary": BET}]},
        "deepDives": {"618": {"id": 618, "insight_id": 618, "podcast_episode_id": 607,
                              "insight_title": "AI Cyber Panic, Ken Griffin's Bubble Warning, The Fall of France?",
                              "ticker_analysis": {"META": {"rationale": CAPEX,
                                                           "positioning": "Watch"}}}},
    }


def test_capex_intensity_fixed_in_deep_dive_618():
    d = _data()
    export_data._apply_summary_overrides(d)
    r = d["deepDives"]["618"]["ticker_analysis"]["META"]["rationale"]
    assert "capex intensity" not in r and "heavy capital spending versus near-term payoff" in r


def test_bending_spoons_bet_wording_removed_everywhere():
    d = _data()
    export_data._apply_summary_overrides(d)
    for s in (d["archive"]["insights"][0]["summary"], d["mainContent"]["insights"][0]["summary"]):
        assert "bet" not in s.split() and "venture-style model that depends on repeated" in s
        assert not site_text_sanitize.style_gate_hits(s)


def test_idempotent():
    d = _data()
    export_data._apply_summary_overrides(d)
    once = json.dumps(d, sort_keys=True)
    export_data._apply_summary_overrides(d)
    assert json.dumps(d, sort_keys=True) == once


def test_rules_present_and_capex_rule_scoped():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())
    r = [x for x in rules["summaries"] if x.get("insight_id") == 618]
    assert len(r) == 1 and r[0]["podcast_episode_id"] == 607
    assert ["capex intensity", "heavy capital spending"] in r[0]["replacements"]
    olds = [g[0] for g in rules["global_replacements"]]
    assert "venture-style bet" in olds
    assert "capex intensity" not in olds  # stays card-scoped (see test_sweep_1102 card 700)
