"""Debt at exit: accrual on an explicit date, absolute priority, and no-debt regression.

Expected values are hand-derived in `docs/debt.md`; fixtures live in
`tests/debt_fixtures.py`.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import ovf
from ovf.instruments import AccrualMethod, ConvertibleNote, DebtInstrument, debt
from ovf.waterfall import enumerate_equilibria, solve_waterfall
from tests.debt_fixtures import (
    ACCRUAL_FIXTURES,
    ACT_365,
    AS_OF,
    DEBT_WATERFALL_FIXTURES,
    ISSUE,
    NOTE_CONVERSION_FIXTURES,
    NOTE_MATURITY,
    AccrualFixture,
    DebtWaterfallFixture,
    NoteConversionFixture,
    founders,
    loan,
    note,
    series_a,
    venture_loan,
)
from tests.fixtures import FIXTURES, WaterfallFixture

EQUITY_IDS = ("common", "series_a")

# ---------------------------------------------------------------------------
# Accrual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ACCRUAL_FIXTURES, ids=lambda f: f.case_id)
def test_accrual_fixture(fixture: AccrualFixture) -> None:
    accrual = fixture.instrument.accrue(fixture.as_of)
    assert accrual.days == fixture.expected_days
    assert accrual.year_fraction == pytest.approx(fixture.expected_year_fraction, rel=1e-15)
    assert accrual.compounding_periods == fixture.expected_periods
    assert accrual.outstanding_principal == pytest.approx(
        fixture.expected_outstanding_principal, rel=1e-12
    )
    assert accrual.accrued_interest == pytest.approx(
        fixture.expected_accrued_interest, rel=1e-12, abs=1e-9
    )
    claim = fixture.instrument.exit_claim(fixture.as_of)
    assert claim.claim == pytest.approx(fixture.expected_claim, rel=1e-12)
    assert claim.accrual == accrual


def test_compounding_exceeds_simple_and_frequency_matters() -> None:
    by_id = {f.case_id: f.instrument.exit_claim(AS_OF).claim for f in ACCRUAL_FIXTURES}
    assert by_id["A1"] < by_id["A2"] < by_id["A3"]
    assert by_id["A2"] - by_id["A1"] == pytest.approx(6_400, rel=1e-12)


def test_pik_capitalises_into_principal() -> None:
    pik = loan(accrual="pik", compounding_frequency=2)
    after_one_year = pik.accrue(date(2026, 1, 1))
    assert after_one_year.compounding_periods == 2
    assert after_one_year.outstanding_principal == pytest.approx(1_081_600, rel=1e-12)
    after_two_years = pik.accrue(AS_OF)
    assert after_two_years.outstanding_principal == pytest.approx(1_169_858.56, rel=1e-12)
    for accrual in (after_one_year, after_two_years):
        assert accrual.accrued_interest == 0
        assert accrual.principal == 1_000_000
    assert pik.exit_claim(AS_OF).claim == after_two_years.outstanding_principal
    # Same growth as compounding at the same frequency; only the split differs.
    compound = loan(accrual="compound", compounding_frequency=2).accrue(AS_OF)
    assert compound.outstanding_amount == pytest.approx(after_two_years.outstanding_amount)
    assert compound.outstanding_principal == 1_000_000


def test_zero_elapsed_days_accrues_nothing() -> None:
    for instrument in (loan(), loan(accrual="pik", compounding_frequency=4)):
        accrual = instrument.accrue(ISSUE)
        assert accrual.days == 0
        assert accrual.outstanding_amount == 1_000_000


def test_venture_debt_claim_trace() -> None:
    claim = venture_loan().exit_claim(AS_OF)  # type: ignore[attr-defined]
    assert claim.accrual.accrued_interest == pytest.approx(400_000, rel=1e-12)
    assert claim.exit_fee == 60_000
    assert claim.claim == pytest.approx(2_460_000, rel=1e-12)
    assert "exit fee" in claim.basis


def test_note_maturity_repayment() -> None:
    due = note().repayment_at_maturity()
    assert due.as_of == NOTE_MATURITY
    assert due.days == 730
    assert due.outstanding_amount == pytest.approx(560_000, rel=1e-12)


# ---------------------------------------------------------------------------
# Time basis: no implicit clock, no silent partial periods
# ---------------------------------------------------------------------------


def test_debt_at_exit_requires_an_explicit_as_of() -> None:
    securities = (founders(), series_a(), loan())
    for exit_value in (0, 36_160_000):
        with pytest.raises(ValueError, match="explicit as_of"):
            solve_waterfall(securities, exit_value)
        with pytest.raises(ValueError, match="explicit as_of"):
            enumerate_equilibria(securities, exit_value)
    with pytest.raises(ValueError, match="explicit as_of"):
        ovf.CapTable(securities=list(securities)).waterfall(36_160_000)


def test_as_of_outside_the_accrual_window_is_refused() -> None:
    with pytest.raises(ValueError, match="before issue_date"):
        loan().accrue(date(2024, 12, 31))
    with pytest.raises(ValueError, match="after maturity_date"):
        note().accrue(date(2028, 1, 2))
    with pytest.raises(ValueError, match="after maturity_date"):
        solve_waterfall((founders(), note().resolved("repay")), 1e7, as_of=date(2028, 1, 2))


def test_as_of_must_be_a_date_not_a_datetime() -> None:
    with pytest.raises(ValueError, match="datetime.date"):
        loan().accrue(datetime(2027, 1, 1, 12, 0))
    with pytest.raises(ValueError, match="datetime.date"):
        loan().accrue("2027-01-01")  # type: ignore[arg-type]


def test_partial_compounding_period_is_refused() -> None:
    quarterly = loan(accrual="compound", compounding_frequency=4)
    with pytest.raises(ValueError, match="whole number"):
        quarterly.accrue(date(2025, 4, 1))  # 90 days is not a quarter of a 365-day year
    monthly_360 = loan(accrual="pik", compounding_frequency=12, day_count="actual/360")
    assert monthly_360.accrue(date(2025, 1, 31)).compounding_periods == 1  # 30 days
    with pytest.raises(ValueError, match="whole number"):
        monthly_360.accrue(date(2025, 2, 1))


def test_no_clock_is_read() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ovf"
    for path in (root / "instruments" / "debt.py", root / "waterfall.py"):
        source = path.read_text(encoding="utf-8")
        for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
            assert call not in source, f"{path.name} reads a clock via {call}"


# ---------------------------------------------------------------------------
# Absolute priority at exit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", DEBT_WATERFALL_FIXTURES, ids=lambda f: f.case_id)
def test_debt_fixture_allocation(fixture: DebtWaterfallFixture) -> None:
    report = solve_waterfall(fixture.securities, fixture.exit_valuation, as_of=fixture.as_of)
    actual = {p.security_id: p.amount for p in report.payouts}
    assert actual == pytest.approx(fixture.expected, abs=1e-6)
    assert math.fsum(actual.values()) == pytest.approx(fixture.exit_valuation, rel=1e-12)
    assert abs(report.conservation_error) <= report.tolerance
    assert all(p.amount >= 0 for p in report.payouts)
    assert report.converged and report.max_unilateral_gain <= report.tolerance
    assert report.as_of == fixture.as_of
    claims = {d.claim.security_id: d.claim.claim for d in report.debt_settlements}
    assert claims == pytest.approx(fixture.expected_claims, rel=1e-12)
    for d in report.debt_settlements:
        assert d.paid + d.shortfall == pytest.approx(d.claim.claim, rel=1e-12)
    converted = {p.security_id: p.converted for p in report.payouts if p.security_id == "series_a"}
    assert converted == fixture.expected_converted


@pytest.mark.parametrize("fixture", DEBT_WATERFALL_FIXTURES, ids=lambda f: f.case_id)
def test_debt_fixture_payoffs_are_equilibrium_unique(fixture: DebtWaterfallFixture) -> None:
    survey = enumerate_equilibria(fixture.securities, fixture.exit_valuation, as_of=fixture.as_of)
    assert survey.feasible_equilibria
    assert survey.payoff_unique
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


@pytest.mark.parametrize("case_id", ["D2", "D3", "D4"])
def test_uncovered_debt_leaves_every_equity_holder_exactly_zero(case_id: str) -> None:
    fixture = next(f for f in DEBT_WATERFALL_FIXTURES if f.case_id == case_id)
    report = solve_waterfall(fixture.securities, fixture.exit_valuation, as_of=fixture.as_of)
    for payout in report.payouts:
        if payout.security_id in EQUITY_IDS:
            assert payout.amount == 0.0
            assert payout.preference_payout == 0.0
            assert payout.residual_payout == 0.0


def test_junior_debt_tier_gets_nothing_until_the_senior_tier_is_whole() -> None:
    securities = (founders(), series_a(), loan(), note().resolved("repay"))
    report = solve_waterfall(securities, 1_000_000, as_of=AS_OF)
    paid = {p.security_id: p.amount for p in report.payouts}
    assert paid["loan"] == pytest.approx(1_000_000) and paid["note"] == 0.0


def test_debt_ranks_ahead_of_equity_whatever_the_seniority_integers() -> None:
    """Debt seniority 7 still pays before preferred seniority 0."""
    securities = (founders(), series_a(seniority=0), loan(seniority=7))
    report = solve_waterfall(securities, 1_000_000, as_of=AS_OF)
    paid = {p.security_id: p.amount for p in report.payouts}
    assert paid == pytest.approx({"common": 0, "series_a": 0, "loan": 1_000_000}, abs=1e-9)


def test_transaction_costs_come_off_before_debt() -> None:
    d1 = next(f for f in DEBT_WATERFALL_FIXTURES if f.case_id == "D1")
    report = solve_waterfall(d1.securities, 36_660_000, transaction_costs=500_000, as_of=AS_OF)
    assert report.net_exit == 36_160_000
    assert {p.security_id: p.amount for p in report.payouts} == pytest.approx(d1.expected, abs=1e-6)


def test_debt_is_a_pure_prefix_of_the_equity_waterfall() -> None:
    """D1's equity rows equal F1's exactly: debt changes the residual and nothing else."""
    f1 = next(f for f in FIXTURES if f.case_id == "F1")
    d1 = next(f for f in DEBT_WATERFALL_FIXTURES if f.case_id == "D1")
    plain = {p.security_id: p for p in solve_waterfall(f1.securities, 35_000_000).payouts}
    with_debt = {
        p.security_id: p
        for p in solve_waterfall(d1.securities, d1.exit_valuation, as_of=AS_OF).payouts
    }
    fields = ("amount", "preference_payout", "participation_payout", "residual_payout")
    for sid in EQUITY_IDS:
        for name in (*fields, "converted", "invested_capital", "effective_multiple"):
            assert getattr(with_debt[sid], name) == getattr(plain[sid], name), (sid, name)


def test_debt_payout_carries_no_equity_components() -> None:
    d5 = next(f for f in DEBT_WATERFALL_FIXTURES if f.case_id == "D5")
    report = solve_waterfall(d5.securities, d5.exit_valuation, as_of=AS_OF)
    lender = next(p for p in report.payouts if p.security_id == "venture_debt")
    assert lender.preference_payout == lender.participation_payout == lender.residual_payout == 0
    assert not lender.converted
    assert lender.invested_capital == 2_000_000
    assert lender.effective_multiple == pytest.approx(1.23, rel=1e-12)
    assert any("prepayment charges" in line for line in report.assumptions)


def test_debt_fingerprint_is_reproducible_and_pins_the_date() -> None:
    d1 = next(f for f in DEBT_WATERFALL_FIXTURES if f.case_id == "D1")
    first = solve_waterfall(d1.securities, d1.exit_valuation, as_of=AS_OF)
    again = solve_waterfall(d1.securities, d1.exit_valuation, as_of=AS_OF)
    later = solve_waterfall(d1.securities, d1.exit_valuation, as_of=date(2027, 1, 2))
    assert first.input_hash == again.input_hash
    assert first.input_hash != later.input_hash
    assert any("2027-01-01" in line for line in first.assumptions)


def test_debt_only_table_with_surplus_cash_is_refused() -> None:
    """Nothing is entitled to cash above the claim, so allocation cannot be verified."""
    with pytest.raises(ValueError, match="fully allocated"):
        solve_waterfall((loan(),), 2_000_000, as_of=AS_OF)
    report = solve_waterfall((loan(),), 1_000_000, as_of=AS_OF)
    assert report.payouts[0].amount == 1_000_000


# ---------------------------------------------------------------------------
# Convertible notes
# ---------------------------------------------------------------------------


def test_unresolved_note_is_rejected_at_exit_even_at_zero() -> None:
    securities = (founders(), series_a(), note())
    for exit_value in (0, 20_000_000):
        with pytest.raises(ValueError, match="no stated exit treatment"):
            solve_waterfall(securities, exit_value, as_of=AS_OF)
        with pytest.raises(ValueError, match="no stated exit treatment"):
            enumerate_equilibria(securities, exit_value, as_of=AS_OF)


def test_resolving_a_note_returns_a_new_snapshot() -> None:
    original = note()
    repaid = original.resolved("repay")
    assert original.exit_treatment is None
    assert repaid is not original and repaid.exit_treatment == "repay"
    assert repaid.exit_claim(AS_OF).claim == pytest.approx(530_000, rel=1e-12)
    multiple = original.resolved("multiple", exit_principal_multiple=2)
    assert multiple.exit_claim(AS_OF).claim == pytest.approx(1_030_000, rel=1e-12)
    assert multiple.exit_claim(AS_OF).basis == "2 x original principal + accrued interest"


@pytest.mark.parametrize("fixture", NOTE_CONVERSION_FIXTURES, ids=lambda f: f.case_id)
def test_qualified_financing_conversion(fixture: NoteConversionFixture) -> None:
    result = fixture.note_security.convert_at_financing(
        fixture.financing_date,
        new_money=fixture.new_money,
        round_price=fixture.round_price,
        capitalization_shares=fixture.capitalization_shares,
    )
    assert result.amount_converted == pytest.approx(fixture.expected_amount, rel=1e-12)
    assert result.cap_price == pytest.approx(fixture.expected_cap_price, rel=1e-12)
    assert result.discount_price == pytest.approx(fixture.expected_discount_price, rel=1e-12)
    assert result.conversion_price == pytest.approx(fixture.expected_price, rel=1e-12)
    assert result.binding == fixture.expected_binding
    assert result.shares == pytest.approx(fixture.expected_shares, rel=1e-12)


def test_conversion_inputs_are_not_guessed() -> None:
    with pytest.raises(ValueError, match="qualified financing threshold"):
        note().convert_at_financing(AS_OF, new_money=900_000, round_price=1.5)
    assert note().is_qualified_financing(1_000_000)
    with pytest.raises(ValueError, match="capitalization_shares"):
        note().convert_at_financing(AS_OF, new_money=3_000_000, round_price=1.5)
    with pytest.raises(ValueError, match="round_price"):
        note().convert_at_financing(
            AS_OF, new_money=3_000_000, round_price=0, capitalization_shares=8_000_000
        )
    uncapped = note(valuation_cap=None, discount_rate=0.0)
    plain = uncapped.convert_at_financing(AS_OF, new_money=3_000_000, round_price=1.25)
    assert plain.binding == "round_price" and plain.shares == pytest.approx(424_000)
    with pytest.raises(ValueError, match="only used with a valuation_cap"):
        uncapped.convert_at_financing(
            AS_OF, new_money=3_000_000, round_price=1.25, capitalization_shares=1
        )


# ---------------------------------------------------------------------------
# Shares and ownership
# ---------------------------------------------------------------------------


def test_debt_adds_no_shares_until_it_converts() -> None:
    table = ovf.CapTable(securities=[founders(), series_a(), loan(), note().resolved("repay")])
    assert table.fully_diluted_shares == 10_000_000
    ownership = table.ownership_breakdown()
    assert ownership["founders"] == pytest.approx(0.8)
    assert ownership["series_a"] == pytest.approx(0.2)
    assert ownership["bank"] == 0.0 and ownership["angel"] == 0.0

    conversion = note().convert_at_financing(
        AS_OF, new_money=3_000_000, round_price=1.50, capitalization_shares=8_000_000
    )
    converted = ovf.preferred(
        conversion.shares, conversion.conversion_price, holder_id="angel", security_id="note_pref"
    )
    after = ovf.CapTable(securities=[founders(), series_a(), loan(), converted])
    assert after.fully_diluted_shares == 10_530_000


def test_debt_is_not_a_liquidation_preference() -> None:
    with pytest.raises(TypeError, match="exit_claim"):
        loan().base_liquidation_preference()
    assert not loan().is_convertible() and note().is_convertible()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _loan_terms(**overrides: object) -> dict[str, object]:
    terms: dict[str, object] = {
        "security_id": "x",
        "holder_id": "bank",
        "principal": 1_000_000,
        "annual_rate": 0.08,
        "accrual": "simple",
        "day_count": ACT_365,
        "issue_date": ISSUE,
        "seniority": 0,
    }
    terms.update(overrides)
    return terms


@pytest.mark.parametrize(
    "overrides",
    [
        {"shares": 100},
        {"price": 1.0},
        {"principal": 0},
        {"annual_rate": -0.01},
        {"accrual": "compound"},
        {"accrual": "pik"},
        {"compounding_frequency": 4},
        {"accrual": "compound", "compounding_frequency": 0},
        {"accrual": "compound", "compounding_frequency": True},
        {"accrual": "compound", "compounding_frequency": 4.0},
        {"day_count": "30/360"},
        {"accrual": "continuous"},
        {"maturity_date": ISSUE},
        {"issue_date": datetime(2025, 1, 1, 9, 30)},
        {"unknown_term": 1},
    ],
    ids=lambda o: ",".join(o),
)
def test_invalid_debt_terms_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DebtInstrument.model_validate(_loan_terms(**overrides))


def test_required_debt_terms_have_no_defaults() -> None:
    for missing in ("accrual", "day_count", "issue_date", "seniority", "annual_rate"):
        terms = _loan_terms()
        del terms[missing]
        with pytest.raises(ValidationError):
            DebtInstrument.model_validate(terms)


def test_invalid_note_terms_are_rejected() -> None:
    base = {
        **_loan_terms(),
        "maturity_date": NOTE_MATURITY,
        "qualified_financing_threshold": 1_000_000,
    }
    assert ConvertibleNote.model_validate(base).exit_treatment is None
    for overrides in (
        {"maturity_date": None},
        {"qualified_financing_threshold": 0},
        {"exit_treatment": "multiple"},
        {"exit_treatment": "repay", "exit_principal_multiple": 2},
        {"exit_treatment": "multiple", "exit_principal_multiple": 0.5},
        {"exit_treatment": "convert"},
        {"discount_rate": 1.0},
        {"valuation_cap": 0},
        {
            "accrual": "pik",
            "compounding_frequency": 1,
            "exit_treatment": "multiple",
            "exit_principal_multiple": 2,
        },
    ):
        with pytest.raises(ValidationError):
            ConvertibleNote.model_validate({**base, **overrides})


def test_debt_is_immutable() -> None:
    instrument = loan()
    with pytest.raises(ValidationError):
        instrument.principal = 2_000_000  # type: ignore[misc]
    with pytest.raises(ValidationError):
        note().exit_treatment = "repay"  # type: ignore[assignment, misc]


def test_constructor_accepts_enum_members() -> None:
    by_enum = debt(
        1_000_000,
        0.08,
        accrual=AccrualMethod.SIMPLE,
        day_count=ACT_365,
        issue_date=ISSUE,
        seniority=0,
        security_id="loan",
        holder_id="bank",
        maturity_date=date(2030, 1, 1),
    )
    assert by_enum == loan()


# ---------------------------------------------------------------------------
# Regression: a table without debt is unchanged
# ---------------------------------------------------------------------------

PRE_DEBT_ASSUMPTIONS = [
    "Each preferred position makes an independent conversion decision.",
    "Reserved unallocated option capacity has no exit payment entitlement.",
    "Single base currency; float accounting within reported tolerance.",
    "No debt, unexercised option settlement, SAFE liquidity events or class voting.",
]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.case_id)
def test_existing_fixtures_are_unchanged_without_debt(fixture: WaterfallFixture) -> None:
    """The hand-derived F-fixtures still hold, and an unused as_of changes nothing."""
    plain = solve_waterfall(fixture.securities, fixture.exit_valuation)
    dated = solve_waterfall(fixture.securities, fixture.exit_valuation, as_of=AS_OF)
    actual = {p.security_id: p.amount for p in plain.payouts}
    assert actual == pytest.approx(fixture.expected, abs=1e-6)
    assert [p.model_dump() for p in dated.payouts] == [p.model_dump() for p in plain.payouts]
    assert dated.input_hash == plain.input_hash
    assert plain.assumptions == PRE_DEBT_ASSUMPTIONS
    assert plain.as_of is None and dated.as_of is None
    assert plain.debt_settlements == [] and dated.debt_settlements == []


def test_no_debt_fingerprint_format_is_unchanged() -> None:
    """The input hash of a debt-free table is still SHA-256 of the pre-debt payload."""
    f1 = next(f for f in FIXTURES if f.case_id == "F1")
    report = solve_waterfall(f1.securities, f1.exit_valuation)
    payload = {
        "securities": [{"kind": type(s).__name__, **s.model_dump()} for s in f1.securities],
        "exit_valuation": f1.exit_valuation,
        "transaction_costs": 0.0,
        "max_iterations": 20,
        "atol": 1e-8,
        "rtol": 1e-12,
    }
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
    assert report.input_hash == expected.hexdigest()
    assert report.engine_version == "waterfall-v3"
