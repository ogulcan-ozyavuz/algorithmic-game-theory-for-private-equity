"""Preferred dividends: accrual on an explicit date, settlement, caps, and the reduction.

Expected values are hand-derived in `docs/dividends.md`; fixtures live in
`tests/dividend_fixtures.py`. The reduction tests check the proposition in that document:
a dividend-bearing table is the same game as a stated no-dividend table.
"""

from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import math
import random
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

import ovf
from ovf.contracts.securities import (
    CumulativeDividend,
    DividendDayCount,
    NonCumulativeDividend,
    PreferredStock,
    cumulative_dividend,
    non_cumulative_dividend,
)
from ovf.instruments import DayCount
from ovf.waterfall import enumerate_equilibria, evaluate_fixed_waterfall, solve_waterfall
from tests.dividend_fixtures import (
    ACCRUAL_FIXTURES,
    ACCRUES_FROM,
    AS_OF,
    FLIP_FIXTURES,
    WATERFALL_FIXTURES,
    DividendAccrualFixture,
    DividendWaterfallFixture,
    FlipFixture,
    dividend,
    founders,
    series_a,
)
from tests.fixtures import FIXTURES, WaterfallFixture

# ---------------------------------------------------------------------------
# Accrual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ACCRUAL_FIXTURES, ids=lambda f: f.case_id)
def test_accrual_fixture(fixture: DividendAccrualFixture) -> None:
    accrual = fixture.position.dividend_accrual(fixture.as_of)
    assert accrual is not None
    assert accrual.days == fixture.expected_days
    assert accrual.compounding_periods == fixture.expected_periods
    assert accrual.accrued_per_share == pytest.approx(
        fixture.expected_accrued_per_share, rel=1e-12, abs=1e-12
    )
    assert accrual.accrued == pytest.approx(fixture.expected_accrued, rel=1e-12, abs=1e-9)
    assert accrual.preference == pytest.approx(fixture.expected_preference, rel=1e-12)
    assert accrual.conversion_units == pytest.approx(fixture.expected_units, rel=1e-12)
    if fixture.expected_paid_in_kind_shares is None:
        assert accrual.paid_in_kind_shares is None
    else:
        assert accrual.paid_in_kind_shares == pytest.approx(
            fixture.expected_paid_in_kind_shares, rel=1e-12
        )
    terms = fixture.position.exit_terms(fixture.as_of)
    assert terms.preference == accrual.preference
    assert terms.units == accrual.conversion_units
    assert fixture.position.liquidation_preference(fixture.as_of) == accrual.preference


def test_long_horizon_date_is_fifteen_365_day_years() -> None:
    assert (date(2039, 12, 29) - ACCRUES_FROM).days == 15 * 365


def test_compounding_exceeds_simple_by_interest_on_year_one() -> None:
    by_id = {f.case_id: f.position.dividend_accrual(f.as_of) for f in ACCRUAL_FIXTURES}
    simple, compound = by_id["DV1"], by_id["DV2"]
    assert simple is not None and compound is not None
    assert compound.accrued > simple.accrued
    assert compound.accrued - simple.accrued == pytest.approx(32_000, rel=1e-9)


def test_zero_elapsed_days_accrues_nothing() -> None:
    for term in (dividend(), dividend(accrual="compound", compounding_frequency=4)):
        accrual = series_a(term).dividend_accrual(ACCRUES_FROM)
        assert accrual is not None
        assert accrual.days == 0 and accrual.accrued == 0
        assert accrual.preference == 5_000_000


def test_non_cumulative_accrues_nothing_on_any_date() -> None:
    position = series_a(non_cumulative_dividend(0.08))
    for as_of in (None, AS_OF, date(2039, 12, 29)):
        accrual = position.dividend_accrual(as_of)
        assert accrual is not None and accrual.kind == "non_cumulative"
        assert accrual.accrued == 0 and accrual.preference == 5_000_000
        assert accrual.as_of is None and accrual.days is None
    assert position.base_liquidation_preference() == 5_000_000


def test_day_count_names_match_the_debt_module() -> None:
    assert set(get_args(DividendDayCount)) == {member.value for member in DayCount}
    by_enum = series_a(dividend(day_count=DayCount.ACT_360))  # type: ignore[arg-type]
    assert by_enum == series_a(dividend(day_count="actual/360"))


