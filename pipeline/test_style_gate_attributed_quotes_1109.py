"""Nov 9 2026 (decisions.md ~11:15 PM CT): the no-'bet' rule covers our own voice only.
Attributed guest quotes pass verbatim; our copy and unattributed quotes stay strict."""
import publish_guard
from site_text_sanitize import find_style_gate_hits, style_gate_hits


# --- attributed guest quotes pass -----------------------------------------
def test_structured_quote_with_speaker_passes():
    rec = {"notable_quotes": [{"speaker": "Andy Constan", "quote": "my bet today is a period of three"}]}
    assert find_style_gate_hits(rec) == []


def test_speaker_line_in_quote_field_passes():
    rec = {"episode_evidence": "Andy Constan: my bet today is that we're going to see a period of three"}
    assert find_style_gate_hits(rec) == []


def test_inline_attributed_quotes_pass():
    for t in (
        'Alex Zhang: "there\u2019s so many big bets to take."',
        "The host mentions that 'The labs are betting that RL VR will generalize.'",
        'According to Jensen Huang, "we bet the company on CUDA".',
        '"We are betting on robots," Dara Khosrowshahi said.',
        '\u201cWe bet the company\u201d \u2014 Jensen Huang',
    ):
        assert style_gate_hits(t) == [], t


def test_guard_passes_attributed_quote_in_data(tmp_path):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "data.js").write_text(
        'const dashboardData = {\n"generatedAt": "x", "priceSnapshot": {"A": 1},\n'
        '"deepDives": {"1": {"overview": "Rates stay high.", "episode_evidence": "Andy Constan: my bet today is three years",'
        ' "notable_quotes": [{"speaker": "Alex Zhang", "quote": "so many big bets"}]}}\n};\n', encoding="utf-8")
    assert publish_guard.check_data(site) == []


# --- our copy and unattributed quotes stay strict -------------------------
def test_our_copy_still_fails():
    for t in ("Our lean: a bet on power.", "We are betting on model-only platforms.",
              "This is a big bet on AI.", "Andy Constan: my bet today"):
        assert style_gate_hits(t), t
    assert find_style_gate_hits({"overview": "Andy Constan: my bet today"})  # speaker lines only in quote fields
    assert find_style_gate_hits({"investment_thesis": "The cleanest bet is GEV."})


def test_unattributed_quotes_still_fail():
    for t in ('This is a "big bet" on AI.', '"Big bets" are everywhere.', 'The "bet" is AI.',
              'We say "bet on it".', 'Our view: "bet on chips"'):
        assert style_gate_hits(t), t
    assert find_style_gate_hits({"notable_quotes": [{"speaker": "", "quote": "big bets"}]})
    assert find_style_gate_hits({"notable_quotes": ["big bets ahead"]})
    assert find_style_gate_hits({"episode_evidence": "my bet today is three"})


def test_guard_blocks_our_copy_and_unattributed_quote(tmp_path):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "data.js").write_text(
        'const dashboardData = {\n"generatedAt": "x", "priceSnapshot": {"A": 1},\n'
        '"deepDives": {"1": {"overview": "Our call is a \\"bet\\" on power.",'
        ' "notable_quotes": [{"quote": "so many big bets"}]}}\n};\n', encoding="utf-8")
    reasons = publish_guard.check_data(site)
    assert reasons and "style gate: 2 'bet' wording hit(s)" in reasons[0]
