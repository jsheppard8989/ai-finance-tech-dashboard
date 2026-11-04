"""Nov 4 2026 daily site check (G, sweep_1104): cards 644, 653, 654, Overton 'Evals', pundit 613,
guest-list rename for Cosign, and the passed Nov 3 row on lrcx-paid-to-wait."""
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
GUESTS = "David Booth & Dhruv Gupta"


def _site():
    return publish_guard.parse_data_js((ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8"))


def _cards(d, cid):
    out = [i for i in d["mainContent"]["insights"] + d["archive"]["insights"] if i.get("id") == cid]
    assert out
    return out


def test_card_644_gupta_and_guest():
    d = _site()
    for c in _cards(d, 644):
        assert "Drew" not in c["summary"] and "Gupta says" in c["summary"] and "Gupta explicitly says" in c["summary"]
        if "guest_name" in c:
            assert c["guest_name"] == GUESTS
    # podcastGuests 109252 carried the episode title as a name; dropped via the exact-name blocklist
    assert not any(g.get("id") == 109252 for g in d["podcastGuests"])
    pj = json.loads((ROOT / "site" / "data" / "podcast_guests.json").read_text(encoding="utf-8"))
    assert "Can AI Fix Professional Networking?" not in [g["name"] for g in pj]


def test_card_654_wording():
    d = _site()
    for c in _cards(d, 654):
        s = c["summary"]
        assert "scores agent outputs with evals (automated checks run by AI judges)" in s
        assert "e-values" not in s and "grades" not in s and "costs have still" not in s
        assert "a measure the team tracks rose about 40% over the last month" in s
        assert "cost per pull request (each proposed code change)" in s
        assert "subscription-based usage" in s and "sub-based" not in s
        assert "MCP connectors (a standard way to plug outside tools into AI agents)" in s
        assert "[agentic] system in the cloud" in c["notable_quotes"][0]["quote"]
    dd = json.dumps(d["deepDives"]["654"])
    assert "retroactive grading" not in dd and "e-values" not in dd and "evals are a noisy proxy" in dd


def test_overton_evals():
    d = _site()
    for lst in (d["mainContent"]["overton"], d["archive"]["overton"]):
        t = [x for x in lst if x.get("id") == 282][0]
        assert t["term"] == "Evals" and "AI judge models to score agent outputs" in t["description"]


def test_card_653_ticker_quote_jargon():
    d = _site()
    for c in _cards(d, 653):
        assert c["tickers_mentioned"] == []
        assert not any("zero is better" in q["quote"] for q in c["notable_quotes"])
    dd = d["deepDives"]["653"]
    assert "X" not in (dd.get("ticker_analysis") or {})
    s = json.dumps(dd)
    assert "PSG" not in s and "sleep-lab tests (polysomnography), wrist-worn sleep trackers (actigraphy)" in s


def test_pundit_613_bio():
    p = [x for x in _site()["pundits"] if x.get("id") == 613][0]
    assert p["bio"].startswith("Founder and CEO of Warp, focused on")


def test_lrcx_passed_row_removed():
    assert "Lam annual shareholder meeting" not in (ROOT / "site" / "lrcx-paid-to-wait.html").read_text()


def test_rules_idempotent_on_fresh_record():
    c = {"id": 654, "podcast_episode_id": 643, "summary": "Lloyd says Warp grades agent outputs with e-values, and GitHub, and MCPs.",
         "notable_quotes": [{"speaker": "Zach Lloyd", "quote": "like a agente system in the cloud"}]}
    data = {"insights": [c]}
    export_data._apply_summary_overrides(data)
    once = json.dumps(data)
    export_data._apply_summary_overrides(data)
    assert json.dumps(data) == once and "[agentic]" in once and "e-values" not in once
