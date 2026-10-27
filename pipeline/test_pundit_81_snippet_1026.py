"""Oct 26 2026 routine quote fix: Elon Musk (pundit 81) had a last_proof_snippet that was the
garbled All-In host intro ("...Yeah, five years went by so quickly with us today. David Sacks is
back."), not his words. The pundit_overrides rule unsets the snippet and its cite on every export."""
import json
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
SNIPPET = ("Actually, we actually were number one good as a literal thing. I'm for one last week only "
           "took a little bit of time to get me to five years only to five. Yeah, five years went by so "
           "quickly with us today. David Sachs is back.")
CITE = ("All-In with Chamath, Jason, Sacks & Friedberg \u2022 2026-10-17 \u2022 CoreWeave Crash, AI "
        "Trade Cracks, Anthropic IPO Red Flags, Bill Gates Doomer")


def _row(pid, name, **kw):
    row = {"id": pid, "slug": name.lower().replace(" ", "-"), "name": name, "mention_score": 4}
    row.update(kw)
    return row


def test_rule_unsets_snippet_and_cite():
    rules = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["pundit_overrides"]
    r81 = [r for r in rules if r["id"] == 81]
    assert r81 and {"last_proof_snippet", "last_proof_cite"} <= set(r81[0].get("unset") or [])


def test_pundit_81_has_no_snippet_after_overrides():
    other = _row(96, "Other Person", last_proof_snippet="A real quote.", last_proof_cite="Pod \u2022 2026-10-01 \u2022 Ep")
    rows = [_row(81, "Elon Musk", last_proof_snippet=SNIPPET, last_proof_cite=CITE,
                 last_podcast_name="All-In with Chamath, Jason, Sacks & Friedberg"), other]
    data = {"pundits": rows}
    export_data._apply_summary_overrides(data)
    by_id = {p["id"]: p for p in data["pundits"]}
    musk = by_id[81]
    assert not musk.get("last_proof_snippet")
    assert not musk.get("last_proof_cite")
    assert "David Sacks is back" not in json.dumps(musk) and "David Sachs is back" not in json.dumps(musk)
    assert musk["last_podcast_name"] == "All-In with Chamath, Jason, Sacks & Friedberg"  # rest kept
    assert by_id[96]["last_proof_snippet"] == "A real quote."  # other pundits untouched


def test_site_files_have_no_pundit_81_snippet():
    pund = {p["id"]: p for p in json.loads((ROOT / "site" / "data" / "pundits.json").read_text())}
    if 81 in pund:
        assert not pund[81].get("last_proof_snippet")
        assert not pund[81].get("last_proof_cite")
    assert "David Sacks is back" not in (ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8")
