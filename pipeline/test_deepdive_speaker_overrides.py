#!/usr/bin/env python3
"""Tests for curated Deep Dive speaker overrides and non-persisting drafts."""

import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import generate_deepdives as gd
from tools.match_official_transcript import suggest_quote_speakers


FALSIFIERS = [
    "If SK Hynix reports HBM inventory above 8 weeks in its Q3 2027 earnings release, the shortage thesis fails.",
    "If NVIDIA's datacenter share falls more than 5 points per Mercury Research by Dec 31, 2026, reassess positioning.",
]


def _valid_content():
    return {
        "schema_version": 2,
        "episode_evidence": (
            'Chris McGuire: "The DOJ investigation was obviously not complete."\n'
            'Peter Harrell: "Export-control violations carry a five-year statute of limitations."'
        ),
        "overview": (
            "The reinstatement leaves enforcement discretion intact while congressional oversight "
            "becomes the principal constraint on licensing policy."
        ),
        "investment_thesis": (
            "Policy-driven volatility remains a material risk for semiconductor valuations through 2027."
        ),
        "ticker_analysis": {"NVDA": {"rationale": "Policy exposure", "positioning": "Watch", "risk": "Licensing"}},
        "falsification_tracks": list(FALSIFIERS),
        "key_takeaways_detailed": [],
        "contrarian_signals": [],
        "catalysts": [],
    }


def _extraction():
    return {
        "high_value_quotes": [
            {"speaker": "one host", "quote": "The DOJ investigation was obviously not complete."},
            {
                "speaker": "a panelist",
                "quote": "Export-control violations carry a five-year statute of limitations.",
            },
            {"speaker": "guest", "quote": "This unlisted generic quote must stay generic."},
        ],
        "companies_and_assets": [
            {
                "name": "Nvidia",
                "key_quotes": [
                    {"speaker": "host", "quote": "This second unlisted quote must also stay generic."}
                ],
            }
        ],
    }


def _override():
    return {
        "host": "Jordan Schneider",
        "guests": ["Chris McGuire", "Peter Harrell"],
        "source_urls": ["https://www.chinatalk.media/p/jensen-returns"],
        "quote_speakers": [
            {
                "quote": "The DOJ investigation was obviously not complete.",
                "speaker": "Chris McGuire",
            },
            {
                "quote_prefix": "Export-control violations carry",
                "speaker": "Peter Harrell",
            },
        ],
    }


def test_override_changes_names_and_only_relabels_listed_quotes():
    extraction_json, host, guests = gd.apply_deepdive_speaker_override(
        731,
        json.dumps(_extraction()),
        host_name=None,
        guest_names=["one host", "a panelist"],
        overrides={"731": _override()},
    )

    changed = json.loads(extraction_json)
    assert host == "Jordan Schneider"
    assert guests == ["Chris McGuire", "Peter Harrell"]
    assert [q["speaker"] for q in changed["high_value_quotes"]] == [
        "Chris McGuire",
        "Peter Harrell",
        "guest",
    ]
    assert changed["companies_and_assets"][0]["key_quotes"][0]["speaker"] == "host"


def test_relabelled_quotes_pass_structural_check():
    ok, reason = gd.deep_dive_structural_ok(_valid_content())
    assert ok, reason


def test_prompt_forbids_naming_unlisted_generic_quotes():
    extraction_json, host, guests = gd.apply_deepdive_speaker_override(
        731,
        json.dumps(_extraction()),
        host_name=None,
        guest_names=None,
        overrides={"731": _override()},
    )
    prompt = gd._build_extraction_deepdive_prompt(
        extraction_json,
        "summary",
        "takeaway",
        host_name=host,
        guest_names=guests,
    )

    assert '"speaker": "guest"' in prompt
    assert '"speaker": "host"' in prompt
    assert "does not authorize you to replace a generic extraction label" in prompt
    assert "use the speaker label EXACTLY as it appears on that quote" in prompt


def test_quote_validation_rejects_naming_an_unlisted_generic_quote():
    extraction = {
        "high_value_quotes": [
            {"speaker": "one host", "quote": "This exact quote has no sourced name."},
        ],
        "companies_and_assets": [],
    }
    ok, error = gd._validate_quotes_from_extraction(
        ["Jordan Schneider: This exact quote has no sourced name."],
        extraction,
    )
    assert not ok
    assert "speaker label" in error


def test_quote_check_cannot_upgrade_a_generic_label_to_a_name():
    content = {"episode_evidence": "one host: This exact quote has no sourced name."}
    with patch(
        "speaker_attribution.verify_evidence_lines",
        return_value=("Jordan Schneider: This exact quote has no sourced name.", []),
    ):
        gd.apply_evidence_quote_check(
            content,
            "This exact quote has no sourced name.",
            preserve_generic_labels=True,
        )
    assert content["episode_evidence"].startswith("one host:")


