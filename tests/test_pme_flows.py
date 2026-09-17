"""Fund cash flows and ``resolve``: every rule of the contract, with hand numbers."""

from __future__ import annotations

import itertools
import math
import sys
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from ovf.pme.flows import (
    ENGINE_VERSION,
    CashFlow,
    DatedAmount,
    FundCashFlows,
    NavObservation,
    NavRollForward,
    NearZeroNet,
    ResolvedCashFlows,
    canonical_hash,
    finite_fsum,
    finite_product,
    finite_ratio,
    near_zero_nets,
    net_by_date,
    net_stated_by_date,
    resolve,
)
from ovf.pme.irr import fund_irr

D0 = date(2020, 1, 15)
D1 = date(2020, 6, 30)
D2 = date(2021, 3, 31)
D3 = date(2021, 12, 31)


def _c(day: date, amount: float, flow_id: str | None = None) -> CashFlow:
    return CashFlow(date=day, kind="contribution", amount=amount, flow_id=flow_id)


def _d(day: date, amount: float, flow_id: str | None = None) -> CashFlow:
    return CashFlow(date=day, kind="distribution", amount=amount, flow_id=flow_id)


def _fund(
    flows: tuple[CashFlow, ...],
    nav: NavObservation | None,
    *,
    basis: str = "net_lp",
    currency: str = "USD",
) -> FundCashFlows:
    return FundCashFlows(
        name="Fund I",
        currency=currency,
        basis=basis,
        flows=flows,
        nav=nav,  # type: ignore[arg-type]
    )


FLOWS = (_c(D0, 100.0), _c(D1, 50.0), _d(D2, 30.0))


# --- Models -----------------------------------------------------------------------


@pytest.mark.parametrize("amount", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_cash_flow_amount_must_be_positive_and_finite(amount: float) -> None:
    with pytest.raises(ValidationError):
        CashFlow(date=D0, kind="contribution", amount=amount)


def test_cash_flow_kind_is_closed() -> None:
    with pytest.raises(ValidationError):
        CashFlow(date=D0, kind="fee", amount=1.0)  # type: ignore[arg-type]
    assert _c(D0, 5.0).signed_amount == -5.0
    assert _d(D0, 5.0).signed_amount == 5.0


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf])
def test_nav_must_be_non_negative_and_finite(value: float) -> None:
    with pytest.raises(ValidationError):
        NavObservation(date=D0, value=value)


def test_dated_amount_must_be_finite() -> None:
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            DatedAmount(date=D0, amount=bad)
    assert DatedAmount(date=D0, amount=-3.0).amount == -3.0


def test_models_are_frozen() -> None:
    flow = _c(D0, 1.0)
    with pytest.raises(ValidationError):
        flow.amount = 2.0  # type: ignore[misc]


def test_fund_requires_flows_name_currency_and_basis() -> None:
    with pytest.raises(ValidationError):
        _fund((), None)
    with pytest.raises(ValidationError):
        FundCashFlows(name="", currency="USD", basis="net_lp", flows=FLOWS, nav=None)
    with pytest.raises(ValidationError):
        FundCashFlows(name="F", currency="", basis="net_lp", flows=FLOWS, nav=None)
    with pytest.raises(ValidationError):
        _fund(FLOWS, None, basis="gross")
    with pytest.raises(ValidationError):  # nav has no default: it must be stated
        FundCashFlows(name="F", currency="USD", basis="net_lp", flows=FLOWS)  # type: ignore[call-arg]


def test_duplicate_flow_id_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate flow_id 'call-1'"):
        _fund((_c(D0, 100.0, "call-1"), _c(D1, 50.0, "call-1")), None)
    # None ids may repeat; identical id-less flows are two flows.
    fund = _fund((_c(D0, 100.0), _c(D0, 100.0)), None)
    assert len(fund.flows) == 2


