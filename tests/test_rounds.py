"""Priced-round fixtures and invariants, asserted against `ovf.rounds`.

Every expected number comes from `tests/rounds_fixtures.py`, whose derivations are written
out in `docs/rounds.md`. Published source figures are compared within the rounding the
source used, never used as expected values.
"""

from __future__ import annotations

import inspect
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import ovf
from ovf.antidilution import BROAD_BASED_NVCA
from ovf.contracts.safes import (
    MFNResolution,
    PostMoneyDiscountSAFE,
    PostMoneyMFNSAFE,
    mfn_resolution,
    resolve_mfn,
    safe_post_discount,
    safe_post_mfn,
)
from ovf.financing import FULL_RATCHET, UNPROTECTED, weighted_average_protection
from ovf.instruments import convertible_note, debt
from ovf.rounds import (
    ENGINE_VERSION,
    NO_POOL_CHANGE,
    SENIOR_TO_ALL,
    NewSeries,
    PoolChange,
    PricedRound,
    RoundResult,
    SeniorityPlacement,
    apply_priced_round,
    explicit_seniority,
    pari_passu_with,
    pool_increase,
    pool_target_unallocated,
    round_capitalization,
)
from tests.rounds_fixtures import (
    CAP_SAFE,
    COOLEY_FOUNDERS,
    COOLEY_SAFE,
    DISCOUNT_SAFE,
    FOUNDERS,
    MFN_SAFE,
    MFN_TABLE,
    MR_A_OWNERSHIP,
    MR_A_PREFERENCE_PRICE,
    MR_A_PRICE,
    MR_A_SHARES,
    MR_A_TOTAL,
    MR_B_NEW_SHARES,
    MR_B_OWNERSHIP,
    MR_B_PRICE,
    MR_B_TOTAL,
    MR_EXITS,
    MR_TABLE_AFTER_SAFE,
    MR_UNPROTECTED,
    ROUND_FIXTURES,
    S1_ANGEL,
    ExitFixture,
    M,
    RoundFixture,
    by_id,
    mfn_elects,
    series,
    series_a_terms,
    series_b_terms,
    terms,
)
from tests.safe_fixtures import SAFE_FIXTURES, SafeFixture

BROAD = weighted_average_protection(BROAD_BASED_NVCA)


def _run(fixture: RoundFixture) -> RoundResult:
    return apply_priced_round(
        ovf.CapTable(securities=list(fixture.table)),
        terms=fixture.terms,
        protection=fixture.protection,
        mfn=fixture.mfn,
    )


def _as_converted(table: ovf.CapTable) -> dict[str, float]:
    return {
        s.security_id: s.converted_shares if isinstance(s, ovf.PreferredStock) else s.shares
        for s in table.securities
    }


# --- Named fixtures -----------------------------------------------------------------


