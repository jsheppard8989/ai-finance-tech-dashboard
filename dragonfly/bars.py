"""Daily bars for the Dragonfly 7 scanner (Phase 1 source: Yahoo via yfinance).

One yfinance history call per name, cached as JSON under
dragonfly/state/live/cache/bars/ (gitignored). Refresh is incremental: only
bars since the last cached session are fetched. ATR, 20-day average dollar
volume (ADV), and relative volume are computed from the cache, never typed.

Every payload is stamped source="yahoo", provisional=True. The governor
blocks provisional data from live approval (risk_math.structural_blocks).

Guarded by dragonfly/guards.py (pipeline lock + daemon windows). Cache-first:
the CLI skips the network for caches younger than DRAGONFLY_BARS_MAX_AGE_MINUTES (30).

Python 3.9 compatible. Run: python3 dragonfly/bars.py AAPL MSFT NVDA [--allow-daemon-window]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonfly import guards  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "yahoo"
ATR_PERIOD = 14
ADV_WINDOW = 20
FULL_PERIOD = "1y"
# If a re-fetched completed bar's close moved more than this, Yahoo re-adjusted
# history (split or dividend). Refetch the full window instead of merging.
ADJUSTMENT_TOLERANCE = 0.005
# Cache-first: CLI / builder skip the network when the cache is younger than this.
ENV_MAX_AGE = "DRAGONFLY_BARS_MAX_AGE_MINUTES"
DEFAULT_MAX_AGE_MINUTES = 30

Bar = dict  # {"date": "YYYY-MM-DD", "open", "high", "low", "close", "volume"}
Fetcher = Callable[..., List[Bar]]


class BarsUnavailable(Exception):
    """No usable history. Fail closed; never substitute data."""

    def __init__(self, ticker: str, reason: str, detail: str = ""):
        self.ticker = ticker
        self.reason = reason
        self.detail = detail
        super().__init__(f"{ticker}: {reason}{(' - ' + detail) if detail else ''}")


def state_dir() -> Path:
    override = os.environ.get("DRAGONFLY_STATE_DIR")
    return Path(override) if override else ROOT / "dragonfly" / "state" / "live"


def cache_path(ticker: str) -> Path:
    return state_dir() / "cache" / "bars" / f"{ticker.upper()}.json"


# ---------------------------------------------------------------- fetch layer

def frame_to_bars(frame) -> List[Bar]:
    """Convert a yfinance history DataFrame to plain bar dicts. Drops NaN rows."""
    bars: List[Bar] = []
    if frame is None or len(frame) == 0:
        return bars
    for idx, row in frame.iterrows():
        vals = [row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"), row.get("Volume")]
        if any(v is None or v != v for v in vals):  # NaN check without numpy
            continue
        day = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        bars.append(
            {
                "date": day.isoformat(),
                "open": float(vals[0]),
                "high": float(vals[1]),
                "low": float(vals[2]),
                "close": float(vals[3]),
                "volume": int(vals[4]),
            }
        )
    return bars


def yahoo_history(ticker: str, start: Optional[date] = None, period: Optional[str] = None) -> List[Bar]:
    """Exactly one yfinance history call. Split/dividend adjusted daily bars.

    Guarded: refuses while the site pipeline holds its lock or inside a
    daemon window (dragonfly.guards).
    """
    guards.before_fetch()
    import yfinance as yf  # lazy: tests never import it

    tk = yf.Ticker(ticker)
    if start is not None:
        frame = tk.history(start=start.isoformat(), interval="1d", auto_adjust=True, actions=False)
    else:
        frame = tk.history(period=period or FULL_PERIOD, interval="1d", auto_adjust=True, actions=False)
    return frame_to_bars(frame)


# ---------------------------------------------------------------- cache layer

def load_cache(ticker: str) -> Optional[dict]:
    path = cache_path(ticker)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("bars"):
        return None
    return data


def save_cache(ticker: str, payload: dict) -> None:
    path = cache_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(path)


def _payload(ticker: str, bars: Sequence[Bar], mode: str) -> dict:
    return {
        "ticker": ticker.upper(),
        "source": SOURCE,
        "provisional": True,
        "adjusted": True,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_fetch_mode": mode,
        "bars": list(bars),
    }


def merge_bars(cached: Sequence[Bar], fresh: Sequence[Bar]) -> List[Bar]:
    """Fresh bars replace cached bars from the first fresh date onward."""
    if not fresh:
        return list(cached)
    first = fresh[0]["date"]
    kept = [b for b in cached if b["date"] < first]
    return kept + sorted(fresh, key=lambda b: b["date"])


def default_max_age_minutes() -> float:
    return float(os.environ.get(ENV_MAX_AGE, DEFAULT_MAX_AGE_MINUTES))


def cache_age_minutes(payload: Mapping, now: Optional[datetime] = None) -> Optional[float]:
    try:
        fetched = datetime.fromisoformat(str(payload.get("fetched_at")))
    except (TypeError, ValueError):
        return None
    now = now or datetime.now().astimezone()
    if fetched.tzinfo is None:
        fetched = fetched.astimezone()
    return (now - fetched).total_seconds() / 60.0


def refresh(
    ticker: str,
    fetcher: Optional[Fetcher] = None,
    full_period: str = FULL_PERIOD,
    max_age_minutes: Optional[float] = None,
) -> dict:
    """Return the cached payload for `ticker`, fetching only what is missing.

    With a cache: re-fetch from the second-to-last cached session (one call).
    The last cached bar may have been a partial intraday bar, so it is always
    replaced. The second-to-last bar is a completed session and is used to
    detect a history re-adjustment, which triggers one full re-fetch.
    """
    fetch = fetcher or yahoo_history
    ticker = ticker.upper()
    cached = load_cache(ticker)
    if cached and max_age_minutes is not None:
        age = cache_age_minutes(cached)
        if age is not None and 0 <= age < max_age_minutes:
            return dict(cached, last_fetch_mode="cache")  # cache-first: no network
    if cached and len(cached["bars"]) >= 2:
        anchor = cached["bars"][-2]
        try:
            fresh = fetch(ticker, start=date.fromisoformat(anchor["date"]))
        except guards.GuardBlocked:
            raise
        except Exception as exc:  # network/provider failure
            raise BarsUnavailable(ticker, "fetch_failed", str(exc)) from exc
        if fresh:
            overlap = [b for b in fresh if b["date"] == anchor["date"]]
            if overlap and anchor["close"] and abs(overlap[0]["close"] / anchor["close"] - 1) > ADJUSTMENT_TOLERANCE:
                cached = None  # re-adjusted history: fall through to a full fetch
            else:
                payload = _payload(ticker, merge_bars(cached["bars"], fresh), "incremental")
                save_cache(ticker, payload)
                return payload
        else:
            return cached  # nothing new; keep the cache as-is
    try:
        bars = fetch(ticker, period=full_period)
    except guards.GuardBlocked:
        raise
    except Exception as exc:
        raise BarsUnavailable(ticker, "fetch_failed", str(exc)) from exc
    if not bars:
        raise BarsUnavailable(ticker, "empty_history")
    payload = _payload(ticker, bars, "full")
    save_cache(ticker, payload)
    return payload


# ---------------------------------------------------------------- math

def true_ranges(bars: Sequence[Mapping]) -> List[float]:
    out: List[float] = []
    prev_close = None
    for b in bars:
        hl = b["high"] - b["low"]
        if prev_close is None:
            out.append(hl)
        else:
            out.append(max(hl, abs(b["high"] - prev_close), abs(b["low"] - prev_close)))
        prev_close = b["close"]
    return out


def atr(bars: Sequence[Mapping], period: int = ATR_PERIOD) -> Optional[float]:
    """Wilder ATR. Needs period + 1 bars (the first bar has no prior close)."""
    if len(bars) < period + 1:
        return None
    trs = true_ranges(bars)[1:]
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def adv_dollars(bars: Sequence[Mapping], window: int = ADV_WINDOW) -> Optional[float]:
    if len(bars) < window:
        return None
    tail = bars[-window:]
    return sum(b["close"] * b["volume"] for b in tail) / window


def adv_shares(bars: Sequence[Mapping], window: int = ADV_WINDOW) -> Optional[float]:
    if len(bars) < window:
        return None
    return sum(b["volume"] for b in bars[-window:]) / window


def relative_volume(bars: Sequence[Mapping], window: int = ADV_WINDOW) -> Optional[float]:
    """Last bar's volume / mean volume of the `window` bars before it."""
    if len(bars) < window + 1:
        return None
    base = adv_shares(bars[:-1], window)
    if not base:
        return None
    return bars[-1]["volume"] / base