def test_canonical_order() -> None:
    fund = _fund(
        (_d(D1, 5.0, "b"), _c(D1, 7.0), _c(D0, 9.0), _d(D1, 5.0, "a"), _c(D1, 3.0)),
        None,
    )
    # date, then contributions first, then amount, then flow_id (None first).
    assert [(f.date, f.kind, f.amount, f.flow_id) for f in fund.flows] == [
        (D0, "contribution", 9.0, None),
        (D1, "contribution", 3.0, None),
        (D1, "contribution", 7.0, None),
        (D1, "distribution", 5.0, "a"),
        (D1, "distribution", 5.0, "b"),
    ]


# --- Rule 1: dates ----------------------------------------------------------------


def test_flow_after_as_of_refused() -> None:
    fund = _fund(FLOWS, NavObservation(date=D1, value=80.0))
    with pytest.raises(ValueError, match="never truncated"):
        resolve(fund, as_of=D1, stale_nav="refuse")


def test_as_of_before_first_flow_refused() -> None:
    fund = _fund(FLOWS, None)
    with pytest.raises(ValueError, match="before the first flow"):
        resolve(fund, as_of=date(2019, 12, 31), stale_nav="refuse")


def test_unknown_policy_and_bad_as_of_refused() -> None:
    fund = _fund(FLOWS, None)
    with pytest.raises(ValueError, match="stale_nav"):
        resolve(fund, as_of=D3, stale_nav="interpolate")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="as_of"):
        resolve(fund, as_of="2021-12-31", stale_nav="refuse")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="FundCashFlows"):
        resolve(FLOWS, as_of=D3, stale_nav="refuse")  # type: ignore[arg-type]


# --- Rules 2-4: NAV presence and date ---------------------------------------------


def test_nav_none() -> None:
    resolved = resolve(_fund(FLOWS, None), as_of=D3, stale_nav="refuse")
    assert resolved.residual_value is None
    assert resolved.nav_source == "none"
    assert resolved.nav_roll_forward is None
    # No residual in the series: only the flows, netted.
    assert [(a.date, a.amount) for a in resolved.net_by_date] == [
        (D0, -100.0),
        (D1, -50.0),
        (D2, 30.0),
    ]
    assert any("NAV source: none" in line for line in resolved.assumptions)


def test_nav_after_as_of_refused() -> None:
    fund = _fund(FLOWS, NavObservation(date=D3, value=80.0))
    with pytest.raises(ValueError, match="after as_of"):
        resolve(fund, as_of=D2, stale_nav="roll_forward_cash_adjusted")


def test_nav_reported_at_as_of() -> None:
    resolved = resolve(
        _fund(FLOWS, NavObservation(date=D3, value=140.0)), as_of=D3, stale_nav="refuse"
    )
    assert resolved.nav_source == "reported_at_as_of"
    assert resolved.residual_value == 140.0
    assert resolved.nav_roll_forward is None
    assert resolved.paid_in == 150.0
    assert resolved.distributed == 30.0
    assert [(a.date, a.amount) for a in resolved.net_by_date] == [
        (D0, -100.0),
        (D1, -50.0),
        (D2, 30.0),
        (D3, 140.0),
    ]
    assert resolved.engine_version == ENGINE_VERSION == "pme-v1"


# --- Rule 5: stale NAV ------------------------------------------------------------


def test_stale_nav_refused_under_refuse() -> None:
    fund = _fund(FLOWS, NavObservation(date=D2, value=120.0))
    with pytest.raises(ValueError, match="stale_nav='refuse'"):
        resolve(fund, as_of=D3, stale_nav="refuse")


def test_stale_nav_refused_even_without_later_flows() -> None:
    fund = _fund(FLOWS, NavObservation(date=D2, value=120.0))
    with pytest.raises(ValueError):
        resolve(fund, as_of=D3, stale_nav="refuse")


