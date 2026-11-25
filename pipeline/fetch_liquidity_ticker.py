#!/usr/bin/env python3
"""Fetch 6-input Liquidity Pulse ticker + composite risk-on/risk-off score.

Inputs (equal weight):
  1. MOVE       Yahoo ^MOVE (1d, 1y)                         [+z, risk-off]
  2. VIX        FRED VIXCLS (1y history) + Yahoo ^VIX (5d)   [+z, risk-off]
  3. Truflation truflation.com badge (1y) + index-data       [+z, risk-off]
  4. HY OAS     FRED BAMLH0A0HYM2                             [+z, risk-off]
  5. Net Liq    FRED WALCL - WTREGEN - (RRPONTSYD * 1000)    [-z, risk-on]
  6. DXY        Yahoo DX-Y.NYB (1d, 1y)                      [+z, risk-off]

Formula:
  - 365-calendar-day window ending on each series' latest observation
  - Sample mean and sample stdev (n - 1); require n >= 20
  - Signed z (+z for risk-off inputs, -z for Net Liq)
  - Winsorize signed z to [-3, +3]
  - Require >= 4 of 6 active inputs (if 3+ stale/missing, fail closed on composite)
  - Score = round(clip(50 * mean(signed_z_winsorized), -100, +100))
  - Bands: <= -25 Risk-On (favor longs), -24..+24 Neutral (balanced), >= +25 Risk-Off (favor shorts)

Fail-closed: never invent values. On source failure, reuse prior value + as_of
date with status="stale". On composite failure (< 4 ok inputs), keep prior
score/band/lean and set top-level stale=true.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from market_data_io import validate_json_text  # noqa: E402
from workspace_paths import SITE_DATA_DIR  # noqa: E402

CT_TZ = ZoneInfo("America/Chicago")

OUTPUT_FILE = SITE_DATA_DIR / "liquidity_ticker.json"
RAW_HISTORY_FILE = SITE_DATA_DIR / "_raw" / "liquidity_ticker_history.csv"

USER_AGENT = (
    "scarcityabundance-dashboard/1.0 "
    "(liquidity-ticker; +https://jsheppard8989.github.io/ai-finance-tech-dashboard/)"
)

YAHOO_MOVE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE?interval=1d&range=1y"
YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
YAHOO_DXY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=1y"

FRED_URL_TMPL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
TRUFLATION_LATEST_URL = "https://truflation.com/api/index-data/us-inflation-rate"
TRUFLATION_HISTORY_URL = "https://truflation.com/api/index-badge-data/us-inflation-rate"

MIN_HISTORY_OBS = 20
MIN_COMPOSITE_INPUTS = 4
WINSOR_LIMIT = 3.0
HISTORY_CALENDAR_DAYS = 365
TOTAL_INPUTS = 6

INPUT_ORDER = ("move", "vix", "truflation", "hy_oas", "net_liq", "dxy")


def _now_ct() -> datetime:
    return datetime.now(CT_TZ)


def _fetch_text(url: str, *, timeout: int = 30, retries: int = 2, polite_delay: float = 0.0) -> str:
    if polite_delay > 0:
        time.sleep(polite_delay)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/csv, text/plain, */*",
                    "Connection": "close",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if getattr(resp, "status", 200) >= 400:
                    raise RuntimeError(f"HTTP {resp.status} for {url}")
                body = resp.read().decode("utf-8", errors="replace")
            if not body.strip():
                raise ValueError(f"Empty response from {url}")
            return body
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
    assert last_err is not None
    raise last_err


def _fetch_json(url: str, *, timeout: int = 30, retries: int = 2, polite_delay: float = 0.0) -> Any:
    raw = _fetch_text(url, timeout=timeout, retries=retries, polite_delay=polite_delay)
    return json.loads(raw)


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """Parse FRED fredgraph.csv text into sorted (YYYY-MM-DD, float) pairs."""
    dedup: dict[str, float] = {}
    lines = text.strip().splitlines()
    if not lines:
        return []
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        d_str, v_str = parts[0], parts[1]
        if idx == 0 and not _is_iso_date(d_str):
            continue
        if not _is_iso_date(d_str):
            continue
        if v_str in ("", ".", "nan", "NaN", "null", "None"):
            continue
        try:
            val = float(v_str)
        except ValueError:
            continue
        if not math.isfinite(val):
            continue
        dedup[d_str] = val
    return sorted(dedup.items())


def _is_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def parse_yahoo_chart(payload: dict) -> tuple[list[tuple[str, float]], str | None]:
    """Parse Yahoo v8 chart JSON into sorted (YYYY-MM-DD, close) pairs and as_of_time_ct."""
    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = (chart or {}).get("result") if isinstance(chart, dict) else None
    if not results or not isinstance(results, list):
        raise ValueError("Yahoo chart payload missing result")
    res = results[0]
    meta = res.get("meta") or {}
    timestamps = res.get("timestamp") or []
    quote_list = ((res.get("indicators") or {}).get("quote") or [])
    if not quote_list:
        raise ValueError("Yahoo chart payload missing indicators.quote")
    closes = quote_list[0].get("close") or []
    if len(timestamps) != len(closes):
        raise ValueError("Yahoo chart timestamp/close length mismatch")

    tz_name = meta.get("exchangeTimezoneName")
    ex_tz: Any = None
    if tz_name:
        try:
            ex_tz = ZoneInfo(tz_name)
        except Exception:
            ex_tz = None
    if ex_tz is None:
        offset_sec = int(meta.get("gmtoffset") or 0)
        ex_tz = timezone(timedelta(seconds=offset_sec))

    dedup: dict[str, float] = {}
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        try:
            val = float(close)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val):
            continue
        d_str = datetime.fromtimestamp(int(ts), tz=ex_tz).strftime("%Y-%m-%d")
        dedup[d_str] = val

    if not dedup:
        raise ValueError("Yahoo chart returned zero valid closes")

    as_of_time_ct: str | None = None
    reg_ts = meta.get("regularMarketTime")
    if reg_ts is not None:
        try:
            as_of_time_ct = datetime.fromtimestamp(int(reg_ts), tz=CT_TZ).strftime("%H:%M")
        except Exception:
            as_of_time_ct = None

    return sorted(dedup.items()), as_of_time_ct


def parse_truflation(
    badge_payload: dict | None,
    index_payload: dict | None = None,
) -> list[tuple[str, float]]:
    """Merge Truflation 1y badge series + ~31d index-data tail."""
    dedup: dict[str, float] = {}
    for payload in (badge_payload, index_payload):
        if not isinstance(payload, dict):
            continue
        dates = payload.get("index") or []
        vals = payload.get("truflation_us_cpi_frozen_yoy") or []
        if len(dates) != len(vals):
            raise ValueError("Truflation index/values length mismatch")
        for d_raw, v_raw in zip(dates, vals):
            d_str = str(d_raw).strip()[:10]
            if not _is_iso_date(d_str) or v_raw is None:
                continue
            try:
                val = float(v_raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(val):
                continue
            dedup[d_str] = val
    return sorted(dedup.items())


def compute_net_liq_series(
    walcl: list[tuple[str, float]],
    wtregen: list[tuple[str, float]],
    rrp: list[tuple[str, float]],
) -> dict[str, Any]:
    """Compute Net Liq ($ millions) = WALCL - WTREGEN - (RRPONTSYD * 1000).

    Forward-fills weekly WALCL and WTREGEN onto each daily RRP observation date
    using the latest weekly leg on or before that date. Fails closed if any leg
    is empty.
    """
    if not walcl or not wtregen or not rrp:
        raise ValueError("Net Liq requires non-empty WALCL, WTREGEN, and RRPONTSYD series")

    walcl_s = sorted(walcl)
    wtregen_s = sorted(wtregen)
    rrp_s = sorted(rrp)

    wi = 0
    ti = 0
    series: list[tuple[str, float]] = []
    for d_str, rrp_b in rrp_s:
        while wi + 1 < len(walcl_s) and walcl_s[wi + 1][0] <= d_str:
            wi += 1
        while ti + 1 < len(wtregen_s) and wtregen_s[ti + 1][0] <= d_str:
            ti += 1
        if walcl_s[wi][0] > d_str or wtregen_s[ti][0] > d_str:
            continue
        net_m = walcl_s[wi][1] - wtregen_s[ti][1] - (rrp_b * 1000.0)
        series.append((d_str, net_m))

    if not series:
        raise ValueError("No overlapping dates for WALCL, WTREGEN, and RRPONTSYD")

    latest_walcl_date, latest_walcl_val = walcl_s[-1]
    latest_wtregen_date, latest_wtregen_val = wtregen_s[-1]
    latest_rrp_date, latest_rrp_val = rrp_s[-1]

    return {
        "series": series,
        "walcl": round(latest_walcl_val, 3),
        "walcl_as_of": latest_walcl_date,
        "wtregen": round(latest_wtregen_val, 3),
        "wtregen_as_of": latest_wtregen_date,
        "rrpontsyd_usd_billions": round(latest_rrp_val, 4),
        "rrp_as_of": latest_rrp_date,
    }


def winsorize_z(z: float, limit: float = WINSOR_LIMIT) -> float:
    return max(-limit, min(limit, z))


def classify_score(score: int) -> tuple[str, str]:
    if score <= -25:
        return "Risk-On", "favor longs"
    if score >= 25:
        return "Risk-Off", "favor shorts"
    return "Neutral", "balanced"


def business_days_between(start_iso: str, end_iso: str) -> int:
    """Count weekday (Mon-Fri) steps from start_iso to end_iso (0 if start >= end)."""
    a = date.fromisoformat(start_iso)
    b = date.fromisoformat(end_iso)
    if a >= b:
        return 0
    days = 0
    cur = a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def compute_z_stats(
    series: list[tuple[str, float]],
    *,
    invert: bool = False,
    min_obs: int = MIN_HISTORY_OBS,
    window_days: int = HISTORY_CALENDAR_DAYS,
) -> dict[str, Any]:
    """Compute latest, prior, change, 1y sample mean/stdev, raw z, signed z, winsorized z."""
    if not series:
        raise ValueError("Empty series")
    ordered = sorted(dict(series).items())
    latest_date, latest_val = ordered[-1]
    prior_date: str | None = None
    prior_val: float | None = None
    change: float | None = None
    if len(ordered) >= 2:
        prior_date, prior_val = ordered[-2]
        change = latest_val - prior_val

    cutoff = (date.fromisoformat(latest_date) - timedelta(days=window_days)).isoformat()
    window = [v for d, v in ordered if cutoff <= d <= latest_date]
    n = len(window)
    if n < min_obs:
        return {
            "latest_date": latest_date,
            "latest_val": latest_val,
            "prior_date": prior_date,
            "prior_val": prior_val,
            "change": change,
            "n": n,
            "mu": None,
            "sigma": None,
            "z": None,
            "signed_z": None,
            "signed_z_winsorized": None,
            "status": "insufficient_history",
        }

    mu = statistics.mean(window)
    sigma = statistics.stdev(window)
    z = (latest_val - mu) / sigma if sigma > 0 else 0.0
    signed_z = -z if invert else z
    signed_z_w = winsorize_z(signed_z)

    return {
        "latest_date": latest_date,
        "latest_val": latest_val,
        "prior_date": prior_date,
        "prior_val": prior_val,
        "change": change,
        "n": n,
        "mu": mu,
        "sigma": sigma,
        "z": z,
        "signed_z": signed_z,
        "signed_z_winsorized": signed_z_w,
        "status": "ok",
    }


def compute_composite(
    inputs: list[dict[str, Any]],
    *,
    min_inputs: int = MIN_COMPOSITE_INPUTS,
) -> dict[str, Any] | None:
    """Compute composite score/band/lean from active ok inputs; None if < min_inputs."""
    active = [
        inp for inp in inputs
        if inp.get("status") == "ok" and inp.get("signed_z_winsorized") is not None
    ]
    if len(active) < min_inputs:
        return None
    mean_sz = sum(float(inp["signed_z_winsorized"]) for inp in active) / len(active)
    raw_score = 50.0 * mean_sz
    clamped = max(-100.0, min(100.0, raw_score))
    score = int(round(clamped))
    band, lean = classify_score(score)
    return {
        "score": score,
        "band": band,
        "lean": lean,
        "mean_signed_z": round(mean_sz, 2),
        "inputs_used": len(active),
    }


def load_raw_history(path: Path | None = None) -> dict[str, list[tuple[str, float]]]:
    path = path or RAW_HISTORY_FILE
    out: dict[str, list[tuple[str, float]]] = {}
    if not path.is_file():
        return out
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            buckets: dict[str, dict[str, float]] = {}
            for row in reader:
                sid = (row.get("series_id") or "").strip()
                d_str = (row.get("date") or "").strip()
                v_str = (row.get("value") or "").strip()
                if not sid or not _is_iso_date(d_str):
                    continue
                try:
                    val = float(v_str)
                except ValueError:
                    continue
                if math.isfinite(val):
                    buckets.setdefault(sid, {})[d_str] = val
            for sid, mapping in buckets.items():
                out[sid] = sorted(mapping.items())
    except Exception:
        return {}
    return out


def save_raw_history(series_map: dict[str, list[tuple[str, float]]], path: Path | None = None) -> None:
    path = path or RAW_HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["series_id", "date", "value"])
        for sid in sorted(series_map):
            ordered = sorted(dict(series_map[sid]).items())
            if ordered:
                latest_d = ordered[-1][0]
                cutoff = (date.fromisoformat(latest_d) - timedelta(days=400)).isoformat()
                ordered = [(d, v) for d, v in ordered if d >= cutoff]
            for d_str, val in ordered:
                writer.writerow([sid, d_str, f"{val:.8g}"])
    tmp.replace(path)


def _load_prior_output(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        ok, _, data = validate_json_text(raw, label=str(path))
        if ok and isinstance(data, dict):
            return data
    except OSError:
        pass
    return None


def _save_output(payload: dict[str, Any], path: Path) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    ok, msg, _ = validate_json_text(text, label="liquidity_ticker.json")
    if not ok:
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _format_input_entry(
    *,
    input_id: str,
    label: str,
    name: str,
    stats: dict[str, Any],
    source: str,
    history_source: str | None = None,
    as_of_time_ct: str | None = None,
    extra: dict[str, Any] | None = None,
    today_ct: str,
    max_biz_lag: int | None = None,
    max_cal_lag: int | None = None,
) -> dict[str, Any]:
    val = stats["latest_val"]
    prior_val = stats["prior_val"]
    chg = stats["change"]
    as_of = stats["latest_date"]
    status = stats["status"]

    if status == "ok":
        if max_biz_lag is not None and business_days_between(as_of, today_ct) > max_biz_lag:
            status = "stale"
        elif max_cal_lag is not None:
            cal_lag = (date.fromisoformat(today_ct) - date.fromisoformat(as_of)).days
            if cal_lag > max_cal_lag:
                status = "stale"

    if input_id in ("move", "vix"):
        display = f"{val:.1f}"
        chg_round = round(chg, 2) if chg is not None else None
    elif input_id in ("truflation", "hy_oas"):
        display = f"{val:.2f}%"
        chg_round = round(chg, 5) if chg is not None else None
    elif input_id == "dxy":
        display = f"{val:.2f}"
        chg_round = round(chg, 3) if chg is not None else None
    elif input_id == "net_liq":
        display = f"${val / 1_000_000.0:.2f}T"
        chg_round = round(chg, 2) if chg is not None else None
    else:
        display = str(round(val, 2))
        chg_round = round(chg, 3) if chg is not None else None

    entry: dict[str, Any] = {
        "id": input_id,
        "label": label,
        "name": name,
    }
    if input_id == "net_liq":
        entry["value_usd_millions"] = round(val, 2)
        entry["display"] = display
        entry["as_of"] = as_of
        if extra:
            entry.update(extra)
        entry["prior_usd_millions"] = round(prior_val, 2) if prior_val is not None else None
        entry["prior_as_of"] = stats["prior_date"]
        entry["change"] = chg_round
        entry["change_usd_billions"] = round(chg / 1000.0, 2) if chg is not None else None
    else:
        entry["value"] = round(val, 6)
        entry["display"] = display
        entry["as_of"] = as_of
        if as_of_time_ct:
            entry["as_of_time_ct"] = as_of_time_ct
        entry["prior"] = round(prior_val, 6) if prior_val is not None else None
        entry["prior_as_of"] = stats["prior_date"]
        entry["change"] = chg_round

    entry["n"] = stats["n"]
    entry["mu"] = round(stats["mu"], 6) if stats["mu"] is not None else None
    entry["sigma"] = round(stats["sigma"], 6) if stats["sigma"] is not None else None
    entry["z"] = round(stats["z"], 2) if stats["z"] is not None else None
    entry["signed_z"] = round(stats["signed_z"], 2) if stats["signed_z"] is not None else None
    entry["signed_z_winsorized"] = (
        round(stats["signed_z_winsorized"], 2)
        if stats["signed_z_winsorized"] is not None
        else None
    )
    entry["source"] = source
    if history_source:
        entry["history_source"] = history_source
    entry["status"] = status
    return entry


def _stale_fallback_entry(prior_map: dict[str, dict[str, Any]], input_id: str, reason: str) -> dict[str, Any] | None:
    prev = prior_map.get(input_id)
    if not isinstance(prev, dict):
        return None
    copy = dict(prev)
    copy["status"] = "stale"
    copy["stale_reason"] = reason
    return copy


def run_fetch(
    *,
    fetch_text: Callable[..., str] = _fetch_text,
    fetch_json: Callable[..., Any] = _fetch_json,
    output_file: Path | None = None,
    raw_history_file: Path | None = None,
    now_ct: datetime | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """Fetch all 6 inputs, compute Liquidity Pulse, and write JSON fail-closed.

    Returns (exit_code, payload_or_none). exit_code is 0 when composite updated
    with >= 4 fresh ok inputs, else 1.
    """
    out_path = output_file or OUTPUT_FILE
    raw_path = raw_history_file or RAW_HISTORY_FILE
    now = now_ct or _now_ct()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    today_str = now.strftime("%Y-%m-%d")

    prior_doc = _load_prior_output(out_path)
    prior_map: dict[str, dict[str, Any]] = {}
    if isinstance(prior_doc, dict):
        for item in prior_doc.get("inputs") or []:
            if isinstance(item, dict) and item.get("id"):
                prior_map[item["id"]] = item

    cached_hist = load_raw_history(raw_path)
    updated_hist = dict(cached_hist)
    results: dict[str, dict[str, Any]] = {}
    fetch_errors: dict[str, str] = {}

    # 1. MOVE (Yahoo ^MOVE)
    try:
        payload = fetch_json(YAHOO_MOVE_URL)
        series, time_ct = parse_yahoo_chart(payload)
        updated_hist["move"] = series
        st = compute_z_stats(series, invert=False)
        results["move"] = _format_input_entry(
            input_id="move",
            label="MOVE",
            name="MOVE (ICE BofA)",
            stats=st,
            source="yahoo_chart_^MOVE",
            as_of_time_ct=time_ct,
            today_ct=today_str,
            max_biz_lag=1,
        )
    except Exception as exc:
        fetch_errors["move"] = str(exc)

    # 2. VIX (FRED VIXCLS 1y + Yahoo ^VIX 5d)
    try:
        fred_series: list[tuple[str, float]] = []
        hist_src = "fred_VIXCLS"
        try:
            fred_csv = fetch_text(FRED_URL_TMPL.format(series_id="VIXCLS"), polite_delay=0.6)
            fred_series = parse_fred_csv(fred_csv)
        except Exception:
            if cached_hist.get("vix"):
                fred_series = list(cached_hist["vix"])
                hist_src = "cached_raw_history"
            else:
                fred_series = []

        yahoo_series: list[tuple[str, float]] = []
        time_ct = None
        vix_source = "yahoo_chart_^VIX"
        try:
            vix_payload = fetch_json(YAHOO_VIX_URL)
            yahoo_series, time_ct = parse_yahoo_chart(vix_payload)
        except Exception:
            yahoo_series = []

        if yahoo_series and fred_series:
            merged = dict(fred_series)
            merged.update(dict(yahoo_series))
            series = sorted(merged.items())
        elif yahoo_series:
            raise RuntimeError("VIX history unavailable (FRED failed and no cached history)")
        elif fred_series:
            series = fred_series
            vix_source = "fred_VIXCLS"
        else:
            raise RuntimeError("Both FRED VIXCLS and Yahoo ^VIX failed")

        updated_hist["vix"] = series
        st = compute_z_stats(series, invert=False)
        results["vix"] = _format_input_entry(
            input_id="vix",
            label="VIX",
            name="Cboe Volatility Index",
            stats=st,
            source=vix_source,
            history_source=hist_src,
            as_of_time_ct=time_ct,
            today_ct=today_str,
            max_biz_lag=1,
        )
    except Exception as exc:
        fetch_errors["vix"] = str(exc)

    # 3. Truflation US CPI YoY
    try:
        badge_payload = None
        index_payload = None
        hist_src = "truflation_index-badge-data_us-inflation-rate"
        try:
            badge_payload = fetch_json(TRUFLATION_HISTORY_URL)
        except Exception:
            badge_payload = None
        try:
            index_payload = fetch_json(TRUFLATION_LATEST_URL)
        except Exception:
            index_payload = None

        if badge_payload is not None:
            series = parse_truflation(badge_payload, index_payload)
            src = (
                "truflation_index-data_us-inflation-rate"
                if index_payload is not None
                else hist_src
            )
        elif index_payload is not None and cached_hist.get("truflation"):
            tail = parse_truflation(None, index_payload)
            merged = dict(cached_hist["truflation"])
            merged.update(dict(tail))
            series = sorted(merged.items())
            src = "truflation_index-data_us-inflation-rate"
            hist_src = "cached_raw_history"
        else:
            raise RuntimeError("Truflation endpoints unavailable")

        if not series:
            raise RuntimeError("Truflation returned empty series")

        updated_hist["truflation"] = series
        st = compute_z_stats(series, invert=False)
        results["truflation"] = _format_input_entry(
            input_id="truflation",
            label="TRUFL",
            name="Truflation US CPI YoY",
            stats=st,
            source=src,
            history_source=hist_src,
            today_ct=today_str,
            max_cal_lag=2,
        )
    except Exception as exc:
        fetch_errors["truflation"] = str(exc)

    # 4. HY OAS (FRED BAMLH0A0HYM2 — normal 1-business-day ICE lag)
    try:
        hy_csv = fetch_text(FRED_URL_TMPL.format(series_id="BAMLH0A0HYM2"), polite_delay=0.6)
        series = parse_fred_csv(hy_csv)
        if not series:
            raise RuntimeError("FRED BAMLH0A0HYM2 returned empty series")
        updated_hist["hy_oas"] = series
        st = compute_z_stats(series, invert=False)
        results["hy_oas"] = _format_input_entry(
            input_id="hy_oas",
            label="HY OAS",
            name="ICE BofA US High Yield OAS",
            stats=st,
            source="fred_BAMLH0A0HYM2",
            today_ct=today_str,
            max_biz_lag=2,  # T-1 is normal; >2 biz days behind is stale
        )
    except Exception as exc:
        fetch_errors["hy_oas"] = str(exc)

    # 5. Fed Net Liquidity (FRED WALCL - WTREGEN - RRPONTSYD * 1000) — inverted (-z)
    try:
        walcl = parse_fred_csv(fetch_text(FRED_URL_TMPL.format(series_id="WALCL"), polite_delay=0.6))
        wtregen = parse_fred_csv(fetch_text(FRED_URL_TMPL.format(series_id="WTREGEN"), polite_delay=0.6))
        rrp = parse_fred_csv(fetch_text(FRED_URL_TMPL.format(series_id="RRPONTSYD"), polite_delay=0.6))
        nl = compute_net_liq_series(walcl, wtregen, rrp)
        series = nl["series"]
        updated_hist["net_liq"] = series
        st = compute_z_stats(series, invert=True)
        results["net_liq"] = _format_input_entry(
            input_id="net_liq",
            label="NET LIQ",
            name="Fed Net Liquidity",
            stats=st,
            source="fred_WALCL_WTREGEN_RRPONTSYD",
            extra={
                "walcl": nl["walcl"],
                "walcl_as_of": nl["walcl_as_of"],
                "wtregen": nl["wtregen"],
                "wtregen_as_of": nl["wtregen_as_of"],
                "rrpontsyd_usd_billions": nl["rrpontsyd_usd_billions"],
                "rrp_as_of": nl["rrp_as_of"],
            },
            today_ct=today_str,
            max_biz_lag=1,
        )
    except Exception as exc:
        fetch_errors["net_liq"] = str(exc)

    # 6. DXY (Yahoo DX-Y.NYB) — higher = risk-off (+z)
    try:
        dxy_payload = fetch_json(YAHOO_DXY_URL)
        series, time_ct = parse_yahoo_chart(dxy_payload)
        updated_hist["dxy"] = series
        st = compute_z_stats(series, invert=False)
        results["dxy"] = _format_input_entry(
            input_id="dxy",
            label="DXY",
            name="DXY (ICE U.S. Dollar Index)",
            stats=st,
            source="yahoo_chart_DX-Y.NYB",
            as_of_time_ct=time_ct,
            today_ct=today_str,
            max_biz_lag=1,
        )
    except Exception as exc:
        fetch_errors["dxy"] = str(exc)

    # Save any fresh history series we did receive
    if updated_hist != cached_hist:
        save_raw_history(updated_hist, raw_path)

    # Assemble ordered inputs using fail-closed fallbacks for failed ones
    final_inputs: list[dict[str, Any]] = []
    for iid in INPUT_ORDER:
        if iid in results:
            final_inputs.append(results[iid])
        else:
            fb = _stale_fallback_entry(prior_map, iid, fetch_errors.get(iid, "fetch failed"))
            if fb is not None:
                final_inputs.append(fb)

    if not final_inputs:
        # Total failure with no prior JSON on disk
        return 1, None

    # If all 6 failed and prior exists, preserve prior values/dates with stale=True
    if not results and prior_doc is not None:
        stale_doc = dict(prior_doc)
        stale_doc["stale"] = True
        stale_doc["last_attempt_ct"] = now_str
        stale_doc["inputs"] = final_inputs
        _save_output(stale_doc, out_path)
        return 1, stale_doc

    comp = compute_composite(final_inputs, min_inputs=MIN_COMPOSITE_INPUTS)
    if comp is not None:
        doc = {
            "as_of_ct": now_str,
            "last_attempt_ct": now_str,
            "stale": False,
            "model": "liquidity_pulse_v1",
            "disclaimer": "In-house model, not advice.",
            "score": comp["score"],
            "band": comp["band"],
            "lean": comp["lean"],
            "mean_signed_z": comp["mean_signed_z"],
            "inputs_used": comp["inputs_used"],
            "inputs_total": TOTAL_INPUTS,
            "inputs": final_inputs,
        }
        _save_output(doc, out_path)
        return 0, doc

    # Composite cannot be computed (< 4 ok inputs): keep prior composite if present
    if prior_doc is not None:
        stale_doc = dict(prior_doc)
        stale_doc["stale"] = True
        stale_doc["last_attempt_ct"] = now_str
        stale_doc["inputs_used"] = sum(1 for i in final_inputs if i.get("status") == "ok")
        stale_doc["inputs_total"] = TOTAL_INPUTS
        stale_doc["inputs"] = final_inputs
        _save_output(stale_doc, out_path)
        return 1, stale_doc

    # No prior composite and fewer than 4 ok inputs
    partial_doc = {
        "as_of_ct": now_str,
        "last_attempt_ct": now_str,
        "stale": True,
        "model": "liquidity_pulse_v1",
        "disclaimer": "In-house model, not advice.",
        "score": None,
        "band": "Unavailable",
        "lean": "unavailable",
        "mean_signed_z": None,
        "inputs_used": sum(1 for i in final_inputs if i.get("status") == "ok"),
        "inputs_total": TOTAL_INPUTS,
        "inputs": final_inputs,
    }
    _save_output(partial_doc, out_path)
    return 1, partial_doc


def main() -> int:
    code, doc = run_fetch()
    if doc is None:
        print("✗ Liquidity ticker: all sources failed and no prior data on disk.")
        return 1
    stale_tag = " [STALE]" if doc.get("stale") else ""
    print(
        f"Liquidity Pulse{stale_tag}: {doc.get('score')} {doc.get('band')} "
        f"({doc.get('lean')}) — {doc.get('inputs_used')}/{doc.get('inputs_total')} inputs"
    )
    for inp in doc.get("inputs") or []:
        print(
            f"  {inp.get('label'):8s} {inp.get('display'):>8s} "
            f"as_of={inp.get('as_of')} z={inp.get('signed_z_winsorized')} "
            f"status={inp.get('status')}"
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