def _make_draft_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE latest_insights (
            id INTEGER PRIMARY KEY,
            title TEXT,
            source_type TEXT,
            podcast_episode_id INTEGER,
            summary TEXT,
            key_takeaway TEXT,
            source_date TEXT,
            notable_quotes TEXT,
            source_name TEXT
        );
        CREATE TABLE podcast_episodes (id INTEGER PRIMARY KEY, extraction_json TEXT);
        CREATE TABLE deep_dive_content (id INTEGER PRIMARY KEY, insight_id INTEGER);
        CREATE TABLE deep_dive_generation_failures (
            insight_id INTEGER PRIMARY KEY,
            insight_title TEXT,
            source_type TEXT,
            podcast_episode_id INTEGER,
            failure_reason TEXT,
            failure_detail TEXT,
            last_attempt_at TEXT,
            retry_count INTEGER,
            next_retry_after TEXT,
            status TEXT
        );
        INSERT INTO latest_insights VALUES (
            731, 'Emergency Pod: Jensen Back', 'podcast', 720, 'summary', 'takeaway',
            '2026-11-24', '[]', 'ChinaTalk'
        );
        INSERT INTO podcast_episodes VALUES (
            720, '{"high_value_quotes": [], "companies_and_assets": []}'
        );
        INSERT INTO deep_dive_generation_failures VALUES (
            731, 'Emergency Pod: Jensen Back', 'podcast', 720, 'generation_failed',
            'speaker labels', '2026-11-24', 3, NULL, 'blocked'
        );
        """
    )
    conn.commit()
    conn.close()


def test_draft_out_writes_artifacts_without_any_persistence(tmp_path):
    db = tmp_path / "dashboard.db"
    out = tmp_path / "drafts"
    _make_draft_db(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    with (
        patch.dict("os.environ", {"DEEPDIVE_MODE": "extraction"}),
        patch.object(gd, "DB_PATH", db),
        patch.object(gd, "get_ai_clients", return_value=[("openai", MagicMock())]),
        patch.object(gd, "load_high_profile_config", return_value={"episode_ids": [], "insight_ids": [], "shows": [], "title_keywords": []}),
        patch.object(
            gd,
            "run_extraction_deep_dive_attempts",
            return_value=(_valid_content(), None, {"model": "fake"}),
        ) as run_attempts,
        patch.object(gd, "store_deep_dive") as store,
        patch.object(gd, "record_deep_dive_failure") as record_failure,
        patch.object(gd, "mark_deep_dive_failure_resolved") as resolve_failure,
    ):
        assert gd.generate_missing_deepdives([731], draft_out=out) == (1, 1, 0)

    store.assert_not_called()
    record_failure.assert_not_called()
    resolve_failure.assert_not_called()
    assert run_attempts.call_args.kwargs["preserve_generic_labels"] is True
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert json.loads((out / "731.json").read_text())["content"]["episode_evidence"]
    assert json.loads((out / "731.checks.json").read_text())["structural"]["ok"] is True
    assert "# Emergency Pod: Jensen Back" in (out / "731.md").read_text()


def test_non_overridden_insight_keeps_generic_relabeling_default(tmp_path):
    db = tmp_path / "dashboard.db"
    out = tmp_path / "drafts"
    _make_draft_db(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE latest_insights SET id = 730 WHERE id = 731")
    conn.execute("UPDATE deep_dive_generation_failures SET insight_id = 730 WHERE insight_id = 731")
    conn.commit()
    conn.close()

    with (
        patch.dict("os.environ", {"DEEPDIVE_MODE": "extraction"}),
        patch.object(gd, "DB_PATH", db),
        patch.object(gd, "get_ai_clients", return_value=[("openai", MagicMock())]),
        patch.object(
            gd,
            "load_high_profile_config",
            return_value={"episode_ids": [], "insight_ids": [], "shows": [], "title_keywords": []},
        ),
        patch.object(
            gd,
            "run_extraction_deep_dive_attempts",
            return_value=(_valid_content(), None, {"model": "fake"}),
        ) as run_attempts,
    ):
        assert gd.generate_missing_deepdives([730], draft_out=out) == (1, 1, 0)

    assert run_attempts.call_args.kwargs["preserve_generic_labels"] is False


def test_committed_731_override_uses_official_sources_only():
    overrides = gd.load_deepdive_speaker_overrides()
    assert overrides["731"]["host"] == "Jordan Schneider"
    assert overrides["731"]["guests"] == ["Chris McGuire", "Peter Harrell"]
    assert overrides["731"]["source_urls"] == [
        "https://www.chinatalk.media/p/jensen-returns",
        "https://feeds.megaphone.fm/CHTAL4990341033",
    ]


def test_read_only_fallback_decision_honors_existing_daily_use(tmp_path):
    db = tmp_path / "fallback.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE deep_dive_legacy_fallbacks (
            episode_id INTEGER, day TEXT, insight_id INTEGER, reason TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO deep_dive_legacy_fallbacks VALUES (720, '2026-11-24', 731, 'high_profile')"
    )
    conn.commit()
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    assert gd.legacy_fallback_decision(
        conn,
        720,
        "structural failure",
        "insight_id=731",
        today="2026-11-24",
        create_table=False,
    ) == (False, "already_used_today")
    conn.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_official_transcript_matcher_suggests_only_fuzzy_verified_quotes():
    extraction = _extraction()
    official_text = (
        "Photo: Official episode artwork "
        "Chris McGuire: Okay. I think it is important to note at the start that the "
        "Department of Justice investigation was obviously not complete. "
        "Peter Harrell: Export-control violations carry a five-year statute of limitations. "
        "Jordan: This line is unrelated to the remaining generic extraction quotes."
    )
    suggestions = suggest_quote_speakers(
        extraction,
        official_text,
        ["Jordan Schneider", "Chris McGuire", "Peter Harrell"],
    )

    assert suggestions == [
        {
            "quote": "The DOJ investigation was obviously not complete.",
            "speaker": "Chris McGuire",
        },
        {
            "quote": "Export-control violations carry a five-year statute of limitations.",
            "speaker": "Peter Harrell",
        },
    ]
