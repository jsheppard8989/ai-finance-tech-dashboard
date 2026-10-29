"""Oct 29 2026 daily site check (cos/sweep_1029/fixes.md): card 630 (Annie Seelaus, The Credit Edge)
plain-language summary + key_takeaway, the new global 'asset_class_tickers' rule, and pundit 586's
host-intro proof snippet. Quotes untouched, scoped, idempotent."""
import copy
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Mom-and-Pop Buyers Pounce on Battered Hyperscaler Bonds, Says Seelaus"
TAKE_OLD = ("The episode\u2019s main claim is that current calm credit spreads hide lagged technical stress, making "
            "selective liquidity-sensitive and AI/data-center underwriting more important than broad market averages.")
TAKE_NEW = ("Seelaus says calm credit spreads hide stress that shows up with a lag, so picking the right bonds, "
            "especially in thinly traded areas and AI data-center debt, matters more than buying the whole market.")
SUM_OLD = ("less-liquid sectors such as BDCs and REITs. preferreds, and certain IG paper as attractive, while warning "
           "that investors should not deploy all dry powder at once because \u201cfundamental cracks\u201d.\n\n"
           "She also sees ABS and private credit growth as investable.")
SUM_NEW = ("less-liquid sectors such as business development companies (BDCs) and real estate investment trusts (REITs). "
           "preferreds, and some investment-grade corporate bonds as attractive, while warning that investors should "
           "not put all their spare cash to work at once because \u201cfundamental cracks\u201d.\n\n"
           "She also sees the growth of asset-backed securities and private credit as investable.")
QUOTE = {"speaker": "Annie Seelaus", "quote": "We like IG paper and ABS here, keep dry powder."}
ASSET = ["BDC", "REIT", "IG", "HY", "ABS", "CMBS"]


def _apply(data):
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    return data


def _card(i=630, ep=619):
    return {"id": i, "podcast_episode_id": ep, "title": TITLE, "summary": SUM_OLD, "key_takeaway": TAKE_OLD,
            "sentiment": "neutral", "tickers_mentioned": list(ASSET), "notable_quotes": [dict(QUOTE)]}


def test_asset_class_tickers_config():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())
    assert set(ASSET) <= set(rules["asset_class_tickers"])
    assert "LENS" in rules["sponsor_tickers"]


def test_630_card():
    data = {"archive": {"insights": [_card()]}, "priceSnapshot": {"REIT": {"price": 1.0}}}
    _apply(data)
    c = data["archive"]["insights"][0]
    assert c["tickers_mentioned"] == []
    assert c["summary"] == SUM_NEW
    assert c["key_takeaway"] == TAKE_NEW
    assert c["sentiment"] == "neutral"
    assert c["notable_quotes"] == [QUOTE]  # quote text never changes
    assert data["priceSnapshot"] == {"REIT": {"price": 1.0}}
    once = copy.deepcopy(data)
    _apply(data)
    assert data == once
    assert publish_guard.find_style_gate_hits(data["archive"]) == []


def test_asset_class_tickers_dropped_on_any_card_but_real_tickers_kept():
    data = {"archive": {"insights": [
        {"id": 9001, "podcast_episode_id": 9001, "title": "Other", "summary": "IG and HY spreads",
         "tickers_mentioned": json.dumps(["HY", "NVDA", "CMBS"]), "key_tickers": ["abs", "TLT"]}]},
        "deepDives": {"9001": {"insight_id": 9001, "key_tickers": ["REIT", "MSFT"],
                               "ticker_analysis": {"BDC": {"rationale": "x"}, "MSFT": {"rationale": "y"}}}}}
    _apply(data)
    c = data["archive"]["insights"][0]
    tm = c["tickers_mentioned"]
    assert (json.loads(tm) if isinstance(tm, str) else tm) == ["NVDA"]
    assert c["key_tickers"] == ["TLT"] and c["summary"] == "IG and HY spreads"
    dd = data["deepDives"]["9001"]
    assert dd["key_tickers"] == ["MSFT"] and list(dd["ticker_analysis"]) == ["MSFT"]


def _pundits(title=TITLE):
    return {"pundits": [{"id": 586, "name": "Annie Seelaus", "slug": "annie-seelaus", "mention_score": 1,
                         "last_episode_title": title, "last_main_idea": TAKE_OLD,
                         "last_proof_snippet": "Speaker 1: My name is James Crombie. I'm a senior editor at Bloomberg.",
                         "last_proof_cite": "The Credit Edge by Bloomberg Intelligence \u2022 2026-10-22 \u2022 " + title,
                         "supporting_takeaway": "Seelaus says rate moves hit with a lag."}]}


def test_pundit_586():
    rows = _pundits()
    export_data._apply_summary_overrides(rows)
    p = rows["pundits"][0]
    assert "last_proof_snippet" not in p and "last_proof_cite" not in p
    assert p["last_main_idea"] == TAKE_NEW
    assert p["supporting_takeaway"] == "Seelaus says rate moves hit with a lag."
    once = copy.deepcopy(rows)
    export_data._apply_summary_overrides(rows)
    assert rows == once


def test_pundit_586_gate_holds_for_new_episode():
    rows = _pundits(title="A later Seelaus episode")
    export_data._apply_summary_overrides(rows)
    assert rows["pundits"][0]["last_proof_snippet"].startswith("Speaker 1")


def test_633_buckets_wording_matches_618_fix():
    old = "The actionable setup is to separate AI beneficiaries into three buckets: owners of complements"
    data = {"deepDives": {"633": {"insight_id": 633, "podcast_episode_id": 620, "investment_thesis": old}},
            "archive": {"insights": [{"id": 9633, "podcast_episode_id": 9620, "investment_thesis": old}]}}
    _apply(data)
    assert data["deepDives"]["633"]["investment_thesis"].endswith("into three groups: owners of complements")
    assert data["archive"]["insights"][0]["investment_thesis"] == old  # other cards untouched
