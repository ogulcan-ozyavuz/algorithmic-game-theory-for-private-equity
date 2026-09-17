"""Independent validation of ``ovf.opm`` against a second implementation.

``tests/opm_oracle.py`` derives breakpoints by a different route (exact black-box kink
finding over ``fractions.Fraction``, no candidate families) and values positions by a
different route (Gauss-Legendre quadrature against the lognormal density, no call values).
These tests are small seeded versions of the searches reported in docs/opm-findings.md;
``python -m tests.opm_oracle`` replays the large ones.

The oracle is first checked against hand derivations made elsewhere and before it:
docs/opm-breakpoints.md (BP1, BP3, BP4, BP7) and docs/opm.md (O1-O3). It is only evidence
after that.
"""

from __future__ import annotations

import functools
import math
import random
from fractions import Fraction

import pytest

from ovf.opm import BreakpointError, BreakpointSchedule, OpmAssumptionError, OpmError, OpmInputs
from ovf.opm.allocate import opm_allocate
from ovf.opm.blackscholes import call_value
from ovf.opm.breakpoints import breakpoint_schedule
from ovf.waterfall import solve_waterfall
from tests.opm_oracle import (
    GENERATORS,
    OracleError,
    OracleSchedule,
    Position,
    Table,
    Term,
    UndeterminedIntervalError,
    _system_under_test,
    checks_disabled,
    compare_schedules,
    continuous_kinks,
    digital_value,
    engine_payout,
    lognormal_value,
    oracle_import_violations,
    oracle_schedule,
    pick_spot,
    replay_gap,
)

Q = Fraction
M = 1_000_000

FOUNDERS = Position("common", "founders", "common", shares=Q(8 * M))
SERIES_A_1X = Position("series_a", "series_a", "preferred", shares=Q(2 * M), price=Q(5, 2))
SERIES_B = Position("series_b", "series_b", "preferred", shares=Q(3 * M, 2), price=Q(6))
README = Table(
    "hand",
    0,
    (
        FOUNDERS,
        Position(
            "series_a",
            "series_a",
            "preferred",
            shares=Q(2 * M),
            price=Q(5, 2),
            seniority=2,
            participating=True,
            cap=Q(2),
        ),
        SERIES_B,
    ),
)
MAJORITY = Term(("series_a", "series_b"), ((("series_a", "series_b"), Q(1, 2), "more_than"),))
ALL = {"common": Q(16, 23), "series_a": Q(4, 23), "series_b": Q(3, 23)}


def _weights(schedule: OracleSchedule) -> list[dict[str, Fraction]]:
    return [
        {sid: w for sid, w in zip(schedule.ids, slope, strict=True) if w}
        for slope in schedule.slopes
    ]


@functools.cache
def _ours(table: Table) -> OracleSchedule | str:
    try:
        return oracle_schedule(table)
    except UndeterminedIntervalError:
        return "undetermined"


def _theirs(table: Table) -> BreakpointSchedule:
    return breakpoint_schedule(
        table.securities(), as_of=table.as_of, collective_conversion=table.collective_conversion()
    )


def _inputs(spot: float, sigma: float, years: float, rate: float, q: float = 0.0) -> OpmInputs:
    return OpmInputs(
        equity_value=spot,
        volatility=sigma,
        time_to_liquidity=years,
        risk_free_rate=rate,
        dividend_yield=q,
    )


# ---------------------------------------------------------------------------
# The oracle, checked first against hand derivations made elsewhere
# ---------------------------------------------------------------------------


def test_the_oracle_shares_no_code_with_the_modules_under_test() -> None:
    assert oracle_import_violations() == []


