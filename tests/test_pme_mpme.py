"""mPME (``ovf.pme.mpme``): hand examples, refusals, identities and the never-short property.

Hand examples use an index 100 -> 120 -> 160 on dates exactly 365 days apart, so under
ACT/365F the flow times are t = 0, 1, 2 years and every IRR is the root of a quadratic in
``y = 1 / (1 + r)``. No number here is a published mPME figure. The Gredil, Griffiths &
Stucke (2014) Exhibit 5-6 fund states no interim NAVs, so its mPME cannot be computed from
the displayed inputs (``test_ggs_displayed_inputs_carry_no_interim_navs``).
"""

from __future__ import annotations

import math
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from ovf.pme.benchmark import BenchmarkIndex, IndexLevel, IndexLookup
from ovf.pme.flows import (
    ENGINE_VERSION,
    CashFlow,
    FundCashFlows,
    NavObservation,
    ResolvedCashFlows,
    StaleNavPolicy,
    resolve,
)
from ovf.pme.irr import IrrResult
from ovf.pme.mpme import (
    FundNavHistory,
    InterimNavPolicy,
    MpmeResult,
    MpmeStep,
    check_interim_policy,
    mpme,
)
from ovf.pme.pme import ln_pme

DAY_COUNT = "ACT/365F"
T0 = date(2021, 1, 1)
T1 = date(2022, 1, 1)  # 365 days after T0: t = 1
T2 = date(2023, 1, 1)  # 730 days after T0: t = 2
S = T1 - timedelta(days=30)  # 2021-12-02, an interim NAV date 30 days before T1

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
    flows: list[Flow],
    nav: tuple[date, float] | None,
    *,
    as_of: date = T2,
    stale_nav: StaleNavPolicy = "refuse",
    currency: str = "USD",
) -> ResolvedCashFlows:
    return resolve(_fund(flows, nav, currency=currency), as_of=as_of, stale_nav=stale_nav)


def _index(levels: list[tuple[date, float]], *, currency: str = "USD") -> BenchmarkIndex:
    return BenchmarkIndex(
        name="MSCI World NR",
        currency=currency,
        return_basis="total_return_net",
        levels=tuple(IndexLevel(date=d, level=v) for d, v in levels),
    )


def _history(*observations: tuple[date, float]) -> FundNavHistory:
    return FundNavHistory(
        observations=tuple(NavObservation(date=d, value=v) for d, v in observations)
    )


INDEX = _index([(T0, 100.0), (T1, 120.0), (T2, 160.0)])


def _run(
    resolved: ResolvedCashFlows,
    history: FundNavHistory,
    benchmark: BenchmarkIndex = INDEX,
    *,
    interim_nav: InterimNavPolicy = "refuse",
    max_nav_gap_days: int = 0,
    lookup: IndexLookup = "exact",
    max_gap_days: int = 0,
) -> MpmeResult:
    return mpme(
        resolved,
        history,
        benchmark,
        lookup=lookup,
        max_gap_days=max_gap_days,
        day_count=DAY_COUNT,
        interim_nav=interim_nav,
        max_nav_gap_days=max_nav_gap_days,
    )


def _series(result: MpmeResult) -> list[tuple[date, float]]:
    return [(item.date, item.amount) for item in result.mpme_series]


def _step(result: MpmeResult, on: date) -> MpmeStep:
    return next(step for step in result.path if step.date == on)


# --- Hand example -------------------------------------------------------------------
#
# Fund: contribute 100 at T0; receive 30 at T1, with the fund's NAV 50 after it (end of
# day); NAV 88 at T2 = as_of. Index 100 -> 120 -> 160.
#   T0: X = 0 + 100 = 100; no distribution, w = 0; NAV_mPME = 100.
#   T1: X = 100 * 120/100 = 120; w = 30 / (30 + 50) = 3/8; Dist_mPME = 45;
#       NAV_mPME = (50 / 80) * 120 = 75.
#   T2: X = 75 * 160/120 = 100; no distribution; NAV_mPME,T = 100.
# mPME series -100, +45, +100: 100 y^2 + 45 y - 100 = (5y - 4)(20y + 25) = 0, y = 4/5,
# mPME IRR 25%. Fund series -100, +30, +88: 88 y^2 + 30 y - 100 = 2(11y - 10)(4y + 5) = 0,
# y = 10/11, fund IRR 10%. Spread 10% - 25% = -15%; log spread ln(1.1) - ln(1.25).
# FV(C) = 100 * 1.6 = 160 and FV(D) = 30 * 160/120 = 40 (the shared PME fields).

HAND: list[Flow] = [(T0, "contribution", 100.0), (T1, "distribution", 30.0)]
HAND_NAV = (T2, 88.0)


def _hand(history: FundNavHistory | None = None, **policy: object) -> MpmeResult:
    return _run(
        _resolved(HAND, HAND_NAV),
        history if history is not None else _history((T1, 50.0)),
        **policy,  # type: ignore[arg-type]
    )


def test_hand_example_path() -> None:
    result = _hand()
    assert [step.date for step in result.path] == [T0, T1, T2]
    first, middle, last = result.path
    assert (first.contribution, first.distribution, first.weight) == (100.0, 0.0, 0.0)
    assert first.position_before_sale == first.position_after == 100.0
    assert (first.fund_nav, first.fund_nav_source, first.fund_nav_observation_date) == (
        None,
        "none",
        None,
    )
    assert middle.index_level == 120.0
    assert (middle.fund_nav, middle.fund_nav_source) == (50.0, "reported")
    assert middle.fund_nav_observation_date == T1
    assert middle.weight == 0.375  # 30 / 80, exact in binary
    assert middle.position_before_sale == pytest.approx(120.0, rel=1e-15)
    assert middle.mpme_distribution == pytest.approx(45.0, rel=1e-15)
    assert middle.position_after == pytest.approx(75.0, rel=1e-15)
    assert last.weight == 0.0 and last.fund_nav is None and last.mpme_distribution == 0.0
    assert last.position_before_sale == pytest.approx(100.0, rel=1e-15)
    assert result.terminal_value == last.position_after
    assert result.terminal_value == pytest.approx(100.0, rel=1e-15)


