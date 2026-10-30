from pathlib import Path
import re

SITE = Path(__file__).resolve().parents[1] / "site"


def test_dc_buildout_oct30_grading():
    html = (SITE / "dc-buildout.html").read_text(encoding="utf-8")
    assert "only Alphabet cleared our bar, so the demand check failed (section 8)" in html
    assert html.count("Result (Oct 30): NOT MET.") == 2
    assert "No standing order; Core Scientific is watch only." in html
    assert "Result: CANCEL.</strong> Only Alphabet met its bar." in html
    assert "docket ER27-330-000" in html and "Comments are due Nov 30." in html
    assert "not found as of Oct 30" in html
    assert "no new position before the big cloud companies" not in html
    assert "nothing opens before Oct 28" not in html
    assert "PJM plans an emergency" not in html
