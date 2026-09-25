"""Synthetic daily-bar fixtures for the engine tests (offline). Not used in production.

Each builder returns bars in the #266 cache format ending at `end` (an NYSE
session), with the setup's signal bar last. Numbers are chosen so the
canonical draft passes every gate; keyword overrides make one gate fail.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from dragonfly import market_calendar as mc


def _dates(end: date, n: int) -> List[str]:
    return [d.isoformat() for d in mc.previous_sessions(mc.next_session(end), n)]


def _bar(day: str, close: float, high: float, low: float, volume: float, open_: Optional[float] = None) -> Dict:
    return {"date": day, "open": close if open_ is None else open_, "high": high, "low": low,
            "close": close, "volume": volume}


def breakout(end: date, rvol: float = 2.4, last_close: float = 84.3) -> List[Dict]:
    days = _dates(end, 100)
    bars = [_bar(d, 80.0, 82.0, 78.0, 1.5e6) for d in days[:-1]]
    bars.append(_bar(days[-1], last_close, 85.0, 81.0, 1.5e6 * rvol, open_=80.5))
    return bars


def pullback(end: date, pull_closes=(89.6, 89.3, 89.0), pull_volume: float = 1.0e6,
             momentum: bool = True, formed: bool = True, pull_half_range: float = 0.5) -> List[Dict]:
    n_pull = len(pull_closes) if formed else 0
    days = _dates(end, 95 + n_pull)
    bars = []
    base = 70.0 if momentum else 85.0
    for i in range(75):
        bars.append(_bar(days[i], base, base + 1, base - 1, 1.5e6))
    for j in range(20):
        c = base + 1 + j if momentum else base - 0.05 * j   # no momentum: a slow drift down
        bars.append(_bar(days[75 + j], c, c + 1, c - 1, 2.0e6))
    for k, c in enumerate(pull_closes[:n_pull]):
        bars.append(_bar(days[95 + k], c, c + pull_half_range, c - pull_half_range, pull_volume))
    return bars


def failed_breakdown(end: date, window_low: float = 78.0, reversal_close: float = 80.5,
                     reversal_low: float = 79.2, reversal_volume: float = 3.2e6) -> List[Dict]:
    days = _dates(end, 100)
    bars = [_bar(d, 80.0, 81.0, 79.0, 2.0e6) for d in days[:-3]]
    bars.append(_bar(days[-3], 78.5, 79.5, window_low, 2.4e6))
    bars.append(_bar(days[-2], 79.0, 79.5, max(window_low, 78.2), 2.2e6))
    bars.append(_bar(days[-1], reversal_close, 81.0, reversal_low, reversal_volume, open_=79.3))
    return bars


def compression(end: date, tight_half: float = 0.8, exp_low: float = 80.0, exp_high: float = 82.6,
                exp_close: float = 82.4, exp_volume: float = 2.5e6) -> List[Dict]:
    days = _dates(end, 100)
    bars = [_bar(d, 80.0, 83.0, 77.0, 1.5e6) for d in days[:70]]
    bars += [_bar(d, 80.0, 80.0 + tight_half, 80.0 - tight_half, 1.5e6) for d in days[70:99]]
    bars.append(_bar(days[99], exp_close, exp_high, exp_low, exp_volume, open_=80.1))
    return bars
