"""Option chains for Dragonfly 7 (Phase 1 source: Yahoo via yfinance).

`get_chain(ticker, expiration)` makes one `Ticker.option_chain(exp)` call for a
single expiration and keeps bid, ask, volume, open interest, and Yahoo's
implied volatility per contract. Every chain is stamped
source="yahoo", provisional=True.

Fail closed: a missing expiration list, an expiration Yahoo does not list, a
provider error, or an empty chain raises `ChainUnavailable` with a reason code.
Nothing is filled in. A missing volume/OI/bid/ask stays None and a None never
passes `contract_passes_gates`.

Chains are for an explicit scanner shortlist only (default cap 20 names,
DRAGONFLY_CHAINS_MAX_NAMES); a larger list is refused, never truncated.
Guarded by dragonfly/guards.py. Cache-first for a named expiration.

Python 3.9 compatible. Run: python3 dragonfly/chains.py AAPL MSFT [--expiration YYYY-MM-DD]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonfly import guards  # noqa: E402
from dragonfly.risk_math import (  # noqa: E402
    MAX_OPTION_SPREAD_PCT,
    MIN_OPTION_OPEN_INTEREST,
    MIN_OPTION_VOLUME,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "yahoo"
# Chains are pulled for an explicit scanner shortlist only, never the watchlist.
ENV_MAX_NAMES = "DRAGONFLY_CHAINS_MAX_NAMES"
DEFAULT_MAX_NAMES = 20
ENV_MAX_AGE = "DRAGONFLY_CHAINS_MAX_AGE_MINUTES"
DEFAULT_MAX_AGE_MINUTES = 15
KEEP = ("contractSymbol", "strike", "bid", "ask", "volume", "openInterest", "impliedVolatility", "lastTradeDate")


class ShortlistRefused(ValueError):
    """The chains entry point was handed more than an explicit small shortlist."""


class ChainUnavailable(Exception):
    """Reasons: fetch_failed, no_expirations, expiration_not_listed,
    empty_chain, no_expiration_in_range."""

    def __init__(self, ticker: str, reason: str, detail: str = ""):
        self.ticker = ticker
        self.reason = reason
        self.detail = detail
        super().__init__(f"{ticker}: {reason}{(' - ' + detail) if detail else ''}")


def _clean(value: Any) -> Any:
    """NaN/NaT/None -> None. Numpy scalars -> Python. Timestamps -> ISO."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _records(frame) -> List[dict]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
    else:
        rows = list(frame)
    out = []
    for row in rows:
        rec = {k: _clean(row.get(k)) for k in KEEP}
        for k in ("volume", "openInterest"):
            if rec[k] is not None:
                rec[k] = int(rec[k])
        out.append(rec)
    return out


def default_ticker_factory(symbol: str):
    guards.before_fetch()  # pipeline lock + daemon window; raises GuardBlocked
    import yfinance as yf  # lazy: tests never import it

    return yf.Ticker(symbol)


def list_expirations(ticker: str, ticker_factory: Callable = default_ticker_factory) -> List[str]:
    try:
        exps = list(ticker_factory(ticker).options or ())
    except guards.GuardBlocked:
        raise
    except Exception as exc:
        raise ChainUnavailable(ticker, "fetch_failed", str(exc)) from exc
    if not exps:
        raise ChainUnavailable(ticker, "no_expirations")
    return exps


def pick_expiration(expirations: Iterable[str], today: date, min_days: int = 7, max_days: int = 45) -> str:
    """First listed expiration between today+min_days and today+max_days."""
    lo = today + timedelta(days=min_days)
    hi = today + timedelta(days=max_days)
    for exp in sorted(expirations):
        d = date.fromisoformat(exp)
        if lo <= d <= hi:
            return exp
    raise ChainUnavailable("", "no_expiration_in_range", f"{lo.isoformat()}..{hi.isoformat()}")


def get_chain(ticker: str, expiration: str, ticker_factory: Callable = default_ticker_factory) -> dict:
    """One expiration. Raises ChainUnavailable instead of returning fake data."""
    ticker = ticker.upper()
    try:
        tk = ticker_factory(ticker)
        exps = list(tk.options or ())
    except guards.GuardBlocked:
        raise
    except Exception as exc:
        raise ChainUnavailable(ticker, "fetch_failed", str(exc)) from exc
    if not exps:
        raise ChainUnavailable(ticker, "no_expirations")
    if expiration not in exps:
        raise ChainUnavailable(ticker, "expiration_not_listed", expiration)
    try:
        oc = tk.option_chain(expiration)
    except guards.GuardBlocked:
        raise
    except Exception as exc:
        raise ChainUnavailable(ticker, "fetch_failed", str(exc)) from exc
    calls = _records(getattr(oc, "calls", None))
    puts = _records(getattr(oc, "puts", None))
    if not calls and not puts:
        raise ChainUnavailable(ticker, "empty_chain", expiration)
    underlying = getattr(oc, "underlying", None)
    spot = underlying.get("regularMarketPrice") if isinstance(underlying, Mapping) else None
    return {
        "ticker": ticker,
        "expiration": expiration,
        "source": SOURCE,
        "provisional": True,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "underlying_price": _clean(spot),
        "calls": calls,
        "puts": puts,
    }


def contract_passes_gates(contract: Mapping) -> bool:
    """Plan section 6 option gates. Any missing field fails (fail closed)."""
    bid, ask = contract.get("bid"), contract.get("ask")
    oi, vol = contract.get("openInterest"), contract.get("volume")
    if bid is None or ask is None or oi is None or vol is None:
        return False
    bid, ask = Decimal(str(bid)), Decimal(str(ask))
    if bid <= 0 or ask < bid:
        return False
    mid = (bid + ask) / 2
    if (ask - bid) / mid > MAX_OPTION_SPREAD_PCT:
        return False
    return int(oi) >= MIN_OPTION_OPEN_INTEREST and int(vol) >= MIN_OPTION_VOLUME