def test_hand_example_series_rates_and_common_fields() -> None:
    result = _hand()
    assert [d for d, _ in _series(result)] == [T0, T1, T2]
    assert [a for _, a in _series(result)] == pytest.approx([-100.0, 45.0, 100.0], rel=1e-15)
    assert result.mpme_irr.status == "unique"
    assert result.mpme_irr.irr == pytest.approx(0.25, rel=1e-12)
    assert result.fund_irr is not None and result.fund_irr.status == "unique"
    assert result.fund_irr.irr == pytest.approx(0.10, rel=1e-12)
    assert result.spread == pytest.approx(-0.15, rel=1e-11)
    assert result.log_spread == pytest.approx(math.log(1.1) - math.log(1.25), rel=1e-11)
    assert result.fv_contributions == pytest.approx(160.0, rel=1e-15)
    assert result.fv_distributions == pytest.approx(40.0, rel=1e-15)
    assert result.residual_value == 88.0
    assert result.max_gap_used_days == 0
    assert result.max_nav_gap_used_days == 0
    assert result.interim_nav == "refuse" and result.max_nav_gap_days == 0
    assert result.engine_version == ENGINE_VERSION


def test_call_is_invested_before_the_sale_and_legs_are_gross() -> None:
    # T1 carries a call of 20 and a distribution of 30, fund NAV 50 after both.
    #   T1: X = 100 * 1.2 + 20 = 140 (the call is invested first); w = 30/80 = 3/8;
    #       Dist_mPME = 52.5; NAV_mPME = 87.5. Selling before the call would give 45.
    #   T2: X = 87.5 * 160/120 = 116.666...
    # The fund's own net at T1 is +10, but the recursion uses the gross C = 20, D = 30.
    # mPME series: -100, -20 + 52.5 = +32.5, +116.67.
    flows: list[Flow] = [*HAND, (T1, "contribution", 20.0)]
    result = _run(_resolved(flows, HAND_NAV), _history((T1, 50.0)))
    step = _step(result, T1)
    assert (step.contribution, step.distribution) == (20.0, 30.0)
    assert step.position_before_sale == pytest.approx(140.0, rel=1e-15)
    assert step.mpme_distribution == pytest.approx(52.5, rel=1e-15)
    assert step.position_after == pytest.approx(87.5, rel=1e-15)
    assert result.terminal_value == pytest.approx(87.5 * 160.0 / 120.0, rel=1e-15)
    assert [a for _, a in _series(result)] == pytest.approx(
        [-100.0, 32.5, 87.5 * 160.0 / 120.0], rel=1e-14
    )
    assert "same-day recall is not netted" in " ".join(result.assumptions)


# --- w_t = 1 at a zero interim NAV ---------------------------------------------------


def test_zero_interim_nav_sells_the_whole_position() -> None:
    # The fund pays out everything at T1: NAV 0 after the distribution of 30, 0 at T2.
    #   T1: X = 120; w = 30 / (30 + 0) = 1 exactly; Dist_mPME = 120; NAV_mPME = 0 * 120 = 0.
    #   T2: X = 0 * 160/120 = 0; NAV_mPME,T = 0.
    # mPME series -100, +120: IRR 20%. Fund series -100, +30: IRR -70%.
    result = _run(_resolved(HAND, (T2, 0.0)), _history((T1, 0.0)))
    step = _step(result, T1)
    assert step.weight == 1.0
    assert step.position_after == 0.0
    assert step.mpme_distribution == step.position_before_sale
    assert step.mpme_distribution == pytest.approx(120.0, rel=1e-15)
    assert result.terminal_value == 0.0
    assert _series(result) == [(T0, -100.0), (T1, step.mpme_distribution)]
    assert result.mpme_irr.irr == pytest.approx(0.20, rel=1e-12)
    assert result.fund_irr is not None
    assert result.fund_irr.irr == pytest.approx(-0.70, rel=1e-12)


def test_a_distribution_from_an_empty_position_sells_exactly_zero() -> None:
    # Found by hypothesis: after the full sale at T1 the position is exactly 0, so a later
    # distribution (10 at T2, fund NAV 0 after it: w = 1) sells w * 0 = 0 exactly. That
    # zero is exact, not an underflow, and must not be refused.
    flows: list[Flow] = [*HAND, (T2, "distribution", 10.0)]
    result = _run(_resolved(flows, (T2, 0.0)), _history((T1, 0.0)))
    step = _step(result, T2)
    assert (step.weight, step.position_before_sale, step.mpme_distribution) == (1.0, 0.0, 0.0)
    assert result.terminal_value == 0.0
    assert [d for d, _ in _series(result)] == [T0, T1]


def test_an_underflowing_weight_is_refused_naming_the_date() -> None:
    # Found by hypothesis: fund NAV 5e-324 after a distribution of 30 gives
    # 1 - w_t = 5e-324 / 30, below the smallest normal float. It is refused, as every
    # underflowing non-zero ratio in ovf.pme is, rather than silently read as w_t = 1.
    with pytest.raises(ValueError, match=r"1 - w_t on 2022-01-01 .* underflows"):
        _run(_resolved(HAND, HAND_NAV), _history((T1, 5e-324)))