def test_roll_forward_hand_checked() -> None:
    nav_date = date(2021, 6, 30)
    as_of = date(2021, 12, 31)
    flows = (
        _c(date(2020, 1, 1), 200.0),
        _c(nav_date, 20.0),  # ON the NAV date: already in the NAV
        _d(nav_date, 11.0),  # ON the NAV date: already in the NAV
        _c(date(2021, 9, 30), 30.0),  # after: added
        _d(date(2021, 11, 15), 45.0),  # after: subtracted
        _d(as_of, 5.0),  # on as_of: in (nav.date, as_of], subtracted
    )
    fund = _fund(flows, NavObservation(date=nav_date, value=100.0))
    resolved = resolve(fund, as_of=as_of, stale_nav="roll_forward_cash_adjusted")
    # 100 + 30 - 45 - 5 = 80
    assert resolved.nav_source == "rolled_forward"
    assert resolved.residual_value == 80.0
    roll = resolved.nav_roll_forward
    assert roll is not None
    assert roll.reported_date == nav_date
    assert roll.reported_value == 100.0
    assert roll.contributions_after == 30.0
    assert roll.distributions_after == 50.0
    assert roll.rolled_value == 80.0
    # The residual is added to the as_of net: -0 contributions + 5 distribution + 80.
    assert resolved.net_by_date[-1] == DatedAmount(date=as_of, amount=85.0)
    # NAV date net: -20 + 11 = -9.
    assert DatedAmount(date=nav_date, amount=-9.0) in resolved.net_by_date
    line = next(a for a in resolved.assumptions if a.startswith("NAV source"))
    assert "zero return" in line and "2021-06-30" in line and "80.0" in line


def test_roll_forward_to_zero_is_allowed() -> None:
    fund = _fund((_c(D0, 100.0), _d(D3, 60.0)), NavObservation(date=D2, value=60.0))
    resolved = resolve(fund, as_of=D3, stale_nav="roll_forward_cash_adjusted")
    assert resolved.residual_value == 0.0
    assert resolved.net_by_date[-1] == DatedAmount(date=D3, amount=60.0)


def test_negative_rolled_value_refused() -> None:
    fund = _fund((_c(D0, 100.0), _d(D3, 60.0)), NavObservation(date=D2, value=59.0))
    with pytest.raises(ValueError, match="inconsistent"):
        resolve(fund, as_of=D3, stale_nav="roll_forward_cash_adjusted")


def test_roll_forward_policy_with_current_nav_is_plain_report() -> None:
    fund = _fund(FLOWS, NavObservation(date=D3, value=140.0))
    resolved = resolve(fund, as_of=D3, stale_nav="roll_forward_cash_adjusted")
    assert resolved.nav_source == "reported_at_as_of"
    assert resolved.nav_roll_forward is None


# --- Rule 6 and netting -----------------------------------------------------------


def test_same_date_netting_and_exact_zero() -> None:
    flows = (
        _c(D0, 100.0),
        _c(D1, 40.0),
        _d(D1, 15.0),  # D1 nets to -25
        _c(D2, 0.1),
        _c(D2, 0.2),
        _d(D2, 0.3),  # cancels in decimal; the binary legs leave a tiny fsum net
        _d(D3, 12.5),
    )
    resolved = resolve(
        _fund(flows, NavObservation(date=D3, value=7.5)), as_of=D3, stale_nav="refuse"
    )
    got = [(a.date, a.amount) for a in resolved.net_by_date]
    # fsum(-0.1, -0.2, +0.3) = -2.8e-17, within eps * (0.1 + 0.2 + 0.3) = 1.3e-16: the
    # legs cancel within decimal-representation noise, so D2 counts as zero (contract
    # §11.3) and its raw net is named.
    d2_net = math.fsum([-0.1, -0.2, 0.3])
    assert d2_net != 0.0 and abs(d2_net) <= sys.float_info.epsilon * 0.6
    assert got == [(D0, -100.0), (D1, -25.0), (D3, 20.0)]  # D3: 12.5 + 7.5 residual
    assert resolved.netted_to_zero == (D2,)
    assert any(repr(d2_net) in line for line in resolved.assumptions)
    # Gross sums keep both legs.
    assert resolved.paid_in == math.fsum([100.0, 40.0, 0.1, 0.2])
    assert resolved.distributed == math.fsum([15.0, 0.3, 12.5])


def test_date_netting_to_exactly_zero_is_dropped_and_listed() -> None:
    flows = (_c(D0, 100.0), _c(D1, 25.0), _d(D1, 25.0), _d(D2, 10.0))
    resolved = resolve(
        _fund(flows, NavObservation(date=D3, value=120.0)), as_of=D3, stale_nav="refuse"
    )
    assert resolved.netted_to_zero == (D1,)
    assert D1 not in [a.date for a in resolved.net_by_date]
    assert any("2020-06-30" in a and "exactly zero" in a for a in resolved.assumptions)
    # Multiples still see both legs.
    assert resolved.paid_in == 125.0
    assert resolved.distributed == 35.0


