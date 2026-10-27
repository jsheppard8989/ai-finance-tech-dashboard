"""Oct 26 2026 routine quote fixes: host-intro proof snippets that are not the pundit's words.

- #81 Elon Musk: garbled All-In host intro ("...David Sacks is back."). The rule is gated with
  'when' on last_episode_title, so only that episode's snippet/cite are unset.
- #333 Dylan Patel, #418 Anish Acharya, #226 Warren Pies: host intros; unconditional id-keyed
  unset of last_proof_snippet + last_proof_cite, whatever text the next export produces."""
import json
from pathlib import Path

import export_data

ROOT = Path(__file__).resolve().parent.parent
MUSK_EP = "CoreWeave Crash, AI Trade Cracks, Anthropic IPO Red Flags, Bill Gates Doomer"
SNIPPET = ("Actually, we actually were number one good as a literal thing. I'm for one last week only "
           "took a little bit of time to get me to five years only to five. Yeah, five years went by so "
           "quickly with us today. David Sachs is back.")
CITE = "All-In with Chamath, Jason, Sacks & Friedberg \u2022 2026-10-17 \u2022 " + MUSK_EP
HOSTS = {333: "Dylan Patel", 418: "Anish Acharya", 226: "Warren Pies"}
ALL = {81: "Elon Musk", **HOSTS}


def _row(pid, name, **kw):
    row = {"id": pid, "slug": name.lower().replace(" ", "-"), "name": name, "mention_score": 4}
    row.update(kw)
    return row


def _rules():
    return json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text())["pundit_overrides"]


def test_rules_unset_snippet_and_cite():
    for pid in ALL:
        rs = [r for r in _rules() if r["id"] == pid and r.get("unset")]
        assert len(rs) == 1, pid
        assert {"last_proof_snippet", "last_proof_cite"} <= set(rs[0]["unset"]), pid
        if pid == 81:
            assert rs[0]["when"] == {"last_episode_title": MUSK_EP}
        else:
            assert "when" not in rs[0], pid  # holds whatever the next export produces


def test_no_snippet_after_overrides():
    rows = [_row(81, "Elon Musk", last_episode_title=MUSK_EP, last_proof_snippet=SNIPPET, last_proof_cite=CITE,
                 last_podcast_name="All-In with Chamath, Jason, Sacks & Friedberg")]
    rows += [_row(pid, n, last_episode_title="Any new episode", last_proof_snippet="Welcome back, any text at all.",
                  last_proof_cite="Pod \u2022 2026-10-27 \u2022 Any new episode") for pid, n in HOSTS.items()]
    rows.append(_row(96, "Other Person", last_proof_snippet="A real quote.", last_proof_cite="Pod \u2022 2026-10-01 \u2022 Ep"))
    data = {"pundits": rows}
    export_data._apply_summary_overrides(data)
    by_id = {p["id"]: p for p in data["pundits"]}
    for pid in ALL:
        assert not by_id[pid].get("last_proof_snippet"), pid
        assert not by_id[pid].get("last_proof_cite"), pid
    assert "is back" not in json.dumps(by_id[81])
    assert by_id[81]["last_podcast_name"] == "All-In with Chamath, Jason, Sacks & Friedberg"  # rest kept
    assert by_id[96]["last_proof_snippet"] == "A real quote."  # other pundits untouched


def test_musk_rule_skips_a_later_episode():
    row = _row(81, "Elon Musk", last_episode_title="Some Later Episode", last_proof_snippet="Musk's real words.",
               last_proof_cite="Pod \u2022 2026-11-01 \u2022 Some Later Episode")
    data = {"pundits": [row]}
    export_data._apply_summary_overrides(data)
    assert data["pundits"][0]["last_proof_snippet"] == "Musk's real words."
    assert data["pundits"][0]["last_proof_cite"].endswith("Some Later Episode")


def test_when_gate_requires_every_field():
    rule = {"id": 7, "when": {"a": 1, "b": 2}, "unset": ["x"]}
    hit, miss = {"id": 7, "slug": "p", "name": "P", "mention_score": 1, "a": 1, "b": 2, "x": 1}, \
        {"id": 7, "slug": "q", "name": "Q", "mention_score": 1, "a": 1, "b": 3, "x": 1}
    export_data._apply_pundit_rules([hit], [], [rule])
    export_data._apply_pundit_rules([miss], [], [rule])
    assert "x" not in hit and miss["x"] == 1


def test_site_files_have_no_snippets():
    pund = {p["id"]: p for p in json.loads((ROOT / "site" / "data" / "pundits.json").read_text())}
    for pid in ALL:
        if pid in pund:
            assert not pund[pid].get("last_proof_snippet"), pid
            assert not pund[pid].get("last_proof_cite"), pid
    assert "David Sacks is back" not in (ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8")
