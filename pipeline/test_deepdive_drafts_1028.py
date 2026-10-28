"""Oct 28 2026: G's 49 fixes to the held deep dive drafts 616 (ep 604), 625 (ep 613) and 628 (ep 616)
(cos/deepdive_drafts_1028/G_fixes.md), applied as export-time summary_overrides rules.

Each reviewed draft row (test_deepdive_drafts_1028_fixture.json: the exact deep_dive_content row and
latest_insights card that will be imported, unchanged) is rendered through the same chain export_data
uses for data.js deepDives (sanitize_public_text -> _apply_summary_overrides ->
_normalize_tickers_mentioned), and every fix is asserted on the result."""
import copy
import json
import re
from pathlib import Path

import pytest

import export_data
from site_text_sanitize import find_style_gate_hits, sanitize_public_text

FIX = json.loads((Path(__file__).resolve().parent / "test_deepdive_drafts_1028_fixture.json").read_text(encoding="utf-8"))
JSON_FIELDS = ("key_takeaways_detailed", "ticker_analysis", "risk_factors", "contrarian_signals",
               "catalysts", "related_insights", "falsification_tracks")
BANNED = re.compile(r"\b(bet|bets|betting|thin)\b", re.I)


def _deep_dive(i):
    """Mirror db_manager.get_all_deep_dive_content for the fixture row."""
    f = FIX[str(i)]
    c = dict(copy.deepcopy(f["db_row"]), **copy.deepcopy(f["export_meta"]))
    for k in JSON_FIELDS:
        if c.get(k):
            try:
                c[k] = json.loads(c[k])
            except Exception:
                pass
    return c


def _card(i, as_json):
    li = copy.deepcopy(FIX[str(i)]["latest_insight"])
    if not as_json:
        li["tickers_mentioned"] = json.loads(li["tickers_mentioned"])
        li["notable_quotes"] = json.loads(li["notable_quotes"])
    return li


def _render():
    data = {"archive": {"insights": [_card(i, False) for i in (616, 625, 628)]},
            "mainContent": {"insights": [_card(i, True) for i in (616, 625, 628)]},
            "deepDives": {str(i): _deep_dive(i) for i in (616, 625, 628)}}
    data = sanitize_public_text(data)
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    return data


@pytest.fixture(scope="module")
def out():
    return _render()


def _cards(out, i):
    a = [c for c in out["archive"]["insights"] if c["id"] == i][0]
    m = [c for c in out["mainContent"]["insights"] if c["id"] == i][0]
    q = m["notable_quotes"]
    return a, dict(m, notable_quotes=json.loads(q) if isinstance(q, str) else q)


def _ev(out, i):
    return out["deepDives"][str(i)]["episode_evidence"].split("\n")


# ---- 616: ClusterMAX 3.0 (ep 604) ---------------------------------------------------------------

def test_616_evidence(out):  # fixes 1-5
    assert _ev(out, 616) == [
        "Dylan Patel: And it's like, good God, we're just like here to test the cluster and we can, like, see this stuff.",
        "Dylan Patel: It's really tough. It's the toughest it's ever been to rent compute.",
        "Jordan Nanos: And so SpaceX's contract with Google, for example, has mutual 90-day cancellation rights.",
    ]
    ev = out["deepDives"]["616"]["episode_evidence"]
    for gone in ("10 criteria to ground", "Even back from the first cluster max", "VLM or S Chile", "Dylan:"):
        assert gone not in ev


def test_616_overview_catalyst_falsifiers(out):  # fixes 6-13
    dd = out["deepDives"]["616"]
    assert "support a mix of chip types for inference and reinforcement learning." in dd["overview"]
    assert "heterogeneous chips for inference and RL" not in dd["overview"]
    assert dd["overview"].endswith(
        "The episode also suggests contract terms matter more than they look: SpaceX's SEC filing on its June 2026 cloud "
        "agreement with Google says either side can end it on 90 days' notice after Dec. 31, 2026, so big compute deals can "
        "be more reversible than they appear.")
    assert "optionality and 90-day exit windows" not in dd["overview"]
    assert dd["catalysts"][3] == ("Evidence of broader GB300 NVL72 adoption among top-tier customers, likely during the "
                                  "next procurement cycle.")
    assert len(dd["catalysts"]) == 5 and "VL72" not in dd["catalysts"][3].replace("NVL72", "")
    assert dd["falsification_tracks"] == [
        "By 2027-06-30, if the Silicon Data H100 Rental Price Index (SDH100RT) is more than 20% below its Oct. 28, 2026 "
        "level of $2.90 per GPU-hour, Dylan Patel's claim that compute is the hardest it has ever been to rent no longer "
        "holds. Source: silicondata.com H100 Rental Price Index.",
        "By 2029-03-31, if published industry estimates put China's 2028 domestic AI chip output below 10 million chips, "
        "Dylan Patel's claim that China will reach tens of millions of chips produced by 2028 is wrong. Source: "
        "SemiAnalysis, TrendForce, or similar industry reports.",
    ]
    assert list(dd["ticker_analysis"]) == ["NVDA"]  # unchanged