def test_oracle_bp1_bp3_bp4_match_docs_opm_breakpoints() -> None:
    """BP1: 5M and 25M. BP3 (B senior): 9M, 14M, 34M, 69M. BP4 (pari passu): 14M, 34M, 69M,
    with 5M and 9M not kinks. Derived by hand in docs/opm-breakpoints.md."""
    bp1 = oracle_schedule(Table("hand", 0, (FOUNDERS, SERIES_A_1X)))
    assert bp1.knots == (0, 5 * M, 25 * M)
    assert _weights(bp1) == [
        {"series_a": 1},
        {"common": 1},
        {"common": Q(4, 5), "series_a": Q(1, 5)},
    ]
    stacked = (FOUNDERS, Position(**{**SERIES_A_1X.__dict__, "seniority": 2}), SERIES_B)
    assert oracle_schedule(Table("hand", 0, stacked)).knots == (0, 9 * M, 14 * M, 34 * M, 69 * M)
    pari = (FOUNDERS, SERIES_A_1X, SERIES_B)
    bp4 = oracle_schedule(Table("hand", 0, pari))
    assert bp4.knots == (0, 14 * M, 34 * M, 69 * M)
    assert _weights(bp4)[0] == {"series_a": Q(5, 14), "series_b": Q(9, 14)}
    assert _weights(bp4)[-1] == ALL


def test_oracle_readme_table_without_the_term() -> None:
    """docs/opm-breakpoints.md BP7, 'without the term': 9M, 14M, 39M, 59M, 69M."""
    schedule = oracle_schedule(README)
    assert schedule.knots == (0, 9 * M, 14 * M, 39 * M, 59 * M, 69 * M)
    assert _weights(schedule) == [
        {"series_b": 1},
        {"series_a": 1},
        {"common": Q(4, 5), "series_a": Q(1, 5)},
        {"common": 1},
        {"common": Q(4, 5), "series_a": Q(1, 5)},
        ALL,
    ]
    assert schedule.continuous and schedule.monotone


def test_oracle_readme_table_under_the_majority_term() -> None:
    """docs/opm-breakpoints.md BP7, 'with the term': steps at 207/19 M and 57.5M, with
    jumps -+144/19 M and +-1.5M, and no negative weight anywhere."""
    schedule = oracle_schedule(README.__class__("hand", 0, README.positions, MAJORITY))
    assert schedule.knots == (0, Q(207 * M, 19), 14 * M, 39 * M, Q(115 * M, 2))
    assert _weights(schedule) == [
        ALL,
        {"series_a": 1},
        {"common": Q(4, 5), "series_a": Q(1, 5)},
        {"common": 1},
        ALL,
    ]
    assert schedule.steps == (
        (Q(207 * M, 19), (-Q(144 * M, 19), Q(0), Q(144 * M, 19))),
        (Q(115 * M, 2), (Q(3 * M, 2), Q(0), -Q(3 * M, 2))),
    )
    assert not schedule.continuous and not schedule.monotone and not schedule.negative_weight


@pytest.mark.parametrize(
    ("positions", "expected"),
    [
        ((FOUNDERS, SERIES_A_1X), {"series_a": 5_605_633.58, "common": 14_394_366.42}),
        (
            (FOUNDERS, Position(**{**SERIES_A_1X.__dict__, "participating": True, "cap": Q(2)})),
            {"series_a": 6_793_422.68, "common": 13_206_577.32},
        ),
        (
            (FOUNDERS, Position(**{**SERIES_A_1X.__dict__, "participating": True})),
            {"series_a": 7_314_044.54, "common": 12_685_955.46},
        ),
    ],
    ids=["O1", "O2", "O3"],
)
def test_quadrature_reproduces_docs_opm_o1_to_o3_to_the_cent(
    positions: tuple[Position, ...], expected: dict[str, float]
) -> None:
    """S = $20M, 60% volatility, 3 years, 4%: docs/opm.md derives these by hand and in
    60-digit decimal. The quadrature evaluates no call value and no normal CDF."""
    schedule = oracle_schedule(Table("hand", 0, positions))
    result = lognormal_value(schedule, spot=20 * M, volatility=0.6, time=3.0, rate=0.04)
    for sid, value in expected.items():
        assert result.values[sid] == pytest.approx(value, abs=0.005)