def test_a_call_after_a_full_sale_starts_from_zero() -> None:
    # As above, then a new call of 50 at T2 (index 160): X = 0 * 160/120 + 50 = 50.
    flows: list[Flow] = [*HAND, (T2, "contribution", 50.0)]
    result = _run(_resolved(flows, (T2, 40.0)), _history((T1, 0.0)))
    assert _step(result, T1).position_after == 0.0
    assert _step(result, T2).position_before_sale == 50.0
    assert result.terminal_value == 50.0


# --- Interim NAV roll-forward --------------------------------------------------------
#
# Index 100 at T0 and at S, 120 at T1, 160 at T2. Flows: call 100 at T0, call 20 at S,
# call 10 and distribution 30 at T1. The fund's NAV is observed at S only (110, end of
# day: after the call of 20 on S); the residual at T2 is 150.
#   Rolled NAV at T1 = 110 + 10 - 30 = 90: the call on S is already in the NAV; the call
#   and the distribution on T1 are applied. Gap: 30 days.
#   S:  X = 100 * 100/100 + 20 = 120.
#   T1: X = 120 * 120/100 + 10 = 154; w = 30 / (30 + 90) = 1/4; Dist_mPME = 38.5;
#       NAV_mPME = 3/4 * 154 = 115.5.
#   T2: X = 115.5 * 160/120 = 154 = NAV_mPME,T.

ROLL_INDEX = _index([(T0, 100.0), (S, 100.0), (T1, 120.0), (T2, 160.0)])
ROLL_FLOWS: list[Flow] = [
    (T0, "contribution", 100.0),
    (S, "contribution", 20.0),
    (T1, "contribution", 10.0),
    (T1, "distribution", 30.0),
]


def _roll(nav_at_s: float, max_nav_gap_days: int) -> MpmeResult:
    return _run(
        _resolved(ROLL_FLOWS, (T2, 150.0)),
        _history((S, nav_at_s)),
        ROLL_INDEX,
        interim_nav="roll_forward_cash_adjusted",
        max_nav_gap_days=max_nav_gap_days,
    )


@pytest.mark.parametrize("limit", [30, 365])
def test_interim_nav_rolled_forward_within_the_gap(limit: int) -> None:
    result = _roll(110.0, limit)
    assert [step.date for step in result.path] == [T0, S, T1, T2]
    assert _step(result, S).fund_nav is None  # no distribution on S: no NAV needed
    step = _step(result, T1)
    assert step.fund_nav == 90.0
    assert step.fund_nav_source == "rolled_forward"
    assert step.fund_nav_observation_date == S
    assert step.weight == 0.25
    assert step.position_before_sale == pytest.approx(154.0, rel=1e-15)
    assert step.mpme_distribution == pytest.approx(38.5, rel=1e-15)
    assert step.position_after == pytest.approx(115.5, rel=1e-15)
    assert result.terminal_value == pytest.approx(154.0, rel=1e-15)
    assert result.max_nav_gap_used_days == 30
    assert result.max_nav_gap_days == limit
    text = " ".join(result.assumptions)
    assert "rolled forward with zero return from 2021-12-02 (30 days" in text
    assert "= 90.0" in text
    assert f"max_nav_gap_days {limit}" in text


def test_interim_nav_gap_beyond_the_limit_is_refused_naming_the_date() -> None:
    with pytest.raises(ValueError, match=r"2022-01-01.*30 days earlier.*max_nav_gap_days 29"):
        _roll(110.0, 29)


def test_negative_rolled_interim_nav_is_refused_naming_the_date() -> None:
    # 10 + 10 - 30 = -10: the distribution on T1 exceeds the NAV plus the call.
    with pytest.raises(ValueError, match=r"2022-01-01 gives -10\.0.*inconsistent"):
        _roll(10.0, 30)


def test_roll_to_exactly_zero_sells_everything() -> None:
    # 20 + 10 - 30 = 0: w = 1 and the position after T1 is exactly 0.
    result = _roll(20.0, 30)
    step = _step(result, T1)
    assert step.fund_nav == 0.0 and step.weight == 1.0 and step.position_after == 0.0


def test_no_earlier_observation_is_refused_naming_the_date() -> None:
    # The only observation is the residual at T2, after the distribution on T1.
    with pytest.raises(ValueError, match=r"on or before the distribution date 2022-01-01"):
        _run(
            _resolved(HAND, HAND_NAV),
            _history(HAND_NAV),
            interim_nav="roll_forward_cash_adjusted",
            max_nav_gap_days=365,
        )


def test_missing_interim_nav_under_refuse_is_refused_naming_the_date() -> None:
    with pytest.raises(ValueError, match=r"no fund NAV observation dated 2022-01-01"):
        _run(_resolved(HAND, HAND_NAV), _history(HAND_NAV))
    with pytest.raises(ValueError, match=r"dated 2022-01-01"):
        _hand(_history((S, 80.0)))  # an earlier NAV is not rolled under "refuse"


def test_nav_dates_need_no_index_level() -> None:
    # The hand example with its NAV observed 30 days before T1 (80), a date with no index
    # level and no flow: rolled 80 - 30 = 50, so the path is the hand example's.
    result = _hand(
        _history((S, 80.0)), interim_nav="roll_forward_cash_adjusted", max_nav_gap_days=30
    )
    step = _step(result, T1)
    assert (step.fund_nav, step.fund_nav_source, step.fund_nav_observation_date) == (
        50.0,
        "rolled_forward",
        S,
    )
    assert step.mpme_distribution == pytest.approx(45.0, rel=1e-15)
    assert result.mpme_irr.irr == pytest.approx(0.25, rel=1e-12)
    assert result.max_nav_gap_used_days == 30


