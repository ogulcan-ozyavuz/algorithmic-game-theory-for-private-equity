"""Financing fixtures and invariants, asserted against `ovf.financing`.

Every expected number comes from `tests/financing_fixtures.py`, whose derivations are
written out in `docs/financing.md`.
"""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

import ovf
from ovf.antidilution import BROAD_BASED_NVCA, CapitalizationBeforeIssue
from ovf.financing import (
    ENGINE_VERSION,
    FULL_RATCHET,
    UNPROTECTED,
    AntiDilutionProtection,
    ExemptionDetermination,
    FinancingResult,
    NewIssue,
    adjust_position,
    apply_dilutive_issuance,
    capitalization_before_issue,
    weighted_average_protection,
)
from ovf.instruments import convertible_note, debt
from tests.financing_fixtures import (
    ACQUISITION,
    ACQUISITION_EXEMPT,
    BROAD,
    COMMON,
    DOWN_ROUND,
    EXIT_FIXTURES,
    FINANCING_FIXTURES,
    NAIVE_A_THEN_SEED,
    NAIVE_SEED_THEN_A,
    NOT_EXEMPT,
    OPTIONS,
    PREFERRED_AS_CONVERTED,
    RESERVE,
    SEED,
    SERIES_A,
    TABLE,
    ExitAfterFinancingFixture,
    FinancingFixture,
    series_b,
)

FOUNDERS_ONLY = ovf.common(8_000_000, holder_id="founders", security_id="common")


def _by_id(case_id: str) -> FinancingFixture:
    return next(f for f in FINANCING_FIXTURES if f.case_id == case_id)


def _run(fixture: FinancingFixture) -> FinancingResult:
    return apply_dilutive_issuance(
        ovf.CapTable(securities=list(fixture.table)),
        issue=fixture.issue,
        protection=fixture.protection,
        exemption=fixture.exemption,
    )


def _ratios(table: ovf.CapTable) -> dict[str, float]:
    return {
        s.security_id: s.conversion_ratio
        for s in table.securities
        if isinstance(s, ovf.PreferredStock)
    }


# --- Named fixtures -----------------------------------------------------------------


