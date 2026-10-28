"""Oct 28 2026 daily site check (cos/sweep_1028/fixes.md): id-keyed export-time fixes for insights
627 (Vincent Deluard), 628 (Anthropic on Latent Space) and 629 (Mark Cuban), pundit 585, the six
Overton speaker fields from episode 616, and the new global 'sponsor_tickers' rule (LENS).
Rules re-apply on export, stay scoped, never reword quote text, and are idempotent."""
import copy
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
TITLE_617 = "The Fed Put Is Dead: Why Stagflation & a Bear Market Are Next | Vincent Deluard | StoneX"
TAKE_OLD = ("Treasure the next 6 months in Treasuries over equities because sticky inflation and fading "
            "fiscal support make the U.S. market vulnerable to a stagflationary bear phase.")
TAKE_NEW = ("Favor Treasuries over equities for the next 6 months because sticky inflation and fading "
            "fiscal support make the U.S. market vulnerable to a stagflationary bear phase.")
Q627_BAD = ("If you look at the consumer names, I mean, you are seeing just complete massacre most names, like your "
            "Nike, your Harley Davidson, your Renault, and McDonald's are down 50, 60% plus, which is very unusual for "
            "when you see the index at two percent from the old time high and the Fed being of hiking cycle.")
Q627_OK = "I think the primary reason to own treasuries is just liquidity. The seller's in treasuries bring their own buyers."
SUM_628 = (
    "Pam highlights that trailing-12-month revenue per employee rose to $6.6 million from $1.4 million a year earlier, "
    "and that Anthropic moved from losing 129% of every revenue dollar to making $2 for every $1 of cost, with the host "
    "characterizing the company's first profitable quarter as 19% GAAP profit.\n\nPam says over 50% of customers use "
    "Claude Platform. The episode also discusses Opus 5.5, which Pam says testers view as the best model in the world."
    "\n\nCaitlin spends most of the guest segment on safety.\n\nCaitlin describes Anthropic's \"brain vs. hands\" architecture.")
Q628 = [{"speaker": "Pam", "quote": "Trillion 12 month revenue per employee is now six point six million, uh, as compared to one year ago it was one point four million."},
        {"speaker": "Caitlin", "quote": "We did do a lot of work on trying to make our API harder to distill from."},
        {"speaker": "Caitlin", "quote": "Somewhere, like, 40 to 50%. Something, like, really crazy."}]
SUM_629 = ("He says Cost Plus Drugs launched on January 19, 2022 with 111 medications and has expanded to about 4,000 skews, "
           "while the pharmacy-card network includes 17,000 pharmacies.")
Q629 = [{"speaker": "Mark Cuban", "quote": "Take every benefits contract you're about to sign, run it through AI, and ask where you're getting screwed."},
        {"speaker": "Mark Cuban", "quote": "And I literally can save hospitals millions of dollars a year."},
        {"speaker": "Mark Cuban", "quote": "These pods cost about $20 million. Ship a two a research hospital. And if they specialize in any types of therapies."}]
FT_629 = ("By 2026-12-31, if archived website snapshots and independent catalog checks show CosplusTrugs.com has fewer than "
          "3,000 drug skews versus the claimed ~4,000, using the site archive and third-party catalog listings as source, "
          "the scale thesis weakens.")
EVID_629 = "Mark Cuban: So, now, as you said, we have 4,000 skews give or take."


def _card(i, pe, **kw):
    return dict({"id": i, "podcast_episode_id": pe, "title": f"t{i}", "sentiment": "neutral", "tickers_mentioned": []}, **kw)


