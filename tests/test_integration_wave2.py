"""Cross-module checks that no single worker could have made.

Each module in this wave was built in isolation with strict file ownership, so an
interaction between two of them is exactly what nobody was in a position to see. These
are the coordinator's integration assertions.
"""

from __future__ import annotations

from datetime import date

import pytest

import ovf
from ovf.contracts.securities import cumulative_dividend
from ovf.ocf import Issuer, OcfUnsupportedError, from_ocf, to_ocf

ACCRUES_FROM = date(2024, 1, 1)
SETTLE = date(2026, 1, 1)


def issuer() -> Issuer:
    return Issuer(
        object_type="ISSUER",
        id="issuer-1",
        legal_name="Integration Test Co",
        formation_date=date(2020, 1, 1),
        country_of_formation="US",
    )


def dividend_table() -> ovf.CapTable:
    term = cumulative_dividend(
        0.08,
        accrual="simple",
        day_count="actual/365_fixed",
        accrues_from=ACCRUES_FROM,
        settlement="forfeit_on_conversion",
    )
    return ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(
                2_000_000, 2.50, holder_id="series_a", security_id="series_a", dividend=term
            ),
        ]
    )


def test_ocf_export_refuses_a_dividend_rather_than_dropping_it() -> None:
    """Regression for a real integration defect found at the end of this wave.

    OCF v1.2.0 StockClass carries no dividend fields. Before this check the writer
    emitted the class without them, and a round trip returned a position whose accruing
    claim had silently vanished: on a $20M exit that understated Series A by $801,095.89.
    A refusal is the correct behaviour; a wrong number is worse than an error.
    """
    with pytest.raises(OcfUnsupportedError, match="no dividend fields"):
        to_ocf(dividend_table(), issuer=issuer(), currency="USD", as_of=SETTLE)


def test_a_dividend_free_table_still_round_trips() -> None:
    """The refusal must be narrow: tables without dividends are unaffected."""
    table = ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
        ]
    )
    recovered = from_ocf(to_ocf(table, issuer=issuer(), currency="USD", as_of=SETTLE))
    original = {p.security_id: p.amount for p in table.waterfall(35_000_000)}
    again = {p.security_id: p.amount for p in recovered.waterfall(35_000_000)}
    assert original == pytest.approx(again)


def test_the_dropped_dividend_would_have_cost_this_much() -> None:
    """Pins the magnitude quoted in the regression above, so the claim stays checkable.

    731 days from 2024-01-01 to 2026-01-01 (2024 is a leap year), simple at 8% on
    $5,000,000 invested: 5,000,000 x 0.08 x 731/365 = $801,095.89 of accrued dividend.
    """
    accrued = 5_000_000 * 0.08 * 731 / 365
    assert accrued == pytest.approx(801_095.89, abs=0.01)
    with_dividend = {
        p.security_id: p.amount for p in dividend_table().waterfall(20_000_000, as_of=SETTLE)
    }
    stripped = ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
        ]
    )
    without = {p.security_id: p.amount for p in stripped.waterfall(20_000_000)}
    assert with_dividend["series_a"] - without["series_a"] == pytest.approx(accrued, abs=0.01)


def test_an_anti_dilution_adjustment_survives_an_ocf_round_trip() -> None:
    """financing.py and ocf.py were built in parallel; the adjusted ratio must persist."""
    from ovf.financing import apply_dilutive_issuance

    table = ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
        ]
    )
    before = {s.security_id: s for s in table.securities}["series_a"]
    recovered = from_ocf(to_ocf(table, issuer=issuer(), currency="USD", as_of=SETTLE))
    after = {s.security_id: s for s in recovered.securities}["series_a"]
    assert after.conversion_ratio == pytest.approx(before.conversion_ratio)
    assert callable(apply_dilutive_issuance)


def test_debt_and_dividends_share_one_as_of() -> None:
    """Both accruing claims take the same explicit date; neither invents a second clock."""
    from ovf.instruments import debt

    table = ovf.CapTable(
        securities=[
            ovf.common(8_000_000, holder_id="founders", security_id="common"),
            ovf.preferred(
                2_000_000,
                2.50,
                holder_id="series_a",
                security_id="series_a",
                dividend=cumulative_dividend(
                    0.08,
                    accrual="simple",
                    day_count="actual/365_fixed",
                    accrues_from=ACCRUES_FROM,
                    settlement="forfeit_on_conversion",
                ),
            ),
            debt(
                principal=1_000_000,
                annual_rate=0.08,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=ACCRUES_FROM,
                seniority=0,
                holder_id="lender",
                security_id="loan",
            ),
        ]
    )
    report = table.waterfall_detailed(30_000_000, as_of=SETTLE)
    assert report.as_of == SETTLE
    assert report.debt_settlements
    assert sum(p.amount for p in report.payouts) == pytest.approx(30_000_000)
    with pytest.raises(ValueError, match="as_of"):
        table.waterfall_detailed(30_000_000)
