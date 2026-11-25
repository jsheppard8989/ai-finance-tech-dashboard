#!/usr/bin/env python3
"""Tests for fetch_liquidity_ticker.py (no network; tmp paths via conftest.py)."""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

import fetch_liquidity_ticker as flt  # noqa: E402
from site_text_sanitize import style_gate_hits  # noqa: E402

CT_TZ = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent.parent


def _synth_series(
    *,
    end_date: date,
    n_obs: int,
    mean_target: float,
    stdev_target: float,
    latest_val: float,
    prior_val: float,
    step_days: int = 1,
) -> list[tuple[str, float]]:
    """Build a deterministic series of length n_obs whose latest=latest_val, prior=prior_val,
    and whose sample mean and sample stdev match mean_target and stdev_target closely."""
    # Put (n_obs - 2) historical points symmetric around a base so we hit exact mean & stdev.
    assert n_obs >= 20
    dates: list[str] = []
    cur = end_date
    for _ in range(n_obs):
        dates.append(cur.isoformat())
        cur -= timedelta(days=step_days)
    dates.reverse()

    # Use alternating +delta / -delta around c for first k = n_obs - 2 points (make k even or handle remainder).
    k = n_obs - 2
    sum_total = n_obs * mean_target
    rem_sum = sum_total - latest_val - prior_val
    c = rem_sum / k

    ss_total = (n_obs - 1) * (stdev_target ** 2)
    ss_tail = (latest_val - mean_target) ** 2 + (prior_val - mean_target) ** 2
    ss_rem = ss_total - ss_tail - k * ((c - mean_target) ** 2)
    assert ss_rem > 0, "Cannot hit target stdev with given latest/prior"

    m = k // 2
    delta = math.sqrt(ss_rem / (2 * m))
    vals: list[float] = []
    for i in range(m):
        vals.append(c - delta)
        vals.append(c + delta)
    if k % 2 == 1:
        vals.append(c)
    vals.append(prior_val)
    vals.append(latest_val)
    return list(zip(dates, vals))


def test_net_liq_unit_conversion_and_forward_fill():
    # WALCL and WTREGEN in $ millions; RRPONTSYD in $ billions (requires * 1000).
    walcl = [
        ("2026-11-11", 6_758_867.0),
        ("2026-11-18", 6_741_452.0),
    ]
    wtregen = [
        ("2026-11-11", 914_370.0),
        ("2026-11-18", 916_613.0),
    ]
    rrp = [
        ("2026-11-17", 1.500),  # uses Nov 11 WALCL & WTREGEN
        ("2026-11-18", 0.500),  # uses Nov 18 WALCL & WTREGEN
        ("2026-11-24", 0.301),
        ("2026-11-25", 0.300),
    ]
    nl = flt.compute_net_liq_series(walcl, wtregen, rrp)
    pts = dict(nl["series"])

    # Nov 17: 6,758,867 - 914,370 - (1.5 * 1000) = 5,842,997
    assert pts["2026-11-17"] == 6_758_867.0 - 914_370.0 - 1500.0
    # Nov 25: 6,741,452 - 916,613 - (0.300 * 1000) = 5,824,539
    assert pts["2026-11-25"] == 5_824_539.0
    # Verify *1000 scaling mattered (without *1000 Nov 17 would be off by 1498.5)
    assert pts["2026-11-17"] != 6_758_867.0 - 914_370.0 - 1.5
    assert nl["walcl_as_of"] == "2026-11-18"
    assert nl["wtregen_as_of"] == "2026-11-18"
    assert nl["rrp_as_of"] == "2026-11-25"


def test_net_liq_fails_closed_on_missing_leg():
    walcl = [("2026-11-18", 6_741_452.0)]
    rrp = [("2026-11-25", 0.300)]
    try:
        flt.compute_net_liq_series(walcl, [], rrp)
    except ValueError as exc:
        assert "requires non-empty" in str(exc)
    else:
        raise AssertionError("Expected ValueError when WTREGEN is empty")


