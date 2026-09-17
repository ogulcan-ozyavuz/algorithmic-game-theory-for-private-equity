"""CapTable's as_of passthrough to the debt-aware waterfall.

The engine work lives in ovf.instruments.debt and ovf.waterfall (see tests/test_debt.py).
These cases only pin the CapTable surface: that the explicit settlement date reaches the
solver, that omitting it on a table holding debt raises rather than assuming a date, and
that a table without debt is unaffected.
"""

from __future__ import annotations

from datetime import date

import pytest

import ovf
from ovf.instruments import debt

ISSUE = date(2024, 1, 1)
SETTLE = date(2026, 1, 1)  # 731 days: 2024 is a leap year, so 366 + 365.


def table_with_debt() -> ovf.CapTable:
    return ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
            debt(
                principal=1_000_000,
                annual_rate=0.08,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=ISSUE,
                seniority=0,
                holder_id="lender",
                security_id="loan",
            ),
        ]
    )


def test_as_of_reaches_the_solver() -> None:
    """Hand-derived: 1,000,000 x (1 + 0.08 x 731/365) = 1,160,219.178..."""
    expected_claim = 1_000_000 * (1 + 0.08 * 731 / 365)
    report = table_with_debt().waterfall_detailed(20_000_000, as_of=SETTLE)
    assert report.as_of == SETTLE
    settlement = report.debt_settlements[0]
    assert settlement.claim.claim == pytest.approx(expected_claim)
    assert settlement.paid == pytest.approx(expected_claim)
    assert settlement.shortfall == pytest.approx(0.0)


def test_absolute_priority_and_conservation() -> None:
    report = table_with_debt().waterfall_detailed(20_000_000, as_of=SETTLE)
    payouts = {p.security_id: p.amount for p in report.payouts}
    assert payouts["loan"] == pytest.approx(1_000_000 * (1 + 0.08 * 731 / 365))
    assert payouts["series_a"] == pytest.approx(5_000_000)
    assert sum(payouts.values()) == pytest.approx(20_000_000)
    assert report.conservation_error == pytest.approx(0.0, abs=1e-6)


def test_debt_exhausts_proceeds_before_any_equity() -> None:
    report = table_with_debt().waterfall_detailed(800_000, as_of=SETTLE)
    payouts = {p.security_id: p.amount for p in report.payouts}
    assert payouts["loan"] == pytest.approx(800_000)
    assert payouts["common"] == pytest.approx(0.0)
    assert payouts["series_a"] == pytest.approx(0.0)
    assert report.debt_settlements[0].shortfall > 0


def test_omitting_as_of_raises_rather_than_assuming_today() -> None:
    """An implicit clock would make the result irreproducible; refusing is the contract."""
    with pytest.raises(ValueError, match="as_of"):
        table_with_debt().waterfall_detailed(20_000_000)


def test_waterfall_list_api_also_takes_as_of() -> None:
    payouts = table_with_debt().waterfall(20_000_000, as_of=SETTLE)
    assert sum(p.amount for p in payouts) == pytest.approx(20_000_000)


def test_table_without_debt_is_unaffected() -> None:
    """No debt means no date is needed and the existing answer is unchanged."""
    table = ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
        ]
    )
    payouts = {p.security_id: p.amount for p in table.waterfall(35_000_000)}
    assert payouts == pytest.approx({"common": 28_000_000, "series_a": 7_000_000})
    report = table.waterfall_detailed(35_000_000)
    assert report.as_of is None
    assert report.debt_settlements == []