def test_residual_can_net_as_of_to_zero() -> None:
    # A contribution on as_of exactly offset by the residual value.
    flows = (_c(D0, 100.0), _d(D2, 110.0), _c(D3, 5.0))
    resolved = resolve(
        _fund(flows, NavObservation(date=D3, value=5.0)), as_of=D3, stale_nav="refuse"
    )
    assert resolved.netted_to_zero == (D3,)
    assert [a.date for a in resolved.net_by_date] == [D0, D2]


def test_zero_residual_adds_nothing() -> None:
    flows = (_c(D0, 100.0), _d(D2, 130.0))
    resolved = resolve(
        _fund(flows, NavObservation(date=D3, value=0.0)), as_of=D3, stale_nav="refuse"
    )
    assert resolved.residual_value == 0.0
    assert resolved.nav_source == "reported_at_as_of"
    assert resolved.netted_to_zero == ()
    assert [(a.date, a.amount) for a in resolved.net_by_date] == [(D0, -100.0), (D2, 130.0)]


def test_residual_added_to_as_of_net() -> None:
    flows = (_c(D0, 100.0), _c(D3, 10.0), _d(D3, 4.0))
    resolved = resolve(
        _fund(flows, NavObservation(date=D3, value=90.0)), as_of=D3, stale_nav="refuse"
    )
    # -10 + 4 + 90 = 84
    assert resolved.net_by_date[-1] == DatedAmount(date=D3, amount=84.0)


def test_net_by_date_helper() -> None:
    nets, zeros = net_by_date([(D1, 5.0), (D0, -3.0), (D1, -5.0), (D0, 1.0)])
    assert nets == [DatedAmount(date=D0, amount=-2.0)]
    assert zeros == [D1]


# --- Hash and assumptions ---------------------------------------------------------


def test_input_hash_is_order_free() -> None:
    flows = (_c(D0, 100.0, "a"), _c(D1, 50.0), _d(D2, 30.0, "z"), _d(D2, 30.0), _c(D2, 1.0))
    hashes = set()
    for perm in itertools.permutations(flows):
        fund = _fund(perm, NavObservation(date=D3, value=140.0))
        hashes.add(resolve(fund, as_of=D3, stale_nav="refuse").input_hash)
    assert len(hashes) == 1


def test_input_hash_changes_with_inputs() -> None:
    base = _fund(FLOWS, NavObservation(date=D3, value=140.0))
    h0 = resolve(base, as_of=D3, stale_nav="refuse").input_hash
    other_nav = _fund(FLOWS, NavObservation(date=D3, value=141.0))
    other_basis = _fund(FLOWS, NavObservation(date=D3, value=140.0), basis="gross_fund")
    other_policy = resolve(base, as_of=D3, stale_nav="roll_forward_cash_adjusted")
    assert resolve(other_nav, as_of=D3, stale_nav="refuse").input_hash != h0
    assert resolve(other_basis, as_of=D3, stale_nav="refuse").input_hash != h0
    assert other_policy.input_hash != h0
    assert len(h0) == 64


def test_canonical_hash_refuses_nan_and_accepts_dates() -> None:
    assert canonical_hash({"d": D0, "x": 1.0}) == canonical_hash({"x": 1.0, "d": "2020-01-15"})
    with pytest.raises(ValueError):
        canonical_hash({"x": math.nan})


@pytest.mark.parametrize(("basis", "currency"), [("net_lp", "USD"), ("gross_fund", "EUR")])
def test_assumptions_state_conventions(basis: str, currency: str) -> None:
    resolved = resolve(
        _fund(FLOWS, NavObservation(date=D3, value=140.0), basis=basis, currency=currency),
        as_of=D3,
        stale_nav="refuse",
    )
    text = "\n".join(resolved.assumptions)
    assert "Perspective: the investor (LP)" in text
    assert "Sign convention" in text and "contribution -> -amount" in text
    assert "end of day" in text
    assert f"Basis: {basis}" in text
    assert f"Currency: {currency}" in text
    assert "NAV source: reported at as_of" in text
    assert resolved.basis == basis
    assert resolved.currency == currency