# ---------------------------------------------------------------------------
# Exit waterfalls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", WATERFALL_FIXTURES, ids=lambda f: f.case_id)
def test_waterfall_fixture(fixture: DividendWaterfallFixture) -> None:
    report = solve_waterfall(fixture.securities, fixture.exit_valuation, as_of=fixture.as_of)
    actual = {p.security_id: p.amount for p in report.payouts}
    assert actual == pytest.approx(fixture.expected, abs=1e-6)
    assert math.fsum(actual.values()) == pytest.approx(fixture.exit_valuation, rel=1e-12)
    assert abs(report.conservation_error) <= report.tolerance
    assert all(p.amount >= 0 for p in report.payouts)
    assert report.converged and report.max_unilateral_gain <= report.tolerance
    converted = {
        p.security_id: p.converted
        for p in report.payouts
        if p.security_id in fixture.expected_converted
    }
    assert converted == fixture.expected_converted


@pytest.mark.parametrize("fixture", WATERFALL_FIXTURES, ids=lambda f: f.case_id)
def test_waterfall_fixture_payoffs_are_equilibrium_unique(
    fixture: DividendWaterfallFixture,
) -> None:
    survey = enumerate_equilibria(fixture.securities, fixture.exit_valuation, as_of=fixture.as_of)
    assert survey.feasible_equilibria
    assert survey.payoff_unique
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


def _fixture(case_id: str) -> DividendWaterfallFixture:
    return next(f for f in WATERFALL_FIXTURES if f.case_id == case_id)


def test_accrued_dividends_change_who_converts() -> None:
    with_dividend = solve_waterfall(_fixture("DW1").securities, 27_000_000, as_of=AS_OF)
    without = solve_waterfall(_fixture("DW1-none").securities, 27_000_000)
    assert [p.converted for p in with_dividend.payouts] == [False, False]
    assert [p.converted for p in without.payouts] == [False, True]


def test_dividend_is_a_preference_component_and_trace_is_reported() -> None:
    report = solve_waterfall(_fixture("DW1").securities, 27_000_000, as_of=AS_OF)
    series = next(p for p in report.payouts if p.security_id == "series_a")
    assert series.preference_payout == pytest.approx(5_800_000)
    assert series.invested_capital == 5_000_000
    assert series.effective_multiple == pytest.approx(1.16)
    assert report.as_of == AS_OF
    (trace,) = report.dividend_accruals
    assert trace.accrued == pytest.approx(800_000) and trace.settlement == "forfeit_on_conversion"
    assert report.debt_settlements == []


def test_shortfall_weights_include_dividends() -> None:
    with_dividend = _fixture("DW7")
    without = _fixture("DW7-none")
    a = solve_waterfall(with_dividend.securities, 7_400_000, as_of=AS_OF).payouts[1].amount
    b = solve_waterfall(without.securities, 7_400_000).payouts[1].amount
    assert a - b == pytest.approx(2_900_000 - 7_400_000 * 5 / 14, abs=1e-6)


def test_cap_bases_differ_and_pik_differs_again() -> None:
    """At $40M: inside $10M, outside $10.8M, paid in kind $11.6M (DW2, DW3, DW4)."""
    paid = {
        case: solve_waterfall(_fixture(case).securities, 40_000_000, as_of=AS_OF).payouts[1].amount
        for case in ("DW2", "DW3", "DW4")
    }
    assert paid == pytest.approx({"DW2": 10_000_000, "DW3": 10_800_000, "DW4": 11_600_000})


def test_clamp_makes_dividends_above_the_cap_worthless() -> None:
    """DW5 pays what F5a pays: a $6M accrual adds nothing once the preference passes the cap."""
    f5a = next(f for f in FIXTURES if f.case_id == "F5a")
    plain = solve_waterfall(f5a.securities, 40_000_000).payouts
    clamped = solve_waterfall(_fixture("DW5").securities, 40_000_000, as_of=date(2039, 12, 29))
    assert [p.amount for p in clamped.payouts] == pytest.approx([p.amount for p in plain])
    (trace,) = clamped.dividend_accruals
    assert trace.accrued == pytest.approx(6_000_000) and trace.preference == pytest.approx(1e7)


# ---------------------------------------------------------------------------
# The conversion flip point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", FLIP_FIXTURES, ids=lambda f: f.case_id)
def test_flip_point(fixture: FlipFixture) -> None:
    """At the flip both actions pay the same; $10 either side the decision changes."""
    at = enumerate_equilibria(fixture.securities, fixture.flip_exit, as_of=fixture.as_of)
    assert len(at.feasible_equilibria) == 2
    assert at.payoff_unique
    assert at.feasible_payoffs[0] == pytest.approx(fixture.expected_at_flip, abs=1e-6)
    report = solve_waterfall(fixture.securities, fixture.flip_exit, as_of=fixture.as_of)
    assert {p.security_id: p.amount for p in report.payouts} == pytest.approx(
        fixture.expected_at_flip, abs=1e-6
    )
    for exit_value, converts in ((fixture.flip_exit - 10, False), (fixture.flip_exit + 10, True)):
        near = solve_waterfall(fixture.securities, exit_value, as_of=fixture.as_of)
        assert near.payouts[1].converted is converts


