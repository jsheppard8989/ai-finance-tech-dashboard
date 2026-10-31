"""Oct 28 2026 plumbing fix (Wendy): Deep Dives for insights 616 / 625 / 628 were 'blocked' after 3
retries because deep_dive_structural_ok only accepted "Full Name:" speaker labels, while those
transcripts carry single names ("Pam:", "Dylan:") or a qualified name ("Ant (Supabase):").
Also: the 628 rule's "Pam:" -> "swyx:" label swap, and the read-only check_blocked_deepdives.py alert."""
import hashlib
import sqlite3
from datetime import datetime

import pytest

import check_blocked_deepdives as cbd
import export_data
from generate_deepdives import SPEAKER_LINE_RE, deep_dive_structural_ok

FALSIFIERS = [
    "If SK Hynix reports HBM inventory above 8 weeks in its Q3 2027 earnings release, the shortage thesis fails.",
    "If NVIDIA's datacenter share falls more than 5 points per Mercury Research by Dec 31, 2026, reassess positioning.",
    "If hyperscaler capex guidance in the 10-Q filings declines 2 quarters in a row by Q2 2027, the demand story weakens.",
]


def _content(evidence):
    return {
        "episode_evidence": evidence,
        "overview": "The semiconductor supply chain faces structural constraints that may persist through 2027 and beyond.",
        "investment_thesis": "Long exposure to capacity constrained suppliers offers asymmetric upside.",
        "falsification_tracks": list(FALSIFIERS),
    }


# ---- speaker check -------------------------------------------------------------------------

@pytest.mark.parametrize("evidence", [
    # 628 shape: diarized single first names, no bullets / quote marks
    "Pam: Over 50% of the people testing the new model said it was a step change in agentic coding.\n"
    "Caitlin: We spend most of our time making the Claude platform reliable for enterprise developers.",
    # 604 shape: one single-named guest, bulleted
    "- Dylan: The neoclouds that actually deliver good GPU clusters are a much shorter list than people think.\n"
    "- Dylan: Reliability and networking separate the platinum tier from everyone else in ClusterMAX.",
])
def test_single_name_labels_pass(evidence):
    ok, reason = deep_dive_structural_ok(_content(evidence))
    assert ok, reason


def test_qualified_name_label_passes():
    ev = ("Ant (Supabase): Postgres is becoming the default database that coding agents reach for first.\n"
          "Ant (Supabase): Most new projects on the platform are now created by an AI agent, not a person.")
    ok, reason = deep_dive_structural_ok(_content(ev))
    assert ok, reason


def test_full_name_labels_still_pass():
    ev = ("Jack Farley: Question from the host about market dynamics and the cycle.\n"
          "Patrick O'Shaughnessy: Another named quote with substantial content about compounding.")
    ok, reason = deep_dive_structural_ok(_content(ev))
    assert ok, reason
    ev2 = ('J Mintzmyer: "The oil must flow and this is a longer quote."\n'
           'J Mintzmyer: "This is another quote with sufficient length to count."')
    ok, reason = deep_dive_structural_ok(_content(ev2))
    assert ok, reason


@pytest.mark.parametrize("labels", [
    ("Host", "Guest"), ("Speaker", "Author"), ("Host (Latent Space)", "Guest (Supabase)"), ("Speaker (1)", "Speaker (2)"),
])
def test_generic_labels_do_not_count_as_named(labels):
    ev = (f"{labels[0]}: We see significant opportunity in the semiconductor space for 2027.\n"
          f"{labels[1]}: Risks remain elevated but manageable for long-term holders of the group.")
    ok, reason = deep_dive_structural_ok(_content(ev))
    assert not ok
    assert "name the speaker" in reason


def test_one_named_plus_generic_still_fails():
    ev = ("Host: We see significant opportunity in the semiconductor space for 2027.\n"
          "Dylan: Reliability and networking separate the platinum tier from everyone else.")
    ok, reason = deep_dive_structural_ok(_content(ev))
    assert not ok and "name the speaker" in reason


@pytest.mark.parametrize("line,match", [
    ("Pam: hello there", True),
    ("Dylan: the cluster is good", True),
    ("Ant (Supabase): agents pick Postgres", True),
    ("Katelyn Lesse: we ship the platform", True),
    ("J Mintzmyer: the oil must flow", True),
    ("pam: lower-case is not a label", False),
    ("Pam:", False),  # label with no quote text
    ("The market (broadly): is not a speaker", False),  # lower-case second token
])
def test_speaker_line_re(line, match):
    assert bool(SPEAKER_LINE_RE.match(line)) is match


# ---- 628 "Pam:" -> "swyx:" ----------------------------------------------------------------

def _dd(ins, pe, lines):
    return {"id": ins, "insight_id": ins, "podcast_episode_id": pe, "insight_title": f"t{ins}",
            "key_tickers": [], "episode_evidence": "\n".join(lines)}