@pytest.mark.parametrize("sigma", [1e-6, 1e-3, 0.3, 1.0, 3.0])
@pytest.mark.parametrize("years", [1 / 12, 1.0, 10.0])
def test_quadrature_integrates_the_density_and_the_spot(sigma: float, years: float) -> None:
    schedule = oracle_schedule(README)
    for rate, q in ((0.04, 0.0), (-0.01, 0.02)):
        result = lognormal_value(
            schedule, spot=30 * M, volatility=sigma, time=years, rate=rate, dividend_yield=q
        )
        assert result.mass_error <= 1e-13 and result.mean_error <= 1e-13
        assert math.fsum(result.values.values()) == pytest.approx(
            30 * M * math.exp(-q * years), rel=1e-13
        )


def test_the_kink_finder_refuses_a_step_rather_than_smearing_it() -> None:
    def step(x: Fraction) -> tuple[Fraction, ...]:
        return (Q(0),) if x < Q(1, 3) else (Q(1),)

    with pytest.raises(OracleError, match="not continuous"):
        continuous_kinks(step, Q(0), Q(1), max_splits=300)


# ---------------------------------------------------------------------------
# Search 1: two breakpoint derivations, on generated tables
# ---------------------------------------------------------------------------

SEEDED = [("adversarial", s) for s in range(12)] + [("venture", s) for s in range(6)]


@pytest.mark.parametrize(("generator", "seed"), SEEDED)
def test_two_breakpoint_derivations_agree(generator: str, seed: int) -> None:
    """Count, position, weights, steps, jumps and flags, with and without the term; and the
    oracle replays the float engine, which it was not derived from."""
    governed = GENERATORS[generator](seed)
    for table in (governed.plain(), governed):
        ours = _ours(table)
        if ours == "undetermined":
            with pytest.raises(BreakpointError, match="refuses to price"):
                _theirs(table)
            continue
        assert isinstance(ours, OracleSchedule)
        found = compare_schedules(ours, _theirs(table))
        context = (table.describe(), found)
        assert not found["unmatched_ours"] and not found["unmatched_theirs"], context
        assert found["count_ours"] == found["count_theirs"], context
        assert found["weight_gap"] <= 1e-9, context
        assert not found["unmatched_steps"] and found["jump_gap"] <= 1e-6, context
        assert found["monotone"][0] == found["monotone"][1], context
        assert found["continuous"][0] == found["continuous"][1], context
        gap, priced = replay_gap(table, ours)
        assert priced > 0 and gap <= 1e-6, (context, gap)


# ---------------------------------------------------------------------------
# Search 2 and 3: call spreads against quadrature, and conservation
# ---------------------------------------------------------------------------

GRID = [
    (0.01, 1.0, 0.04, 0.0),
    (0.3, 1 / 12, 0.04, 0.0),
    (0.6, 3.0, 0.04, 0.0),
    (1.0, 5.0, -0.01, 0.02),
    (3.0, 10.0, 0.04, 0.0),
]


@pytest.mark.parametrize(
    ("generator", "seed"), [("adversarial", 0), ("adversarial", 2), ("venture", 0), ("venture", 3)]
)
def test_call_spreads_agree_with_quadrature_and_conserve_value(generator: str, seed: int) -> None:
    table = GENERATORS[generator](seed).plain()
    ours = _ours(table)
    assert isinstance(ours, OracleSchedule)
    theirs = _theirs(table)
    spot = pick_spot(ours, random.Random(seed))
    for sigma, years, rate, q in GRID:
        result = opm_allocate(
            table.securities(),
            inputs=_inputs(spot, sigma, years, rate, q),
            as_of=table.as_of,
            schedule=theirs,
        )
        integral = lognormal_value(
            ours, spot=spot, volatility=sigma, time=years, rate=rate, dividend_yield=q
        )
        forward = spot * math.exp(-q * years)
        for cv in result.class_values:
            assert abs(cv.value - integral.values[cv.security_id]) <= 1e-12 * forward
        assert result.conservation_error <= 1e-12 * forward
        assert abs(math.fsum(cv.value for cv in result.class_values) - forward) <= 1e-12 * forward