def test_flip_point_moves_with_the_dividend() -> None:
    flips = {f.case_id: f.flip_exit for f in FLIP_FIXTURES}
    assert flips["FL0"] < flips["FL3"] < flips["FL1"] < flips["FL2"]
    assert flips["FL1"] - flips["FL0"] == pytest.approx(800_000 / 0.20)


# ---------------------------------------------------------------------------
# Time basis: no implicit clock
# ---------------------------------------------------------------------------


def test_cumulative_dividend_at_exit_requires_an_explicit_as_of() -> None:
    securities = (founders(), series_a(dividend()))
    for exit_value in (0, 27_000_000):
        with pytest.raises(ValueError, match="explicit as_of date \\(series_a\\)"):
            solve_waterfall(securities, exit_value)
        with pytest.raises(ValueError, match="explicit as_of"):
            enumerate_equilibria(securities, exit_value)
    with pytest.raises(ValueError, match="explicit as_of"):
        ovf.CapTable(securities=list(securities)).waterfall(27_000_000)
    with pytest.raises(ValueError, match="explicit as_of"):
        evaluate_fixed_waterfall(securities, 1.0, {"series_a": False})
    with pytest.raises(TypeError, match="exit_terms"):
        series_a(dividend()).base_liquidation_preference()


def test_as_of_is_checked() -> None:
    position = series_a(dividend())
    with pytest.raises(ValueError, match="before accrues_from"):
        position.exit_terms(date(2024, 12, 31))
    with pytest.raises(ValueError, match="datetime.date"):
        position.exit_terms(datetime(2027, 1, 1, 9, 0))
    with pytest.raises(ValueError, match="datetime.date"):
        position.exit_terms("2027-01-01")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="before accrues_from"):
        solve_waterfall((founders(), position), 1e7, as_of=date(2024, 12, 31))


def test_partial_compounding_period_is_refused() -> None:
    quarterly = series_a(dividend(accrual="compound", compounding_frequency=4))
    with pytest.raises(ValueError, match="whole number"):
        quarterly.exit_terms(date(2025, 4, 1))
    monthly_360 = series_a(
        dividend(accrual="compound", compounding_frequency=12, day_count="actual/360")
    )
    trace = monthly_360.dividend_accrual(date(2025, 1, 31))
    assert trace is not None and trace.compounding_periods == 1


def test_no_clock_is_read() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ovf"
    for path in (root / "contracts" / "securities.py", root / "waterfall.py"):
        source = path.read_text(encoding="utf-8")
        for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
            assert call not in source, f"{path.name} reads a clock via {call}"


def test_fingerprint_pins_the_date_and_the_terms() -> None:
    securities = _fixture("DW1").securities
    first = solve_waterfall(securities, 27_000_000, as_of=AS_OF)
    assert first.input_hash == solve_waterfall(securities, 27_000_000, as_of=AS_OF).input_hash
    assert first.input_hash != solve_waterfall(securities, 27e6, as_of=date(2027, 1, 2)).input_hash
    compound = (founders(), series_a(dividend(accrual="compound", compounding_frequency=1)))
    assert first.input_hash != solve_waterfall(compound, 27_000_000, as_of=AS_OF).input_hash


def test_non_cumulative_does_not_read_as_of() -> None:
    securities = _fixture("DW8").securities
    plain = solve_waterfall(securities, 15_000_000)
    dated = solve_waterfall(securities, 15_000_000, as_of=AS_OF)
    assert plain.input_hash == dated.input_hash
    assert plain.as_of is None and dated.as_of is None
    f2 = next(f for f in FIXTURES if f.case_id == "F2")
    reference = solve_waterfall(f2.securities, 15_000_000)
    assert [p.model_dump() for p in plain.payouts] == [p.model_dump() for p in reference.payouts]
    assert any("Non-cumulative dividends accrue nothing" in line for line in plain.assumptions)


# ---------------------------------------------------------------------------
# Assumptions: a default that is used is a stated default
# ---------------------------------------------------------------------------


def test_default_cap_basis_is_written_into_assumptions() -> None:
    report = solve_waterfall(_fixture("DW2").securities, 40_000_000, as_of=AS_OF)
    assert (
        "series_a: the participation cap includes accrued dividends (default; NVCA Model COI "
        "fn 20)." in report.assumptions
    )
    (trace,) = report.dividend_accruals
    assert trace.participation_cap_basis == "includes_dividends"
    assert not trace.participation_cap_basis_stated


