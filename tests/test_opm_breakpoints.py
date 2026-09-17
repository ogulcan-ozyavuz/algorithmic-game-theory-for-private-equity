"""Breakpoint schedules derived from the waterfall engine, checked against it and by hand.

Expected breakpoints, weights and jumps are the hand derivations of docs/opm-breakpoints.md,
stated in tests/opm_breakpoint_fixtures.py. Generated tables are checked against the engine
and against the exact-rational oracle of tests/test_governance.py, which was written without
reference to ovf.waterfall and is itself checked against hand-derived fixtures there.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from datetime import date
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

import pytest

import ovf
import ovf.opm.breakpoints as bp
from ovf.governance import CollectiveConversion, VoteRequirement, resolve_collective_conversion
from ovf.opm import BreakpointError, BreakpointSchedule
from ovf.opm.breakpoints import breakpoint_schedule
from ovf.waterfall import solve_waterfall
from tests import governance_fixtures as gv
from tests.opm_breakpoint_fixtures import (
    AS_OF,
    FIXTURES,
    FLIP_HIGH,
    FLIP_LOW,
    BreakpointFixture,
    founders,
    generated_table,
    series_a,
)
from tests.test_governance import _sid, exact_equilibria, exact_vote, random_vote_instance
from tests.test_governance import to_securities as exact_to_securities

Q = Fraction
M = 1_000_000
ATOL = 1e-6


def _fixture(case_id: str) -> BreakpointFixture:
    return next(f for f in FIXTURES if f.case_id == case_id)


def _schedule(fixture: BreakpointFixture) -> BreakpointSchedule:
    return breakpoint_schedule(
        fixture.securities, as_of=fixture.as_of, collective_conversion=fixture.term
    )


def _engine(
    securities: Any, x: float, *, as_of: date | None = None, term: Any = None
) -> dict[str, float]:
    if term is None:
        result = solve_waterfall(securities, x, as_of=as_of)
    else:
        result = resolve_collective_conversion(securities, x, term=term, as_of=as_of).result
    return {p.security_id: p.amount for p in result.payouts}


def _gap(a: dict[str, float], b: dict[str, float]) -> float:
    return max(abs(a[k] - b[k]) for k in b)


def _probes(schedule: BreakpointSchedule, rng: random.Random) -> list[float]:
    """Every breakpoint, both sides of it, and interior points of every tranche."""
    steps = {d.value for d in schedule.discontinuities}
    edges = [t.lower for t in schedule.tranches]
    top = 3 * max(edges[-1], 1.0)
    out: list[float] = []
    for i, x in enumerate(edges):
        gap = min(
            x - edges[i - 1] if i else math.inf,
            (edges[i + 1] if i + 1 < len(edges) else top) - x,
        )
        d = min(1e-3 * max(x, 1.0), gap / 4)
        out += [x - d, x + d] if x else [d]
        if x not in steps:
            out.append(x)
    for lo, hi in zip(edges, [*edges[1:], top], strict=True):
        out += [lo + rng.random() * (hi - lo) for _ in range(3)]
    return [x for x in out if x >= 0]


# ---------------------------------------------------------------------------
# BP1-BP7: the hand derivations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_breakpoints_are_the_hand_derived_ones(fixture: BreakpointFixture) -> None:
    schedule = _schedule(fixture)
    first, *rest = schedule.breakpoints
    assert (first.value, first.kind, first.exact) == (0.0, "origin", True)
    assert [(b.value, b.kind) for b in rest] == [
        (float(value), kind) for value, kind in fixture.breakpoints
    ]
    assert all(b.exact for b in rest), "every fixture breakpoint is closed-form"
    assert [t.lower for t in schedule.tranches] == [b.value for b in schedule.breakpoints]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_weights_are_the_hand_derived_ones(fixture: BreakpointFixture) -> None:
    schedule = _schedule(fixture)
    assert len(schedule.tranches) == len(fixture.weights)
    for tranche, expected in zip(schedule.tranches, fixture.weights, strict=True):
        assert set(tranche.weights) == set(schedule.security_ids)
        for security_id, weight in tranche.weights.items():
            assert weight == pytest.approx(float(expected.get(security_id, 0)), abs=1e-12), (
                tranche.lower,
                security_id,
            )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_steps_and_flags(fixture: BreakpointFixture) -> None:
    schedule = _schedule(fixture)
    assert schedule.monotone is fixture.monotone
    assert schedule.continuous is (not fixture.jumps)
    assert [d.value for d in schedule.discontinuities] == [float(x) for x, _ in fixture.jumps]
    for step, (_, jumps) in zip(schedule.discontinuities, fixture.jumps, strict=True):
        assert step.exact
        assert set(step.jumps) == set(schedule.security_ids)
        for security_id, jump in step.jumps.items():
            assert jump == pytest.approx(float(jumps.get(security_id, 0)), abs=1e-6)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_payouts_replay_the_repository_fixtures(fixture: BreakpointFixture) -> None:
    schedule = _schedule(fixture)
    for x, expected, source in fixture.payouts:
        replay = schedule.payout(float(x))
        engine = _engine(fixture.securities, float(x), as_of=fixture.as_of, term=fixture.term)
        for security_id in schedule.security_ids:
            want = float(expected.get(security_id, 0))
            assert replay[security_id] == pytest.approx(want, abs=1e-6), (source, security_id)
            assert engine[security_id] == pytest.approx(want, abs=1e-6), (source, security_id)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_fixture_replays_the_engine_everywhere_it_is_defined(fixture: BreakpointFixture) -> None:
    schedule = _schedule(fixture)
    rng = random.Random(fixture.case_id)
    for x in _probes(schedule, rng):
        engine = _engine(fixture.securities, x, as_of=fixture.as_of, term=fixture.term)
        assert _gap(schedule.payout(x), engine) <= ATOL, x
    assert 0.0 <= schedule.max_linearity_error <= ATOL
    assert schedule.linearity_samples > 5 * len(schedule.breakpoints)
    assert schedule.max_weight_sum_error <= 1e-12
    for tranche in schedule.tranches:
        assert tranche.weight_sum_error == abs(math.fsum(tranche.weights.values()) - 1.0)


@pytest.mark.parametrize(
    "fixture", [f for f in FIXTURES if f.not_breakpoints], ids=lambda f: f.case_id
)
def test_candidates_a_hand_table_would_list_are_probed_and_dropped(
    fixture: BreakpointFixture,
) -> None:
    """Each value is generated as an analytic candidate and the engine shows it is no kink."""
    schedule = _schedule(fixture)
    model = bp._exact_model(fixture.securities, fixture.as_of)
    candidates = bp._analytic_candidates(model, fixture.term, fixture.as_of).reasons
    kept = {b.value for b in schedule.breakpoints}
    for value in fixture.not_breakpoints:
        if fixture.case_id != "BP6":  # 27.5M is the fully diluted mistake, not a candidate
            assert value in candidates, value
        assert float(value) not in kept, value


def test_bp1_is_the_textbook_table_derived_from_the_engine() -> None:
    schedule = _schedule(_fixture("BP1"))
    assert [b.value for b in schedule.breakpoints] == [0.0, 5 * M, 25 * M]
    weights = [{k: w for k, w in t.weights.items() if w} for t in schedule.tranches]
    assert weights == [
        {"series_a": 1.0},
        {"common": 1.0},
        {"series_a": pytest.approx(0.2, abs=1e-15), "common": pytest.approx(0.8, abs=1e-15)},
    ]
    assert "indifferent between holding and converting" in schedule.breakpoints[2].basis


def test_bp6_the_pool_dilutes_ownership_but_takes_no_cash() -> None:
    fixture = _fixture("BP6")
    schedule = _schedule(fixture)
    assert all(t.weights["pool"] == 0.0 for t in schedule.tranches)
    fully_diluted = 2_000_000 / (8_000_000 + 2_000_000 + 1_000_000)
    assert fully_diluted == pytest.approx(2 / 11)
    assert schedule.tranches[-1].weights["series_a"] == pytest.approx(1 / 5)
    assert schedule.breakpoints[-1].value == 25 * M  # not 5M / (2/11) = 27.5M
    ownership = ovf.CapTable(securities=list(fixture.securities)).ownership_breakdown()
    assert ownership["series_a"] == pytest.approx(2 / 11)
    assert ownership["esop"] == pytest.approx(1 / 11)


def test_bp5_debt_is_repaid_first_and_needs_a_date() -> None:
    fixture = _fixture("BP5")
    schedule = _schedule(fixture)
    assert schedule.breakpoints[1].kind == "debt_repaid"
    assert "as of 2027-01-01" in schedule.breakpoints[1].basis
    assert schedule.as_of == AS_OF
    with pytest.raises(BreakpointError, match="explicit as_of"):
        breakpoint_schedule(fixture.securities)


# ---------------------------------------------------------------------------
# BP7: the table the Option Pricing Method cannot price
# ---------------------------------------------------------------------------


def test_bp7_the_vote_makes_cash_step_down_as_the_exit_rises() -> None:
    fixture = _fixture("BP7")
    schedule = _schedule(fixture)
    assert schedule.monotone is False and schedule.continuous is False
    low, high = schedule.discontinuities
    # At 207/19 M the vote stops carrying: founders lose 144/19 M, series_b regains it.
    assert low.value == float(FLIP_LOW)
    assert low.jumps["common"] == pytest.approx(-144 * M / 19, abs=1e-6)
    assert low.jumps["series_b"] == pytest.approx(144 * M / 19, abs=1e-6)
    # At 57.5M (GV6) it starts carrying again: series_b loses 1.5M, founders gain it.
    assert high.value == float(FLIP_HIGH)
    assert high.jumps["series_b"] == pytest.approx(-1_500_000, abs=1e-6)
    assert high.jumps["common"] == pytest.approx(1_500_000, abs=1e-6)
    # The pivotal holder is indifferent at each flip, so its own cash does not step.
    assert low.jumps["series_a"] == pytest.approx(0, abs=1e-6)
    assert high.jumps["series_a"] == pytest.approx(0, abs=1e-6)
    assert low.size == pytest.approx(144 * M / 19, abs=1e-6)


def test_bp7_the_failure_is_a_step_not_a_negative_slope() -> None:
    """No tranche carries a negative weight: every fall happens at a step."""
    schedule = _schedule(_fixture("BP7"))
    assert all(w >= 0.0 for t in schedule.tranches for w in t.weights.values())
    assert any("not in the span" in a for a in schedule.assumptions)
    assert any(
        "common falls 7,578,947.37 at X = 10,894,736.84" in a
        and "series_b falls 1,500,000.00 at X = 57,500,000.00" in a
        for a in schedule.assumptions
    )


def test_bp7_matches_gv6a_and_gv6b_on_either_side_of_the_knife_edge() -> None:
    schedule = _schedule(_fixture("BP7"))
    below = schedule.payout(57.4 * M)
    above = schedule.payout(57.6 * M)
    assert below["series_b"] == pytest.approx(9 * M, abs=1e-6)
    assert above["series_b"] == pytest.approx(172.8 / 23 * M, abs=1e-6)
    assert below["series_b"] - above["series_b"] == pytest.approx(1_486_956.52, abs=0.01)


def test_bp7_the_value_at_the_step_is_undefined_and_payout_takes_the_right_limit() -> None:
    fixture = _fixture("BP7")
    schedule = _schedule(fixture)
    for step in schedule.discontinuities:
        with pytest.raises(ovf.governance.GovernanceIndeterminateError):
            resolve_collective_conversion(fixture.securities, step.value, term=fixture.term)
        assert "undefined" in step.basis and "limit from above" in step.basis
        offset = step.value * 1e-9
        just_above = _engine(fixture.securities, step.value + offset, term=fixture.term)
        assert _gap(schedule.payout(step.value), just_above) <= 2 * offset


def test_bp7_without_the_term_the_same_table_is_monotone_and_continuous() -> None:
    schedule = breakpoint_schedule(gv.TABLE)
    assert schedule.monotone and schedule.continuous and not schedule.discontinuities
    assert [b.value for b in schedule.breakpoints] == [0.0, 9 * M, 14 * M, 39 * M, 59 * M, 69 * M]


def test_bp7_candidates_include_the_exact_vote_flips() -> None:
    model = bp._exact_model(gv.TABLE, None)
    candidates = bp._analytic_candidates(model, gv.MAJORITY, None).reasons
    flips = sorted(
        x for x, rs in candidates.items() if any(r.kind == "forced_conversion" for r in rs)
    )
    assert flips[:2] == [FLIP_LOW, FLIP_HIGH]
    assert FLIP_LOW == Q(207 * M, 19)


# ---------------------------------------------------------------------------
# Generated tables
# ---------------------------------------------------------------------------


BAD_GENERATED = (
    "refused",
    "located",
    "not_monotone",
    "discontinuous",
    "linearity_above_atol",
    "replay_gap",
    "weight_sum_misreported",
)
BAD_GOVERNED = (
    "refused_unexplained",
    "located",
    "flag_mismatch",
    "interior_undetermined",
    "payout_mismatch",
    "jump_mismatch",
)


def check_generated(seed: int) -> tuple[Counter[str], float]:
    """One generated table: replay the engine at every breakpoint, 10^-3 either side of it
    and three random exits per tranche; check the recorded weight sums; compare every weight
    with the exact oracle's slope. Returns event counts and the largest weight-slope gap."""
    table = generated_table(seed)
    stats: Counter[str] = Counter(tables=1)
    try:
        schedule = breakpoint_schedule(table.securities, as_of=table.as_of)
    except BreakpointError:
        stats["refused"] += 1
        return stats, 0.0
    stats["breakpoints"] += len(schedule.breakpoints) - 1
    stats["located"] += sum(not b.exact for b in schedule.breakpoints)
    stats["not_monotone"] += not schedule.monotone
    stats["discontinuous"] += not schedule.continuous
    stats["linearity_above_atol"] += schedule.max_linearity_error > ATOL
    for x in _probes(schedule, random.Random(seed)):
        stats["probes"] += 1
        if _gap(schedule.payout(x), _engine(table.securities, x, as_of=table.as_of)) > ATOL:
            stats["replay_gap"] += 1
    worst = 0.0
    for tranche in schedule.tranches:
        measured = abs(math.fsum(tranche.weights.values()) - 1.0)
        if not measured == tranche.weight_sum_error <= schedule.max_weight_sum_error:
            stats["weight_sum_misreported"] += 1
        worst = max(worst, _oracle_slope_gap(table, tranche.lower, tranche.upper, tranche.weights))
    return stats, worst


