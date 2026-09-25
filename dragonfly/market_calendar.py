"""Static NYSE session calendar for Dragonfly (no network, no dependencies).

Source: NYSE "Holidays & Trading Hours",
https://www.nyse.com/markets/hours-calendars (retrieved 2026-09-25). All NYSE
markets observe these full-day closures; early closes are 1:00 p.m. ET
(12:00 CT). Regular close is 4:00 p.m. ET (15:00 CT).

Coverage is explicit: a date outside COVERED_YEARS raises CalendarNotCovered
so a caller fails closed instead of guessing. Extend the tables (from the same
NYSE page) before the end of the last covered year.

Python 3.9 compatible.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List

# Full-day closures (NYSE published calendar).
HOLIDAYS = {
    # 2026
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King, Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth National Independence Day",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
    # 2027
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 18): "Martin Luther King, Jr. Day",
    date(2027, 2, 15): "Washington's Birthday",
    date(2027, 3, 26): "Good Friday",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth National Independence Day (observed)",
    date(2027, 7, 5): "Independence Day (observed)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving Day",
    date(2027, 12, 24): "Christmas Day (observed)",
    # 2028 (published on the same page; covers time stops that run into 2028)
    # No New Year's Day closure in 2028: January 1 falls on a Saturday.
    date(2028, 1, 17): "Martin Luther King, Jr. Day",
    date(2028, 2, 21): "Washington's Birthday",
    date(2028, 4, 14): "Good Friday",
    date(2028, 5, 29): "Memorial Day",
    date(2028, 6, 19): "Juneteenth National Independence Day",
    date(2028, 7, 4): "Independence Day",
    date(2028, 9, 4): "Labor Day",
    date(2028, 11, 23): "Thanksgiving Day",
    date(2028, 12, 25): "Christmas Day",
}

# Early closes at 1:00 p.m. ET (NYSE published calendar).
EARLY_CLOSES = {
    date(2026, 11, 27): "Day after Thanksgiving",
    date(2026, 12, 24): "Christmas Eve",
    date(2027, 11, 26): "Day after Thanksgiving",
    date(2028, 7, 3): "Day before Independence Day",
    date(2028, 11, 24): "Day after Thanksgiving",
}

COVERED_YEARS = (2026, 2027, 2028)
CT = "America/Chicago"
ET = "America/New_York"
REGULAR_CLOSE_ET = time(16, 0)
EARLY_CLOSE_ET = time(13, 0)


class CalendarNotCovered(ValueError):
    """The date is outside the static holiday tables. Fail closed."""


def _covered(d: date) -> None:
    if d.year not in COVERED_YEARS:
        raise CalendarNotCovered(f"{d.isoformat()} is outside the NYSE calendar tables {COVERED_YEARS}")


def is_session(d: date) -> bool:
    _covered(d)
    return d.weekday() < 5 and d not in HOLIDAYS


def holiday_name(d: date):
    return HOLIDAYS.get(d)


def is_early_close(d: date) -> bool:
    return is_session(d) and d in EARLY_CLOSES


def sessions_between(start: date, end: date) -> List[date]:
    """Sessions with start <= d <= end."""
    out = []
    d = start
    while d <= end:
        if is_session(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def previous_session(d: date) -> date:
    """Last session strictly before d."""
    p = d - timedelta(days=1)
    for _ in range(15):
        if is_session(p):
            return p
        p -= timedelta(days=1)
    raise CalendarNotCovered(f"no session in the 15 days before {d.isoformat()}")


def previous_sessions(d: date, n: int) -> List[date]:
    """The n sessions strictly before d, most recent last."""
    out: List[date] = []
    p = d
    while len(out) < n:
        p = previous_session(p)
        out.append(p)
    return list(reversed(out))


def next_session(d: date) -> date:
    n = d + timedelta(days=1)
    for _ in range(15):
        if is_session(n):
            return n
        n += timedelta(days=1)
    raise CalendarNotCovered(f"no session in the 15 days after {d.isoformat()}")


def session_close(d: date) -> datetime:
    """Close of session d as an aware America/Chicago datetime (early closes honoured)."""
    from zoneinfo import ZoneInfo

    if not is_session(d):
        raise ValueError(f"{d.isoformat()} is not an NYSE session")
    et_time = EARLY_CLOSE_ET if d in EARLY_CLOSES else REGULAR_CLOSE_ET
    return datetime.combine(d, et_time, tzinfo=ZoneInfo(ET)).astimezone(ZoneInfo(CT))


def previous_close(d: date) -> datetime:
    """Close of the last session before d (CT). The pre-open book must be marked at or after this."""
    return session_close(previous_session(d))
