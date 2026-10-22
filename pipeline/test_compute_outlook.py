import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compute_outlook as co
import fetch_compute_curve as fcc
from fetch_gpu_index import build_spot_history


def _md(b200=(5.0, 6.0, 7.0), h100=(3.0, 3.0, 3.0), a100=(2.0, 1.9, 1.7), fwd=None):
    end = date(2026, 10, 22)
    dates = [(end - timedelta(days=d)).isoformat() for d in (120, 90, 30, 0)]
    def s(t): return [t[0], t[0], t[1], t[2]]
    fwd = fwd or {}
    curve = {c: {"points": [{"tenor_key": "2026-10", "price": 99.0}] + [{"tenor_key": k, "price": v} for k, v in fwd.get(c, [])]} for c in ("a100", "h100", "b200")}
    return {"compute_forward": {"spot_history": {"end": end.isoformat(), "dates": dates, "b200": s(b200), "h100": s(h100), "a100": s(a100)}},
            "compute_forward_curve": curve}


def test_example_line():
    out = co.build_outlook(_md())
    assert out["line"] == "B200 rising, H100 steady, A100 dropping: demand strong for the newest chips, supply catching up on older ones."
    assert "bet" not in out["line"].lower().split() and "thin" not in out["line"].lower()


def test_current_month_forward_ignored_and_thresholds():
    out = co.build_outlook(_md(fwd={"h100": [("2026-11", 3.0)]}))
    assert out["chips"]["h100"]["forward_vs_spot_pct"] == 0.0  # Oct '26 (99.0) skipped
    assert co.classify(3.0) == "steady" and co.classify(3.1) == "rising" and co.classify(-3.1) == "dropping"


def test_uniform_clauses():
    assert co.build_outlook(_md(b200=(5, 5, 5), h100=(3, 3, 3), a100=(2, 2, 2)))["line"].endswith("prices holding across every generation.")
    assert "across every generation" in co.build_outlook(_md(b200=(5, 6, 7), h100=(3, 3.5, 4), a100=(1, 1.3, 1.5)))["line"]


def test_no_history_no_line():
    assert co.build_outlook({}) is None


def test_spot_history_window():
    idx = [{"date": (date(2026, 1, 1) + timedelta(days=i)).strftime("%a, %d %b %Y 00:00:00 GMT"), "a100": 1.5, "h100": 3.0, "b200": None if i < 120 else 6.0} for i in range(295)]
    h = build_spot_history(idx)
    assert h["days"] == 183 and len(h["dates"]) == 183 and h["end"] == "2026-10-22"
    assert h["available_from"]["b200"] == "2026-05-01"
    assert h["b200"][0] is None and h["b200"][-1] == 6.0


def test_curve_keeps_chips_and_last_trade():
    assert fcc.CHIPS == ("a100", "h100", "b200", "h200")
    raw = {"asOf": "2026-10-22T17:35:45Z", "chips": [
        {"id": c, "provenance": {"latestMarketAt": "2026-09-09T17:33:08Z"},
         "points": [{"priceUsdPerGpuHour": 3.0, "quality": "thin", "evidence": {"tenorKey": "2026-11"}}]} for c in ("a100", "h100", "b200", "h200", "rtx5090")]}
    out = fcc.parse(raw)
    assert set(c for c in out if not c.startswith("_") and isinstance(out[c], dict)) == {"a100", "h100", "b200", "h200"}
    assert out["b200"]["last_trade_at"] == "2026-09-09T17:33:08Z"


def test_home_chart_wiring():
    html = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text()
    for needle in ('id="compute-forward-chart"', "renderComputeChart", "few trades so far", "Ornn OCPI", "compute-thesis", 'id="compute-thesis-slot"'):
        assert needle in html
    assert 'href="./compute-thesis.html"' not in html  # button only injected once the page exists