def test_six_input_fixture_matches_updated_spec():
    """6-input fixture updated from spec section 4.3 (Nov 25, 2026):
      1. MOVE:       latest=97.53,   mu=77.36,   sigma=14.05,  n=250 -> z=+1.44, signed=+1.44, wins=+1.44
      2. VIX:        latest=28.70,   mu=18.26,   sigma=3.68,   n=259 -> z=+2.84, signed=+2.84, wins=+2.84
      3. Truflation: latest=2.98493, mu=2.06,    sigma=0.63,   n=366 -> z=+1.47, signed=+1.47, wins=+1.47
      4. HY OAS:     latest=3.72,    mu=2.91,    sigma=0.24,   n=263 -> z=+3.38, signed=+3.38, wins=+3.00 (capped)
      5. Net Liq:    latest=5824539, mu=5801000, sigma=85000,  n=250 -> z=+0.28, signed=-0.28, wins=-0.28 (inverted)
      6. DXY:        latest=103.67,  mu=99.74,   sigma=1.63,   n=252 -> z=+2.41, signed=+2.41, wins=+2.41
    Mean signed z (winsorized) = (1.44 + 2.84 + 1.47 + 3.00 - 0.28 + 2.41) / 6 = 1.8133
    Score = round(clip(50 * 1.8133, -100, 100)) = 91 -> Risk-Off / favor shorts.
    """
    end = date(2026, 11, 25)
    specs = [
        ("move", "MOVE", "MOVE (ICE BofA)", 97.53, 98.84, 77.36, 14.05, 250, False),
        ("vix", "VIX", "Cboe Volatility Index", 28.7, 26.36, 18.26, 3.68, 259, False),
        ("truflation", "TRUFL", "Truflation US CPI YoY", 2.98493, 2.983349, 2.06, 0.63, 366, False),
        ("hy_oas", "HY OAS", "ICE BofA US High Yield OAS", 3.72, 3.63, 2.91, 0.24, 263, False),
        ("net_liq", "NET LIQ", "Fed Net Liquidity", 5_824_539.0, 5_824_538.0, 5_801_000.0, 85_000.0, 250, True),
        ("dxy", "DXY", "DXY (ICE U.S. Dollar Index)", 103.67, 103.81, 99.74, 1.63, 252, False),
    ]
    entries = []
    for iid, lbl, name, latest, prior, mu, sd, n, inv in specs:
        ser = _synth_series(
            end_date=end, n_obs=n, mean_target=mu, stdev_target=sd,
            latest_val=latest, prior_val=prior, step_days=1,
        )
        st = flt.compute_z_stats(ser, invert=inv)
        entries.append(
            flt._format_input_entry(
                input_id=iid, label=lbl, name=name, stats=st, source="fixture",
                today_ct="2026-11-25", max_biz_lag=2,
            )
        )

    by_id = {e["id"]: e for e in entries}
    assert by_id["hy_oas"]["z"] > 3.0
    assert by_id["hy_oas"]["signed_z_winsorized"] == 3.0
    assert by_id["net_liq"]["signed_z"] == -0.28
    assert by_id["dxy"]["signed_z_winsorized"] == 2.41

    comp = flt.compute_composite(entries)
    assert comp is not None
    assert comp["score"] == 91
    assert comp["band"] == "Risk-Off"
    assert comp["lean"] == "favor shorts"
    assert comp["inputs_used"] == 6


def test_band_classification_thresholds():
    assert flt.classify_score(-25) == ("Risk-On", "favor longs")
    assert flt.classify_score(-100) == ("Risk-On", "favor longs")
    assert flt.classify_score(-24) == ("Neutral", "balanced")
    assert flt.classify_score(0) == ("Neutral", "balanced")
    assert flt.classify_score(24) == ("Neutral", "balanced")
    assert flt.classify_score(25) == ("Risk-Off", "favor shorts")
    assert flt.classify_score(100) == ("Risk-Off", "favor shorts")


def test_insufficient_history_excluded():
    ser = [(f"2026-11-{d:02d}", float(d)) for d in range(1, 15)]
    st = flt.compute_z_stats(ser)
    assert st["status"] == "insufficient_history"
    assert st["signed_z_winsorized"] is None


def _make_yahoo_payload(dates: list[str], closes: list[float], tz: str = "America/New_York"):
    ts = [int(datetime.fromisoformat(d + "T16:00:00").replace(tzinfo=ZoneInfo(tz)).timestamp()) for d in dates]
    return {
        "chart": {
            "result": [{
                "meta": {"exchangeTimezoneName": tz, "regularMarketTime": ts[-1]},
                "timestamp": ts,
                "indicators": {"quote": [{"close": closes}]},
            }]
        }
    }


def _make_fred_csv(series: list[tuple[str, float]]) -> str:
    lines = ["observation_date,VALUE"] + [f"{d},{v}" for d, v in series]
    return "\n".join(lines) + "\n"


def _make_truflation_payload(series: list[tuple[str, float]]) -> dict:
    return {
        "index": [d for d, _ in series],
        "truflation_us_cpi_frozen_yoy": [v for _, v in series],
    }


