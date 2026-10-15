"""Regression tests for the Oct 15 2026 card 587/588 fixes (durable through re-export)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

INKER = "The AI Bubble Will Pop from Equity Supply Says This $80 Billion Asset Manager | Ben Inker | GMO"
LAMBERT = "Can Open Models Keep Up With the AI Frontier? | Nathan Lambert"
DATA = Path(__file__).parent.parent / "site" / "data"


def test_add_key_tickers_card_scoped_and_idempotent():
    rec = {"title": INKER, "key_tickers": ["NVDA", "TSM"], "tickers_mentioned": "[\"NVDA\"]"}
    other = {"title": "Other", "key_tickers": ["NVDA"]}
    export_data._apply_summary_overrides([rec, other])
    export_data._apply_summary_overrides([rec, other])
    assert rec["key_tickers"] == ["NVDA", "TSM", "SMCI"]
    assert rec["tickers_mentioned"] == "[\"NVDA\"]"
    assert other["key_tickers"] == ["NVDA"]
    assert export_data._add_key_tickers('["A"]', ["B", "a"]) == '["A", "B"]'


def test_inker_text_fixes_idempotent():
    rec = {
        "title": INKER,
        "summary": 'passive ownership, closet indexing, and more. if the world becomes a "wash" in compute',
        "notable_quotes": [{"speaker": "Ben Inker", "quote": "if now the world is suddenly a wash in compute, we"}],
    }
    for _ in range(2):
        export_data._apply_summary_overrides([rec])
    assert rec["summary"].count("closet indexing (active funds that mostly track the index)") == 1
    assert "becomes awash in compute" in rec["summary"]
    assert "suddenly awash in compute" in rec["notable_quotes"][0]["quote"]


def test_lambert_trillium_no_double_labs():
    rec = {"title": LAMBERT, "summary": "The episode also introduces Trillium, Lambert\u2019s lab. Lambert says Trillium will"}
    for _ in range(3):
        export_data._apply_summary_overrides([rec])
    assert "Labs Labs" not in rec["summary"]
    assert rec["summary"].count("Trillium Labs") == 2


def test_term_rename_compute_glut():
    terms = [{"id": 902, "term": "Compute wash", "definition": "keep"}]
    export_data._apply_term_overrides(terms)
    assert terms[0] == {"id": 902, "term": "Compute glut", "definition": "keep"}


def test_guest_overrides_name_and_bio():
    mc = {"insights": [{"id": 588, "guest_name": None}]}
    guests = [{"name": "Nathan Lambert", "bio": None, "known_for": None}, {"name": "X Y", "bio": None}]
    mc, guests = export_data._apply_guest_export_overrides(mc, guests)
    assert mc["insights"][0]["guest_name"] == "Ben Inker"
    assert "co-founder of the nonprofit research lab Trillium Labs" in guests[0]["bio"]
    assert guests[1]["bio"] is None
    kept = [{"name": "Nathan Lambert", "bio": "curated elsewhere"}]
    export_data._apply_guest_bio_overrides(kept)
    assert kept[0]["bio"] == "curated elsewhere"


def test_site_data_has_fixes():
    js = (DATA / "data.js").read_text(encoding="utf-8")
    for s in ("awash in compute", "Compute glut", "Trillium Labs", '"SMCI"', '"guest_name": "Ben Inker"'):
        assert s in js, s
    for name in ("data.js", "archive.json", "podcast_summaries.json", "pundits.json"):
        t = (DATA / name).read_text(encoding="utf-8")
        for bad in ("a wash in compute", "market gap that comes in", "let's 24% worse", "Compute wash",
                    "Trillium Labs Labs", "soon to be anthropic", "RL-heavy post-training", "fast-takeoff dynamic"):
            assert bad not in t, (name, bad)