@pytest.mark.parametrize("fixture", ROUND_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_price_and_totals(fixture: RoundFixture) -> None:
    result = _run(fixture)
    assert result.price_per_share == pytest.approx(fixture.expected_price, rel=1e-12)
    assert result.total_post_shares == pytest.approx(fixture.expected_total, rel=1e-12)
    assert result.new_money_shares == pytest.approx(fixture.expected_new_shares, rel=1e-12)
    assert result.pool_increase_shares == pytest.approx(
        fixture.expected_pool_increase, rel=1e-12, abs=1e-6
    )


@pytest.mark.parametrize("fixture", ROUND_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_safe_conversions(fixture: RoundFixture) -> None:
    result = _run(fixture)
    shares = {c.security_id: c.shares for c in result.safe_conversions}
    assert shares == pytest.approx(fixture.expected_safe_shares, rel=1e-12)
    assert {c.security_id: c.basis for c in result.safe_conversions} == fixture.expected_basis
    for c in result.safe_conversions:
        assert c.conversion_price == pytest.approx(c.purchase_amount / c.shares, rel=1e-12)
        assert c.round_price == result.price_per_share
    if fixture.expected_post_capitalization is not None:
        assert result.post_money_safe_capitalization == pytest.approx(
            fixture.expected_post_capitalization, rel=1e-12
        )
    if fixture.expected_pre_capitalization is not None:
        assert result.pre_money_safe_capitalization == pytest.approx(
            fixture.expected_pre_capitalization, rel=1e-12
        )


@pytest.mark.parametrize(
    "fixture", [f for f in ROUND_FIXTURES if f.expected_ownership], ids=lambda f: f.case_id
)
def test_fixture_ownership(fixture: RoundFixture) -> None:
    ownership = _run(fixture).ownership_breakdown
    assert ownership == pytest.approx(fixture.expected_ownership, abs=1e-12)
    assert math.fsum(ownership.values()) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("fixture", ROUND_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_conservation_and_pricing_identity(fixture: RoundFixture) -> None:
    result = _run(fixture)
    assert result.table.fully_diluted_shares == pytest.approx(result.total_post_shares, rel=1e-12)
    assert abs(result.share_balance_error) <= max(1e-8, result.total_post_shares * 1e-10)
    assert abs(result.pricing_error) <= 1e-9 * result.effective_pre_money_valuation
    assert result.uniqueness_margin > 0
    assert result.price_per_share * result.pre_money_share_count == pytest.approx(
        result.effective_pre_money_valuation, rel=1e-12
    )
    if fixture.terms.convention == "percentage_ownership_method":
        post = fixture.terms.pre_money_valuation + fixture.terms.new_money
        new_fraction = result.new_money_shares / result.total_post_shares
        assert new_fraction == pytest.approx(fixture.terms.new_money / post, rel=1e-12)


def _published_value(result: RoundResult, key: str) -> float:
    fields: dict[str, float] = {
        "price": result.price_per_share,
        "total": result.total_post_shares,
        "new_shares": result.new_money_shares,
        "post_capitalization": result.post_money_safe_capitalization,
    }
    if key in fields:
        return fields[key]
    if key == "conversion_price":
        (only,) = result.safe_conversions
        return only.conversion_price
    return result.conversion(key).shares


@pytest.mark.parametrize(
    "fixture", [f for f in ROUND_FIXTURES if f.published], ids=lambda f: f.case_id
)
def test_fixture_agrees_with_the_published_source(fixture: RoundFixture) -> None:
    """YC and Cooley round prices and shares; the exact values are the hand derivations."""
    result = _run(fixture)
    for key, printed in fixture.published.items():
        assert _published_value(result, key) == pytest.approx(
            printed, rel=fixture.published_rel_tol
        ), key


@pytest.mark.parametrize("fixture", ROUND_FIXTURES, ids=lambda f: f.case_id)
def test_fixture_table_shape(fixture: RoundFixture) -> None:
    """Existing positions keep their objects and order; SAFEs are replaced in place."""
    table = ovf.CapTable(securities=list(fixture.table))
    snapshot = [s.model_dump() for s in table.securities]
    result = apply_priced_round(
        table, terms=fixture.terms, protection=fixture.protection, mfn=fixture.mfn
    )
    assert [s.model_dump() for s in table.securities] == snapshot
    after = result.table.securities
    safe_ids = {c.security_id for c in result.safe_conversions}
    for before, now in zip(fixture.table, after, strict=False):
        assert now.security_id == before.security_id
        if before.security_id in safe_ids:
            assert isinstance(now, ovf.PreferredStock)
            assert now is result.conversion(before.security_id).position
        else:
            assert now is before
    extra = [s.security_id for s in after[len(fixture.table) :]]
    expected_extra = [fixture.terms.new_series.security_id]
    if fixture.expected_pool_increase > 0:
        assert fixture.terms.pool.security_id is not None
        expected_extra.append(fixture.terms.pool.security_id)
    assert extra == expected_extra


@pytest.mark.parametrize("fixture", ROUND_FIXTURES, ids=lambda f: f.case_id)
def test_converted_safes_take_the_new_series_terms(fixture: RoundFixture) -> None:
    result = _run(fixture)
    new = result.table.securities[len(fixture.table)]
    assert isinstance(new, ovf.PreferredStock)
    assert new.price == result.price_per_share
    for c in result.safe_conversions:
        p = c.position
        assert p.seniority == new.seniority == result.new_series_seniority
        assert (p.liquidation_multiple, p.participating, p.participation_cap) == (
            new.liquidation_multiple,
            new.participating,
            new.participation_cap,
        )
        assert p.conversion_ratio == 1.0
        # YC Safe Preferred: the per-share preference is the conversion price, so the
        # preference is the Purchase Amount.
        assert p.price == c.conversion_price
        assert p.invested_capital == pytest.approx(c.purchase_amount, rel=1e-12)
        assert c.series == ("standard_preferred" if c.basis == "round_price" else "safe_preferred")


@pytest.mark.parametrize(
    "fixture",
    [
        f
        for f in ROUND_FIXTURES
        if not any(isinstance(s, ovf.StockOptionPool) and s.allocated_shares for s in f.table)
    ],
    ids=lambda f: f.case_id,
)
def test_round_to_exit_handoff(fixture: RoundFixture) -> None:
    report = _run(fixture).table.waterfall_detailed(100 * M)
    assert report.converged
    assert math.fsum(p.amount for p in report.payouts) == pytest.approx(100 * M)


# --- Item 5b: Cooley's three conventions on identical inputs -------------------------


def test_three_conventions_give_three_answers_to_one_round() -> None:
    """The negotiated difference, on Cooley's own example."""
    pre, pct, dol = (_run(by_id(c)) for c in ("CM-pre", "CM-pct", "CM-dol"))
    assert pre.price_per_share > dol.price_per_share > pct.price_per_share
    founders = [r.ownership_breakdown["founders"] for r in (pre, dol, pct)]
    assert founders == sorted(founders, reverse=True)
    new = {k: r.ownership_breakdown["series_a"] for k, r in (("pre", pre), ("pct", pct))}
    assert new["pct"] == pytest.approx(0.20, rel=1e-12)
    assert new["pre"] < new["pct"]
    assert pre.implied_post_money_valuation == pytest.approx(80 * M / 7, rel=1e-12)
    assert dol.implied_post_money_valuation == pytest.approx(11 * M, rel=1e-12)
    assert pct.implied_post_money_valuation == pytest.approx(10 * M, rel=1e-12)


def test_a_cap_bound_safe_keeps_its_ratio_to_founders_under_every_convention() -> None:
    """The convention moves value between existing holders and the new money only."""
    for case_id in ("CS-pre", "CS-pct", "CS-dol"):
        result = _run(by_id(case_id))
        assert result.conversion("angel").shares / 8_000_000 == pytest.approx(1 / 9, rel=1e-12)
        assert result.post_money_safe_capitalization == pytest.approx(80 * M / 9, rel=1e-12)


@pytest.mark.parametrize("fixture", SAFE_FIXTURES, ids=lambda f: f.case_id)
def test_percentage_ownership_reproduces_the_legacy_fixtures(fixture: SafeFixture) -> None:
    """S1-S5 through the new engine: `solve_priced_round_with_safes` is this convention."""
    pool = (
        pool_target_unallocated(
            fixture.target_pool_pct, security_id="round:pool", holder_id="option_pool"
        )
        if fixture.target_pool_pct
        else NO_POOL_CHANGE
    )
    result = apply_priced_round(
        ovf.CapTable(
            securities=[
                ovf.common(fixture.prior_common_shares, holder_id="founders", security_id="c"),
                *fixture.safes,
            ]
        ),
        terms=terms(
            fixture.pre_money_valuation,
            fixture.new_money,
            "percentage_ownership_method",
            pool,
            new_series=NewSeries(
                security_id="round:new",
                holder_id="new_preferred",
                seniority=explicit_seniority(1),
                liquidation_multiple=1.0,
                participating=False,
                participation_cap=None,
            ),
        ),
        protection={},
        mfn=None,
    )
    assert result.price_per_share == pytest.approx(fixture.expected_share_price, rel=1e-12)
    assert result.total_post_shares == pytest.approx(fixture.expected_total_shares, rel=1e-12)
    shares = {c.security_id: c.shares for c in result.safe_conversions}
    assert shares == pytest.approx(fixture.expected_safe_shares, rel=1e-12)
    expected = {k: v for k, v in fixture.expected_ownership.items() if v}
    assert result.ownership_breakdown == pytest.approx(expected, abs=1e-12)


def test_legacy_solver_is_the_percentage_ownership_method() -> None:
    """Cooley's example through the legacy solver, with a cap too high to bind: $46/7."""
    legacy = ovf.solve_priced_round_with_safes(
        prior_common_shares=M,
        new_money=2 * M,
        pre_money_valuation=8 * M,
        target_pool_pct=0.0,
        safes=[ovf.safe_post(M, 1e15, discount_rate=0.30, holder_id="x", security_id="x")],
    )
    assert legacy.share_price == pytest.approx(46 / 7, rel=1e-12)
    assert legacy.share_price == pytest.approx(by_id("CM-pct").expected_price, rel=1e-12)


# --- Item 1: existing pool and granted options -------------------------------------


def test_existing_pool_is_in_the_cap_denominator_and_the_increase_is_not() -> None:
    result = _run(by_id("EP1"))
    cap = result.capitalization
    assert (cap.common_outstanding, cap.granted_options, cap.unallocated_pool) == (
        8 * M,
        M / 2,
        M / 2,
    )
    counted = cap.outstanding + cap.unallocated_pool + result.conversion("angel").shares
    assert result.post_money_safe_capitalization == pytest.approx(counted, rel=1e-12)
    assert result.conversion("angel").cap_price == pytest.approx(1.0, rel=1e-12)


def test_target_pool_is_hit_exactly_and_an_absolute_increase_is_not_recomputed() -> None:
    ep1 = _run(by_id("EP1"))
    assert ep1.unallocated_pool_after / ep1.total_post_shares == pytest.approx(0.10, rel=1e-12)
    yc = _run(by_id("YC1-Q2"))
    assert yc.pool_increase_shares == 1_695_000
    assert yc.unallocated_pool_after == 1_795_000
    # The same round with more new money: the target recomputes, the absolute increase does not.
    target_increase = by_id("YC1-Q2t").expected_pool_increase
    fixture = by_id("YC1-Q2t")
    table = ovf.CapTable(securities=list(fixture.table))
    for pool in (
        pool_target_unallocated(0.10, security_id="pool_increase", holder_id="esop"),
        pool_increase(target_increase, security_id="pool_increase", holder_id="esop"),
    ):
        base = apply_priced_round(
            table,
            terms=terms(15 * M, 5 * M, "percentage_ownership_method", pool),
            protection={},
            mfn=None,
        )
        assert base.pool_increase_shares == pytest.approx(target_increase, rel=1e-12)
        bigger = apply_priced_round(
            table,
            terms=terms(15 * M, 6 * M, "percentage_ownership_method", pool),
            protection={},
            mfn=None,
        )
        fraction = bigger.unallocated_pool_after / bigger.total_post_shares
        if pool.kind == "target_unallocated_fraction":
            assert fraction == pytest.approx(0.10, rel=1e-12)
        else:
            assert bigger.pool_increase_shares == target_increase
            assert fraction < 0.10 - 1e-3


def test_a_target_below_the_existing_reserve_is_refused() -> None:
    table = ovf.CapTable(
        securities=[FOUNDERS, ovf.option_pool(5 * M, security_id="pool"), S1_ANGEL]
    )
    with pytest.raises(ValueError, match="already exceeds the target"):
        apply_priced_round(
            table,
            terms=terms(
                12 * M,
                3 * M,
                "percentage_ownership_method",
                pool_target_unallocated(0.05, security_id="inc", holder_id="esop"),
            ),
            protection={},
            mfn=None,
        )


# --- Item 3: discount-only ---------------------------------------------------------


def test_discount_safe_counts_in_the_capped_safes_company_capitalization() -> None:
    result = _run(by_id("DO2"))
    cap, discount = result.conversion("cap"), result.conversion("discount")
    assert result.post_money_safe_capitalization == pytest.approx(
        8 * M + cap.shares + discount.shares, rel=1e-12
    )
    assert cap.shares / result.post_money_safe_capitalization == pytest.approx(0.10, rel=1e-12)
    assert discount.discount_price == pytest.approx(0.8 * result.price_per_share, rel=1e-12)
    assert discount.capitalization is None and discount.cap_price is None


def test_new_safe_forms_are_refused_outside_ovf_rounds() -> None:
    with pytest.raises(ValueError, match="Mixed SAFE types"):
        ovf.solve_priced_round_with_safes(
            prior_common_shares=8 * M,
            new_money=3 * M,
            pre_money_valuation=12 * M,
            target_pool_pct=0.0,
            safes=[DISCOUNT_SAFE],  # type: ignore[list-item]
        )
    for safe in (DISCOUNT_SAFE, MFN_SAFE):
        with pytest.raises(ValueError, match="Unsupported exit instrument"):
            ovf.CapTable(securities=[FOUNDERS, safe]).waterfall(10 * M)


def test_discount_only_field_rules() -> None:
    with pytest.raises(ValidationError):
        safe_post_discount(M, 0.0, holder_id="x", security_id="x")
    with pytest.raises(ValidationError):
        safe_post_discount(M, 1.0, holder_id="x", security_id="x")
    with pytest.raises(ValidationError):
        safe_post_mfn(0.0, holder_id="x", security_id="x")


# --- Item 4: MFN ----------------------------------------------------------------------


def test_mfn_amendment_copies_one_later_safe_and_keeps_the_purchase_amount() -> None:
    amended = _run(by_id("MF-cap")).mfn_amendments
    (record,) = amended
    assert record.elected_security_id == "cap"
    assert isinstance(record.after, ovf.PostMoneySAFE)
    assert (record.after.security_id, record.after.holder_id) == ("mfn", "mfn_angel")
    assert record.after.investment_amount == M / 2
    assert (record.after.valuation_cap, record.after.discount_rate) == (10 * M, 0.0)
    (unchanged,) = _run(by_id("MF-none")).mfn_amendments
    assert unchanged.after is unchanged.before is MFN_SAFE
    (discount,) = _run(by_id("MF-disc")).mfn_amendments
    assert isinstance(discount.after, PostMoneyDiscountSAFE)
    assert discount.after.discount == 0.20


def test_which_election_is_better_depends_on_the_round() -> None:
    """At $12M pre the discount beats the cap for the MFN holder; at $48M the cap wins.

    Hand derivation (docs/rounds.md, MF): round 1 gives 1/25 (cap) and 1/24 (discount) of
    post-round shares; round 2 ($12M at $48M pre) gives 0.05 x 0.8 = 1/25 and
    0.5/(60 x 0.8) = 1/96.
    """
    assert (
        by_id("MF-disc").expected_ownership["mfn_angel"]
        > by_id("MF-cap").expected_ownership["mfn_angel"]
    )
    fractions = {}
    for elected in ("cap", "discount"):
        result = apply_priced_round(
            ovf.CapTable(securities=list(MFN_TABLE)),
            terms=terms(48 * M, 12 * M, "percentage_ownership_method", NO_POOL_CHANGE),
            protection={},
            mfn=mfn_elects(elected),
        )
        fractions[elected] = result.conversion("mfn").shares / result.total_post_shares
    assert fractions == pytest.approx({"cap": 1 / 25, "discount": 1 / 96}, rel=1e-12)


@pytest.mark.parametrize(
    ("resolution", "message"),
    [
        (
            mfn_resolution(issue_order=("cap", "mfn", "discount"), elections={"mfn": "cap"}),
            "not issued after it",
        ),
        (
            mfn_resolution(issue_order=("mfn", "cap", "discount"), elections={}),
            "must name every MFN Only Safe",
        ),
        (
            mfn_resolution(issue_order=("mfn", "cap"), elections={"mfn": "cap"}),
            "every Safe in the round exactly once",
        ),
        (
            mfn_resolution(issue_order=("mfn", "cap", "discount"), elections={"mfn": "other"}),
            "not a Safe in the round",
        ),
    ],
)
def test_bad_mfn_resolutions_are_refused(resolution: MFNResolution, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_mfn([MFN_SAFE, CAP_SAFE, DISCOUNT_SAFE], resolution)


def test_electing_another_mfn_safe_is_refused() -> None:
    later = safe_post_mfn(M, holder_id="later", security_id="later")
    with pytest.raises(ValueError, match="another MFN Only Safe"):
        resolve_mfn(
            [MFN_SAFE, later],
            mfn_resolution(issue_order=("mfn", "later"), elections={"mfn": "later", "later": None}),
        )


def test_mfn_must_be_stated_exactly_when_the_table_holds_one() -> None:
    with pytest.raises(ValueError, match="mfn must be an MFNResolution"):
        apply_priced_round(
            ovf.CapTable(securities=list(MFN_TABLE)),
            terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
            protection={},
            mfn=None,
        )
    with pytest.raises(ValueError, match="mfn must be None"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, S1_ANGEL]),
            terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
            protection={},
            mfn=mfn_resolution(issue_order=("angel",), elections={}),
        )
    with pytest.raises(ValidationError, match="more than once"):
        MFNResolution(issue_order=("a", "a"), elections={})


# --- Item 5a: mixed pre- and post-money SAFEs ----------------------------------------


def test_mixed_round_holds_both_denominators_at_once() -> None:
    result = _run(by_id("MX1"))
    post, pre = result.conversion("post"), result.conversion("pre")
    assert result.post_money_safe_capitalization == pytest.approx(
        8 * M + post.shares + pre.shares, rel=1e-12
    )
    assert result.pre_money_safe_capitalization == pytest.approx(8 * M, rel=1e-12)
    assert (post.cap_price, pre.cap_price) == pytest.approx((1.0, 1.0), rel=1e-12)
    # g'(T) for large T: 0.8 - max(1/15, 0.08) - max(1/15, 0) = 49/75.
    assert result.uniqueness_margin == pytest.approx(49 / 75, rel=1e-12)


def test_legacy_solver_still_refuses_mixed_safes() -> None:
    with pytest.raises(ValueError, match="Mixed SAFE types"):
        ovf.solve_priced_round_with_safes(
            prior_common_shares=8 * M,
            new_money=3 * M,
            pre_money_valuation=12 * M,
            target_pool_pct=0.0,
            safes=[S1_ANGEL, ovf.safe_pre(M, 8 * M, security_id="pre")],
        )


@pytest.mark.parametrize(
    "safes",
    [
        # Discount slope 10M / (15M x 0.8) = 5/6 exceeds the 0.8 left for SAFEs.
        [safe_post_discount(10 * M, 0.20, holder_id="d", security_id="d")],
        # Two caps implying 60% and 50% of Company Capitalization.
        [
            ovf.safe_post(6 * M, 10 * M, holder_id="a", security_id="a"),
            ovf.safe_post(5 * M, 10 * M, holder_id="b", security_id="b"),
        ],
        # A mixed round whose SAFEs take more than the round leaves.
        [
            ovf.safe_post(6 * M, 10 * M, holder_id="a", security_id="a"),
            ovf.safe_pre(4 * M, 2 * M, discount_rate=0.5, holder_id="b", security_id="b"),
        ],
    ],
)
def test_a_round_without_a_unique_solution_is_refused(safes: list[ovf.Security]) -> None:
    with pytest.raises(ValueError, match="No unique solution"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, *safes]),
            terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
            protection={},
            mfn=None,
        )