def _build_live_mocks():
    end = date(2026, 11, 25)
    move_s = _synth_series(end_date=end, n_obs=250, mean_target=77.36, stdev_target=14.05, latest_val=97.53, prior_val=98.84)
    vix_fred_s = _synth_series(end_date=date(2026, 11, 24), n_obs=258, mean_target=18.22, stdev_target=3.62, latest_val=26.36, prior_val=26.62)
    vix_yah_s = [("2026-11-24", 26.36), ("2026-11-25", 28.70)]
    trufl_s = _synth_series(end_date=end, n_obs=366, mean_target=2.06, stdev_target=0.63, latest_val=2.98493, prior_val=2.983349)
    hy_s = _synth_series(end_date=date(2026, 11, 24), n_obs=263, mean_target=2.91, stdev_target=0.24, latest_val=3.72, prior_val=3.63)
    dxy_s = _synth_series(end_date=end, n_obs=252, mean_target=99.74, stdev_target=1.63, latest_val=103.67, prior_val=103.81)

    rrp_s = _synth_series(end_date=end, n_obs=250, mean_target=10.0, stdev_target=2.0, latest_val=0.300, prior_val=0.301)
    first_d = rrp_s[0][0]
    walcl_s = [(first_d, 6_758_867.0), ("2026-11-18", 6_741_452.0)]
    wtregen_s = [(first_d, 914_370.0), ("2026-11-18", 916_613.0)]

    json_map = {
        flt.YAHOO_MOVE_URL: _make_yahoo_payload([d for d, _ in move_s], [v for _, v in move_s]),
        flt.YAHOO_VIX_URL: _make_yahoo_payload([d for d, _ in vix_yah_s], [v for _, v in vix_yah_s], tz="America/Chicago"),
        flt.YAHOO_DXY_URL: _make_yahoo_payload([d for d, _ in dxy_s], [v for _, v in dxy_s]),
        flt.TRUFLATION_HISTORY_URL: _make_truflation_payload(trufl_s),
        flt.TRUFLATION_LATEST_URL: _make_truflation_payload(trufl_s[-31:]),
    }
    text_map = {
        flt.FRED_URL_TMPL.format(series_id="VIXCLS"): _make_fred_csv(vix_fred_s),
        flt.FRED_URL_TMPL.format(series_id="BAMLH0A0HYM2"): _make_fred_csv(hy_s),
        flt.FRED_URL_TMPL.format(series_id="WALCL"): _make_fred_csv(walcl_s),
        flt.FRED_URL_TMPL.format(series_id="WTREGEN"): _make_fred_csv(wtregen_s),
        flt.FRED_URL_TMPL.format(series_id="RRPONTSYD"): _make_fred_csv(rrp_s),
    }
    return json_map, text_map


def test_fail_closed_partial_and_total_failures():
    json_map, text_map = _build_live_mocks()
    now = datetime(2026, 11, 25, 22, 0, tzinfo=CT_TZ)

    # Initial healthy run writes OUTPUT_FILE and RAW_HISTORY_FILE
    code, doc = flt.run_fetch(
        fetch_text=lambda url, **kw: text_map[url],
        fetch_json=lambda url, **kw: json_map[url],
        now_ct=now,
    )
    assert code == 0 and doc is not None
    assert doc["stale"] is False
    assert doc["inputs_used"] == 6
    assert flt.OUTPUT_FILE.is_file()
    assert flt.RAW_HISTORY_FILE.is_file()
    orig_score = doc["score"]

    # 1) Single-source failure (WTREGEN fails): Net Liq must NOT mix fresh WALCL with missing TGA!
    bad_text_1 = dict(text_map)
    bad_text_1.pop(flt.FRED_URL_TMPL.format(series_id="WTREGEN"))
    code1, doc1 = flt.run_fetch(
        fetch_text=lambda url, **kw: bad_text_1[url],
        fetch_json=lambda url, **kw: json_map[url],
        now_ct=now + timedelta(days=1),
    )
    assert code1 == 0 and doc1 is not None
    assert doc1["stale"] is False
    assert doc1["inputs_used"] == 5
    nl1 = next(i for i in doc1["inputs"] if i["id"] == "net_liq")
    assert nl1["status"] == "stale"
    assert nl1["as_of"] == "2026-11-25"

    # 2) Cached history fallback: FRED VIXCLS fails, Yahoo ^VIX succeeds -> uses RAW_HISTORY_FILE
    bad_text_vix = dict(text_map)
    bad_text_vix.pop(flt.FRED_URL_TMPL.format(series_id="VIXCLS"))
    code_vix, doc_vix = flt.run_fetch(
        fetch_text=lambda url, **kw: bad_text_vix[url],
        fetch_json=lambda url, **kw: json_map[url],
        now_ct=now,
    )
    assert code_vix == 0 and doc_vix is not None
    vix_entry = next(i for i in doc_vix["inputs"] if i["id"] == "vix")
    assert vix_entry["status"] == "ok"
    assert vix_entry["history_source"] == "cached_raw_history"

    # 3) 3+ stale inputs -> composite fails closed (keeps prior score, sets top-level stale=True)
    def fail_three_text(url, **kw):
        raise OSError("FRED down")

    # With FRED down, VIX still works via cached history, while HY OAS and Net Liq fail (2 stale).
    # Also fail MOVE so 3 inputs are stale (MOVE, HY OAS, Net Liq) -> 3/6 ok < 4 -> stale composite.
    bad_json_3 = dict(json_map)
    bad_json_3.pop(flt.YAHOO_MOVE_URL)
    code3, doc3 = flt.run_fetch(
        fetch_text=fail_three_text,
        fetch_json=lambda url, **kw: bad_json_3[url],
        now_ct=now + timedelta(days=1),
    )
    assert code3 == 1 and doc3 is not None
    assert doc3["stale"] is True
    assert doc3["score"] == orig_score

    # 4) Total failure preserves prior JSON values and marks stale=True
    code4, doc4 = flt.run_fetch(
        fetch_text=lambda url, **kw: (_ for _ in ()).throw(OSError("down")),
        fetch_json=lambda url, **kw: (_ for _ in ()).throw(OSError("down")),
        now_ct=now + timedelta(days=2),
    )
    assert code4 == 1 and doc4 is not None
    assert doc4["stale"] is True
    assert doc4["last_attempt_ct"] == "2026-11-27 22:00"
    assert doc4["score"] == orig_score


