"""KS-PME, Direct Alpha, PME+ and Long-Nickels (ICM), asserted against `ovf.pme.pme`.

Hand examples use an index 100 -> 120 -> 150 on dates exactly 365 days apart, so under
ACT/365F the flow times are t = 0, 1, 2 years and every IRR is the root of a quadratic in
``y = 1 / (1 + r)``.
"""

from __future__ import annotations

import math
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from ovf.pme.benchmark import BenchmarkIndex, IndexLevel, IndexLookupRecord
from ovf.pme.flows import (
    ENGINE_VERSION,
    CashFlow,
    FundCashFlows,
    NavObservation,
    NearZeroNet,
    ResolvedCashFlows,
    resolve,
)
from ovf.pme.irr import IrrResult, fund_irr
from ovf.pme.metrics import multiples
from ovf.pme.pme import (
    DirectAlphaResult,
    FlowValuation,
    IcmStep,
    KsPmeResult,
    LnPmeResult,
    PmePlusResult,
    direct_alpha,
    ks_pme,
    ln_pme,
    pme_plus,
)

DAY_COUNT = "ACT/365F"
T0 = date(2021, 1, 1)
T1 = date(2022, 1, 1)  # 365 days after T0: t = 1
T2 = date(2023, 1, 1)  # 730 days after T0: t = 2

Flow = tuple[date, str, float]


def _fund(
    flows: list[Flow], nav: tuple[date, float] | None, *, currency: str = "USD"
) -> FundCashFlows:
    return FundCashFlows(
        name="Fund I",
        currency=currency,
        basis="net_lp",
        flows=tuple(CashFlow(date=d, kind=k, amount=a) for d, k, a in flows),  # type: ignore[arg-type]
        nav=None if nav is None else NavObservation(date=nav[0], value=nav[1]),
    )


def _resolved(
    flows: list[Flow], nav: tuple[date, float] | None, *, as_of: date = T2
) -> ResolvedCashFlows:
    return resolve(_fund(flows, nav), as_of=as_of, stale_nav="refuse")


def _index(
    levels: list[tuple[date, float]], *, currency: str = "USD", basis: str = "total_return_net"
) -> BenchmarkIndex:
    return BenchmarkIndex(
        name="MSCI World NR",
        currency=currency,
        return_basis=basis,  # type: ignore[arg-type]
        levels=tuple(IndexLevel(date=d, level=v) for d, v in levels),
    )


INDEX = _index([(T0, 100.0), (T1, 120.0), (T2, 150.0)])
FLAT = _index([(T0, 100.0), (T1, 100.0), (T2, 100.0)])

METHODS: dict[str, Any] = {
    "ks_pme": ks_pme,
    "direct_alpha": partial(direct_alpha, day_count=DAY_COUNT),
    "pme_plus": partial(pme_plus, day_count=DAY_COUNT),
    "ln_pme": partial(ln_pme, day_count=DAY_COUNT),
}


def _run_all(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    *,
    lookup: str = "exact",
    max_gap_days: int = 0,
) -> tuple[KsPmeResult, DirectAlphaResult, PmePlusResult, LnPmeResult]:
    policy = {"lookup": lookup, "max_gap_days": max_gap_days}
    return (
        ks_pme(resolved, benchmark, **policy),  # type: ignore[arg-type]
        direct_alpha(resolved, benchmark, day_count=DAY_COUNT, **policy),  # type: ignore[arg-type]
        pme_plus(resolved, benchmark, day_count=DAY_COUNT, **policy),  # type: ignore[arg-type]
        ln_pme(resolved, benchmark, day_count=DAY_COUNT, **policy),  # type: ignore[arg-type]
    )


def _quadratic_irr(a0: float, a1: float, a2: float) -> float:
    """``r`` with ``a0 + a1 * y + a2 * y**2 = 0``, ``y = 1/(1+r)``, for ``a0 < 0 < a2``.

    The product of the roots is ``a0 / a2 < 0``, so exactly one root ``y`` is positive.
    """
    y = (-a1 + math.sqrt(a1 * a1 - 4.0 * a2 * a0)) / (2.0 * a2)
    return 1.0 / y - 1.0


def _series(result_series: tuple[Any, ...]) -> list[tuple[date, float]]:
    return [(item.date, item.amount) for item in result_series]


def _assert_series(actual: tuple[Any, ...], expected: list[tuple[date, float]]) -> None:
    assert [d for d, _ in _series(actual)] == [d for d, _ in expected]
    for (_, got), (_, want) in zip(_series(actual), expected, strict=True):
        assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


# --- Hand example -------------------------------------------------------------------
#
# Fund: contribute 100 at T0; contribute 40 and receive 80 at T1; receive 30 at T2;
# NAV 110 at T2. Index 100 -> 120 -> 150, so I_T / I_t = 1.5 (T0), 1.25 (T1), 1 (T2).
#   FV(C) = 100 * 1.5 + 40 * 1.25 = 150 + 50 = 200
#   FV(D) = 80 * 1.25 + 30 * 1    = 100 + 30 = 130
# Fund per-date nets: -100, +40, +140; 140 y^2 + 40 y - 100 = 0 -> (7y - 5)(y + 1) = 0,
# y = 5/7, fund IRR = 40%.

HAND: list[Flow] = [
    (T0, "contribution", 100.0),
    (T1, "contribution", 40.0),
    (T1, "distribution", 80.0),
    (T2, "distribution", 30.0),
]
HAND_NAV = (T2, 110.0)


def _hand() -> ResolvedCashFlows:
    return _resolved(HAND, HAND_NAV)


def test_hand_flow_valuations_and_future_values() -> None:
    result = ks_pme(_hand(), INDEX, lookup="exact", max_gap_days=0)
    assert result.flows == (
        FlowValuation(
            date=T0,
            kind="contribution",
            amount=100.0,
            index_date=T0,
            index_level=100.0,
            index_gap_days=0,
            growth_to_as_of=1.5,
            future_value=150.0,
        ),
        FlowValuation(
            date=T1,
            kind="contribution",
            amount=40.0,
            index_date=T1,
            index_level=120.0,
            index_gap_days=0,
            growth_to_as_of=1.25,
            future_value=50.0,
        ),
        FlowValuation(
            date=T1,
            kind="distribution",
            amount=80.0,
            index_date=T1,
            index_level=120.0,
            index_gap_days=0,
            growth_to_as_of=1.25,
            future_value=100.0,
        ),
        FlowValuation(
            date=T2,
            kind="distribution",
            amount=30.0,
            index_date=T2,
            index_level=150.0,
            index_gap_days=0,
            growth_to_as_of=1.0,
            future_value=30.0,
        ),
    )
    assert result.fv_contributions == 200.0
    assert result.fv_distributions == 130.0
    assert result.residual_value == 110.0
    assert result.index_at_as_of == IndexLookupRecord(
        requested=T2, used=T2, level=150.0, gap_days=0
    )
    assert (result.as_of, result.benchmark_name, result.return_basis) == (
        T2,
        "MSCI World NR",
        "total_return_net",
    )
    assert (result.lookup, result.max_gap_days) == ("exact", 0)
    assert result.engine_version == ENGINE_VERSION


def test_hand_ks_pme() -> None:
    # KS-PME = (FV(D) + NAV) / FV(C) = (130 + 110) / 200 = 1.2.
    result = ks_pme(_hand(), INDEX, lookup="exact", max_gap_days=0)
    assert result.ks_pme == pytest.approx(1.2, rel=1e-15)