# --- Item 2: SAFE, then Series A, then a Series B down round -------------------------


def _series_a(safe_series: Any = "safe_preferred") -> RoundResult:
    return apply_priced_round(
        ovf.CapTable(securities=list(MR_TABLE_AFTER_SAFE)),
        terms=series_a_terms(safe_series),
        protection={},
        mfn=None,
    )


def test_multi_round_tables_after_each_event() -> None:
    after_safe = round_capitalization(ovf.CapTable(securities=list(MR_TABLE_AFTER_SAFE)))
    assert (
        after_safe.common_outstanding,
        after_safe.preferred_as_converted,
        after_safe.granted_options,
        after_safe.unallocated_pool,
    ) == (8 * M, 0, 0, M)

    a = _series_a()
    assert a.price_per_share == pytest.approx(MR_A_PRICE, rel=1e-12)
    assert a.total_post_shares == pytest.approx(MR_A_TOTAL, rel=1e-12)
    assert _as_converted(a.table) == pytest.approx(MR_A_SHARES, rel=1e-12)
    prices = {
        s.security_id: s.price for s in a.table.securities if isinstance(s, ovf.PreferredStock)
    }
    assert prices == pytest.approx(MR_A_PREFERENCE_PRICE, rel=1e-12)
    assert a.ownership_breakdown == pytest.approx(MR_A_OWNERSHIP, abs=1e-12)
    assert a.new_series_seniority == 1

    b = apply_priced_round(
        a.table, terms=series_b_terms(SENIOR_TO_ALL), protection=MR_UNPROTECTED, mfn=None
    )
    assert b.price_per_share == pytest.approx(MR_B_PRICE, rel=1e-12)
    assert b.total_post_shares == pytest.approx(MR_B_TOTAL, rel=1e-12)
    assert b.new_money_shares == pytest.approx(MR_B_NEW_SHARES, rel=1e-12)
    assert b.ownership_breakdown == pytest.approx(MR_B_OWNERSHIP, abs=1e-12)
    assert b.new_series_seniority == 0
    assert {p.security_id: p.outcome for p in b.existing_preferred} == {
        "angel": "unprotected",
        "series_a": "unprotected",
    }
    # Existing preferred is carried as the same objects, with its own terms.
    for before, now in zip(a.table.securities, b.table.securities, strict=False):
        assert now is before
    pari = apply_priced_round(
        a.table,
        terms=series_b_terms(pari_passu_with("series_a")),
        protection=MR_UNPROTECTED,
        mfn=None,
    )
    assert pari.new_series_seniority == 1


