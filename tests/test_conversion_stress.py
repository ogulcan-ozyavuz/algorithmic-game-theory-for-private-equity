"""Adversarial conversion games: knife-edge exits, ties, larger tables, search guards.

Findings recorded in `docs/findings.md` are asserted here so a regression in the
search or the allocation primitive is caught rather than silently changing the
documented claims.
"""

from __future__ import annotations

import itertools

import pytest

import ovf
from ovf.waterfall import WaterfallConvergenceError, solve_waterfall

# A game whose best-response search needs three sweeps. Found by random search
# over 200,000 adversarial tables; see docs/findings.md.
SLOW_GAME_TERMS: tuple[dict[str, float | bool], ...] = (
    {
        "shares": 1,
        "price": 1,
        "seniority": 1,
        "liquidation_multiple": 1.5,
        "participating": True,
        "participation_cap": 2.5,
    },
    {
        "shares": 1,
        "price": 5,
        "seniority": 2,
        "liquidation_multiple": 2.0,
        "participating": True,
        "participation_cap": 3.0,
    },
    {
        "shares": 3,
        "price": 5,
        "seniority": 4,
        "liquidation_multiple": 3.0,
        "participating": True,
        "participation_cap": 3.25,
    },
    {
        "shares": 1,
        "price": 5,
        "seniority": 1,
        "liquidation_multiple": 1.5,
        "participating": True,
        "participation_cap": 1.75,
    },
)
SLOW_GAME_EXIT = 91.0


def slow_game() -> list[ovf.Security]:
    return [
        ovf.preferred(holder_id=f"p{i}", security_id=f"p{i}", **terms)
        for i, terms in enumerate(SLOW_GAME_TERMS)
    ]


def test_slow_game_needs_more_than_one_sweep() -> None:
    result = solve_waterfall(slow_game(), SLOW_GAME_EXIT)
    assert result.converged
    assert result.iterations == 3
    assert sum(p.amount for p in result.payouts) == pytest.approx(SLOW_GAME_EXIT)


def test_search_budget_is_enforced() -> None:
    """The iteration guard raises rather than returning an unverified state."""
    with pytest.raises(WaterfallConvergenceError):
        solve_waterfall(slow_game(), SLOW_GAME_EXIT, max_iterations=1)


def test_returned_state_is_always_a_verified_equilibrium() -> None:
    result = solve_waterfall(slow_game(), SLOW_GAME_EXIT)
    survey = ovf.enumerate_equilibria(slow_game(), SLOW_GAME_EXIT)
    actual = {p.security_id: p.converted for p in result.payouts}
    assert actual in survey.feasible_equilibria
    assert result.max_unilateral_gain <= result.tolerance


def test_no_common_shares_is_supported() -> None:
    """A table with only preferred still allocates the whole exit."""
    result = solve_waterfall(slow_game(), 1_000.0)
    assert sum(p.amount for p in result.payouts) == pytest.approx(1_000.0)


def test_identical_classes_are_symmetric() -> None:
    """Two identical positions receive identical cash at every exit."""
    securities = [
        ovf.common(1_000_000, holder_id="f", security_id="common"),
        ovf.preferred(
            500_000, 2.0, participating=True, participation_cap=2.0, holder_id="a", security_id="a"
        ),
        ovf.preferred(
            500_000, 2.0, participating=True, participation_cap=2.0, holder_id="b", security_id="b"
        ),
    ]
    for exit_value in (0, 500_000, 1_000_000, 2_000_000, 4_000_000, 10_000_000):
        payouts = {p.security_id: p.amount for p in solve_waterfall(securities, exit_value).payouts}
        assert payouts["a"] == pytest.approx(payouts["b"])


@pytest.mark.parametrize("positions", [5, 6, 7])
def test_larger_games_converge(positions: int) -> None:
    securities: list[ovf.Security] = [ovf.common(10_000, holder_id="f", security_id="common")]
    for i in range(positions):
        securities.append(
            ovf.preferred(
                shares=1_000 * (i + 1),
                price=float(i + 1),
                seniority=i % 3 + 1,
                liquidation_multiple=1.0 + (i % 3) * 0.5,
                participating=i % 2 == 0,
                participation_cap=2.0 + (i % 3) if i % 2 == 0 else None,
                holder_id=f"p{i}",
                security_id=f"p{i}",
            )
        )
    for exit_value in (0, 1_000, 25_000, 120_000, 1_000_000):
        result = solve_waterfall(securities, exit_value)
        assert result.converged
        assert result.max_unilateral_gain <= result.tolerance
        assert sum(p.amount for p in result.payouts) == pytest.approx(exit_value)


