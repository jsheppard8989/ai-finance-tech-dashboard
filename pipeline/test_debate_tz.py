from debate_weekly import chicago_tz_abbr


def test_cdt_in_summer():
    assert chicago_tz_abbr("2026-09-25") == "CDT"
    assert chicago_tz_abbr("2026-04-29") == "CDT"


def test_cst_in_winter():
    assert chicago_tz_abbr("2026-12-04") == "CST"
    assert chicago_tz_abbr("2026-03-06") == "CST"


def test_dst_boundaries():
    assert chicago_tz_abbr("2026-03-08") == "CDT"  # DST starts 2 AM Mar 8; noon is CDT
    assert chicago_tz_abbr("2026-11-01") == "CST"  # DST ends 2 AM Nov 1


def test_bad_input():
    assert chicago_tz_abbr("not-a-date") == "CT"