@pytest.mark.parametrize("fixture", MR_EXITS, ids=lambda f: f.case_id)
def test_multi_round_exit(fixture: ExitFixture) -> None:
    a = _series_a(fixture.safe_series)
    b = apply_priced_round(
        a.table,
        terms=series_b_terms(fixture.series_b_seniority),
        protection=MR_UNPROTECTED,
        mfn=None,
    )
    report = b.table.waterfall_detailed(fixture.exit_valuation)
    assert {p.security_id: p.amount for p in report.payouts} == pytest.approx(
        fixture.expected, abs=1e-6
    )
    survey = ovf.enumerate_equilibria(b.table.securities, fixture.exit_valuation)
    assert survey.payoff_unique
    for payoff in survey.feasible_payoffs:
        assert payoff == pytest.approx(fixture.expected, abs=1e-6)


def test_safe_series_choice_changes_the_preference_not_the_shares() -> None:
    own, joined = _series_a("safe_preferred"), _series_a("standard_preferred")
    assert own.conversion("angel").shares == joined.conversion("angel").shares
    assert own.conversion("angel").position.invested_capital == pytest.approx(M, rel=1e-12)
    assert joined.conversion("angel").position.invested_capital == pytest.approx(
        7 * M / 6, rel=1e-12
    )
    assert joined.conversion("angel").series == "standard_preferred"