def test_stated_cap_bases_are_labelled_stated() -> None:
    stated_inside = (
        founders(),
        series_a(
            dividend(participation_cap_basis="includes_dividends"),
            participating=True,
            participation_cap=2.0,
        ),
    )
    report = solve_waterfall(stated_inside, 40_000_000, as_of=AS_OF)
    assert any("includes accrued dividends (stated" in line for line in report.assumptions)
    outside = solve_waterfall(_fixture("DW3").securities, 40_000_000, as_of=AS_OF)
    assert any("excludes accrued dividends" in line for line in outside.assumptions)


def test_cap_basis_is_not_consulted_without_a_cap() -> None:
    for case in ("DW1", "DW9", "DW10", "DW4"):
        report = solve_waterfall(
            _fixture(case).securities, _fixture(case).exit_valuation, as_of=AS_OF
        )
        assert report.dividend_accruals[0].participation_cap_basis is None
        assert not any("participation cap" in line for line in report.assumptions)


def test_settlement_is_named_in_assumptions() -> None:
    forfeit = solve_waterfall(_fixture("DW1").securities, 27_000_000, as_of=AS_OF)
    pik = solve_waterfall(_fixture("DW10").securities, 30_960_000, as_of=AS_OF)
    assert any(line.startswith("forfeit_on_conversion:") for line in forfeit.assumptions)
    assert any(line.startswith("paid_in_kind:") for line in pik.assumptions)
    assert any("2027-01-01" in line for line in forfeit.assumptions)
    assert "Declared-but-unpaid dividends are not modelled" in forfeit.assumptions[-1]


# ---------------------------------------------------------------------------
# Input validation: conventions without a standard have no default
# ---------------------------------------------------------------------------


def _terms(**overrides: object) -> dict[str, object]:
    terms: dict[str, object] = {
        "annual_rate": 0.08,
        "accrual": "simple",
        "day_count": "actual/365_fixed",
        "accrues_from": ACCRUES_FROM,
        "settlement": "forfeit_on_conversion",
    }
    terms.update(overrides)
    return terms


def test_required_dividend_terms_have_no_defaults() -> None:
    for missing in ("annual_rate", "accrual", "day_count", "accrues_from", "settlement"):
        terms = _terms()
        del terms[missing]
        with pytest.raises(ValidationError):
            CumulativeDividend.model_validate(terms)
    signature = inspect.signature(cumulative_dividend)
    for name in ("accrual", "day_count", "accrues_from", "settlement"):
        assert signature.parameters[name].default is inspect.Parameter.empty
    assert signature.parameters["participation_cap_basis"].default is None
    assert "NVCA Model COI fn 20" in (cumulative_dividend.__doc__ or "")
    assert "fn 20" in (CumulativeDividend.__doc__ or "")


@pytest.mark.parametrize(
    "overrides",
    [
        {"annual_rate": 0},
        {"annual_rate": -0.01},
        {"annual_rate": 1.5},
        {"annual_rate": float("nan")},
        {"accrual": "continuous"},
        {"accrual": "compound"},
        {"compounding_frequency": 1},
        {"accrual": "compound", "compounding_frequency": 0},
        {"accrual": "compound", "compounding_frequency": 4.0},
        {"accrual": "compound", "compounding_frequency": True},
        {"day_count": "30/360"},
        {"settlement": "retain_as_cash"},
        {"settlement": "forfeit"},
        {"accrues_from": datetime(2025, 1, 1, 9, 30)},
        {"participation_cap_basis": "total"},
        {"settlement": "paid_in_kind", "participation_cap_basis": "includes_dividends"},
        {"unknown_term": 1},
    ],
    ids=lambda o: ",".join(o),
)
def test_invalid_dividend_terms_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CumulativeDividend.model_validate(_terms(**overrides))


def test_invalid_positions_are_rejected() -> None:
    with pytest.raises(ValidationError, match="price must be positive"):
        ovf.preferred(100, 0.0, dividend=dividend())
    with pytest.raises(ValidationError, match="only to a participating position"):
        series_a(dividend(participation_cap_basis="includes_dividends"))
    with pytest.raises(ValidationError, match="only to a participating position"):
        series_a(dividend(participation_cap_basis="excludes_dividends"), participating=True)
    for bad in ({"annual_rate": 0}, {"annual_rate": 0.08, "accrues_from": ACCRUES_FROM}):
        with pytest.raises(ValidationError):
            NonCumulativeDividend.model_validate(bad)
    with pytest.raises(ValidationError):
        PreferredStock.model_validate(
            {**series_a().model_dump(), "dividend": {"kind": "declared", "annual_rate": 0.08}}
        )


