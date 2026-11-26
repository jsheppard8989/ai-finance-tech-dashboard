#!/usr/bin/env python3
"""US equity/options session calendar in Central Time, for scoreboard freshness.

Share session: 8:30 AM to 3:00 PM CT (12:00 PM CT on early-close days).
Option session: 8:30 AM to 3:15 PM CT (12:15 PM CT on early-close days).
Holidays and early closes are the NYSE published lists for 2026 and 2027.
Extend NYSE_HOLIDAYS / NYSE_EARLY_CLOSES before 2028.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")

NYSE_HOLIDAYS: frozenset[date] = frozenset(
    date.fromisoformat(d)
    for d in (
        # 2026
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
        # 2027
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    )
)
NYSE_EARLY_CLOSES: frozenset[date] = frozenset(
    date.fromisoformat(d) for d in ("2026-11-27", "2026-12-24", "2027-11-26")
)

SESSION_OPEN = time(8, 30)
SESSION_CLOSE = time(15, 0)
EARLY_CLOSE = time(12, 0)
# Options trade 15 minutes after the share close (3:15 PM CT, or 12:15 PM CT on half days).
OPTION_CLOSE_OFFSET = timedelta(minutes=15)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def session_close(d: date) -> datetime:
    """Share/ETF session close: 3:00 PM CT, or 12:00 PM CT on early-close days."""
    t = EARLY_CLOSE if d in NYSE_EARLY_CLOSES else SESSION_CLOSE
    return datetime.combine(d, t, tzinfo=CT)


def option_session_close(d: date) -> datetime:
    """Option session close: 15 minutes after the share close that day."""
    return session_close(d) + OPTION_CLOSE_OFFSET


def quote_cutoff(d: date, kind: str = "share") -> datetime:
    """Last acceptable quote stamp for this instrument type on date d (inclusive)."""
    if str(kind).lower().startswith("option"):
        return option_session_close(d)
    return session_close(d)


def session_open(d: date) -> datetime:
    return datetime.combine(d, SESSION_OPEN, tzinfo=CT)


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def previous_trading_day(d: date) -> date:
    n = d - timedelta(days=1)
    while not is_trading_day(n):
        n -= timedelta(days=1)
    return n


def in_regular_session(ts: datetime, kind: str = "share") -> bool:
    """True when a quote timestamp is inside the regular session for this instrument type.

    Shares and ETF underlyings: 8:30 AM CT through the share close (3:00 PM CT,
    or 12:00 PM CT on early-close days). Options: 8:30 AM CT through the option
    close (3:15 PM CT, or 12:15 PM CT on early-close days). The cutoff second is
    included. After-hours quotes and non-trading days are rejected.
    """
    local = ts.astimezone(CT)
    d = local.date()
    if not is_trading_day(d):
        return False
    return session_open(d) <= local <= quote_cutoff(d, kind)


def stale_after(mark_ts: datetime) -> datetime:
    """A mark is older than 1 trading day once the next full session after it has closed."""
    local = mark_ts.astimezone(CT)
    d = local.date()
    if is_trading_day(d) and local < session_open(d):
        # A pre-open read still describes the prior session.
        d = previous_trading_day(d)
    elif not is_trading_day(d):
        d = previous_trading_day(d)
    return session_close(next_trading_day(d))


def is_stale(mark_ts: datetime, now: datetime) -> bool:
    return now.astimezone(CT) > stale_after(mark_ts)