def test_knife_edge_exits_keep_a_unique_payoff_vector() -> None:
    """At the exact conversion and cap boundaries the cash split stays determinate."""
    securities = [
        ovf.common(8_000_000, holder_id="f", security_id="common"),
        ovf.preferred(
            2_000_000,
            2.50,
            participating=True,
            participation_cap=2.0,
            holder_id="a",
            security_id="a",
        ),
    ]
    # $25M: preference equals as-converted value. $50M: cap equals as-converted value.
    for exit_value in (25_000_000, 50_000_000):
        survey = ovf.enumerate_equilibria(securities, exit_value)
        assert len(survey.feasible_equilibria) >= 1
        assert survey.payoff_unique


def test_enumeration_matches_the_solver_across_a_sweep() -> None:
    securities = slow_game()
    for exit_value in range(0, 400, 7):
        survey = ovf.enumerate_equilibria(securities, float(exit_value))
        if not survey.feasible_equilibria:
            continue
        result = solve_waterfall(securities, float(exit_value))
        chosen = {p.security_id: p.converted for p in result.payouts}
        assert chosen in survey.feasible_equilibria
        assert survey.payoff_unique


def test_enumeration_refuses_intractable_tables() -> None:
    securities = [ovf.preferred(1, 1, holder_id=f"p{i}", security_id=f"p{i}") for i in range(13)]
    with pytest.raises(ValueError, match="max_positions"):
        ovf.enumerate_equilibria(securities, 100.0)


def test_enumeration_reports_every_profile() -> None:
    securities = slow_game()
    survey = ovf.enumerate_equilibria(securities, SLOW_GAME_EXIT)
    expected_ids = [f"p{i}" for i in range(len(SLOW_GAME_TERMS))]
    assert survey.states_evaluated == 2 ** len(SLOW_GAME_TERMS)
    assert survey.positions == expected_ids
    assert all(set(profile) == set(expected_ids) for profile in survey.feasible_equilibria)


def test_multi_position_holder_disclosure() -> None:
    """One holder across several positions weakens the independent-position assumption."""
    securities = [
        ovf.common(1_000_000, holder_id="f", security_id="common"),
        ovf.preferred(100_000, 1.0, holder_id="fund_x", security_id="a"),
        ovf.preferred(100_000, 2.0, holder_id="fund_x", security_id="b"),
        ovf.preferred(100_000, 3.0, holder_id="fund_y", security_id="c"),
    ]
    result = solve_waterfall(securities, 5_000_000)
    assert result.multi_position_holders == ["fund_x"]
    single = solve_waterfall(securities[:2] + securities[3:], 5_000_000)
    assert single.multi_position_holders == []


def test_exhaustive_small_game_payoff_uniqueness() -> None:
    """Deterministic sweep: every enumerated small game has one equilibrium payoff."""
    shapes = [
        (1.0, False, None),
        (1.0, True, None),
        (1.0, True, 2.0),
        (2.0, True, 3.0),
    ]
    checked = 0
    for first, second in itertools.product(shapes, repeat=2):
        securities = [
            ovf.common(1_000, holder_id="f", security_id="common"),
            ovf.preferred(
                500,
                2.0,
                seniority=1,
                liquidation_multiple=first[0],
                participating=first[1],
                participation_cap=first[2],
                holder_id="a",
                security_id="a",
            ),
            ovf.preferred(
                400,
                3.0,
                seniority=2,
                liquidation_multiple=second[0],
                participating=second[1],
                participation_cap=second[2],
                holder_id="b",
                security_id="b",
            ),
        ]
        for exit_value in (0, 500, 1_000, 2_200, 3_400, 5_000, 12_000, 40_000):
            survey = ovf.enumerate_equilibria(securities, float(exit_value))
            if survey.feasible_equilibria:
                assert survey.payoff_unique
                checked += 1
    assert checked > 100