def _oracle_slope_gap(
    table: Any, lower: float, upper: float | None, weights: dict[str, float]
) -> float:
    """Largest gap between a tranche's weights and the exact oracle's slopes at its middle."""
    lo = Q(lower)
    hi = Q(upper) if upper is not None else lo + 1000
    mid, h = (lo + hi) / 2, (hi - lo) / 1000
    ends = []
    for x in (mid - h, mid + h):
        equity = x - table.debt
        if equity <= 0:
            ends.append(None)
            continue
        _, vectors = exact_equilibria(table.positions, equity)
        assert len(vectors) == 1, (table.seed, x)
        ends.append(next(iter(vectors)))
    expected: dict[str, float] = {}
    for i in range(len(table.positions)):
        a, b = (Q(0) if e is None else e[i] for e in ends)
        expected[_sid(table.positions, i)] = float((b - a) / (2 * h))
    if table.debt:
        expected["loan"] = 1.0 if upper is not None and upper <= table.debt else 0.0
    if table.pool:
        expected["pool"] = 0.0
    return max(abs(weights[k] - w) for k, w in expected.items())


@pytest.mark.parametrize("start", range(0, 300, 50))
def test_generated_tables_replay_the_engine_and_the_exact_oracle(start: int) -> None:
    """50 tables per case, seeds 0-299 in all. `python -m tests.test_opm_breakpoints`
    runs the same check on 3,000; docs/opm-breakpoints.md reports that run."""
    total: Counter[str] = Counter()
    for seed in range(start, start + 50):
        stats, gap = check_generated(seed)
        assert not any(stats[k] for k in BAD_GENERATED), (seed, stats)
        assert gap <= 1e-9, (seed, gap)
        total += stats
    assert total["tables"] == 50 and total["probes"] > 0


