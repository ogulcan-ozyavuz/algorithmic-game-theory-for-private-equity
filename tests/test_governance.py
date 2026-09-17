"""Collective conversion (`ovf.governance`) and forced conversions in `ovf.waterfall`.

Every expected number in the named fixtures is derived by hand in `docs/governance.md`.
The exact-rational oracle below is written independently of `ovf.waterfall`: it does its
own tiering and water-filling over `fractions.Fraction`. It backs Propositions G1 and G2
and the two uniqueness searches. The pytest runs use small deterministic subsets; the full
searches recorded in `docs/governance.md` are replayed with

    python -m tests.test_governance            # both searches, recorded seeds
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import itertools
import json
import random
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import ovf
from ovf.governance import (
    CollectiveConversion,
    GovernanceIndeterminateError,
    VoteRequirement,
    resolve_collective_conversion,
)
from ovf.waterfall import enumerate_equilibria, evaluate_fixed_waterfall, solve_waterfall
from tests.fixtures import FIXTURES
from tests.governance_fixtures import (
    GOVERNANCE_FIXTURES,
    MAJORITY,
    NVCA_MANDATORY_CONVERSION,
    PREFERRED_IDS,
    SPLIT_TABLE,
    TABLE,
    GovernanceFixture,
    M,
    mandatory_conversion,
)

PRE_GOVERNANCE_ASSUMPTIONS = [
    "Each preferred position makes an independent conversion decision.",
    "Reserved unallocated option capacity has no exit payment entitlement.",
    "Single base currency; float accounting within reported tolerance.",
    "No debt, unexercised option settlement, SAFE liquidity events or class voting.",
]


def _fixture(case_id: str) -> GovernanceFixture:
    return next(f for f in GOVERNANCE_FIXTURES if f.case_id == case_id)


def _resolve(fixture: GovernanceFixture) -> Any:
    return resolve_collective_conversion(
        fixture.securities, fixture.exit_valuation, term=fixture.term, as_of=fixture.as_of
    )


# ---------------------------------------------------------------------------
# Named fixtures (docs/governance.md, "Fixture derivations")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", GOVERNANCE_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_outcome(fixture: GovernanceFixture) -> None:
    outcome = _resolve(fixture)
    assert outcome.approved is fixture.expected_approved
    assert outcome.changes_payout is fixture.expected_changes_payout
    paid = {p.security_id: p.amount for p in outcome.result.payouts}
    assert paid == pytest.approx(fixture.expected, abs=1e-6)
    assert sum(paid.values()) == pytest.approx(fixture.exit_valuation, abs=1e-6)
    decisions = {h.holder_id: h.decision for h in outcome.holders}
    assert decisions == fixture.expected_decisions
    changes = {h.holder_id: h.change for h in outcome.holders}
    assert changes == pytest.approx(fixture.expected_changes, abs=1e-6)
    assert outcome.result is (
        outcome.with_conversion if fixture.expected_approved else outcome.without_conversion
    )


@pytest.mark.parametrize("fixture", GOVERNANCE_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_stages_are_verified_and_payoff_unique(fixture: GovernanceFixture) -> None:
    outcome = _resolve(fixture)
    for survey in (outcome.survey_without_conversion, outcome.survey_with_conversion):
        assert survey.feasible_equilibria and survey.payoff_unique
    assert outcome.survey_with_conversion.forced_conversions == sorted(fixture.term.converts)
    converted = {p.security_id: p.converted for p in outcome.with_conversion.payouts}
    assert all(converted[i] for i in fixture.term.converts)
    for result in (outcome.with_conversion, outcome.without_conversion):
        assert result.max_unilateral_gain <= result.tolerance


def test_gv1_is_the_omneon_mechanism_on_the_readme_table() -> None:
    """B's preference is stripped: 27/23 M leaves B, 5.4/23 M to A and 21.6/23 M to common."""
    outcome = _resolve(_fixture("GV1"))
    before = {p.security_id: p.amount for p in outcome.without_conversion.payouts}
    after = {p.security_id: p.amount for p in outcome.result.payouts}
    assert before == pytest.approx({"common": 40.8 * M, "series_a": 10.2 * M, "series_b": 9 * M})
    moved = {k: after[k] - before[k] for k in after}
    assert moved == pytest.approx(
        {"common": 21.6 / 23 * M, "series_a": 5.4 / 23 * M, "series_b": -27 / 23 * M}
    )
    # The converted outcome is not an equilibrium of the individual game: B would un-convert.
    survey = enumerate_equilibria(TABLE, 60 * M)
    assert {"series_a": True, "series_b": True} not in survey.feasible_equilibria
    tally = outcome.tallies[0]
    assert (tally.consenting_weight, tally.total_weight) == (2_000_000, 3_500_000)


def test_gv6_knife_edge_is_refused_with_the_tolerance_in_the_error() -> None:
    """At $57.5M Series A is exactly indifferent ($10M both ways) and holds the majority."""
    with pytest.raises(GovernanceIndeterminateError, match=r"within the reported tolerance"):
        resolve_collective_conversion(TABLE, 57.5 * M, term=MAJORITY)
    with pytest.raises(GovernanceIndeterminateError, match=r"5\.75\de-05"):
        resolve_collective_conversion(TABLE, 57.5 * M, term=MAJORITY)


def test_governance_makes_series_b_cash_fall_as_the_exit_rises() -> None:
    """GV6b to GV6a: a $200,000 higher exit costs Series B 34.2/23 M ($1,486,957)."""
    low = _resolve(_fixture("GV6b")).result
    high = _resolve(_fixture("GV6a")).result
    b_low = next(p.amount for p in low.payouts if p.security_id == "series_b")
    b_high = next(p.amount for p in high.payouts if p.security_id == "series_b")
    assert b_low == pytest.approx(9 * M)
    assert b_high == pytest.approx(172.8 / 23 * M)
    assert b_low - b_high == pytest.approx(34.2 / 23 * M)
    # Without the term, B's cash does not fall across the same step.
    plain = [
        next(p.amount for p in solve_waterfall(TABLE, x).payouts if p.security_id == "series_b")
        for x in (57.4 * M, 57.5 * M, 57.6 * M)
    ]
    assert plain == pytest.approx([9 * M, 9 * M, 9 * M])