def test_resolved_is_frozen_and_rejects_nan() -> None:
    resolved = resolve(_fund(FLOWS, None), as_of=D3, stale_nav="refuse")
    with pytest.raises(ValidationError):
        resolved.paid_in = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        resolved.model_copy(update={}).model_validate(
            {**resolved.model_dump(), "paid_in": math.nan}
        )


# --- Float range, datetime and signed zero (reviewer R1) ----------------------------


def test_gross_sums_outside_the_float_range_are_refused() -> None:
    # math.fsum raised OverflowError from resolve before; now a ValueError names the sum.
    with pytest.raises(ValueError, match="paid-in capital .* overflows"):
        resolve(
            _fund((_c(D0, 1e308), _c(D1, 1e308)), NavObservation(date=D1, value=0.0)),
            as_of=D1,
            stale_nav="refuse",
        )
    with pytest.raises(ValueError, match="distributed capital .* overflows"):
        resolve(
            _fund((_c(D0, 1.0), _d(D1, 1e308), _d(D2, 1e308)), NavObservation(date=D2, value=0.0)),
            as_of=D2,
            stale_nav="refuse",
        )


def test_same_date_net_outside_the_float_range_is_refused() -> None:
    with pytest.raises(ValueError, match="net amount on 2020-06-30 overflows"):
        resolve(
            _fund((_c(D0, 1.0), _d(D1, 1e308), _d(D1, 1e308)), NavObservation(date=D1, value=0.0)),
            as_of=D1,
            stale_nav="refuse",
        )
    with pytest.raises(ValueError, match="overflows"):
        net_by_date([(D0, 1e308), (D0, 1e308)])


def test_roll_forward_outside_the_float_range_is_refused() -> None:
    # NAV 1e308 at D1 plus a 1e308 contribution after it cannot be rolled to D2.
    fund = _fund((_c(D0, 1.0), _c(D2, 1e308)), NavObservation(date=D1, value=1e308))
    with pytest.raises(ValueError, match="rolled forward .* overflows"):
        resolve(fund, as_of=D2, stale_nav="roll_forward_cash_adjusted")


@pytest.mark.parametrize(
    "moment",
    [datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, 12, 30)],
)
def test_datetime_is_refused_in_every_date_field(moment: datetime) -> None:
    # Midnight and timezone-aware midnight too: pydantic would truncate them silently.
    with pytest.raises(ValidationError, match="not a datetime"):
        CashFlow(date=moment, kind="contribution", amount=1.0)
    with pytest.raises(ValidationError, match="not a datetime"):
        NavObservation(date=moment, value=1.0)
    with pytest.raises(ValidationError, match="not a datetime"):
        DatedAmount(date=moment, amount=1.0)


def test_signed_zero_hashes_like_zero() -> None:
    flows = (_c(D0, 100.0), _d(D1, 110.0))
    plus = resolve(_fund(flows, NavObservation(date=D1, value=0.0)), as_of=D1, stale_nav="refuse")
    minus = resolve(_fund(flows, NavObservation(date=D1, value=-0.0)), as_of=D1, stale_nav="refuse")
    assert plus.input_hash == minus.input_hash
    assert canonical_hash({"a": [-0.0, {"b": -0.0}]}) == canonical_hash({"a": [0.0, {"b": 0.0}]})


def test_float_range_helpers() -> None:
    assert finite_fsum([1e308, -1e308, 1.0], what="x") == 1.0
    with pytest.raises(ValueError, match="x overflows"):
        finite_fsum([1e308, 1e308], what="x")
    assert finite_product(0.0, 1e-300, what="p") == 0.0
    with pytest.raises(ValueError, match="p = .* underflows"):
        finite_product(1e-200, 1e-200, what="p")
    with pytest.raises(ValueError, match="p = .* overflows"):
        finite_product(1e200, 1e200, what="p")
    assert finite_ratio(0.0, 1e300, what="r") == 0.0
    with pytest.raises(ValueError, match="r = .* overflows"):
        finite_ratio(1e300, 1e-300, what="r")
    with pytest.raises(ValueError, match="r = .* underflows"):
        finite_ratio(1e-300, 1e300, what="r")


