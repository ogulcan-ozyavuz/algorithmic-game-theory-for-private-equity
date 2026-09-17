"""NVCA model-charter presets, asserted against hand derivations in `docs/presets.md`.

The fixtures live in this file. Every expected number is derived by hand in
`docs/presets.md` (cases P1-P10) and was rechecked there with exact rational arithmetic;
none was copied from engine output. `reviewed_by` stays empty until an external specialist
confirms the term mapping and the arithmetic.

Shared equity, as in `docs/fixtures.md`: founders hold 8,000,000 common. Series A holds
2,000,000 preferred at a $2.50 Original Issue Price, $5,000,000 invested, 20% as
converted. Accruing dividends start on 2025-01-01 and are measured on 2027-01-01, 730 days,
2.0 years under Actual/365 Fixed.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import ovf
from ovf.antidilution import BROAD_BASED_NVCA
from ovf.contracts.securities import CumulativeDividend, NonCumulativeDividend
from ovf.financing import ExemptionDetermination, NewIssue, apply_dilutive_issuance
from ovf.presets import (
    ENGINE_VERSION,
    NVCA_MODEL_COI,
    SERIES_A_SENIORITY,
    AntiDilutionFullRatchet,
    DividendAccruing,
    DividendNonCumulative,
    Participating,
    PresetPosition,
    additional_series,
    anti_dilution_broad_based_weighted_average,
    anti_dilution_full_ratchet,
    anti_dilution_none,
    anti_dilution_terms,
    dividend_accruing,
    dividend_as_converted_only,
    dividend_non_cumulative,
    non_participating,
    nvca_series_a,
    participating,
)

MILLION = 1_000_000
ACCRUES_FROM = date(2025, 1, 1)
AS_OF = date(2027, 1, 1)  # 730 days = 2.0 years under Actual/365 Fixed
FOUNDERS = ovf.common(8_000_000, holder_id="founders", security_id="common")


def series_a(
    *,
    liquidation_multiple: float = 1.0,
    participation: object = None,
    dividend: object = None,
    anti_dilution: object = None,
) -> PresetPosition:
    """Test helper: Series A with P1's choices unless one is overridden.

    The helper has defaults so each fixture can differ from P1 in exactly one bracket. The
    preset it calls has none.
    """
    return nvca_series_a(
        shares=2_000_000,
        original_issue_price=2.50,
        liquidation_multiple=liquidation_multiple,
        participation=participation if participation is not None else non_participating(),
        dividend=dividend if dividend is not None else dividend_as_converted_only(),
        anti_dilution=anti_dilution
        if anti_dilution is not None
        else anti_dilution_broad_based_weighted_average(),
        holder_id="series_a",
        security_id="series_a",
    )


def accruing(accrual: str = "simple", frequency: int | None = None) -> DividendAccruing:
    return dividend_accruing(
        rate=0.08,
        accrual=accrual,  # type: ignore[arg-type]
        compounding_frequency=frequency,
        day_count="actual/365_fixed",
        accrues_from=ACCRUES_FROM,
        payable_on_liquidation=True,
    )


P1 = series_a()
P2 = series_a(participation=participating(maximum_participation_multiple=None))
P3 = series_a(participation=participating(maximum_participation_multiple=2.0))
P4 = series_a(dividend=accruing())
P5 = series_a(dividend=accruing("compound", 1))
P6 = series_a(dividend=dividend_non_cumulative(rate=0.08))
P7 = series_a(participation=participating(maximum_participation_multiple=2.0), dividend=accruing())
P8 = series_a(liquidation_multiple=2.0)


@dataclass(frozen=True)
class PresetExitFixture:
    case_id: str
    description: str
    position: PresetPosition
    exit_valuation: float
    as_of: date | None
    expected: dict[str, float]
    series_a_converts: bool
    reviewed_by: tuple[str, ...] = field(default=())


EXIT_FIXTURES: tuple[PresetExitFixture, ...] = (
    PresetExitFixture(
        "P1a",
        "1x non-participating, holds",
        P1,
        15 * MILLION,
        None,
        {"common": 10 * MILLION, "series_a": 5 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P1b",
        "1x non-participating, converts",
        P1,
        35 * MILLION,
        None,
        {"common": 28 * MILLION, "series_a": 7 * MILLION},
        True,
    ),
    PresetExitFixture(
        "P1c",
        "P1 at P4's exit",
        P1,
        27 * MILLION,
        None,
        {"common": 21_600_000, "series_a": 5_400_000},
        True,
    ),
    PresetExitFixture(
        "P1d",
        "P1 at P8's exit",
        P1,
        30 * MILLION,
        None,
        {"common": 24 * MILLION, "series_a": 6 * MILLION},
        True,
    ),
    PresetExitFixture(
        "P2a",
        "participating, uncapped",
        P2,
        15 * MILLION,
        None,
        {"common": 8 * MILLION, "series_a": 7 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P2b",
        "participating, uncapped",
        P2,
        35 * MILLION,
        None,
        {"common": 24 * MILLION, "series_a": 11 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P3a",
        "fn 20 cap of 2x binds",
        P3,
        40 * MILLION,
        None,
        {"common": 30 * MILLION, "series_a": 10 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P3b",
        "fn 20 cap makes conversion better",
        P3,
        60 * MILLION,
        None,
        {"common": 48 * MILLION, "series_a": 12 * MILLION},
        True,
    ),
    PresetExitFixture(
        "P3c",
        "capped participation below the cap",
        P3,
        20 * MILLION,
        None,
        {"common": 12 * MILLION, "series_a": 8 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P4",
        "accruing, simple",
        P4,
        27 * MILLION,
        AS_OF,
        {"common": 21_200_000, "series_a": 5_800_000},
        False,
    ),
    PresetExitFixture(
        "P5",
        "accruing, compounded annually (fn 13)",
        P5,
        27 * MILLION,
        AS_OF,
        {"common": 21_168_000, "series_a": 5_832_000},
        False,
    ),
    PresetExitFixture(
        "P6",
        "non-cumulative: no exit effect",
        P6,
        15 * MILLION,
        None,
        {"common": 10 * MILLION, "series_a": 5 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P7a",
        "capped participation with accruing dividends",
        P7,
        40 * MILLION,
        AS_OF,
        {"common": 30 * MILLION, "series_a": 10 * MILLION},
        False,
    ),
    PresetExitFixture(
        "P7b",
        "capped participation with accruing dividends",
        P7,
        20 * MILLION,
        AS_OF,
        {"common": 11_360_000, "series_a": 8_640_000},
        False,
    ),
    PresetExitFixture(
        "P8",
        "2x non-participating",
        P8,
        30 * MILLION,
        None,
        {"common": 20 * MILLION, "series_a": 10 * MILLION},
        False,
    ),
)


def _fixture(case_id: str) -> PresetExitFixture:
    return next(f for f in EXIT_FIXTURES if f.case_id == case_id)


def _run(fixture: PresetExitFixture) -> ovf.WaterfallResult:
    table = ovf.CapTable(securities=[FOUNDERS, fixture.position.security])
    return table.waterfall_detailed(fixture.exit_valuation, as_of=fixture.as_of)


def _payouts(result: ovf.WaterfallResult) -> dict[str, float]:
    return {p.security_id: p.amount for p in result.payouts}


# --- Exits through the existing waterfall ---------------------------------------------


@pytest.mark.parametrize("fixture", EXIT_FIXTURES, ids=lambda f: f.case_id)
def test_preset_exit_payouts(fixture: PresetExitFixture) -> None:
    result = _run(fixture)
    assert _payouts(result) == pytest.approx(fixture.expected, abs=1e-6)
    assert sum(_payouts(result).values()) == pytest.approx(fixture.exit_valuation)
    converted = {p.security_id: p.converted for p in result.payouts}["series_a"]
    assert converted is fixture.series_a_converts


@pytest.mark.parametrize("fixture", EXIT_FIXTURES, ids=lambda f: f.case_id)
def test_preset_exit_payoffs_are_equilibrium_unique(fixture: PresetExitFixture) -> None:
    survey = ovf.enumerate_equilibria(
        [FOUNDERS, fixture.position.security], fixture.exit_valuation, as_of=fixture.as_of
    )
    assert survey.feasible_equilibria
    assert survey.payoff_unique
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


# --- One bracket apart, the same exit, two different numbers ---------------------------


@pytest.mark.parametrize(
    ("left", "right", "bracket", "series_a_difference"),
    [
        ("P1a", "P2a", "participation (s.2.1-2.2 alternatives)", 2 * MILLION),
        ("P1c", "P4", "dividend (s.1 alternative 1 vs 3)", 400_000),
        ("P4", "P5", "accrual (s.1 operative text vs fn 13 variant)", 32_000),
        ("P1d", "P8", "liquidation multiple (s.2.1 '[__ times]')", 4 * MILLION),
        ("P3c", "P7b", "dividend with a fn 20 cap", 640_000),
    ],
)
def test_one_bracket_changes_the_payout(
    left: str, right: str, bracket: str, series_a_difference: float
) -> None:
    """Two presets that differ in one required choice, the same exit, two derived numbers."""
    a, b = _fixture(left), _fixture(right)
    assert a.exit_valuation == b.exit_valuation, bracket
    paid_a = _payouts(_run(a))["series_a"]
    paid_b = _payouts(_run(b))["series_a"]
    assert paid_b - paid_a == pytest.approx(series_a_difference, abs=1e-6), bracket
    assert paid_a == pytest.approx(a.expected["series_a"], abs=1e-6)
    assert paid_b == pytest.approx(b.expected["series_a"], abs=1e-6)


def test_non_cumulative_alternative_pays_what_no_dividend_pays() -> None:
    """P6 = P1 at $15M; the non-cumulative Dividend Amount accrues nothing (s.1 alt. 2)."""
    plain, non_cumulative = _run(_fixture("P1a")), _run(_fixture("P6"))
    assert _payouts(plain) == pytest.approx(_payouts(non_cumulative), abs=1e-6)
    assert any("Non-cumulative dividends accrue nothing" in a for a in non_cumulative.assumptions)
    assert non_cumulative.as_of is None


def test_cap_includes_accruing_dividends_as_fn20_states() -> None:
    """P7: the preset states the fn 20 basis, and the waterfall reports it as stated."""
    dividend = P7.security.dividend
    assert isinstance(dividend, CumulativeDividend)
    assert dividend.participation_cap_basis == "includes_dividends"
    result = _run(_fixture("P7a"))
    assert (
        "series_a: the participation cap includes accrued dividends (stated; NVCA Model COI "
        "fn 20)." in result.assumptions
    )


# --- The position each preset builds --------------------------------------------------


@pytest.mark.parametrize(
    ("position", "multiple", "is_participating", "cap"),
    [
        (P1, 1.0, False, None),
        (P2, 1.0, True, None),
        (P3, 1.0, True, 2.0),
        (P8, 2.0, False, None),
    ],
)
def test_preset_position_fields(
    position: PresetPosition, multiple: float, is_participating: bool, cap: float | None
) -> None:
    security = position.security
    assert isinstance(security, ovf.PreferredStock)
    assert security.security_id == "series_a" and security.holder_id == "series_a"
    assert security.shares == 2_000_000
    assert security.price == 2.50
    assert security.invested_capital == 5_000_000
    assert security.seniority == SERIES_A_SENIORITY == 1
    assert security.liquidation_multiple == multiple
    assert security.participating is is_participating
    assert security.participation_cap == cap
    assert security.conversion_ratio == 1.0
    assert security.dividend is None
    assert position.anti_dilution.method == "weighted_average"
    assert position.anti_dilution.definition == BROAD_BASED_NVCA
    assert position.series == "Series A Preferred Stock"
    assert position.series_in_model is True
    assert position.document == NVCA_MODEL_COI
    assert position.engine_version == ENGINE_VERSION == "presets-v1"


def test_accruing_dividend_fields() -> None:
    for position, accrual, frequency in ((P4, "simple", None), (P5, "compound", 1)):
        dividend = position.security.dividend
        assert isinstance(dividend, CumulativeDividend)
        assert dividend.annual_rate == 0.08
        assert dividend.accrual == accrual
        assert dividend.compounding_frequency == frequency
        assert dividend.day_count == "actual/365_fixed"
        assert dividend.accrues_from == ACCRUES_FROM
        assert dividend.settlement == "forfeit_on_conversion"
        assert dividend.participation_cap_basis is None  # uncapped: the basis does not apply
    # P4's preference on 2027-01-01: $5,000,000 + $800,000.
    assert P4.security.liquidation_preference(AS_OF) == pytest.approx(5_800_000, abs=1e-6)
    assert P5.security.liquidation_preference(AS_OF) == pytest.approx(5_832_000, abs=1e-6)
    assert P4.term("accruing_dividends_on_conversion").origin == "model_text"
    assert P4.term("accruing_dividends_on_conversion").value == "forfeited"


def test_non_cumulative_dividend_fields() -> None:
    dividend = P6.security.dividend
    assert isinstance(dividend, NonCumulativeDividend)
    assert dividend.annual_rate == 0.08
    assert P6.term("dividend_amount").origin == "caller"


def test_accruing_preset_needs_an_explicit_as_of() -> None:
    table = ovf.CapTable(securities=[FOUNDERS, P4.security])
    with pytest.raises(ValueError, match="No implicit clock"):
        table.waterfall_detailed(27 * MILLION)


# --- Anti-dilution: P9, applied through ovf.financing and then an exit ----------------

DOWN_ROUND = NewIssue(
    securities=(
        ovf.common(4_000_000, holder_id="new_investor", security_id="new_common", price=1.25),
    ),
    aggregate_consideration=5_000_000,
)
NOT_EXEMPT = ExemptionDetermination(exempted=False, basis="cash sale of common stock")


@pytest.mark.parametrize(
    ("anti_dilution", "method", "ratio", "expected"),
    [
        (
            anti_dilution_broad_based_weighted_average(),
            "weighted_average",
            7 / 6,
            {"common": 24 * MILLION, "series_a": 7 * MILLION, "new_common": 12 * MILLION},
        ),
        (
            anti_dilution_full_ratchet(end_date=None),
            "full_ratchet",
            2.0,
            {"common": 21_500_000, "series_a": 10_750_000, "new_common": 10_750_000},
        ),
        (
            anti_dilution_none(),
            "none",
            1.0,
            {
                "common": 172 * MILLION / 7,
                "series_a": 43 * MILLION / 7,
                "new_common": 86 * MILLION / 7,
            },
        ),
    ],
    ids=["P9a-broad", "P9b-ratchet", "P9c-none"],
)
def test_p9_anti_dilution_choice_through_a_down_round_and_an_exit(
    anti_dilution: object, method: str, ratio: float, expected: dict[str, float]
) -> None:
    position = series_a(anti_dilution=anti_dilution)
    assert position.anti_dilution.method == method
    financed = apply_dilutive_issuance(
        ovf.CapTable(securities=[FOUNDERS, position.security]),
        issue=DOWN_ROUND,
        protection=anti_dilution_terms(position),
        exemption=NOT_EXEMPT,
    )
    adjusted = next(s for s in financed.table.securities if s.security_id == "series_a")
    assert isinstance(adjusted, ovf.PreferredStock)
    assert adjusted.conversion_ratio == pytest.approx(ratio, rel=1e-12)
    result = financed.table.waterfall_detailed(43 * MILLION)
    assert _payouts(result) == pytest.approx(expected, abs=1e-6)
    assert all(p.converted for p in result.payouts if p.security_id == "series_a")


# --- A further series: P10, rank is the one choice that differs -----------------------


def series_b(rank: str, relative_to: PresetPosition = P1) -> PresetPosition:
    return additional_series(
        series="Series B Preferred Stock",
        rank=rank,  # type: ignore[arg-type]
        relative_to=relative_to,
        shares=1_500_000,
        original_issue_price=6.00,
        liquidation_multiple=1.0,
        participation=non_participating(),
        dividend=dividend_as_converted_only(),
        anti_dilution=anti_dilution_broad_based_weighted_average(),
        holder_id="series_b",
        security_id="series_b",
    )


@pytest.mark.parametrize(
    ("rank", "seniority", "expected"),
    [
        (
            "pari_passu",
            1,
            {"common": 0.0, "series_a": 25 * MILLION / 7, "series_b": 45 * MILLION / 7},
        ),
        ("senior", 0, {"common": 0.0, "series_a": 1 * MILLION, "series_b": 9 * MILLION}),
        ("junior", 2, {"common": 0.0, "series_a": 5 * MILLION, "series_b": 5 * MILLION}),
    ],
    ids=["P10a-pari-passu", "P10b-senior", "P10c-junior"],
)
def test_p10_rank_decides_a_downside_exit(
    rank: str, seniority: int, expected: dict[str, float]
) -> None:
    b = series_b(rank)
    assert b.security.seniority == seniority
    assert b.security.invested_capital == 9 * MILLION
    table = ovf.CapTable(securities=[FOUNDERS, P1.security, b.security])
    result = table.waterfall_detailed(10 * MILLION)
    assert _payouts(result) == pytest.approx(expected, abs=1e-6)
    assert not any(p.converted for p in result.payouts)
    survey = ovf.enumerate_equilibria(table.securities, 10 * MILLION)
    assert survey.payoff_unique and survey.feasible_equilibria


def test_p10_pari_passu_and_senior_differ_by_the_derived_amount() -> None:
    """Series A: $25M/7 pari passu against $1M junior to a senior Series B."""
    pari = _payouts(
        ovf.CapTable(
            securities=[FOUNDERS, P1.security, series_b("pari_passu").security]
        ).waterfall_detailed(10 * MILLION)
    )
    senior = _payouts(
        ovf.CapTable(
            securities=[FOUNDERS, P1.security, series_b("senior").security]
        ).waterfall_detailed(10 * MILLION)
    )
    assert pari["series_a"] - senior["series_a"] == pytest.approx(18 * MILLION / 7, abs=1e-6)


def test_additional_series_is_marked_outside_the_model() -> None:
    pari, senior = series_b("pari_passu"), series_b("senior")
    for position in (pari, senior):
        assert position.preset == "additional_series"
        assert position.series_in_model is False
        assert position.term("series").within_model is False
        assert position.term("series").origin == "caller"
    assert pari.term("rank").within_model is True
    assert senior.term("rank").within_model is False
    assert "fn 16" in senior.term("rank").source
    assert series_b("junior").term("rank").within_model is False


# --- Provenance -----------------------------------------------------------------------

CALLER_TERMS = {
    "original_issue_price",
    "shares",
    "liquidation_multiple",
    "participation",
    "dividend",
    "anti_dilution",
}
MODEL_TERMS = {
    "series",
    "ranking_among_preferred",
    "ranking_against_common",
    "shortfall_within_rank",
    "conversion_ratio",
    "conversion_election",
    "anti_dilution_definition_of_a",
}


def test_series_a_terms_record_their_origin() -> None:
    origins = {r.term: r.origin for r in P1.terms}
    assert {t for t, o in origins.items() if o == "caller"} == CALLER_TERMS
    assert {t for t, o in origins.items() if o == "model_text"} == MODEL_TERMS
    assert all(r.within_model for r in P1.terms)
    assert all(r.wording and r.source for r in P1.terms)
    assert P1.term("original_issue_price").value == "2.5 per share"
    assert P1.term("liquidation_multiple").value == "1.0x the Original Issue Price"
    assert P1.term("dividend").value == "as_converted_only"
    with pytest.raises(KeyError):
        P1.term("pay_to_play")


def test_capped_participation_records_the_fn20_amount_and_basis() -> None:
    cap = P3.term("maximum_participation_amount")
    assert cap.origin == "caller"
    assert cap.value == "2.0x the Original Issue Price = 5.0 per share"
    assert "fn 20" in cap.source
    assert P3.term("participation_cap_basis").origin == "model_text"
    assert P2.term("maximum_participation_amount").value == "none (no fn 20 cap)"
    with pytest.raises(KeyError):
        P2.term("participation_cap_basis")


def test_no_anti_dilution_is_a_term_sheet_alternative_outside_the_charter() -> None:
    record = series_a(anti_dilution=anti_dilution_none()).term("anti_dilution")
    assert record.within_model is False
    assert "Term Sheet" in record.source


def test_unrepresented_brackets_are_listed() -> None:
    listed = " ".join(P1.not_represented)
    for provision in ("s.5A", "pay-to-play", "s.3.3", "s.6 Redemption", "s.2.3.4", "s.4.2"):
        assert provision in listed


def test_input_hash_is_stable_and_follows_each_bracket() -> None:
    assert P1.input_hash == series_a().input_hash
    hashes = {p.input_hash for p in (P1, P2, P3, P4, P5, P6, P7, P8)}
    assert len(hashes) == 8
    assert len(P1.input_hash) == 64


# --- No defaults, explicit refusals ---------------------------------------------------


@pytest.mark.parametrize(
    "function",
    [
        nvca_series_a,
        additional_series,
        participating,
        dividend_non_cumulative,
        dividend_accruing,
        anti_dilution_full_ratchet,
        anti_dilution_terms,
    ],
)
def test_public_functions_have_no_default_arguments(function: object) -> None:
    assert callable(function)
    for parameter in inspect.signature(function).parameters.values():
        assert parameter.default is inspect.Parameter.empty, parameter.name


@pytest.mark.parametrize(
    "model", [Participating, DividendNonCumulative, DividendAccruing, AntiDilutionFullRatchet]
)
def test_choices_have_no_default_fields(model: type) -> None:
    for name, info in model.model_fields.items():  # type: ignore[attr-defined]
        assert info.is_required(), name


@pytest.mark.parametrize(
    "missing", ["liquidation_multiple", "participation", "dividend", "anti_dilution"]
)
def test_a_preset_cannot_be_built_without_each_bracket(missing: str) -> None:
    arguments = {
        "shares": 2_000_000,
        "original_issue_price": 2.50,
        "liquidation_multiple": 1.0,
        "participation": non_participating(),
        "dividend": dividend_as_converted_only(),
        "anti_dilution": anti_dilution_broad_based_weighted_average(),
        "holder_id": "series_a",
        "security_id": "series_a",
    }
    del arguments[missing]
    with pytest.raises(TypeError, match=missing):
        nvca_series_a(**arguments)  # type: ignore[arg-type]


def test_accruing_dividends_outside_the_liquidation_amount_are_refused() -> None:
    with pytest.raises(ValueError, match="payable_on_liquidation=False is not supported"):
        dividend_accruing(
            rate=0.08,
            accrual="simple",
            compounding_frequency=None,
            day_count="actual/365_fixed",
            accrues_from=ACCRUES_FROM,
            payable_on_liquidation=False,
        )


@pytest.mark.parametrize(
    ("accrual", "frequency", "message"),
    [("simple", 1, "compounding_frequency=None"), ("compound", None, "needs a compounding")],
)
def test_accrual_and_frequency_must_agree(
    accrual: str, frequency: int | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        accruing(accrual, frequency)


def test_accruing_dividend_input_is_checked() -> None:
    base = {
        "rate": 0.08,
        "accrual": "simple",
        "compounding_frequency": None,
        "day_count": "actual/365_fixed",
        "accrues_from": ACCRUES_FROM,
        "payable_on_liquidation": True,
    }
    for bad in (
        {"accrues_from": datetime(2025, 1, 1, 12, 0)},
        {"rate": 0.0},
        {"rate": 1.5},
        {"rate": True},
        {"day_count": "30/360"},
        {"payable_on_liquidation": 1},
        {"accrual": "compound", "compounding_frequency": True},
    ):
        with pytest.raises(ValueError):
            dividend_accruing(**{**base, **bad})  # type: ignore[arg-type]


def test_full_ratchet_end_date_is_refused() -> None:
    with pytest.raises(ValueError, match="end date"):
        anti_dilution_full_ratchet(end_date=date(2028, 1, 1))


def test_cap_below_the_multiple_is_refused() -> None:
    with pytest.raises(ValueError, match="below liquidation_multiple"):
        series_a(
            liquidation_multiple=2.0,
            participation=participating(maximum_participation_multiple=1.5),
        )


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), True])
def test_bad_cap_is_refused(bad: float) -> None:
    with pytest.raises(ValidationError):
        participating(maximum_participation_multiple=bad)


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("shares", 0),
        ("shares", -1.0),
        ("shares", True),
        ("original_issue_price", float("nan")),
        ("original_issue_price", "2.50"),
        ("liquidation_multiple", 0.0),
        ("liquidation_multiple", float("inf")),
    ],
)
def test_bad_numbers_are_refused(name: str, bad: object) -> None:
    arguments = {"shares": 2_000_000, "original_issue_price": 2.50, "liquidation_multiple": 1.0}
    arguments[name] = bad  # type: ignore[assignment]
    with pytest.raises(ValueError, match=name):
        nvca_series_a(
            **arguments,  # type: ignore[arg-type]
            participation=non_participating(),
            dividend=dividend_as_converted_only(),
            anti_dilution=anti_dilution_broad_based_weighted_average(),
            holder_id="series_a",
            security_id="series_a",
        )


@pytest.mark.parametrize(
    ("argument", "bad"),
    [
        ("participation", "participating"),
        ("participation", True),
        ("dividend", None),
        ("dividend", 0.08),
        ("anti_dilution", "broad"),
        ("anti_dilution", BROAD_BASED_NVCA),
    ],
)
def test_choices_must_be_built_with_their_constructors(argument: str, bad: object) -> None:
    arguments: dict[str, object] = {
        "participation": non_participating(),
        "dividend": dividend_as_converted_only(),
        "anti_dilution": anti_dilution_broad_based_weighted_average(),
    }
    arguments[argument] = bad
    with pytest.raises(ValueError, match=f"{argument} must be built with"):
        nvca_series_a(
            shares=2_000_000,
            original_issue_price=2.50,
            liquidation_multiple=1.0,
            holder_id="series_a",
            security_id="series_a",
            **arguments,  # type: ignore[arg-type]
        )


def test_empty_identifiers_are_refused() -> None:
    with pytest.raises(ValueError, match="security_id"):
        nvca_series_a(
            shares=2_000_000,
            original_issue_price=2.50,
            liquidation_multiple=1.0,
            participation=non_participating(),
            dividend=dividend_as_converted_only(),
            anti_dilution=anti_dilution_broad_based_weighted_average(),
            holder_id="series_a",
            security_id="",
        )


def test_additional_series_refusals() -> None:
    with pytest.raises(ValueError, match="rank must be"):
        series_b("equal")
    with pytest.raises(ValueError, match="relative_to must be"):
        series_b("senior", relative_to="series_a")  # type: ignore[arg-type]
    top = series_b("senior")
    assert top.security.seniority == 0
    with pytest.raises(ValueError, match="seniority 0"):
        additional_series(
            series="Series C Preferred Stock",
            rank="senior",
            relative_to=top.security,
            shares=1,
            original_issue_price=1.0,
            liquidation_multiple=1.0,
            participation=non_participating(),
            dividend=dividend_as_converted_only(),
            anti_dilution=anti_dilution_none(),
            holder_id="series_c",
            security_id="series_c",
        )
    with pytest.raises(ValueError, match="already used"):
        additional_series(
            series="Series B Preferred Stock",
            rank="pari_passu",
            relative_to=P1,
            shares=1,
            original_issue_price=1.0,
            liquidation_multiple=1.0,
            participation=non_participating(),
            dividend=dividend_as_converted_only(),
            anti_dilution=anti_dilution_none(),
            holder_id="series_b",
            security_id="series_a",
        )


def test_anti_dilution_terms_refusals() -> None:
    assert anti_dilution_terms(P1, series_b("senior")) == {
        "series_a": P1.anti_dilution,
        "series_b": series_b("senior").anti_dilution,
    }
    with pytest.raises(ValueError, match="Duplicate security_id"):
        anti_dilution_terms(P1, P2)
    with pytest.raises(ValueError, match="expected a PresetPosition"):
        anti_dilution_terms(P1.security)  # type: ignore[arg-type]


def test_positions_are_immutable() -> None:
    with pytest.raises(ValidationError):
        P1.series = "Series B"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        P1.security.liquidation_multiple = 3.0  # type: ignore[misc]


def test_no_clock_is_read() -> None:
    path = Path(__file__).resolve().parents[1] / "src" / "ovf" / "presets.py"
    source = path.read_text(encoding="utf-8")
    for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
        assert call not in source, f"presets.py reads a clock via {call}"