def test_hand_direct_alpha() -> None:
    # Compounded series: T0: -100 * 1.5 = -150; T1: (-40 + 80) * 1.25 = +50;
    # T2: 30 + 110 = +140. Alpha solves 140 y^2 + 50 y - 150 = 0:
    # y = (-50 + sqrt(2500 + 84000)) / 280 = (-50 + sqrt(86500)) / 280, alpha = 1/y - 1.
    result = direct_alpha(_hand(), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    _assert_series(result.compounded_series, [(T0, -150.0), (T1, 50.0), (T2, 140.0)])
    expected = (280.0 / (-50.0 + math.sqrt(86500.0))) - 1.0
    assert expected == pytest.approx(_quadratic_irr(-150.0, 50.0, 140.0), rel=1e-14)
    assert result.irr.status == "unique"
    assert result.irr.day_count == DAY_COUNT
    assert result.alpha_annual_effective == pytest.approx(expected, rel=1e-9)
    assert result.alpha_continuous == pytest.approx(math.log1p(expected), rel=1e-9)
    # Contract §6: the continuous alpha is the root's own log rate, not ln(1 + rate).
    assert result.alpha_continuous == result.irr.roots[0].log_rate


def test_hand_pme_plus() -> None:
    # s = (FV(C) - NAV) / FV(D) = (200 - 110) / 130 = 9/13.
    # PME+ series: T0: -100; T1: -40 + 80 * 9/13 = 200/13; T2: 30 * 9/13 + 110 = 1700/13.
    # Times 13: 1700 y^2 + 200 y - 1300 = 0 -> 17 y^2 + 2 y - 13 = 0,
    # y = (-2 + sqrt(4 + 884)) / 34 = (-2 + sqrt(888)) / 34.
    # Identity residual: 200 - (9/13) * 130 - 110 = 0. Spread = 40% - PME+ IRR.
    result = pme_plus(_hand(), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert result.scale == pytest.approx(9.0 / 13.0, rel=1e-15)
    assert result.scale_negative is False
    assert result.identity_residual == pytest.approx(0.0, abs=1e-12)
    _assert_series(result.pme_plus_series, [(T0, -100.0), (T1, 200.0 / 13.0), (T2, 1700.0 / 13.0)])
    plus_rate = 34.0 / (-2.0 + math.sqrt(888.0)) - 1.0
    assert result.pme_plus_irr is not None and result.pme_plus_irr.status == "unique"
    assert result.pme_plus_irr.irr == pytest.approx(plus_rate, rel=1e-9)
    assert result.fund_irr.status == "unique"
    assert result.fund_irr.irr == pytest.approx(0.4, rel=1e-9)
    assert result.spread == pytest.approx(0.4 - plus_rate, rel=1e-8)


def test_hand_long_nickels() -> None:
    # V: T0: 0 grown, +100 -> 100; T1: 100 * 120/100 = 120, +40 - 80 -> 80;
    # T2: 80 * 150/120 = 100, -30 -> 70. Closed form FV(C) - FV(D) = 200 - 130 = 70.
    # ICM series: -100, +40, +30 + 70 = +100 -> 100 y^2 + 40 y - 100 = 0 -> 5 y^2 + 2 y - 5,
    # y = (-2 + sqrt(104)) / 10. Spread = 40% - ICM IRR.
    result = ln_pme(_hand(), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert result.path == (
        IcmStep(
            date=T0,
            index_level=100.0,
            position_grown=0.0,
            contribution=100.0,
            distribution=0.0,
            position_after=100.0,
        ),
        IcmStep(
            date=T1,
            index_level=120.0,
            position_grown=120.0,
            contribution=40.0,
            distribution=80.0,
            position_after=80.0,
        ),
        IcmStep(
            date=T2,
            index_level=150.0,
            position_grown=100.0,
            contribution=0.0,
            distribution=30.0,
            position_after=70.0,
        ),
    )
    assert result.terminal_value_recursive == pytest.approx(70.0, rel=1e-15)
    assert result.terminal_value_closed_form == pytest.approx(70.0, rel=1e-15)
    assert result.reconciliation_residual == pytest.approx(0.0, abs=1e-12)
    assert result.went_short is False and result.first_short_date is None
    assert result.min_position == pytest.approx(70.0, rel=1e-15)
    _assert_series(result.icm_series, [(T0, -100.0), (T1, 40.0), (T2, 100.0)])
    icm_rate = 10.0 / (-2.0 + math.sqrt(104.0)) - 1.0
    assert result.icm_irr.status == "unique"
    assert result.icm_irr.irr == pytest.approx(icm_rate, rel=1e-9)
    assert result.fund_irr.irr == pytest.approx(0.4, rel=1e-9)
    assert result.spread == pytest.approx(0.4 - icm_rate, rel=1e-8)


def test_icm_rolls_to_as_of_after_the_last_flow() -> None:
    # Last flow at T1, NAV at T2: the path ends with a growth-only step at T2.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "distribution", 60.0)]
    result = ln_pme(
        _resolved(flows, (T2, 90.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    # T1: 120 - 60 = 60; T2: 60 * 1.25 = 75. Closed form 150 - 75 = 75.
    last = result.path[-1]
    assert (last.date, last.contribution, last.distribution) == (T2, 0.0, 0.0)
    assert last.position_grown == pytest.approx(75.0, rel=1e-15)
    assert result.terminal_value_recursive == pytest.approx(75.0, rel=1e-15)
    assert result.terminal_value_closed_form == pytest.approx(75.0, rel=1e-15)


# --- Published example: Gredil, Griffiths & Stucke (2014), Exhibits 5-6 --------------
#
# Year-end dates 2001..2010, index 100, 78, 100, 111, 117, 135, 142, 90, 113, 131.
# Contributions 100 (2001), 100 (2003), 50 (2005); distributions 25 (2003), 150 (2005),
# 150 (2007), 100 (2009); NAV 75 at 2010-12-31; ACT/365F. Values verified by the
# coordinator: KS-PME = 1990055721/1193950768, fund IRR 0.17520129832391, Direct Alpha
# 0.12560316898427, ICM V_T = -514497653/3754764.
# ICM path: 2001 +100; 2003 100 + 100 - 25 = 175; 2005 175 * 117/100 + 50 - 150 = 104.75;
# 2007 104.75 * 142/117 - 150 = -22.8675... (first short). The ICM series has two roots,
# -0.27255088669879 and +0.05967014313864; the paper shows only the +6.0% one.

GGS_END = date(2010, 12, 31)
GGS_INDEX = _index(
    [
        (date(year, 12, 31), level)
        for year, level in zip(
            range(2001, 2011),
            (100.0, 78.0, 100.0, 111.0, 117.0, 135.0, 142.0, 90.0, 113.0, 131.0),
            strict=True,
        )
    ]
)
GGS_FLOWS: list[Flow] = [
    (date(2001, 12, 31), "contribution", 100.0),
    (date(2003, 12, 31), "contribution", 100.0),
    (date(2005, 12, 31), "contribution", 50.0),
    (date(2003, 12, 31), "distribution", 25.0),
    (date(2005, 12, 31), "distribution", 150.0),
    (date(2007, 12, 31), "distribution", 150.0),
    (date(2009, 12, 31), "distribution", 100.0),
]


def test_gredil_griffiths_stucke_2014_exhibits_5_and_6() -> None:
    resolved = _resolved(GGS_FLOWS, (GGS_END, 75.0), as_of=GGS_END)
    ks, da, plus, ln = _run_all(resolved, GGS_INDEX)
    assert ks.ks_pme == pytest.approx(1990055721 / 1193950768, rel=1e-12)
    assert da.irr.status == "unique"
    assert da.alpha_annual_effective == pytest.approx(0.12560316898427, rel=1e-10)
    assert plus.fund_irr.status == "unique"
    assert plus.fund_irr.irr == pytest.approx(0.17520129832391, rel=1e-10)
    assert ln.terminal_value_recursive == pytest.approx(-514497653 / 3754764, rel=1e-12)
    assert ln.terminal_value_closed_form == pytest.approx(-514497653 / 3754764, rel=1e-12)
    assert ln.went_short is True
    assert ln.first_short_date == date(2007, 12, 31)
    short = next(step for step in ln.path if step.date == date(2007, 12, 31))
    assert short.position_after == pytest.approx(104.75 * 142.0 / 117.0 - 150.0, rel=1e-12)
    assert short.position_after == pytest.approx(-22.8675, abs=1e-4)
    assert ln.icm_irr.status == "multiple" and ln.icm_irr.irr is None
    assert [root.rate for root in ln.icm_irr.roots] == pytest.approx(
        [-0.27255088669879, 0.05967014313864], rel=1e-10
    )
    assert ln.spread is None


# --- Pathologies and undefined figures ---------------------------------------------


def test_long_nickels_short_position_is_flagged_with_its_first_date() -> None:
    # Contribute 100 at T0 (index 100); receive 150 at T1 (index 120); NAV 50 at T2 (150).
    # V: T0 100; T1 100 * 1.2 - 150 = -30 (short); T2 -30 * 1.25 = -37.5.
    # Closed form: FV(C) = 150, FV(D) = 150 * 1.25 = 187.5 -> -37.5.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "distribution", 150.0)]
    result = ln_pme(
        _resolved(flows, (T2, 50.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.went_short is True
    assert result.first_short_date == T1
    assert result.min_position == pytest.approx(-37.5, rel=1e-15)
    assert result.terminal_value_recursive == pytest.approx(-37.5, rel=1e-15)
    assert result.terminal_value_closed_form == pytest.approx(-37.5, rel=1e-15)
    # ICM series {-C_t, +D_t, +V_T at T}: the fund's NAV is replaced by the (short)
    # terminal index position, so -100, +150, -37.5.
    _assert_series(result.icm_series, [(T0, -100.0), (T1, 150.0), (T2, -37.5)])
    text = " ".join(result.assumptions)
    assert "went short on 2022-01-01" in text
    assert "fn. 5" in text


def test_pme_plus_negative_scale_is_flagged() -> None:
    # Contribute 100 at T0, receive 20 at T1, NAV 200 at T2.
    # FV(C) = 150, FV(D) = 20 * 1.25 = 25, s = (150 - 200) / 25 = -2.
    # PME+ series: -100, -2 * 20 = -40, +200.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "distribution", 20.0)]
    result = pme_plus(
        _resolved(flows, (T2, 200.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.scale == pytest.approx(-2.0, rel=1e-15)
    assert result.scale_negative is True
    # Contract §11.4: no spread for s < 0; the PME+ IRR stays attached, the reason is given.
    assert result.spread is None and result.log_spread is None
    assert result.fund_irr is not None and result.fund_irr.status == "unique"
    assert any("not a performance difference" in line for line in result.assumptions)
    assert result.identity_residual == pytest.approx(0.0, abs=1e-12)
    _assert_series(result.pme_plus_series, [(T0, -100.0), (T1, -40.0), (T2, 200.0)])
    # -100 - 40 y + 200 y^2 = 0 -> y = (40 + sqrt(1600 + 80000)) / 400.
    assert result.pme_plus_irr is not None
    assert result.pme_plus_irr.irr == pytest.approx(_quadratic_irr(-100.0, -40.0, 200.0), rel=1e-9)
    assert any("< 0" in line and "pathology" in line for line in result.assumptions)


def test_pme_plus_without_distributions_has_no_scale() -> None:
    # No distributions: FV(D) = 0, nothing to scale.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "contribution", 50.0)]
    result = pme_plus(
        _resolved(flows, (T2, 200.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.fv_distributions == 0.0
    assert result.scale is None and result.scale_negative is False
    assert result.identity_residual is None
    assert result.pme_plus_series == () and result.pme_plus_irr is None
    assert result.spread is None
    assert result.fund_irr.status == "unique"
    assert any("FV(D) is zero" in line for line in result.assumptions)


def test_direct_alpha_with_multiple_roots_is_none() -> None:
    # Constant index, so the compounded series is the raw series -100, +230, -132 at
    # t = 0, 1, 2: -100 + 230 y - 132 y^2 = 0 -> y = (230 +- 10) / 264 -> y = 10/11 or 5/6,
    # r = 10% or 20%. No root is picked.
    flows: list[Flow] = [
        (T0, "contribution", 100.0),
        (T1, "distribution", 230.0),
        (T2, "contribution", 132.0),
    ]
    resolved = _resolved(flows, (T2, 0.0))
    result = direct_alpha(resolved, FLAT, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert result.irr.status == "multiple"
    assert result.irr.irr is None
    assert [root.rate for root in result.irr.roots] == pytest.approx([0.1, 0.2], rel=1e-9)
    assert result.alpha_annual_effective is None and result.alpha_continuous is None
    assert any("status 'multiple'" in line for line in result.assumptions)
    plus = pme_plus(resolved, FLAT, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert plus.fund_irr.status == "multiple" and plus.spread is None


def test_direct_alpha_with_no_root_is_none() -> None:
    # Contributions only and NAV 0: every compounded amount is negative, no rate exists.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "contribution", 50.0)]
    result = direct_alpha(
        _resolved(flows, (T2, 0.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.irr.status == "none"
    assert result.alpha_annual_effective is None and result.alpha_continuous is None


def test_single_date_series_is_refused_for_rates_but_not_for_ks_pme() -> None:
    # Everything on T0: KS-PME = 110 / 100, but no rate of return is defined.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T0, "distribution", 110.0)]
    resolved = _resolved(flows, (T0, 0.0), as_of=T0)
    assert ks_pme(resolved, INDEX, lookup="exact", max_gap_days=0).ks_pme == pytest.approx(1.1)
    with pytest.raises(ValueError, match="fewer than two dates"):
        direct_alpha(resolved, INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)


def test_sign_equivalence_needs_a_negative_first_net() -> None:
    # Nets +50 at T0 and -100 at T1 at a constant index: one sign change, but the first
    # net is positive. KS-PME = 50 / 100 = 0.5 while the IRR (Direct Alpha) solves
    # 50 - 100 y = 0 -> y = 1/2 -> +100%. The equivalence KS > 1 <=> alpha > 0 fails.
    flows: list[Flow] = [(T0, "distribution", 50.0), (T1, "contribution", 100.0)]
    resolved = _resolved(flows, (T1, 0.0), as_of=T1)
    ks = ks_pme(resolved, FLAT, lookup="exact", max_gap_days=0)
    da = direct_alpha(resolved, FLAT, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert ks.ks_pme == pytest.approx(0.5, rel=1e-15)
    assert da.irr.status == "unique"
    assert da.alpha_annual_effective == pytest.approx(1.0, rel=1e-9)


# --- Computed nets within rounding of zero (contract §9) ----------------------------

NOISE_DATES = [
    date(2021, 1, 1),
    date(2021, 4, 1),
    date(2021, 6, 30),
    date(2021, 9, 28),
    date(2021, 12, 27),
]
NOISE_FLOWS: list[Flow] = [
    (NOISE_DATES[0], "contribution", 10.0),
    (NOISE_DATES[1], "contribution", 90.0),
    (NOISE_DATES[2], "distribution", 77.0),
    (NOISE_DATES[3], "distribution", 50.0),
    (NOISE_DATES[4], "contribution", 10.0),
]
NOISE_LEVELS = [50.0, 50.0, 77.0, 50.0, 50.0]


@pytest.mark.parametrize(
    ("k", "noisy"),
    [(1.0, False), (0.7, False), (1.990652220727, True), (0.3, True), (123.4, True)],
)
def test_icm_terminal_rounding_noise_is_dropped_so_rescaling_changes_nothing(
    k: float, noisy: bool
) -> None:
    # V: 10; 10 + 90 = 100; 100 * 77/50 - 77 = 77; 77 * 50/77 - 50 = 0; 0 + 10 = 10.
    # Exactly, the terminal ICM net -10 + V_T is zero, so the ICM series is the fund's
    # first four nets (-10, -90, +77, +50): one sign change, a unique IRR. With the levels
    # scaled by k the float recursion can give V_T = 10 +- 1.4e-14; kept, that net would
    # add a false sign change and a false root at r = -100%. G_T = 210.
    resolved = _resolved(NOISE_FLOWS, (NOISE_DATES[-1], 0.0), as_of=NOISE_DATES[-1])
    results = [
        ln_pme(
            resolved,
            _index([(d, v * scale) for d, v in zip(NOISE_DATES, NOISE_LEVELS, strict=True)]),
            lookup="exact",
            max_gap_days=0,
            day_count=DAY_COUNT,
        )
        for scale in (1.0, k)
    ]
    base, scaled = results
    assert base.terminal_value_recursive == 10.0
    assert scaled.terminal_value_recursive == pytest.approx(10.0, rel=1e-14)
    for result in results:
        assert [item.date for item in result.icm_series] == NOISE_DATES[:4]
        assert result.icm_irr.status == "unique"
    _same_irr(base.icm_irr, scaled.icm_irr)
    noise = [line for line in scaled.assumptions if "within rounding of zero" in line]
    assert (scaled.terminal_value_recursive != 10.0) is noisy
    if noisy:
        raw_net = scaled.terminal_value_recursive - 10.0
        assert len(noise) == 1
        assert "2021-12-27" in noise[0] and repr(raw_net) in noise[0] and "G = 210" in noise[0]
        assert "float rounding bound" in noise[0]
    else:
        assert noise == []


@pytest.mark.parametrize(
    ("distribution", "kept"),
    [(119.999999, True), (119.99999999999, True), (119.99999999999997, False)],
)
def test_icm_small_terminal_value_is_kept_above_the_rounding_threshold(
    distribution: float, kept: bool
) -> None:
    # Contribute 100 at T0 (index 100), receive d at T1 (120), NAV 0 at T2 (150):
    # V_T = (120 - d) * 1.25 and G_T = (120 + d) * 1.25 ~ 300 after N = 3 steps, so the
    # rounding bound for the terminal net is 8 * (N + 1) * eps * G_T ~ 2.1e-12.
    # d = 119.999999: V_T ~ 1.25e-6, a small but real position, kept.
    # d = 119.99999999999: V_T ~ 1.25e-11, still real, kept (the former 1e-10 * G
    # threshold, ~3e-8, dropped it).
    # d = 120 - 2 ulp: V_T ~ 3.6e-14, within rounding of zero, dropped.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "distribution", distribution)]
    result = ln_pme(
        _resolved(flows, (T2, 0.0)), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    v_t = result.terminal_value_recursive
    assert v_t == pytest.approx((120.0 - distribution) * 1.25, rel=1e-3)
    noise = [line for line in result.assumptions if "within rounding of zero" in line]
    if kept:
        assert result.icm_series[-1].date == T2 and result.icm_series[-1].amount == v_t
        assert noise == []
    else:
        assert [item.date for item in result.icm_series] == [T0, T1]
        assert len(noise) == 1 and "2023-01-01" in noise[0] and repr(v_t) in noise[0]


@pytest.mark.parametrize(
    "levels", [(100.0, 117.0, 131.0), (100.0, 111.0, 117.0), (100.0, 130.0, 170.0)]
)
def test_pme_plus_net_within_rounding_of_zero_is_dropped(
    levels: tuple[float, float, float],
) -> None:
    # Contribute 100 at T0; contribute 50 and receive 50 at T1; NAV = 100 * I_T / I_0 at
    # T2. The fund holds the index, so s = (FV(C) - NAV) / FV(D) = 1 and the PME+ net at
    # T1 is -50 + s * 50 = 0. In floats s can be 1 -+ 1 ulp, leaving -+1.4e-14 (G = 100).
    # Either way the PME+ series is the fund's: -100 at T0, +NAV at T2, spread 0.
    nav = 100.0 * levels[2] / levels[0]
    flows: list[Flow] = [
        (T0, "contribution", 100.0),
        (T1, "contribution", 50.0),
        (T1, "distribution", 50.0),
    ]
    benchmark = _index(list(zip((T0, T1, T2), levels, strict=True)))
    result = pme_plus(
        _resolved(flows, (T2, nav)), benchmark, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.scale == pytest.approx(1.0, rel=1e-15)
    _assert_series(result.pme_plus_series, [(T0, -100.0), (T2, nav)])
    assert result.pme_plus_irr is not None and result.pme_plus_irr.status == "unique"
    _same_irr(result.pme_plus_irr, result.fund_irr)
    assert result.spread == pytest.approx(0.0, abs=1e-12)
    noise = [line for line in result.assumptions if "within rounding of zero" in line]
    assert len(noise) == (0 if result.scale == 1.0 else 1)


def test_stated_nets_keep_the_exact_zero_rule() -> None:
    # Contribute 50 and receive 50.000000000001 at T1: a stated net of ~1e-12. It is above
    # the decimal-representation bound eps * sum|legs| = 2.2e-14 (contract §11.3) and is a
    # stated amount rather than rounding of a computed one, so the Direct Alpha and ICM
    # series keep it.
    flows: list[Flow] = [
        (T0, "contribution", 100.0),
        (T1, "contribution", 50.0),
        (T1, "distribution", 50.000000000001),
        (T2, "distribution", 10.0),
    ]
    resolved = _resolved(flows, (T2, 120.0))
    da = direct_alpha(resolved, INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    ln = ln_pme(resolved, INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert T1 in [item.date for item in da.compounded_series]
    assert T1 in [item.date for item in ln.icm_series]
    assert not any("within rounding of zero" in line for line in (*da.assumptions, *ln.assumptions))


# --- Float range and exact short positions (reviewer R1) ----------------------------


@pytest.mark.parametrize("level", [1.0, 1e-300, 1e300])
def test_constant_index_at_any_normal_scale_gives_the_same_answers(level: float) -> None:
    # Contribute 1 at T0, receive 1.1 at T1 (as_of): KS = 1.1 and Direct Alpha = 10% at
    # any constant index. Forming amount * I_T first underflowed at tiny index levels.
    flows: list[Flow] = [(T0, "contribution", 1.0), (T1, "distribution", 1.1)]
    resolved = _resolved(flows, (T1, 0.0), as_of=T1)
    flat = _index([(T0, level), (T1, level)])
    ks = ks_pme(resolved, flat, lookup="exact", max_gap_days=0)
    assert ks.ks_pme == pytest.approx(1.1, rel=1e-15)
    da = direct_alpha(resolved, flat, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert da.alpha_annual_effective == pytest.approx(0.1, rel=1e-12)


def test_tiny_distribution_is_not_lost_to_an_intermediate_underflow() -> None:
    # Contribute 1 at T0, receive 1e-200 at T1, NAV 1e-200 at T2, constant index 1e-200:
    # KS = (1e-200 + 1e-200) / 1 = 2e-200. The product 1e-200 * 1e-200 used to vanish.
    flows: list[Flow] = [(T0, "contribution", 1.0), (T1, "distribution", 1e-200)]
    tiny_index = _index([(T0, 1e-200), (T1, 1e-200), (T2, 1e-200)])
    result = ks_pme(_resolved(flows, (T2, 1e-200)), tiny_index, lookup="exact", max_gap_days=0)
    assert result.ks_pme == pytest.approx(2e-200, rel=1e-15)


def test_tiny_contributions_keep_a_well_defined_ks() -> None:
    # Contribute 1e-200, receive 2e-200 a year later, constant index 1e-200: KS = 2. The
    # old order made FV(C) underflow to 0 and raised ZeroDivisionError.
    flows: list[Flow] = [(T0, "contribution", 1e-200), (T1, "distribution", 2e-200)]
    tiny_index = _index([(T0, 1e-200), (T1, 1e-200)])
    result = ks_pme(
        _resolved(flows, (T1, 0.0), as_of=T1), tiny_index, lookup="exact", max_gap_days=0
    )
    assert result.ks_pme == pytest.approx(2.0, rel=1e-15)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_growth_and_future_values_outside_the_float_range_are_refused(method: Any) -> None:
    flows: list[Flow] = [(T0, "contribution", 1.0), (T1, "distribution", 1.0)]
    # I_T / I_0 = 1e300 / 1e-300 overflows.
    wild = _index([(T0, 1e-300), (T1, 1.0), (T2, 1e300)])
    with pytest.raises(ValueError, match="index growth .* overflows"):
        method(_resolved(flows, (T2, 1.0)), wild, lookup="exact", max_gap_days=0)
    # A 1e-200 contribution grown by I_T / I_0 = 1e-200 underflows.
    tiny = [(T0, "contribution", 1e-200), (T1, "distribution", 1.0)]
    falling = _index([(T0, 1.0), (T1, 1.0), (T2, 1e-200)])
    with pytest.raises(ValueError, match="future value .* underflows"):
        method(_resolved(tiny, (T2, 1.0)), falling, lookup="exact", max_gap_days=0)


def test_ks_is_returned_when_representable_although_fv_d_plus_nav_overflows() -> None:
    # Contribute 1e308, receive 1e308, NAV 1e308 at a constant index:
    # KS = (1e308 + 1e308) / 1e308 = 2. Dividing term by term returns it (fsum raised
    # OverflowError before).
    flows: list[Flow] = [(T0, "contribution", 1e308), (T1, "distribution", 1e308)]
    result = ks_pme(_resolved(flows, (T2, 1e308)), FLAT, lookup="exact", max_gap_days=0)
    assert result.ks_pme == 2.0
    assert any("term by term" in line for line in result.assumptions)


def test_exact_short_position_beyond_rounding_is_flagged() -> None:
    # Contribute 1e12 at T0, receive 1e12 + 1 at T1, constant index: V = -1 exactly from
    # T1. The old 1e-10 * G_d threshold (G = 2e12 + 1, so 200) hid it; the rounding bound
    # 8 * 2 * eps * G ~ 7.1e-3 does not.
    flows: list[Flow] = [(T0, "contribution", 1e12), (T1, "distribution", 1e12 + 1)]
    result = ln_pme(
        _resolved(flows, (T2, 10.0)), FLAT, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert result.went_short is True
    assert result.first_short_date == T1
    assert result.min_position == -1.0
    assert [item.date for item in result.icm_series][-1] == T2  # V_T = -1 is kept


def test_ks_pme_cost_is_driven_by_the_index_not_flows_times_index() -> None:
    # Reviewer R1: every lookup used to copy the 100,000 index dates, so a call cost
    # O(flows x levels) (3.6 s for 2,000 flows). Lookups now bisect the stored levels, so the
    # cost is dominated by the index and grows only slowly with the number of flows.
    # Asserted as a scaling ratio, not a wall-clock bound, so the test means the same on a
    # slow CI runner under coverage: 10x the flows against the same index measured 1.11x
    # (1.13x under branch coverage); the old O(flows x levels) code gives about 8x.
    # Input construction is outside the timed section; each size keeps its best of three.
    start = date(2000, 1, 1)
    index = _index([(start + timedelta(days=i), 100.0) for i in range(100_000)])

    def timed(n: int) -> tuple[float, float]:
        flows: list[Flow] = [
            (start + timedelta(days=i), "contribution" if i < n // 2 else "distribution", 1.0)
            for i in range(n)
        ]
        end = start + timedelta(days=n - 1)
        resolved = _resolved(flows, (end, 0.0), as_of=end)
        best, value = math.inf, math.nan
        for _ in range(3):
            began = time.perf_counter()
            value = ks_pme(resolved, index, lookup="exact", max_gap_days=0).ks_pme
            best = min(best, time.perf_counter() - began)
        return best, value

    small, _ = timed(200)
    large, value = timed(2_000)
    assert value == pytest.approx(1.0, rel=1e-12)
    assert large / small < 4.0


# --- Wave 2 review amendments (contract §11) ----------------------------------------

EXPLOSIVE_END = date(2021, 1, 2)
# Contribute 1, receive 8 one day later, NAV 0: the IRR solves (1 + r)^(1/365) = 8, so
# delta = ln(1 + r) = 365 * ln 8 = 759 > ln(float max) = 709.78. That root is not
# representable as a rate and fund_irr refuses it (contract §6, the one remaining refusal).
EXPLOSIVE: list[Flow] = [(T0, "contribution", 1.0), (EXPLOSIVE_END, "distribution", 8.0)]
EXPLOSIVE_INDEX = _index([(T0, 100.0), (EXPLOSIVE_END, 100.0)])


def test_fund_irr_refusal_is_carried_as_none_by_pme_plus_and_icm() -> None:
    resolved = _resolved(EXPLOSIVE, (EXPLOSIVE_END, 0.0), as_of=EXPLOSIVE_END)
    with pytest.raises(ValueError, match="delta"):
        fund_irr(resolved, day_count=DAY_COUNT)
    # PME+: s = FV(C) / FV(D) = 1/8, so the PME+ series is -1, +1: IRR 0, still reported.
    plus = pme_plus(resolved, EXPLOSIVE_INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert plus.fund_irr is None and plus.spread is None and plus.log_spread is None
    assert plus.scale == pytest.approx(0.125, rel=1e-15)
    assert plus.pme_plus_irr is not None and plus.pme_plus_irr.status == "unique"
    assert plus.pme_plus_irr.irr == pytest.approx(0.0, abs=1e-12)
    assert any("fund IRR is refused" in line for line in plus.assumptions)
    # ICM: V_T = 1 - 8 = -7 (short); the ICM series -1, 8 - 7 = +1 has IRR 0.
    ln = ln_pme(resolved, EXPLOSIVE_INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert ln.fund_irr is None and ln.spread is None and ln.log_spread is None
    assert ln.terminal_value_recursive == -7.0 and ln.went_short is True
    assert ln.icm_irr.status == "unique" and ln.icm_irr.irr == pytest.approx(0.0, abs=1e-12)
    assert any("fund IRR is refused" in line for line in ln.assumptions)
    # Direct Alpha needs that same root: its compounded series is the fund's (-1, +8).
    with pytest.raises(ValueError, match="delta"):
        direct_alpha(resolved, EXPLOSIVE_INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)


def test_written_off_fund_from_review_r2_runs_through_every_method() -> None:
    # R2's dead fund (out/r2/dead_fund_pme.py): five calls, a small wind-down distribution
    # three days after the last, NAV 0. Its unique root has delta ~ -508 (1 + r underflows).
    rows = [
        (date(2015, 2, 20), "contribution", 8564951.8),
        (date(2015, 4, 18), "contribution", 1980030.11),
        (date(2015, 10, 8), "contribution", 8058613.1),
        (date(2018, 10, 31), "contribution", 4810056.04),
        (date(2019, 9, 6), "contribution", 6178192.46),
        (date(2019, 9, 9), "distribution", 95029.33),
    ]
    as_of = date(2019, 11, 25)
    resolved = _resolved(rows, (as_of, 0.0), as_of=as_of)
    days = sorted({d for d, _, _ in rows} | {as_of})
    index = _index([(d, 100.0 + i) for i, d in enumerate(days)])
    ks, da, plus, ln = _run_all(resolved, index)
    assert 0.0 < ks.ks_pme < 0.01
    assert da.irr.status == "unique"
    assert plus.fund_irr is not None and plus.fund_irr.status == "unique"
    assert ln.fund_irr is not None and ln.fund_irr.status == "unique"


def test_invalid_day_count_is_refused_even_without_an_irr_to_solve() -> None:
    # No distributions: PME+ solves no PME+ IRR, and the fund IRR is carried; an unknown
    # convention must still be refused, not swallowed as a fund-IRR refusal.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "contribution", 50.0)]
    resolved = _resolved(flows, (T2, 200.0))
    for method in (direct_alpha, pme_plus, ln_pme):
        with pytest.raises(ValueError, match="day-count"):
            method(resolved, INDEX, lookup="exact", max_gap_days=0, day_count="30/360")


def test_max_gap_used_and_index_gap_days_are_reported() -> None:
    stale = _index([(T0, 100.0), (date(2021, 12, 28), 120.0), (T2, 150.0)])
    result = ks_pme(_hand(), stale, lookup="last_on_or_before", max_gap_days=10)
    assert result.max_gap_used_days == 4
    assert [row.index_gap_days for row in result.flows] == [0, 4, 4, 0]
    exact = ks_pme(_hand(), INDEX, lookup="exact", max_gap_days=0)
    assert exact.max_gap_used_days == 0
    assert exact.index_growth_over_nav_gap is None


def test_rolled_forward_nav_reports_the_index_growth_over_the_gap() -> None:
    # R2-4 (out/r2/edge_claims.py): contribute 100 at T0, NAV 100 at T1, index 100, 100,
    # 130. At as_of T2 the NAV is rolled forward with zero return while the index rose 30%:
    # KS falls from 100/100 = 1 to 100/130 = 0.7692 and I_T / I_navdate = 1.3.
    fund = FundCashFlows(
        name="Fund I",
        currency="USD",
        basis="net_lp",
        flows=(CashFlow(date=T0, kind="contribution", amount=100.0),),
        nav=NavObservation(date=T1, value=100.0),
    )
    index = _index([(T0, 100.0), (T1, 100.0), (T2, 130.0)])
    at_nav = ks_pme(
        resolve(fund, as_of=T1, stale_nav="refuse"), index, lookup="exact", max_gap_days=0
    )
    rolled = ks_pme(
        resolve(fund, as_of=T2, stale_nav="roll_forward_cash_adjusted"),
        index,
        lookup="exact",
        max_gap_days=0,
    )
    assert at_nav.ks_pme == pytest.approx(1.0) and at_nav.index_growth_over_nav_gap is None
    assert rolled.ks_pme == pytest.approx(100.0 / 130.0, rel=1e-15)
    assert rolled.index_growth_over_nav_gap == pytest.approx(1.3, rel=1e-15)
    assert any("against the fund" in line for line in rolled.assumptions)


def test_log_spreads_on_the_hand_example() -> None:
    # Fund IRR 40%; PME+ and ICM IRRs from the quadratics above.
    _, _, plus, ln = _run_all(_hand(), INDEX)
    plus_rate = 34.0 / (-2.0 + math.sqrt(888.0)) - 1.0
    icm_rate = 10.0 / (-2.0 + math.sqrt(104.0)) - 1.0
    assert plus.log_spread == pytest.approx(math.log1p(0.4) - math.log1p(plus_rate), rel=1e-9)
    assert ln.log_spread == pytest.approx(math.log1p(0.4) - math.log1p(icm_rate), rel=1e-9)


def test_direct_alpha_as_of_net_is_used_as_stated() -> None:
    # R2-16: x * L / L differed from x by one ulp in ~9% of draws. The as-of net of the
    # compounded series is now the stated net itself.
    rng = random.Random(20260915)
    for _ in range(100):
        nav = rng.uniform(1.0, 1e7)
        level = rng.uniform(1.0, 1e4)
        resolved = _resolved([(T0, "contribution", 100.0)], (T1, nav), as_of=T1)
        benchmark = _index([(T0, rng.uniform(1.0, 1e4)), (T1, level)])
        da = direct_alpha(resolved, benchmark, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
        assert da.compounded_series[-1].amount == resolved.net_by_date[-1].amount == nav


def test_gross_legs_are_stated_on_ks_and_pme_plus() -> None:
    ks, _, plus, _ = _run_all(_hand(), INDEX)
    for result in (ks, plus):
        assert any(line.startswith("Gross legs:") for line in result.assumptions)


def test_stated_dust_is_dropped_from_the_compounded_series() -> None:
    # R2-3: a same-day recall booked in cents, +300000.30 -100000.10 -200000.20, nets to
    # -2.9e-11 in binary. It is within eps * sum|legs| and counts as zero, so the Direct
    # Alpha series and the fund IRR keep one sign change.
    flows: list[Flow] = [
        (T0, "contribution", 1_000_000.0),
        (T1, "distribution", 300_000.30),
        (T1, "contribution", 100_000.10),
        (T1, "contribution", 200_000.20),
        (T2, "distribution", 400_000.0),
    ]
    resolved = _resolved(flows, (T2, 900_000.0))
    assert T1 in resolved.netted_to_zero
    da = direct_alpha(resolved, INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert [item.date for item in da.compounded_series] == [T0, T2]
    assert da.irr.sign_changes == 1


def test_ln_pme_docstring_names_long_nickels() -> None:
    assert ln_pme.__doc__ is not None
    assert ln_pme.__doc__.splitlines()[0] == (
        "Long–Nickels (LN) PME, the index comparison method (ICM)."
    )


# --- Final review (contract §13) ------------------------------------------------------


def test_dropped_computed_nets_are_structured_records() -> None:
    # R3-5, contract §13.2: the ICM rescaling case drops the terminal net (-7.1e-15); the
    # record carries the raw net, G = 210 and the bound 8 * (N + 1) * eps * G.
    resolved = _resolved(NOISE_FLOWS, (NOISE_DATES[-1], 0.0), as_of=NOISE_DATES[-1])
    scaled = _index(
        [(d, v * 1.990652220727) for d, v in zip(NOISE_DATES, NOISE_LEVELS, strict=True)]
    )
    ln = ln_pme(resolved, scaled, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    (record,) = ln.dropped_computed_nets
    assert isinstance(record, NearZeroNet)
    assert record.date == NOISE_DATES[-1]
    assert record.raw_net == ln.terminal_value_recursive - 10.0
    assert record.gross == pytest.approx(210.0, rel=1e-12)
    assert record.bound == 8 * (len(ln.path) + 1) * sys.float_info.epsilon * record.gross
    assert 0.0 < abs(record.raw_net) <= record.bound
    _, _, plus, clean = _run_all(_hand(), INDEX)
    assert plus.dropped_computed_nets == () and clean.dropped_computed_nets == ()


def test_pme_plus_dropped_net_is_recorded() -> None:
    # s = 1 -+ 1 ulp at index 100, 117, 131 leaves a -7.1e-15 PME+ net on T1 (G = 100).
    levels = (100.0, 117.0, 131.0)
    nav = 100.0 * levels[2] / levels[0]
    flows: list[Flow] = [
        (T0, "contribution", 100.0),
        (T1, "contribution", 50.0),
        (T1, "distribution", 50.0),
    ]
    result = pme_plus(
        _resolved(flows, (T2, nav)),
        _index(list(zip((T0, T1, T2), levels, strict=True))),
        lookup="exact",
        max_gap_days=0,
        day_count=DAY_COUNT,
    )
    (record,) = result.dropped_computed_nets
    assert record.date == T1 and 0.0 < abs(record.raw_net) <= record.bound
    assert record.gross == pytest.approx(100.0, rel=1e-12)


def test_the_nav_date_lookup_counts_in_the_largest_gap_without_a_path_step() -> None:
    # R3-6, contract §13.3: contribute 100 at T0 (index 1); NAV 80 dated T1 has an index
    # level only on T1 - 1 day (2); as_of T2 (index 4), NAV rolled forward. The NAV-date
    # lookup has gap 1 and gives I_T / I_navdate = 4 / 2 = 2; it is the only stale lookup.
    fund = FundCashFlows(
        name="Fund I",
        currency="USD",
        basis="net_lp",
        flows=(CashFlow(date=T0, kind="contribution", amount=100.0),),
        nav=NavObservation(date=T1, value=80.0),
    )
    day_before = T1 - timedelta(days=1)
    index = _index([(T0, 1.0), (day_before, 2.0), (T2, 4.0)])
    resolved = resolve(fund, as_of=T2, stale_nav="roll_forward_cash_adjusted")
    ks, _, _, ln = _run_all(resolved, index, lookup="last_on_or_before", max_gap_days=1)
    assert ks.index_growth_over_nav_gap == 2.0
    assert ks.index_at_nav_date == IndexLookupRecord(
        requested=T1, used=day_before, level=2.0, gap_days=1
    )
    assert ks.max_gap_used_days == 1 and ln.max_gap_used_days == 1
    assert [step.date for step in ln.path] == [T0, T2]  # no step for the NAV date
    assert any("for the NAV date" in line for line in ks.assumptions)
    reported = ks_pme(_hand(), INDEX, lookup="exact", max_gap_days=0)
    assert reported.index_at_nav_date is None and reported.max_gap_used_days == 0


@pytest.mark.parametrize("stamp", [datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=UTC)])
def test_every_result_date_field_refuses_datetime(stamp: datetime) -> None:
    # R3-11, contract §13.6.
    ks, _, _, ln = _run_all(_hand(), INDEX)
    row = ks.flows[0].model_dump()
    for field in ("date", "index_date"):
        with pytest.raises(ValidationError, match="not a datetime"):
            FlowValuation.model_validate({**row, field: stamp})
    with pytest.raises(ValidationError, match="not a datetime"):
        IcmStep.model_validate({**ln.path[0].model_dump(), "date": stamp})
    with pytest.raises(ValidationError, match="not a datetime"):
        KsPmeResult.model_validate({**ks.model_dump(), "as_of": stamp})
    with pytest.raises(ValidationError, match="not a datetime"):
        LnPmeResult.model_validate({**ln.model_dump(), "first_short_date": stamp})


# --- Refusals -----------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_no_residual_value_is_refused(method: Any) -> None:
    with pytest.raises(ValueError, match="residual value"):
        method(_resolved(HAND, None), INDEX, lookup="exact", max_gap_days=0)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_zero_paid_in_is_refused(method: Any) -> None:
    flows: list[Flow] = [(T0, "distribution", 50.0), (T1, "distribution", 20.0)]
    with pytest.raises(ValueError, match="paid-in capital"):
        method(_resolved(flows, (T2, 10.0)), INDEX, lookup="exact", max_gap_days=0)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_currency_mismatch_is_refused(method: Any) -> None:
    euro = _index([(T0, 100.0), (T1, 120.0), (T2, 150.0)], currency="EUR")
    with pytest.raises(ValueError, match=r"EUR.*USD.*no FX"):
        method(_hand(), euro, lookup="exact", max_gap_days=0)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_missing_flow_date_level_is_refused_naming_the_date(method: Any) -> None:
    no_t1 = _index([(T0, 100.0), (T2, 150.0)])
    with pytest.raises(ValueError, match="flow date 2022-01-01"):
        method(_hand(), no_t1, lookup="exact", max_gap_days=0)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_missing_as_of_level_is_refused_naming_the_date(method: Any) -> None:
    no_t2 = _index([(T0, 100.0), (T1, 120.0), (date(2022, 12, 30), 149.0)])
    with pytest.raises(ValueError, match="as-of date 2023-01-01"):
        method(_hand(), no_t2, lookup="exact", max_gap_days=0)


@pytest.mark.parametrize("method", METHODS.values(), ids=METHODS.keys())
def test_gap_exceeded_is_refused_naming_the_date(method: Any) -> None:
    # T1 level is missing; the latest earlier level is 2021-12-28, 4 days before T1.
    stale = _index([(T0, 100.0), (date(2021, 12, 28), 120.0), (T2, 150.0)])
    with pytest.raises(ValueError, match="2022-01-01"):
        method(_hand(), stale, lookup="last_on_or_before", max_gap_days=3)
    result = method(_hand(), stale, lookup="last_on_or_before", max_gap_days=4)
    assert result.lookup == "last_on_or_before" and result.max_gap_days == 4
    t1_rows = [row for row in result.flows if row.date == T1]
    assert all(row.index_date == date(2021, 12, 28) for row in t1_rows)
    assert any("2022-01-01 used 2021-12-28 (4 days)" in line for line in result.assumptions)


def test_stale_lookup_gives_the_same_numbers_as_the_equivalent_exact_index() -> None:
    stale = _index([(T0, 100.0), (date(2021, 12, 28), 120.0), (T2, 150.0)])
    exact = _run_all(_hand(), INDEX)
    looked_up = _run_all(_hand(), stale, lookup="last_on_or_before", max_gap_days=4)
    assert looked_up[0].ks_pme == exact[0].ks_pme
    assert looked_up[1].alpha_annual_effective == exact[1].alpha_annual_effective
    assert looked_up[3].terminal_value_recursive == exact[3].terminal_value_recursive


def test_policy_arguments_are_keyword_only_without_defaults() -> None:
    with pytest.raises(TypeError):
        ks_pme(_hand(), INDEX, "exact", 0)  # type: ignore[misc]
    with pytest.raises(TypeError):
        direct_alpha(_hand(), INDEX, lookup="exact", max_gap_days=0)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        pme_plus(_hand(), INDEX, day_count=DAY_COUNT)  # type: ignore[call-arg]


def test_non_model_inputs_are_refused() -> None:
    with pytest.raises(ValueError, match="ResolvedCashFlows"):
        ks_pme(_fund(HAND, HAND_NAV), INDEX, lookup="exact", max_gap_days=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="BenchmarkIndex"):
        ks_pme(_hand(), INDEX.levels, lookup="exact", max_gap_days=0)  # type: ignore[arg-type]


# --- Assumptions, hashing, immutability ---------------------------------------------


def test_assumptions_state_every_convention() -> None:
    price = _index([(T0, 100.0), (T1, 120.0), (T2, 150.0)], basis="price_return")
    for result in _run_all(_hand(), price):
        text = " ".join(result.assumptions)
        assert "price_return" in text and "omits dividends" in text
        assert "Index lookup: exact" in text
        assert "end-of-day" in text
        assert "No FX" in text and "USD" in text
        assert "NAV source: reported at as_of (2023-01-01)" in text
        assert "net_lp" in text
    ks, da, plus, ln = _run_all(_hand(), INDEX)
    assert "Harris, Jenkinson & Kaplan" in " ".join(ks.assumptions)
    assert "Gredil" in " ".join(da.assumptions)
    assert "s < 0" in " ".join(plus.assumptions)
    assert "short" in " ".join(ln.assumptions)
    assert all("WARNING" not in line for line in ks.assumptions)


def test_input_hash_is_stable_across_permuted_inputs() -> None:
    forward = _run_all(_hand(), INDEX)
    shuffled_index = _index([(T2, 150.0), (T0, 100.0), (T1, 120.0)])
    backward = _run_all(_resolved(list(reversed(HAND)), HAND_NAV), shuffled_index)
    for a, b in zip(forward, backward, strict=True):
        assert a.input_hash == b.input_hash
        assert a == b
    hashes = {result.input_hash for result in forward}
    assert len(hashes) == 4  # the method is part of the hash
    other = ks_pme(_resolved(HAND, (T2, 111.0)), INDEX, lookup="exact", max_gap_days=0)
    assert other.input_hash != forward[0].input_hash


def test_results_are_frozen() -> None:
    ks, da, plus, ln = _run_all(_hand(), INDEX)
    for result, field in (
        (ks, "ks_pme"),
        (da, "alpha_annual_effective"),
        (plus, "scale"),
        (ln, "went_short"),
    ):
        with pytest.raises(ValidationError):
            setattr(result, field, 0.0)
        with pytest.raises(ValidationError):
            result.flows[0].amount = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ln.path[0].position_after = 1.0  # type: ignore[misc]


# --- Identities (contract section 9) ------------------------------------------------

_AMOUNT = st.floats(min_value=10.0, max_value=1000.0, allow_nan=False)
_LEVEL = st.floats(min_value=50.0, max_value=200.0, allow_nan=False)
_GAP = st.integers(min_value=90, max_value=720)
_KIND = st.sampled_from(["contribution", "distribution"])
IDENTITY = settings(max_examples=60, deadline=None)


def _dates(draw: st.DrawFn, n: int) -> list[date]:
    dates = [T0]
    for gap in draw(st.lists(_GAP, min_size=n - 1, max_size=n - 1)):
        dates.append(dates[-1] + timedelta(days=gap))
    return dates


@st.composite
def _cases(
    draw: st.DrawFn,
    *,
    conventional: bool = False,
    constant_index: bool = False,
    nav_zero: bool = False,
) -> tuple[ResolvedCashFlows, BenchmarkIndex]:
    """One flow per date, a contribution first, NAV at the last flow date.

    ``conventional``: contributions on the first ``k`` dates and distributions after, so
    the per-date nets have exactly one sign change and a negative first net.
    """
    n = draw(st.integers(min_value=2, max_value=6))
    dates = _dates(draw, n)
    if conventional:
        k = draw(st.integers(min_value=1, max_value=n - 1))
        kinds = ["contribution"] * k + ["distribution"] * (n - k)
    else:
        kinds = ["contribution", *draw(st.lists(_KIND, min_size=n - 1, max_size=n - 1))]
    amounts = draw(st.lists(_AMOUNT, min_size=n, max_size=n))
    # A NAV near the bottom of the float range makes NAV / FV(C) underflow, which is refused
    # (explicit tests cover it); the identities here use 0 or an ordinary NAV.
    nav = (
        0.0
        if nav_zero
        else draw(st.one_of(st.just(0.0), st.floats(min_value=1e-6, max_value=1000.0)))
    )
    levels = [100.0] * n if constant_index else draw(st.lists(_LEVEL, min_size=n, max_size=n))
    flows = list(zip(dates, kinds, amounts, strict=True))
    resolved = _resolved(flows, (dates[-1], nav), as_of=dates[-1])
    # A rate needs two dated nets: e.g. contribute 10, then contribute 10 with NAV 10 on
    # the last date nets to a single date, which the rate methods rightly refuse.
    assume(len(resolved.net_by_date) >= 2)
    return resolved, _index(list(zip(dates, levels, strict=True)))


@st.composite
def _replicating(draw: st.DrawFn) -> tuple[ResolvedCashFlows, BenchmarkIndex]:
    """A fund that holds the index: contributions buy it, distributions sell a fraction.

    Its NAV at T is the index position, so NAV_T = FV(C) - FV(D) by construction.
    """
    n = draw(st.integers(min_value=2, max_value=6))
    dates = _dates(draw, n)
    k = draw(st.integers(min_value=1, max_value=n - 1))
    levels = draw(st.lists(_LEVEL, min_size=n, max_size=n))
    position = 0.0
    flows: list[Flow] = []
    for i, (on, level) in enumerate(zip(dates, levels, strict=True)):
        if i:
            position *= level / levels[i - 1]
        if i < k:
            amount = draw(_AMOUNT)
            flows.append((on, "contribution", amount))
            position += amount
        else:
            # Sell a fraction of the position; all of it only on the last date, so every
            # distribution is strictly positive.
            top = 1.0 if i == n - 1 else 0.95
            amount = draw(st.floats(min_value=0.05, max_value=top)) * position
            flows.append((on, "distribution", amount))
            position -= amount
    resolved = _resolved(flows, (dates[-1], position), as_of=dates[-1])
    return resolved, _index(list(zip(dates, levels, strict=True)))


def _same_irr(a: IrrResult | None, b: IrrResult | None) -> None:
    """Rescaling changes no rate and no certified status: same status, same roots."""
    if a is None or b is None:
        assert a is None and b is None
        return
    assert a.status == b.status
    assert len(a.roots) == len(b.roots)
    for x, y in zip(a.roots, b.roots, strict=True):
        assert x.rate == pytest.approx(y.rate, rel=1e-7, abs=1e-9)


def _optional_approx(a: float | None, b: float | None, *, rel: float, abs_: float = 0.0) -> None:
    if a is None or b is None:
        assert a is None and b is None
        return
    assert a == pytest.approx(b, rel=rel, abs=abs_)


@IDENTITY
@given(_cases(constant_index=True))
def test_constant_index_ks_is_tvpi_and_alpha_is_fund_irr(
    case: tuple[ResolvedCashFlows, BenchmarkIndex],
) -> None:
    resolved, benchmark = case
    ks, da, _, _ = _run_all(resolved, benchmark)
    assert ks.ks_pme == pytest.approx(multiples(resolved).tvpi, rel=1e-12)
    fund = fund_irr(resolved, day_count=DAY_COUNT)
    _assert_series(da.compounded_series, _series(resolved.net_by_date))
    _same_irr(da.irr, fund)
    if fund.status == "unique":
        assert da.alpha_annual_effective == pytest.approx(fund.irr, rel=1e-9, abs=1e-12)


@IDENTITY
@given(_replicating())
def test_replicating_fund_has_ks_one_alpha_zero_scale_one(
    case: tuple[ResolvedCashFlows, BenchmarkIndex],
) -> None:
    resolved, benchmark = case
    ks, da, plus, ln = _run_all(resolved, benchmark)
    assert ks.ks_pme == pytest.approx(1.0, rel=1e-9)
    assert da.irr.status == "unique"
    assert da.alpha_annual_effective == pytest.approx(0.0, abs=1e-9)
    assert plus.scale == pytest.approx(1.0, rel=1e-9)
    assert ln.terminal_value_recursive == pytest.approx(
        resolved.residual_value, rel=1e-9, abs=1e-9 * ks.fv_contributions
    )
    assert ln.went_short is False
    # s = 1 and V_T = NAV_T make both comparison series the fund's own series.
    assert plus.spread == pytest.approx(0.0, abs=1e-7)
    assert ln.spread == pytest.approx(0.0, abs=1e-7)


@IDENTITY
@given(_cases(nav_zero=True))
def test_zero_nav_ks_is_the_reciprocal_of_the_scale(
    case: tuple[ResolvedCashFlows, BenchmarkIndex],
) -> None:
    # NAV_T = 0: KS = FV(D) / FV(C) and s = FV(C) / FV(D).
    resolved, benchmark = case
    assume(resolved.distributed > 0)
    ks = ks_pme(resolved, benchmark, lookup="exact", max_gap_days=0)
    plus = pme_plus(resolved, benchmark, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert plus.scale is not None
    assert ks.ks_pme == pytest.approx(1.0 / plus.scale, rel=1e-12)


@IDENTITY
@given(_cases(conventional=True))
def test_conventional_series_ks_above_one_iff_alpha_positive(
    case: tuple[ResolvedCashFlows, BenchmarkIndex],
) -> None:
    resolved, benchmark = case
    ks = ks_pme(resolved, benchmark, lookup="exact", max_gap_days=0)
    assume(abs(ks.ks_pme - 1.0) > 1e-9)
    da = direct_alpha(resolved, benchmark, lookup="exact", max_gap_days=0, day_count=DAY_COUNT)
    assert da.irr.sign_changes == 1
    assert da.irr.status == "unique"
    assert da.alpha_annual_effective is not None
    assert (ks.ks_pme > 1.0) == (da.alpha_annual_effective > 0.0)


@IDENTITY
@given(_cases(), st.floats(min_value=1e-3, max_value=1e3))
def test_rescaling_the_index_changes_nothing(
    case: tuple[ResolvedCashFlows, BenchmarkIndex], k: float
) -> None:
    resolved, benchmark = case
    scaled = _index([(item.date, item.level * k) for item in benchmark.levels])
    base = _run_all(resolved, benchmark)
    moved = _run_all(resolved, scaled)
    assert moved[0].ks_pme == pytest.approx(base[0].ks_pme, rel=1e-12)
    for a, b in zip(base, moved, strict=True):
        assert b.fv_contributions == pytest.approx(a.fv_contributions, rel=1e-12)
        assert b.fv_distributions == pytest.approx(a.fv_distributions, rel=1e-12)
    _same_irr(base[1].irr, moved[1].irr)
    _optional_approx(base[2].scale, moved[2].scale, rel=1e-9, abs_=1e-12)
    _same_irr(base[2].pme_plus_irr, moved[2].pme_plus_irr)
    assert moved[3].terminal_value_recursive == pytest.approx(
        base[3].terminal_value_recursive, rel=1e-9, abs=1e-9 * base[0].fv_contributions
    )
    _same_irr(base[3].icm_irr, moved[3].icm_irr)
    assert moved[3].went_short == base[3].went_short


@IDENTITY
@given(_cases(), st.floats(min_value=1e-3, max_value=1e3))
def test_rescaling_flows_and_nav_changes_no_ratio_or_rate(
    case: tuple[ResolvedCashFlows, BenchmarkIndex], k: float
) -> None:
    resolved, benchmark = case
    assert resolved.residual_value is not None
    scaled = _resolved(
        [(f.date, f.kind, f.amount * k) for f in resolved.flows],
        (resolved.as_of, resolved.residual_value * k),
        as_of=resolved.as_of,
    )
    base = _run_all(resolved, benchmark)
    moved = _run_all(scaled, benchmark)
    assert moved[0].ks_pme == pytest.approx(base[0].ks_pme, rel=1e-12)
    assert moved[0].fv_contributions == pytest.approx(k * base[0].fv_contributions, rel=1e-12)
    _same_irr(base[1].irr, moved[1].irr)
    _optional_approx(base[2].scale, moved[2].scale, rel=1e-9, abs_=1e-12)
    _same_irr(base[2].pme_plus_irr, moved[2].pme_plus_irr)
    _same_irr(base[2].fund_irr, moved[2].fund_irr)
    _optional_approx(base[2].spread, moved[2].spread, rel=1e-6, abs_=1e-9)
    _same_irr(base[3].icm_irr, moved[3].icm_irr)
    _optional_approx(base[3].spread, moved[3].spread, rel=1e-6, abs_=1e-9)
    assert moved[3].went_short == base[3].went_short


@IDENTITY
@given(_cases())
def test_icm_recursion_equals_closed_form_and_pme_plus_identity_holds(
    case: tuple[ResolvedCashFlows, BenchmarkIndex],
) -> None:
    resolved, benchmark = case
    _, _, plus, ln = _run_all(resolved, benchmark)
    scale = ln.fv_contributions + ln.fv_distributions
    assert abs(ln.reconciliation_residual) <= 1e-12 * scale
    assert ln.terminal_value_closed_form == pytest.approx(
        ln.fv_contributions - ln.fv_distributions, rel=1e-15, abs=1e-15 * scale
    )
    if plus.identity_residual is not None:
        assert abs(plus.identity_residual) <= 1e-12 * (scale + plus.residual_value)
    # Short positions by the contract's rounding-bound definition, recomputed from the path:
    # at step n, V_d < -8 * n * eps * G_d with G_d the gross flows grown to d.
    shorts: list[date] = []
    gross = 0.0
    previous: IcmStep | None = None
    for n, step in enumerate(ln.path, start=1):
        grown = 0.0 if previous is None else gross * (step.index_level / previous.index_level)
        gross = math.fsum((grown, step.contribution, step.distribution))
        if step.position_after < -8 * n * sys.float_info.epsilon * gross:
            shorts.append(step.date)
        previous = step
    assert bool(shorts) == ln.went_short
    assert ln.first_short_date == (shorts[0] if shorts else None)
    if ln.went_short:
        assert ln.min_position < 0
