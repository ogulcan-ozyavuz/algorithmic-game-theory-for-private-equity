"""Anti-dilution fixtures and invariants, asserted against `ovf.antidilution`."""

from __future__ import annotations

import inspect
import itertools

import pytest
from pydantic import ValidationError

import ovf
from ovf.antidilution import (
    BROAD_BASED_NVCA,
    BROAD_BASED_WITH_RESERVED_POOL,
    NARROW_BASED_OUTSTANDING_STOCK,
    CapitalizationBeforeIssue,
    DeemedOutstandingDefinition,
    DilutiveIssuance,
    conversion_ratio,
    deemed_outstanding,
    full_ratchet,
    weighted_average,
)
from tests.antidilution_fixtures import (
    ANTIDILUTION_FIXTURES,
    CAPITALIZATION,
    CP1,
    DOWN_ROUND,
    FREE_ISSUE,
    SERIES_A_INVESTED,
    SERIES_A_ORIGINAL_ISSUE_PRICE,
    SERIES_A_SHARES,
    UP_ROUND,
    AntidilutionFixture,
    adjust,
)

CAPITALIZATION_FIELDS = (
    "common_outstanding",
    "preferred_as_converted",
    "options_and_warrants_as_exercised",
    "other_convertibles_as_converted",
    "reserved_unissued_pool",
)


def _by_id(case_id: str) -> AntidilutionFixture:
    return next(f for f in ANTIDILUTION_FIXTURES if f.case_id == case_id)


# --- Named fixtures ---------------------------------------------------------------