def test_dividend_terms_are_immutable_and_round_trip() -> None:
    position = series_a(dividend(accrual="compound", compounding_frequency=1))
    with pytest.raises(ValidationError):
        position.dividend = None  # type: ignore[misc]
    term = position.dividend
    assert isinstance(term, CumulativeDividend)
    with pytest.raises(ValidationError):
        term.annual_rate = 0.1  # type: ignore[misc]
    assert PreferredStock.model_validate(position.model_dump()) == position
    assert PreferredStock.model_validate_json(position.model_dump_json()) == position
    noncum = series_a(non_cumulative_dividend(0.08))
    assert PreferredStock.model_validate(noncum.model_dump()) == noncum


# ---------------------------------------------------------------------------
# Regression: a position without a dividend is unchanged, byte for byte
# ---------------------------------------------------------------------------

PRE_DIVIDEND_PREFERRED_FIELDS = {
    "security_id",
    "holder_id",
    "shares",
    "price",
    "seniority",
    "liquidation_multiple",
    "participating",
    "participation_cap",
    "conversion_ratio",
}
PRE_DIVIDEND_ASSUMPTIONS = [
    "Each preferred position makes an independent conversion decision.",
    "Reserved unallocated option capacity has no exit payment entitlement.",
    "Single base currency; float accounting within reported tolerance.",
    "No debt, unexercised option settlement, SAFE liquidity events or class voting.",
]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_no_dividend_results_are_unchanged(fixture: WaterfallFixture) -> None:
    """Hand-derived payouts, the pre-dividend fingerprint and assumptions, no trace."""
    report = solve_waterfall(fixture.securities, fixture.exit_valuation)
    dated = solve_waterfall(fixture.securities, fixture.exit_valuation, as_of=AS_OF)
    assert {p.security_id: p.amount for p in report.payouts} == pytest.approx(
        fixture.expected, abs=1e-6
    )
    payload = {
        "securities": [{"kind": type(s).__name__, **s.model_dump()} for s in fixture.securities],
        "exit_valuation": fixture.exit_valuation,
        "transaction_costs": 0.0,
        "max_iterations": 20,
        "atol": 1e-8,
        "rtol": 1e-12,
    }
    expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
    assert report.input_hash == dated.input_hash == expected_hash.hexdigest()
    assert report.assumptions == PRE_DIVIDEND_ASSUMPTIONS
    assert report.dividend_accruals == [] and report.as_of is None and dated.as_of is None
    assert report.engine_version == "waterfall-v3"
    for s in fixture.securities:
        if isinstance(s, PreferredStock):
            assert set(s.model_dump()) == PRE_DIVIDEND_PREFERRED_FIELDS
            assert "dividend" not in s.model_dump_json()
            assert s.exit_terms(None) == (
                s.base_liquidation_preference(),
                None if s.participation_cap is None else s.invested_capital * s.participation_cap,
                s.converted_shares,
            )


def test_explicit_none_dividend_equals_omitting_it() -> None:
    explicit = ovf.preferred(2_000_000, 2.50, holder_id="a", security_id="a", dividend=None)
    omitted = ovf.preferred(2_000_000, 2.50, holder_id="a", security_id="a")
    assert explicit == omitted and explicit.model_dump_json() == omitted.model_dump_json()
    for exit_value in (0, 15e6, 35e6):
        first = solve_waterfall([founders(), explicit], exit_value)
        second = solve_waterfall([founders(), omitted], exit_value)
        assert first.model_dump_json() == second.model_dump_json()


# ---------------------------------------------------------------------------
# The reduction (docs/dividends.md, Proposition 1)
# ---------------------------------------------------------------------------


def reduction_twin(position: PreferredStock, as_of: date) -> PreferredStock:
    """The no-dividend position Proposition 1 says is equivalent, built from the algebra.

    Forfeit: multiple m + d, where d = accrued / invested. With a cap c, the cap stays c
    and the multiple becomes min(m + d, c) when accrued dividends are inside it; the cap
    becomes c + d when they are outside. Paid in kind: shares x (1 + d).
    """
    term = position.dividend
    if not isinstance(term, CumulativeDividend):
        return position
    trace = position.dividend_accrual(as_of)
    assert trace is not None
    d = trace.accrued / position.invested_capital
    fields = {**position.model_dump(), "dividend": None}
    m, c = position.liquidation_multiple, position.participation_cap
    if term.settlement == "paid_in_kind":
        fields["shares"] = position.shares * (1 + d)
    elif c is None:
        fields["liquidation_multiple"] = m + d
    elif term.participation_cap_basis == "excludes_dividends":
        fields["liquidation_multiple"], fields["participation_cap"] = m + d, c + d
    else:
        fields["liquidation_multiple"] = min(m + d, c)
    return PreferredStock.model_validate(fields)