# ---------------------------------------------------------------------------
# Search 4: the deterministic limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sigma", [1e-3, 1e-5, 1e-8])
def test_deterministic_limit_off_and_on_a_breakpoint(sigma: float) -> None:
    """Off a breakpoint ($25M, 1.02 log-units from the nearest) the value is the engine's
    payout to float precision. On one ($39M, the cap) it exceeds the payout by exactly the
    kink option dw * S * (2 N(sigma/2) - 1) = dw * S * erf(sigma / (2 sqrt 2)) of docs/opm.md,
    with dw = +1/5 for common and -1/5 for Series A."""
    securities = README.securities()
    schedule = breakpoint_schedule(securities)
    for spot, dw in ((25.0 * M, {}), (39.0 * M, {"common": 0.2, "series_a": -0.2})):
        result = opm_allocate(securities, inputs=_inputs(spot, sigma, 1.0, 0.0), schedule=schedule)
        engine = {p.security_id: p.amount for p in solve_waterfall(securities, spot).payouts}
        kink = spot * math.erf(sigma / (2 * math.sqrt(2.0)))
        for cv in result.class_values:
            expected = engine[cv.security_id] + dw.get(cv.security_id, 0.0) * kink
            assert cv.value == pytest.approx(expected, abs=1e-5 + 1e-15 * spot)


# ---------------------------------------------------------------------------
# Search 5: how often the method applies
# ---------------------------------------------------------------------------


@functools.cache
def _verdict(table: Table) -> str:
    ours = _ours(table)
    spot = pick_spot(ours, random.Random(0)) if isinstance(ours, OracleSchedule) else 1.0
    try:
        opm_allocate(
            table.securities(),
            inputs=_inputs(spot, 0.6, 3.0, 0.04),
            as_of=table.as_of,
            collective_conversion=table.collective_conversion(),
        )
    except OpmAssumptionError as exc:
        return "step" if "not continuous" in str(exc) else "not monotone"
    except BreakpointError as exc:
        return "undetermined" if "refuses to price" in str(exc) else f"breakpoint error: {exc}"
    return "applies"


@pytest.mark.parametrize(("generator", "seed"), SEEDED)
def test_opm_refuses_exactly_where_the_oracle_finds_a_step(generator: str, seed: int) -> None:
    governed = GENERATORS[generator](seed)
    assert _verdict(governed.plain()) == "applies"
    ours = _ours(governed)
    expected = (
        "undetermined"
        if ours == "undetermined"
        else "step"
        if isinstance(ours, OracleSchedule) and not ours.continuous
        else "not monotone"
        if isinstance(ours, OracleSchedule) and not ours.monotone
        else "applies"
    )
    assert _verdict(governed) == expected, governed.describe()


def test_the_seeded_subset_is_refused_only_under_the_term() -> None:
    governed = [GENERATORS[g](s) for g, s in SEEDED]
    assert all(_verdict(t.plain()) == "applies" for t in governed)
    assert sum(_verdict(t) != "applies" for t in governed) >= 3


# ---------------------------------------------------------------------------
# Search 6: what the unchecked construction would have said
# ---------------------------------------------------------------------------