def test_gv7_position_level_voting_would_have_passed() -> None:
    """Both Series A positions gain, so counting positions would give 4/7 > 1/2."""
    outcome = _resolve(_fixture("GV7"))
    assert outcome.tallies[0].weights == {"fund_a": 1_500_000, "fund_b": 2_000_000}
    before = {p.security_id: p.amount for p in outcome.without_conversion.payouts}
    after = {p.security_id: p.amount for p in outcome.with_conversion.payouts}
    gains = {k: after[k] - before[k] for k in ("series_a1", "series_a2", "series_b")}
    assert gains == pytest.approx(
        {"series_a1": 4.05 / 23 * M, "series_a2": 1.35 / 23 * M, "series_b": -27 / 23 * M}
    )
    by_position = sum(
        s.converted_shares
        for s in SPLIT_TABLE
        if isinstance(s, ovf.PreferredStock) and gains[s.security_id] > 0
    )
    assert Fraction(by_position) / 3_500_000 == Fraction(4, 7)


@pytest.mark.parametrize(("comparison", "approved"), [("at_least", True), ("more_than", False)])
def test_a_vote_exactly_on_the_threshold(comparison: str, approved: bool) -> None:
    """Series A holds exactly 4/7 of the votes. 'At least 4/7' passes; 'more than' fails."""
    term = mandatory_conversion("4/7", comparison)  # type: ignore[arg-type]
    outcome = resolve_collective_conversion(TABLE, 60 * M, term=term)
    assert outcome.approved is approved
    expected_b = 180 / 23 * M if approved else 9 * M
    paid = {p.security_id: p.amount for p in outcome.result.payouts}
    assert paid["series_b"] == pytest.approx(expected_b)


def test_unanimity_threshold_needs_every_holder() -> None:
    outcome = resolve_collective_conversion(
        TABLE, 60 * M, term=mandatory_conversion("1", "at_least")
    )
    assert not outcome.approved


def test_a_term_converting_only_series_b() -> None:
    """All preferred vote on converting B alone. At $60M A then converts anyway, so the
    outcome is GV1: with B converted, A's 2/11.5 x $60M beats its capped $10M."""
    term = MAJORITY.model_copy(update={"converts": ("series_b",)})
    outcome = resolve_collective_conversion(TABLE, 60 * M, term=term)
    assert outcome.approved
    paid = {p.security_id: p.amount for p in outcome.result.payouts}
    assert paid == pytest.approx(_fixture("GV1").expected)
    assert outcome.survey_with_conversion.positions == ["series_a"]


def test_result_is_fingerprinted_and_explains_itself() -> None:
    first = _resolve(_fixture("GV1"))
    again = _resolve(_fixture("GV1"))
    other = _resolve(_fixture("GV2"))
    assert first.engine_version == "governance-v1"
    assert len(first.input_hash) == 64 and first.input_hash == again.input_hash
    assert first.input_hash != other.input_hash
    text = " ".join(first.assumptions)
    for phrase in (
        "Sincere voting",
        "unique",
        "Drag-along",
        "as-converted",
        NVCA_MANDATORY_CONVERSION,
    ):
        assert phrase in text
    assert "given" in first.assumptions[-1]
    assert first.model_dump_json()  # the whole result serialises, thresholds as text
    assert first.term.approvals[0].model_dump()["threshold"] == "1/2"


# ---------------------------------------------------------------------------
# Refusals and required terms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0.5, 0.6, True, None, "0", "3/2", "-1/2", "x", "1/0"])
def test_threshold_must_be_exact_and_in_range(bad: object) -> None:
    with pytest.raises(ValidationError, match="threshold"):
        VoteRequirement(
            name="r", voters=("series_a",), threshold=bad, comparison="at_least", source="s"
        )


def test_threshold_accepts_exact_forms() -> None:
    for value in ("3/5", "0.6", Fraction(3, 5)):
        req = VoteRequirement(
            name="r", voters=("a",), threshold=value, comparison="at_least", source="s"
        )
        assert req.threshold == Fraction(3, 5)
    assert (
        VoteRequirement(
            name="r", voters=("a",), threshold=1, comparison="at_least", source="s"
        ).threshold
        == 1
    )


def test_every_charter_field_is_required() -> None:
    with pytest.raises(ValidationError) as excinfo:
        VoteRequirement()  # type: ignore[call-arg]
    assert {e["loc"][0] for e in excinfo.value.errors()} == {
        "name",
        "voters",
        "threshold",
        "comparison",
        "source",
    }
    with pytest.raises(ValidationError) as excinfo:
        CollectiveConversion()  # type: ignore[call-arg]
    assert {e["loc"][0] for e in excinfo.value.errors()} == {
        "name",
        "converts",
        "approvals",
        "source",
    }
    for field_name in ("threshold", "comparison", "voters"):
        assert VoteRequirement.model_fields[field_name].is_required()


def test_resolve_has_no_default_term() -> None:
    parameter = inspect.signature(resolve_collective_conversion).parameters["term"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voters": ()},
        {"voters": ("a", "a")},
        {"comparison": "majority"},
        {"name": ""},
        {"source": ""},
    ],
)
def test_bad_vote_requirement_is_rejected(kwargs: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "name": "r",
        "voters": ("a",),
        "threshold": "1/2",
        "comparison": "at_least",
        "source": "s",
    }
    with pytest.raises(ValidationError):
        VoteRequirement(**{**fields, **kwargs})