def _payload():
    c627 = _card(627, 617, title=TITLE_617, key_takeaway=TAKE_OLD, tickers_mentioned=["LENS"],
                 notable_quotes=[{"speaker": "Vincent Deluard", "quote": Q627_BAD}, {"speaker": "Vincent Deluard", "quote": Q627_OK}])
    c628 = _card(628, 616, summary=SUM_628, notable_quotes=copy.deepcopy(Q628))
    c629 = _card(629, 618, summary=SUM_629, notable_quotes=copy.deepcopy(Q629))
    other = _card(999, 998, summary=SUM_629 + " " + SUM_628, key_takeaway=TAKE_OLD,
                  notable_quotes=copy.deepcopy(Q628 + Q629) + [{"speaker": "Vincent Deluard", "quote": Q627_BAD}])
    main627 = dict(copy.deepcopy(c627), tickers_mentioned=json.dumps(["LENS"]))
    return {
        "archive": {"insights": [c627, c628, c629, other]},
        "mainContent": {"insights": [copy.deepcopy(c629), main627]},
        "deepDives": {
            "627": {"id": 626, "insight_id": 627, "podcast_episode_id": 617, "insight_title": TITLE_617,
                    "key_tickers": [], "ticker_analysis": {"LENS": {"rationale": "LENS is positioned as a 'return to tangibles' vehicle"}}},
            "629": {"id": 627, "insight_id": 629, "podcast_episode_id": 618, "insight_title": "Cuban",
                    "key_tickers": [], "falsification_tracks": [FT_629, "Track two."], "episode_evidence": EVID_629},
        },
        "eps": [{"id": 617, "podcast_name": "Monetary Matters with Jack Farley", "episode_title": TITLE_617,
                 "investment_thesis": TAKE_OLD, "key_tickers": None},
                {"id": 618, "podcast_name": "The a16z Show", "episode_title": "Cuban", "summary": SUM_629,
                 "key_takeaways": ["Cost Plus Drugs has grown to roughly 4,000 skews."]}],
    }


def _apply(data):
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    return data


def test_627_deluard_card():  # fixes 1-4
    data = _apply(_payload())
    for c in (data["archive"]["insights"][0], data["mainContent"]["insights"][1]):
        assert c["key_takeaway"] == TAKE_NEW
        assert c["tickers_mentioned"] == []
        assert c["sentiment"] == "bearish"  # the site's negative value (index.html: bullish/bearish/neutral)
        assert [q["quote"] for q in c["notable_quotes"]] == [Q627_OK]  # garbled #1 dropped, #2 untouched
    dd = data["deepDives"]["627"]
    assert "LENS" not in dd["ticker_analysis"] and dd["key_tickers"] == []
    assert data["eps"][0]["investment_thesis"] == TAKE_NEW


def test_628_anthropic_card():  # fixes 6-9
    data = _apply(_payload())
    c = data["archive"]["insights"][1]
    # Oct 28 2026 deep dive draft review (G_fixes.md 628 fix 6): all three 628 quotes are now dropped.
    assert c["notable_quotes"] == []
    s = c["summary"]
    assert "Pam" not in s and "Caitlin" not in s and "129%" not in s
    for want in ("Host swyx highlights", "swyx says over 50%", "which swyx says testers view",
                 "Katelyn Lesse spends", "Lesse describes",
                 "Anthropic went from losing about half a dollar for every dollar of revenue in Q2 2025 to making $2 for every $1 of cost"):
        assert want in s, want
    assert "Katelyn Lesse describes" not in s  # G's wording: surname on second reference


def test_629_cuban_card_and_deep_dive():  # fixes 11-13
    data = _apply(_payload())
    for c in (data["archive"]["insights"][2], data["mainContent"]["insights"][0]):
        assert "about 4,000 SKUs" in c["summary"] and "skews" not in c["summary"]
        assert [q["quote"] for q in c["notable_quotes"]] == [Q629[0]["quote"], Q629[1]["quote"]]
    dd = data["deepDives"]["629"]
    assert dd["falsification_tracks"][0] == FT_629.replace("CosplusTrugs.com", "CostPlusDrugs.com").replace("drug skews", "drug SKUs")
    assert dd["falsification_tracks"][1] == "Track two."
    assert dd["episode_evidence"] == EVID_629  # transcript line (direct quote) left as-is
    assert data["eps"][1]["summary"].count("about 4,000 SKUs") == 1
    assert data["eps"][1]["key_takeaways"] == ["Cost Plus Drugs has grown to roughly 4,000 SKUs."]