def test_unchecked_value_misses_by_the_digital_value_of_each_step() -> None:
    """On the README table under the majority term, dropping the continuity and monotonicity
    checks gives a well-formed allocation that conserves value exactly, and that misses the
    integral of the true payoff by -sum over steps of jump x exp(-rT) P(X_T >= step)."""
    table = Table("hand", 0, README.positions, MAJORITY)
    securities, term = table.securities(), table.collective_conversion()
    theirs = breakpoint_schedule(securities, collective_conversion=term)
    ours = oracle_schedule(table)
    spot, sigma, years, rate = 60.0 * M, 0.6, 3.0, 0.04
    with pytest.raises(OpmAssumptionError, match="not continuous"):
        opm_allocate(
            securities, inputs=_inputs(spot, sigma, years, rate), collective_conversion=term
        )
    sut = _system_under_test()
    with checks_disabled(sut):
        unchecked = opm_allocate(
            securities,
            inputs=_inputs(spot, sigma, years, rate),
            schedule=theirs,
            collective_conversion=term,
        )
    values = {cv.security_id: cv.value for cv in unchecked.class_values}
    assert math.fsum(values.values()) == pytest.approx(spot, rel=1e-12)
    assert unchecked.conservation_error <= 1e-9 * spot
    truth = lognormal_value(ours, spot=spot, volatility=sigma, time=years, rate=rate)
    for c, sid in enumerate(ours.ids):
        digital = math.fsum(
            float(jumps[c])
            * digital_value(
                float(level), spot=spot, volatility=sigma, time=years, rate=rate, dividend_yield=0
            )
            for level, jumps in ours.steps
        )
        assert values[sid] - truth.values[sid] == pytest.approx(-digital, abs=1e-8 * spot)
    assert abs(values["series_b"] - truth.values["series_b"]) > 0.05 * spot


def test_the_engine_refuses_the_vote_exactly_at_a_step() -> None:
    table = Table("hand", 0, README.positions, MAJORITY)
    for level, _ in oracle_schedule(table).steps:
        assert engine_payout(table, float(level)) is None


# ---------------------------------------------------------------------------
# Defects found in other modules: the correct behaviour, asserted (docs/opm-findings.md)
# ---------------------------------------------------------------------------


def test_call_value_when_total_volatility_underflows_is_the_discounted_intrinsic() -> None:
    """docs/opm-findings.md D1. docs/opm.md's limits table: when sigma * sqrt(T) underflows the
    payoff is known with certainty, max(S e^-qT - K e^-rT, 0). F1 ($35M on the 1x
    non-participating table, docs/fixtures.md) is then common $28M and Series A $7M."""
    assert call_value(2.0, 1.0, 1e-300, 1e-60, 0.0) == 1.0
    assert call_value(1.0, 2.0, 1e-300, 1e-60, 0.0) == 0.0
    table = Table("hand", 0, (FOUNDERS, SERIES_A_1X))
    try:
        result = opm_allocate(table.securities(), inputs=_inputs(35.0 * M, 1e-300, 1e-60, 0.0))
    except OpmError:
        return
    values = {cv.security_id: cv.value for cv in result.class_values}
    assert values == pytest.approx({"common": 28.0 * M, "series_a": 7.0 * M}, abs=1e-6)


ISOLATED = Table(
    "hand",
    0,
    (
        Position("common", "founders", "common", shares=Q(100)),
        Position("p0", "h0", "preferred", shares=Q(800), price=Q(2), seniority=3),
        Position("p1", "h1", "preferred", shares=Q(200), price=Q(2), seniority=2, multiple=Q(3, 2)),
    ),
    Term(("p0", "p1"), ((("p0", "p1"), Q(3, 5), "at_least"),)),
)
"""The table of tests/test_opm_breakpoints.py::test_an_isolated_undefined_point_is_recorded_not_
refused, derived by hand in its docstring: h0 (800 of 1,000 votes) gains 600 - 3X/11 below
X = 2,200 and 8X/11 - 1,600 above it, touching zero only there, so the vote carries at every
other exit and the governed payoff is the single line 1/11, 8/11, 2/11."""