def test_an_observation_on_the_date_wins_over_a_roll() -> None:
    # Both S (80) and T1 (50) observed: T1's own observation is used, gap 0.
    result = _hand(
        _history((S, 999.0), (T1, 50.0)),
        interim_nav="roll_forward_cash_adjusted",
        max_nav_gap_days=30,
    )
    step = _step(result, T1)
    assert (step.fund_nav, step.fund_nav_source) == (50.0, "reported")
    assert result.max_nav_gap_used_days == 0


# --- NAV at as_of (contract section 12 as amended) -----------------------------------
#
# Call 100 at T0; distribution 40 at T2 = as_of; residual 120. The history holds only an
# unused observation at T0.
#   T2: X = 100 * 1.6 = 160; w = 40 / (40 + 120) = 1/4; Dist_mPME = 40; NAV_mPME,T = 120.
#   mPME series -100, +160: IRR sqrt(1.6) - 1 (this fund tracks the index).

END_FLOWS: list[Flow] = [(T0, "contribution", 100.0), (T2, "distribution", 40.0)]


@pytest.mark.parametrize("interim_nav", ["refuse", "roll_forward_cash_adjusted"])
def test_distribution_at_as_of_uses_the_residual_value(interim_nav: InterimNavPolicy) -> None:
    result = _run(_resolved(END_FLOWS, (T2, 120.0)), _history((T0, 100.0)), interim_nav=interim_nav)
    step = _step(result, T2)
    assert (step.fund_nav, step.fund_nav_source, step.fund_nav_observation_date) == (
        120.0,
        "reported",
        T2,
    )
    assert step.weight == 0.25
    assert step.mpme_distribution == pytest.approx(40.0, rel=1e-15)
    assert result.terminal_value == pytest.approx(120.0, rel=1e-15)
    assert result.mpme_irr.irr == pytest.approx(math.sqrt(1.6) - 1.0, rel=1e-12)


def test_distribution_at_as_of_uses_a_residual_rolled_by_resolve() -> None:
    # resolve rolls the stated NAV 130 at T1 to T2: 130 - 40 = 90 = NAV_T.
    #   T2: w = 40 / (40 + 90) = 4/13; Dist_mPME = 160 * 4/13; NAV_mPME,T = 160 * 9/13.
    resolved = _resolved(END_FLOWS, (T1, 130.0), stale_nav="roll_forward_cash_adjusted")
    assert resolved.residual_value == 90.0
    result = _run(resolved, _history((T0, 100.0)))
    step = _step(result, T2)
    assert (step.fund_nav, step.fund_nav_source, step.fund_nav_observation_date) == (
        90.0,
        "rolled_forward",
        T1,
    )
    assert step.weight == pytest.approx(4.0 / 13.0, rel=1e-15)
    assert step.mpme_distribution == pytest.approx(160.0 * 4.0 / 13.0, rel=1e-14)
    assert result.terminal_value == pytest.approx(160.0 * 9.0 / 13.0, rel=1e-14)
    assert result.max_nav_gap_used_days == 0  # resolve's roll, not an interim roll
    assert "rolled forward by resolve from 2022-01-01" in " ".join(result.assumptions)


def test_history_observation_at_as_of_must_equal_the_residual_value() -> None:
    result = _hand(_history((T1, 50.0), (T2, 88.0)))
    assert result.terminal_value == pytest.approx(100.0, rel=1e-15)
    with pytest.raises(ValueError, match=r"as_of 2023-01-01 is 87\.0.*88\.0"):
        _hand(_history((T1, 50.0), (T2, 87.0)))


def test_observation_after_as_of_is_refused_naming_the_date() -> None:
    with pytest.raises(ValueError, match=r"dated 2023-01-02 is after as_of 2023-01-01"):
        _hand(_history((T1, 50.0), (T2 + timedelta(days=1), 88.0)))


# --- Policy and input refusals ------------------------------------------------------


def test_refuse_policy_requires_a_zero_gap() -> None:
    with pytest.raises(ValueError, match=r"'refuse'.*max_nav_gap_days must be 0, got 5"):
        _hand(max_nav_gap_days=5)


