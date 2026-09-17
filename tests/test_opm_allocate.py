"""Option Pricing Method allocation: the refusals first, then the invariants and fixtures.

Every schedule here is built by hand from breakpoints derived in docs/opm.md, then replayed
against ``solve_waterfall`` before use (``verified_schedule``), which fills in its measured
linearity error. The tests therefore do not depend on ``ovf.opm.breakpoints``; the one test
that exercises the derived path is skipped if that module cannot be imported.
"""

from __future__ import annotations

import inspect
import itertools
import math
from datetime import date
from fractions import Fraction

import numpy as np
import pytest
from scipy.stats import norm

from ovf.opm.allocate import (
    NEGATIVE_WEIGHT_FLOOR,
    WEIGHT_SUM_TOLERANCE,
    linearity_tolerance,
    opm_allocate,
)
from ovf.opm.types import (
    Breakpoint,
    BreakpointError,
    BreakpointSchedule,
    Discontinuity,
    OpmAssumptionError,
    OpmInputs,
    OpmResult,
    Tranche,
)
from ovf.waterfall import solve_waterfall
from tests import governance_fixtures as gov
from tests.fixtures import FIXTURES, WaterfallFixture

M = 1_000_000
F = Fraction
Shape = list[tuple[float, dict[str, Fraction]]]

