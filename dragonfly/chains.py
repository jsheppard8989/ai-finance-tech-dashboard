"""Option chains for Dragonfly 7 (Phase 1 source: Yahoo via yfinance).

`get_chain(ticker, expiration)` makes one `Ticker.option_chain(exp)` call for a
single expiration and keeps bid, ask, volume, open interest, and Yahoo's
implied volatility per contract. Every chain is stamped
source="yahoo", provisional=True.

Fail closed: a missing expiration list, an expiration Yahoo does not list, a
provider error, or an empty chain raises `ChainUnavailable` with a reason code.
Nothing is filled in. A missing volume/OI/bid/ask stays None and a None never
passes `contract_passes_gates`.

Python 3.9 compatible. Run: python3 dragonfly/chains.py AAPL [YYYY-MM-DD]
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

from dragonfly.risk_math import (  # noqa: E402
    MAX_OPTION_SPREAD_PCT,
    MIN_OPTION_OPEN_INTEREST,
    MIN_OPTION_VOLUME,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "yahoo"
KEEP = ("contractSymbol", "strike", "bid", "ask", "volume", "openInterest", "impliedVolatility", "lastTradeDate")


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
    import yfinance as yf  # lazy: tests never import it

    return yf.Ticker(symbol)


def list_expirations(ticker: str, ticker_factory: Callable = default_ticker_factory) -> List[str]:
    try:
        exps = list(ticker_factory(ticker).options or ())
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
    except Exception as exc:
        raise ChainUnavailable(ticker, "fetch_failed", str(exc)) from exc
    if not exps:
        raise ChainUnavailable(ticker, "no_expirations")
    if expiration not in exps:
        raise ChainUnavailable(ticker, "expiration_not_listed", expiration)
    try:
        oc = tk.option_chain(expiration)
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


def main(argv: Sequence[str]) -> int:
    ticker = argv[0] if argv else "AAPL"
    start = time.perf_counter()
    try:
        if len(argv) > 1:
            exp = argv[1]
        else:
            exp = pick_expiration(list_expirations(ticker), date.today())
        chain = get_chain(ticker, exp)
    except ChainUnavailable as exc:
        print(json.dumps({"ticker": ticker, "unavailable": exc.reason, "detail": exc.detail}))
        return 1
    path = save_chain(chain)
    passing = sum(1 for c in chain["calls"] + chain["puts"] if contract_passes_gates(c))
    print(
        json.dumps(
            {
                "ticker": chain["ticker"],
                "expiration": chain["expiration"],
                "source": chain["source"],
                "provisional": chain["provisional"],
                "calls": len(chain["calls"]),
                "puts": len(chain["puts"]),
                "contracts_passing_gates": passing,
                "sample_call": chain["calls"][len(chain["calls"]) // 2] if chain["calls"] else None,
                "cached_to": str(path),
                "seconds": round(time.perf_counter() - start, 3),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
