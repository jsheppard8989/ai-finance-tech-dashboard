"""Oct 23 2026 full sweep (cos/sweep_1023_full/fixes.md): routine fixes re-apply on export from pre-fix files."""
import json, re, subprocess
from pathlib import Path
import pytest
import export_data

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PRE = "193ae4e"  # origin/main before this sweep


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


def _fix(path):
    obj = _old(path)
    out = export_data._apply_summary_overrides(obj)
    return out if out is not None else obj


def _by_name(pundits):
    return {p.get("id"): p for p in pundits}


def test_proof_quotes_replaced_and_musk_untouched():
    old = _by_name(_old("site/data/pundits.json"))
    new = _by_name(_fix("site/data/pundits.json"))
    text = json.dumps(list(new.values()), ensure_ascii=False)
    for bad in ("brought you by Sarmaya Partners", "Silicon Valley, Royalty, Legendary Investor",
                "a new threat merged in the world of photography", "neurodiverse routing"):
        assert bad not in text
    assert new[96]["last_proof_snippet"].startswith("You can't separate capability")
    assert "joined OpenRouter's Alex Atallah" in new[180]["last_main_idea"]
    musk = [i for i, p in new.items() if "Musk" in (p.get("name") or "")]
    for n in musk:  # G: leave Musk's guest count alone
        assert new[n].get("mention_score") == old[n].get("mention_score")
        if n == 81:  # Oct 26 2026 quote fix: the All-In host intro is unset, not Musk's words
            assert "last_proof_snippet" not in new[n]
        else:
            assert new[n].get("last_proof_snippet") == old[n].get("last_proof_snippet")


def test_proof_quotes_are_verbatim_from_source():
    """Every non-empty replacement snippet must be a notable quote in the source data (no invented quotes)."""
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["pundit_overrides"]
    corpus = json.dumps(_old("site/data/archive.json"), ensure_ascii=False) + \
        json.dumps(_old("site/data/podcast_summaries.json"), ensure_ascii=False)
    for r in rules:
        if "full sweep" not in r.get("_note", ""):
            continue
        for old, new in r.get("replacements", []):
            if new and new.endswith((".", "?", "!")) and len(new) > 20 and not new.startswith(("Josh Elman", "Amjad Masad", "Gurley")):
                assert json.dumps(new, ensure_ascii=False)[1:-1] in corpus, new[:60]


def test_summary_and_gloss_fixes():
    text = json.dumps(_fix("site/data/archive.json"), ensure_ascii=False)
    assert "RBAC (role-based access control)" in text
    assert "S-1 (IPO filing)" in text
    assert "the total transfer would be about $10.5 billion" not in text


def test_return_to_tangibles_dropped_from_overton():
    demote = json.loads((SITE / "data" / "overton_demote.json").read_text())
    terms = [str(d.get("term", "")).lower() for d in demote["demote"]]
    assert "return to tangibles" in terms
    main = {"overton": [{"term": "Return to Tangibles"}, {"term": "Compute glut"}]}
    export_data._apply_overton_term_overrides(main)
    assert [t["term"] for t in main["overton"]] == ["Compute glut"]


def test_dead_x_handles_removed():
    cs = (SITE / "data" / "curated_sources.json").read_text()
    for h in ("FedGuy12", "biotechscooper", "SamRines", "crossabordr"):
        assert f"x.com/{h}" not in cs and f"twitter.com/{h}" not in cs


def test_debait_and_dc_buildout_wording():
    deb = (SITE / "debait.html").read_text()
    assert "Shared voting backend coming" not in deb and "--mark-resolved" not in deb and "6AIndolf" not in deb
    assert "resolvedExpiryText" in deb
    dc = (SITE / "dc-buildout.html").read_text()
    assert "IN LINE" in dc and "$135–145B" in dc and "not yet reviewed" not in dc  # cut in sweep 10/25 round 2
    assert "Meta-Reports-Third-Quarter-2026-Results" in dc
    assert "John Galt" not in dc and "automated reader" not in dc
    for page in SITE.glob("*.html"):
        assert "why-gpu-prices-matter" not in page.read_text()
    idx = (SITE / "index.html").read_text()
    assert "dc-buildout" not in idx  # G: not in nav


def test_compute_card_source_line_unchanged():
    idx = (SITE / "index.html").read_text()
    assert "SemiAnalysis, AI Compute Tracker" in idx