def _generated_term(positions: Any, converts: Any, approvals: Any) -> CollectiveConversion:
    return CollectiveConversion(
        name="generated",
        converts=tuple(_sid(positions, i) for i in sorted(converts)),
        approvals=tuple(
            VoteRequirement(
                name=f"approval {k}",
                voters=tuple(_sid(positions, i) for i in v),
                threshold=t,
                comparison=c,
                source="generated",
            )
            for k, (v, t, c) in enumerate(approvals)
        ),
        source="generated",
    )


def check_governed(seed: int) -> Counter[str]:
    """One table and term from the governance vote search. A returned schedule must replay
    the exact governed payoff inside every tranche and carry the exact jump at every step; a
    refusal must name an exit around which the exact vote is itself undetermined."""
    positions, converts, approvals = random_vote_instance(random.Random(seed))
    term = _generated_term(positions, converts, approvals)
    stats: Counter[str] = Counter(tables=1)
    try:
        schedule = breakpoint_schedule(exact_to_securities(positions), collective_conversion=term)
    except BreakpointError as exc:
        found = re.search(r"an exit of ([0-9.e+-]+),", str(exc))
        x = Q(float(found.group(1))) if found else None
        undetermined = x is not None and all(
            exact_vote(positions, x * (1 + rel), converts, approvals)["kind"] == "refused"
            for rel in (Q(-1, 10**9), Q(0), Q(1, 10**9))
        )
        stats["refused_on_an_interval" if undetermined else "refused_unexplained"] += 1
        return stats
    stats["schedules"] += 1
    stats["steps"] += len(schedule.discontinuities)
    stats["discontinuous"] += not schedule.continuous
    stats["not_monotone"] += not schedule.monotone
    stats["located"] += sum(not b.exact for b in schedule.breakpoints)
    if schedule.continuous is not (not schedule.discontinuities):
        stats["flag_mismatch"] += 1
    for tranche in schedule.tranches:
        top = tranche.upper if tranche.upper is not None else 2 * tranche.lower + 1000
        for t in (0.25, 0.5, 0.75):
            x = tranche.lower + t * (top - tranche.lower)
            outcome = exact_vote(positions, Q(x), converts, approvals)
            if outcome["kind"] != "ok":
                stats["interior_undetermined"] += 1
                continue
            expected = {_sid(positions, i): float(v) for i, v in enumerate(outcome["payout"])}
            if _gap(schedule.payout(x), expected) > ATOL:
                stats["payout_mismatch"] += 1
    for step in schedule.discontinuities:
        x, eps = Q(step.value), Q(step.value) / 10**12
        lo = exact_vote(positions, x - eps, converts, approvals)
        hi = exact_vote(positions, x + eps, converts, approvals)
        for i in range(len(positions)):
            jump = float(hi["payout"][i] - lo["payout"][i])
            if abs(step.jumps[_sid(positions, i)] - jump) > 1e-6:
                stats["jump_mismatch"] += 1
        if any(j < -ATOL for j in step.jumps.values()) and schedule.monotone:
            stats["flag_mismatch"] += 1
    return stats


