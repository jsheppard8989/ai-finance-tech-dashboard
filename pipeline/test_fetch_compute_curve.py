from fetch_compute_curve import parse, tenor_label


def _raw():
    keys = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03",
            "2027-04", "2027-05", "2027-06", "2027-07", "2027-08"]
    pts = [{"tenor": "Anchor", "priceUsdPerGpuHour": 2.9, "evidence": {"tenorKey": None}}]
    pts += [{"tenor": "x", "priceUsdPerGpuHour": 2.0 + i / 10, "evidence": {"tenorKey": k}}
            for i, k in enumerate(keys)]
    return {"asOf": "2026-10-14T12:18:52Z", "chips": [{"id": "h100", "points": pts, "provenance": {}}]}


def test_tenor_label_year_from_data():
    assert tenor_label("2027-06") == "Jun '27"
    assert tenor_label("2026-12") == "Dec '26"
    assert tenor_label("bad") is None


def test_card_tenors_have_years():
    out = parse(_raw())
    card = [p["tenor"] for p in out["h100"]["card"]]
    assert card == ["Oct '26", "Dec '26", "Jun '27"]
    assert all("'" in p["tenor"] for p in out["h100"]["points"])
    assert len(out["h100"]["points"]) == 11  # Anchor dropped


def test_no_as_of_returns_none():
    assert parse({"chips": []}) is None