def test_bad_collective_conversion_is_rejected() -> None:
    approval = MAJORITY.approvals[0]
    with pytest.raises(ValidationError, match="twice"):
        CollectiveConversion(name="t", converts=("a", "a"), approvals=(approval,), source="s")
    with pytest.raises(ValidationError, match="repeats"):
        CollectiveConversion(name="t", converts=("a",), approvals=(approval, approval), source="s")
    with pytest.raises(ValidationError):
        CollectiveConversion(name="t", converts=(), approvals=(approval,), source="s")
    with pytest.raises(ValidationError):
        CollectiveConversion(name="t", converts=("a",), approvals=(), source="s")


@pytest.mark.parametrize(
    ("converts", "voters", "match"),
    [
        (("series_a", "ghost"), PREFERRED_IDS, "converts names ghost"),
        (("series_a", "common"), PREFERRED_IDS, "converts names common"),
        (PREFERRED_IDS, ("series_a", "common"), "approval 'Requisite Holders' names common"),
    ],
)
def test_term_must_name_preferred_positions_in_the_table(
    converts: tuple[str, ...], voters: tuple[str, ...], match: str
) -> None:
    term = CollectiveConversion(
        name="t",
        converts=converts,
        approvals=(
            VoteRequirement(
                name="Requisite Holders",
                voters=voters,
                threshold="1/2",
                comparison="more_than",
                source="s",
            ),
        ),
        source="s",
    )
    with pytest.raises(ValueError, match=match):
        resolve_collective_conversion(TABLE, 60 * M, term=term)