def test_total_failure_without_prior_never_invents_file():
    code, doc = flt.run_fetch(
        fetch_text=lambda url, **kw: (_ for _ in ()).throw(OSError("down")),
        fetch_json=lambda url, **kw: (_ for _ in ()).throw(OSError("down")),
    )
    assert code == 1
    assert doc is None
    assert not flt.OUTPUT_FILE.exists()


def test_no_bet_or_grading_copy_in_ticker_script_or_ui():
    script_text = Path(flt.__file__).read_text(encoding="utf-8")
    assert style_gate_hits(script_text) == []

    html_text = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    # Extract liquidity-ticker HTML + CSS + JS sections
    aside_m = re.search(r'<aside id="liquidity-ticker".*?</aside>', html_text, re.S)
    assert aside_m is not None
    aside_html = aside_m.group(0)
    assert "model, not advice" in aside_html
    assert style_gate_hits(aside_html) == []

    js_m = re.search(r'async function loadLiquidityTicker\(\).*?\n    \}\n', html_text, re.S)
    assert js_m is not None
    assert style_gate_hits(js_m.group(0)) == []

    # Placement: directly after </header>, before .landing-spill and .plumbing-widgets
    hdr_end = html_text.index("</header>")
    aside_pos = html_text.index('<aside id="liquidity-ticker"')
    spill_pos = html_text.index('<div class="landing-spill"')
    plumb_pos = html_text.index('<div class="plumbing-widgets"')
    assert hdr_end < aside_pos < spill_pos < plumb_pos
    assert "prefers-reduced-motion: reduce" in html_text
    assert "animation-play-state: paused" in html_text
    # Composite stays pinned in the left rail. Desktop loops one 6-input set
    # plus a tape-width/6 gap; the dup copy is aria-hidden and for animation only.
    assert aside_html.count('id="lt-group-primary"') == 1
    assert 'id="lt-pad"' in aside_html
    assert 'id="lt-group-dup"' in aside_html
    assert 'aria-hidden="true"' in aside_html
    assert "LT_PX_PER_SEC" in js_m.group(0)
    assert "layoutTicker" in js_m.group(0)
    assert "viewW / 6" in js_m.group(0)
    assert "--lt-from" in html_text and "--lt-to" in html_text
    assert "border-radius: 12px" in html_text
    # Full-bleed 100vw is mobile-only; the default desktop rule is width: 100%.
    ticker_css = html_text.split("/* Liquidity Pulse strip")[1].split("</style>")[0]
    desktop_css, mobile_and_rest = ticker_css.split("@media (max-width: 768px)", 1)
    mobile_css = mobile_and_rest.split("@media (prefers-reduced-motion")[0]
    assert "width: 100vw" not in desktop_css
    assert "border-radius: 12px" in desktop_css
    assert "width: 100vw" in mobile_css
    assert "border-radius: 0" in mobile_css


def test_tests_never_touch_real_site_data():
    assert "site_data" in str(flt.OUTPUT_FILE)
    assert "site_data" in str(flt.RAW_HISTORY_FILE)