# Breakpoints and marginal-dollar weights, derived in docs/opm.md §Breakpoints used here.
ONE_X_NON_PARTICIPATING: Shape = [
    (0, {"series_a": F(1)}),
    (5 * M, {"common": F(1)}),
    (25 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
]
PARTICIPATING: Shape = [
    (0, {"series_a": F(1)}),
    (5 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
]
PARTICIPATING_2X_CAP: Shape = [
    (0, {"series_a": F(1)}),
    (5 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
    (30 * M, {"common": F(1)}),
    (50 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
]
ALL_CONVERTED = {"common": F(16, 23), "series_a": F(4, 23), "series_b": F(3, 23)}
STACKED: Shape = [
    (0, {"series_b": F(1)}),
    (9 * M, {"series_a": F(1)}),
    (14 * M, {"common": F(1)}),
    (34 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
    (69 * M, ALL_CONVERTED),
]
PARI_PASSU: Shape = [
    (0, {"series_a": F(5, 14), "series_b": F(9, 14)}),
    (14 * M, {"common": F(1)}),
    (34 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
    (69 * M, ALL_CONVERTED),
]
TWO_X_PARTICIPATING: Shape = [
    (0, {"series_a": F(1)}),
    (10 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
]
# The README table in tests/governance_fixtures.py, without any collective-conversion term.
README: Shape = [
    (0, {"series_b": F(1)}),
    (9 * M, {"series_a": F(1)}),
    (14 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
    (39 * M, {"common": F(1)}),
    (59 * M, {"common": F(4, 5), "series_a": F(1, 5)}),
    (69 * M, ALL_CONVERTED),
]

SHAPES: dict[str, Shape] = {
    "F1": ONE_X_NON_PARTICIPATING,
    "F2": ONE_X_NON_PARTICIPATING,
    "F3": ONE_X_NON_PARTICIPATING,
    "F4": PARTICIPATING,
    "F5a": PARTICIPATING_2X_CAP,
    "F5b": PARTICIPATING_2X_CAP,
    "F6": STACKED,
    "F7": PARI_PASSU,
    "F8a": STACKED,
    "F8b": STACKED,
    "F9": ONE_X_NON_PARTICIPATING,
    "F10": TWO_X_PARTICIPATING,
}
BY_ID = {f.case_id: f for f in FIXTURES}


def engine_payouts(securities, exit_value):
    return {p.security_id: p.amount for p in solve_waterfall(securities, exit_value).payouts}


def verified_schedule(securities, shape: Shape) -> BreakpointSchedule:
    """A hand-built schedule, replayed against the engine to measure its linearity error."""
    ids = [s.security_id for s in securities]
    tranches = []
    for index, (lower, weights) in enumerate(shape):
        upper = shape[index + 1][0] if index + 1 < len(shape) else None
        floats = {i: float(weights.get(i, 0)) for i in ids}
        tranches.append(
            Tranche(
                lower=lower,
                upper=upper,
                weights=floats,
                basis="hand-derived in docs/opm.md",
                weight_sum_error=abs(math.fsum(floats.values()) - 1.0),
            )
        )
    schedule = BreakpointSchedule(
        breakpoints=[
            Breakpoint(
                value=lower, kind="origin" if lower == 0 else "other", basis="hand", exact=True
            )
            for lower, _ in shape
        ],
        tranches=tranches,
        security_ids=ids,
        monotone=True,
        max_weight_sum_error=max(t.weight_sum_error for t in tranches),
        max_linearity_error=0.0,
        linearity_samples=0,
        assumptions=["hand-built for tests/test_opm_allocate.py"],
    )
    edges = [lower for lower, _ in shape]
    probes = {x for e in edges for x in (e, e + 0.5, max(e - 0.5, 0.0))}
    probes |= {(a + b) / 2 for a, b in itertools.pairwise(edges)}
    probes |= {2 * edges[-1] + 1, 3 * edges[-1] + 7, 400 * M}
    gap = 0.0
    for x in probes:
        replay, engine = schedule.payout(x), engine_payouts(securities, x)
        gap = max(gap, *(abs(replay[i] - engine[i]) for i in ids))
    return rebuild(schedule, max_linearity_error=gap, linearity_samples=len(probes))


def rebuild(schedule: BreakpointSchedule, **changes) -> BreakpointSchedule:
    """A validated copy of a schedule with some fields replaced."""
    return BreakpointSchedule.model_validate({**schedule.model_dump(), **changes})


def with_weights(schedule: BreakpointSchedule, index: int, weights: dict[str, float]):
    tranches = [t.model_dump() for t in schedule.tranches]
    tranches[index]["weights"] = weights
    tranches[index]["weight_sum_error"] = abs(math.fsum(weights.values()) - 1.0)
    return rebuild(schedule, tranches=tranches)


def market(equity_value, volatility=0.60, time=3.0, rate=0.04, dividend_yield=0.0):
    return OpmInputs(
        equity_value=equity_value,
        volatility=volatility,
        time_to_liquidity=time,
        risk_free_rate=rate,
        dividend_yield=dividend_yield,
    )


def values(result: OpmResult) -> dict[str, float]:
    return {cv.security_id: cv.value for cv in result.class_values}


def fixture_schedule(case_id: str) -> tuple[WaterfallFixture, BreakpointSchedule]:
    fixture = BY_ID[case_id]
    return fixture, verified_schedule(fixture.securities, SHAPES[case_id])


# --- refusals ---------------------------------------------------------------------------


def test_there_is_no_parameter_that_skips_the_checks():
    """`atol` was added by the coordinator after this test was written, and this test
    caught it, which is what it is for. It is allowed because it cannot skip a check: it
    is forwarded to the breakpoint CONSTRUCTION, while the refusals below compare the
    resulting schedule against `linearity_tolerance(equity_value)`, which `atol` does not
    touch. `test_a_loose_atol_cannot_buy_a_sloppy_schedule` proves that. Any further
    parameter must clear the same bar before it is added here.
    """
    assert list(inspect.signature(opm_allocate).parameters) == [
        "securities",
        "inputs",
        "as_of",
        "schedule",
        "collective_conversion",
        "atol",
    ]


def test_a_loose_atol_cannot_buy_a_sloppy_schedule():
    """A caller who passes an absurd `atol` does not thereby get a looser allocation.

    The construction tolerance and the tolerance the allocation demands are separate
    numbers. Whatever the first lets through, the second still measures against
    `linearity_tolerance(equity_value)`, so the answer is either as verified as ever or
    refused.
    """
    fixture = BY_ID["F1"]
    strict = opm_allocate(fixture.securities, inputs=market(35 * M))
    loose = opm_allocate(fixture.securities, inputs=market(35 * M), atol=1e6)
    assert [(c.security_id, c.value) for c in loose.class_values] == [
        (c.security_id, c.value) for c in strict.class_values
    ]
    assert loose.schedule.max_linearity_error <= linearity_tolerance(35 * M)


def readme_step() -> Discontinuity:
    """A step modelled on GV6 in docs/governance.md, where Series B loses $1,486,956.52 at
    about $57.5M. The offsetting jumps to common and Series A are illustrative only."""
    return Discontinuity(
        value=57_500_000,
        jumps={"series_b": -1_486_956.52, "series_a": 0.0, "common": 1_486_956.52},
        basis="a Requisite Holders vote carries and converts Series B",
        exact=False,
    )


def test_a_step_in_the_payoff_is_refused_as_discontinuous():
    schedule = verified_schedule(gov.TABLE, README)
    stepped = rebuild(schedule, discontinuities=[readme_step()], continuous=False)
    with pytest.raises(OpmAssumptionError) as info:
        opm_allocate(gov.TABLE, inputs=market(50 * M), schedule=stepped)
    message = str(info.value)
    for fragment in ("not continuous", "57,500,000.00", "series_b", "-1,486,956.52", "a step"):
        assert fragment in message


def test_negative_weight_is_refused_naming_the_most_negative_class_tranche_and_weight():
    fixture, schedule = fixture_schedule("F1")
    bad = with_weights(schedule, 1, {"common": 1.05, "series_a": -0.05})
    bad = with_weights(bad, 2, {"common": 1.2, "series_a": -0.2})
    with pytest.raises(OpmAssumptionError) as info:
        opm_allocate(fixture.securities, inputs=market(20 * M), schedule=bad)
    message = str(info.value)
    assert "series_a's share of each marginal dollar in tranches[2]" in message
    assert "[25,000,000.00, unbounded)" in message
    assert "is -0.2," in message
    assert "1 more below the floor" in message
    assert "stops being an allocation" in message


def test_monotone_false_is_refused_even_when_no_weight_is_negative():
    fixture, schedule = fixture_schedule("F1")
    with pytest.raises(OpmAssumptionError, match="monotone=False"):
        opm_allocate(
            fixture.securities, inputs=market(20 * M), schedule=rebuild(schedule, monotone=False)
        )


def test_a_weight_inside_the_floor_is_allowed_and_its_noise_is_counted():
    fixture, schedule = fixture_schedule("F1")
    tiny = NEGATIVE_WEIGHT_FLOOR / 2
    noisy = with_weights(schedule, 1, {"common": 1.0 + tiny, "series_a": -tiny})
    result = opm_allocate(fixture.securities, inputs=market(20 * M), schedule=noisy)
    series_a = next(cv for cv in result.class_values if cv.security_id == "series_a")
    assert series_a.tranche_values[1] == 0.0
    snapped = tiny * result.tranche_option_values[1]
    measured = abs(result.total_allocated - 20 * M)
    assert result.conservation_error == pytest.approx(measured + snapped, rel=1e-6)
    assert result.conservation_error > measured
    assert any("Float noise" in line for line in result.assumptions)


def test_weights_that_do_not_sum_to_one_are_refused():
    fixture, schedule = fixture_schedule("F1")
    bad = with_weights(schedule, 1, {"common": 1.0 + 1e-6, "series_a": 0.0})
    with pytest.raises(OpmAssumptionError) as info:
        opm_allocate(fixture.securities, inputs=market(20 * M), schedule=bad)
    assert "do not sum to one" in str(info.value)
    assert "tranches[1] = [5,000,000.00, 25,000,000.00)" in str(info.value)
    assert "off by 1e-06" in str(info.value)


def test_a_reported_weight_sum_error_is_not_overruled_by_clean_weights():
    fixture, schedule = fixture_schedule("F1")
    bad = rebuild(schedule, max_weight_sum_error=10 * WEIGHT_SUM_TOLERANCE)
    with pytest.raises(OpmAssumptionError, match="schedule's own measurement"):
        opm_allocate(fixture.securities, inputs=market(20 * M), schedule=bad)


def test_a_schedule_never_replayed_is_not_evidence():
    fixture, schedule = fixture_schedule("F1")
    unmeasured = rebuild(schedule, max_linearity_error=0.0, linearity_samples=0)
    with pytest.raises(BreakpointError, match="not evidence"):
        opm_allocate(fixture.securities, inputs=market(20 * M), schedule=unmeasured)


def test_a_replay_gap_beyond_tolerance_is_refused():
    fixture, schedule = fixture_schedule("F1")
    tolerance = linearity_tolerance(20 * M)
    assert tolerance == pytest.approx(0.02)
    rough = rebuild(schedule, max_linearity_error=2 * tolerance)
    with pytest.raises(OpmAssumptionError) as info:
        opm_allocate(fixture.securities, inputs=market(20 * M), schedule=rough)
    assert "not piecewise linear" in str(info.value)
    assert "0.04" in str(info.value) and "0.02" in str(info.value)


def test_a_schedule_for_other_positions_is_refused():
    _, schedule = fixture_schedule("F1")
    with pytest.raises(BreakpointError, match="in the table but not the schedule: pool"):
        opm_allocate(BY_ID["F9"].securities, inputs=market(20 * M), schedule=schedule)


def test_a_schedule_from_another_date_is_refused():
    fixture, schedule = fixture_schedule("F1")
    dated = rebuild(schedule, as_of=date(2027, 1, 1))
    with pytest.raises(BreakpointError, match="2027-01-01"):
        opm_allocate(
            fixture.securities, inputs=market(20 * M), schedule=dated, as_of=date(2026, 1, 1)
        )


def test_a_schedule_from_another_table_with_the_same_ids_fails_the_spot_check():
    """The 1x non-participating schedule claims full verification; the participating table
    pays common $24M at $35M, not $28M, and only the replay at the equity value sees it.
    Common and Series A are both $4M out; the first in table order is named."""
    _, schedule = fixture_schedule("F1")
    with pytest.raises(BreakpointError) as info:
        opm_allocate(BY_ID["F4"].securities, inputs=market(35 * M), schedule=schedule)
    message = str(info.value)
    assert "it pays common 28,000,000.00" in message
    assert "solve_waterfall pays 24,000,000.00" in message
    assert "a gap of 4,000,000.00" in message


def test_under_a_collective_conversion_term_the_spot_check_oracle_is_governance():
    """At $57.6M the vote converts Series B (GV6a): $7,513,043.48, not its $9M preference."""
    schedule = verified_schedule(gov.TABLE, README)
    opm_allocate(gov.TABLE, inputs=market(57.6 * M), schedule=schedule)  # ungoverned: fine
    with pytest.raises(BreakpointError) as info:
        opm_allocate(
            gov.TABLE,
            inputs=market(57.6 * M),
            schedule=schedule,
            collective_conversion=gov.MAJORITY,
        )
    message = str(info.value)
    assert "resolve_collective_conversion under 'mandatory conversion'" in message
    assert "7,513,043.48" in message


def test_refusals_come_in_the_stated_order():
    """continuity, then monotonicity, weight sums, linearity, and correspondence last."""
    fixture, schedule = fixture_schedule("F1")
    table = fixture.securities
    step = Discontinuity(value=30 * M, jumps={"series_a": -1.0}, basis="test step", exact=False)
    negative = with_weights(schedule, 2, {"common": 1.2, "series_a": -0.2})
    off_sum = with_weights(schedule, 2, {"common": 0.8, "series_a": 0.3})
    cases = [
        (rebuild(negative, discontinuities=[step], continuous=False), "not continuous"),
        (rebuild(negative, max_linearity_error=1e6, monotone=False), "not non-decreasing"),
        (rebuild(off_sum, max_linearity_error=1e6), "do not sum to one"),
        (rebuild(schedule, max_linearity_error=1e6), "not piecewise linear"),
    ]
    for bad, expected in cases:
        with pytest.raises(OpmAssumptionError, match=expected):
            opm_allocate(BY_ID["F9"].securities, inputs=market(20 * M), schedule=bad)
    with pytest.raises(BreakpointError, match="not the schedule"):
        opm_allocate(BY_ID["F9"].securities, inputs=market(20 * M), schedule=schedule)
    assert opm_allocate(table, inputs=market(20 * M), schedule=schedule).class_values


# --- the deterministic limit ----------------------------------------------------------

ON_A_BREAKPOINT = {"F3", "F8a"}
OFF_A_BREAKPOINT = [f for f in FIXTURES if f.case_id not in ON_A_BREAKPOINT]
ZERO_RATES = {"time": 1.0, "rate": 0.0, "dividend_yield": 0.0}


@pytest.mark.parametrize("fixture", OFF_A_BREAKPOINT, ids=lambda f: f.case_id)
def test_deterministic_limit_reproduces_the_waterfall_engine(fixture):
    """At volatility 1% with r = q = 0 each position's option value is its engine payout.

    The nearest breakpoint is at least 10 standard deviations away in every one of these
    fixtures, so the residual option value is below float resolution, and the test holds
    each value to a millionth of a dollar.
    """
    schedule = verified_schedule(fixture.securities, SHAPES[fixture.case_id])
    result = opm_allocate(
        fixture.securities,
        inputs=market(fixture.exit_valuation, volatility=0.01, **ZERO_RATES),
        schedule=schedule,
    )
    engine = engine_payouts(fixture.securities, fixture.exit_valuation)
    assert values(result) == pytest.approx(engine, abs=1e-6)
    assert values(result) == pytest.approx(fixture.expected, abs=1e-6)


@pytest.mark.parametrize(
    ("case_id", "slope_change"),
    [
        ("F3", {"common": -0.2, "series_a": 0.2}),
        ("F8a", {"common": 1.0, "series_a": -1.0, "series_b": 0.0}),
    ],
)
@pytest.mark.parametrize("volatility", [1e-2, 1e-3, 1e-4, 1e-6])
def test_deterministic_limit_on_a_breakpoint_leaves_exactly_the_kink_option(
    case_id, slope_change, volatility
):
    """At X on a breakpoint the payoff bends at X itself, so with r = q = 0

        value = payout(X) + dw * X * (2 N(sigma sqrt(T) / 2) - 1),

    the change in slope times an at-the-money call. The second term is O(sigma) and
    vanishes; the formula is evaluated with scipy, not with the call routine under test.
    """
    fixture, schedule = fixture_schedule(case_id)
    exit_value = fixture.exit_valuation
    result = opm_allocate(
        fixture.securities,
        inputs=market(exit_value, volatility=volatility, **ZERO_RATES),
        schedule=schedule,
    )
    at_the_money = exit_value * (2 * norm.cdf(volatility / 2) - 1)
    engine = engine_payouts(fixture.securities, exit_value)
    for security_id, dw in slope_change.items():
        assert values(result)[security_id] == pytest.approx(
            engine[security_id] + dw * at_the_money, abs=1e-6
        )
        assert (
            abs(values(result)[security_id] - engine[security_id])
            <= abs(dw) * exit_value * volatility * 0.4
        )


@pytest.mark.parametrize("fixture", OFF_A_BREAKPOINT, ids=lambda f: f.case_id)
def test_deterministic_limit_through_the_derived_schedule(fixture):
    """The same limit with the breakpoints derived by ovf.opm.breakpoints, not by hand."""
    pytest.importorskip("ovf.opm.breakpoints")
    result = opm_allocate(
        fixture.securities, inputs=market(fixture.exit_valuation, volatility=0.01, **ZERO_RATES)
    )
    engine = engine_payouts(fixture.securities, fixture.exit_valuation)
    tolerance = linearity_tolerance(fixture.exit_valuation) + 1e-6
    assert values(result) == pytest.approx(engine, abs=tolerance)


# --- conservation and monotonicity ------------------------------------------------------

CONSERVATION_TABLES = ["F1", "F4", "F5a", "F6", "F7", "F9", "F10"]
MARKETS = [
    {"volatility": 0.60, "time": 3.0, "rate": 0.04, "dividend_yield": 0.0},
    {"volatility": 0.30, "time": 0.5, "rate": -0.01, "dividend_yield": 0.02},
    {"volatility": 1.50, "time": 10.0, "rate": 0.05, "dividend_yield": -0.01},
    {"volatility": 0.05, "time": 1.0, "rate": 0.0, "dividend_yield": 0.0},
]


@pytest.mark.parametrize("case_id", CONSERVATION_TABLES)
@pytest.mark.parametrize("terms", MARKETS)
@pytest.mark.parametrize("equity_value", [1e6, 2e7, 3e8])
def test_value_is_conserved_and_the_error_is_reported(case_id, terms, equity_value):
    fixture, schedule = fixture_schedule(case_id)
    result = opm_allocate(
        fixture.securities, inputs=market(equity_value, **terms), schedule=schedule
    )
    target = equity_value * math.exp(-terms["dividend_yield"] * terms["time"])
    total = math.fsum(values(result).values())
    assert abs(total - target) <= 1e-9 * target
    assert result.total_allocated == total
    assert result.conservation_error == abs(total - target)
    assert math.fsum(result.tranche_option_values) == pytest.approx(target, rel=1e-12)
    for cv in result.class_values:
        assert cv.value == math.fsum(cv.tranche_values)
        assert len(cv.tranche_values) == len(schedule.tranches)
    assert math.fsum(cv.pct_of_equity for cv in result.class_values) == pytest.approx(1.0)


@pytest.mark.parametrize("case_id", CONSERVATION_TABLES)
def test_each_value_is_non_decreasing_in_equity_value(case_id):
    fixture, schedule = fixture_schedule(case_id)
    grid = np.geomspace(1e5, 1e9, 41)
    rows = [
        values(opm_allocate(fixture.securities, inputs=market(x), schedule=schedule)) for x in grid
    ]
    for (x0, low), (x1, high) in itertools.pairwise(zip(grid, rows, strict=True)):
        for security_id in low:
            assert high[security_id] >= low[security_id] - 1e-12 * x1, (security_id, x0, x1)


def per_share(result: OpmResult) -> dict[str, float]:
    return {cv.security_id: cv.value_per_share for cv in result.class_values}


def test_preferred_per_share_is_at_or_above_common_and_the_gap_closes():
    """1x non-participating: Series A's payoff per share is at or above common's at every
    exit, so its value per share is too; the ratio falls towards one as value rises. At the
    top of the grid the two agree to the last bit, hence the relative allowance of 1e-12."""
    fixture, schedule = fixture_schedule("F1")
    grid = np.geomspace(1e5, 1e11, 61)
    ratios = []
    for x in grid:
        ps = per_share(opm_allocate(fixture.securities, inputs=market(x), schedule=schedule))
        assert ps["series_a"] >= ps["common"] * (1 - 1e-12)
        ratios.append(ps["series_a"] / ps["common"])
    assert all(b <= a * (1 + 1e-12) for a, b in itertools.pairwise(ratios))
    assert ratios[0] > 10
    assert ratios[-1] == pytest.approx(1.0, abs=1e-6)


def test_a_senior_stack_orders_per_share_values_and_the_gaps_close():
    fixture, schedule = fixture_schedule("F6")
    ratios = []
    for x in np.geomspace(1e5, 1e11, 61):
        ps = per_share(opm_allocate(fixture.securities, inputs=market(x), schedule=schedule))
        assert ps["series_b"] >= ps["series_a"] * (1 - 1e-12)
        assert ps["series_a"] >= ps["common"] * (1 - 1e-12)
        ratios.append(ps["series_a"] / ps["common"])
    assert all(b <= a * (1 + 1e-12) for a, b in itertools.pairwise(ratios))
    assert ratios[-1] == pytest.approx(1.0, abs=1e-6)


# --- result shape -------------------------------------------------------------------------


def test_result_lists_every_position_in_table_order_and_states_its_basis():
    fixture, schedule = fixture_schedule("F9")
    result = opm_allocate(fixture.securities, inputs=market(20 * M), schedule=schedule)
    assert [cv.security_id for cv in result.class_values] == ["common", "series_a", "pool"]
    pool = result.class_values[2]
    assert pool.value == 0.0 and pool.shares == 0.0 and pool.value_per_share is None
    assert result.schedule == schedule
    text = " ".join(result.assumptions)
    assert "AICPA Accounting and Valuation Guide" in text
    assert "implemented as published" in text
    assert "no conformance" in text
    assert "supplied by the caller" in text


# --- fixtures derived in docs/opm.md --------------------------------------------------------

DOC_MARKET = market(20 * M, volatility=0.60, time=3.0, rate=0.04)
CENT = 0.005


def test_o1_one_x_non_participating_to_the_cent():
    fixture, schedule = fixture_schedule("F1")
    result = opm_allocate(fixture.securities, inputs=DOC_MARKET, schedule=schedule)
    assert result.tranche_option_values == pytest.approx(
        [4_142_555.67, 8_542_054.77, 7_315_389.56], abs=CENT
    )
    assert values(result) == pytest.approx(
        {"common": 14_394_366.42, "series_a": 5_605_633.58}, abs=CENT
    )
    ps = per_share(result)
    assert ps["series_a"] == pytest.approx(2.80281679, abs=5e-9)
    assert ps["common"] == pytest.approx(1.79929580, abs=5e-9)


def test_o2_participating_with_a_2x_cap_to_the_cent():
    fixture, schedule = fixture_schedule("F5a")
    result = opm_allocate(fixture.securities, inputs=DOC_MARKET, schedule=schedule)
    assert result.tranche_option_values == pytest.approx(
        [4_142_555.67, 9_603_549.07, 2_603_109.29, 3_650_785.96], abs=CENT
    )
    assert values(result) == pytest.approx(
        {"common": 13_206_577.32, "series_a": 6_793_422.68}, abs=CENT
    )
    ps = per_share(result)
    assert ps["series_a"] == pytest.approx(3.39671134, abs=5e-9)
    assert ps["common"] == pytest.approx(1.65082217, abs=5e-9)


def test_o3_participating_uncapped_to_the_cent():
    fixture, schedule = fixture_schedule("F4")
    result = opm_allocate(fixture.securities, inputs=DOC_MARKET, schedule=schedule)
    assert result.tranche_option_values == pytest.approx([4_142_555.67, 15_857_444.33], abs=CENT)
    assert values(result) == pytest.approx(
        {"common": 12_685_955.46, "series_a": 7_314_044.54}, abs=CENT
    )


def test_hand_built_schedules_replay_the_engine():
    """Guard on the test inputs themselves: each shape above matches solve_waterfall."""
    for case_id in SHAPES:
        _, schedule = fixture_schedule(case_id)
        assert schedule.max_linearity_error <= 1e-6, case_id
    readme = verified_schedule(gov.TABLE, README)
    assert readme.max_linearity_error <= 1e-6