def test_card_rules_are_id_scoped_and_idempotent():
    data = _apply(_payload())
    other = data["archive"]["insights"][3]
    assert other["key_takeaway"] == TAKE_OLD and other["sentiment"] == "neutral"
    assert "Pam highlights" in other["summary"] and "4,000 skews" in other["summary"] and "129%" in other["summary"]
    assert len(other["notable_quotes"]) == 7 and other["notable_quotes"][0]["speaker"] == "Pam"
    once = copy.deepcopy(data)
    _apply(data)
    assert data == once
    assert publish_guard.find_style_gate_hits(data["archive"]) == []


def _pundits(title=TITLE_617):
    return {"pundits": [{"id": 585, "name": "Vincent Deluard", "slug": "vincent-deluard", "mention_score": 1,
                         "last_episode_title": title, "last_main_idea": TAKE_OLD,
                         "last_proof_snippet": "Probably two, third of US stocks are trading video data to only day moving average.",
                         "last_proof_cite": "Monetary Matters with Jack Farley • 2026-10-27 • " + TITLE_617,
                         "supporting_takeaway": "Deluard says consumer stocks are showing extreme stress."}]}


def test_pundit_585():  # fixes 1 and 5
    rows = _pundits()
    export_data._apply_summary_overrides(rows)
    p = rows["pundits"][0]
    assert p["last_main_idea"] == TAKE_NEW
    assert "last_proof_snippet" not in p and "last_proof_cite" not in p
    assert p["supporting_takeaway"] == "Deluard says consumer stocks are showing extreme stress."
    once = copy.deepcopy(rows)
    export_data._apply_summary_overrides(rows)
    assert rows == once


def test_pundit_585_gate_holds_for_new_episode():
    rows = _pundits(title="A later Deluard episode")
    export_data._apply_summary_overrides(rows)
    assert rows["pundits"][0]["last_proof_snippet"].startswith("Probably two")


OVERTON_616 = {317: "Sub-agents", 299: "Pacing the Frontier", 285: "Loops", 270: "Taste", 97: "Distillation", 161: "AGI"}


def _overton(ep=616):
    rows = [{"id": i, "term": t, "last_mentioned_episode_id": ep, "last_mentioned_speaker": "Caitlin, Angela, Kaitlyn"}
            for i, t in OVERTON_616.items()]
    return {"overton": rows, "overton_recent": copy.deepcopy(rows[1:2]), "overton_established": copy.deepcopy(rows[-1:])}


def test_overton_speakers_616():  # fix 10 (161 is on the homepage: overton_established)
    c = _overton()
    export_data._apply_overton_term_overrides(c)
    for k in ("overton", "overton_recent", "overton_established"):
        assert all(t["last_mentioned_speaker"] == "Katelyn Lesse, Angela Jiang" for t in c[k]), k
    once = copy.deepcopy(c)
    export_data._apply_overton_term_overrides(c)
    assert c == once
    c = _overton(ep=1616)  # a later mention keeps its own speaker
    export_data._apply_overton_term_overrides(c)
    assert all(t["last_mentioned_speaker"] == "Caitlin, Angela, Kaitlyn" for t in c["overton"])


def test_archive_json_gets_overton_616_rules(tmp_path):
    (tmp_path / "archive.json").write_text(json.dumps({"overton": _overton()["overton"]}))
    export_data._apply_summary_overrides_to_files(tmp_path)
    got = json.loads((tmp_path / "archive.json").read_text())
    assert {t["id"]: t["last_mentioned_speaker"] for t in got["overton"]} == {i: "Katelyn Lesse, Angela Jiang" for i in OVERTON_616}