def test_oracle_isolated_undefined_vote_point_is_one_continuous_line() -> None:
    schedule = oracle_schedule(ISOLATED)
    assert schedule.knots == (0,) and schedule.continuous and schedule.monotone
    assert _weights(schedule) == [{"common": Q(1, 11), "p0": Q(8, 11), "p1": Q(2, 11)}]
    assert engine_payout(ISOLATED, 2200.0) is None


def test_allocation_at_an_isolated_undefined_vote_point_matches_its_neighbours() -> None:
    """docs/opm-findings.md D2. The payoff is one continuous line, so the value at the tie exit
    is defined: it must be priced, lie between its neighbours, and agree with the quadrature."""
    term = ISOLATED.collective_conversion()
    values = {}
    for spot in (2199.0, 2200.0, 2201.0):
        result = opm_allocate(
            ISOLATED.securities(), inputs=_inputs(spot, 0.6, 3.0, 0.04), collective_conversion=term
        )
        values[spot] = {cv.security_id: cv.value for cv in result.class_values}
    truth = lognormal_value(
        oracle_schedule(ISOLATED), spot=2200.0, volatility=0.6, time=3.0, rate=0.04
    )
    for sid, value in values[2200.0].items():
        assert values[2199.0][sid] < value < values[2201.0][sid]
        assert value == pytest.approx(truth.values[sid], abs=1e-9)
    assert math.fsum(values[2200.0].values()) == pytest.approx(2200.0, rel=1e-12)


def test_a_governed_table_is_not_refused_for_its_origin_probe() -> None:
    """docs/opm-findings.md D3. venture_table(256) under its term: the vote carries below
    about $14M and is moot above it, where every series converts anyway, so the governed
    payoff is one line and the method applies. The origin probe of the breakpoint derivation
    sat at X = 1e-6, inside ovf.governance's absolute tie band of 1e-8, where fund0's exact
    gain from the conversion is 3.2e-9, and the whole table was refused."""
    table = GENERATORS["venture"](256)
    ours = _ours(table)
    assert isinstance(ours, OracleSchedule) and ours.knots == (0,) and ours.continuous
    found = compare_schedules(ours, _theirs(table))
    assert not found["unmatched_ours"] and not found["unmatched_theirs"], found
    assert found["weight_gap"] <= 1e-9 and found["continuous"] == (True, True), found
    spot = 10.0 * M
    result = opm_allocate(
        table.securities(),
        inputs=_inputs(spot, 0.6, 3.0, 0.04),
        collective_conversion=table.collective_conversion(),
    )
    truth = lognormal_value(ours, spot=spot, volatility=0.6, time=3.0, rate=0.04)
    for cv in result.class_values:
        assert cv.value == pytest.approx(truth.values[cv.security_id], abs=1e-9 * spot)


def test_a_tranche_midpoint_on_an_isolated_tie_does_not_refuse_the_schedule() -> None:
    """docs/opm-findings.md D5. adversarial_table(1316) under its term: h0's and h3's exact
    gains both cross zero at X = 7,600, so the vote is undefined at that one exit and fails
    on either side of it. The governed payoff is continuous there and steps at 15,200 and
    49400/3. The midpoint of the tranche [5,200, 10,000), probed only to describe the
    tranche, is exactly 7,600, and the whole schedule was refused with a false reason."""
    table = GENERATORS["adversarial"](1316)
    ours = _ours(table)
    assert isinstance(ours, OracleSchedule)
    assert [c for c, _ in ours.steps] == [Q(15200), Q(49400, 3)]
    assert Q(5200) in ours.knots and Q(10000) in ours.knots and Q(7600) not in ours.knots
    found = compare_schedules(ours, _theirs(table))
    assert not found["unmatched_ours"] and not found["unmatched_theirs"], found
    assert not found["unmatched_steps"] and found["jump_gap"] <= 1e-6, found
    assert _verdict(table) == "step"
