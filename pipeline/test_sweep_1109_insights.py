"""Nov 9 2026 G daily check (cos/sweep_1109/daily_check_fixes.md): durable export
overrides for Insights 657/658/659/660/661/662/663/664 (names, Claude, Shanghai cut,
ticker drops, optional glosses). Same card-scoped pattern as #778/#779."""
from __future__ import annotations

import json
import re
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
OV = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())

BANNED_RE = re.compile(r"(?<![\w-])(bet|bets|betting|grade|graded|grading)(?![\w-])", re.I)

SUM661 = (
    "Praveer Mulwani argues that AI is changing finance from a backward-looking "
    "“traffic cop” into a forward-looking business enabler.\n\n"
    "Mulwani repeatedly stresses that AI should augment, not replace, human judgment."
)
SUM660 = (
    "Patrick Suresna adds a tactical trade idea in Marathon Petroleum (MPC), arguing "
    "the stock’s sharp sell-off may have overshot. He proposes a December 18, 2026 "
    "390/450 bull call spread. He also treats gold’s move."
)
SUM658 = (
    "Diamandis cites Life Val and GDPX benchmarks to argue that AI is improving, "
    "and he points to Anthropic’s internal metrics—cloud allegedly writing more than "
    "90% of September code—as evidence."
)
SUM662 = (
    "The guest says Shanghai brought the event to Shanghai, not the reverse, and "
    "emphasizes that the conference is scaling through a franchise-like model."
)
SUM659 = (
    "He frames current non-investment-grade private credit yields as roughly SOFR plus "
    "475 to 575 basis points, with the illiquidity premium generally around 150 to 250 "
    "basis points. He also notes that yields were wider in 2023, when normal transactions "
    "could reach SOFR plus 600 basis points. He also makes the case that CLOs remain the "
    "bedrock of the leveraged loan market, with demand likely north of 70% today, up from "
    "around 50% pre-GFC and 60% to 70% around 2020."
)
KT659 = (
    "Private credit remains attractive because Baskind expects today’s illiquidity premium "
    "and SOFR-plus yields to stay compelling while disciplined underwriting and CLO demand "
    "support returns."
)
SUM663 = (
    "saying the pace was increased on August 18 from roughly $64 billion per year to about "
    "$192 billion per year for 20s and 30s, and that the QRA maintained that pace."
)
SUM664 = (
    "venture markets have become faster and more structured around multi-tranche financings, "
    "with secondary tranches now often pricing at 3x to 5x instead of the 2x fast-follow "
    "pattern. companies need capital staged across primary and secondary tranches rather "
    "than all up front. match compute financing with the scale and risk of private "
    'frontier-model builders, or "neo labs." He suggests the industry may need new capital.'
)


def _payload():
    return {
        "insights": [
            {
                "id": 661,
                "insight_id": 661,
                "podcast_episode_id": 648,
                "title": "The New CFO: How AI Is Rewriting the Finance Function | Figma CFO Praveer Melwani",
                "summary": SUM661,
                "tickers_mentioned": ["FIG", "COIN"],
                "notable_quotes": [
                    {"speaker": "Praveer Mulwani", "quote": "Collections work flows are automated."}
                ],
            },
            {
                "id": 660,
                "insight_id": 660,
                "podcast_episode_id": 649,
                "title": "MacroVoices #557 Michael Every: The Blue Tsunami Lands on Markets... and Geopolitics",
                "summary": SUM660,
                "tickers_mentioned": ["MPC"],
                "notable_quotes": [
                    {"speaker": "Patrick Suresna", "quote": "With mpc trading around $392."}
                ],
            },
            {
                "id": 658,
                "insight_id": 658,
                "podcast_episode_id": 646,
                "title": "Big Tech’s $3T AI Bet, Claude Writes 90% of Anthropic’s Code | EP #308",
                "summary": SUM658,
                "tickers_mentioned": ["GOOGL", "META", "AAPL"],
            },
            {
                "id": 662,
                "insight_id": 662,
                "podcast_episode_id": 651,
                "title": "Behind Latent Space: A Rare Look Inside the Pod | AIEi Shanghai",
                "summary": SUM662,
                "tickers_mentioned": ["DOCU", "AMZN"],
            },
            {
                "id": 657,
                "insight_id": 657,
                "podcast_episode_id": 647,
                "title": "Why This Short Seller Doesn’t Want to Short the AI Bubble | Russell Clark",
                "summary": "Russell Clark argues AI capex is still funded; he likes Apple.",
                "tickers_mentioned": ["ORCL", "AAPL"],
            },
            {
                "id": 659,
                "insight_id": 659,
                "podcast_episode_id": 650,
                "title": "Invesco’s Private Credit CIO Eyes ‘Equity-Like’ Returns in Loans",
                "summary": SUM659,
                "key_takeaway": KT659,
                "tickers_mentioned": [],
            },
            {
                "id": 663,
                "insight_id": 663,
                "podcast_episode_id": 652,
                "title": "Growth Expectations Are Probably Too High | Andy Constan on QRA",
                "summary": SUM663,
                "tickers_mentioned": ["MSFT"],
            },
            {
                "id": 664,
                "insight_id": 664,
                "podcast_episode_id": 654,
                "title": "Ramtin Naimi on the State of Venture Investing",
                "summary": SUM664,
                "tickers_mentioned": [],
            },
        ],
        "podcastGuests": [
            {
                "id": 616,
                "name": "Praveer Mulwani",
                "slug": "praveer-mulwani",
                "last_proof_snippet": "Mulwani frames the organizational change as moving finance forward.",
            }
        ],
    }