@pytest.mark.parametrize("fixture", ANTIDILUTION_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_conversion_price(fixture: AntidilutionFixture) -> None:
    result = adjust(fixture)
    assert result.method == fixture.method
    assert result.conversion_price_before == CP1
    assert result.conversion_price_after == pytest.approx(
        fixture.expected_conversion_price, rel=1e-12
    )
    assert result.triggered is fixture.expected_triggered
    assert result.c == fixture.issuance.shares_issued
    if fixture.expected_a is None:
        assert result.a is None and result.b is None and result.deemed_outstanding is None
    else:
        assert result.a == pytest.approx(fixture.expected_a, rel=1e-12)
        assert result.b == pytest.approx(fixture.expected_b, rel=1e-12)


@pytest.mark.parametrize("fixture", ANTIDILUTION_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_conversion_ratio(fixture: AntidilutionFixture) -> None:
    result = adjust(fixture)
    ratio = conversion_ratio(
        original_issue_price=SERIES_A_ORIGINAL_ISSUE_PRICE,
        conversion_price=result.conversion_price_after,
    )
    assert ratio == pytest.approx(fixture.expected_conversion_ratio, rel=1e-12)


@pytest.mark.parametrize("fixture", ANTIDILUTION_FIXTURES, ids=lambda f: f.case_id)
def test_no_fixture_moves_the_price_upward(fixture: AntidilutionFixture) -> None:
    result = adjust(fixture)
    assert result.conversion_price_after <= result.conversion_price_before
    if not result.triggered:
        assert result.conversion_price_after == result.conversion_price_before
        assert result.adjustment_factor == 1.0


def test_down_round_ordering_ratchet_narrow_broad_reserve() -> None:
    """AD3 < AD2 < AD1 < AD4 < CP1: the smaller A, the larger the downward move."""
    ratchet, narrow, broad, reserve = (
        adjust(_by_id(case)).conversion_price_after for case in ("AD3", "AD2", "AD1", "AD4")
    )
    assert ratchet < narrow < broad < reserve < CP1
    assert (ratchet, narrow, broad, reserve) == pytest.approx(
        (1.25, 15 / 7, 2.1875, 75 / 34), rel=1e-12
    )


def test_series_a_share_counts_after_the_down_round() -> None:
    """Hand-derived common-equivalent shares of Series A under each adjustment."""
    expected = {
        "AD1": 16_000_000 / 7,  # 2,285,714.29
        "AD2": 7_000_000 / 3,  # 2,333,333.33
        "AD3": 4_000_000,
        "AD4": 34_000_000 / 15,  # 2,266,666.67
    }
    for case_id, shares in expected.items():
        cp2 = adjust(_by_id(case_id)).conversion_price_after
        ratio = conversion_ratio(
            original_issue_price=SERIES_A_ORIGINAL_ISSUE_PRICE, conversion_price=cp2
        )
        assert SERIES_A_SHARES * ratio == pytest.approx(shares, rel=1e-12)


# --- Never upward -----------------------------------------------------------------


@pytest.mark.parametrize(
    "definition", [BROAD_BASED_NVCA, NARROW_BASED_OUTSTANDING_STOCK, BROAD_BASED_WITH_RESERVED_POOL]
)
def test_raw_formula_would_raise_the_price_above_cp1(
    definition: DeemedOutstandingDefinition,
) -> None:
    """AD5: B > C, so the unguarded formula exceeds CP1. The engine must not follow it."""
    result = weighted_average(
        conversion_price=CP1,
        capitalization=CAPITALIZATION,
        definition=definition,
        issuance=UP_ROUND,
    )
    assert result.a is not None and result.b is not None
    assert result.b > result.c
    raw = CP1 * (result.a + result.b) / (result.a + result.c)
    assert raw > CP1
    assert result.conversion_price_after == CP1
    assert not result.triggered


def test_issue_exactly_at_the_conversion_price_does_not_trigger() -> None:
    """The NVCA trigger is 'less than' the conversion price in effect."""
    at_price = DilutiveIssuance(shares_issued=1_000_000, aggregate_consideration=2_500_000)
    wa = weighted_average(
        conversion_price=CP1,
        capitalization=CAPITALIZATION,
        definition=BROAD_BASED_NVCA,
        issuance=at_price,
    )
    ratchet = full_ratchet(conversion_price=CP1, issuance=at_price)
    for result in (wa, ratchet):
        assert not result.triggered
        assert result.conversion_price_after == CP1


def test_grid_invariants() -> None:
    """Over a grid of bases, sizes and prices: p <= CP2 <= CP1 and the closed form holds.

    Where the adjustment applies, CP2 - p = A (CP1 - p) / (A + C), which is the
    algebraic reason the weighted-average price always lies between the issue price
    and the old conversion price. Full ratchet is never above weighted average.
    """
    commons = (0, 1_000_000, 8_000_000, 50_000_000)
    sizes = (1, 1_000, 4_000_000, 100_000_000)
    prices = (0.0, 0.01, 1.25, 2.4999, 2.50, 2.5001, 3.00, 40.0)
    for common, size, price in itertools.product(commons, sizes, prices):
        cap = CapitalizationBeforeIssue(
            common_outstanding=common,
            preferred_as_converted=2_000_000,
            options_and_warrants_as_exercised=500_000,
            other_convertibles_as_converted=0,
            reserved_unissued_pool=750_000,
        )
        issuance = DilutiveIssuance(shares_issued=size, aggregate_consideration=size * price)
        broad = weighted_average(
            conversion_price=CP1, capitalization=cap, definition=BROAD_BASED_NVCA, issuance=issuance
        )
        narrow = weighted_average(
            conversion_price=CP1,
            capitalization=cap,
            definition=NARROW_BASED_OUTSTANDING_STOCK,
            issuance=issuance,
        )
        for result in (broad, narrow):
            assert result.conversion_price_after <= CP1
            if result.triggered:
                assert result.a is not None
                p = result.issue_price
                assert p - 1e-12 <= result.conversion_price_after
                closed_form = p + result.a * (CP1 - p) / (result.a + result.c)
                assert result.conversion_price_after == pytest.approx(closed_form, rel=1e-12)
            else:
                assert result.conversion_price_after == CP1
        assert narrow.conversion_price_after <= broad.conversion_price_after + 1e-12
        if price > 0:
            ratchet = full_ratchet(conversion_price=CP1, issuance=issuance)
            assert ratchet.conversion_price_after <= narrow.conversion_price_after + 1e-12


def test_larger_base_never_gives_a_larger_adjustment() -> None:
    """Adding shares to A moves CP2 toward CP1; that is the whole broad/narrow question."""
    previous = 0.0
    for reserve in (0, 100_000, 1_000_000, 10_000_000, 1_000_000_000):
        cap = CAPITALIZATION.model_copy(update={"reserved_unissued_pool": reserve})
        cp2 = weighted_average(
            conversion_price=CP1,
            capitalization=cap,
            definition=BROAD_BASED_WITH_RESERVED_POOL,
            issuance=DOWN_ROUND,
        ).conversion_price_after
        assert previous <= cp2 < CP1
        previous = cp2


# --- Zero consideration -----------------------------------------------------------


def test_zero_consideration_is_the_weighted_average_floor_for_a_given_size() -> None:
    """With A and C fixed, B = 0 gives the lowest weighted-average price."""
    floor = weighted_average(
        conversion_price=CP1,
        capitalization=CAPITALIZATION,
        definition=BROAD_BASED_NVCA,
        issuance=FREE_ISSUE,
    ).conversion_price_after
    assert floor == pytest.approx(1.875, rel=1e-12)
    for consideration in (1.0, 1_000_000.0, 4_999_999.0):
        paid = DilutiveIssuance(shares_issued=4_000_000, aggregate_consideration=consideration)
        cp2 = weighted_average(
            conversion_price=CP1,
            capitalization=CAPITALIZATION,
            definition=BROAD_BASED_NVCA,
            issuance=paid,
        ).conversion_price_after
        assert cp2 > floor


def test_full_ratchet_without_consideration_is_rejected() -> None:
    with pytest.raises(ValueError, match="without consideration"):
        full_ratchet(conversion_price=CP1, issuance=FREE_ISSUE)


def test_full_ratchet_with_the_nvca_deemed_consideration() -> None:
    """NVCA brackets [$0.001] in aggregate for a free issue: CP2 = 0.001 / 4,000,000."""
    deemed = DilutiveIssuance(shares_issued=4_000_000, aggregate_consideration=0.001)
    result = full_ratchet(conversion_price=CP1, issuance=deemed)
    assert result.conversion_price_after == pytest.approx(2.5e-10, rel=1e-12)
    ratio = conversion_ratio(
        original_issue_price=SERIES_A_ORIGINAL_ISSUE_PRICE,
        conversion_price=result.conversion_price_after,
    )
    assert ratio == pytest.approx(1e10, rel=1e-12)


def test_full_ratchet_ignores_issuance_size() -> None:
    for shares in (1, 4_000_000, 400_000_000):
        issuance = DilutiveIssuance(shares_issued=shares, aggregate_consideration=shares * 1.25)
        assert full_ratchet(conversion_price=CP1, issuance=issuance).conversion_price_after == 1.25


# --- Conversion-ratio identity ----------------------------------------------------


@pytest.mark.parametrize(
    ("case_id", "expected_shares"),
    [("AD1", 16_000_000 / 7), ("AD3", 4_000_000.0)],
)
def test_ratio_identity_recovers_the_repriced_share_count(
    case_id: str, expected_shares: float
) -> None:
    """shares x OIP / CP2 = invested capital / CP2, as a PreferredStock sees it.

    AD1: $5,000,000 / $2.1875 = 16,000,000 / 7. AD3: $5,000,000 / $1.25 = 4,000,000.
    """
    cp2 = adjust(_by_id(case_id)).conversion_price_after
    ratio = conversion_ratio(
        original_issue_price=SERIES_A_ORIGINAL_ISSUE_PRICE, conversion_price=cp2
    )
    series_a = ovf.preferred(
        shares=SERIES_A_SHARES,
        price=SERIES_A_ORIGINAL_ISSUE_PRICE,
        conversion_ratio=ratio,
        holder_id="series_a",
        security_id="series_a",
    )
    assert series_a.invested_capital == SERIES_A_INVESTED
    assert series_a.converted_shares == pytest.approx(expected_shares, rel=1e-12)
    assert series_a.converted_shares == pytest.approx(SERIES_A_INVESTED / cp2, rel=1e-12)


def test_ratio_is_one_before_any_adjustment() -> None:
    assert conversion_ratio(original_issue_price=2.50, conversion_price=2.50) == 1.0


# --- No defaults, explicit composition --------------------------------------------


@pytest.mark.parametrize("missing", CAPITALIZATION_FIELDS)
def test_every_component_of_a_is_required(missing: str) -> None:
    fields = {name: 1_000.0 for name in CAPITALIZATION_FIELDS if name != missing}
    with pytest.raises(ValidationError, match=missing):
        CapitalizationBeforeIssue(**fields)


def test_every_definition_flag_is_required() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DeemedOutstandingDefinition(name="x", source="y")  # type: ignore[call-arg]
    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert missing == {
        "include_common",
        "include_preferred_as_converted",
        "include_options_and_warrants",
        "include_other_convertibles",
        "include_reserved_pool",
    }


def test_definition_flags_must_be_booleans() -> None:
    with pytest.raises(ValidationError):
        BROAD_BASED_NVCA.model_validate(
            {**BROAD_BASED_NVCA.model_dump(), "include_reserved_pool": 1}
        )


@pytest.mark.parametrize(
    "function", [weighted_average, full_ratchet, conversion_ratio, deemed_outstanding]
)
def test_public_functions_have_no_default_arguments(function: object) -> None:
    assert callable(function)
    for parameter in inspect.signature(function).parameters.values():
        assert parameter.default is inspect.Parameter.empty, parameter.name


def test_weighted_average_refuses_to_run_without_a_definition() -> None:
    with pytest.raises(TypeError):
        weighted_average(  # type: ignore[call-arg]
            conversion_price=CP1, capitalization=CAPITALIZATION, issuance=DOWN_ROUND
        )


def test_deemed_outstanding_records_what_each_definition_excluded() -> None:
    broad = deemed_outstanding(CAPITALIZATION, BROAD_BASED_NVCA)
    assert broad.total == 12_000_000
    assert broad.excluded == {"reserved_unissued_pool": 1_000_000}
    narrow = deemed_outstanding(CAPITALIZATION, NARROW_BASED_OUTSTANDING_STOCK)
    assert narrow.total == 10_000_000
    assert narrow.excluded == {
        "options_and_warrants_as_exercised": 2_000_000,
        "other_convertibles_as_converted": 0,
        "reserved_unissued_pool": 1_000_000,
    }
    reserve = deemed_outstanding(CAPITALIZATION, BROAD_BASED_WITH_RESERVED_POOL)
    assert reserve.total == 13_000_000
    assert reserve.excluded == {}
    for base in (broad, narrow, reserve):
        assert set(base.counted) | set(base.excluded) == set(CAPITALIZATION_FIELDS)


def test_result_carries_the_composition_and_a_stable_hash() -> None:
    first = adjust(_by_id("AD1"))
    again = adjust(_by_id("AD1"))
    narrow = adjust(_by_id("AD2"))
    assert first.engine_version == "antidilution-v1"
    assert first.deemed_outstanding is not None
    assert first.deemed_outstanding.definition == "broad_based_nvca"
    assert any("broad_based_nvca" in line for line in first.assumptions)
    assert any("unrounded" in line for line in first.assumptions)
    assert len(first.input_hash) == 64
    assert first.input_hash == again.input_hash
    assert first.input_hash != narrow.input_hash


# --- Rejected input ---------------------------------------------------------------


@pytest.mark.parametrize("bad", [0.0, -2.50, float("nan"), float("inf"), True, "2.50", None])
def test_bad_conversion_price_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="conversion_price"):
        weighted_average(
            conversion_price=bad,  # type: ignore[arg-type]
            capitalization=CAPITALIZATION,
            definition=BROAD_BASED_NVCA,
            issuance=DOWN_ROUND,
        )
    with pytest.raises(ValueError, match="conversion_price"):
        full_ratchet(conversion_price=bad, issuance=DOWN_ROUND)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("shares", "consideration"),
    [(0, 1.0), (-1, 1.0), (1, -1.0), (float("nan"), 1.0), (1, float("inf"))],
)
def test_bad_issuance_is_rejected(shares: float, consideration: float) -> None:
    with pytest.raises(ValidationError):
        DilutiveIssuance(shares_issued=shares, aggregate_consideration=consideration)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_bad_share_count_is_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        CAPITALIZATION.model_validate({**CAPITALIZATION.model_dump(), "common_outstanding": bad})