@pytest.mark.parametrize(
    ("interim_nav", "gap", "message"),
    [
        ("roll_forward", 0, "interim_nav must be one of"),
        ("roll_forward_cash_adjusted", -1, "max_nav_gap_days must be >= 0"),
        ("roll_forward_cash_adjusted", True, "max_nav_gap_days must be an integer"),
        ("roll_forward_cash_adjusted", 30.0, "max_nav_gap_days must be an integer"),
    ],
)
def test_invalid_policy_values_are_refused(interim_nav: str, gap: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _hand(interim_nav=interim_nav, max_nav_gap_days=gap)


def test_common_pme_requirements_are_refused() -> None:
    history = _history((T1, 50.0))
    with pytest.raises(ValueError, match="residual value"):
        _run(_resolved(HAND, None), history)
    with pytest.raises(ValueError, match="paid-in capital above zero"):
        _run(_resolved([(T0, "distribution", 30.0)], HAND_NAV), history)
    with pytest.raises(ValueError, match="no FX"):
        _run(_resolved(HAND, HAND_NAV, currency="EUR"), history)
    gappy = _index([(T0, 100.0), (T2, 160.0)])
    with pytest.raises(ValueError, match="flow date 2022-01-01"):
        _run(_resolved(HAND, HAND_NAV), history, gappy)
    with pytest.raises(ValueError, match="unknown day-count"):
        mpme(
            _resolved(HAND, HAND_NAV),
            history,
            INDEX,
            lookup="exact",
            max_gap_days=0,
            day_count="30/360",
            interim_nav="refuse",
            max_nav_gap_days=0,
        )  # type: ignore[arg-type]


def test_non_model_inputs_are_refused() -> None:
    with pytest.raises(ValueError, match="FundNavHistory"):
        _run(_resolved(HAND, HAND_NAV), (NavObservation(date=T1, value=50.0),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ResolvedCashFlows"):
        _run(_fund(HAND, HAND_NAV), _history((T1, 50.0)))  # type: ignore[arg-type]


def test_policy_arguments_are_keyword_only_without_defaults() -> None:
    resolved, history = _resolved(HAND, HAND_NAV), _history((T1, 50.0))
    with pytest.raises(TypeError):
        mpme(resolved, history, INDEX, "exact", 0, DAY_COUNT, "refuse", 0)  # type: ignore[misc]
    with pytest.raises(TypeError):
        mpme(
            resolved,
            history,
            INDEX,
            lookup="exact",
            max_gap_days=0,  # type: ignore[call-arg]
            day_count=DAY_COUNT,
            max_nav_gap_days=0,
        )
    with pytest.raises(TypeError):
        mpme(
            resolved,
            history,
            INDEX,
            lookup="exact",
            max_gap_days=0,  # type: ignore[call-arg]
            day_count=DAY_COUNT,
            interim_nav="refuse",
        )


def test_fund_nav_history_is_ascending_unique_and_non_empty() -> None:
    history = _history((T2, 88.0), (T0, 100.0), (T1, 50.0))
    assert [item.date for item in history.observations] == [T0, T1, T2]
    with pytest.raises(ValidationError, match="duplicate NAV date 2022-01-01"):
        _history((T1, 50.0), (T1, 51.0))
    with pytest.raises(ValidationError):
        FundNavHistory(observations=())
    with pytest.raises(ValidationError, match="not a datetime"):
        FundNavHistory(observations=(NavObservation(date=datetime(2022, 1, 1), value=1.0),))
    with pytest.raises(ValidationError):
        _history((T1, -1.0))  # a NAV is Money, >= 0
    assert issubclass(ValidationError, ValueError)  # refusals stay ValueError


# --- Fund IRR refusal, no distribution, GGS -----------------------------------------


def test_fund_irr_refusal_is_carried_as_none() -> None:
    # Call 100 and distribution 100 at T0 (fund NAV 50 after both), residual 50 at T1.
    # The fund's nets: 0 at T0 (dropped), +50 at T1: one date, so its IRR is refused.
    #   T0: X = 100; w = 100 / 150 = 2/3; Dist_mPME = 66.67; NAV_mPME = 33.33.
    #   T1: X = 33.33 * 1.2 = 40. mPME series -33.33, +40: IRR 20%.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T0, "distribution", 100.0)]
    result = _run(_resolved(flows, (T1, 50.0), as_of=T1), _history((T0, 50.0)))
    assert result.fund_irr is None
    assert result.spread is None and result.log_spread is None
    assert result.mpme_irr.irr == pytest.approx(0.20, rel=1e-12)
    assert "the fund IRR is refused" in " ".join(result.assumptions)


def test_without_distributions_the_mpme_never_sells() -> None:
    # Calls of 100 at T0 and 50 at T1; NAV_mPME,T = FV(C) = 100 * 1.6 + 50 * 160/120.
    flows: list[Flow] = [(T0, "contribution", 100.0), (T1, "contribution", 50.0)]
    result = _run(_resolved(flows, (T2, 200.0)), _history((T2, 200.0)))
    assert all(step.weight == 0.0 and step.fund_nav is None for step in result.path)
    assert result.terminal_value == pytest.approx(result.fv_contributions, rel=1e-15)
    assert "never sells" in " ".join(result.assumptions)


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


@pytest.mark.parametrize("interim_nav", ["refuse", "roll_forward_cash_adjusted"])
def test_ggs_displayed_inputs_carry_no_interim_navs(interim_nav: InterimNavPolicy) -> None:
    # Gredil, Griffiths & Stucke (2014) Exhibits 5-6 display the flows, the index and NAV
    # 75 at the end, but no interim NAV. The mPME needs the fund's NAV at every
    # distribution date, so it is refused at the first one, not guessed. No published
    # mPME figure exists in the fixture and none is asserted here.
    resolved = _resolved(GGS_FLOWS, (GGS_END, 75.0), as_of=GGS_END)
    with pytest.raises(ValueError, match="2003-12-31"):
        _run(
            resolved,
            _history((GGS_END, 75.0)),
            GGS_INDEX,
            interim_nav=interim_nav,
            max_nav_gap_days=0 if interim_nav == "refuse" else 36500,
        )


# --- Assumptions, hashing, immutability ---------------------------------------------


def test_assumptions_label_the_reconstruction_and_every_convention() -> None:
    result = _roll(110.0, 30)
    text = " ".join(result.assumptions)
    assert "labelled reconstruction of Cambridge Associates' modified PME" in text
    assert "does not claim to reproduce CA's figures" in text
    assert "eq. (9)" in text and "eq. (11) as printed" in text and "is not used" in text
    assert "grow, invest the call, then sell" in text
    assert "w_t = 1 leaves exactly 0" in text
    assert "Gross legs" in text
    assert "Interim NAV policy: roll_forward_cash_adjusted" in text
    assert "never goes short" in text
    assert "enter the mPME benchmark itself" in text
    assert "Index lookup: exact" in text and "No FX" in text and "net_lp" in text
    assert "ACT/365F" in text
    # Never a claim to reproduce Cambridge Associates.
    assert "reproduces Cambridge" not in text and "CA's published algebra" not in text
    assert "Interim NAV policy: refuse" in " ".join(_hand().assumptions)
    assert "Fund NAV reported on the distribution date(s) 2022-01-01." in _hand().assumptions


def test_input_hash_covers_the_nav_history_and_both_policies() -> None:
    base = _hand(_history((T1, 50.0), (T2, 88.0)))
    permuted = _hand(_history((T2, 88.0), (T1, 50.0)))
    assert permuted.input_hash == base.input_hash
    assert permuted == base
    extra = _hand(_history((T0, 1.0), (T1, 50.0), (T2, 88.0)))  # an unused observation
    assert extra.terminal_value == base.terminal_value
    assert extra.input_hash != base.input_hash
    rolled = _hand(_history((T1, 50.0), (T2, 88.0)), interim_nav="roll_forward_cash_adjusted")
    assert rolled.mpme_irr == base.mpme_irr and rolled.input_hash != base.input_hash
    wider = _hand(
        _history((T1, 50.0), (T2, 88.0)),
        interim_nav="roll_forward_cash_adjusted",
        max_nav_gap_days=10,
    )
    assert wider.input_hash != rolled.input_hash
    icm = ln_pme(
        _resolved(HAND, HAND_NAV), INDEX, lookup="exact", max_gap_days=0, day_count=DAY_COUNT
    )
    assert icm.input_hash != base.input_hash  # the method is part of the hash


def test_results_are_frozen() -> None:
    result = _hand()
    with pytest.raises(ValidationError):
        result.terminal_value = 0.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.path[1].weight = 0.0  # type: ignore[misc]
    history = _history((T1, 50.0))
    with pytest.raises(ValidationError):
        history.observations = ()  # type: ignore[misc]


# --- Identities and properties (contract section 12) --------------------------------

PROPERTY = settings(max_examples=80, deadline=None)
_AMOUNT = st.floats(min_value=10.0, max_value=1000.0)
_GAP = st.integers(min_value=90, max_value=720)


def _dates(draw: st.DrawFn, n: int) -> list[date]:
    dates = [T0]
    for gap in draw(st.lists(_GAP, min_size=n - 1, max_size=n - 1)):
        dates.append(dates[-1] + timedelta(days=gap))
    return dates


@st.composite
def _tracking(draw: st.DrawFn) -> tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex]:
    """A fund that holds the index: calls buy it and distributions sell part of it.

    Its NAV is the index value of its own flows, ``P_t = P_prev * I_t / I_prev + C_t - D_t``,
    observed at every distribution date and at ``T``.
    """
    n = draw(st.integers(min_value=2, max_value=6))
    dates = _dates(draw, n)
    levels = draw(st.lists(st.floats(min_value=50.0, max_value=200.0), min_size=n, max_size=n))
    flows: list[Flow] = []
    observations: list[tuple[date, float]] = []
    position = 0.0
    for i, (on, level) in enumerate(zip(dates, levels, strict=True)):
        if i:
            position *= level / levels[i - 1]
        if i == 0 or draw(st.booleans()):
            amount = draw(_AMOUNT)
            flows.append((on, "contribution", amount))
            position += amount
        if i and draw(st.booleans()):
            # Sell part of the position; all of it only on the last date.
            top = 1.0 if i == n - 1 else 0.95
            paid = draw(st.floats(min_value=0.05, max_value=top)) * position
            flows.append((on, "distribution", paid))
            position -= paid
            observations.append((on, position))
    if not observations or observations[-1][0] != dates[-1]:
        observations.append((dates[-1], position))
    resolved = _resolved(flows, (dates[-1], position), as_of=dates[-1])
    return resolved, _history(*observations), _index(list(zip(dates, levels, strict=True)))


@st.composite
def _arbitrary(
    draw: st.DrawFn, *, wide: bool = False
) -> tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex]:
    """Calls and distributions with arbitrary non-negative interim NAVs (zeros included).

    A distribution date gets its own observation or, when the zero-return roll from the
    previous observation stays clearly positive, is left to the roll-forward.
    """
    n = draw(st.integers(min_value=2, max_value=6))
    dates = _dates(draw, n)
    level = st.floats(min_value=1e-3, max_value=1e3) if wide else st.floats(50.0, 200.0)
    levels = draw(st.lists(level, min_size=n, max_size=n))
    # A NAV near the bottom of the float range makes 1 - w_t underflow, which is refused
    # (test_an_underflowing_weight_is_refused_naming_the_date); here 0 or an ordinary NAV.
    nav_value = st.one_of(st.just(0.0), st.floats(min_value=1e-6, max_value=2000.0))
    flows: list[Flow] = []
    observations: list[tuple[date, float]] = []
    last_nav: float | None = None
    since: list[float] = []  # signed flows after the last observation
    for i, on in enumerate(dates[:-1] if n > 1 else dates):
        called = i == 0 or draw(st.booleans())
        paid = i > 0 and (not called or draw(st.booleans()))
        if called:
            amount = draw(_AMOUNT)
            flows.append((on, "contribution", amount))
            since.append(amount)
        if paid:
            amount = draw(_AMOUNT)
            flows.append((on, "distribution", amount))
            since.append(-amount)
            rolled = None if last_nav is None else math.fsum([last_nav, *since])
            if rolled is None or rolled < 1e-6 * sum(map(abs, since)) or draw(st.booleans()):
                last_nav = draw(nav_value)
                observations.append((on, last_nav))
                since = []
    last = dates[-1]
    if draw(st.booleans()):
        flows.append((last, "contribution", draw(_AMOUNT)))
    residual = draw(nav_value)
    if not observations or draw(st.booleans()):
        observations.append((last, residual))
    resolved = _resolved(flows, (last, residual), as_of=last)
    return resolved, _history(*observations), _index(list(zip(dates, levels, strict=True)))


def _roll_run(
    resolved: ResolvedCashFlows, history: FundNavHistory, benchmark: BenchmarkIndex
) -> MpmeResult:
    return _run(
        resolved,
        history,
        benchmark,
        interim_nav="roll_forward_cash_adjusted",
        max_nav_gap_days=100_000,
    )


def _same_irr(a: IrrResult | None, b: IrrResult | None) -> None:
    """Same status and the same roots, to rounding."""
    if a is None or b is None:
        assert a is None and b is None
        return
    assert a.status == b.status
    assert len(a.roots) == len(b.roots)
    for x, y in zip(a.roots, b.roots, strict=True):
        assert x.rate == pytest.approx(y.rate, rel=1e-7, abs=1e-9)


@PROPERTY
@given(_tracking())
def test_tracking_fund_mpme_is_the_fund_itself(
    case: tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex],
) -> None:
    # With NAV_t = P_t, by induction NAV_mPME,prev = P_prev, so X_t = P_t + D_t,
    # Dist_mPME,t = D_t / (D_t + P_t) * (P_t + D_t) = D_t and NAV_mPME,t = P_t.
    resolved, history, benchmark = case
    result = _run(resolved, history, benchmark)
    assert resolved.residual_value is not None
    scale = resolved.paid_in
    for step in result.path:
        assert step.mpme_distribution == pytest.approx(
            step.distribution, rel=1e-9, abs=1e-12 * scale
        )
    assert result.terminal_value == pytest.approx(
        resolved.residual_value, rel=1e-9, abs=1e-12 * scale
    )
    _same_irr(result.mpme_irr, result.fund_irr)
    assert result.fund_irr is not None
    if result.fund_irr.status == "unique":
        assert result.spread == pytest.approx(0.0, abs=1e-8)
        assert result.log_spread == pytest.approx(0.0, abs=1e-8)