def _by_id(d):
    return {c["id"]: c for c in d["insights"]}


def test_overrides_present():
    by = {
        r["insight_id"]: r
        for r in OV["summaries"]
        if r.get("insight_id") in {657, 658, 659, 660, 661, 662, 663, 664}
        and "sweep_1109" in (r.get("_note") or "")
        or (
            r.get("insight_id") == 658
            and r.get("podcast_episode_id") == 646
            and any("cloud allegedly" in a for a, _ in r.get("replacements") or [])
        )
    }
    # 658 may be the extended older rule
    r658 = next(
        r
        for r in OV["summaries"]
        if r.get("insight_id") == 658 and r.get("podcast_episode_id") == 646
    )
    assert any("cloud allegedly" in a for a, _ in r658["replacements"])
    assert any("Life Val and GDPX" in a for a, _ in r658["replacements"])

    r661 = next(r for r in OV["summaries"] if r.get("insight_id") == 661 and "sweep_1109" in r.get("_note", ""))
    assert r661["drop_tickers"] == ["COIN"]
    r662 = next(r for r in OV["summaries"] if r.get("insight_id") == 662 and "sweep_1109" in r.get("_note", ""))
    assert r662["drop_tickers"] == ["DOCU"]
    r657 = next(r for r in OV["summaries"] if r.get("insight_id") == 657 and "sweep_1109" in r.get("_note", ""))
    assert r657["drop_tickers"] == ["ORCL"]

    gn = {a: b for a, b in OV["global_name_replacements"]}
    assert gn["Praveer Mulwani"] == "Praveer Melwani"
    assert gn["Mulwani"] == "Melwani"
    assert gn["Patrick Suresna"] == "Patrick Ceresna"
    assert gn["Suresna"] == "Ceresna"


def test_transforms_live_text():
    d = _payload()
    export_data._apply_summary_overrides(d)
    by = _by_id(d)

    assert "Praveer Melwani argues" in by[661]["summary"]
    assert "Melwani repeatedly" in by[661]["summary"]
    assert "Mulwani" not in by[661]["summary"]
    assert by[661]["notable_quotes"][0]["speaker"] == "Praveer Melwani"
    assert by[661]["tickers_mentioned"] == ["FIG"]

    assert "Patrick Ceresna adds" in by[660]["summary"]
    assert "Suresna" not in by[660]["summary"]
    assert by[660]["notable_quotes"][0]["speaker"] == "Patrick Ceresna"
    assert "390/450 bull call spread (buying one call and selling a higher-strike call). He" in by[660]["summary"]

    assert "Claude allegedly writing more than 90%" in by[658]["summary"]
    assert "cloud allegedly" not in by[658]["summary"]
    assert "LifeVal and GDPx benchmarks" in by[658]["summary"]
    assert "Life Val" not in by[658]["summary"]

    assert "Shanghai brought the event to Shanghai" not in by[662]["summary"]
    assert "The guest emphasizes that the conference is scaling" in by[662]["summary"]
    assert by[662]["tickers_mentioned"] == ["AMZN"]

    assert by[657]["tickers_mentioned"] == ["AAPL"]

    assert "SOFR (the benchmark short-term lending rate) plus" in by[659]["summary"]
    assert "CLOs (collateralized loan obligations) remain" in by[659]["summary"]
    assert "pre-GFC (the 2008 global financial crisis)" in by[659]["summary"]
    assert "illiquidity premium (extra yield for hard-to-sell loans)" in by[659]["summary"]

    assert "20- and 30-year Treasuries" in by[663]["summary"]
    assert "for 20s and 30s" not in by[663]["summary"]

    assert "multi-tranche financings (capital raised in staged rounds)" in by[664]["summary"]
    assert "neo labs\" (new frontier AI model companies)" in by[664]["summary"]

    # global name also hits podcastGuests name + snippet; slug untouched
    assert d["podcastGuests"][0]["name"] == "Praveer Melwani"
    assert "Melwani frames" in d["podcastGuests"][0]["last_proof_snippet"]
    assert d["podcastGuests"][0]["slug"] == "praveer-mulwani"


def test_banned_words_on_touched():
    d = _payload()
    export_data._apply_summary_overrides(d)
    # Title of 658 contains "AI Bet" (exempt title field) — check body fields only
    for card in d["insights"]:
        body = " ".join(
            str(card.get(k) or "")
            for k in ("summary", "key_takeaway", "key_takeaways")
        )
        for q in card.get("notable_quotes") or []:
            if isinstance(q, dict):
                body += " " + str(q.get("quote") or "") + " " + str(q.get("speaker") or "")
        hits = [m.group(0) for m in BANNED_RE.finditer(body)]
        # "non-investment-grade" contains "grade" as substring — BANNED_RE uses word boundaries
        # so "investment-grade" hyphen may or may not match; filter genuine hits
        bad = [h for h in hits if h.lower() in {"bet", "bets", "betting", "grade", "graded", "grading"}]
        assert not bad, (card["id"], bad, body[:200])


def test_idempotent():
    d = _payload()
    export_data._apply_summary_overrides(d)
    once = json.dumps(d, sort_keys=True, ensure_ascii=False)
    export_data._apply_summary_overrides(d)
    assert json.dumps(d, sort_keys=True, ensure_ascii=False) == once