# --- Anti-dilution inside a round -----------------------------------------------------


def test_a_triggered_protected_position_refuses_the_round() -> None:
    a = _series_a()
    with pytest.raises(ValueError, match="series_a: its weighted average protection would be"):
        apply_priced_round(
            a.table,
            terms=series_b_terms(SENIOR_TO_ALL),
            protection={"angel": UNPROTECTED, "series_a": BROAD},
            mfn=None,
        )


def test_a_protected_position_not_triggered_is_carried_unchanged() -> None:
    """Up round: $5M at $30M pre over 90M/7 shares is $7/3, above $7/6 and $1.00."""
    a = _series_a()
    up = apply_priced_round(
        a.table,
        terms=terms(
            30 * M,
            5 * M,
            "percentage_ownership_method",
            NO_POOL_CHANGE,
            new_series=series("series_b", SENIOR_TO_ALL),
        ),
        protection={"angel": FULL_RATCHET, "series_a": BROAD},
        mfn=None,
    )
    assert up.price_per_share == pytest.approx(7 / 3, rel=1e-12)
    assert {p.security_id: p.outcome for p in up.existing_preferred} == {
        "angel": "not_triggered",
        "series_a": "not_triggered",
    }
    for before, now in zip(a.table.securities, up.table.securities, strict=False):
        assert now is before