def test_628_pam_label_becomes_swyx_and_caitlin_becomes_lesse():
    lines = ["Pam: Over 50% of testers said the new model felt like a step change.",
             "Caitlin: We spend most of our time on the Claude platform."]
    data = {"archive": {"insights": []}, "mainContent": {"insights": []},
            "deepDives": {"628": _dd(628, 616, lines), "627": _dd(627, 617, lines)}}
    export_data._apply_summary_overrides(data)
    ev = data["deepDives"]["628"]["episode_evidence"].split("\n")
    assert ev[0] == "swyx: Over 50% of testers said the new model felt like a step change."
    assert ev[1] == "Katelyn Lesse: We spend most of our time on the Claude platform."
    assert "Pam:" not in data["deepDives"]["628"]["episode_evidence"]
    # scoped to the 628 rule: another insight keeps its labels
    assert data["deepDives"]["627"]["episode_evidence"].startswith("Pam: ")


def test_628_rule_order_pam_swap_next_to_bare_caitlin():
    rules = export_data._load_override_rules()["summaries"]
    r = [x for x in rules if x.get("insight_id") == 628]
    assert len(r) == 1
    reps = [tuple(x) for x in r[0]["replacements"]]
    i = reps.index(("Pam:", "swyx:"))
    assert reps[i + 1] == ("Caitlin", "Katelyn Lesse") and i + 1 == len(reps) - 1
    # the summary phrase swaps still run first
    assert reps.index(("Pam highlights", "Host swyx highlights")) < i


# ---- check_blocked_deepdives.py ------------------------------------------------------------

def _make_db(path, *, blocked=False, stale=False, fresh=False):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE latest_insights (id INTEGER PRIMARY KEY, title TEXT, podcast_episode_id INTEGER,
            added_date DATE, archived_date DATE);
        CREATE TABLE deep_dive_content (id INTEGER PRIMARY KEY, insight_id INTEGER);
        CREATE TABLE deep_dive_generation_failures (insight_id INTEGER UNIQUE, insight_title TEXT,
            source_type TEXT, podcast_episode_id INTEGER, failure_reason TEXT, failure_detail TEXT,
            last_attempt_at TIMESTAMP, retry_count INTEGER, next_retry_after TIMESTAMP, status TEXT);
        INSERT INTO latest_insights VALUES (1, 'ok', 10, '2026-10-01', NULL);
        INSERT INTO deep_dive_content (insight_id) VALUES (1);
        INSERT INTO latest_insights VALUES (2, 'archived old', 11, '2026-09-01', '2026-09-10');
        INSERT INTO deep_dive_generation_failures VALUES (1, 'ok', 'podcast', 10, 'generation_failed', '', '2026-10-01T09:00:00', 1, NULL, 'resolved');
    """)
    if blocked:
        c.execute("INSERT INTO latest_insights VALUES (628, 'Anthropic', 616, '2026-10-27', NULL)")
        c.execute("INSERT INTO deep_dive_generation_failures VALUES (628, 'Anthropic', 'podcast', 616, 'generation_failed', "
                  "'source_quotes need at least two lines that name the speaker', '2026-10-28T05:17:16.293686', 3, NULL, 'blocked')")
    if stale:
        c.execute("INSERT INTO latest_insights VALUES (700, 'stale', 700, '2026-10-20', NULL)")
    if fresh:
        c.execute("INSERT INTO latest_insights VALUES (701, 'fresh', 701, '2026-10-28', NULL)")
    c.commit()
    c.close()


NOW = datetime(2026, 10, 28, 14, 30, tzinfo=cbd.CT)


def _run(path):
    conn = cbd.open_readonly(path)
    try:
        return cbd.find_problems(conn, now=NOW)
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _pin_now(monkeypatch):
    # main() uses the wall clock; pin it so the "fresh" (<48h) fixture insight stays fresh.
    real = cbd.find_problems
    monkeypatch.setattr(cbd, "find_problems", lambda conn, now=None: real(conn, now=now or NOW))


def test_clean_db_ok_exit0(tmp_path, capsys):
    db = tmp_path / "d.db"
    _make_db(db, fresh=True)  # a <48h insight without a deep dive is not an alert yet
    assert _run(db) == ([], [])
    assert cbd.render([], []) == "OK: 0 blocked"
    assert cbd.main(["--db", str(db)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 0 blocked"


def test_blocked_listed_exit1_and_ct_time(tmp_path, capsys):
    db = tmp_path / "d.db"
    _make_db(db, blocked=True)
    blocked, stale = _run(db)
    assert [b["insight_id"] for b in blocked] == [628] and stale == []  # not listed twice
    assert cbd.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert "BLOCKED insight 628 | ep 616 | reason: generation_failed | retries: 3 | last tried: 2026-10-28 05:17 CT" in out
    assert "OK:" not in out


def test_stale_insight_without_deep_dive_listed(tmp_path, capsys):
    db = tmp_path / "d.db"
    _make_db(db, stale=True, fresh=True)
    blocked, stale = _run(db)
    assert blocked == [] and [s["insight_id"] for s in stale] == [700]
    assert cbd.main(["--db", str(db)]) == 1
    assert "NO DEEP DIVE insight 700 | ep 700 | added 2026-10-20" in capsys.readouterr().out


def test_fmt_ct_converts_aware_utc():
    assert cbd.fmt_ct("2026-10-28T10:17:00Z") == "2026-10-28 05:17 CT"
    assert cbd.fmt_ct(None) == "never"


def test_check_is_read_only(tmp_path):
    db = tmp_path / "d.db"
    _make_db(db, blocked=True, stale=True)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    cbd.main(["--db", str(db)])
    conn = cbd.open_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE deep_dive_generation_failures SET status='resolved'")
    conn.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