def _ny_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York"))


def last_bar_partial(bars: Sequence[Mapping], now_ny: Optional[datetime] = None) -> bool:
    """True when the last bar is today's session and the close has not printed."""
    if not bars:
        return False
    now_ny = now_ny or _ny_now()
    return bars[-1]["date"] == now_ny.date().isoformat() and (now_ny.hour, now_ny.minute) < (16, 0)


def metrics(bars: Sequence[Mapping], partial_last: bool = False) -> dict:
    """ATR / ADV from completed sessions; relative volume on the latest bar.

    If the last bar is a partial intraday bar, ATR and ADV exclude it and
    `rvol` is its volume so far over the completed 20-day average (a raw pace,
    not time-of-day normalized; flagged by `rvol_partial`).
    """
    completed = list(bars[:-1]) if partial_last and bars else list(bars)
    last = bars[-1] if bars else None
    if partial_last and last is not None:
        base = adv_shares(completed)
        rvol = (last["volume"] / base) if base else None
    else:
        rvol = relative_volume(completed)
    a = atr(completed)
    adv_d = adv_dollars(completed)
    adv_s = adv_shares(completed)
    return {
        "as_of_bar": last["date"] if last else None,
        "last_price": last["close"] if last else None,
        "atr14": round(a, 4) if a is not None else None,
        "adv20_dollars": round(adv_d, 2) if adv_d is not None else None,
        "adv20_shares": round(adv_s, 1) if adv_s is not None else None,
        "rvol20": round(rvol, 3) if rvol is not None else None,
        "rvol_partial": bool(partial_last),
        "completed_bars": len(completed),
        "source": SOURCE,
        "provisional": True,
    }


