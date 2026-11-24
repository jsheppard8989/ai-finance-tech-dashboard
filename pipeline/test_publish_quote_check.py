"""Publish-time, flag-only checks for main-page podcast summary cards."""

from __future__ import annotations

import json

import export_data
import publish_quote_check as checker


TRANSCRIPT = """
Satya Nadella said Microsoft expects revenue to reach 1.5 billion dollars.
He added, "The cloud market is growing faster than we expected."
"""


def _card(**updates):
    card = {
        "id": 42,
        "podcast_episode_id": 711,
        "podcast_name": "The Test Show",
        "key_takeaway": "",
        "key_points": [],
        "notable_quotes": [],
    }
    card.update(updates)
    return card


def test_exact_quote_passes(tmp_path):
    log = tmp_path / "quote_check.jsonl"
    misses = checker.check_episode_summary(
        _card(key_takeaway='Nadella said “The cloud market is growing faster than we expected.”'),
        TRANSCRIPT,
        transcript_path="/tmp/episode.txt",
        log_path=log,
    )
    assert misses == []
    assert not log.exists()


def test_small_asr_difference_passes(tmp_path):
    misses = checker.check_episode_summary(
        _card(key_takeaway='"I think we can win."'),
        "The speaker said I tink we can win during the interview.",
        transcript_path="/tmp/episode.txt",
        log_path=tmp_path / "quote_check.jsonl",
    )
    assert misses == []


def test_paraphrased_quote_is_flagged(tmp_path):
    log = tmp_path / "quote_check.jsonl"
    misses = checker.check_episode_summary(
        _card(key_takeaway='"The cloud market is shrinking much faster than expected."'),
        TRANSCRIPT,
        transcript_path="/tmp/episode.txt",
        log_path=log,
    )
    assert [miss["kind"] for miss in misses] == ["quote"]
    assert misses[0]["field"] == "key_takeaway"
    assert misses[0]["best_match_score"] < 0.85


def test_missing_number_in_key_points_is_flagged(tmp_path):
    misses = checker.check_episode_summary(
        _card(key_points=["Microsoft expects revenue to reach $2.5B."]),
        TRANSCRIPT,
        transcript_path="/tmp/episode.txt",
        log_path=tmp_path / "quote_check.jsonl",
    )
    assert any(m["kind"] == "number" and m["text"] == "2.5B" for m in misses)


def test_missing_spelled_number_in_key_points_is_flagged(tmp_path):
    misses = checker.check_episode_summary(
        _card(key_points=["Microsoft expects revenue to reach two billion dollars."]),
        TRANSCRIPT,
        transcript_path="/tmp/episode.txt",
        log_path=tmp_path / "quote_check.jsonl",
    )
    assert any(m["kind"] == "number" and m["text"] == "2B" for m in misses)


def test_missing_name_in_key_points_is_flagged(tmp_path):
    misses = checker.check_episode_summary(
        _card(key_points=["Tim Cook expects Microsoft revenue to reach $1.5B."]),
        TRANSCRIPT,
        transcript_path="/tmp/episode.txt",
        log_path=tmp_path / "quote_check.jsonl",
    )
    assert any(m["kind"] == "name" and m["text"] == "Tim Cook" for m in misses)
    assert not any(m["kind"] == "name" and m["text"] == "Microsoft" for m in misses)


def test_missing_single_token_name_in_key_points_is_flagged(tmp_path):
    misses = checker.check_episode_summary(
        _card(key_points=["Nadella disagrees with Databricks."]),
        "Nadella discussed Microsoft.",
        transcript_path="/tmp/episode.txt",
        log_path=tmp_path / "quote_check.jsonl",
    )
    assert any(m["kind"] == "name" and m["text"] == "Databricks" for m in misses)
    assert not any(m["kind"] == "name" and m["text"] == "Nadella" for m in misses)


def test_sentence_initial_title_case_is_not_assumed_to_be_a_name(tmp_path):
    assert list(checker._name_mentions("Higher Rates could slow demand.", _card())) == []


def test_checker_exception_does_not_block_publish(monkeypatch, capsys):
    main_content = {"insights": [_card()]}

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic checker failure")

    monkeypatch.setattr(checker, "check_main_page_summaries", explode)
    returned = export_data.run_publish_quote_check_fail_open(main_content, db=object())
    assert returned is main_content
    assert "publish quote check failed open" in capsys.readouterr().out.lower()


def test_no_transcript_logs_one_miss(tmp_path):
    log = tmp_path / "quote_check.jsonl"
    misses = checker.check_episode_summary(
        _card(key_points=["Tim Cook expects $2.5B."]),
        None,
        transcript_path="",
        log_path=log,
    )
    assert len(misses) == 1
    assert misses[0]["kind"] == "no_transcript"
    line = json.loads(log.read_text(encoding="utf-8"))
    assert line["episode_id"] == 711
    assert line["podcast"] == "The Test Show"