def test_tracking_fund_with_a_same_day_recall() -> None:
    # A fund holding the index recalls 30 at T1 (call 30 and distribution 30). Its NAV is
    # the index value of its flows: 120 + 30 - 30 = 120 at T1, 120 * 160/120 = 160 at T2.
    #   mPME T1: X = 120 + 30 = 150; w = 30 / 150 = 1/5; Dist_mPME = 30; NAV_mPME = 120.
    # The fund's net at T1 is exactly 0 and dropped. The mPME net -30 + Dist_mPME is zero
    # in exact arithmetic, and in floats at most rounding of zero, so it is dropped too:
    # both series are -100 at T0 and +160 at T2, IRR sqrt(1.6) - 1, spread 0.
    flows: list[Flow] = [*HAND[:1], (T1, "contribution", 30.0), (T1, "distribution", 30.0)]
    result = _run(_resolved(flows, (T2, 160.0)), _history((T1, 120.0)))
    assert [d for d, _ in _series(result)] == [T0, T2]
    assert result.mpme_irr.irr == pytest.approx(math.sqrt(1.6) - 1.0, rel=1e-12)
    assert result.spread == pytest.approx(0.0, abs=1e-12)


@PROPERTY
@given(_arbitrary(), st.floats(min_value=1e-3, max_value=1e3))
def test_rescaling_the_index_changes_nothing(
    case: tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex], k: float
) -> None:
    resolved, history, benchmark = case
    scaled = _index([(item.date, item.level * k) for item in benchmark.levels])
    base, moved = _roll_run(resolved, history, benchmark), _roll_run(resolved, history, scaled)
    scale = resolved.paid_in
    for a, b in zip(base.path, moved.path, strict=True):
        assert b.weight == a.weight  # w_t does not involve the index at all
        assert b.fund_nav == a.fund_nav
        assert b.position_after == pytest.approx(a.position_after, rel=1e-9, abs=1e-12 * scale)
        assert b.mpme_distribution == pytest.approx(
            a.mpme_distribution, rel=1e-9, abs=1e-12 * scale
        )
    assert moved.terminal_value == pytest.approx(base.terminal_value, rel=1e-9, abs=1e-12 * scale)
    _same_irr(base.mpme_irr, moved.mpme_irr)


