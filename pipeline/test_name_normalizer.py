"""name_normalizer: source-side name spelling fixes before analysis (Oct 14 2026)."""
import json

import name_normalizer as nn


def _norm(text, meta=(), tmp_path=None):
    log = tmp_path / "name_review.jsonl"
    fixed, changes, review = nn.normalize_text(text, meta, episode_id="ep1", log_path=log)
    return fixed, review, log


def test_thropic_becomes_anthropic(tmp_path):
    fixed, _, _ = _norm("Dario runs Thropic and said Thropic will ship.", tmp_path=tmp_path)
    assert fixed == "Dario runs Anthropic and said Anthropic will ship."
    assert nn.apply_exact("Anthropic") == "Anthropic"


def test_mark_andrewson(tmp_path):
    fixed, _, _ = _norm("Mark Andrewson argued for stablecoins.", tmp_path=tmp_path)
    assert fixed == "Marc Andreessen argued for stablecoins."


def test_patrick_suresne(tmp_path):
    fixed, _, _ = _norm("Patrick Suresne joins Erik.", tmp_path=tmp_path)
    assert fixed == "Patrick Ceresna joins Erik."


def test_eric_schmidt_unchanged(tmp_path):
    text = "Eric Schmidt talked about Google and Eric Townsend's show."
    fixed, review, log = _norm(text, meta=["Eric Schmidt"], tmp_path=tmp_path)
    assert "Eric Schmidt" in fixed
    assert not any(r["original"] == "Eric Schmidt" for r in review)


def test_metadata_confirmed_fuzzy_fix(tmp_path):
    meta = nn.metadata_names_from_sidecar({"episode_title": "Oil Outlook with Rory Kessler",
                                           "show_notes": "<p>Guest Rory Kessler of Acme.</p>"})
    assert "Rory Kessler" in meta
    fixed, _, _ = _norm("Rory Kesler thinks oil goes up.", meta=meta, tmp_path=tmp_path)
    assert fixed == "Rory Kessler thinks oil goes up."


def test_unconfirmed_near_miss_logged_not_changed(tmp_path):
    text = "Then Marc Andreesen said crypto is back."
    fixed, review, log = _norm(text, meta=[], tmp_path=tmp_path)
    assert fixed == text
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert rows and rows[0]["original"] == "Marc Andreesen"
    assert rows[0]["candidate"] == "Marc Andreessen"
    assert set(rows[0]) >= {"episode_id", "original", "candidate", "score", "context"}


def test_common_words_never_fuzzed(tmp_path):
    text = "The Fed and Wall Street reacted."
    fixed, review, _ = _norm(text, meta=["Wall Streat"], tmp_path=tmp_path)
    assert fixed == text and not review


def test_card_backstop_skips_quotes():
    card = {"summary": "Mark Andrewson said 'Mark Andrewson is here.' Thropic too.",
            "notable_quotes": [{"quote": "Thropic rocks", "speaker": "Mark Andrewson"}],
            "title": "Mark Andrewson show"}
    nn.apply_to_cards(card)
    assert card["summary"] == "Marc Andreessen said 'Mark Andrewson is here.' Anthropic too."
    assert card["notable_quotes"][0] == {"quote": "Thropic rocks", "speaker": "Marc Andreessen"}
    assert card["title"] == "Mark Andrewson show"


def test_cli(capsys):
    assert nn.main(["--check", "Mark Andrewson"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output"] == "Marc Andreessen" and out["changed"]
