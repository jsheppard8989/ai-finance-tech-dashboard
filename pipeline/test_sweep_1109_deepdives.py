"""Nov 9 2026 G review (cos/deepdive_drafts_1109/G_REVIEW.md): durable export overrides
for deep dives 636 / 638 / 669 (640 cleared as-is). Same card-scoped pattern as DD658
'capex intensity' (#769)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import export_data
import site_text_sanitize

ROOT = Path(__file__).resolve().parent.parent
OV = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())

FT636 = [
    "By Dec 31, 2026, New York State enacts at least 1 statute materially redirecting MTA Bridges and Tunnels toll revenues away from bond-protected purposes with under $1 billion of required bondholder compensation, graded by the NYS Senate bill database and MTA EMMA material event notices.",
    "In the FY2026 MTA Annual Comprehensive Financial Report, published by Jun 30, 2027, MTA Bridges and Tunnels senior-lien debt outstanding is below $5 billion and annual surplus transfers are below $500 million, grading whether the authority structure is still financially central.",
    "By Dec 31, 2027, at least 3 final federal or New York appellate decisions uphold legislative impairment of public-authority bond covenants without full monetary remedy to bondholders, graded by Westlaw and the U.S. Supreme Court docket.",
    "By Dec 31, 2028, fewer than 25% of the MTA capital program is funded by authority-issued debt or dedicated authority revenues, graded by the MTA 2025–2029 Capital Program amendment filings and official statements on EMMA.",
]
FT638_4 = (
    "By Mar 31, 2028, 90-day NPLs above 9% for Nubank's Brazil consumer finance portfolio "
    "while Brazil revenue growth is below 15% in Nubank's FY 2027 Form 20-F would show "
    "underwriting gains are not offsetting credit-cycle risk."
)
SUM638 = (
    "A major part of the episode is the claim that NuBank has already built an unusually "
    "powerful operating model. Vélez says NuBank has close to 120 million customers."
)
KT638 = "NuBank’s proprietary data scale and AI foundation model create a durable cost and underwriting advantage."
SUM669 = (
    "Peter Diamandis cites Goldman Sachs-style estimates that 45% of planned U.S. data-center "
    "buildout could face restrictions, and the speakers discuss the White House’s NSTM6 policy "
    "on synthetic DNA/RNA screening."
)
CAT669 = [
    "By Aug 31, 2026: hyperscaler FY2026 capex guidance revisions after Q2 earnings calls.",
    "By Dec 31, 2026: public announcements of Canadian AI data-center projects above 1 GW.",
    "By Dec 31, 2027: first commercial orbital compute contracts with disclosed customer workloads.",
]

BANNED_RE = re.compile(r"\b(bet|bets|betting|grade|graded|grading)\b", re.I)


def _payload():
    return {
        "deepDives": {
            "636": {
                "id": 636,
                "insight_id": 636,
                "podcast_episode_id": 624,
                "insight_title": "What I learned about power from LBJ and Robert Moses",
                "falsification_tracks": list(FT636),
            },
            "638": {
                "id": 638,
                "insight_id": 638,
                "podcast_episode_id": 627,
                "insight_title": "David Vélez - Building Nubank",
                "summary": SUM638,
                "key_takeaway": KT638,
                "falsification_tracks": [FT638_4],
            },
            "669": {
                "id": 669,
                "insight_id": 669,
                "podcast_episode_id": 658,
                "insight_title": "The Great Collision Between Politics and AI | #309",
                "summary": SUM669,
                "catalysts": list(CAT669),
            },
            "640": {
                "id": 640,
                "insight_id": 640,
                "podcast_episode_id": 629,
                "insight_title": "Andrew Huberman - The Frontier of Neurotechnology",
                "overview": "Cleared as written; no text swaps required.",
            },
        },
        "mainContent": {
            "insights": [
                {
                    "id": 638,
                    "podcast_episode_id": 627,
                    "title": "David Vélez - Building Nubank",
                    "summary": SUM638,
                    "key_takeaway": KT638,
                },
                {
                    "id": 669,
                    "podcast_episode_id": 658,
                    "title": "The Great Collision Between Politics and AI | #309",
                    "summary": SUM669,
                },
            ]
        },
    }


def test_636_grade_language_swapped():
    d = _payload()
    export_data._apply_summary_overrides(d)
    tracks = d["deepDives"]["636"]["falsification_tracks"]
    blob = "\n".join(tracks)
    assert "graded by" not in blob
    assert "grading" not in blob
    assert "checked against the NYS Senate bill database" in blob
    assert "showing whether the authority structure" in blob
    assert "checked against Westlaw" in blob
    assert "checked against the MTA 2025–2029" in blob


def test_638_nubank_and_npl_plain_english():
    d = _payload()
    export_data._apply_summary_overrides(d)
    dd = d["deepDives"]["638"]
    card = d["mainContent"]["insights"][0]
    for text in (dd["summary"], dd["key_takeaway"], card["summary"], card["key_takeaway"]):
        assert "NuBank" not in text
        assert "Nubank" in text
    assert "90-day NPLs" not in dd["falsification_tracks"][0]
    assert "loans more than 90 days late above 9%" in dd["falsification_tracks"][0]


def test_669_catalyst_dropped_and_summary_hedges_removed():
    d = _payload()
    export_data._apply_summary_overrides(d)
    dd = d["deepDives"]["669"]
    cats = dd["catalysts"]
    assert len(cats) == 2
    assert all("Aug 31, 2026" not in c for c in cats)
    assert "By Dec 31, 2026: public announcements of Canadian AI data-center projects above 1 GW." in cats
    s = dd["summary"]
    assert "Goldman Sachs-style" not in s
    assert "an estimate that 45%" in s
    assert "NSTM6" not in s
    assert "a White House policy on synthetic DNA/RNA screening" in s
    card = d["mainContent"]["insights"][1]["summary"]
    assert "Goldman Sachs-style" not in card and "NSTM6" not in card


def test_no_banned_words_in_four_after_overrides():
    d = _payload()
    export_data._apply_summary_overrides(d)
    for iid in ("636", "638", "640", "669"):
        blob = json.dumps(d["deepDives"][iid], ensure_ascii=False)
        hits = BANNED_RE.findall(blob)
        assert hits == [], (iid, hits)
        assert not site_text_sanitize.style_gate_hits(blob)


def test_rules_present_card_scoped():
    by = {r["insight_id"]: r for r in OV["summaries"] if "insight_id" in r}
    assert by[636]["podcast_episode_id"] == 624
    assert ["graded by Westlaw", "checked against Westlaw"] in by[636]["replacements"]
    assert by[638]["podcast_episode_id"] == 627
    assert ["NuBank", "Nubank"] in by[638]["replacements"]
    assert ["90-day NPLs", "loans more than 90 days late"] in by[638]["replacements"]
    assert by[669]["podcast_episode_id"] == 658
    assert ["Goldman Sachs-style estimates", "an estimate"] in by[669]["replacements"]
    assert "NSTM6" in by[669]["replacements"][1][0]
    assert "By Aug 31, 2026" in by[669]["drop_list_items"]["catalysts"][0]
    glob = [g[0] for g in OV.get("global_replacements") or []]
    assert "graded by Westlaw" not in glob
    assert "90-day NPLs" not in glob
    assert "Goldman Sachs-style estimates" not in glob


def test_idempotent():
    d = _payload()
    export_data._apply_summary_overrides(d)
    once = json.dumps(d, sort_keys=True, ensure_ascii=False)
    export_data._apply_summary_overrides(d)
    assert json.dumps(d, sort_keys=True, ensure_ascii=False) == once
