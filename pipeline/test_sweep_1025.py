"""Oct 25 2026 sweep (cos/sweep_1025/fixes.md): routine name/ticker/wording fixes re-apply on export."""
import copy, json, subprocess
from pathlib import Path
import pytest
import export_data

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PRE = "7890c586"  # origin/main before this sweep


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


def _fix(obj):
    out = export_data._apply_summary_overrides(obj)
    return out if out is not None else obj


def test_names_fixed_in_archive_and_pundits():
    arch = json.dumps(_fix(_old("site/data/archive.json")), ensure_ascii=False)
    pund = json.dumps(_fix(_old("site/data/pundits.json")), ensure_ascii=False)
    for bad in ("Grace One", "Garing and Rozencwajg", "Michiel Buduma", "VERN"):
        assert bad not in arch
    assert "Gray Swan" in arch and "Goehring & Rozencwajg" in arch
    assert "Nikhil Buduma, co-founder and chief scientist of Ambience Healthcare" in arch
    for bad in ("Garing", "Poladian", "Daria Amade", "Basman", "Anankumar"):
        assert bad not in pund
    # item 11 cut #489's host-intro snippet (the only "Ben Poladian" text), so it is no longer checked here
    for good in ("Dario Amodei, CEO of Anthropic", "Harley Bassman", "Anandkumar emphasizes"):
        assert good in pund


def _deep(dive, field):
    v = dive[field]
    return json.loads(v) if isinstance(v, str) and v[:1] in "[{" else v


def test_deep_dive_fixes_from_raw_text():
    """Per-card rules work on raw DB text (before the 'thin' global swaps) as well as on exported text."""
    dives = {
        "618": {"insight_id": 618, "podcast_episode_id": 607, "insight_title": "x",
                "investment_thesis": "separate AI beneficiaries into three buckets: a, b, c. The episode suggests the second bucket is still thin, while the third bucket is driving demand."},
        "620": {"insight_id": 620, "podcast_episode_id": 609, "insight_title": "y",
                "catalysts": ["Over the next 2 years: product launches from incumbents that either confirm the moat thesis through rapid adaptation or expose thin-wrapper vulnerability."],
                "falsification_tracks": ["By 2027-12-31, if at least 3 leading AI application categories are dominated by thin wrapper products with no meaningful proprietary data layer and still maintain >60% gross retention, the thesis is weakened."]},
        "313": {"insight_id": 313, "podcast_episode_id": 297, "insight_title": "z", "key_tickers": ["CAT", "VERN"],
                "ticker_analysis": {"VNR": {"rationale": "Vernova, with its nearly $90 billion order backlog, is well-positioned."}}},
    }
    raw = copy.deepcopy(dives)
    _fix(raw)
    t = raw["618"]["investment_thesis"]
    assert "three groups:" in t and "the second group is still small, while the third group is driving" in t
    assert "expose the risk to simple add-on apps built on others' AI models." in raw["620"]["catalysts"][0]
    assert "dominated by simple add-on apps with no data of their own and still maintain" in raw["620"]["falsification_tracks"][0]
    assert raw["313"]["key_tickers"] == ["CAT", "GEV"]
    ta = _deep(raw["313"], "ticker_analysis")
    assert list(ta) == ["GEV"] and ta["GEV"]["rationale"].startswith("GE Vernova, with")
    for d in raw.values():
        assert " thin" not in json.dumps(d) and "thin-" not in json.dumps(d)


def test_site_data_has_no_old_forms():
    text = (SITE / "data" / "data.js").read_text(encoding="utf-8")
    for bad in ("Grace One", "Garing and Rozencwajg", "Michiel Buduma", "Borenstein", "Cobounder",
                "Poladian", "Daria Amade", "Basman", "Anankumar", '"VNR"', '"VERN"', "simple-wrapper vulnerability"):
        assert bad not in text, bad
    assert "the episode with Lassie's co-founders".lower() in text.lower()


def test_dc_buildout_capex_and_passed_pjm_row():
    html = (SITE / "dc-buildout.html").read_text(encoding="utf-8")
    assert "2026 capex (capital spending) guide" in html
    assert "PJM members' meeting (held; outcome not yet reviewed)" not in html