def test_untyped_term_and_zero_weight_vote_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be a CollectiveConversion"):
        resolve_collective_conversion(TABLE, 60 * M, term=MAJORITY.model_dump())  # type: ignore[arg-type]
    empty = ovf.preferred(0, 1.0, holder_id="ghost", security_id="empty")
    term = mandatory_conversion(converts=("series_a",)).model_copy(
        update={
            "approvals": (
                VoteRequirement(
                    name="empty",
                    voters=("empty",),
                    threshold="1/2",
                    comparison="at_least",
                    source="s",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="hold no shares"):
        resolve_collective_conversion((*TABLE, empty), 60 * M, term=term)


def test_non_unique_stage_payoff_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """No exact counterexample to payoff uniqueness is known, so the refusal is exercised
    by reporting two payoff vectors from the enumeration."""
    import ovf.governance as governance

    real = governance.enumerate_equilibria

    def two_vectors(*args: Any, **kwargs: Any) -> Any:
        survey = real(*args, **kwargs)
        return survey.model_copy(update={"payoff_unique": False, "distinct_payoff_vectors": 2})

    monkeypatch.setattr(governance, "enumerate_equilibria", two_vectors)
    with pytest.raises(GovernanceIndeterminateError, match="2 distinct equilibrium payoff"):
        resolve_collective_conversion(TABLE, 60 * M, term=MAJORITY)


def test_infeasible_table_is_refused() -> None:
    """A zero-share preferred beside an unallocated reserve strands cash in every profile."""
    stranded = (
        ovf.option_pool(1_000, security_id="pool"),
        ovf.preferred(0, 1.0, holder_id="x", security_id="x"),
    )
    term = mandatory_conversion(converts=("x",))
    with pytest.raises(ValueError, match="allocates the whole exit"):
        resolve_collective_conversion(stranded, 5.0, term=term)


def test_max_positions_bounds_both_enumerations() -> None:
    with pytest.raises(ValueError, match="max_positions is 1"):
        resolve_collective_conversion(TABLE, 60 * M, term=MAJORITY, max_positions=1)


def test_inputs_are_immutable() -> None:
    with pytest.raises(ValidationError):
        MAJORITY.name = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MAJORITY.approvals[0].threshold = Fraction(1)  # type: ignore[misc]


def test_no_clock_is_read() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ovf"
    for path in (root / "governance.py", root / "waterfall.py"):
        source = path.read_text(encoding="utf-8")
        for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
            assert call not in source, f"{path.name} reads a clock via {call}"


# ---------------------------------------------------------------------------
# forced_conversions in ovf.waterfall, and the no-governance regression contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_no_forced_conversion_is_byte_identical(fixture: Any) -> None:
    """Empty forced_conversions: the pre-governance fingerprint, assumptions and dumps."""
    report = solve_waterfall(fixture.securities, fixture.exit_valuation)
    explicit = solve_waterfall(fixture.securities, fixture.exit_valuation, forced_conversions=())
    assert report.model_dump_json() == explicit.model_dump_json()
    payload = {
        "securities": [{"kind": type(s).__name__, **s.model_dump()} for s in fixture.securities],
        "exit_valuation": fixture.exit_valuation,
        "transaction_costs": 0.0,
        "max_iterations": 20,
        "atol": 1e-8,
        "rtol": 1e-12,
    }
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
    assert report.input_hash == expected.hexdigest()
    assert report.assumptions == PRE_GOVERNANCE_ASSUMPTIONS
    survey = enumerate_equilibria(fixture.securities, fixture.exit_valuation)
    assert "forced_conversions" not in survey.model_dump()
    assert "forced_conversions" not in survey.model_dump_json()
    assert (
        survey.model_dump_json()
        == enumerate_equilibria(
            fixture.securities, fixture.exit_valuation, forced_conversions=[]
        ).model_dump_json()
    )


def test_forced_conversion_in_the_solver() -> None:
    result = solve_waterfall(TABLE, 60 * M, forced_conversions=["series_b"])
    paid = {p.security_id: p.amount for p in result.payouts}
    assert paid == pytest.approx(_fixture("GV1").expected)
    assert all(p.converted for p in result.payouts if p.security_id != "common")
    assert result.assumptions[0].startswith("Each preferred position not converted")
    assert "series_b" in result.assumptions[1] and "docs/governance.md" in result.assumptions[1]
    assert result.input_hash != solve_waterfall(TABLE, 60 * M).input_hash
    survey = enumerate_equilibria(TABLE, 60 * M, forced_conversions=("series_b",))
    assert survey.positions == ["series_a"] and survey.states_evaluated == 2
    assert survey.forced_conversions == ["series_b"]
    assert survey.feasible_equilibria == [{"series_a": True}]


def test_every_position_forced_leaves_no_players() -> None:
    result = solve_waterfall(TABLE, 20 * M, forced_conversions=PREFERRED_IDS)
    paid = {p.security_id: p.amount for p in result.payouts}
    assert paid == pytest.approx(
        {"common": 320 / 23 * M, "series_a": 80 / 23 * M, "series_b": 60 / 23 * M}
    )
    assert result.iterations == 1 and result.max_unilateral_gain == 0.0
    survey = enumerate_equilibria(TABLE, 20 * M, forced_conversions=PREFERRED_IDS)
    assert survey.states_evaluated == 1 and survey.positions == []


@pytest.mark.parametrize(
    ("forced", "match"),
    [
        ("series_a", "not a single string"),
        (["series_a", "series_a"], "twice"),
        (["ghost"], "not a preferred position"),
        (["common"], "not a preferred position"),
        ([1], "must be security_id strings"),
    ],
)
def test_forced_conversions_are_validated(forced: Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        solve_waterfall(TABLE, 60 * M, forced_conversions=forced)
    with pytest.raises(ValueError, match=match):
        enumerate_equilibria(TABLE, 60 * M, forced_conversions=forced)


def test_forced_positions_do_not_count_against_max_positions() -> None:
    securities = [
        ovf.preferred(1, 1, holder_id=f"p{i}", security_id=f"p{i:02d}") for i in range(13)
    ]
    with pytest.raises(ValueError, match="max_positions"):
        enumerate_equilibria(securities, 100.0)
    survey = enumerate_equilibria(securities, 100.0, forced_conversions=["p00"])
    assert survey.states_evaluated == 2**12


# ---------------------------------------------------------------------------
# Exact-rational oracle, written without reference to ovf.waterfall
# ---------------------------------------------------------------------------

Q = Fraction


@dataclass(frozen=True)
class Pos:
    """One position. Common: always in the residual, no preference. Preferred: the rest."""

    holder: str
    shares: Fraction
    common: bool = False
    price: Fraction = Q(0)
    seniority: int = 1
    multiple: Fraction = Q(1)
    participating: bool = False
    cap: Fraction | None = None
    ratio: Fraction = Q(1)

    @property
    def claim(self) -> Fraction:
        return self.shares * self.price * self.multiple

    @property
    def units(self) -> Fraction:
        return self.shares if self.common else self.shares * self.ratio


Positions = tuple[Pos, ...]
Profile = tuple[bool, ...]


def _water_fill(
    cash: Fraction, units: dict[int, Fraction], heads: dict[int, Fraction]
) -> tuple[dict[int, Fraction], Fraction]:
    """Split ``cash`` pro rata by units, capping each capped entry at its headroom.

    Every entry whose headroom is below its share at the current cash-per-unit level is
    capped at once; removing it can only raise the level for the rest.
    """
    out: dict[int, Fraction] = {}
    active = dict(units)
    while active:
        level = cash / sum(active.values(), Q(0))
        capped = [j for j in active if j in heads and heads[j] < level * active[j]]
        if not capped:
            out.update({j: level * u for j, u in active.items()})
            return out, Q(0)
        for j in capped:
            out[j] = heads[j]
            cash -= heads[j]
            del active[j]
    return out, cash


@functools.lru_cache(maxsize=50_000)
def exact_allocation(
    positions: Positions, exit_value: Fraction, converted: Profile
) -> tuple[tuple[Fraction, ...], Fraction]:
    """Cash to every position for a fixed conversion profile, and cash left unallocated."""
    paid = [Q(0)] * len(positions)
    cash = exit_value
    holding = [
        i for i, p in enumerate(positions) if not p.common and not converted[i] and p.shares > 0
    ]
    for rank in sorted({positions[i].seniority for i in holding}):
        tier = [i for i in holding if positions[i].seniority == rank]
        total = sum((positions[i].claim for i in tier), Q(0))
        budget = min(cash, total)
        for i in tier:
            paid[i] = budget * positions[i].claim / total if total else Q(0)
        cash -= budget
    units: dict[int, Fraction] = {}
    heads: dict[int, Fraction] = {}
    for i, p in enumerate(positions):
        if p.shares <= 0:
            continue
        if p.common or converted[i] or p.participating:
            units[i] = p.units
            if not p.common and not converted[i] and p.cap is not None:
                heads[i] = max(Q(0), p.cap * p.shares * p.price - paid[i])
    share, stranded = _water_fill(cash, units, heads)
    return tuple(paid[i] + share.get(i, Q(0)) for i in range(len(positions))), stranded


def _profiles(positions: Positions, forced: frozenset[int]) -> tuple[list[int], list[Profile]]:
    players = [i for i, p in enumerate(positions) if not p.common and i not in forced]
    out = []
    for bits in itertools.product((False, True), repeat=len(players)):
        state = [i in forced for i in range(len(positions))]
        for i, b in zip(players, bits, strict=True):
            state[i] = b
        out.append(tuple(state))
    return players, out


def _flip(profile: Profile, i: int) -> Profile:
    return tuple(not b if j == i else b for j, b in enumerate(profile))


def exact_equilibria(
    positions: Positions, exit_value: Fraction, forced: frozenset[int] = frozenset()
) -> tuple[list[Profile], set[tuple[Fraction, ...]]]:
    """Feasible pure equilibria of the per-position game and their payoff vectors."""
    players, profiles = _profiles(positions, forced)
    feasible: list[Profile] = []
    vectors: set[tuple[Fraction, ...]] = set()
    for profile in profiles:
        pay, stranded = exact_allocation(positions, exit_value, profile)
        if stranded:
            continue
        if all(
            pay[i] >= exact_allocation(positions, exit_value, _flip(profile, i))[0][i]
            for i in players
        ):
            feasible.append(profile)
            vectors.add(pay)
    return feasible, vectors


Approval = tuple[tuple[int, ...], Fraction, str]


def exact_vote(
    positions: Positions,
    exit_value: Fraction,
    converts: frozenset[int],
    approvals: tuple[Approval, ...],
) -> dict[str, Any]:
    """The governed outcome under sincere holder voting, in exact arithmetic."""
    f0, v0 = exact_equilibria(positions, exit_value)
    f1, v1 = exact_equilibria(positions, exit_value, converts)
    if not f0 or not f1:
        return {"kind": "infeasible"}
    if len(v0) > 1 or len(v1) > 1:
        return {"kind": "nonunique", "without": len(v0), "with": len(v1)}
    base, forced = next(iter(v0)), next(iter(v1))
    delta: dict[str, Fraction] = {}
    voting = {positions[i].holder for voters, _, _ in approvals for i in voters}
    for h in voting:
        delta[h] = sum(
            (forced[i] - base[i] for i, p in enumerate(positions) if p.holder == h), Q(0)
        )

    def approved(count_indifferent: bool) -> bool:
        for voters, threshold, comparison in approvals:
            weights: dict[str, Fraction] = {}
            for i in voters:
                h = positions[i].holder
                weights[h] = weights.get(h, Q(0)) + positions[i].units
            total = sum(weights.values(), Q(0))
            yes = sum(
                (
                    w
                    for h, w in weights.items()
                    if delta[h] > 0 or (count_indifferent and delta[h] == 0)
                ),
                Q(0),
            )
            ok = yes >= threshold * total if comparison == "at_least" else yes > threshold * total
            if not ok:
                return False
        return True

    a0, a1 = approved(False), approved(True)
    if base != forced and a0 != a1:
        return {"kind": "refused", "base": base, "forced": forced, "delta": delta}
    return {
        "kind": "ok",
        "approved": a0,
        "payout": forced if a0 else base,
        "base": base,
        "forced": forced,
        "delta": delta,
    }


def as_common(positions: Positions, converts: frozenset[int]) -> Positions:
    """Proposition G1's twin: each converted position becomes common with its units."""
    return tuple(
        Pos(holder=p.holder, shares=p.units, common=True) if i in converts else p
        for i, p in enumerate(positions)
    )


def to_securities(positions: Positions) -> list[ovf.Security]:
    out: list[ovf.Security] = []
    for i, p in enumerate(positions):
        if p.common:
            out.append(ovf.common(float(p.shares), holder_id=p.holder, security_id=f"c{i}"))
        else:
            out.append(
                ovf.preferred(
                    float(p.shares),
                    float(p.price),
                    seniority=p.seniority,
                    liquidation_multiple=float(p.multiple),
                    participating=p.participating,
                    participation_cap=None if p.cap is None else float(p.cap),
                    conversion_ratio=float(p.ratio),
                    holder_id=p.holder,
                    security_id=f"p{i}",
                )
            )
    return out


def _sid(positions: Positions, i: int) -> str:
    return f"c{i}" if positions[i].common else f"p{i}"


def test_oracle_reproduces_hand_derived_fixtures() -> None:
    """The oracle is checked against hand derivations before it checks anything else."""
    table = (
        Pos("founders", Q(8_000_000), common=True),
        Pos("a", Q(2_000_000), price=Q(5, 2), seniority=2, participating=True, cap=Q(2)),
        Pos("b", Q(1_500_000), price=Q(6), seniority=1),
    )
    x = Q(60_000_000)
    _, vectors = exact_equilibria(table, x)
    assert vectors == {(Q(40_800_000), Q(10_200_000), Q(9_000_000))}
    outcome = exact_vote(table, x, frozenset({1, 2}), (((1, 2), Q(1, 2), "more_than"),))
    assert outcome["kind"] == "ok" and outcome["approved"]
    assert outcome["payout"] == (Q(960_000_000, 23), Q(240_000_000, 23), Q(180_000_000, 23))
    assert (
        exact_vote(table, Q(57_500_000), frozenset({1, 2}), (((1, 2), Q(1, 2), "more_than"),))[
            "kind"
        ]
        == "refused"
    )


# ---------------------------------------------------------------------------
# Random tables and adversarial exits
# ---------------------------------------------------------------------------

MULTIPLES = (Q(1), Q(1), Q(3, 2), Q(2))
RATIOS = (Q(1), Q(1), Q(1), Q(3, 2), Q(2), Q(1, 2))
THRESHOLDS: tuple[tuple[Fraction, str], ...] = (
    (Q(1, 2), "more_than"),
    (Q(1, 2), "at_least"),
    (Q(3, 5), "at_least"),
    (Q(2, 3), "at_least"),
)


def _preferred(rng: random.Random, holder: str, shares: Fraction | None = None) -> Pos:
    multiple = rng.choice(MULTIPLES)
    participating = rng.random() < 0.5
    cap = None
    if participating and rng.random() < 0.6:
        cap = multiple + rng.choice((Q(0), Q(1, 2), Q(1), Q(2)))
    return Pos(
        holder=holder,
        shares=shares if shares is not None else Q(rng.randint(1, 10) * 100),
        price=Q(rng.randint(1, 6)),
        seniority=rng.randint(1, 3),
        multiple=multiple,
        participating=participating,
        cap=cap,
        ratio=rng.choice(RATIOS),
    )


def random_vote_instance(
    rng: random.Random,
) -> tuple[Positions, frozenset[int], tuple[Approval, ...]]:
    """A table of 2-4 preferred positions, common, some shared holders, and a term."""
    n = rng.randint(2, 4)
    common = rng.choice((0, 1, 2, 5, 8, 10, 20)) * 100
    prefs = [_preferred(rng, f"h{i}") for i in range(n)]
    if rng.random() < 0.15:
        prefs[1] = replace(prefs[0], holder="h1")  # identical terms
    if rng.random() < 0.3:
        i, j = rng.sample(range(n), 2)
        prefs[j] = replace(prefs[j], holder=prefs[i].holder)  # one holder, two positions
    common_holder = "founders"
    if rng.random() < 0.2:
        common_holder = rng.choice(prefs).holder  # an investor also holds common
    positions: list[Pos] = []
    if common:
        positions.append(Pos(common_holder, Q(common), common=True))
    positions.extend(prefs)
    table = tuple(positions)
    preferred = [i for i, p in enumerate(table) if not p.common]
    if rng.random() < 0.6:
        converts = frozenset(preferred)
    else:
        converts = frozenset(rng.sample(preferred, rng.randint(1, len(preferred))))
    threshold, comparison = rng.choice(THRESHOLDS)
    approvals: list[Approval] = [(tuple(preferred), threshold, comparison)]
    if rng.random() < 0.3:
        approvals.append(((rng.choice(sorted(converts)),), Q(1, 2), "more_than"))
    return table, converts, tuple(approvals)


def _upper(positions: Positions) -> Fraction:
    total_units = sum((p.units for p in positions), Q(0))
    total_claim = sum((p.claim for p in positions if not p.common), Q(0))
    reach = [
        (p.shares * p.price * (p.cap or p.multiple)) * total_units / p.units
        for p in positions
        if not p.common and p.units
    ]
    return (max(reach, default=Q(1)) + total_claim) * Q(6, 5) + 1


def _roots(
    f: Callable[[Fraction], Fraction], lo: Fraction, hi: Fraction, samples: int
) -> set[Fraction]:
    """Exact roots of a piecewise-linear ``f`` found by sign changes on a grid, then
    alternating secant and bisection steps. A secant step inside one linear piece lands
    on the root exactly."""
    xs = [lo + (hi - lo) * k / samples for k in range(samples + 1)]
    ys = [f(x) for x in xs]
    found = {x for x, y in zip(xs, ys, strict=True) if y == 0}
    for a, fa, b, fb in zip(xs, ys, xs[1:], ys[1:], strict=False):
        if (fa < 0 < fb) or (fb < 0 < fa):
            for step in range(60):
                m = a - fa * (b - a) / (fb - fa) if step % 2 == 0 else (a + b) / 2
                fm = f(m)
                if fm == 0:
                    found.add(m)
                    break
                if (fa < 0) == (fm < 0):
                    a, fa = m, fm
                else:
                    b, fb = m, fm
    return found


def candidate_exits(
    positions: Positions,
    extra: list[Callable[[Fraction], Fraction]],
    rng: random.Random,
    samples: int = 24,
    limit: int = 40,
) -> list[Fraction]:
    """Breakpoints in exact arithmetic, then 1/1000 either side.

    Cumulative preference levels of every profile; every exit at which a position is
    indifferent to its own conversion in some profile; the roots of ``extra``.
    """
    hi = _upper(positions)
    found: set[Fraction] = set()
    _, profiles = _profiles(positions, frozenset())
    for profile in profiles:
        claims = sorted(
            (p.seniority, p.claim)
            for i, p in enumerate(positions)
            if not p.common and not profile[i]
        )
        running = Q(0)
        for rank in sorted({r for r, _ in claims}):
            running += sum((c for r, c in claims if r == rank), Q(0))
            found.add(running)
    players = [i for i, p in enumerate(positions) if not p.common]
    for profile in profiles:
        for i in players:
            flipped = _flip(profile, i)

            def gain(
                x: Fraction, i: int = i, profile: Profile = profile, flipped: Profile = flipped
            ) -> Fraction:
                return (
                    exact_allocation(positions, x, flipped)[0][i]
                    - exact_allocation(positions, x, profile)[0][i]
                )

            found |= _roots(gain, Q(0), hi, samples)
    for f in extra:
        found |= _roots(f, Q(0), hi, samples)
    exact = sorted(x for x in found if 0 <= x <= hi)
    if len(exact) > limit:
        exact = sorted(rng.sample(exact, limit))
    near = {x + d for x in exact for d in (Q(-1, 1000), Q(1, 1000))}
    near |= {Q(rng.randint(0, 10**6)) * hi / 10**6 for _ in range(4)}
    return sorted({x for x in (*exact, *near) if x >= 0})


def _payout_map(result: Any) -> dict[str, float]:
    return {p.security_id: p.amount for p in result.payouts}


def _float_tolerance(x: float) -> float:
    return 1e-8 + 1e-12 * x


# ---------------------------------------------------------------------------
# Search A: the vote model
# ---------------------------------------------------------------------------


def vote_search_instance(seed: int) -> Counter[str]:
    """One generated table and term, at every candidate exit. Returns event counts."""
    exact_allocation.cache_clear()  # the cache is per table; keep memory bounded
    rng = random.Random(seed)
    positions, converts, approvals = random_vote_instance(rng)
    stats: Counter[str] = Counter(tables=1)

    def vote_delta(holder: str) -> Callable[[Fraction], Fraction]:
        def f(x: Fraction) -> Fraction:
            outcome = exact_vote(positions, x, converts, approvals)
            return outcome["delta"][holder] if "delta" in outcome else Q(0)

        return f

    voters = sorted({positions[i].holder for v, _, _ in approvals for i in v})
    exits = candidate_exits(positions, [vote_delta(h) for h in voters], rng)
    twin = as_common(positions, converts)
    securities = to_securities(positions)
    term = CollectiveConversion(
        name="generated",
        converts=tuple(_sid(positions, i) for i in sorted(converts)),
        approvals=tuple(
            VoteRequirement(
                name=f"approval {k}",
                voters=tuple(_sid(positions, i) for i in v),
                threshold=t,
                comparison=c,  # type: ignore[arg-type]
                source="generated",
            )
            for k, (v, t, c) in enumerate(approvals)
        ),
        source="generated",
    )
    governed_path: list[tuple[Fraction, tuple[Fraction, ...]]] = []
    plain_path: list[tuple[Fraction, tuple[Fraction, ...]]] = []
    for x in exits:
        stats["instances"] += 1
        # Proposition G1, exactly, on every profile of the players left after the vote.
        _, profiles = _profiles(positions, converts)
        for profile in profiles:
            twin_profile = tuple(False if i in converts else b for i, b in enumerate(profile))
            if exact_allocation(positions, x, profile) != exact_allocation(twin, x, twin_profile):
                stats["g1_mismatch"] += 1
        outcome = exact_vote(positions, x, converts, approvals)
        stats[f"exact_{outcome['kind']}"] += 1
        if outcome["kind"] == "ok":
            if outcome["approved"]:
                stats["approved"] += 1
                if outcome["base"] != outcome["forced"]:
                    stats["approved_and_moves_cash"] += 1
            governed_path.append((x, outcome["payout"]))
            plain_path.append((x, outcome["base"]))
        # The float engine at the float nearest x, against the oracle at that same float.
        xf = float(x)
        at = exact_vote(positions, Q(xf), converts, approvals)
        try:
            engine = resolve_collective_conversion(securities, xf, term=term)
        except GovernanceIndeterminateError:
            engine = None
        tol = _float_tolerance(xf)
        near_tie = at.get("kind") == "refused" or any(
            abs(d) <= Q(tol) * 4 for d in at.get("delta", {}).values()
        )
        if at["kind"] == "ok" and engine is not None:
            paid = _payout_map(engine.result)
            expected = {_sid(positions, i): float(v) for i, v in enumerate(at["payout"])}
            same = engine.approved is at["approved"] and all(
                abs(paid[k] - expected[k]) <= 8 * tol + 1e-9 * abs(expected[k]) for k in expected
            )
            stats[
                "engine_agrees" if same else ("engine_tie_flag" if near_tie else "engine_mismatch")
            ] += 1
        elif engine is None and (at["kind"] == "refused" or near_tie):
            stats["engine_refuses_tie"] += 1
        else:
            stats["engine_tie_flag" if near_tie else "engine_mismatch"] += 1
    for path, key in ((governed_path, "governed"), (plain_path, "plain")):
        falls = [
            max(Q(0), *(a - b for a, b in zip(p0, p1, strict=True)))
            for (_, p0), (_, p1) in zip(path, path[1:], strict=False)
        ]
        if any(f > 0 for f in falls):
            stats[f"{key}_tables_with_a_falling_payout"] += 1
    return stats


# ---------------------------------------------------------------------------
# Search B: the constraint model (a homogeneous series moves together)
# ---------------------------------------------------------------------------


def random_series_instance(rng: random.Random) -> tuple[Positions, tuple[tuple[int, ...], ...]]:
    """1-3 series of identical per-share terms, each split into 1-3 positions (<= 5)."""
    common = rng.choice((0, 2, 5, 10, 20)) * 100
    positions: list[Pos] = []
    if common:
        positions.append(Pos("founders", Q(common), common=True))
    series: list[tuple[int, ...]] = []
    for k in range(rng.randint(1, 3)):
        template = _preferred(rng, f"s{k}")
        room = 5 - sum(len(s) for s in series)
        if room <= 0:
            break
        parts = min(room, rng.randint(1, 3) if series else rng.randint(2, 3))
        members = []
        for j in range(parts):
            positions.append(
                replace(template, holder=f"s{k}h{j}", shares=Q(rng.randint(1, 10) * 100))
            )
            members.append(len(positions) - 1)
        series.append(tuple(members))
    return tuple(positions), tuple(series)


def merged(positions: Positions, series: tuple[tuple[int, ...], ...]) -> Positions:
    """Proposition G2's twin: each series as one position holding the series' shares."""
    out = [p for p in positions if p.common]
    for members in series:
        first = positions[members[0]]
        out.append(
            replace(
                first,
                holder=f"series{members[0]}",
                shares=sum((positions[i].shares for i in members), Q(0)),
            )
        )
    return tuple(out)


def constrained_equilibria(
    positions: Positions, series: tuple[tuple[int, ...], ...], exit_value: Fraction
) -> tuple[list[Profile], set[tuple[Fraction, ...]]]:
    """Series are the players: a profile converts all or none of each series."""

    def profile_of(bits: tuple[bool, ...]) -> Profile:
        state = [False] * len(positions)
        for members, b in zip(series, bits, strict=True):
            for i in members:
                state[i] = b
        return tuple(state)

    feasible: list[Profile] = []
    vectors: set[tuple[Fraction, ...]] = set()
    for bits in itertools.product((False, True), repeat=len(series)):
        pay, stranded = exact_allocation(positions, exit_value, profile_of(bits))
        if stranded:
            continue
        stable = True
        for k, members in enumerate(series):
            other = profile_of(tuple(not b if j == k else b for j, b in enumerate(bits)))
            alt = exact_allocation(positions, exit_value, other)[0]
            if sum((alt[i] for i in members), Q(0)) > sum((pay[i] for i in members), Q(0)):
                stable = False
                break
        if stable:
            feasible.append(profile_of(bits))
            vectors.add(pay)
    return feasible, vectors


def series_search_instance(seed: int) -> Counter[str]:
    exact_allocation.cache_clear()  # the cache is per table; keep memory bounded
    rng = random.Random(seed)
    positions, series = random_series_instance(rng)
    twin = merged(positions, series)
    common_count = sum(1 for p in positions if p.common)
    stats: Counter[str] = Counter(tables=1)
    exits = candidate_exits(positions, [], rng)
    for x in exits:
        stats["instances"] += 1
        # Proposition G2, exactly, on every series profile.
        for bits in itertools.product((False, True), repeat=len(series)):
            state = [False] * len(positions)
            for members, b in zip(series, bits, strict=True):
                for i in members:
                    state[i] = b
            split_pay, split_left = exact_allocation(positions, x, tuple(state))
            twin_pay, twin_left = exact_allocation(
                twin, x, tuple([False] * common_count + list(bits))
            )
            summed = list(split_pay[:common_count]) + [
                sum((split_pay[i] for i in members), Q(0)) for members in series
            ]
            if tuple(summed) != twin_pay or split_left != twin_left:
                stats["g2_mismatch"] += 1
            for members in series:
                per_share = {split_pay[i] / positions[i].shares for i in members}
                if len(per_share) > 1:
                    stats["g2_unequal_per_share"] += 1
        pp_feasible, pp_vectors = exact_equilibria(positions, x)
        c_feasible, c_vectors = constrained_equilibria(positions, series, x)
        if not pp_feasible or not c_feasible:
            stats["infeasible"] += 1
            continue
        stats["pp_multiple_profiles"] += len(pp_feasible) > 1
        stats["constrained_multiple_profiles"] += len(c_feasible) > 1
        stats["pp_nonunique_payoff"] += len(pp_vectors) > 1
        stats["constrained_nonunique_payoff"] += len(c_vectors) > 1
        if pp_vectors != c_vectors:
            stats["pp_vs_constrained_payoff_differs"] += 1
        for profile in pp_feasible:
            if any(len({profile[i] for i in members}) > 1 for members in series):
                stats["pp_split_series_equilibria"] += 1
                pay = exact_allocation(positions, x, profile)[0]
                if any(
                    len({pay[i] / positions[i].shares for i in members}) > 1 for members in series
                ):
                    stats["pp_split_unequal_per_share"] += 1
        # The float engine on the merged table: the constrained game as the engine sees it.
        xf = float(x)
        survey = enumerate_equilibria(to_securities(twin), xf)
        exact_twin = exact_equilibria(twin, Q(xf))[1]
        if len(exact_twin) == 1 and survey.feasible_equilibria:
            expected = next(iter(exact_twin))
            got = survey.feasible_payoffs[0]
            tol = _float_tolerance(xf)
            ok = survey.payoff_unique and all(
                abs(got[_sid(twin, i)] - float(v)) <= 8 * tol + 1e-9 * abs(float(v))
                for i, v in enumerate(expected)
            )
            stats["engine_merged_agrees" if ok else "engine_merged_flag"] += 1
        else:
            stats["engine_merged_flag"] += 1
    return stats


# ---------------------------------------------------------------------------
# Deterministic subsets of both searches (the full runs are in docs/governance.md)
# ---------------------------------------------------------------------------

VOTE_SEED = 20_260_915
SERIES_SEED = 20_260_916


def test_vote_search_subset() -> None:
    stats: Counter[str] = Counter()
    for t in range(6):
        stats += vote_search_instance(VOTE_SEED + t)
    assert stats["instances"] > 100
    assert stats["g1_mismatch"] == 0
    assert stats["exact_nonunique"] == 0
    assert stats["engine_mismatch"] == 0


def test_series_search_subset() -> None:
    stats: Counter[str] = Counter()
    for t in range(6):
        stats += series_search_instance(SERIES_SEED + t)
    assert stats["instances"] > 100
    assert stats["g2_mismatch"] == 0 and stats["g2_unequal_per_share"] == 0
    assert stats["pp_nonunique_payoff"] == 0 and stats["constrained_nonunique_payoff"] == 0


def test_proposition_g1_on_the_engine() -> None:
    """Forced conversion in ovf.waterfall equals the table with those positions as common."""
    rng = random.Random(VOTE_SEED)
    checked = 0
    for _ in range(40):
        positions, converts, _ = random_vote_instance(rng)
        securities = to_securities(positions)
        forced_ids = {_sid(positions, i) for i in converts}
        twin = [
            ovf.common(float(positions[i].units), holder_id=s.holder_id, security_id=s.security_id)
            if s.security_id in forced_ids
            else s
            for i, s in enumerate(securities)
        ]
        players = sorted(
            s.security_id
            for s in securities
            if isinstance(s, ovf.PreferredStock) and s.security_id not in forced_ids
        )
        for x in (0.0, 350.0, 2_500.0, 12_345.0, 90_000.0):
            for bits in itertools.product((False, True), repeat=len(players)):
                state = dict(zip(players, bits, strict=True))
                forced_pay, forced_left = evaluate_fixed_waterfall(
                    securities, x, {**state, **dict.fromkeys(forced_ids, True)}
                )
                twin_pay, twin_left = evaluate_fixed_waterfall(twin, x, state)
                for key in forced_pay:
                    assert forced_pay[key].amount == pytest.approx(twin_pay[key].amount, abs=1e-6)
                assert forced_left == pytest.approx(twin_left, abs=1e-6)
                checked += 1
    assert checked > 200  # most generated terms convert every position, leaving one profile


# ---------------------------------------------------------------------------
# Full searches: python -m tests.test_governance [vote_tables series_tables workers]
# ---------------------------------------------------------------------------


def _run(fn: Callable[[int], Counter[str]], seed: int, count: int, workers: int) -> Counter[str]:
    from concurrent.futures import ProcessPoolExecutor

    total: Counter[str] = Counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for done, stats in enumerate(pool.map(fn, range(seed, seed + count), chunksize=4), 1):
            total += stats
            if done % 250 == 0:  # running totals, so an interrupted run leaves evidence
                print(fn.__name__, done, json.dumps(dict(total), sort_keys=True), file=sys.stderr)
    return total


if __name__ == "__main__":
    vote_tables = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000
    series_tables = int(sys.argv[2]) if len(sys.argv) > 2 else 2_000
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    report = {
        "vote_search": {"seed": VOTE_SEED, "tables": vote_tables},
        "series_search": {"seed": SERIES_SEED, "tables": series_tables},
    }
    report["vote_search"].update(_run(vote_search_instance, VOTE_SEED, vote_tables, workers))
    report["series_search"].update(
        _run(series_search_instance, SERIES_SEED, series_tables, workers)
    )
    print(json.dumps(report, indent=2, sort_keys=True))