def test_616_card_quotes(out):  # fixes 14-16
    for card in _cards(out, 616):
        assert card["notable_quotes"] == [
            {"speaker": "Dylan Patel", "quote": "It's really tough. It's the toughest it's ever been to rent compute."}]


# ---- 625: Supabase (ep 613) ---------------------------------------------------------------------

def test_625_evidence(out):  # fixes 1-5
    assert _ev(out, 625) == [
        'Paul Copplestone: "So tomorrow we\'re announcing, and by the time this comes out, Supabase Compute, which is you can run anything."',
        'Paul Copplestone: "It completely removes the need for some of these background tasks, like vacuum and bloat, so it\'s actually very efficient for your database as well."',
    ]
    assert "Ant (Supabase)" not in json.dumps(out["deepDives"]["625"], ensure_ascii=False)


def test_625_quotes_and_tickers(out):  # fixes 6-8
    for card in _cards(out, 625):
        assert card["notable_quotes"] == []
        tm = card["tickers_mentioned"]
        tm = json.loads(tm) if isinstance(tm, str) else tm
        assert "DBX" not in tm and "SQ" not in tm and "XYZ" not in tm
        assert {"AMZN", "GOOGL"} <= set(tm)
    dd = out["deepDives"]["625"]
    assert set(dd["ticker_analysis"]) == {"AMZN", "GOOGL"}


def test_625_text(out):  # fixes 9-19
    dd = out["deepDives"]["625"]
    assert dd["ticker_analysis"]["AMZN"]["rationale"].startswith(
        "AWS is relevant because Supabase runs on it: the founders describe moving from DigitalOcean to AWS after Y "
        "Combinator, and say they meet AWS repeatedly about compute capacity. Any successful expansion")
    assert "a place where AI-built apps both run and store their data" in dd["overview"]
    assert "execution-and-storage substrate" not in dd["overview"]
    assert "the company is planning around how many databases get created, not how many people use them." in dd["overview"]
    assert "launch-rate regime" not in dd["overview"]
    assert dd["catalysts"][:3] == [
        "Supabase Compute moving from private alpha (announced Oct. 2, 2026) to wider availability, plus early developer adoption data.",
        "OrioleDB public beta feedback, benchmark results, and post-launch issue reports over the next 1-2 quarters.",
        "First Multigres sharding features, which the founders said should start to land by early 2027, followed by customer testing.",
    ]
    assert len(dd["catalysts"]) == 5
    assert dd["falsification_tracks"] == [
        "By 2027-06-30, if Supabase Compute is still in private alpha rather than open to all paid projects, per Supabase's docs or changelog, the core compute thesis weakens.",
        "By 2027-06-30, if Supabase's OrioleDB docs still label it beta and not for production use, the storage-engine thesis weakens. Source: supabase.com/docs/guides/database/orioledb.",
        "By 2027-03-31, if a Supabase incident report, postmortem, or Multigres GitHub issue confirms data loss during a Multigres failover, the reliability thesis is broken. Source: status.supabase.com incident history and the Multigres GitHub repo.",
        "By 2027-12-31, if Supabase has not publicly reported launching at least 50 million databases in a single month (the founders said about five million a month in this episode), the “billions per month” plan looks overstated. Source: Supabase blog, press releases, or founder posts.",
        "By 2027-09-30, if Supabase's Multigres docs or release notes say sharding requires changes to application queries, or sharding still has not shipped, the founders' zero-code-change promise fails. Source: supabase.com/docs/guides/database/multigres and the Supabase changelog.",
    ]


# ---- 628: Anthropic, Latent Space (ep 616) ------------------------------------------------------

def test_628_evidence(out):  # fixes 1-5
    assert _ev(out, 628) == [
        "swyx: Ultimately, it looks like Anthropic is really positioning their IPO to talk about going from chatbots to copilots to virtual collaborators."]
    ev = out["deepDives"]["628"]["episode_evidence"]
    for gone in ("Trillion 12 month", "harder to distill", "fork of the entire API in Rust", "40 to 50%", "Pam", "Caitlin"):
        assert gone not in ev