def ticker_metrics(
    ticker: str,
    fetcher: Optional[Fetcher] = None,
    now_ny: Optional[datetime] = None,
    max_age_minutes: Optional[float] = None,
) -> dict:
    payload = refresh(ticker, fetcher=fetcher, max_age_minutes=max_age_minutes)
    bars = payload["bars"]
    out = metrics(bars, partial_last=last_bar_partial(bars, now_ny))
    out["ticker"] = payload["ticker"]
    out["fetch_mode"] = payload.get("last_fetch_mode")
    return out


def main(argv: Sequence[str]) -> int:
    if "--allow-daemon-window" in argv:
        os.environ[guards.ENV_ALLOW_WINDOW] = "1"
    tickers = [t for t in argv if not t.startswith("-")] or ["AAPL", "MSFT", "NVDA"]
    try:
        guards.preflight()
    except guards.GuardBlocked as exc:
        print(json.dumps({"blocked": exc.reason, "detail": exc.detail}))
        return 2
    results = []
    total_start = time.perf_counter()
    for t in tickers:
        start = time.perf_counter()
        try:
            m = ticker_metrics(t, max_age_minutes=default_max_age_minutes())
        except guards.GuardBlocked as exc:
            print(json.dumps({"blocked": exc.reason, "detail": exc.detail, "partial_results": results}))
            return 2
        except BarsUnavailable as exc:
            m = {"ticker": t, "unavailable": exc.reason, "detail": exc.detail}
        m["seconds"] = round(time.perf_counter() - start, 3)
        results.append(m)
    print(json.dumps({"results": results, "total_seconds": round(time.perf_counter() - total_start, 3)}, indent=1))
    return 0 if all("unavailable" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
