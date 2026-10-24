"""Oct 23 2026 G(ai)ndolf sweep (cos/sweep_1023/fixes.md): 10 fixes re-apply on export from pre-fix files."""
import json, subprocess
from pathlib import Path
import pytest
import export_data
import db_manager

ROOT = Path(__file__).resolve().parent.parent
PRE = "78bc897"
OLD = ["Vincent Gave\u2019s \u201cthree seas", "Gave also pushes", "Louis-Vincent Gav ", "Louis-Vincent Gav:",
       "Patrick highlights", "Jamoth", "Habatilla", "gender of AI wave", "20, 20, 7",
       "encrypted hardlist"]


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


def _fix(path):
    obj = _old(path)
    out = export_data._apply_summary_overrides(obj)
    return out if out is not None else obj


def _cards(obj):
    return obj.get("insights", obj) if isinstance(obj, dict) else obj


@pytest.mark.parametrize("path", ["site/data/archive.json", "site/data/podcast_summaries.json",
                                  "site/data/pundits.json"])
def test_old_strings_gone(path):
    text = json.dumps(_fix(path), ensure_ascii=False)
    for s in OLD:
        assert s not in text, f"{s!r} survived re-export of {path}"
    assert "Louis-Dr. Anas" not in text


def test_card_613_speakers_and_summary():
    c = [x for x in _cards(_fix("site/data/archive.json")) if x.get("id") == 613][0]
    assert "Dr. Anas Alhajji\u2019s \u201cthree seas\u201d" in c["summary"]
    assert "Alhajji also pushes a contrarian energy view" in c["summary"]
    assert "Louis-Vincent Gave frames France" in c["summary"]
    assert "Patrick Ceresna highlights" in c["summary"]
    sp = [q["speaker"] for q in c["notable_quotes"]]
    assert sp == ["Dr. Anas Alhajji", "Dr. Anas Alhajji", "Louis-Vincent Gave"]


def test_cards_615_608_611_606():
    cards = {x.get("id"): x for x in _cards(_fix("site/data/archive.json"))}
    j = json.dumps(cards[615], ensure_ascii=False)
    assert "In the first three years of this [generative] AI wave, our AI business in AWS is over $25 billion in run rate." in j
    assert "just a 2027 issue" in j and cards[615]["sentiment"] == "bullish"
    assert "if you have encrypted [data] today that gets stolen" in json.dumps(cards[608])
    assert not {"MOSHI", "NASA"} & set(cards[611].get("tickers_mentioned") or [])
    assert "AMP" not in (cards[606].get("tickers_mentioned") or [])
    assert "Chamath Palihapitiya" in json.dumps(cards[609], ensure_ascii=False)


def test_pundits_merged_and_clips_removed():
    rows = _fix("site/data/pundits.json")
    rows = rows if isinstance(rows, list) else rows.get("pundits", [])
    by = {r["id"]: r for r in rows}
    for gone in (574, 575, 565, 566, 567):
        assert gone not in by
    assert 568 in by and by[568]["name"] == "Kevin Fischer"
    assert by[236]["last_episode_date"] == "2026-10-22" and "France" in by[236]["supporting_takeaway"]
    assert by[55]["last_episode_date"] == "2026-10-22" and "Alhajji" in by[55]["supporting_takeaway"]
    assert "MacroVoices #554" in by[236]["last_proof_cite"] and "MacroVoices #554" in by[55]["last_proof_cite"]


def test_guest_names():
    g = json.loads((ROOT / "pipeline/guest_overrides.json").read_text())["insight_guest_by_id"]
    assert g["615"] == "Andy Jassy" and g["614"] == "Erik Bernhardsson"


def test_floor_demoted_and_filtered():
    dem = json.loads((ROOT / "site/data/overton_demote.json").read_text())["demote"]
    assert any(d["term"] == "floor" and d.get("id") == 313 for d in dem)
    rows = [{"term": "floor", "novelty_score": 3.1, "mention_count": 8},
            {"term": "Superintelligence", "novelty_score": 2.9, "mention_count": 13},
            {"term": "Return to Tangibles", "novelty_score": 2.6, "mention_count": 6},
            {"term": "HBM", "novelty_score": 2.5, "mention_count": 5}]
    out = db_manager.select_recent_overton_candidates(rows, [], limit=2)
    assert [r["term"] for r in out] == ["Superintelligence", "Return to Tangibles"]


def test_brazil_notes():
    t = (ROOT / "site/debate_history.json").read_text()
    assert "scheduled for Oct 4, 2026" not in t and "Brazil's first round was held Oct 4, 2026" in t