def test_generated_governed_tables_against_the_exact_vote() -> None:
    """Seeds 0-39; `python -m tests.test_opm_breakpoints` runs 60."""
    total: Counter[str] = Counter()
    for seed in range(40):
        stats = check_governed(seed)
        assert not any(stats[k] for k in BAD_GOVERNED), (seed, stats)
        total += stats
    assert total["schedules"] >= 30 and total["steps"] > 0, total


def test_an_isolated_undefined_point_is_recorded_not_refused() -> None:
    """Founders 100 common; h1 200 at $2, 1.5x senior ($600); h0 800 at $2, 1x junior
    ($1,600); all preferred converts on at least 3/5 of 1,000 votes, so h0 (800) decides.
    Converted, h0 gets 8/11 X. Without, h0 gets X - 600 up to 2,200 and 1,600 up to 2,400.
    Its gain 600 - 3X/11 falls to zero at X = 2,200 and 8X/11 - 1,600 rises from zero there:
    it touches zero without changing sign. The vote carries everywhere else, so the governed
    payoff is one line, and only the exit 2,200 itself, where h0 is pivotal, is undefined."""
    table = (
        ovf.common(100, holder_id="founders", security_id="common"),
        ovf.preferred(800, 2.0, seniority=3, holder_id="h0", security_id="p0"),
        ovf.preferred(
            200, 2.0, seniority=2, liquidation_multiple=1.5, holder_id="h1", security_id="p1"
        ),
    )
    term = CollectiveConversion(
        name="mandatory conversion",
        converts=("p0", "p1"),
        approvals=(
            VoteRequirement(
                name="Requisite Holders",
                voters=("p0", "p1"),
                threshold=Q(3, 5),
                comparison="at_least",
                source=gv.NVCA_REQUISITE_HOLDERS,
            ),
        ),
        source=gv.NVCA_MANDATORY_CONVERSION,
    )
    with pytest.raises(ovf.governance.GovernanceIndeterminateError):
        resolve_collective_conversion(table, 2200.0, term=term)
    schedule = breakpoint_schedule(table, collective_conversion=term)
    assert schedule.continuous and schedule.monotone
    (tranche,) = schedule.tranches
    assert tranche.weights == pytest.approx({"common": 1 / 11, "p0": 8 / 11, "p1": 2 / 11})
    assert any("isolated exit value(s) 2,200.00" in a for a in schedule.assumptions)
    assert schedule.payout(2200.0)["p0"] == pytest.approx(1600.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Finding what the candidates missed, and refusing what cannot be verified
# ---------------------------------------------------------------------------


def test_a_missed_kink_is_found_by_bisection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete the 5M preference candidate from BP1: probing must find it anyway."""
    original = bp._analytic_candidates

    def without_preference(*args: Any) -> Any:
        found = original(*args)
        del found.reasons[Q(5 * M)]
        return found

    monkeypatch.setattr(bp, "_analytic_candidates", without_preference)
    schedule = _schedule(_fixture("BP1"))
    located = [b for b in schedule.breakpoints if b.kind == "other"]
    assert len(located) == 1 and not located[0].exact
    assert located[0].value == pytest.approx(5 * M, abs=1e-3)
    assert "located numerically" in located[0].basis
    assert "no candidate family" in located[0].basis
    assert schedule.max_linearity_error <= ATOL
    assert any("located numerically" in a for a in schedule.assumptions)


def _fake_engine(payout: Any) -> Any:
    def fake(securities: Any, x: float, **kwargs: Any) -> Any:
        return SimpleNamespace(
            payouts=[
                SimpleNamespace(security_id=k, amount=v, converted=False)
                for k, v in payout(x).items()
            ],
            assumptions=["fake engine"],
        )

    return fake


def test_an_unpredicted_step_is_recorded_as_located_numerically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stepped(x: float) -> dict[str, float]:
        a = min(x, 5 * M) if x < 25 * M else 0.2 * x
        shift = 1_000_000.0 if x >= 7_300_000.3 else 0.0
        return {"common": x - a + shift, "series_a": a - shift}

    monkeypatch.setattr(bp, "solve_waterfall", _fake_engine(stepped))
    schedule = _schedule(_fixture("BP1"))
    assert schedule.continuous is False and schedule.monotone is False
    (step,) = schedule.discontinuities
    assert not step.exact
    assert step.value == pytest.approx(7_300_000.3, abs=1e-6)
    assert step.jumps["series_a"] == pytest.approx(-1_000_000, abs=1e-6)


def test_a_curved_map_cannot_be_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    def curved(x: float) -> dict[str, float]:
        a = 5 * M * (1 - math.exp(-x / (5 * M)))
        return {"common": x - a, "series_a": a}

    monkeypatch.setattr(bp, "solve_waterfall", _fake_engine(curved))
    with pytest.raises(BreakpointError, match=r"gave up after 400 interval splits.*deviates"):
        _schedule(_fixture("BP1"))


def test_a_replay_gap_above_atol_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bump between the construction probes, hit only by a fresh verification probe
    (5M + 0.382 x 20M = 12,639,320): the final replay check refuses it."""

    def bumped(x: float) -> dict[str, float]:
        a = min(x, 5 * M) if x < 25 * M else 0.2 * x
        bump = 1e-3 if 12_600_000 < x < 12_700_000 else 0.0
        return {"common": x - a + bump, "series_a": a - bump}

    monkeypatch.setattr(bp, "solve_waterfall", _fake_engine(bumped))
    with pytest.raises(BreakpointError, match=r"does not replay the engine.*above atol 1e-06"):
        _schedule(_fixture("BP1"))


@pytest.mark.parametrize(
    ("securities", "kwargs", "match"),
    [
        ((founders(), ovf.safe_post(1e6, 1e7, security_id="safe")), {}, "PostMoneySAFE"),
        ((founders(), ovf.option_pool(10, 5, security_id="pool")), {}, "allocated options"),
        ((founders(), series_a()), {"atol": 0.0}, "atol must be finite and positive"),
        ((founders(), series_a()), {"atol": math.nan}, "atol must be finite and positive"),
        ((founders(), series_a()), {"upper_probe": -1.0}, "upper_probe must be finite"),
        ((founders(), series_a()), {"upper_probe": 25 * M}, "must lie above every analytic"),
        ((founders(), series_a()), {"collective_conversion": "vote"}, "CollectiveConversion"),
        ((founders(), founders()), {}, "Duplicate security_id"),
        ((gv.LOAN,), {"as_of": AS_OF}, "engine refused"),
    ],
)
def test_refusals_say_what_failed(securities: Any, kwargs: Any, match: str) -> None:
    with pytest.raises(BreakpointError, match=match):
        breakpoint_schedule(securities, **kwargs)


def test_too_many_preferred_positions_to_enumerate() -> None:
    table = [founders()] + [
        ovf.preferred(100, 1.0, holder_id=f"h{i}", security_id=f"p{i}") for i in range(13)
    ]
    with pytest.raises(BreakpointError, match="limited to 12"):
        breakpoint_schedule(table)


def test_a_table_with_no_candidate_is_one_tranche() -> None:
    schedule = breakpoint_schedule([founders(), ovf.common(2_000_000, security_id="c2")])
    assert [b.kind for b in schedule.breakpoints] == ["origin"]
    (tranche,) = schedule.tranches
    assert tranche.weights == {"common": 0.8, "c2": 0.2}
    assert any("no analytic candidate" in a for a in schedule.assumptions)


def test_upper_probe_supplied_by_the_caller_is_used_and_stated() -> None:
    schedule = breakpoint_schedule([founders(), series_a()], upper_probe=100 * M)
    assert any("supplied by the caller" in a for a in schedule.assumptions)
    assert [b.value for b in schedule.breakpoints] == [0.0, 5 * M, 25 * M]


def test_dividends_enter_through_the_exit_terms() -> None:
    """GV9's Series B carries a cumulative dividend: its preference level is 10.44M."""
    table = (founders(), gv.series_a(), gv.series_b(dividend=gv.B_DIVIDEND))
    schedule = breakpoint_schedule(table, as_of=gv.AS_OF)
    assert schedule.breakpoints[1].value == 10_440_000
    assert schedule.breakpoints[1].kind == "preference"
    rng = random.Random(9)
    for x in _probes(schedule, rng):
        assert _gap(schedule.payout(x), _engine(table, x, as_of=gv.AS_OF)) <= ATOL


def test_the_schedule_is_deterministic_and_round_trips() -> None:
    fixture = _fixture("BP7")
    first, second = _schedule(fixture), _schedule(fixture)
    assert first.model_dump() == second.model_dump()
    assert BreakpointSchedule.model_validate(first.model_dump()) == first


def test_assumptions_state_the_method_and_the_tolerances() -> None:
    schedule = _schedule(_fixture("BP3"))
    text = " ".join(schedule.assumptions)
    for phrase in (
        "fractions.Fraction",
        "twice the largest analytic candidate",
        "atol = 1e-06",
        "not clipped to [0, 1]",
        "engine:",
    ):
        assert phrase in text, phrase


if __name__ == "__main__":  # python -m tests.test_opm_breakpoints [ungoverned] [governed]
    import sys
    import time

    plain = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    governed = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    started = time.perf_counter()
    totals: Counter[str] = Counter()
    widest = 0.0
    for seed in range(plain):
        found, gap = check_generated(seed)
        totals += found
        widest = max(widest, gap)
    print(
        f"ungoverned seeds 0-{plain - 1}: {dict(sorted(totals.items()))}; largest weight-slope "
        f"gap {widest:.3g}; {time.perf_counter() - started:.1f}s"
    )
    started = time.perf_counter()
    votes: Counter[str] = Counter()
    for seed in range(governed):
        votes += check_governed(seed)
    print(
        f"governed seeds 0-{governed - 1}: {dict(sorted(votes.items()))}; "
        f"{time.perf_counter() - started:.1f}s"
    )