@pytest.mark.parametrize("fixture", FINANCING_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_outcomes_prices_and_ratios(fixture: FinancingFixture) -> None:
    result = _run(fixture)
    assert {p.security_id: p.outcome for p in result.positions} == fixture.expected_outcomes
    prices = {p.security_id: p.conversion_price_after for p in result.positions}
    assert prices == pytest.approx(fixture.expected_conversion_prices, rel=1e-12)
    assert _ratios(result.table) == pytest.approx(fixture.expected_ratios, rel=1e-12)
    assert result.table.fully_diluted_shares == pytest.approx(
        fixture.expected_fully_diluted, rel=1e-12
    )


@pytest.mark.parametrize("fixture", FINANCING_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_changes_only_conversion_ratios(fixture: FinancingFixture) -> None:
    """Every other term of every pre-existing position is carried over unchanged."""
    result = _run(fixture)
    before = {s.security_id: s for s in fixture.table}
    after = {s.security_id: s for s in result.table.securities}
    assert list(after) == [*before, *result.issued_security_ids]
    for security_id, old in before.items():
        new = after[security_id]
        assert type(new) is type(old)
        unchanged = {k: v for k, v in old.model_dump().items() if k != "conversion_ratio"}
        assert {k: v for k, v in new.model_dump().items() if k != "conversion_ratio"} == unchanged
        assert new.base_liquidation_preference() == old.base_liquidation_preference()
    for issued in fixture.issue.securities:
        assert after[issued.security_id] is issued


@pytest.mark.parametrize("fixture", FINANCING_FIXTURES, ids=lambda f: f.case_id)
def test_positions_not_adjusted_are_the_same_objects(fixture: FinancingFixture) -> None:
    """No new state for a position the issuance did not adjust."""
    result = _run(fixture)
    by_id = {s.security_id: s for s in fixture.table}
    for record in result.positions:
        if record.outcome == "adjusted":
            assert record.position_after is not by_id[record.security_id]
            assert record.conversion_ratio_after > record.conversion_ratio_before
        else:
            assert record.position_after is by_id[record.security_id]
            assert record.conversion_price_after == record.conversion_price_before
    for s in result.table.securities:
        if not isinstance(s, ovf.PreferredStock) and s.security_id in by_id:
            assert s is by_id[s.security_id]


@pytest.mark.parametrize("fixture", FINANCING_FIXTURES, ids=lambda f: f.case_id)
def test_input_table_is_not_modified(fixture: FinancingFixture) -> None:
    table = ovf.CapTable(securities=list(fixture.table))
    snapshot = [s.model_dump() for s in table.securities]
    result = apply_dilutive_issuance(
        table, issue=fixture.issue, protection=fixture.protection, exemption=fixture.exemption
    )
    assert result.table is not table
    assert [s.model_dump() for s in table.securities] == snapshot
    assert all(a is b for a, b in zip(table.securities, fixture.table, strict=True))


def test_capitalization_is_counted_from_the_table() -> None:
    cap = capitalization_before_issue(ovf.CapTable(securities=list(TABLE)))
    assert cap == CapitalizationBeforeIssue(
        common_outstanding=COMMON,
        preferred_as_converted=PREFERRED_AS_CONVERTED,
        options_and_warrants_as_exercised=OPTIONS,
        other_convertibles_as_converted=0,
        reserved_unissued_pool=RESERVE,
    )


def test_fa1_full_before_and_after_table() -> None:
    """The FA1 table, position by position, as derived in docs/financing.md."""
    result = _run(_by_id("FA1"))
    before = ovf.CapTable(securities=list(TABLE))
    assert before.fully_diluted_shares == 15_000_000
    record = result.position("series_a")
    adjustment = record.adjustment
    assert adjustment is not None and adjustment.deemed_outstanding is not None
    assert (adjustment.a, adjustment.b, adjustment.c) == (14_000_000, 2_000_000, 4_000_000)
    assert adjustment.deemed_outstanding.excluded == {"reserved_unissued_pool": 1_000_000}
    assert adjustment.issue_price == 1.25
    assert record.conversion_price_before == 2.50
    assert record.conversion_price_after == pytest.approx(20 / 9, rel=1e-12)

    after = {s.security_id: s for s in result.table.securities}
    as_converted = {
        k: s.converted_shares if isinstance(s, ovf.PreferredStock) else s.shares
        for k, s in after.items()
    }
    assert as_converted == pytest.approx(
        {
            "common": 8_000_000,
            "seed": 2_000_000,
            "series_a": 2_250_000,
            "pool": 3_000_000,
            "series_b": 4_000_000,
        },
        rel=1e-12,
    )
    preferences = {
        k: s.base_liquidation_preference()
        for k, s in after.items()
        if isinstance(s, ovf.PreferredStock)
    }
    assert preferences == {"seed": 3_000_000, "series_a": 5_000_000, "series_b": 5_000_000}
    assert result.table.fully_diluted_shares == pytest.approx(19_250_000, rel=1e-12)
    ownership = result.table.ownership_breakdown()
    assert ownership["founders"] == pytest.approx(32 / 77, rel=1e-12)
    assert ownership["series_a"] == pytest.approx(9 / 77, rel=1e-12)


def test_adjusted_ratio_reprices_the_original_investment() -> None:
    """shares x OIP / CP2 = invested capital / CP2 for every adjusted position."""
    for fixture in FINANCING_FIXTURES:
        for record in _run(fixture).positions:
            if record.outcome != "adjusted":
                continue
            invested = record.position_after.invested_capital
            assert record.converted_shares_after == pytest.approx(
                invested / record.conversion_price_after, rel=1e-12
            )


def test_fa2_same_issuance_without_protection_changes_nothing() -> None:
    result = _run(_by_id("FA2"))
    assert all(p.adjustment is None for p in result.positions)
    assert result.table.securities == [*TABLE, *DOWN_ROUND.securities]


def test_fa5_issue_above_both_prices_leaves_no_new_state() -> None:
    fixture = _by_id("FA5")
    result = _run(fixture)
    for record in result.positions:
        assert record.adjustment is not None and not record.adjustment.triggered
    assert all(a is b for a, b in zip(result.table.securities, TABLE, strict=False))
    assert result.table.securities == [*TABLE, *fixture.issue.securities]


def test_fa5b_trigger_is_evaluated_per_series() -> None:
    result = _run(_by_id("FA5b"))
    seed, series_a = result.position("seed"), result.position("series_a")
    assert seed.adjustment is not None and seed.adjustment.issue_price == 2.00
    assert not seed.adjustment.triggered
    assert series_a.adjustment is not None and series_a.adjustment.triggered
    assert series_a.adjustment.b == pytest.approx(800_000, rel=1e-12)


# --- Several series: independence and order ----------------------------------------


def test_fa3_order_independence() -> None:
    """One order, the reverse order and the simultaneous application agree exactly.

    Under the NVCA reading every series takes CP1 and A immediately prior to the issue,
    so the capitalization handed to the second series is the pre-issuance one, however
    the first series was adjusted. The intermediate table does change; A does not.
    """
    fixture = _by_id("FA3")
    table = ovf.CapTable(securities=list(TABLE))
    simultaneous = _run(fixture)
    prior = capitalization_before_issue(table)
    issuance = DOWN_ROUND.dilutive_issuance()

    def sequential(order: tuple[str, ...]) -> dict[str, float]:
        current = {s.security_id: s for s in TABLE}
        for security_id in order:
            position = current[security_id]
            assert isinstance(position, ovf.PreferredStock)
            current[security_id] = adjust_position(
                position,
                protection=fixture.protection[security_id],
                capitalization=prior,
                issuance=issuance,
                exemption=fixture.exemption,
            ).position_after
        intermediate = capitalization_before_issue(ovf.CapTable(securities=list(current.values())))
        assert intermediate.preferred_as_converted > prior.preferred_as_converted
        return _ratios(ovf.CapTable(securities=list(current.values())))

    expected = {"seed": 27 / 26, "series_a": 9 / 8}
    forward = sequential(("seed", "series_a"))
    backward = sequential(("series_a", "seed"))
    together = {k: v for k, v in _ratios(simultaneous.table).items() if k in expected}
    assert forward == backward == together
    assert together == pytest.approx(expected, rel=1e-12)


def test_fa3_result_does_not_depend_on_table_or_mapping_order() -> None:
    fixture = _by_id("FA3")
    reference = _run(fixture)
    shuffled = apply_dilutive_issuance(
        ovf.CapTable(securities=[TABLE[3], SERIES_A, TABLE[0], SEED]),
        issue=fixture.issue,
        protection=dict(reversed(list(fixture.protection.items()))),
        exemption=fixture.exemption,
    )
    assert _ratios(shuffled.table) == _ratios(reference.table)
    assert {p.security_id: p.adjustment for p in shuffled.positions} == {
        p.security_id: p.adjustment for p in reference.positions
    }


def test_naive_reading_would_be_order_dependent() -> None:
    """Recomputing A after each adjustment gives a different answer in each order.

    This is not the charter's reading; it shows why the reading matters. Both naive
    orders are derived by hand in docs/financing.md.
    """
    fixture = _by_id("FA3")
    issuance = DOWN_ROUND.dilutive_issuance()

    def naive(order: tuple[str, ...]) -> dict[str, float]:
        current = {s.security_id: s for s in TABLE}
        prices: dict[str, float] = {}
        for security_id in order:
            position = current[security_id]
            assert isinstance(position, ovf.PreferredStock)
            record = adjust_position(
                position,
                protection=fixture.protection[security_id],
                capitalization=capitalization_before_issue(
                    ovf.CapTable(securities=list(current.values()))
                ),
                issuance=issuance,
                exemption=fixture.exemption,
            )
            current[security_id] = record.position_after
            prices[security_id] = record.conversion_price_after
        return prices

    seed_first = naive(("seed", "series_a"))
    a_first = naive(("series_a", "seed"))
    assert seed_first == pytest.approx(NAIVE_SEED_THEN_A, rel=1e-12)
    assert a_first == pytest.approx(NAIVE_A_THEN_SEED, rel=1e-12)
    charter = _by_id("FA3").expected_conversion_prices
    assert seed_first["series_a"] > charter["series_a"]
    assert a_first["seed"] > charter["seed"]


def test_fa4_ratchet_on_one_series_does_not_feed_the_other() -> None:
    fa1, fa3, fa4 = (_run(_by_id(c)).position("series_a") for c in ("FA1", "FA3", "FA4"))
    for record in (fa1, fa3, fa4):
        assert record.adjustment is not None
        assert record.adjustment.a == 14_000_000
    assert fa1.conversion_price_after == fa3.conversion_price_after == fa4.conversion_price_after
    seed = _run(_by_id("FA4")).position("seed")
    assert seed.adjustment is not None and seed.adjustment.a is None
    assert seed.converted_shares_after == pytest.approx(2_400_000, rel=1e-12)


# --- Exemption ----------------------------------------------------------------------


def test_fa6_exemption_suppresses_the_adjustment() -> None:
    """The same issuance, not exempted, gives FA3's hand-derived prices."""
    fixture = _by_id("FA6")
    exempted = _run(fixture)
    assert all(p.adjustment is None for p in exempted.positions)
    assert exempted.exemption == ACQUISITION_EXEMPT
    assert any(ACQUISITION_EXEMPT.basis in line for line in exempted.assumptions)
    not_exempted = apply_dilutive_issuance(
        ovf.CapTable(securities=list(TABLE)),
        issue=ACQUISITION,
        protection=fixture.protection,
        exemption=NOT_EXEMPT,
    )
    prices = {p.security_id: p.conversion_price_after for p in not_exempted.positions}
    assert prices == pytest.approx(_by_id("FA3").expected_conversion_prices, rel=1e-12)


def test_exemption_must_be_stated() -> None:
    with pytest.raises(TypeError):
        apply_dilutive_issuance(  # type: ignore[call-arg]
            ovf.CapTable(securities=list(TABLE)),
            issue=DOWN_ROUND,
            protection={"seed": BROAD, "series_a": BROAD},
        )
    with pytest.raises(ValidationError):
        ExemptionDetermination(exempted=False)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ExemptionDetermination(exempted=False, basis="")
    with pytest.raises(ValidationError):
        ExemptionDetermination(exempted=0, basis="not a boolean")  # type: ignore[arg-type]


# --- An adjusted table carried into an exit ------------------------------------------


@pytest.mark.parametrize("fixture", EXIT_FIXTURES, ids=lambda f: f.case_id)
def test_exit_after_financing(fixture: ExitAfterFinancingFixture) -> None:
    result = apply_dilutive_issuance(
        ovf.CapTable(securities=list(fixture.table)),
        issue=fixture.issue,
        protection=fixture.protection,
        exemption=fixture.exemption,
    )
    assert _ratios(result.table)["series_a"] == pytest.approx(
        fixture.expected_series_a_ratio, rel=1e-12
    )
    report = result.table.waterfall_detailed(fixture.exit_valuation)
    actual = {p.security_id: p.amount for p in report.payouts}
    assert actual == pytest.approx(fixture.expected, abs=1e-6)
    converted = {
        p.security_id: p.converted
        for p in report.payouts
        if p.security_id in fixture.expected_converted
    }
    assert converted == fixture.expected_converted
    survey = ovf.enumerate_equilibria(result.table.securities, fixture.exit_valuation)
    assert survey.payoff_unique
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


def test_the_adjustment_moves_six_million_to_series_a() -> None:
    protected, unprotected = (f.expected for f in EXIT_FIXTURES)
    assert protected["series_a"] - unprotected["series_a"] == 6_000_000
    assert protected["common"] - unprotected["common"] == -4_000_000
    assert protected["series_b"] - unprotected["series_b"] == -2_000_000


# --- Inputs that must be stated, and refusals ---------------------------------------


@pytest.mark.parametrize(
    "function",
    [
        apply_dilutive_issuance,
        adjust_position,
        capitalization_before_issue,
        weighted_average_protection,
    ],
)
def test_public_functions_have_no_default_arguments(function: object) -> None:
    assert callable(function)
    for parameter in inspect.signature(function).parameters.values():
        assert parameter.default is inspect.Parameter.empty, parameter.name


@pytest.mark.parametrize("model", [AntiDilutionProtection, ExemptionDetermination, NewIssue])
def test_charter_facts_have_no_default_fields(model: type) -> None:
    for name, info in model.model_fields.items():
        assert info.is_required(), name


def test_every_preferred_position_must_be_classified() -> None:
    table = ovf.CapTable(securities=list(TABLE))
    with pytest.raises(ValueError, match="missing: seed"):
        apply_dilutive_issuance(
            table, issue=DOWN_ROUND, protection={"series_a": BROAD}, exemption=NOT_EXEMPT
        )
    with pytest.raises(ValueError, match="not preferred stock in the table: common"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND,
            protection={"seed": BROAD, "series_a": BROAD, "common": BROAD},
            exemption=NOT_EXEMPT,
        )
    with pytest.raises(ValueError, match="must be an AntiDilutionProtection"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND,
            protection={"seed": BROAD, "series_a": "broad"},  # type: ignore[dict-item]
            exemption=NOT_EXEMPT,
        )


def test_protection_definition_rules() -> None:
    with pytest.raises(ValidationError, match="definition of A"):
        AntiDilutionProtection(method="weighted_average", definition=None)
    with pytest.raises(ValidationError, match="does not use a definition"):
        AntiDilutionProtection(method="full_ratchet", definition=BROAD_BASED_NVCA)
    with pytest.raises(ValidationError, match="does not use a definition"):
        AntiDilutionProtection(method="none", definition=BROAD_BASED_NVCA)
    assert FULL_RATCHET.definition is None and UNPROTECTED.method == "none"


@pytest.mark.parametrize(
    "instrument",
    [
        ovf.safe_post(500_000, 10_000_000, holder_id="angel", security_id="safe"),
        convertible_note(
            500_000,
            0.06,
            accrual="simple",
            day_count="actual/365_fixed",
            issue_date=date(2026, 1, 1),
            maturity_date=date(2028, 1, 1),
            seniority=0,
            qualified_financing_threshold=1_000_000,
            security_id="note",
        ),
    ],
)
def test_table_with_an_undetermined_convertible_is_refused(instrument: ovf.Security) -> None:
    table = ovf.CapTable(securities=[*TABLE, instrument])
    with pytest.raises(ValueError, match="A cannot be counted"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND,
            protection={"seed": BROAD, "series_a": BROAD},
            exemption=NOT_EXEMPT,
        )


def test_plain_debt_counts_nothing_in_a() -> None:
    loan = debt(
        1_000_000,
        0.08,
        accrual="simple",
        day_count="actual/365_fixed",
        issue_date=date(2025, 1, 1),
        seniority=0,
        security_id="loan",
    )
    with_debt = capitalization_before_issue(ovf.CapTable(securities=[*TABLE, loan]))
    assert with_debt == capitalization_before_issue(ovf.CapTable(securities=list(TABLE)))


@pytest.mark.parametrize(
    ("securities", "message"),
    [
        ((), "at least one security"),
        ((ovf.option_pool(500_000, security_id="new_pool"),), "not an issuance of shares"),
        ((ovf.safe_post(1.0, 10.0, security_id="s"),), "only common and preferred"),
        ((ovf.common(0, security_id="nothing"),), "positive number of shares"),
        ((series_b(1, 1.0), series_b(1, 1.0)), "Duplicate security_id"),
    ],
)
def test_bad_issue_is_refused(securities: tuple[ovf.Security, ...], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        NewIssue(securities=securities, aggregate_consideration=1.0)


def test_issued_id_colliding_with_the_table_is_refused() -> None:
    clash = NewIssue(
        securities=(ovf.common(1_000, security_id="common"),), aggregate_consideration=500
    )
    with pytest.raises(ValueError, match="Duplicate security_id: common"):
        apply_dilutive_issuance(
            ovf.CapTable(securities=list(TABLE)),
            issue=clash,
            protection={"seed": BROAD, "series_a": BROAD},
            exemption=NOT_EXEMPT,
        )


def test_full_ratchet_on_a_free_issue_is_refused_with_the_position_named() -> None:
    free = NewIssue(securities=(series_b(4_000_000, 0.0),), aggregate_consideration=0)
    with pytest.raises(ValueError, match="seed: full ratchet on an issuance without"):
        apply_dilutive_issuance(
            ovf.CapTable(securities=list(TABLE)),
            issue=free,
            protection={"seed": FULL_RATCHET, "series_a": UNPROTECTED},
            exemption=NOT_EXEMPT,
        )


def test_protected_position_without_an_issue_price_is_refused() -> None:
    free_shares = ovf.preferred(1_000, 0.0, holder_id="x", security_id="free")
    with pytest.raises(ValueError, match="free: protected preferred needs a positive"):
        apply_dilutive_issuance(
            ovf.CapTable(securities=[FOUNDERS_ONLY, free_shares]),
            issue=DOWN_ROUND,
            protection={"free": BROAD},
            exemption=NOT_EXEMPT,
        )


def test_untyped_inputs_are_rejected() -> None:
    table = ovf.CapTable(securities=list(TABLE))
    protection = {"seed": BROAD, "series_a": BROAD}
    with pytest.raises(ValueError, match="table must be a CapTable"):
        apply_dilutive_issuance(
            list(TABLE),  # type: ignore[arg-type]
            issue=DOWN_ROUND,
            protection=protection,
            exemption=NOT_EXEMPT,
        )
    with pytest.raises(ValueError, match="issue must be a NewIssue"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND.dilutive_issuance(),  # type: ignore[arg-type]
            protection=protection,
            exemption=NOT_EXEMPT,
        )
    with pytest.raises(ValueError, match="exemption must be"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND,
            protection=protection,
            exemption=False,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="protection must be a mapping"):
        apply_dilutive_issuance(
            table,
            issue=DOWN_ROUND,
            protection=[BROAD],
            exemption=NOT_EXEMPT,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="position must be a PreferredStock"):
        adjust_position(
            FOUNDERS_ONLY,  # type: ignore[arg-type]
            protection=BROAD,
            capitalization=capitalization_before_issue(table),
            issuance=DOWN_ROUND.dilutive_issuance(),
            exemption=NOT_EXEMPT,
        )


# --- Provenance ---------------------------------------------------------------------


def test_result_carries_a_stable_hash_and_its_assumptions() -> None:
    first, again = _run(_by_id("FA3")), _run(_by_id("FA3"))
    assert first.engine_version == ENGINE_VERSION == "financing-v1"
    assert len(first.input_hash) == 64 and first.input_hash == again.input_hash
    assert first.input_hash != _run(_by_id("FA4")).input_hash
    flipped = apply_dilutive_issuance(
        ovf.CapTable(securities=list(TABLE)),
        issue=DOWN_ROUND,
        protection=_by_id("FA3").protection,
        exemption=ExemptionDetermination(exempted=True, basis=NOT_EXEMPT.basis),
    )
    assert flipped.input_hash != first.input_hash
    assert any("immediately prior" in line for line in first.assumptions)
    assert any("not exempted" in line for line in first.assumptions)


def test_no_clock_is_read() -> None:
    path = Path(__file__).resolve().parents[1] / "src" / "ovf" / "financing.py"
    source = path.read_text(encoding="utf-8")
    for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
        assert call not in source, f"financing.py reads a clock via {call}"
