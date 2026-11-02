"""Nov 2 2026 daily site check (cos/sweep_1102/daily_check_fixes.md): Dhruv Gupta name fix, ticker
cleanups on cards 644/646/647, Gemini 4 Carbon + plain-language wording on 647, 'eval' on 645,
dc-buildout CoreWeave date + Dominion update, qqq-filter CRSP gloss. Durable via summary_overrides.json;
quotes untouched, scoped, idempotent."""
import copy
import json
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def _apply(data):
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    return data


def _cards():
    return {"insights": [
        {"id": 644, "podcast_episode_id": 634, "title": "Can AI Fix Professional Networking? | Inside Cosign",
         "summary": "while Drew Gupta describes Cosign", "tickers_mentioned": ["MUSES", "MCP"]},
        {"id": 645, "podcast_episode_id": 633, "title": "Building ChatGPT for Finance",
         "summary": "no good financial \u201cE-value\u201d today; an investment-banking E-value", "tickers_mentioned": []},
        {"id": 646, "podcast_episode_id": 635, "title": "Using Agents for Long-Horizon Financial Work",
         "summary": "x", "tickers_mentioned": ["ARCA", "GOOGL"]},
        {"id": 647, "podcast_episode_id": 636, "title": "Making Sense of This Week\u2019s AI Market Crashes | #x307",
         "summary": "Gemini for Carbon sits near the front; capex intensity pressure margins",
         "notable_quotes": [{"speaker": "Alex Wissner-Gross", "quote": "Gemini for carbon might look like"}],
         "tickers_mentioned": ["TSLA"]},
        {"id": 700, "podcast_episode_id": 699, "title": "Other", "summary": "Gemini for Carbon; capex intensity",
         "tickers_mentioned": ["ARCA", "TSLA"]},
    ], "deepDives": {"644": {"id": 642, "insight_id": 644, "podcast_episode_id": 634,
                             "ticker_analysis": {"MUSES": {}, "MCP": {}}},
                     "646": {"id": 644, "insight_id": 646, "podcast_episode_id": 635,
                             "ticker_analysis": {"ARCA": {}, "GOOGL": {}}}},
        "pundits": [{"id": 1, "name": "Drew Gupta", "last_proof_snippet": "Drew Gupta says Cosign has 40,000 people",
                     "episode_evidence": "x.\nDrew Gupta: LinkedIn will never"}]}


def test_overrides_apply_scoped_and_idempotent():
    out = _apply(_cards())
    c = {o["id"]: o for o in out["insights"]}
    assert c[644]["tickers_mentioned"] == [] and "Dhruv Gupta" in c[644]["summary"]
    assert out["deepDives"]["644"]["ticker_analysis"] == {}
    assert c[646]["tickers_mentioned"] == ["GOOGL"]
    assert list(out["deepDives"]["646"]["ticker_analysis"]) == ["GOOGL"]
    assert c[647]["tickers_mentioned"] == ["GOOGL", "TSLA"]
    assert "Gemini 4 Carbon sits" in c[647]["summary"] and "heavy capital spending pressure" in c[647]["summary"]
    assert c[647]["notable_quotes"][0]["quote"] == "Gemini for carbon might look like"  # quote untouched
    assert "financial \u201ceval\u201d (a test that scores AI on real finance work)" in c[645]["summary"]
    assert "investment-banking eval" in c[645]["summary"]
    # other cards untouched
    assert c[700]["summary"] == "Gemini for Carbon; capex intensity" and c[700]["tickers_mentioned"] == ["ARCA", "TSLA"]
    p = out["pundits"][0]
    assert p["name"] == "Dhruv Gupta" and "Drew" not in p["last_proof_snippet"] and "Drew" not in p["episode_evidence"]
    again = _apply(copy.deepcopy(out))
    assert again == out


def test_site_files_fixed():
    for name in ("data/data.js", "data/archive.json", "data/pundits.json", "data/podcast_summaries.json"):
        t = (SITE / name).read_text()
        assert "Drew Gupta" not in t and "E-value" not in t and "capex intensity" not in t
        assert "Gemini for Carbon" not in t
    js = (SITE / "data/data.js").read_text()
    assert js.count("Dhruv Gupta") >= 10 and "Gemini for carbon" in js  # quotes kept
    assert '"MUSES"' not in js and '"ARCA"' not in js


def test_dc_buildout_coreweave_and_dominion():
    t = (SITE / "dc-buildout.html").read_text()
    new = "results set for Tue Nov 10 after the close (5 PM ET / 4 PM CT), announced Oct 27, 2026"
    assert t.count(new) >= 3
    assert "<tr><td>Tue Nov 10 (after close)</td><td>CoreWeave Q3" in t
    assert "checked Oct 18" not in t and "10-Q due ~Nov 9" not in t and "By about Nov 9" not in t
    assert "we'll re-check" not in t and "Update Oct 30" not in t
    assert ("Update Nov 2: we still have not found Dominion's revised policy. The SCC opened Case No. "
            "PUR-2026-00131 on Aug 25, 2026 to receive it") in t
    assert "https://www.scc.virginia.gov/docketsearch/DOCS/8%237%2501!.PDF" in t
    # calendar stays in date order: Nov 10 row after Nov 6, before Nov 16
    assert t.index("<tr><td>Fri Nov 6 (call") < t.index("<tr><td>Tue Nov 10 (after close)") < t.index("<tr><td>Mon Nov 16")


def test_qqq_crsp_gloss():
    t = (SITE / "qqq-filter.html").read_text()
    assert t.count("CRSP database (the University of Chicago's standard US stock-price history)") == 1
