"""Strip label: 'Settles <date>' for future grade dates, 'Settled <date>' once reached."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_trap_map as b  # noqa: E402


def test_future_grade_date_says_grades():
    assert b.grade_label("2026-11-10", today=date(2026, 10, 30)) == "Settles Nov 10"
    assert b.grade_label("2028-12-15", today=date(2026, 10, 30)) == "Settles Dec 15, 2028"


def test_past_or_today_grade_date_says_graded():
    assert b.grade_label("2026-10-20", today=date(2026, 10, 30)) == "Settled Oct 20"
    assert b.grade_label("2026-10-30", today=date(2026, 10, 30)) == "Settled Oct 30"


def test_strip_uses_label():
    import json
    d = b.compute(json.loads(b.DATA.read_text()))
    strip = b.render_strip(d, today=date(2026, 10, 30))
    assert "Settles Nov 10" in strip and "Settled Nov" not in strip
