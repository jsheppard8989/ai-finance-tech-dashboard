"""Nov 19 2026 (G weekday site check): pundit 403 stale Anduril fields, card 695
GAAP quote + tickers, card 697 tickers, card 704 quote 2, data.js portfolio exit text,
healthcare/debait/lrcx/power static page wording. Stored DB text and live data.js text
are identical for every override here (checked Nov 19)."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

SITE = Path(__file__).resolve().parent.parent / "site"
T405 = "Anthropic's $2T IPO, Zuck's AI Manifesto, Nvidia's $500B AI Bet, Grok's Comeback"


def _pundit_403(title=T405):
    return {
        "id": 403, "name": "Evan Baker", "slug": "evan-baker", "bio": "x", "mention_score": 1,
        "last_episode_title": title,
        "last_main_idea": "Anduril's upcoming IPO presents an opportunity to invest in a company with significant revenue growth and a lower valuation compared to peers, while the rise of open-source AI could reshape the software industry landscape.",
        "supporting_takeaway": "The company is expected to go public in October with an annualized run rate between $100 and $120 billion.",
        "last_proof_snippet": "",
    }


def test_pundit_403_fields_removed():
    obj = {"pundits": [_pundit_403()]}
    export_data._apply_summary_overrides(obj)
    p = obj["pundits"][0]
    assert "last_main_idea" not in p and "supporting_takeaway" not in p
    assert "Anduril" not in json.dumps(obj)


def test_pundit_403_rule_gated_to_episode():
    obj = {"pundits": [_pundit_403(title="Some later episode")]}
    export_data._apply_summary_overrides(obj)
    assert "last_main_idea" in obj["pundits"][0]


def _card_695():
    q = "And anthropic, you know, a gap operating profit of just shy of $900 million in Q2. A operating profit if you exclude a donation charge in Q3 as well."
    return {
        "id": 695, "podcast_episode_id": 684,
        "title": "The Bond Squeeze | Jan van Eck on >5% Treasury Yields, Semis, Anthropic, and Gold",
        "tickers_mentioned": ["NVDA", "ASML", "INDIA", "GOLD"],
        "notable_quotes": [{"speaker": "Jan van Eck", "quote": q}],
        "episode_evidence": "Jan van Eck: " + q,
    }


def test_card_695_gaap_and_tickers():
    obj = {"cards": [_card_695()]}
    export_data._apply_summary_overrides(obj)
    c = obj["cards"][0]
    assert c["notable_quotes"][0]["quote"].startswith("And Anthropic, you know, a GAAP operating profit of just shy")
    assert "a gap operating" not in json.dumps(c)
    assert c["tickers_mentioned"] == ["NVDA", "ASML"]


def test_card_697_tickers():
    obj = {"cards": [{"id": 697, "podcast_episode_id": 686, "title": "Paul Christiano",
                      "tickers_mentioned": ["METER", "ARC"]}]}
    export_data._apply_summary_overrides(obj)
    assert obj["cards"][0]["tickers_mentioned"] == []


def test_card_704_quote_2_dropped():
    obj = {"cards": [{"id": 704, "podcast_episode_id": 693, "title": "t", "notable_quotes": [
        {"speaker": "Ken Liu", "quote": "So we focus on essentially creating a model of a person and then put that person in control."},
        {"speaker": "Ken Liu", "quote": "It is a very hard problem, especially to get its secure private."}]}]}
    export_data._apply_summary_overrides(obj)
    qs = obj["cards"][0]["notable_quotes"]
    assert len(qs) == 1 and "secure private" not in json.dumps(qs)


def test_portfolio_exit_datajs_only():
    raw = (SITE / "data" / "portfolio.json").read_text(encoding="utf-8")
    pf = json.loads(raw)
    out = export_data._apply_portfolio_exit_overrides(copy.deepcopy(pf))
    names = out["baskets"][0]["names"]
    assert len(names) == 5
    for n in names:
        assert n["exit"] == "Hims & Hers Q3 report, Nov 9: 2.788M subscribers, below 2.891M; basket closed"
    # frozen record untouched
    assert (SITE / "data" / "portfolio.json").read_text(encoding="utf-8") == raw
    assert "expected Nov 9" in raw


def test_static_pages():
    h = (SITE / "healthcare.html").read_text(encoding="utf-8")
    assert "recorded in our private trade archive" in h and "Trap Map archive" not in h
    d = (SITE / "debait.html").read_text(encoding="utf-8")
    assert "No new contract this week" not in d
    l = (SITE / "lrcx-paid-to-wait.html").read_text(encoding="utf-8")
    assert "<h2>What happened</h2>" in l and "<td>Nov 17</td>" not in l
    assert "point to slower AI data center buying. That would weaken" not in l
    pw = (SITE / "power-bottleneck.html").read_text(encoding="utf-8")
    assert "ER27-531-000" in pw and "About Mon Nov 16, 2026" not in pw