def test_a_safe_converting_below_a_protected_price_refuses_the_round() -> None:
    """Up round for new money, but the SAFE's cap price is below Seed's $1.50."""
    seed = ovf.preferred(2 * M, 1.50, seniority=2, holder_id="seed", security_id="seed")
    table = ovf.CapTable(securities=[FOUNDERS, seed, S1_ANGEL])
    round_terms = terms(24 * M, 6 * M, "percentage_ownership_method", NO_POOL_CHANGE)
    with pytest.raises(ValueError, match="seed: its full ratchet protection would be"):
        apply_priced_round(table, terms=round_terms, protection={"seed": FULL_RATCHET}, mfn=None)
    carried = apply_priced_round(
        table, terms=round_terms, protection={"seed": UNPROTECTED}, mfn=None
    )
    assert carried.price_per_share > 1.50 > carried.conversion("angel").conversion_price


def test_every_preferred_position_must_be_classified() -> None:
    a = _series_a()
    b_terms = series_b_terms(SENIOR_TO_ALL)
    with pytest.raises(ValueError, match="missing: angel"):
        apply_priced_round(a.table, terms=b_terms, protection={"series_a": UNPROTECTED}, mfn=None)
    with pytest.raises(ValueError, match="not preferred stock in the table: common"):
        apply_priced_round(
            a.table, terms=b_terms, protection={**MR_UNPROTECTED, "common": UNPROTECTED}, mfn=None
        )
    with pytest.raises(ValueError, match="must be an AntiDilutionProtection"):
        apply_priced_round(
            a.table,
            terms=b_terms,
            protection={"angel": UNPROTECTED, "series_a": "none"},  # type: ignore[dict-item]
            mfn=None,
        )


# --- Seniority placement ------------------------------------------------------------