SWEEP_AS_OF = date(2026, 1, 1)


def random_dividend_table(rng: random.Random) -> list[ovf.Security]:
    securities: list[ovf.Security] = []
    if rng.random() < 0.85:
        securities.append(ovf.common(rng.choice([1, 7, 1_000, 8_000_000]), security_id="c"))
    if rng.random() < 0.2:
        securities.append(ovf.option_pool(rng.choice([10, 1_000_000]), security_id="pool"))
    for i in range(rng.randint(1, 4)):
        m = rng.choice([0.5, 1.0, 1.5, 2.0, 3.0])
        participating = rng.random() < 0.5
        cap = rng.choice([None, m, m + 0.5, m + 2.0]) if participating else None
        term: CumulativeDividend | None = None
        if rng.random() < 0.8:
            settlement = rng.choice(["forfeit_on_conversion", "paid_in_kind"])
            basis = None
            if cap is not None and settlement == "forfeit_on_conversion":
                basis = rng.choice([None, "includes_dividends", "excludes_dividends"])
            compound = rng.random() < 0.3
            term = cumulative_dividend(
                rng.choice([0.04, 0.08, 0.12, 0.25]),
                accrual="compound" if compound else "simple",
                compounding_frequency=rng.choice([1, 4]) if compound else None,
                day_count="actual/365_fixed",
                accrues_from=SWEEP_AS_OF - timedelta(days=365 * rng.choice([0, 1, 2, 5, 10, 20])),
                settlement=settlement,  # type: ignore[arg-type]
                participation_cap_basis=basis,  # type: ignore[arg-type]
            )
        securities.append(
            ovf.preferred(
                rng.choice([1, 3, 500, 2_000_000]),
                rng.choice([0.5, 1.0, 2.5, 6.0]),
                seniority=rng.randint(0, 2),
                liquidation_multiple=m,
                participating=participating,
                participation_cap=cap,
                conversion_ratio=rng.choice([1.0, 1.25, 2.0]),
                holder_id=f"h{i}",
                security_id=f"p{i}",
                dividend=term,
            )
        )
    return securities


def _anniversary(securities: list[ovf.Security]) -> date:
    return SWEEP_AS_OF  # a whole number of 365-day years after every accrues_from above


def _exits(securities: list[ovf.Security], as_of: date) -> list[float]:
    claims = [s.liquidation_preference(as_of) for s in securities if isinstance(s, PreferredStock)]
    total = math.fsum(claims)
    return sorted({0.0, *claims, total / 2, total, total * 1.5, total * 4 + 7, total * 20})


def test_reduction_holds_on_every_profile_on_both_branches() -> None:
    """Dividend table and twin table pay every position the same in every profile.

    Comparing all 2**n profiles covers the preference branch and the conversion branch of
    every position, so the two payoff functions, and hence the two games, coincide.
    """
    rng = random.Random(20260915)
    compared = 0
    for _ in range(150):
        securities = random_dividend_table(rng)
        as_of = _anniversary(securities)
        twins = [
            reduction_twin(s, as_of) if isinstance(s, PreferredStock) else s for s in securities
        ]
        ids = [s.security_id for s in securities if isinstance(s, PreferredStock)]
        for exit_value in _exits(securities, as_of):
            tolerance = 1e-8 + 1e-12 * exit_value
            for bits in itertools.product([False, True], repeat=len(ids)):
                state = dict(zip(ids, bits, strict=True))
                real, real_left = evaluate_fixed_waterfall(
                    securities, exit_value, state, as_of=as_of
                )
                twin, twin_left = evaluate_fixed_waterfall(twins, exit_value, state)
                assert real_left == pytest.approx(twin_left, rel=1e-9, abs=tolerance)
                for sid, payout in real.items():
                    assert payout.amount == pytest.approx(
                        twin[sid].amount, rel=1e-9, abs=tolerance
                    ), (sid, state, exit_value)
                compared += 1
            real_survey = enumerate_equilibria(securities, exit_value, as_of=as_of)
            twin_survey = enumerate_equilibria(twins, exit_value)
            assert real_survey.equilibria == twin_survey.equilibria
            assert real_survey.feasible_equilibria == twin_survey.feasible_equilibria
    assert compared > 3_000


