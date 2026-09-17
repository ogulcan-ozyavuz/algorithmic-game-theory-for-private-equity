"""Day-count conventions: the year fraction between two dates.

A dated cash-flow metric discounts each amount by ``(1 + r) ** -t`` with ``t`` the year
fraction from a reference date. Which convention turns days into years is an input to
every rate, never a default: the same flows give different IRRs under different
conventions.

Every convention here is **signed** (negative when ``end < start``) and **additive**:
``year_fraction(a, c) == year_fraction(a, b) + year_fraction(b, c)`` up to float
rounding. Additivity is why an IRR does not depend on which date is chosen as ``t0``:
moving ``t0`` multiplies every discount factor by the same positive constant.

Conventions:

- ``"ACT/365F"``: actual days / 365. The convention of Excel and LibreOffice ``XIRR``
  (days / 365 measured from the first date).
- ``"ACT/365.25"``: actual days / 365.25, an average Julian year.
- ``"ACT/ACT-ISDA"``: the days of the interval falling in a leap year / 366 plus the days
  falling in a non-leap year / 365 (ISDA 2006 Definitions, Section 4.16(b)). The start
  date is counted and the end date is not.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, get_args

DayCountConvention = Literal["ACT/365F", "ACT/365.25", "ACT/ACT-ISDA"]

DAY_COUNT_CONVENTIONS: tuple[str, ...] = get_args(DayCountConvention)

_DESCRIPTIONS: dict[str, str] = {
    "ACT/365F": "ACT/365F: year fraction = actual days / 365 (the Excel XIRR convention).",
    "ACT/365.25": "ACT/365.25: year fraction = actual days / 365.25.",
    "ACT/ACT-ISDA": (
        "ACT/ACT-ISDA: year fraction = days falling in leap years / 366 + days falling in "
        "non-leap years / 365; the start date counts, the end date does not."
    ),
}


def check_convention(convention: object) -> DayCountConvention:
    """Return ``convention`` if it names a supported day count, else raise ``ValueError``."""
    if not isinstance(convention, str) or convention not in DAY_COUNT_CONVENTIONS:
        raise ValueError(
            f"unknown day-count convention {convention!r}; expected one of "
            f"{', '.join(DAY_COUNT_CONVENTIONS)}"
        )
    return convention  # type: ignore[return-value]


def describe(convention: DayCountConvention) -> str:
    """One assumption line stating what ``convention`` means."""
    return _DESCRIPTIONS[check_convention(convention)]


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _isda_year_offset(day: date) -> tuple[int, float]:
    """``day`` as (year, fraction of that year elapsed before ``day``) under ACT/ACT-ISDA."""
    elapsed = (day - date(day.year, 1, 1)).days
    return day.year, elapsed / (366 if _is_leap(day.year) else 365)


def year_fraction(start: date, end: date, *, convention: DayCountConvention) -> float:
    """Signed year fraction from ``start`` to ``end`` under ``convention``.

    Negative when ``end < start``, zero when they are equal. For ACT/ACT-ISDA the value is
    ``Y(end) - Y(start)`` with ``Y(d) = year(d) + (days from 1 January to d) / days in
    year(d)``: each day adds ``1/366`` in a leap year and ``1/365`` otherwise, which is
    the ISDA split of the interval by calendar year, and is additive by construction.

    Raises ``ValueError`` for an unknown convention or for arguments that are not
    ``datetime.date`` (a ``datetime`` is refused: there is no intraday time here).
    """
    name = check_convention(convention)
    for label, value in (("start", start), ("end", end)):
        if not isinstance(value, date) or isinstance(value, datetime):
            raise ValueError(f"{label} must be a datetime.date, got {type(value).__name__}")
    if name == "ACT/365F":
        return (end - start).days / 365.0
    if name == "ACT/365.25":
        return (end - start).days / 365.25
    start_year, start_offset = _isda_year_offset(start)
    end_year, end_offset = _isda_year_offset(end)
    return (end_year - start_year) + (end_offset - start_offset)