def test_seniority_placement_refusals() -> None:
    table = ovf.CapTable(securities=[FOUNDERS, S1_ANGEL])
    with pytest.raises(ValueError, match="the table has none"):
        apply_priced_round(
            table,
            terms=terms(
                12 * M,
                3 * M,
                "percentage_ownership_method",
                NO_POOL_CHANGE,
                new_series=series(seniority=SENIOR_TO_ALL),
            ),
            protection={},
            mfn=None,
        )
    top = ovf.preferred(M, 1.0, seniority=0, holder_id="top", security_id="top")
    with pytest.raises(ValueError, match="cannot rank ahead of seniority 0"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, top]),
            terms=series_b_terms(SENIOR_TO_ALL),
            protection={"top": UNPROTECTED},
            mfn=None,
        )
    with pytest.raises(ValueError, match="not a preferred position in the table"):
        apply_priced_round(
            table,
            terms=terms(
                12 * M,
                3 * M,
                "percentage_ownership_method",
                NO_POOL_CHANGE,
                new_series=series(seniority=pari_passu_with("common")),
            ),
            protection={},
            mfn=None,
        )
    for bad in (
        {"kind": "senior_to_all", "security_id": "x", "seniority": None},
        {"kind": "pari_passu_with", "security_id": None, "seniority": None},
        {"kind": "explicit", "security_id": None, "seniority": None},
        {"kind": "explicit", "security_id": None, "seniority": -1},
    ):
        with pytest.raises(ValidationError):
            SeniorityPlacement(**bad)


# --- Refused input ------------------------------------------------------------------


def test_unsupported_tables_are_refused() -> None:
    note = convertible_note(
        500_000,
        0.06,
        accrual="simple",
        day_count="actual/365_fixed",
        issue_date=date(2026, 1, 1),
        maturity_date=date(2028, 1, 1),
        seniority=0,
        qualified_financing_threshold=1_000_000,
        security_id="note",
    )
    pik = ovf.preferred(
        M,
        1.0,
        holder_id="pik",
        security_id="pik",
        dividend=ovf.cumulative_dividend(
            0.08,
            accrual="simple",
            day_count="actual/365_fixed",
            accrues_from=date(2025, 1, 1),
            settlement="paid_in_kind",
        ),
    )
    round_terms = terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE)
    with pytest.raises(ValueError, match="convertible note converting in a priced round"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, note]), terms=round_terms, protection={}, mfn=None
        )
    with pytest.raises(ValueError, match="paid-in-kind"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, pik]),
            terms=round_terms,
            protection={"pik": UNPROTECTED},
            mfn=None,
        )
    with pytest.raises(ValueError, match="must hold outstanding shares"):
        apply_priced_round(
            ovf.CapTable(securities=[S1_ANGEL]), terms=round_terms, protection={}, mfn=None
        )
    with pytest.raises(ValueError, match="table must be a CapTable"):
        apply_priced_round(
            [FOUNDERS],  # type: ignore[arg-type]
            terms=round_terms,
            protection={},
            mfn=None,
        )
    with pytest.raises(ValueError, match="terms must be a PricedRound"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS]),
            terms=None,  # type: ignore[arg-type]
            protection={},
            mfn=None,
        )
    with pytest.raises(ValueError, match="protection must be a mapping"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS]),
            terms=round_terms,
            protection=[],  # type: ignore[arg-type]
            mfn=None,
        )


def test_colliding_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="Duplicate security_id: angel"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, S1_ANGEL]),
            terms=terms(
                12 * M,
                3 * M,
                "percentage_ownership_method",
                NO_POOL_CHANGE,
                new_series=series("angel"),
            ),
            protection={},
            mfn=None,
        )
    with pytest.raises(ValueError, match="need different security_ids"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, S1_ANGEL]),
            terms=terms(
                12 * M,
                3 * M,
                "percentage_ownership_method",
                pool_target_unallocated(0.1, security_id="series_a", holder_id="esop"),
            ),
            protection={},
            mfn=None,
        )


def test_plain_debt_is_carried_and_counts_nothing() -> None:
    loan = debt(
        M,
        0.08,
        accrual="simple",
        day_count="actual/365_fixed",
        issue_date=date(2025, 1, 1),
        seniority=0,
        security_id="loan",
    )
    fixture = by_id("CS-pct")
    with_debt = apply_priced_round(
        ovf.CapTable(securities=[*fixture.table, loan]),
        terms=fixture.terms,
        protection={},
        mfn=None,
    )
    assert with_debt.capitalization == _run(fixture).capitalization
    assert with_debt.price_per_share == pytest.approx(fixture.expected_price, rel=1e-12)
    assert loan in with_debt.table.securities


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "target_unallocated_fraction", "fraction": 1.0}, "strictly in"),
        ({"kind": "target_unallocated_fraction", "fraction": 0.1, "shares": 5.0}, "no share"),
        ({"kind": "increase_by_shares", "shares": 0.0}, "positive number"),
        ({"kind": "increase_by_shares", "shares": 5.0, "fraction": 0.1}, "takes no fraction"),
        ({"kind": "none", "fraction": 0.1}, "NO_POOL_CHANGE takes no"),
        (
            {"kind": "increase_by_shares", "shares": 5.0, "security_id": None},
            "needs the security_id",
        ),
    ],
)
def test_pool_change_rules(kwargs: dict[str, Any], message: str) -> None:
    base: dict[str, Any] = {
        "fraction": None,
        "shares": None,
        "security_id": "pool",
        "holder_id": "esop",
    }
    if kwargs.get("kind") == "none":
        base.update(security_id=None, holder_id=None)
    with pytest.raises(ValidationError, match=message):
        PoolChange(**{**base, **kwargs})


