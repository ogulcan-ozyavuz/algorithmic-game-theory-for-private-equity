"""Named SAFE fixtures asserted against the solver, plus the round-to-exit handoff."""

from __future__ import annotations

import math

import pytest

import ovf
from tests.safe_fixtures import SAFE_FIXTURES, SafeFixture, solve


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_share_price_and_total(fixture: SafeFixture) -> None:
    result = solve(fixture)
    assert result.share_price == pytest.approx(fixture.expected_share_price, rel=1e-12)
    assert result.total_post_shares == pytest.approx(fixture.expected_total_shares, rel=1e-12)


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_ownership(fixture: SafeFixture) -> None:
    result = solve(fixture)
    assert result.ownership_breakdown == pytest.approx(fixture.expected_ownership, abs=1e-12)
    assert math.fsum(result.ownership_breakdown.values()) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_safe_shares_and_conversion_prices(fixture: SafeFixture) -> None:
    result = solve(fixture)
    assert result.safe_shares == pytest.approx(fixture.expected_safe_shares, rel=1e-12)
    assert result.safe_conversion_prices == pytest.approx(
        fixture.expected_conversion_prices, rel=1e-12
    )


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_share_conservation(fixture: SafeFixture) -> None:
    result = solve(fixture)
    parts = [
        result.prior_common_shares,
        result.new_preferred_shares,
        result.new_option_pool_shares,
        *result.safe_shares.values(),
    ]
    assert math.fsum(parts) == pytest.approx(result.total_post_shares, rel=1e-10)
    assert abs(result.share_balance_error) <= max(1e-8, result.total_post_shares * 1e-10)


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_round_to_exit_handoff(fixture: SafeFixture) -> None:
    """The post-round snapshot allocates a later exit without leftover cash."""
    post_round = solve(fixture).to_cap_table()
    report = post_round.waterfall_detailed(250_000_000)
    assert report.converged
    assert sum(p.amount for p in report.payouts) == pytest.approx(250_000_000)


def test_pool_shuffle_is_paid_by_everyone_except_the_new_round() -> None:
    """S1 against S3: the new investor keeps 20%; the pool comes out of the others."""
    no_pool = solve(next(f for f in SAFE_FIXTURES if f.case_id == "S1")).ownership_breakdown
    with_pool = solve(next(f for f in SAFE_FIXTURES if f.case_id == "S3")).ownership_breakdown
    assert no_pool["new_preferred"] == pytest.approx(with_pool["new_preferred"])
    assert with_pool["founders"] < no_pool["founders"]
    assert with_pool["angel"] < no_pool["angel"]
    lost = (no_pool["founders"] - with_pool["founders"]) + (no_pool["angel"] - with_pool["angel"])
    assert lost == pytest.approx(with_pool["option_pool"], abs=1e-12)


def test_pre_and_post_money_differ_on_identical_terms() -> None:
    """Same cash, same cap, different capitalization definition, different ownership."""
    post = solve(next(f for f in SAFE_FIXTURES if f.case_id == "S1")).ownership_breakdown
    pre = solve(next(f for f in SAFE_FIXTURES if f.case_id == "S5")).ownership_breakdown
    assert post["angel"] > pre["angel"]
    assert post["new_preferred"] == pytest.approx(pre["new_preferred"])


def test_down_round_gives_the_holder_the_round_price() -> None:
    fixture = next(f for f in SAFE_FIXTURES if f.case_id == "S2")
    result = solve(fixture)
    safe = fixture.safes[0]
    for security_id, price in result.safe_conversion_prices.items():
        # The cap never binds below it: conversion happens at the round price.
        assert price == pytest.approx(result.share_price)
        cap_price = safe.valuation_cap / (result.total_post_shares - result.new_preferred_shares)
        assert price < cap_price
        # And the holder therefore receives more shares than the cap would have given.
        assert result.safe_shares[security_id] > safe.investment_amount / cap_price
    assert result.ownership_breakdown["angel"] == pytest.approx(0.20)


def test_cap_binding_is_independent_of_the_number_of_safes() -> None:
    """Post-money SAFEs do not dilute each other; each cap fixes its own fraction."""
    one = ovf.solve_priced_round_with_safes(
        prior_common_shares=8_000_000,
        new_money=4_000_000,
        pre_money_valuation=16_000_000,
        target_pool_pct=0.10,
        safes=[ovf.safe_post(amount=1_000_000, cap=10_000_000, holder_id="a1")],
    )
    two = solve(next(f for f in SAFE_FIXTURES if f.case_id == "S4"))
    assert two.ownership_breakdown["a1"] == pytest.approx(one.ownership_breakdown["a1"])