# --- general rule: sponsor tickers -------------------------------------------------------------

def test_sponsor_tickers_config():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())
    assert "LENS" in rules["sponsor_tickers"]


def test_sponsor_tickers_dropped_everywhere_but_price_snapshot_and_free_text():
    text = "Seen through a macro lens, LENS and Lens Technology are discussed."
    data = {
        "priceSnapshot": {"LENS": {"price": 43.68}},
        "tickerScores": {"LENS": {"score": 1}},
        "archive": {"insights": [
            {"id": 5001, "podcast_episode_id": 5001, "title": "New Monetary Matters ep", "summary": text,
             "tickers_mentioned": ["LENS", "TLT"], "key_tickers": ["lens", "TLT"]},
            {"id": 5002, "podcast_episode_id": 5002, "title": "Other show", "tickers_mentioned": '["NVDA", "LENS"]'}]},
        "mainContent": {"insights": [{"id": 5001, "podcast_episode_id": 5001, "title": "New Monetary Matters ep",
                                      "tickers_mentioned": json.dumps(["LENS"])}]},
        "deepDives": {"5001": {"id": 5000, "insight_id": 5001, "podcast_episode_id": 5001, "insight_title": "x",
                               "overview": text, "key_tickers": ["LENS", "TLT"],
                               "ticker_analysis": {"LENS": {"rationale": "LENS sponsor"}, "TLT": {"rationale": "duration"}}}},
        "eps": [{"id": 5001, "podcast_name": "Monetary Matters with Jack Farley", "episode_title": "New", "key_tickers": ["LENS"]}],
    }
    _apply(data)
    a = {c["id"]: c for c in data["archive"]["insights"]}
    assert a[5001]["tickers_mentioned"] == ["TLT"] and a[5001]["key_tickers"] == ["TLT"]
    assert a[5002]["tickers_mentioned"] == ["NVDA"]
    assert data["mainContent"]["insights"][0]["tickers_mentioned"] == []
    dd = data["deepDives"]["5001"]
    assert dd["key_tickers"] == ["TLT"] and list(dd["ticker_analysis"]) == ["TLT"]
    assert data["eps"][0]["key_tickers"] == []
    # untouched: price data and ordinary text ('lens' is an English word)
    assert data["priceSnapshot"] == {"LENS": {"price": 43.68}}
    assert data["tickerScores"] == {"LENS": {"score": 1}}
    assert a[5001]["summary"] == text and dd["overview"] == text
    once = copy.deepcopy(data)
    _apply(data)
    assert data == once


def test_per_id_lens_rules_still_work():
    """The 10/27 per-id rules (617, 560, 569, 600, 622) stay in place and still hold."""
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["summaries"]
    have = {(r.get("insight_id"), r.get("podcast_episode_id")) for r in rules if "LENS" in (r.get("drop_tickers") or [])}
    assert {(617, 608), (560, 544), (569, 559), (600, 589), (622, 611), (627, 617)} <= have


def test_site_files_after_publish():
    """Once the site export re-runs, the published JSON carries every fix (skips before then)."""
    import pytest
    arch = json.loads((ROOT / "site" / "data" / "archive.json").read_text())
    ins = {c["id"]: c for c in arch.get("insights", [])}
    if 627 not in ins or "Treasure the next" in json.dumps(ins[627]):
        pytest.skip("site export not yet re-run with the 10/28 rules")
    assert ins[627]["key_takeaway"].startswith("Favor Treasuries over equities for the next 6 months")
    assert ins[627]["sentiment"] == "bearish" and "LENS" not in ins[627]["tickers_mentioned"]
    s = json.dumps(arch, ensure_ascii=False)
    for bad in ("Pam highlights", "Caitlin", "129%", "4,000 skews", "Ship a two a research hospital",
                "the Fed being of hiking cycle", "Trillion 12 month revenue"):
        assert bad not in s, bad
