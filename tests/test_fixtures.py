"""Named market-convention fixtures, asserted against the production engine."""

from __future__ import annotations

import pytest

import ovf
from tests.fixtures import FIXTURES, WaterfallFixture, cap_table


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_allocation(fixture: WaterfallFixture) -> None:
    report = cap_table(fixture).waterfall_detailed(fixture.exit_valuation)
    actual = {p.security_id: p.amount for p in report.payouts}
    assert actual == pytest.approx(fixture.expected, abs=1e-6)
    assert sum(actual.values()) == pytest.approx(fixture.exit_valuation)
    assert report.converged


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_conversion_state(fixture: WaterfallFixture) -> None:
    report = cap_table(fixture).waterfall_detailed(fixture.exit_valuation)
    converted = {
        p.security_id: p.converted
        for p in report.payouts
        if p.security_id in fixture.expected_converted
    }
    assert converted == fixture.expected_converted


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_payoffs_are_equilibrium_unique(fixture: WaterfallFixture) -> None:
    """Every fixture has a single equilibrium payoff vector, however many profiles exist."""
    survey = ovf.enumerate_equilibria(fixture.securities, fixture.exit_valuation)
    assert survey.feasible_equilibria
    assert survey.payoff_unique
    assert survey.distinct_payoff_vectors == 1
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


def test_f3_has_two_equilibrium_profiles_with_one_payoff() -> None:
    """The documented tie case: two profiles, identical cash."""
    fixture = next(f for f in FIXTURES if f.case_id == "F3")
    survey = ovf.enumerate_equilibria(fixture.securities, fixture.exit_valuation)
    assert len(survey.feasible_equilibria) == 2
    assert survey.payoff_unique


def test_dead_zone_boundary_is_total_preference() -> None:
    """Common receives nothing up to total preference and shares every dollar above it."""
    securities = [f for f in FIXTURES if f.case_id == "F8a"][0].securities
    total_preference = 14_000_000
    for exit_value in (0, 1_000_000, 13_999_999, total_preference):
        payouts = ovf.CapTable(securities=list(securities)).waterfall(exit_value)
        common = next(p for p in payouts if p.security_id == "common")
        assert common.amount == pytest.approx(0.0, abs=1e-6)
    for exit_value in (total_preference + 1, 20_000_000, 40_000_000):
        payouts = ovf.CapTable(securities=list(securities)).waterfall(exit_value)
        common = next(p for p in payouts if p.security_id == "common")
        assert common.amount > 0