def state_dir() -> Path:
    override = os.environ.get("DRAGONFLY_STATE_DIR")
    return Path(override) if override else ROOT / "dragonfly" / "state" / "live"


def save_chain(chain: Mapping) -> Path:
    path = state_dir() / "cache" / "chains" / chain["ticker"] / f"{chain['expiration']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chain, indent=1), encoding="utf-8")
    return path


def load_cached_chain(ticker: str, expiration: str, max_age_minutes: float) -> Optional[dict]:
    path = state_dir() / "cache" / "chains" / ticker.upper() / f"{expiration}.json"
    try:
        chain = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(chain["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    age = (datetime.now().astimezone() - fetched).total_seconds() / 60.0
    return chain if 0 <= age < max_age_minutes else None


def validate_shortlist(tickers: Sequence[str], max_names: Optional[int] = None) -> List[str]:
    """Explicit shortlist only. Refuse (never truncate) anything larger than max_names."""
    limit = int(os.environ.get(ENV_MAX_NAMES, DEFAULT_MAX_NAMES)) if max_names is None else int(max_names)
    if isinstance(tickers, (str, bytes)) or isinstance(tickers, Mapping):
        raise ShortlistRefused("pass an explicit list of tickers, not a string or a watchlist document")
    names: List[str] = []
    for t in tickers:
        if not isinstance(t, str) or not t.strip():
            raise ShortlistRefused(f"invalid ticker {t!r}")
        u = t.strip().upper()
        if u not in names:
            names.append(u)
    if not names:
        raise ShortlistRefused("empty shortlist")
    if len(names) > limit:
        raise ShortlistRefused(
            f"shortlist has {len(names)} names; chains are capped at {limit} "
            f"(set {ENV_MAX_NAMES} to change). Never pass the full watchlist."
        )
    return names


def fetch_shortlist_chains(
    tickers: Sequence[str],
    expiration: Optional[str] = None,
    today: Optional[date] = None,
    max_names: Optional[int] = None,
    max_age_minutes: Optional[float] = None,
    ticker_factory: Callable = default_ticker_factory,
    save: bool = True,
) -> dict:
    """Chains for an explicit shortlist. One Ticker per name, cache-first.

    Returns {"chains": {T: chain}, "unavailable": {T: reason}}. A GuardBlocked
    (pipeline running / daemon window) aborts the whole call.
    """
    names = validate_shortlist(tickers, max_names)
    age_limit = float(os.environ.get(ENV_MAX_AGE, DEFAULT_MAX_AGE_MINUTES)) if max_age_minutes is None else max_age_minutes
    today = today or date.today()
    out: dict = {"chains": {}, "unavailable": {}, "from_cache": []}
    for t in names:
        try:
            if expiration:
                cached = load_cached_chain(t, expiration, age_limit)
                if cached:
                    out["chains"][t] = cached
                    out["from_cache"].append(t)
                    continue
            tk = ticker_factory(t)
            try:
                exps = list(tk.options or ())
            except guards.GuardBlocked:
                raise
            except Exception as exc:
                raise ChainUnavailable(t, "fetch_failed", str(exc)) from exc
            if not exps:
                raise ChainUnavailable(t, "no_expirations")
            exp = expiration or pick_expiration(exps, today)
            chain = get_chain(t, exp, ticker_factory=lambda _s, _tk=tk: _tk)
            if save:
                save_chain(chain)
            out["chains"][t] = chain
        except ChainUnavailable as exc:
            out["unavailable"][t] = exc.reason
    return out


def main(argv: Sequence[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Option chains for an explicit shortlist (not the watchlist).")
    ap.add_argument("tickers", nargs="*", help="explicit shortlist, e.g. AAPL MSFT")
    ap.add_argument("--shortlist-file", type=Path, help="JSON list of tickers")
    ap.add_argument("--expiration", default=None, help="YYYY-MM-DD; default first listed 7-45 days out")
    ap.add_argument("--max-names", type=int, default=None)
    ap.add_argument("--allow-daemon-window", action="store_true")
    args = ap.parse_args(argv)
    if args.allow_daemon_window:
        os.environ[guards.ENV_ALLOW_WINDOW] = "1"
    tickers = list(args.tickers)
    if args.shortlist_file:
        tickers += json.loads(args.shortlist_file.read_text())
    try:
        names = validate_shortlist(tickers, args.max_names)
        guards.preflight()
    except ShortlistRefused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    except guards.GuardBlocked as exc:
        print(json.dumps({"blocked": exc.reason, "detail": exc.detail}))
        return 2
    start = time.perf_counter()
    try:
        res = fetch_shortlist_chains(names, expiration=args.expiration, max_names=args.max_names)
    except guards.GuardBlocked as exc:
        print(json.dumps({"blocked": exc.reason, "detail": exc.detail}))
        return 2
    summary = {
        t: {
            "expiration": c["expiration"],
            "source": c["source"],
            "provisional": c["provisional"],
            "calls": len(c["calls"]),
            "puts": len(c["puts"]),
            "contracts_passing_gates": sum(1 for k in c["calls"] + c["puts"] if contract_passes_gates(k)),
        }
        for t, c in res["chains"].items()
    }
    print(
        json.dumps(
            {
                "chains": summary,
                "unavailable": res["unavailable"],
                "from_cache": res["from_cache"],
                "seconds": round(time.perf_counter() - start, 3),
            },
            indent=1,
        )
    )
    return 0 if res["chains"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