def test_round_term_rules() -> None:
    with pytest.raises(ValidationError):
        terms(12 * M, 0.0, "percentage_ownership_method", NO_POOL_CHANGE)
    with pytest.raises(ValidationError):
        terms(12 * M, 3 * M, "cooley", NO_POOL_CHANGE)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="requires participating"):
        NewSeries(
            security_id="a",
            holder_id="a",
            seniority=explicit_seniority(1),
            liquidation_multiple=1.0,
            participating=False,
            participation_cap=2.0,
        )


# --- Inputs that must be stated; provenance -----------------------------------------


@pytest.mark.parametrize(
    "function",
    [
        apply_priced_round,
        round_capitalization,
        pool_target_unallocated,
        pool_increase,
        pari_passu_with,
        explicit_seniority,
        resolve_mfn,
        mfn_resolution,
        safe_post_discount,
        safe_post_mfn,
    ],
)
def test_public_functions_have_no_default_arguments(function: object) -> None:
    assert callable(function)
    for parameter in inspect.signature(function).parameters.values():
        assert parameter.default is inspect.Parameter.empty, parameter.name


@pytest.mark.parametrize(
    "model", [PricedRound, PoolChange, NewSeries, SeniorityPlacement, MFNResolution]
)
def test_round_facts_have_no_default_fields(model: type) -> None:
    for name, info in model.model_fields.items():
        assert info.is_required(), name


def test_new_safe_forms_have_no_default_economic_fields() -> None:
    for model, names in (
        (PostMoneyDiscountSAFE, ("investment_amount", "discount")),
        (PostMoneyMFNSAFE, ("investment_amount",)),
    ):
        for name in names:
            assert model.model_fields[name].is_required(), name


def test_result_carries_a_stable_hash_and_its_assumptions() -> None:
    first, again = _run(by_id("CM-pct")), _run(by_id("CM-pct"))
    assert first.engine_version == ENGINE_VERSION == "rounds-v1"
    assert len(first.input_hash) == 64 and first.input_hash == again.input_hash
    assert first.input_hash != _run(by_id("CM-dol")).input_hash
    assert any("percentage-ownership" in line for line in first.assumptions)
    assert any("dollars-invested" in line for line in _run(by_id("CM-dol")).assumptions)
    assert first.iterations >= 1


@pytest.mark.parametrize("module", ["rounds.py", "contracts/safes.py"])
def test_no_clock_is_read(module: str) -> None:
    path = Path(__file__).resolve().parents[1] / "src" / "ovf" / module
    source = path.read_text(encoding="utf-8")
    for call in ("today(", ".now(", "utcnow(", "time.time(", "monotonic("):
        assert call not in source, f"{module} reads a clock via {call}"


def test_cooley_inputs_are_the_article_assumptions() -> None:
    """$8M pre, $2M new, $1M of Safes at a 30% discount, 1,000,000 shares outstanding."""
    assert COOLEY_FOUNDERS.shares == M
    assert (COOLEY_SAFE.investment_amount, COOLEY_SAFE.discount) == (M, 0.30)


def test_new_safe_forms_carry_their_purchase_amount() -> None:
    for safe in (DISCOUNT_SAFE, MFN_SAFE):
        assert safe.is_convertible()
        assert safe.invested_capital == safe.investment_amount
        assert safe.base_liquidation_preference() == safe.investment_amount


def test_resolve_mfn_rejects_malformed_input() -> None:
    order = mfn_resolution(issue_order=("mfn", "cap"), elections={"mfn": None})
    with pytest.raises(ValueError, match="must be an MFNResolution"):
        resolve_mfn([MFN_SAFE, CAP_SAFE], None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="is not a Safe form"):
        resolve_mfn([MFN_SAFE, FOUNDERS], order)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="Duplicate Safe security_id"):
        resolve_mfn([MFN_SAFE, MFN_SAFE], order)
    with pytest.raises(ValidationError, match="must list every Safe"):
        MFNResolution(issue_order=(), elections={})


class _Warrant(ovf.Security):
    """An instrument the round has no rule for."""

    def is_convertible(self) -> bool:
        return True

    def base_liquidation_preference(self) -> float:
        return 0.0


def test_remaining_refusals_and_lookups() -> None:
    with pytest.raises(ValidationError, match="cannot be below liquidation_multiple"):
        NewSeries(
            security_id="a",
            holder_id="a",
            seniority=explicit_seniority(1),
            liquidation_multiple=2.0,
            participating=True,
            participation_cap=1.5,
        )
    with pytest.raises(KeyError):
        _run(by_id("CS-pct")).conversion("nobody")
    with pytest.raises(ValueError, match="no defined place in a round"):
        round_capitalization(
            ovf.CapTable(
                securities=[FOUNDERS, _Warrant(security_id="w", holder_id="w", shares=1.0)]
            )
        )
    free = ovf.preferred(M, 0.0, holder_id="free", security_id="free")
    with pytest.raises(ValueError, match="free: protected preferred needs a positive"):
        apply_priced_round(
            ovf.CapTable(securities=[FOUNDERS, free]),
            terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
            protection={"free": BROAD},
            mfn=None,
        )
