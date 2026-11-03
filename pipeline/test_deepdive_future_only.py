"""Deep Dive 'What would change our view' lists name only future events (decisions.md, Nov 2 2026)."""
from datetime import date

import pytest

from deepdive_future_only import drop_past_falsifiers, is_past, line_dates

TODAY = date(2026, 11, 2)
ANCHOR = date(2026, 8, 1)


@pytest.mark.parametrize("line", [
    "By Sep 30, 2026, if bookings fail above 5% per the 10-Q, the moat is in question.",
    "By 2026-10-31, source: press release, pages below 8 billion means the claim is wrong.",
    "By Oct 31, 2026, no Moody's downgrade for France weakens the thesis.",
    "By Nov. 1, 2026, the FTA dashboard must show overrun below 15%.",
    "By Q2 2026, Congress requires frontier-model licensing.",
    "By the Q2 2026 Alphabet earnings release, cloud growth must stay above 20%.",
    "Revenue under $318M by Sep 30 per the 10-Q.",          # no year: anchored to Aug 2026 -> Sep 30 2026
    "Shipments below 1M units in Jun 2026 per IDC.",
    "Margins under 40% in the 2Q26 report.",
])
def test_past_lines_detected(line):
    assert is_past(line, TODAY, ANCHOR)


@pytest.mark.parametrize("line", [
    "Revenue under $318M in the Q3 2026 10-Q, due by Nov 9, 2026.",
    "By the Q3 2026 BEA PCE release, PCE must stay at or below 3.5%.",       # report comes after Q3
    "By the next Alphabet earnings release after 2026-10-28, growth stays above 30%.",
    "A significant decline in Apple's market share over consecutive quarters.",  # no date: stays
    "Revenue may decline 10% by the end of 2026.",                            # 'may' verb, unparsed
    "By Dec 31, 2026, HBM inventory above 8 weeks per SK Hynix.",
    "Guidance cut in the Jul 2026 call or the Q1 2027 10-Q.",                 # latest date is future
    "If NVIDIA share falls by Feb 15 per Mercury Research.",                  # no year, anchor Aug -> Feb 2027
    "By Nov 2, 2026, the 8-K shows X.",                                       # today is not past
])
def test_future_or_undated_lines_kept(line):
    assert not is_past(line, TODAY, ANCHOR)


def test_year_inference_rolls_forward():
    assert line_dates("by Feb 15", date(2026, 8, 1)) == [date(2027, 2, 15)]
    assert line_dates("by Sep 30", date(2026, 8, 1)) == [date(2026, 9, 30)]


def test_drop_mutates_and_reports():
    dds = {
        "1": {"insight_id": 1, "source_date": "2026-08-01",
              "falsification_tracks": ["By Sep 30, 2026, X fails per 10-Q.", "By Dec 31, 2026, Y per 8-K.", "No date here."]},
        "2": {"insight_id": 2, "falsification_tracks": ["By Oct 31, 2026, Z per S&P."]},
        "3": {"insight_id": 3, "falsification_tracks": None},
    }
    dropped = drop_past_falsifiers(dds, TODAY)
    assert [i for i, _ in dropped] == ["1", "2"]
    assert dds["1"]["falsification_tracks"] == ["By Dec 31, 2026, Y per 8-K.", "No date here."]
    assert dds["2"]["falsification_tracks"] == []   # empty list: renderer already shows nothing
    assert dds["3"]["falsification_tracks"] is None


def test_export_wires_filter():
    import inspect
    import export_data
    src = inspect.getsource(export_data.generate_website_js)
    assert "drop_past_falsifiers(deepdives" in src


def test_apply_to_data_js_roundtrip(tmp_path):
    import json
    from deepdive_future_only import apply_to_data_js
    dds = {"1": {"insight_id": 1, "falsification_tracks": ["By Sep 30, 2026, X per 10-Q.", "Undated line."]}}
    src = f'const dashboardData = {{\n  archive: [],\n  deepDives: {json.dumps(dds, indent=2)},\n  suggestedTerms: []\n}};\n'
    f = tmp_path / "data.js"
    f.write_text(src)
    assert [i for i, _ in apply_to_data_js(f, TODAY)] == ["1"]
    out = f.read_text()
    assert "Sep 30" not in out and "Undated line." in out and out.startswith("const dashboardData = {\n  archive: [],")
    assert apply_to_data_js(f, TODAY) == []  # idempotent


def test_live_data_js_has_no_past_falsifiers():
    from pathlib import Path
    from deepdive_future_only import apply_to_data_js
    p = Path(__file__).resolve().parent.parent / "site" / "data" / "data.js"
    assert apply_to_data_js(p, TODAY, write=False) == []