def test_paid_in_kind_twin_has_the_intended_denominator() -> None:
    """The twin adds exactly the paid-in-kind shares to the residual denominator."""
    position = series_a(dividend(settlement="paid_in_kind"))
    twin = reduction_twin(position, AS_OF)
    assert twin.shares == pytest.approx(2_320_000)
    assert twin.converted_shares == pytest.approx(2_320_000)
    table = ovf.CapTable(securities=[founders(), twin])
    assert table.fully_diluted_shares == pytest.approx(10_320_000)


# ---------------------------------------------------------------------------
# Exact-rational oracle, written independently of ovf's exit terms and allocation
# ---------------------------------------------------------------------------

Terms = tuple[Fraction, Fraction | None, Fraction]


def exact_accrued(position: PreferredStock, as_of: date) -> Fraction:
    """Accrued dividends for the position, in exact arithmetic."""
    term = position.dividend
    if not isinstance(term, CumulativeDividend):
        return Fraction(0)
    invested = Fraction(position.shares) * Fraction(position.price)
    days = (as_of - term.accrues_from).days
    year = 365 if term.day_count == "actual/365_fixed" else 360
    rate = Fraction(term.annual_rate)
    if term.accrual == "simple":
        return invested * rate * days / year
    f = term.compounding_frequency
    assert f is not None and days * f % year == 0
    return invested * ((1 + rate / f) ** (days * f // year) - 1)


def charter_terms(position: PreferredStock, as_of: date) -> Terms:
    """(preference, total cap, units), read directly off the charter rules."""
    shares, price = Fraction(position.shares), Fraction(position.price)
    m, ratio = Fraction(position.liquidation_multiple), Fraction(position.conversion_ratio)
    c = None if position.participation_cap is None else Fraction(position.participation_cap)
    invested = shares * price
    term = position.dividend
    if not isinstance(term, CumulativeDividend):
        return invested * m, None if c is None else invested * c, shares * ratio
    accrued = exact_accrued(position, as_of)
    if term.settlement == "paid_in_kind":  # Spark s.1.1: accrued / OIP new shares
        grown = shares + accrued / price
        return grown * price * m, None if c is None else grown * price * c, grown * ratio
    preference = invested * m + accrued  # NVCA fn 17/19
    if c is None:
        return preference, None, shares * ratio
    if term.participation_cap_basis == "excludes_dividends":  # Virtual Piggy s.4.2
        return preference, invested * c + accrued, shares * ratio
    return min(preference, invested * c), invested * c, shares * ratio  # NVCA fn 20


def twin_terms(position: PreferredStock, as_of: date) -> Terms:
    """Proposition 1: the no-dividend twin's terms, from d = accrued / invested."""
    shares, price = Fraction(position.shares), Fraction(position.price)
    m, ratio = Fraction(position.liquidation_multiple), Fraction(position.conversion_ratio)
    c = None if position.participation_cap is None else Fraction(position.participation_cap)
    invested = shares * price
    term = position.dividend
    if not isinstance(term, CumulativeDividend):
        return invested * m, None if c is None else invested * c, shares * ratio
    d = exact_accrued(position, as_of) / invested
    if term.settlement == "paid_in_kind":
        shares *= 1 + d
        invested = shares * price
        return invested * m, None if c is None else invested * c, shares * ratio
    if c is None:
        return invested * (m + d), None, shares * ratio
    if term.participation_cap_basis == "excludes_dividends":
        return invested * (m + d), invested * (c + d), shares * ratio
    return invested * min(m + d, c), invested * c, shares * ratio


def exact_allocation(
    securities: list[ovf.Security],
    terms: dict[str, Terms],
    cash: Fraction,
    state: dict[str, bool],
) -> tuple[dict[str, Fraction], Fraction]:
    """Preference tiers, then water-filling of the residual under caps; returns stranded cash."""
    paid = {s.security_id: Fraction(0) for s in securities}
    holding = [s for s in securities if isinstance(s, PreferredStock) and not state[s.security_id]]
    for level in sorted({s.seniority for s in holding}):
        tier = [s for s in holding if s.seniority == level]
        need = sum((terms[s.security_id][0] for s in tier), Fraction(0))
        budget = min(cash, need)
        for s in tier:
            paid[s.security_id] = budget * terms[s.security_id][0] / need if need else Fraction(0)
        cash -= budget
    units: dict[str, Fraction] = {}
    limits: dict[str, Fraction] = {}
    for s in securities:
        sid = s.security_id
        if isinstance(s, ovf.CommonStock) and s.shares > 0:
            units[sid] = Fraction(s.shares)
        elif isinstance(s, PreferredStock) and s.shares > 0 and (state[sid] or s.participating):
            units[sid] = terms[sid][2]
            cap = terms[sid][1]
            if not state[sid] and cap is not None:
                limits[sid] = max(Fraction(0), cap - paid[sid])
    open_units = sum(units.values(), Fraction(0))
    capped: set[str] = set()
    for sid in sorted(limits, key=lambda i: limits[i] / units[i]):
        if cash <= limits[sid] / units[sid] * open_units:
            break
        paid[sid] += limits[sid]
        cash -= limits[sid]
        open_units -= units[sid]
        capped.add(sid)
    if open_units == 0:
        return paid, cash
    for sid, u in units.items():
        if sid not in capped:
            paid[sid] += cash * u / open_units
    return paid, Fraction(0)


Survey = tuple[
    list[tuple[bool, ...]],
    set[tuple[Fraction, ...]],
    dict[tuple[bool, ...], tuple[dict[str, Fraction], Fraction]],
]


def exact_survey(
    securities: list[ovf.Security], exit_value: Fraction, as_of: date, terms_of: object
) -> Survey:
    """Every profile, the feasible pure equilibria (no tolerance) and their payoff vectors."""
    pref = [s for s in securities if isinstance(s, PreferredStock)]
    ids = [s.security_id for s in pref]
    terms = {s.security_id: terms_of(s, as_of) for s in pref}  # type: ignore[operator]
    table = {
        bits: exact_allocation(securities, terms, exit_value, dict(zip(ids, bits, strict=True)))
        for bits in itertools.product([False, True], repeat=len(ids))
    }
    feasible: list[tuple[bool, ...]] = []
    for bits, (paid, stranded) in table.items():
        stable = all(
            paid[sid] >= table[tuple(not b if j == i else b for j, b in enumerate(bits))][0][sid]
            for i, sid in enumerate(ids)
        )
        if stable and stranded == 0:
            feasible.append(bits)
    vectors = {tuple(table[bits][0][s.security_id] for s in securities) for bits in feasible}
    return feasible, vectors, table


def test_exact_oracle_reproduces_the_hand_derived_fixtures() -> None:
    for fixture in WATERFALL_FIXTURES:
        if any(not isinstance(s, (ovf.CommonStock, PreferredStock)) for s in fixture.securities):
            continue  # the oracle has no debt; DW11 is covered by the engine test
        feasible, vectors, _ = exact_survey(
            list(fixture.securities),
            Fraction(fixture.exit_valuation),
            fixture.as_of or AS_OF,
            charter_terms,
        )
        assert feasible and len(vectors) == 1, fixture.case_id
        (vector,) = vectors
        expected = [fixture.expected[s.security_id] for s in fixture.securities]
        assert [float(x) for x in vector] == pytest.approx(expected, abs=1e-6), fixture.case_id


def test_exact_reduction_and_payoff_uniqueness_sweep() -> None:
    """Exact arithmetic on generated tables at breakpoint exits.

    The twin's payoffs equal the charter's in every profile, the engine agrees with the
    oracle in every profile, and every instance with a feasible equilibrium has exactly
    one equilibrium payoff vector.
    """
    rng = random.Random(1_000_003)
    instances = multiple = 0
    for _ in range(60):
        securities = random_dividend_table(rng)
        as_of = _anniversary(securities)
        pref = [s for s in securities if isinstance(s, PreferredStock)]
        claims = [charter_terms(s, as_of)[0] for s in pref]
        total = sum(claims, Fraction(0))
        exits = {Fraction(0), total, *claims, total * 2 + 1, total * 5 + 1, total * 30 + 1}
        exits |= {x + Fraction(1, 1000) for x in list(exits)}
        for exit_value in sorted(exits):
            feasible, vectors, table = exact_survey(securities, exit_value, as_of, charter_terms)
            _, twin_vectors, twin_table = exact_survey(securities, exit_value, as_of, twin_terms)
            assert table == twin_table
            assert vectors == twin_vectors
            tolerance = 1e-8 + 1e-12 * float(exit_value)
            ids = [s.security_id for s in pref]
            for bits, (paid, stranded) in table.items():
                state = dict(zip(ids, bits, strict=True))
                real, left = evaluate_fixed_waterfall(
                    securities, float(exit_value), state, as_of=as_of
                )
                assert left == pytest.approx(float(stranded), rel=1e-9, abs=tolerance)
                for sid, amount in paid.items():
                    assert real[sid].amount == pytest.approx(float(amount), rel=1e-9, abs=tolerance)
            if feasible:
                instances += 1
                multiple += len(feasible) > 1
                assert len(vectors) == 1, (securities, exit_value)
    assert instances > 300 and multiple > 0