# --- Stated nets within decimal-representation noise (contract §11.3) ---------------


def test_cent_dust_on_one_date_counts_as_zero_and_is_named() -> None:
    # R2-3: +300000.30 -100000.10 -200000.20 on D1 nets to -2.9e-11 in binary; the bound
    # eps * sum|legs| = 2.2e-16 * 600000.6 = 1.3e-10 covers it.
    legs = [(D1, 300_000.30), (D1, -100_000.10), (D1, -200_000.20)]
    raw = math.fsum(amount for _, amount in legs)
    assert raw != 0.0
    nets, zeros, near_zero = net_stated_by_date([(D0, -1_000_000.0), *legs, (D2, 1_200_000.0)])
    assert zeros == [D1]
    assert [a.date for a in nets] == [D0, D2]
    bound = math.fsum(sys.float_info.epsilon * abs(amount) for _, amount in legs)
    record = NearZeroNet(date=D1, raw_net=raw, gross=600_000.6, bound=bound)
    assert near_zero == near_zero_nets(legs) == [record]
    assert abs(raw) <= bound
    # The generic numeric layer nets exactly (contract §11.3 scope): the raw dust stays.
    exact_nets, exact_zeros = net_by_date(legs)
    assert exact_zeros == [] and [(a.date, a.amount) for a in exact_nets] == [(D1, raw)]
    flows = (_c(D0, 1_000_000.0), _d(D1, 300_000.30), _c(D1, 100_000.10), _c(D1, 200_000.20))
    resolved = resolve(
        _fund(flows, NavObservation(date=D2, value=1_200_000.0)), as_of=D2, stale_nav="refuse"
    )
    assert resolved.netted_to_zero == (D1,)
    assert [a.date for a in resolved.net_by_date] == [D0, D2]
    assert any(
        repr(raw) in line and "decimal-representation" in line for line in resolved.assumptions
    )
    # The conventional fund keeps one sign change.
    assert fund_irr(resolved, day_count="ACT/365F").sign_changes == 1
    # Contract §13.2: the drop is a structured record on the resolved flows.
    assert resolved.stated_nets_within_noise == (record,)


def test_a_real_small_net_is_kept() -> None:
    # +(1e12 + 0.001) - 1e12 nets to ~0.001, far above eps * 2e12 = 4.4e-4: kept.
    nets, zeros, _ = net_stated_by_date([(D0, 1e12 + 0.001), (D0, -1e12)])
    assert zeros == [] and len(nets) == 1 and nets[0].amount == pytest.approx(0.001, rel=0.3)
    assert near_zero_nets([(D0, 1e12 + 0.001), (D0, -1e12)]) == []
    # A single leg, or legs of one sign, are never dust.
    assert near_zero_nets([(D0, 1e-300)]) == []
    assert near_zero_nets([(D0, 1e-300), (D0, 1e-300)]) == []


def test_generic_netting_is_exact_and_only_stated_netting_has_the_dust_rule() -> None:
    # +1e16 and -1e16 + 2 net to exactly 2. That is within eps * sum|legs| = 4.4, so as
    # STATED legs it counts as representation noise, but net_by_date (used by xirr and
    # npv) keeps the exact 2 (R1-2; contract §11.3 scope).
    legs = [(D0, 1e16), (D0, -1e16 + 2)]
    nets, zeros = net_by_date(legs)
    assert [(a.date, a.amount) for a in nets] == [(D0, 2.0)] and zeros == []
    stated_nets, stated_zeros, near_zero = net_stated_by_date(legs)
    assert stated_nets == [] and stated_zeros == [D0]
    (record,) = near_zero
    assert (record.date, record.raw_net, record.gross) == (D0, 2.0, 2e16 - 2)
    assert 2.0 <= record.bound


# --- FundCashFlows.through: the explicit, listed cut (R2-7) --------------------------