@PROPERTY
@given(_arbitrary(), st.floats(min_value=1e-3, max_value=1e3))
def test_scaling_flows_and_every_nav_by_k_changes_nothing(
    case: tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex], k: float
) -> None:
    resolved, history, benchmark = case
    assert resolved.residual_value is not None
    flows = [(flow.date, flow.kind, flow.amount * k) for flow in resolved.flows]
    as_of = resolved.as_of
    scaled_resolved = _resolved(flows, (as_of, resolved.residual_value * k), as_of=as_of)
    scaled_history = _history(*((item.date, item.value * k) for item in history.observations))
    base = _roll_run(resolved, history, benchmark)
    moved = _roll_run(scaled_resolved, scaled_history, benchmark)
    scale = resolved.paid_in * k
    for a, b in zip(base.path, moved.path, strict=True):
        assert b.weight == pytest.approx(a.weight, rel=1e-12)
        assert b.position_after == pytest.approx(a.position_after * k, rel=1e-9, abs=1e-12 * scale)
    assert moved.terminal_value == pytest.approx(
        base.terminal_value * k, rel=1e-9, abs=1e-12 * scale
    )
    _same_irr(base.mpme_irr, moved.mpme_irr)
    _same_irr(base.fund_irr, moved.fund_irr)


@PROPERTY
@given(_arbitrary(wide=True))
def test_the_mpme_never_goes_short(
    case: tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex],
) -> None:
    resolved, history, benchmark = case
    result = _roll_run(resolved, history, benchmark)
    for step in result.path:
        assert 0.0 <= step.weight <= 1.0
        assert step.position_before_sale >= 0.0
        assert step.mpme_distribution >= 0.0
        assert step.position_after >= 0.0
        if step.fund_nav == 0.0:
            assert step.weight == 1.0 and step.position_after == 0.0
    assert result.terminal_value >= 0.0
    # Every computed amount in the series is an inflow; only calls are outflows.
    calls = {flow.date for flow in resolved.flows if flow.kind == "contribution"}
    assert all(item.amount > 0 or item.date in calls for item in result.mpme_series)


