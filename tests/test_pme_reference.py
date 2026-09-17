"""Independent oracle self-tests, hand fixtures, then production differential tests.

Section 1 was run successfully before any production PME file was inspected.
See docs/pme-fixtures.md for derivations, source precision and independence limits.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, getcontext, localcontext
from fractions import Fraction as Q
from importlib import import_module
from types import SimpleNamespace

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from . import pme_oracle as oracle
from .pme_fixtures import (
    BY_ID,
    MPME_BY_ID,
    MPME_FIXTURES,
    PME_FIXTURES,
    Y0,
    Y1,
    Y2,
    MpmeFixture,
    PmeFixture,
    series,
)

CONVENTIONS = ("ACT/365F", "ACT/365.25", "ACT/ACT-ISDA")
LOOKUP = {"lookup": "exact", "max_gap_days": 0}


def oracle_resolve(fixture: PmeFixture) -> oracle.Resolved:
    return oracle.resolve(
        fixture.flows, as_of=fixture.as_of, nav=fixture.nav, stale_nav=fixture.stale_nav
    )


def decimal_close(actual: Decimal, expected: object) -> None:
    with localcontext() as ctx:
        ctx.prec = 60
        assert abs(actual - oracle.dec(expected)) <= Decimal("1e-35")


# Section 1: oracle alone. No production imports in these tests or their helpers.


@pytest.mark.parametrize("fixture", PME_FIXTURES, ids=lambda f: f.case_id)
def test_oracle_reference_fixture(fixture: PmeFixture) -> None:
    expected = fixture.expected
    assert fixture.reviewed_by == ""
    if expected.get("refused"):
        with pytest.raises(ValueError, match="negative rolled NAV"):
            oracle_resolve(fixture)
        return
    resolved = oracle_resolve(fixture)
    result = oracle.fund_irr(resolved, day_count=fixture.day_count)
    for key in ("status", "complete"):
        if key in expected:
            assert getattr(result, key) == expected[key]
    if "irr" in expected:
        if expected["irr"] is None:
            assert result.irr is None
        else:
            decimal_close(result.irr, expected["irr"])
    if "roots" in expected:
        assert len(result.roots) == len(expected["roots"])
        for actual, root in zip(result.roots, expected["roots"], strict=True):
            decimal_close(actual, root)
    if "year_fraction" in expected:
        assert (
            oracle.year_fraction(fixture.amounts[0][0], fixture.as_of, convention=fixture.day_count)
            == expected["year_fraction"]
        )
    for key in (
        "residual",
        "contributions_after",
        "distributions_after",
        "net_by_date",
        "netted_to_zero",
    ):
        if key in expected:
            assert getattr(resolved, key) == expected[key]
    multiples = oracle.multiples(resolved)
    for key in ("tvpi", "dpi", "rvpi"):
        if key in expected:
            assert multiples[key] == expected[key]
    if not fixture.levels:
        return
    ks = oracle.ks_pme(resolved, fixture.levels, **LOOKUP)
    alpha = oracle.direct_alpha(resolved, fixture.levels, day_count=fixture.day_count, **LOOKUP)
    plus = oracle.pme_plus(resolved, fixture.levels, day_count=fixture.day_count, **LOOKUP)
    ln = oracle.ln_pme(resolved, fixture.levels, day_count=fixture.day_count, **LOOKUP)
    assert ks == expected["ks"]
    assert plus.scale == expected["scale"]
    assert plus.identity_residual == 0
    assert ln.terminal == ln.closed_form == expected["ln_terminal"]
    if "alpha" in expected:
        decimal_close(alpha.irr, expected["alpha"])
    for key in ("positions", "went_short", "first_short_date", "minimum_position"):
        if key in expected:
            assert getattr(ln, key) == expected[key]
    if "icm_roots" in expected:
        assert ln.irr.status == expected["icm_status"]
        assert ln.irr.complete == expected["icm_complete"]
        assert ln.irr.irr == expected["icm_irr"]
        assert len(ln.irr.roots) == len(expected["icm_roots"])
        for actual, root in zip(ln.irr.roots, expected["icm_roots"], strict=True):
            decimal_close(actual, root)


@pytest.mark.parametrize("convention", CONVENTIONS)
def test_oracle_two_flow_closed_form_and_day_count_additivity(convention: str) -> None:
    start, middle, end = date(2019, 7, 1), date(2020, 2, 29), date(2020, 7, 1)
    t = oracle.year_fraction(start, end, convention=convention)
    assert t == (
        oracle.year_fraction(start, middle, convention=convention)
        + oracle.year_fraction(middle, end, convention=convention)
    )
    assert -t == oracle.year_fraction(end, start, convention=convention)
    with localcontext() as ctx:
        ctx.prec = 60
        expected = (Decimal("1.21").ln() / oracle.dec(t)).exp() - 1
    result = oracle.xirr(series((start, -100), (end, 121)), day_count=convention)
    decimal_close(result.irr, expected)


def test_oracle_quadratic_roots_and_tangent() -> None:
    result = oracle.xirr(series((Y0, -100), (Y1, 230), (Y2, -132)), day_count="ACT/365F")
    assert result.status == "multiple" and result.complete
    for actual, expected in zip(result.roots, (Decimal(".1"), Decimal(".2")), strict=True):
        decimal_close(actual, expected)
    tangent = oracle.xirr(series((Y0, -100), (Y1, 200), (Y2, -100)), day_count="ACT/365F")
    assert tangent.kinds == ("tangent",)
    assert tangent.status == "undetermined" and not tangent.complete and tangent.irr is None


def test_oracle_explicitly_flags_roots_missed_by_grid() -> None:
    # Two crossings at ln(1.101), ln(1.102) both lie between .09 and .10.
    close_pair = series((Y0, -1), (Y1, "2.203"), (Y2, "-1.213302"))
    outside = series((Y0, -1), (Y1, 10**10))
    for amounts in (close_pair, outside):
        result = oracle.xirr(amounts, day_count="ACT/365F")
        assert result.status == "undetermined" and not result.complete
        assert result.grid_inconclusive and result.irr is None


def test_oracle_lookup_and_missing_nav() -> None:
    levels = series(("2021-01-01", 100), ("2021-01-04", 105))
    assert oracle.index_level(
        levels, date(2021, 1, 3), lookup="last_on_or_before", max_gap_days=2
    ) == (Y0, Q(100), 2)
    for lookup, gap in (("exact", 0), ("last_on_or_before", 1)):
        with pytest.raises(ValueError):
            oracle.index_level(levels, date(2021, 1, 3), lookup=lookup, max_gap_days=gap)
    resolved = oracle.resolve(BY_ID["PME-F6"].flows, as_of=Y2, nav=None, stale_nav="refuse")
    assert oracle.multiples(resolved) == {"dpi": Q(3, 10), "rvpi": None, "tvpi": None}
    with pytest.raises(ValueError, match="residual"):
        oracle.fund_irr(resolved, day_count="ACT/365F")


def test_oracle_preserves_global_decimal_context() -> None:
    context = getcontext().copy()
    oracle.fund_irr(oracle_resolve(BY_ID["PME-F1"]), day_count="ACT/365F")
    assert getcontext().prec == context.prec
    assert getcontext().rounding == context.rounding
    assert getcontext().flags == context.flags


def test_oracle_zero_residual_adds_no_empty_terminal_date() -> None:
    fixture = replace(BY_ID["PME-F6"], nav=(Y2, Q(0)))
    assert oracle_resolve(fixture).netted_to_zero == ()


def test_oracle_constant_index_and_reciprocal_scale() -> None:
    fixture = BY_ID["PME-F6"]
    resolved = oracle_resolve(fixture)
    alpha = oracle.direct_alpha(resolved, fixture.levels, day_count="ACT/365F", **LOOKUP)
    assert alpha == oracle.fund_irr(resolved, day_count="ACT/365F")
    fixture = BY_ID["PME-F8"]
    resolved = oracle_resolve(fixture)
    plus = oracle.pme_plus(resolved, fixture.levels, day_count="ACT/365F", **LOOKUP)
    assert oracle.ks_pme(resolved, fixture.levels, **LOOKUP) == 1 / plus.scale


def oracle_mpme(fixture: MpmeFixture) -> oracle.Mpme:
    return oracle.mpme(
        oracle_resolve(fixture),
        fixture.nav_history,
        fixture.levels,
        day_count=fixture.day_count,
        interim_nav=fixture.interim_nav,
        max_nav_gap_days=fixture.max_nav_gap_days,
        **LOOKUP,
    )


@pytest.mark.parametrize("fixture", MPME_FIXTURES, ids=lambda f: f.case_id)
def test_oracle_mpme_reference_fixture(fixture: MpmeFixture) -> None:
    expected = fixture.expected
    assert fixture.reviewed_by == ""
    if expected.get("refused"):
        with pytest.raises(ValueError, match=expected["refused"]) as refusal:
            oracle_mpme(fixture)
        assert str(expected["refused_date"]) in str(refusal.value)
        return
    result = oracle_mpme(fixture)
    for key, field in (
        ("before", "position_before_sale"),
        ("weights", "weight"),
        ("sales", "mpme_distribution"),
        ("after", "position_after"),
        ("fund_navs", "fund_nav"),
        ("sources", "fund_nav_source"),
        ("observation_dates", "fund_nav_observation_date"),
    ):
        assert tuple(getattr(step, field) for step in result.path) == expected[key]
    assert result.terminal_value == expected["after"][-1]
    assert result.mpme_series == expected["mpme_series"]
    assert result.max_nav_gap_used_days == expected["max_nav_gap_used_days"]
    for name in ("mpme_irr", "fund_irr"):
        irr = getattr(result, name)
        assert irr.status == "unique" and irr.complete
        decimal_close(irr.irr, expected[name])
    for name in ("spread", "log_spread"):
        if name in expected:
            decimal_close(getattr(result, name), expected[name])
    for step in result.path:
        assert 0 <= step.weight <= 1
        assert step.mpme_distribution >= 0 and step.position_after >= 0
        assert step.mpme_distribution + step.position_after == step.position_before_sale
        if step.distribution and step.fund_nav == 0:
            assert step.weight == 1 and step.position_after == 0
    if expected.get("tracking"):
        assert all(step.mpme_distribution == step.distribution for step in result.path)
        assert result.terminal_value == fixture.nav[1]
        assert result.mpme_irr == result.fund_irr
        assert result.spread == result.log_spread == 0
    if "ln_positions" in expected:
        icm = oracle.ln_pme(
            oracle_resolve(fixture), fixture.levels, day_count=fixture.day_count, **LOOKUP
        )
        assert icm.positions == expected["ln_positions"]
        assert icm.went_short and icm.minimum_position == -44


@pytest.mark.parametrize(
    "changes,reason",
    (
        ({"nav_history": ()}, "nonempty"),
        ({"nav_history": series((Y1, 10), (Y1, 10))}, "unique"),
        ({"nav_history": series((date(2024, 1, 1), 10))}, "on or before as_of"),
        ({"nav_history": series((Y1, -1))}, "nonnegative"),
        ({"nav_history": series((Y1, 10), (Y2, 11))}, "equal the resolved residual"),
        ({"max_nav_gap_days": 1}, "maximum interim NAV gap"),
        ({"max_nav_gap_days": -1}, "maximum interim NAV gap"),
        ({"interim_nav": "guess"}, "unknown interim NAV policy"),
        ({"nav": None}, "requires NAV"),
        ({"amounts": series((Y1, 150))}, "positive paid-in"),
        (
            {
                "nav_history": series((Y2, 10)),
                "interim_nav": "roll_forward_cash_adjusted",
                "max_nav_gap_days": 400,
            },
            "no earlier interim NAV for 2022-01-01",
        ),
    ),
)
def test_oracle_mpme_input_refusals(changes, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        oracle_mpme(replace(MPME_BY_ID["PME-F17"], **changes))


def test_oracle_mpme_latest_mark_and_exact_mark_take_precedence() -> None:
    fixture = MPME_BY_ID["PME-F16a"]
    # A NAV date needs no index level. Jan 10 is later than the original Jan 1 mark.
    observed = date(2021, 1, 10)
    latest = replace(fixture, nav_history=(*fixture.nav_history, (observed, Q(110))))
    result = oracle_mpme(latest)
    assert result.path[2].fund_nav == 80  # 110 - Jan 11 distribution 30.
    assert result.path[2].fund_nav_observation_date == observed
    assert result.max_nav_gap_used_days == 1
    exact = replace(latest, nav_history=(*latest.nav_history, (date(2021, 1, 11), Q(110))))
    result = oracle_mpme(exact)
    assert result.path[2].fund_nav_source == "reported"
    assert result.path[2].fund_nav == 110
    assert result.path[2].weight == Q(3, 14)
    assert result.path[2].mpme_distribution == Q(165, 7)
    assert result.path[2].position_after == Q(605, 7)
    assert result.max_nav_gap_used_days == 0


def test_oracle_mpme_fund_irr_refusal_preserves_reconstruction() -> None:
    fixture = replace(
        MPME_BY_ID["PME-F17"],
        amounts=series((Y0, -100), (Y0, 100)),
        nav=(Y2, Q(0)),
        nav_history=series((Y0, 100)),
    )
    result = oracle_mpme(fixture)
    assert result.fund_irr is None and result.spread is None and result.log_spread is None
    assert result.terminal_value == Q(121, 2)
    assert result.mpme_series == series((Y0, -50), (Y2, Q(121, 2)))
    decimal_close(result.mpme_irr.irr, Q(1, 10))


# Section 2: every named fixture against the production public API and oracle.


@pytest.fixture(scope="module")
def engine() -> SimpleNamespace:
    # Intentionally no importorskip: absent concurrent modules are real failures.
    return SimpleNamespace(
        **{
            name: import_module(f"ovf.pme.{name}")
            for name in ("daycount", "flows", "irr", "benchmark", "metrics", "pme", "mpme")
        }
    )


def engine_resolve(fixture: PmeFixture, engine: SimpleNamespace):
    f = engine.flows
    fund = f.FundCashFlows(
        name=fixture.case_id,
        currency="USD",
        basis="net_lp",
        flows=tuple(
            f.CashFlow(date=flow.date, kind=flow.kind, amount=float(flow.amount))
            for flow in fixture.flows
        ),
        nav=(
            f.NavObservation(date=fixture.nav[0], value=float(fixture.nav[1]))
            if fixture.nav is not None
            else None
        ),
    )
    return f.resolve(fund, as_of=fixture.as_of, stale_nav=fixture.stale_nav)


def engine_benchmark(fixture: PmeFixture, engine: SimpleNamespace):
    return engine.benchmark.BenchmarkIndex(
        name="reference index",
        currency="USD",
        return_basis="total_return_net",
        levels=tuple(
            engine.benchmark.IndexLevel(date=d, level=float(v)) for d, v in fixture.levels
        ),
    )


def ratio_close(actual: float | None, expected: object) -> None:
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(float(expected), rel=1e-9, abs=0)


def rate_close(actual: float | None, expected: object) -> None:
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(float(expected), rel=0, abs=1e-9)


def compare_irr(actual, expected: oracle.Irr) -> None:
    assert actual.sign_changes == expected.sign_changes
    if expected.grid_inconclusive and "tangent" not in expected.kinds:
        # We cannot compare complete root sets, but a crossing already found is real.
        for root in expected.roots:
            assert any(abs(found.rate - float(root)) <= 1e-9 for found in actual.roots)
        return
    assert actual.status == expected.status
    assert actual.complete == expected.complete
    rate_close(actual.irr, expected.irr)
    assert len(actual.roots) == len(expected.roots)
    for found, reference, kind in zip(actual.roots, expected.roots, expected.kinds, strict=True):
        rate_close(found.rate, reference)
        assert found.kind == kind
        assert not found.rate_clamped  # All roots here are representable above -1.
        assert 0 <= found.relative_residual <= actual.tolerance


def compare_fixture(fixture: PmeFixture, engine: SimpleNamespace) -> dict[str, object]:
    resolved = engine_resolve(fixture, engine)
    reference = oracle_resolve(fixture)
    for key, expected in (
        ("paid_in", reference.paid_in),
        ("distributed", reference.distributed),
        ("residual_value", reference.residual),
    ):
        ratio_close(getattr(resolved, key), expected)
    assert resolved.nav_source == reference.nav_source
    assert resolved.netted_to_zero == reference.netted_to_zero
    assert len(resolved.net_by_date) == len(reference.net_by_date)
    for actual, (d, a) in zip(resolved.net_by_date, reference.net_by_date, strict=True):
        assert actual.date == d
        ratio_close(actual.amount, a)
    if reference.nav_source == "rolled_forward":
        ratio_close(resolved.nav_roll_forward.contributions_after, reference.contributions_after)
        ratio_close(resolved.nav_roll_forward.distributions_after, reference.distributions_after)
    multiples = engine.metrics.multiples(resolved)
    for key, expected in oracle.multiples(reference).items():
        ratio_close(getattr(multiples, key), expected)
    for key in ("tvpi", "dpi", "rvpi"):
        if key in fixture.expected:
            ratio_close(getattr(multiples, key), fixture.expected[key])
    irr = engine.irr.fund_irr(resolved, day_count=fixture.day_count)
    compare_irr(irr, oracle.fund_irr(reference, day_count=fixture.day_count))
    raw = tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in fixture.amounts)
    raw += (engine.flows.DatedAmount(date=fixture.as_of, amount=float(reference.residual)),)
    compare_irr(
        engine.irr.xirr(raw, day_count=fixture.day_count),
        oracle.fund_irr(reference, day_count=fixture.day_count),
    )
    if "irr" in fixture.expected:
        rate_close(irr.irr, fixture.expected["irr"])
    for key in ("status", "complete"):
        if key in fixture.expected:
            assert getattr(irr, key) == fixture.expected[key]
    result = {"resolved": resolved, "multiples": multiples, "irr": irr}
    if not fixture.levels:
        return result
    benchmark = engine_benchmark(fixture, engine)
    for d in {f.date for f in fixture.flows} | {fixture.as_of}:
        found = engine.benchmark.index_level(benchmark, d, **LOOKUP)
        used, level, gap = oracle.index_level(fixture.levels, d, **LOOKUP)
        assert found.used == used and found.gap_days == gap
        ratio_close(found.level, level)
    kws = {**LOOKUP, "day_count": fixture.day_count}
    ks = engine.pme.ks_pme(resolved, benchmark, **LOOKUP)
    alpha = engine.pme.direct_alpha(resolved, benchmark, **kws)
    plus = engine.pme.pme_plus(resolved, benchmark, **kws)
    ln = engine.pme.ln_pme(resolved, benchmark, **kws)
    for method in (ks, alpha, plus, ln):
        assert method.max_gap_used_days == 0
        assert all(flow.index_gap_days == 0 for flow in method.flows)
    reference_ks = oracle.ks_pme(reference, fixture.levels, **LOOKUP)
    reference_alpha = oracle.direct_alpha(reference, fixture.levels, **kws)
    reference_plus = oracle.pme_plus(reference, fixture.levels, **kws)
    reference_ln = oracle.ln_pme(reference, fixture.levels, **kws)
    ratio_close(ks.ks_pme, reference_ks)
    compare_irr(alpha.irr, reference_alpha)
    rate_close(alpha.alpha_annual_effective, reference_alpha.irr)
    rate_close(
        alpha.alpha_continuous,
        reference_alpha.log_roots[0] if reference_alpha.irr is not None else None,
    )
    ratio_close(plus.scale, reference_plus.scale)
    assert plus.scale_negative == (reference_plus.scale is not None and reference_plus.scale < 0)
    if reference_plus.irr is None:
        assert plus.pme_plus_irr is None
    else:
        compare_irr(plus.pme_plus_irr, reference_plus.irr)
    compare_irr(plus.fund_irr, reference_plus.fund_irr)
    if reference_plus.irr is None or reference_plus.irr.complete:
        rate_close(plus.spread, reference_plus.spread)
        rate_close(plus.log_spread, reference_plus.log_spread)
    assert plus.identity_residual == pytest.approx(0, rel=0, abs=1e-9)
    # ICM positions are differences of index-grown flows. An exact rational zero comes out
    # of float arithmetic as cancellation noise (82 * (56 / 82) - 56 = 7.1e-15), so a purely
    # relative comparison against the oracle's exact 0 cannot hold. The absolute tolerance
    # scales with the gross grown magnitude the position is computed from; it is not zero.
    levels = [level for _, level in fixture.levels]
    position_scale = float(
        (reference.paid_in + reference.distributed + abs(reference.residual))
        * max(levels)
        / min(levels)
    )

    def position_close(actual: float | None, expected: object) -> None:
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(float(expected), rel=1e-9, abs=1e-12 * position_scale)

    position_close(ln.terminal_value_recursive, reference_ln.terminal)
    position_close(ln.terminal_value_closed_form, reference_ln.closed_form)
    assert ln.reconciliation_residual == pytest.approx(0, rel=0, abs=1e-9)
    assert ln.went_short == reference_ln.went_short
    assert ln.first_short_date == reference_ln.first_short_date
    position_close(ln.min_position, reference_ln.minimum_position)
    assert len(ln.path) == len(reference_ln.positions)
    for step, (d, position) in zip(ln.path, reference_ln.positions, strict=True):
        assert step.date == d
        position_close(step.position_after, position)
    compare_irr(ln.icm_irr, reference_ln.irr)
    if reference_ln.irr.complete:
        rate_close(ln.spread, reference_ln.spread)
        rate_close(ln.log_spread, reference_ln.log_spread)
    for key, actual in (
        ("ks", ks.ks_pme),
        ("scale", plus.scale),
        ("ln_terminal", ln.terminal_value_recursive),
    ):
        if key in fixture.expected:
            ratio_close(actual, fixture.expected[key])
    if "alpha" in fixture.expected:
        rate_close(alpha.alpha_annual_effective, fixture.expected["alpha"])
    result.update(ks=ks, alpha=alpha, plus=plus, ln=ln)
    return result


@pytest.mark.parametrize("fixture", PME_FIXTURES, ids=lambda f: f.case_id)
def test_engine_reference_fixture(fixture: PmeFixture, engine: SimpleNamespace) -> None:
    if fixture.expected.get("refused"):
        with pytest.raises(ValueError):
            engine_resolve(fixture, engine)
        return
    compare_fixture(fixture, engine)


def test_engine_published_display_precision(engine: SimpleNamespace) -> None:
    f12 = BY_ID["PME-F12"]
    result = compare_fixture(f12, engine)
    assert f"{result['ks'].ks_pme:.2f}" == str(f12.expected["published_ks"])
    assert f"{100 * result['irr'].irr:.1f}" == "17.5"
    assert f"{100 * result['alpha'].alpha_annual_effective:.1f}" == "12.6"
    # F1's published 9-decimal figure is not rounded from the exact mathematical root.
    f1 = BY_ID["PME-F1"]
    with localcontext() as ctx:
        ctx.prec = 60
        error = f1.expected["published_irr"] - f1.expected["irr"]
    assert Decimal("1.48e-9") < error < Decimal("1.49e-9")


@pytest.mark.parametrize("convention", CONVENTIONS)
def test_engine_npv_independent_day_counts_and_anchor(
    convention: str, engine: SimpleNamespace
) -> None:
    amounts = BY_ID["PME-F1"].amounts
    actual_amounts = tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in amounts)
    for anchor in (date(2007, 1, 1), date(2008, 1, 1), date(2009, 1, 1)):
        expected = oracle.npv(amounts, rate=Decimal("0.07"), day_count=convention, t0=anchor)
        actual = engine.irr.npv(actual_amounts, rate=0.07, day_count=convention, t0=anchor)
        ratio_close(actual, expected)


def test_engine_degenerate_series_policy(engine: SimpleNamespace) -> None:
    for amounts in ((), series((Y0, -100)), series((Y0, -100), (Y0, 100))):
        with pytest.raises(ValueError):
            oracle.xirr(amounts, day_count="ACT/365F")
        with pytest.raises(ValueError):
            engine.irr.xirr(
                tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in amounts),
                day_count="ACT/365F",
            )
    amounts = series((Y0, -100), (Y1, -200))
    expected = oracle.xirr(amounts, day_count="ACT/365F")
    assert expected.status == "none" and expected.complete and expected.irr is None
    actual = engine.irr.xirr(
        tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in amounts),
        day_count="ACT/365F",
    )
    compare_irr(actual, expected)


def test_engine_refusals_and_missing_values(engine: SimpleNamespace) -> None:
    stale = replace(BY_ID["PME-F10a"], stale_nav="refuse")
    for resolver in (oracle_resolve, lambda f: engine_resolve(f, engine)):
        with pytest.raises(ValueError):
            resolver(stale)
    missing = replace(BY_ID["PME-F6"], nav=None)
    resolved = engine_resolve(missing, engine)
    assert engine.metrics.multiples(resolved).tvpi is None
    with pytest.raises(ValueError):
        engine.irr.fund_irr(resolved, day_count=missing.day_count)
    with pytest.raises(ValueError):
        engine.pme.ks_pme(resolved, engine_benchmark(missing, engine), **LOOKUP)
    distribution_only = replace(BY_ID["PME-F6"], amounts=series((Y0, 10), (Y1, 20)))
    resolved = engine_resolve(distribution_only, engine)
    reference = oracle_resolve(distribution_only)
    for key, value in oracle.multiples(reference).items():
        assert value is None and getattr(engine.metrics.multiples(resolved), key) is None


def test_engine_no_distributions_and_negative_pme_plus_scale(engine: SimpleNamespace) -> None:
    no_dists = replace(BY_ID["PME-F7"], amounts=series((Y0, -100)))
    negative_scale = replace(BY_ID["PME-F7"], nav=(Y2, Q(200)))
    for fixture in (no_dists, negative_scale):
        resolved = engine_resolve(fixture, engine)
        benchmark = engine_benchmark(fixture, engine)
        reference = oracle.pme_plus(
            oracle_resolve(fixture), fixture.levels, day_count=fixture.day_count, **LOOKUP
        )
        actual = engine.pme.pme_plus(resolved, benchmark, day_count=fixture.day_count, **LOOKUP)
        ratio_close(actual.scale, reference.scale)
        if reference.scale is None:
            assert actual.pme_plus_irr is None and actual.spread is None
        else:
            assert actual.scale_negative
            compare_irr(actual.pme_plus_irr, reference.irr)
            assert actual.spread is None and actual.log_spread is None
            assert reference.spread is None and reference.log_spread is None


def test_engine_lookup_never_looks_forward(engine: SimpleNamespace) -> None:
    fixture = replace(BY_ID["PME-F6"], levels=series((Y0, 100), ("2021-01-04", 105)))
    benchmark = engine_benchmark(fixture, engine)
    on = date(2021, 1, 3)
    found = engine.benchmark.index_level(benchmark, on, lookup="last_on_or_before", max_gap_days=2)
    used, level, gap = oracle.index_level(
        fixture.levels, on, lookup="last_on_or_before", max_gap_days=2
    )
    assert found.used == used and found.level == level and found.gap_days == gap
    for lookup, maximum in (("exact", 0), ("last_on_or_before", 1)):
        with pytest.raises(ValueError):
            engine.benchmark.index_level(benchmark, on, lookup=lookup, max_gap_days=maximum)


def test_engine_reverse_sign_counterexample(engine: SimpleNamespace) -> None:
    fixture = replace(
        BY_ID["PME-F6"], amounts=series((Y0, 50), (Y1, -100)), as_of=Y1, nav=(Y1, Q(0)), expected={}
    )
    result = compare_fixture(fixture, engine)
    assert result["ks"].ks_pme == 0.5
    rate_close(result["alpha"].alpha_annual_effective, 1)
    # The KS/alpha sign identity requires first net negative, not merely one sign change.


def engine_mpme(fixture: MpmeFixture, engine: SimpleNamespace):
    history = engine.mpme.FundNavHistory(
        observations=tuple(
            engine.flows.NavObservation(date=d, value=float(value))
            for d, value in fixture.nav_history
        )
    )
    return engine.mpme.mpme(
        engine_resolve(fixture, engine),
        history,
        engine_benchmark(fixture, engine),
        day_count=fixture.day_count,
        interim_nav=fixture.interim_nav,
        max_nav_gap_days=fixture.max_nav_gap_days,
        **LOOKUP,
    )


def compare_mpme(fixture: MpmeFixture, engine: SimpleNamespace):
    reference = oracle_mpme(fixture)
    actual = engine_mpme(fixture, engine)
    assert len(actual.path) == len(reference.path)
    for step, expected in zip(actual.path, reference.path, strict=True):
        for field in ("date", "fund_nav_source", "fund_nav_observation_date"):
            assert getattr(step, field) == getattr(expected, field)
        for field in (
            "index_level",
            "contribution",
            "distribution",
            "fund_nav",
            "weight",
            "position_before_sale",
            "mpme_distribution",
            "position_after",
        ):
            ratio_close(getattr(step, field), getattr(expected, field))
        assert 0 <= step.weight <= 1
        assert step.mpme_distribution >= 0 and step.position_after >= 0
        ratio_close(step.mpme_distribution + step.position_after, step.position_before_sale)
        if expected.distribution and expected.fund_nav == 0:
            assert step.weight == 1 and step.position_after == 0
    ratio_close(actual.terminal_value, reference.terminal_value)
    assert actual.max_nav_gap_used_days == reference.max_nav_gap_used_days
    assert actual.interim_nav == fixture.interim_nav
    assert actual.max_nav_gap_days == fixture.max_nav_gap_days
    assert actual.max_gap_used_days == 0
    assert len(actual.mpme_series) == len(reference.mpme_series)
    for amount, (d, value) in zip(actual.mpme_series, reference.mpme_series, strict=True):
        assert amount.date == d
        ratio_close(amount.amount, value)
    compare_irr(actual.mpme_irr, reference.mpme_irr)
    if reference.fund_irr is None:
        assert actual.fund_irr is None
        assert actual.spread is None and actual.log_spread is None
    else:
        compare_irr(actual.fund_irr, reference.fund_irr)
        if reference.fund_irr.complete and reference.mpme_irr.complete:
            rate_close(actual.spread, reference.spread)
            rate_close(actual.log_spread, reference.log_spread)
    fv_calls, fv_dists, _ = oracle.future_values(oracle_resolve(fixture), fixture.levels, **LOOKUP)
    ratio_close(actual.fv_contributions, fv_calls)
    ratio_close(actual.fv_distributions, fv_dists)
    return actual


@pytest.mark.parametrize("fixture", MPME_FIXTURES, ids=lambda f: f.case_id)
def test_engine_mpme_reference_fixture(fixture: MpmeFixture, engine: SimpleNamespace) -> None:
    if fixture.expected.get("refused"):
        with pytest.raises(ValueError, match=str(fixture.expected["refused_date"])):
            engine_mpme(fixture, engine)
        return
    actual = compare_mpme(fixture, engine)
    rate_close(actual.mpme_irr.irr, fixture.expected["mpme_irr"])
    rate_close(actual.fund_irr.irr, fixture.expected["fund_irr"])
    if fixture.expected.get("tracking"):
        for step in actual.path:
            ratio_close(step.mpme_distribution, step.distribution)
        ratio_close(actual.terminal_value, fixture.nav[1])
        rate_close(actual.spread, 0)
        rate_close(actual.log_spread, 0)
    if "ln_positions" in fixture.expected:
        icm = engine.pme.ln_pme(
            engine_resolve(fixture, engine),
            engine_benchmark(fixture, engine),
            day_count=fixture.day_count,
            **LOOKUP,
        )
        assert icm.went_short and icm.first_short_date == Y1
        for step, (on, position) in zip(icm.path, fixture.expected["ln_positions"], strict=True):
            assert step.date == on
            ratio_close(step.position_after, position)
        assert all(step.position_after >= 0 for step in actual.path)


def test_engine_mpme_nav_precedence_and_optional_fund_irr(engine: SimpleNamespace) -> None:
    fixture = MPME_BY_ID["PME-F16a"]
    latest = replace(
        fixture,
        nav_history=(*fixture.nav_history, (date(2021, 1, 10), Q(110))),
    )
    compare_mpme(latest, engine)
    compare_mpme(
        replace(latest, nav_history=(*latest.nav_history, (date(2021, 1, 11), Q(110)))),
        engine,
    )
    degenerate_fund = replace(
        MPME_BY_ID["PME-F17"],
        amounts=series((Y0, -100), (Y0, 100)),
        nav=(Y2, Q(0)),
        nav_history=series((Y0, 100)),
    )
    actual = compare_mpme(degenerate_fund, engine)
    assert actual.fund_irr is None and actual.spread is None and actual.log_spread is None


def test_engine_stated_cents_netting_does_not_change_raw_xirr(engine: SimpleNamespace) -> None:
    fixture = replace(
        BY_ID["PME-F11"],
        amounts=series(
            (Y0, -100),
            (Y1, "-100000.10"),
            (Y1, "-200000.20"),
            (Y1, "300000.30"),
            (Y2, 110),
        ),
        levels=(),
        expected={},
    )
    exact = oracle_resolve(fixture)
    resolved = engine_resolve(fixture, engine)
    assert exact.net_by_date == series((Y0, -100), (Y2, 110))
    assert exact.netted_to_zero == resolved.netted_to_zero == (Y1,)
    assert tuple((a.date, a.amount) for a in resolved.net_by_date) == exact.net_by_date
    raw = tuple((d, Q(float(amount))) for d, amount in fixture.amounts)
    nets, _ = oracle.net(raw)
    dust = dict(nets)[Y1]
    gross = sum((abs(a) for d, a in raw if d == Y1), Q())
    assert dust == Q(-1, 2**35)
    assert 0 < abs(dust) <= Q(1, 2**52) * gross
    assert any(str(Y1) in line for line in resolved.assumptions)
    compare_irr(
        engine.irr.fund_irr(resolved, day_count=fixture.day_count),
        oracle.fund_irr(exact, day_count=fixture.day_count),
    )
    raw_result = engine.irr.xirr(
        tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in raw),
        day_count=fixture.day_count,
    )
    assert {a.date: a.amount for a in raw_result.amounts}[Y1] == float(dust)
    compare_irr(raw_result, oracle.xirr(raw, day_count=fixture.day_count))

    # A genuine stated difference above the representation bound stays in the series.
    changed = replace(
        fixture,
        amounts=tuple((d, a + Q(1, 10**6) if d == Y1 and a > 0 else a) for d, a in fixture.amounts),
    )
    kept = engine_resolve(changed, engine)
    assert Y1 not in kept.netted_to_zero
    assert {a.date: a.amount for a in kept.net_by_date}[Y1] > float(Q(1, 2**52) * gross)


# Section 3: Hypothesis differential and invariance properties.


@st.composite
def mpme_fixtures(draw):
    """Random gross cash, index paths and independent end-of-day NAV histories.

    A mark preceding a distribution is constructed to have a nonnegative cash
    roll-forward. The dates are at least 180 days apart, so that short NAV gap
    contains just the distribution date's gross flows. Terminal NAV is an
    independent random mark, never an oracle/engine output.
    """
    n = draw(st.integers(3, 7))
    gaps = draw(st.lists(st.integers(180, 450), min_size=n, max_size=n))
    dates = [date(2018, 7, 1)]
    for gap in gaps:
        dates.append(dates[-1] + timedelta(days=gap))
    terminal = dates[-1]
    calls = draw(st.lists(st.integers(0, 100), min_size=n, max_size=n))
    calls[0] = draw(st.integers(20, 500))
    distributions = draw(st.lists(st.integers(0, 300), min_size=n, max_size=n))
    distributions[0] = 0
    distributions[-1] = draw(st.integers(1, 300))
    can_roll = draw(st.booleans())
    amounts, marks = [], []
    for on, call, distribution in zip(dates[:-1], calls, distributions, strict=True):
        if call:
            amounts.append((on, Q(-call)))
        if distribution:
            amounts.append((on, Q(distribution)))
            gap = draw(st.integers(0, 30)) if can_roll else 0
            value = draw(st.integers(0, 500))
            if gap:
                # observed + call - distribution >= 0, including the day's call.
                value += max(0, distribution - call)
            marks.append((on - timedelta(days=gap), Q(value)))
    terminal_nav = Q(draw(st.integers(0, 500)))
    if draw(st.booleans()):
        marks.append((terminal, terminal_nav))
    index_values = draw(st.lists(st.integers(50, 400), min_size=n + 1, max_size=n + 1))
    return MpmeFixture(
        "generated-mpme",
        "Random NAV histories independent of public index returns",
        tuple(amounts),
        terminal,
        (terminal, terminal_nav),
        draw(st.sampled_from(CONVENTIONS)),
        {},
        "Random integer cash and marks, with exact cash-adjusted interim valuations.",
        levels=tuple((d, Q(v)) for d, v in zip(dates, index_values, strict=True)),
        nav_history=tuple(reversed(marks)),
        interim_nav="roll_forward_cash_adjusted" if can_roll else "refuse",
        max_nav_gap_days=30 if can_roll else 0,
    )


@settings(max_examples=60, deadline=None)
@given(fixture=mpme_fixtures())
def test_property_mpme_engine_vs_oracle_with_random_nav_history(
    fixture: MpmeFixture,
    engine: SimpleNamespace,
) -> None:
    actual = compare_mpme(fixture, engine)
    if actual.max_nav_gap_used_days:
        refused = replace(fixture, max_nav_gap_days=actual.max_nav_gap_used_days - 1)
        with pytest.raises(ValueError) as reference_refusal:
            oracle_mpme(refused)
        # Both must refuse the first distribution whose observation exceeds the gap.
        first_bad_date = next(
            step.date
            for step in actual.path
            if step.fund_nav_observation_date is not None
            and (step.date - step.fund_nav_observation_date).days > refused.max_nav_gap_days
        )
        assert str(first_bad_date) in str(reference_refusal.value)
        with pytest.raises(ValueError, match=str(first_bad_date)):
            engine_mpme(refused, engine)


@settings(max_examples=25, deadline=None)
@given(fixture=mpme_fixtures(), scale=st.integers(2, 100))
def test_property_mpme_cash_nav_and_index_rescaling(fixture, scale, engine) -> None:
    original = compare_mpme(fixture, engine)
    variants = (
        (replace(fixture, levels=tuple((d, value * scale) for d, value in fixture.levels)), 1),
        (
            replace(
                fixture,
                amounts=tuple((d, value * scale) for d, value in fixture.amounts),
                nav=(fixture.nav[0], fixture.nav[1] * scale),
                nav_history=tuple((d, value * scale) for d, value in fixture.nav_history),
            ),
            scale,
        ),
    )
    for variant, cash_factor in variants:
        actual = compare_mpme(variant, engine)
        assert actual.mpme_irr.status == original.mpme_irr.status
        assert actual.fund_irr.status == original.fund_irr.status
        rate_close(actual.mpme_irr.irr, original.mpme_irr.irr)
        rate_close(actual.fund_irr.irr, original.fund_irr.irr)
        rate_close(actual.spread, original.spread)
        rate_close(actual.log_spread, original.log_spread)
        assert actual.max_nav_gap_used_days == original.max_nav_gap_used_days
        ratio_close(actual.terminal_value, original.terminal_value * cash_factor)
        for step, before in zip(actual.path, original.path, strict=True):
            ratio_close(step.weight, before.weight)
            ratio_close(step.mpme_distribution, before.mpme_distribution * cash_factor)
            ratio_close(step.position_after, before.position_after * cash_factor)


def test_engine_mpme_gross_splitting_and_order_do_not_change_results(engine) -> None:
    fixture = MPME_BY_ID["PME-F13"]
    original = compare_mpme(fixture, engine)
    # Split both kinds into gross legs and reverse all inputs, including NAV marks.
    divided = tuple((d, value / 2) for d, value in reversed(fixture.amounts) for _ in range(2))
    actual = compare_mpme(
        replace(fixture, amounts=divided, nav_history=tuple(reversed(fixture.nav_history))),
        engine,
    )
    assert actual.path == original.path
    assert actual.mpme_series == original.mpme_series
    rate_close(actual.mpme_irr.irr, original.mpme_irr.irr)


@st.composite
def conventional_fixtures(draw):
    n = draw(st.integers(min_value=3, max_value=7))
    split = draw(st.integers(min_value=1, max_value=n - 1))
    gaps = draw(st.lists(st.integers(180, 450), min_size=n - 1, max_size=n - 1))
    values = draw(st.lists(st.integers(20, 500), min_size=n, max_size=n))
    index_values = draw(st.lists(st.integers(50, 400), min_size=n, max_size=n))
    dates = [date(2018, 7, 1)]
    for gap in gaps:
        dates.append(dates[-1] + timedelta(days=gap))
    return PmeFixture(
        "generated",
        "Conventional net LP fund",
        tuple(
            (d, Q(-v if i < split else v))
            for i, (d, v) in enumerate(zip(dates, values, strict=True))
        ),
        dates[-1],
        (dates[-1], Q(draw(st.integers(0, 500)))),
        draw(st.sampled_from(CONVENTIONS)),
        {},
        "Generated inputs; independent rational oracle.",
        levels=tuple((d, Q(v)) for d, v in zip(dates, index_values, strict=True)),
    )


@settings(max_examples=60, deadline=None)
@given(fixture=conventional_fixtures())
def test_property_conventional_engine_vs_oracle(
    fixture: PmeFixture, engine: SimpleNamespace
) -> None:
    result = compare_fixture(fixture, engine)
    reference = oracle_resolve(fixture)
    assert reference.net_by_date[0][1] < 0
    assert result["irr"].sign_changes == 1
    ks = oracle.ks_pme(reference, fixture.levels, **LOOKUP)
    if ks != 1:
        assert (result["ks"].ks_pme > 1) == (result["alpha"].alpha_annual_effective > 0)
    start, end = fixture.amounts[0][0], fixture.as_of
    expected_t = oracle.year_fraction(start, end, convention=fixture.day_count)
    ratio_close(engine.daycount.year_fraction(start, end, convention=fixture.day_count), expected_t)


@settings(max_examples=25, deadline=None)
@given(fixture=conventional_fixtures(), scale=st.integers(2, 100))
def test_property_cash_and_index_rescaling(fixture, scale, engine: SimpleNamespace) -> None:
    original = compare_fixture(fixture, engine)
    variants = (
        replace(fixture, levels=tuple((d, value * scale) for d, value in fixture.levels)),
        replace(
            fixture,
            amounts=tuple((d, value * scale) for d, value in fixture.amounts),
            nav=(fixture.nav[0], fixture.nav[1] * scale),
        ),
    )
    for changed in variants:
        actual = compare_fixture(changed, engine)
        ratio_close(actual["ks"].ks_pme, original["ks"].ks_pme)
        rate_close(actual["irr"].irr, original["irr"].irr)
        rate_close(actual["alpha"].alpha_annual_effective, original["alpha"].alpha_annual_effective)
        ratio_close(actual["plus"].scale, original["plus"].scale)


@settings(max_examples=60, deadline=None)
@given(
    roots=st.lists(st.integers(3, 25), min_size=2, max_size=4, unique=True),
    convention=st.sampled_from(CONVENTIONS),
)
def test_property_multiple_crossing_root_sets(roots, convention, engine: SimpleNamespace) -> None:
    # Expand product(q - k/10); this constructs varied multi-sign-change funds
    # without borrowing either root solver. Changing day count perturbs the roots.
    coefficients = [Q(1)]
    for numerator in roots:
        qroot = Q(numerator, 10)
        expanded = [Q(0)] * (len(coefficients) + 1)
        for i, coefficient in enumerate(coefficients):
            expanded[i] += coefficient
            expanded[i + 1] -= qroot * coefficient
        coefficients = expanded
    amounts = tuple(
        (date(2019, 1, 1) + timedelta(days=365 * i), -coefficient)
        for i, coefficient in enumerate(coefficients)
    )
    expected = oracle.xirr(amounts, day_count=convention)
    assume(expected.complete)  # Explicitly refuse to claim a grid proves an unseen root absent.
    actual = engine.irr.xirr(
        tuple(engine.flows.DatedAmount(date=d, amount=float(a)) for d, a in amounts),
        day_count=convention,
    )
    compare_irr(actual, expected)
