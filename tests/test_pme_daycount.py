"""Day-count conventions: hand values, sign, additivity and refusals."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ovf.pme.daycount import (
    DAY_COUNT_CONVENTIONS,
    check_convention,
    describe,
    year_fraction,
)

DATES = st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31))


def test_conventions_listed() -> None:
    assert DAY_COUNT_CONVENTIONS == ("ACT/365F", "ACT/365.25", "ACT/ACT-ISDA")
    for convention in DAY_COUNT_CONVENTIONS:
        assert convention in describe(convention)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["ACT/360", "act/365f", "30/360", "", None, 365])
def test_unknown_convention_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="unknown day-count convention"):
        year_fraction(date(2020, 1, 1), date(2021, 1, 1), convention=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        check_convention(bad)


def test_datetime_refused() -> None:
    with pytest.raises(ValueError, match=r"datetime\.date"):
        year_fraction(datetime(2020, 1, 1), date(2021, 1, 1), convention="ACT/365F")
    with pytest.raises(ValueError, match=r"datetime\.date"):
        year_fraction(date(2020, 1, 1), "2021-01-01", convention="ACT/365F")  # type: ignore[arg-type]


# --- Hand values ------------------------------------------------------------------


def test_act_365f_hand_values() -> None:
    # 2020 is a leap year: 366 days / 365.
    assert year_fraction(date(2020, 1, 1), date(2021, 1, 1), convention="ACT/365F") == 366 / 365
    assert year_fraction(date(2021, 1, 1), date(2022, 1, 1), convention="ACT/365F") == 1.0
    # Microsoft XIRR example: 2008-01-01 -> 2008-03-01 is 60 days.
    assert year_fraction(date(2008, 1, 1), date(2008, 3, 1), convention="ACT/365F") == 60 / 365


def test_act_36525_hand_values() -> None:
    assert year_fraction(date(2020, 1, 1), date(2021, 1, 1), convention="ACT/365.25") == (
        366 / 365.25
    )
    # Four years spanning one leap day: 1461 days = 4 average Julian years exactly.
    assert year_fraction(date(2019, 1, 1), date(2023, 1, 1), convention="ACT/365.25") == 4.0


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # 2019-12-31 is one non-leap day; 2020-01-01..2020-12-30 are 365 leap days.
        (date(2019, 12, 31), date(2020, 12, 31), 1 / 365 + 365 / 366),
        # One leap day: 2020-12-31.
        (date(2020, 12, 31), date(2021, 1, 1), 1 / 366),
        # 2019-12-31 (non-leap) + all 366 days of 2020.
        (date(2019, 12, 31), date(2021, 1, 1), 1 / 365 + 1.0),
        # A whole calendar year is exactly 1 in leap and non-leap years alike.
        (date(2020, 1, 1), date(2021, 1, 1), 1.0),
        (date(2021, 1, 1), date(2022, 1, 1), 1.0),
        # Leap day inside February 2020: 28, 29 Feb -> 2 leap days.
        (date(2020, 2, 28), date(2020, 3, 1), 2 / 366),
        # 2100 is not a leap year (divisible by 100, not 400); 2000 is.
        (date(2100, 2, 28), date(2100, 3, 1), 1 / 365),
        (date(2000, 2, 28), date(2000, 3, 1), 2 / 366),
        # 2020-07-01 -> 2021-07-01: 184 days of 2020 / 366 + 181 days of 2021 / 365.
        (date(2020, 7, 1), date(2021, 7, 1), 184 / 366 + 181 / 365),
    ],
)
def test_act_act_isda_hand_values(start: date, end: date, expected: float) -> None:
    assert year_fraction(start, end, convention="ACT/ACT-ISDA") == pytest.approx(
        expected, rel=1e-15, abs=1e-15
    )
    assert year_fraction(end, start, convention="ACT/ACT-ISDA") == pytest.approx(
        -expected, rel=1e-15, abs=1e-15
    )


@pytest.mark.parametrize("convention", DAY_COUNT_CONVENTIONS)
def test_same_date_is_zero(convention: str) -> None:
    for day in (date(2020, 2, 29), date(1900, 1, 1), date(2100, 12, 31)):
        assert year_fraction(day, day, convention=convention) == 0.0  # type: ignore[arg-type]


@pytest.mark.parametrize("convention", DAY_COUNT_CONVENTIONS)
def test_negative_interval(convention: str) -> None:
    forward = year_fraction(date(2019, 3, 15), date(2024, 8, 2), convention=convention)  # type: ignore[arg-type]
    backward = year_fraction(date(2024, 8, 2), date(2019, 3, 15), convention=convention)  # type: ignore[arg-type]
    assert forward > 0
    assert backward == pytest.approx(-forward, rel=1e-15)


# --- Properties -------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(a=DATES, b=DATES, c=DATES, convention=st.sampled_from(DAY_COUNT_CONVENTIONS))
def test_additive(a: date, b: date, c: date, convention: str) -> None:
    ab = year_fraction(a, b, convention=convention)  # type: ignore[arg-type]
    bc = year_fraction(b, c, convention=convention)  # type: ignore[arg-type]
    ac = year_fraction(a, c, convention=convention)  # type: ignore[arg-type]
    assert ab + bc == pytest.approx(ac, rel=1e-12, abs=1e-12)


@settings(max_examples=300, deadline=None)
@given(a=DATES, b=DATES, convention=st.sampled_from(DAY_COUNT_CONVENTIONS))
def test_antisymmetric_and_signed(a: date, b: date, convention: str) -> None:
    ab = year_fraction(a, b, convention=convention)  # type: ignore[arg-type]
    ba = year_fraction(b, a, convention=convention)  # type: ignore[arg-type]
    assert ab == pytest.approx(-ba, rel=1e-15, abs=1e-15)
    assert (ab > 0) == (b > a)
    assert (ab == 0) == (b == a)


@settings(max_examples=200, deadline=None)
@given(a=DATES, days=st.integers(min_value=1, max_value=3000))
def test_isda_between_365_and_366(a: date, days: int) -> None:
    b = a + timedelta(days=days)
    if b > date(2100, 12, 31):
        return
    isda = year_fraction(a, b, convention="ACT/ACT-ISDA")
    assert days / 366 - 1e-12 <= isda <= days / 365 + 1e-12
