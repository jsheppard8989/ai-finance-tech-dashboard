"""Nov 3 2026 daily check (G, sweep_1103): 9 routine wording fixes on cards 644 and 648-652,
made export-proof via per-card rules in summary_overrides.json (+ guest_overrides.json for the
card 650 guest line). Checks the rules on synthetic records and the committed site data."""
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text(encoding="utf-8"))

OLD_GONE = [
    "GLD/XAUUSD as the grading source",
    "graded by an independent evaluation study",
    "with a claim from Claude that",
    "estimates Tudor robots",
    "upfront capex",
    "industrial automation capex",
    "Longer-duration government bonds",
    "long-duration Treasuries",
    "Long-duration Treasuries",
    "retest of 70,000",
    "excellent brometer of",
    "Oracle CDS widening",
    "last year’s capex with",
    "not just capex announcements",
    "credit spreads, CDS, issuance",
    "unsecured bond and CDS moves",
    "document trolling",
    "runs an evals team",
    "keeps leverage well below 3x",
]
NEW_PRESENT = [
    "GLD/XAUUSD as the source.",
    "scored by an independent evaluation study",
    "and he cites an estimate from Claude, Anthropic's AI assistant, that Tutor robots have helped manufacture and ship",
    "estimates [Tutor] robots",
    "upfront hardware costs",
    "industrial automation spending",
    "Longer-dated government bonds",
    "long-term Treasuries",
    "Long-term Treasuries",
    "term premium (the extra yield investors demand to hold long bonds)",
    "conventional QE (the Fed buying bonds)",
    "retest of $70,000",
    "Bitcoin is an excellent [barometer] of liquidity",
    "last year’s capital spending with",
    "Oracle's credit default swaps (the price of insurance against its default) widening",
    "credit spreads, credit default swaps, issuance mix",
    "weakening ISM factory survey through the year",
    "spent all this capex",  # quote left as said
    "less on combing through documents",
    "runs an evaluation team that tests the AI",
    "keeps net debt well below 3 times yearly operating earnings (EBITDA), currently around 2.4-2.5 times",
]


def _site():
    return publish_guard.parse_data_js((ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8"))


def _cards(d, ids):
    out = []
    for sec in ("archive", "mainContent"):
        out += [c for c in d[sec]["insights"] if c.get("id") in ids]
    out += [v for v in d["deepDives"].values() if v.get("insight_id") in ids]
    return out


def test_live_data_js_has_all_nine_fixes():
    d = _site()
    blob = json.dumps(_cards(d, {644, 648, 649, 650, 651, 652}), ensure_ascii=False)
    for old in OLD_GONE:
        assert old not in blob, old
    for new in NEW_PRESENT:
        assert new in blob, new
    for c in _cards(d, {649}):
        if "tickers_mentioned" in c:
            assert c["tickers_mentioned"] == ["JPM", "CRWV", "ORCL"]
    g = [c.get("guest_name") for c in _cards(d, {650}) if "guest_name" in c]
    assert g and all(x == "Josh Gruenstein" for x in g)


def test_rules_reapply_on_fresh_export_and_are_idempotent():
    rec = {"id": 650, "podcast_episode_id": 640, "guest_name": "Tutor Intelligence",
           "summary": "models, with a claim from Claude that Tutor robots have helped manufacture and ship over",
           "notable_quotes": [{"speaker": "Josh Gruenstein", "quote": "it estimates Tudor robots have"}]}
    dd = {"insight_id": 649, "podcast_episode_id": 638,
          "falsification_tracks": ["using US Treasury auction data and GLD/XAUUSD as the grading source."]}
    ins = {"id": 649, "podcast_episode_id": 638, "tickers_mentioned": ["JPM"],
           "summary": "funded much of last year’s capex with cash", "notable_quotes": [
               {"speaker": "Dan Krausz", "quote": "It's not as if we've spent all this capex into"}]}
    data = {"archive": {"insights": [rec, ins]}, "deepDives": {"649": dd}}
    export_data._apply_summary_overrides(data)
    once = json.dumps(data, sort_keys=True)
    assert rec["guest_name"] == "Josh Gruenstein"
    assert "estimates [Tutor] robots" in rec["notable_quotes"][0]["quote"]
    assert "cites an estimate from Claude, Anthropic's AI assistant" in rec["summary"]
    assert dd["falsification_tracks"][0].endswith("GLD/XAUUSD as the source.")
    assert ins["tickers_mentioned"] == ["JPM", "CRWV", "ORCL"]
    assert "capital spending" in ins["summary"] and "spent all this capex" in ins["notable_quotes"][0]["quote"]
    export_data._apply_summary_overrides(data)
    assert json.dumps(data, sort_keys=True) == once


def test_rules_are_card_scoped_not_global():
    mine = [r for r in RULES["summaries"] if "sweep_1103" in r.get("_note", "")]
    assert sorted(r["insight_id"] for r in mine) == [644, 648, 649, 650, 651, 652]
    assert all(r.get("podcast_episode_id") for r in mine)
    olds = {p[0] for k in ("global_replacements", "global_name_replacements", "name_replacements")
            for p in RULES.get(k, [])}
    for o in ("capex", "CDS", "ISM", "Tutor Intelligence", "Tudor", "brometer", "evals team"):
        assert o not in olds


def test_guest_overrides_card_650():
    gov = json.loads((ROOT / "pipeline" / "guest_overrides.json").read_text(encoding="utf-8"))
    assert gov["insight_guest_by_id"]["650"] == "Josh Gruenstein"
    # never a global name fix: 'Tutor Intelligence' is also the company name in summaries/bios
    assert "Tutor Intelligence" not in gov["fixes"]