@PROPERTY
@given(_arbitrary())
def test_every_distribution_date_reports_its_nav_source(
    case: tuple[ResolvedCashFlows, FundNavHistory, BenchmarkIndex],
) -> None:
    resolved, history, benchmark = case
    assume(resolved.distributed > 0)
    result = _roll_run(resolved, history, benchmark)
    observed = {item.date for item in history.observations}
    gaps = [0]
    for step in result.path:
        if step.distribution == 0.0:
            assert step.fund_nav is None and step.fund_nav_source == "none"
            continue
        assert step.fund_nav is not None and step.fund_nav_observation_date is not None
        if step.date in observed:
            assert step.fund_nav_source == "reported"
            assert step.fund_nav_observation_date == step.date
        else:
            assert step.fund_nav_source == "rolled_forward"
            assert step.fund_nav_observation_date < step.date
            gaps.append((step.date - step.fund_nav_observation_date).days)
    assert result.max_nav_gap_used_days == max(gaps)


# --- Final review (contract §13) ------------------------------------------------------


def test_long_permitted_gaps_run_in_linear_time_with_identical_results() -> None:
    # R3-4 (out/r3/performance_mpme_long_gap.py), contract §13.4: 10,000 flows, 100,000
    # index levels and 1,000 NAV observations over the first 1,000 days with
    # max_nav_gap_days 9000. Day 0 contributes 10,000 and each later day distributes 0.125
    # (exact binary fractions), so NAV_T = 10000 - 9999 * 0.125 = 8750.125 and the mPME is
    # the fund itself: spread 0. It took ~3 s when every roll rescanned every flow, which is
    # quadratic in the flows. Asserted as a scaling ratio rather than a wall-clock bound, so
    # the test means the same on a slow CI runner under coverage: 4x the flows measured
    # 2.34x (2.22x under branch coverage); the quadratic rescan gives well over 10x. Input
    # construction is outside the timed section; each size keeps its best of two runs.
    start = date(1800, 1, 1)
    index = _index([(start + timedelta(days=i), 1.0) for i in range(100_000)])
    history = _history(*[(start + timedelta(days=i), 10000 - i * 0.125) for i in range(1000)])

    def timed(n: int) -> tuple[float, MpmeResult]:
        end = start + timedelta(days=n - 1)
        flows: list[Flow] = [
            (
                start + timedelta(days=i),
                "contribution" if i == 0 else "distribution",
                10000.0 if i == 0 else 0.125,
            )
            for i in range(n)
        ]
        resolved = _resolved(flows, (end, 10000 - (n - 1) * 0.125), as_of=end)
        best, runs = math.inf, []
        for _ in range(2):
            began = time.perf_counter()
            runs.append(
                mpme(
                    resolved,
                    history,
                    index,
                    lookup="exact",
                    max_gap_days=0,
                    day_count=DAY_COUNT,
                    interim_nav="roll_forward_cash_adjusted",
                    max_nav_gap_days=9000,
                )
            )
            best = min(best, time.perf_counter() - began)
        return best, runs[-1]

    small, _ = timed(2_500)
    large, result = timed(10_000)
    assert large / small < 6.0
    assert result.terminal_value == 8750.125
    assert result.spread == 0.0
    assert min(step.position_after for step in result.path) == 8750.125
    # The last interim roll is day 9998 from day 999 (8999 days); day 9999 is as_of, whose
    # NAV is the residual value and is not an interim roll.
    assert result.max_nav_gap_used_days == 8999


def test_roll_window_sums_are_exact_not_differences_of_prefix_totals() -> None:
    # Contribute 2e16 at T0, distribute 1e16 on day 1 (NAV 1e16), NAV 5 on day 2, then 1 on
    # days 3 and 4. The day-3 and day-4 NAVs roll from day 2 over (day 2, t]: 5 - 1 = 4 and
    # 5 - 2 = 3 exactly. A prefix-total difference (1e16 + 1) - 1e16 would give 0 here.
    d = [T0 + timedelta(days=i) for i in range(6)]
    flows: list[Flow] = [
        (d[0], "contribution", 2e16),
        (d[1], "distribution", 1e16),
        (d[3], "distribution", 1.0),
        (d[4], "distribution", 1.0),
    ]
    resolved = _resolved(flows, (d[5], 3.0), as_of=d[5])
    index = _index([(day, 100.0) for day in d])
    history = _history((d[1], 1e16), (d[2], 5.0))
    result = mpme(
        resolved,
        history,
        index,
        lookup="exact",
        max_gap_days=0,
        day_count=DAY_COUNT,
        interim_nav="roll_forward_cash_adjusted",
        max_nav_gap_days=5,
    )
    assert (_step(result, d[3]).fund_nav, _step(result, d[3]).fund_nav_source) == (
        4.0,
        "rolled_forward",
    )
    assert _step(result, d[4]).fund_nav == 3.0
    assert _step(result, d[4]).fund_nav_observation_date == d[2]


def test_mpme_carries_structured_dropped_nets_and_a_public_policy_check() -> None:
    assert _hand().dropped_computed_nets == ()
    check_interim_policy("roll_forward_cash_adjusted", 30)
    with pytest.raises(ValueError, match="must be 0"):
        check_interim_policy("refuse", 1)


@pytest.mark.parametrize("stamp", [datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=UTC)])
def test_mpme_step_date_fields_refuse_datetime(stamp: datetime) -> None:
    # R3-11, contract §13.6: MpmeStep coerced midnight datetimes before.
    step = _hand().path[1].model_dump()
    for field in ("date", "fund_nav_observation_date"):
        with pytest.raises(ValidationError, match="not a datetime"):
            MpmeStep.model_validate({**step, field: stamp})