def test_through_keeps_flows_on_or_before_the_cut_and_lists_the_rest() -> None:
    # A quarter-end NAV at D1 with flows booked since: cut at D1 to measure at the NAV date.
    fund = _fund(
        (_c(D0, 100.0), _d(D1, 30.0), _c(D2, 20.0), _d(D3, 50.0)),
        NavObservation(date=D1, value=90.0),
    )
    cut, excluded = fund.through(D1)
    assert [(f.date, f.kind) for f in cut.flows] == [(D0, "contribution"), (D1, "distribution")]
    assert excluded == (_c(D2, 20.0), _d(D3, 50.0))
    assert (cut.name, cut.currency, cut.basis, cut.nav) == (
        fund.name,
        fund.currency,
        fund.basis,
        fund.nav,
    )
    resolved = resolve(cut, as_of=D1, stale_nav="refuse")
    assert resolved.residual_value == 90.0 and resolved.nav_source == "reported_at_as_of"
    # resolve itself still never truncates: the uncut fund at D1 is refused.
    with pytest.raises(ValueError, match="never truncated"):
        resolve(fund, as_of=D1, stale_nav="refuse")


def test_through_with_nothing_to_exclude_and_without_a_nav() -> None:
    fund = _fund((_c(D0, 100.0), _d(D1, 30.0)), None)
    cut, excluded = fund.through(D3)
    assert cut == fund and excluded == ()
    assert cut.nav is None


def test_through_refusals() -> None:
    fund = _fund((_c(D0, 100.0), _d(D2, 30.0)), NavObservation(date=D2, value=90.0))
    with pytest.raises(ValueError, match="after 2020-06-30"):
        fund.through(D1)  # the NAV at D2 cannot be the value at D1
    with pytest.raises(ValueError, match="no flow is dated on or before"):
        _fund((_c(D1, 1.0),), None).through(D0)
    with pytest.raises(ValueError, match="datetime.date"):
        fund.through(datetime(2021, 3, 31))  # type: ignore[arg-type]


def test_an_exact_zero_product_or_ratio_is_not_an_underflow() -> None:
    # W7's differential test: mPME multiplies weight 1 by a position of exactly 0 after a
    # zero interim NAV. A zero operand gives an exact zero; only a product of two non-zero
    # operands that falls below the smallest normal float is an underflow.
    assert finite_product(1.0, 0.0, what="p") == 0.0
    assert finite_product(0.0, 5.0, what="p") == 0.0
    assert finite_product(-3.0, 0.0, what="p") == 0.0
    assert finite_ratio(0.0, 7.0, what="r") == 0.0
    with pytest.raises(ValueError, match="p = .* underflows"):
        finite_product(1e-200, 1e-200, what="p")
    with pytest.raises(ValueError, match="r = .* underflows"):
        finite_ratio(1e-300, 1e300, what="r")


@pytest.mark.parametrize("stamp", [datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=UTC)])
def test_every_record_date_field_refuses_datetime(stamp: datetime) -> None:
    # R3-11, contract §13.6: records and results too, midnight and timezone-aware included.
    with pytest.raises(ValidationError, match="not a datetime"):
        NearZeroNet(date=stamp, raw_net=0.0, gross=0.0, bound=0.0)
    with pytest.raises(ValidationError, match="not a datetime"):
        NavRollForward(
            reported_date=stamp,
            reported_value=1.0,
            contributions_after=0.0,
            distributions_after=0.0,
            rolled_value=1.0,
        )
    resolved = resolve(
        _fund(FLOWS, NavObservation(date=D3, value=1.0)), as_of=D3, stale_nav="refuse"
    )
    for field, value in (("as_of", stamp), ("netted_to_zero", (stamp,))):
        with pytest.raises(ValidationError, match="not a datetime"):
            ResolvedCashFlows.model_validate({**resolved.model_dump(), field: value})


def test_resolved_flows_without_dust_carry_no_records() -> None:
    resolved = resolve(
        _fund(FLOWS, NavObservation(date=D3, value=1.0)), as_of=D3, stale_nav="refuse"
    )
    assert resolved.stated_nets_within_noise == ()
