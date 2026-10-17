"""Public-page rules for site/leaderboard.html (the Bot Game page)."""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = (SITE / "leaderboard.html").read_text(encoding="utf-8")


def test_paper_label_near_top():
    assert PAGE.lower().index("paper game, no real orders") < PAGE.lower().index("<h2")


def test_disclaimer_once_at_bottom():
    line = "We may hold positions in some or all of the companies mentioned."
    assert PAGE.count(line) == 1
    assert PAGE.count("<strong>Disclaimer:</strong>") == 1
    assert PAGE.index(line) > PAGE.index('id="trades"')
    # the JSON's own short disclaimer is not rendered as a second disclaimer
    assert "d.disclaimer" not in PAGE


def test_no_bet_wording_and_no_old_name():
    assert not re.search(r"\b(bets?|betting|wager\w*)\b", PAGE, re.I)
    assert "compound wealth" not in PAGE.lower()


def test_reads_tony_contract_and_handles_gaps():
    assert "data/leaderboard.json" in PAGE
    assert "reason not filed" in PAGE
    # optional fields degrade: chart placeholder and closed-P&L note present
    assert 'class="placeholder"' in PAGE and "d.history" in PAGE
    assert "closed_positions" in PAGE and "d.trades" in PAGE


def test_no_duplicate_page_or_data_file():
    assert not (SITE / "bot-game.html").exists()
    assert not (SITE / "data" / "bot_game.json").exists()
    for p in SITE.glob("*.html"):
        assert "bot-game.html" not in p.read_text(encoding="utf-8"), p.name