def test_zero_base_is_rejected() -> None:
    nothing = DeemedOutstandingDefinition(
        name="common_only",
        source="test",
        include_common=True,
        include_preferred_as_converted=False,
        include_options_and_warrants=False,
        include_other_convertibles=False,
        include_reserved_pool=False,
    )
    empty = CAPITALIZATION.model_copy(update={"common_outstanding": 0.0})
    with pytest.raises(ValueError, match="A is zero"):
        weighted_average(
            conversion_price=CP1, capitalization=empty, definition=nothing, issuance=DOWN_ROUND
        )


def test_untyped_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="capitalization must be"):
        weighted_average(
            conversion_price=CP1,
            capitalization=CAPITALIZATION.model_dump(),  # type: ignore[arg-type]
            definition=BROAD_BASED_NVCA,
            issuance=DOWN_ROUND,
        )
    with pytest.raises(ValueError, match="issuance must be"):
        full_ratchet(conversion_price=CP1, issuance={"shares_issued": 1})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="original_issue_price"):
        conversion_ratio(original_issue_price=0.0, conversion_price=2.50)


def test_inputs_are_immutable() -> None:
    with pytest.raises(ValidationError):
        CAPITALIZATION.common_outstanding = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DOWN_ROUND.shares_issued = 1.0  # type: ignore[misc]
