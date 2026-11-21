"""Nov 20 2026 nightly batch (G g_fixes_2026-11-20 + site check items 1-5, junk net worths)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

T405 = "Anthropic's $2T IPO, Zuck's AI Manifesto, Nvidia's $500B AI Bet, Grok's Comeback"


def _ov(obj):
    export_data._apply_summary_overrides(obj)
    return obj


def test_card_420_anduril_is_anthropic_scoped():
    c = {"id": 420, "podcast_episode_id": 405, "title": "t", "tickers_mentioned": ["ANDR", "SPCE"],
         "key_takeaway": "Anduril's upcoming IPO presents an opportunity to invest in a company with significant revenue growth and a lower valuation compared to peers, while the rise of open-source AI could reshape the software industry landscape."}
    other = {"id": 544, "podcast_episode_id": 999, "title": "t", "summary": "Anduril's upcoming IPO presents an opportunity"}
    _ov({"cards": [c, other]})
    assert c["tickers_mentioned"] == [] and "Anduril" not in c["key_takeaway"]
    assert "Anduril" in other["summary"]  # no global Anduril rule


def test_deep_dive_420_lists():
    dd = {"insight_id": 420, "podcast_episode_id": 405, "key_tickers": ["ANDR", "SPCE"],
          "ticker_analysis": {"AAPL": {"rationale": "x"}},
          "contrarian_signals": ["Regulatory changes or increased scrutiny on data privacy could hinder Anduril's growth and impact its valuation."],
          "falsification_tracks": ["A failure to go public by October, as speculated, could indicate internal or market-related issues that might affect the company's valuation."]}
    _ov({"deepDives": {"420": dd}})
    assert dd["key_tickers"] == [] and dd["ticker_analysis"] == {}
    assert dd["contrarian_signals"] == [] and dd["falsification_tracks"] == []


def test_card_703_ghodsi():
    c = {"id": 703, "podcast_episode_id": 692, "title": "t", "summary": "x with one host saying AI adoption will take 10-15 years and GDP effects will take decades. y",
         "notable_quotes": [{"speaker": "one host", "quote": "I think the biggest challenge that's facing us is how do we actually just make this AI applicable inside organizations?"},
                            {"speaker": "one host", "quote": "They're just using it as a glorified Google search."}]}
    elsewhere = {"id": 1, "podcast_episode_id": 5, "title": "t", "notable_quotes": [{"speaker": "one host", "quote": "x"}]}
    _ov({"cards": [c, elsewhere]})
    assert [q["speaker"] for q in c["notable_quotes"]] == ["Ali Ghodsi", "Ali Ghodsi"]
    assert c["notable_quotes"][0]["quote"].startswith("I argue that the biggest")
    assert elsewhere["notable_quotes"][0]["speaker"] == "one host"


def test_card_705_706_707():
    c705 = {"id": 705, "podcast_episode_id": 696, "title": "t", "tickers_mentioned": ["ANT"],
            "notable_quotes": [{"speaker": "one host", "quote": "the offering would raise about $64 billion value in thropic at 1.4 trillion"}]}
    c706 = {"id": 706, "podcast_episode_id": 694, "title": "t", "sentiment": "neutral", "tickers_mentioned": ["WPM", "SILV"]}
    c707 = {"id": 707, "podcast_episode_id": 695, "title": "t", "tickers_mentioned": ["TSM", "AMD"],
            "summary": "enforcement. one host argues x. response. one host says y",
            "notable_quotes": [{"speaker": "Chris McGuire", "quote": "equivalent of about 200 of the most advanced black well chips or about 800 H 100 chips."}]}
    _ov({"cards": [c705, c706, c707]})
    assert c705["tickers_mentioned"] == [] and "value in Anthropic" in c705["notable_quotes"][0]["quote"]
    assert c706["sentiment"] == "bullish" and c706["tickers_mentioned"] == ["WPM"]
    assert "Blackwell chips" in c707["notable_quotes"][0]["quote"] and "H100" in c707["notable_quotes"][0]["quote"]
    assert c707["summary"].count("One host") == 2 and c707["tickers_mentioned"] == ["TSM", "AMD"]


def _pundit(pid, title, **kw):
    p = {"id": pid, "name": "N", "slug": "n", "bio": "b", "mention_score": 1, "last_episode_title": title}
    p.update(kw)
    return p


def test_pundit_rules():
    rule = _pundit(681, "How Deficits Will Drive the Next Wave of the Commodity Supercycle | Rick Rule",
                   supporting_takeaway="x versus the higher January level he cited.", last_proof_snippet="garbage")
    ros = _pundit(495, "MacroVoices #552 David Rosenberg: Navigating The Noise", last_main_idea="x")
    wang = _pundit(460, "Hawks Take Flight | Joseph Wang on Fed\u2019s Hawkish Hike and Warsh\u2019s Gameplan", last_main_idea="x")
    gb = _pundit(290, T405, last_main_idea="Anduril", supporting_takeaway="y", last_proof_snippet="Evan Baker")
    _ov({"pundits": [rule, ros, wang, gb]})
    assert "January level of about $42 per ounce he cited" in rule["supporting_takeaway"]
    assert rule["last_proof_snippet"].startswith("I think that the silver stocks")
    assert "last_main_idea" not in ros and "last_main_idea" not in wang
    assert "last_main_idea" not in gb and gb["last_proof_snippet"] == ""


def test_junk_net_worths_blanked():
    ids = [242, 335, 40, 444, 121, 117, 187, 180, 94, 203, 403]
    rows = [_pundit(i, "t", net_worth="$1.0M", net_worth_usd=1e6, net_worth_source="http://x") for i in ids]
    _ov({"pundits": rows})
    for r in rows:
        assert not r.get("net_worth") and not r.get("net_worth_usd") and not r.get("net_worth_source")


def test_power_bottleneck_q3_past_tense():
    h = (Path(__file__).resolve().parent.parent / "site" / "power-bottleneck.html").read_text(encoding="utf-8")
    assert "Vistra reported third-quarter 2026 results" in h and "expected Nov 9" not in h
    assert "not yet confirmed by the company)" not in h