@pytest.mark.parametrize("label", ["Pam", "swyx"])
def test_628_trillion_cut_matches_both_labels(label):  # G note 2
    e = FIX["628"]["db_row"]["episode_evidence"].split("\n")
    lines = [l.replace("Pam: ", label + ": ", 1) for l in e]
    data = {"archive": {"insights": []}, "mainContent": {"insights": []},
            "deepDives": {"628": dict(_deep_dive(628), episode_evidence="\n".join(lines))}}
    export_data._apply_summary_overrides(data)
    assert data["deepDives"]["628"]["episode_evidence"].startswith("swyx: Ultimately,")
    assert "Trillion" not in data["deepDives"]["628"]["episode_evidence"]


def test_628_quotes_and_text(out):  # fixes 6-14
    for card in _cards(out, 628):
        assert card["notable_quotes"] == []
    dd = out["deepDives"]["628"]
    assert "persist in its filings once it is a public company" in dd["investment_thesis"]
    assert "post-IPO filings" not in dd["investment_thesis"]
    assert dd["catalysts"][:2] == [
        "Anthropic’s IPO: it filed a public S-1 with the SEC on Oct. 26, 2026, to list on Nasdaq as “ANT”; the price range and listing date have not been set.",
        "Anthropic’s first quarterly report as a public company, which will show whether revenue per employee (over $6.6 million for the 12 months to Sept. 30, 2026, per the S-1) keeps rising.",
    ]
    assert len(dd["catalysts"]) == 5
    assert dd["falsification_tracks"] == [
        "By 2027-06-30, if Anthropic has listed and its first quarterly report as a public company (Form 10-Q or earnings release) shows trailing-12-month revenue per employee below the $6.6 million it reported in its S-1 for Sept. 30, 2026, the efficiency story is weakening. Source: SEC EDGAR.",
        "By 2027-06-30, if Anthropic’s first quarterly report as a public company shows the share of $100,000+ customers using both Claude Platform and at least one Anthropic app below 50% (the S-1 figure for the quarter ended Sept. 30, 2026), the platform-stickiness thesis weakens. Source: SEC EDGAR.",
        "By 2027-01-31, if published security research or an Anthropic disclosure shows outside parties successfully distilling Claude Opus 5.5 through the public API, the anti-distillation work has not held. Source: published research or Anthropic’s news and security posts.",
    ]
    assert dd["ticker_analysis"] == {}


# ---- all three ----------------------------------------------------------------------------------

def test_no_banned_words_outside_quotes(out):
    for i in (616, 625, 628):
        dd = out["deepDives"][str(i)]
        assert find_style_gate_hits(dd) == [], i
        cards = _cards(out, i)
        for c in cards:
            assert find_style_gate_hits({k: v for k, v in c.items() if k != "notable_quotes"}) == [], i
        for k, v in dd.items():
            if k in ("episode_evidence", "insight_title"):
                continue  # evidence is verbatim quotes (exempt)
            assert not BANNED.search(json.dumps(v, ensure_ascii=False)), (i, k)


def test_idempotent(out):
    again = copy.deepcopy(out)
    export_data._apply_summary_overrides(again)
    export_data._normalize_tickers_mentioned(again)
    assert again["deepDives"] == out["deepDives"]


def test_relabel_and_drop_list_items_helpers():
    q = [{"speaker": "Dylan", "quote": "It's really tough."}, {"speaker": "Dylan", "quote": "Other."}]
    assert export_data._relabel_quotes(q, [["really tough", "Dylan Patel"]]) == [
        {"speaker": "Dylan Patel", "quote": "It's really tough."}, {"speaker": "Dylan", "quote": "Other."}]
    s = export_data._relabel_quotes(json.dumps(q), [["really tough", "Dylan Patel"]])
    assert json.loads(s)[0]["speaker"] == "Dylan Patel"
    assert export_data._drop_quotes(["keep me", "drop me"], ["drop"]) == ["keep me"]


def test_rules_scoped_to_their_insights():
    other = {"id": 999, "podcast_episode_id": 998, "title": "x", "tickers_mentioned": ["DBX", "NVDA"],
             "notable_quotes": [{"speaker": "Dylan", "quote": "It's really tough. It's the toughest it's ever been to rent compute."},
                                {"speaker": "Pam", "quote": "Somewhere, like, 40 to 50%. Something, like, really crazy."}],
             "falsification_tracks": ["shows Google's SpaceX deal lacks mutual 90-day cancellation rights"]}
    data = {"archive": {"insights": [copy.deepcopy(other)]}, "mainContent": {"insights": []}, "deepDives": {}}
    export_data._apply_summary_overrides(data)
    got = data["archive"]["insights"][0]
    assert got["notable_quotes"] == other["notable_quotes"]
    assert got["falsification_tracks"] == other["falsification_tracks"]
    assert "DBX" in got["tickers_mentioned"]
