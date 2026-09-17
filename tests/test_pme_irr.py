"""Certified XIRR: hand-checked roots, proven counts, invariances and refusals.

Most series use dates exactly 365 days apart under ACT/365F, so ``t_i`` are integers and
``f`` is a polynomial in ``x = 1 / (1 + r)`` whose roots can be written down by hand.
Run with ``-W error``: nothing here may emit an overflow or underflow warning.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from ovf.pme.daycount import year_fraction
from ovf.pme.flows import (
    CashFlow,
    DatedAmount,
    FundCashFlows,
    NavObservation,
    canonical_hash,
    resolve,
)
from ovf.pme.irr import TOLERANCE, IrrResult, fund_irr, npv, npv_at_log_rate, xirr

Y2021 = date(2021, 1, 1)  # 2021, 2022 and 2023 have 365 days: yearly steps are t = 1


def _series(*pairs: tuple[date, float]) -> list[DatedAmount]:
    return [DatedAmount(date=d, amount=a) for d, a in pairs]


def _yearly(*amounts: float, start: date = Y2021) -> list[DatedAmount]:
    """Amounts exactly 365 days apart: t_i = i under ACT/365F."""
    return [
        DatedAmount(date=start + timedelta(days=365 * i), amount=a) for i, a in enumerate(amounts)
    ]


def _solve(amounts: list[DatedAmount], day_count: str = "ACT/365F") -> IrrResult:
    return xirr(amounts, day_count=day_count)  # type: ignore[arg-type]


def _rates(result: IrrResult) -> list[float]:
    return [r.rate for r in result.roots]


def _residual_limit(amounts: Sequence[DatedAmount], log_rate: float, day_count: str) -> float:
    """``tol * max(sum|a_i|, sum|a_i| (1 + r)^-t_i)``, t from the first date (contract §6)."""
    t0 = min(a.date for a in amounts)
    try:
        discounted = math.fsum(
            abs(a.amount) * math.exp(-log_rate * year_fraction(t0, a.date, convention=day_count))  # type: ignore[arg-type]
            for a in amounts
        )
    except OverflowError:
        return math.inf
    return TOLERANCE * max(math.fsum(abs(a.amount) for a in amounts), discounted)


def _npv_at_log_rate(amounts: Sequence[DatedAmount], log_rate: float, day_count: str) -> float:
    """``sum a_i exp(-delta t_i)`` from the first date, with math.fsum; inf on overflow."""
    t0 = min(a.date for a in amounts)
    try:
        return math.fsum(
            a.amount * math.exp(-log_rate * year_fraction(t0, a.date, convention=day_count))  # type: ignore[arg-type]
            for a in amounts
        )
    except OverflowError:
        return math.inf


def _check_consistent(result: IrrResult) -> None:
    """Invariants every result satisfies."""
    assert list(result.roots) == sorted(result.roots, key=lambda r: r.log_rate)
    assert (result.irr is not None) == (result.status == "unique")
    if result.status == "unique":
        assert result.irr == result.roots[0].rate
    if result.status in ("unique", "multiple", "none"):
        assert result.complete
        assert all(r.kind == "crossing" for r in result.roots)
        for r in result.roots:
            assert r.relative_residual <= TOLERANCE
            if r.npv_residual is not None:
                limit = _residual_limit(result.amounts, r.log_rate, result.day_count)
                assert abs(r.npv_residual) <= limit * (1 + 1e-9)
        # Descartes: at most V roots, of the parity of V.
        assert len(result.roots) <= result.sign_changes
        assert (result.sign_changes - len(result.roots)) % 2 == 0
    for root in result.roots:
        assert root.rate == pytest.approx(math.expm1(root.log_rate), rel=1e-15, abs=0)
        assert 0.0 <= root.relative_residual <= 1.0
        assert root.rate_clamped == (root.rate == -1.0)
    if result.log_root_bound is not None:
        lo, hi = result.log_root_bound
        assert all(lo <= r.log_rate <= hi for r in result.roots)
    assert result.tolerance == TOLERANCE
    assert len(result.input_hash) == 64


# --- Reference values -------------------------------------------------------------


def test_microsoft_xirr_example() -> None:
    # Microsoft's XIRR help page example; Excel returns 0.373362535 (37.34%). Excel stops
    # Newton "accurate within 0.000001 percent", so its 9th decimal is not the root's: the
    # exact root (50-digit Decimal bisection) is 0.37336253351883..., which rounds to
    # 0.373362534. Assert Excel's figure to Excel's tolerance and the root to 1e-12.
    result = _solve(
        _series(
            (date(2008, 1, 1), -10000.0),
            (date(2008, 3, 1), 2750.0),
            (date(2008, 10, 30), 4250.0),
            (date(2009, 2, 15), 3250.0),
            (date(2009, 4, 1), 2750.0),
        )
    )
    assert result.status == "unique"
    assert result.complete
    assert result.sign_changes == 1
    assert result.irr is not None
    assert abs(result.irr - 0.373362535) <= 1e-8 * 0.373362535
    assert result.irr == pytest.approx(0.3733625335188315103, abs=1e-12)
    assert result.t0 == date(2008, 1, 1)
    assert result.day_count == "ACT/365F"
    _check_consistent(result)


@pytest.mark.parametrize(
    ("contribution", "distribution", "days"),
    [(100.0, 150.0, 730), (250.0, 180.0, 1000), (1.0, 3.0, 365), (1e9, 2.5e9, 3653)],
)
def test_two_flows_closed_form(contribution: float, distribution: float, days: int) -> None:
    # -C at 0, +D at t: (1 + r)^t = D / C, so r = (D / C)^(1/t) - 1.
    result = _solve(_series((Y2021, -contribution), (Y2021 + timedelta(days), distribution)))
    t = days / 365
    assert result.status == "unique"
    assert result.irr == pytest.approx((distribution / contribution) ** (1 / t) - 1, rel=1e-12)
    _check_consistent(result)


def test_two_roots_exactly_ten_and_twenty_percent() -> None:
    # -100 + 230x - 132x^2 = -(1.1x - 1)(120x - 100)... roots x = 1/1.1 and 1/1.2:
    # 132x^2 - 230x + 100 = 0 -> x = (230 +- 10) / 264.
    result = _solve(_yearly(-100.0, 230.0, -132.0))
    assert result.status == "multiple"
    assert result.complete
    assert result.irr is None
    assert result.sign_changes == 2
    assert _rates(result) == pytest.approx([0.10, 0.20], abs=1e-12)
    assert all(r.kind == "crossing" for r in result.roots)
    assert "Rolle isolation" in result.proof
    _check_consistent(result)


def test_proven_no_root_with_two_sign_changes() -> None:
    # -100 + 100x - 100x^2 < 0 for every real x (discriminant 1 - 4 < 0).
    result = _solve(_yearly(-100.0, 100.0, -100.0))
    assert result.status == "none"
    assert result.complete
    assert result.roots == ()
    assert result.sign_changes == 2
    assert result.root_bound is not None
    _check_consistent(result)


def test_tangent_double_root_is_undetermined() -> None:
    # -100 + 200x - 100x^2 = -100 (x - 1)^2: a double root at x = 1, r = 0.
    result = _solve(_yearly(-100.0, 200.0, -100.0))
    assert result.status == "undetermined"
    assert not result.complete
    assert result.irr is None
    assert len(result.roots) == 1
    root = result.roots[0]
    assert root.kind == "tangent"
    assert root.rate == pytest.approx(0.0, abs=1e-9)
    assert root.npv_residual is not None
    assert abs(root.npv_residual) <= TOLERANCE * 400
    assert "tangent" in result.proof
    _check_consistent(result)


def test_three_sign_changes_one_root() -> None:
    # 110x^3 - 210x^2 + 210x - 100 = (1.1x - 1)(100x^2 - 100x + 100); the quadratic has
    # discriminant 1 - 4 < 0, so x = 1/1.1 (r = 10%) is the only real root though V = 3.
    result = _solve(_yearly(-100.0, 210.0, -210.0, 110.0))
    assert result.sign_changes == 3
    assert result.status == "unique"
    assert result.complete
    assert result.irr == pytest.approx(0.10, abs=1e-12)
    _check_consistent(result)


def test_six_known_roots() -> None:
    rates = [-0.3, -0.1, 0.05, 0.2, 0.5, 1.0]
    # prod (x - 1/(1+r_j)), coefficients by ascending power: alternating signs, V = 6.
    coeffs = np.poly([1 / (1 + r) for r in rates])[::-1]
    result = _solve(_yearly(*(float(c) for c in coeffs), start=date(2001, 1, 1)))
    assert result.sign_changes == 6
    assert result.status == "multiple"
    assert result.complete
    assert _rates(result) == pytest.approx(rates, abs=1e-9)
    _check_consistent(result)


# --- V = 0 and refusals -----------------------------------------------------------


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_same_sign_has_no_root(sign: float) -> None:
    result = _solve(_yearly(sign * 100.0, sign * 5.0, sign * 20.0))
    assert result.status == "none"
    assert result.complete
    assert result.sign_changes == 0
    assert result.roots == ()
    assert result.root_bound is None
    assert result.log_root_bound is None
    assert "V=0" in result.proof


def test_empty_and_single_date_refused() -> None:
    with pytest.raises(ValueError, match="at least two dates"):
        _solve([])
    with pytest.raises(ValueError, match="at least two dates"):
        _solve(_series((Y2021, -100.0)))
    # Two inputs on one date are one date.
    with pytest.raises(ValueError, match="at least two dates"):
        _solve(_series((Y2021, -100.0), (Y2021, 250.0)))
    # A date netting to zero leaves one date.
    with pytest.raises(ValueError, match="at least two dates"):
        _solve(_series((Y2021, -100.0), (date(2022, 1, 1), 5.0), (date(2022, 1, 1), -5.0)))


def test_bad_inputs_refused() -> None:
    with pytest.raises(ValueError, match="unknown day-count"):
        xirr(_yearly(-1.0, 2.0), day_count="30/360")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="DatedAmount"):
        xirr([(Y2021, -1.0), (date(2022, 1, 1), 2.0)], day_count="ACT/365F")  # type: ignore[list-item]
    with pytest.raises(ValueError, match="sequence"):
        xirr("abc", day_count="ACT/365F")  # type: ignore[arg-type]


def test_same_date_netting_and_zero_dates() -> None:
    split = _series(
        (Y2021, -60.0),
        (Y2021, -40.0),
        (date(2021, 6, 1), 7.0),
        (date(2021, 6, 1), -7.0),
        (date(2022, 1, 1), 150.0),
    )
    result = _solve(split)
    plain = _solve(_series((Y2021, -100.0), (date(2022, 1, 1), 150.0)))
    assert [(a.date, a.amount) for a in result.amounts] == [
        (Y2021, -100.0),
        (date(2022, 1, 1), 150.0),
    ]
    assert result.irr == plain.irr == pytest.approx(0.5, rel=1e-13)
    assert any("2021-06-01" in a for a in result.assumptions)


# --- Extreme rates ----------------------------------------------------------------


def test_huge_rate_in_one_day() -> None:
    # -1 then +2 one day later: (1 + r)^(1/365) = 2, r = 2^365 - 1 ~ 7.5e109.
    result = _solve(_series((Y2021, -1.0), (date(2021, 1, 2), 2.0)))
    assert result.status == "unique"
    assert result.irr == pytest.approx(2.0**365 - 1, rel=1e-12)
    assert result.roots[0].log_rate == pytest.approx(365 * math.log(2), rel=1e-14)
    _check_consistent(result)


def test_rate_beyond_float_range_refused() -> None:
    # -1 then +1e6 one day later: delta = 365 ln(1e6) = 5042.66 > ln(max float) = 709.78.
    with pytest.raises(ValueError, match="delta=5042.66"):
        _solve(_series((Y2021, -1.0), (date(2021, 1, 2), 1e6)))


def test_near_total_loss() -> None:
    # -100 then +1e-6 five years later (1827 days, two leap days): r = (1e-8)^(365/1827) - 1.
    end = date(2026, 1, 1)
    result = _solve(_series((Y2021, -100.0), (end, 1e-6)))
    t = (end - Y2021).days / 365
    assert result.status == "unique"
    assert result.irr == pytest.approx((1e-8) ** (1 / t) - 1, rel=1e-12)
    assert -1.0 < result.irr < -0.97
    _check_consistent(result)


def test_rate_at_float_resolution_of_minus_one() -> None:
    # -100 then +1e-300 one day later: delta = 365 ln(1e-302) ~ -253,800, 1 + r underflows.
    result = _solve(_series((Y2021, -100.0), (date(2021, 1, 2), 1e-300)))
    assert result.status == "unique"
    root = result.roots[0]
    assert root.rate == -1.0
    assert root.rate_clamped
    assert root.log_rate == pytest.approx(365 * math.log(1e-302), rel=1e-12)
    assert any("below float resolution" in a for a in result.assumptions)


def test_root_bound_overflow_keeps_log_bound() -> None:
    # A root near delta = 699 (rate ~ 1e303, representable) whose certified bound
    # delta* + ln 2 / g overflows as a rate: root_bound None, log_root_bound set.
    result = _solve(_series((Y2021, -1.0), (date(2021, 1, 2), math.exp(699 / 365))))
    assert result.status == "unique"
    assert result.roots[0].log_rate == pytest.approx(699.0, rel=1e-12)
    assert result.root_bound is None
    assert result.log_root_bound is not None
    assert result.log_root_bound[1] > 709.78
    assert any("root_bound is None" in a for a in result.assumptions)


@pytest.mark.parametrize(
    "series",
    [
        # Found by hypothesis: a dead fund. 16 paid in, 1 back; root delta ~ -13.4
        # (r ~ -0.999998) where compounded terms of ~1.7e6 cancel. An undiscounted
        # residual scale (17e-10) is below float rounding of those terms; the discounted
        # scale of contract §6 (amended) verifies it.
        _series(
            (date(2000, 1, 1), -1.0),
            (date(2000, 1, 2), -1.0),
            (date(2000, 11, 16), -14.0),
            (date(2001, 1, 27), 1.0),
        ),
        _series(
            (date(2000, 1, 1), -1.0),
            (date(2000, 1, 2), -1.0),
            (date(2005, 10, 17), -2.0),
            (date(2006, 2, 18), 1.0),
        ),
    ],
)
def test_near_total_loss_with_late_contributions(series: list[DatedAmount]) -> None:
    result = _solve(series)
    assert result.status == "unique"
    assert result.complete
    assert result.irr is not None and -1.0 < result.irr < -0.8
    _check_consistent(result)
    assert any("gross discounted magnitude" in a for a in result.assumptions)


def test_amount_ratio_beyond_float_range_is_solved() -> None:
    # |amounts| ratio 1e600: as a float quotient it underflows to 0; in log space it is
    # exact. Five 365-day years: (1 + r)^5 = 1e600, delta = 600 ln 10 / 5 ~ 276.3.
    series = _series((Y2021, -1e-300), (Y2021 + timedelta(days=5 * 365), 1e300))
    result = _solve(series)
    assert result.status == "unique"
    assert result.complete
    assert result.roots[0].log_rate == pytest.approx(120 * math.log(10), rel=1e-13)


# --- Precision: coefficients spanning the float range (reviewer R1) ---------------


def _decimal_discriminant(a0: float, a1: float, a2: float) -> Decimal:
    """Exact ``a1^2 - 4 a0 a2`` of the binary64 values (Decimal(float) is exact)."""
    with localcontext() as ctx:
        ctx.prec = 4000  # each exact float has <= 767 significant digits
        return Decimal(a1) * Decimal(a1) - 4 * Decimal(a0) * Decimal(a2)


def _decimal_log_roots(a0: float, a1: float, a2: float) -> list[Decimal]:
    """``delta = -ln x`` for the roots x of ``a0 + a1 x + a2 x^2``, ascending delta."""
    disc = _decimal_discriminant(a0, a1, a2)
    with localcontext() as ctx:
        ctx.prec = 60
        root = disc.sqrt()
        xs = [(-Decimal(a1) + sign * root) / (2 * Decimal(a2)) for sign in (1, -1)]
        return sorted(-x.ln() for x in xs)


def test_r1_span_no_real_root() -> None:
    # Reviewer R1: with x = 1/(1+r), 1e20 - 1.999999e-140 x + 1e-300 x^2 has discriminant
    # (1.999999e-140)^2 - 4e-280 < 0 for the exact binary64 inputs: no real root. The
    # former engine divided 1e-300 by 1e20 into the subnormal 1e-320 (a few significant
    # bits), flipped the discriminant and claimed two roots with complete=True.
    a0, a1, a2 = 1e20, -1.999999e-140, 1e-300
    assert _decimal_discriminant(a0, a1, a2) < 0
    result = _solve(_yearly(a0, a1, a2))
    assert result.sign_changes == 2
    assert result.status == "none"
    assert result.complete
    assert result.roots == ()
    _check_consistent(result)


def test_r1_span_mirrored_two_roots() -> None:
    # Same span, discriminant (2.000001e-140)^2 - 4e-280 > 0: two roots near
    # x = 1e160 (rate within float resolution of -1), 0.002 apart in log rate.
    a0, a1, a2 = 1e20, -2.000001e-140, 1e-300
    assert _decimal_discriminant(a0, a1, a2) > 0
    result = _solve(_yearly(a0, a1, a2))
    assert result.status == "multiple"
    assert result.complete
    assert [r.kind for r in result.roots] == ["crossing", "crossing"]
    expected = _decimal_log_roots(a0, a1, a2)
    assert [r.log_rate for r in result.roots] == pytest.approx(
        [float(d) for d in expected], rel=1e-12
    )
    _check_consistent(result)


_NEAR_TANGENT = [
    0.0,
    1e-15,
    -1e-15,
    1e-12,
    -1e-12,
    1e-9,
    -1e-9,
    1e-6,
    -1e-6,
    1e-3,
    -1e-3,
    0.5,
    -0.5,
]


@st.composite
def spanning_quadratics(draw: st.DrawFn) -> tuple[float, float, float]:
    """``a0 + a1 x + a2 x^2`` with ``V = 2`` and magnitudes in 1e-300..1e301."""

    def magnitude() -> float:
        mantissa = draw(st.floats(min_value=1.0, max_value=9.99))
        return mantissa * 10.0 ** draw(st.integers(min_value=-300, max_value=300))

    sign = draw(st.sampled_from([1.0, -1.0]))
    m0, m2 = magnitude(), magnitude()
    if draw(st.booleans()):
        # Near the tangent a1^2 = 4 a0 a2, where the discriminant's sign is delicate.
        eta = draw(st.sampled_from(_NEAR_TANGENT))
        m1 = 2.0 * math.sqrt(m0) * math.sqrt(m2) * (1.0 + eta)
    else:
        m1 = magnitude()
    return sign * m0, -sign * m1, sign * m2


@settings(max_examples=400, deadline=None)
@given(coeffs=spanning_quadratics())
def test_spanning_quadratics_never_claim_a_wrong_count(
    coeffs: tuple[float, float, float],
) -> None:
    """On yearly dates (ACT/365F, t = 0, 1, 2) f is the quadratic in x = 1/(1+r); the
    exact discriminant of the float coefficients (Fraction arithmetic) decides the real
    root count: 2 if positive, 0 if negative, a double root if zero. complete=True must
    never contradict it; a decisive discriminant must not be left undetermined."""
    a0, a1, a2 = coeffs
    disc = Fraction(a1) ** 2 - 4 * Fraction(a0) * Fraction(a2)
    try:
        result = _solve(_yearly(a0, a1, a2))
    except ValueError as exc:  # a root beyond the float range: a refusal, not a claim
        assert "float range" in str(exc)
        return
    assert result.sign_changes == 2
    crossings = [r for r in result.roots if r.kind == "crossing"]
    if result.complete:
        assert disc != 0, "a double root was claimed decided"
        assert len(crossings) == (2 if disc > 0 else 0)
        assert result.status in ("multiple" if disc > 0 else "none", "undetermined")
    else:
        assert result.status == "undetermined"
    # Decisive at the contract's tolerance: the engine partitions at the critical point x_c
    # of g = x^(-1/2) f (tau = 1/2), where 3 a2 x^2 + a1 x - a0 = 0, and calls it a tangent
    # when |f(x_c)| <= tol * max(sum|a_i|, sum|a_i| x_c^i). Clear that by 10x (in 100-digit
    # Decimal) and the engine must decide the count.
    with localcontext() as ctx:
        ctx.prec = 100
        d0, d1, d2 = Decimal(a0), Decimal(a1), Decimal(a2)
        radical = (d1 * d1 + 12 * d0 * d2).sqrt()
        x_c = (-d1 + (radical if d2 > 0 else -radical)) / (6 * d2)
        f_c = d0 + d1 * x_c + d2 * x_c * x_c
        limit = Decimal(TOLERANCE) * max(
            abs(d0) + abs(d1) + abs(d2), abs(d0) + abs(d1) * x_c + abs(d2) * x_c * x_c
        )
    assert x_c > 0
    if abs(f_c) > 10 * limit:
        assert result.complete, result.proof
        assert result.status == ("multiple" if disc > 0 else "none"), result.proof


def test_huge_and_tiny_amounts() -> None:
    result = _solve(_yearly(-1e300, 1.1e300))
    assert result.irr == pytest.approx(0.1, rel=1e-12)
    result = _solve(_yearly(-1e-300, 1.1e-300))
    assert result.irr == pytest.approx(0.1, rel=1e-12)


# --- npv --------------------------------------------------------------------------


def test_npv_hand_value_and_root() -> None:
    amounts = _yearly(-100.0, 230.0, -132.0)
    assert npv(amounts, rate=0.0, day_count="ACT/365F", t0=Y2021) == -2.0
    # At r = 10%: -100 + 230/1.1 - 132/1.21 = -100 + 209.0909... - 109.0909... = 0.
    assert npv(amounts, rate=0.1, day_count="ACT/365F", t0=Y2021) == pytest.approx(0.0, abs=1e-12)
    # Changing t0 multiplies by (1 + r)^(year_fraction(new t0, old t0)).
    moved = npv(amounts, rate=0.05, day_count="ACT/365F", t0=date(2022, 1, 1))
    base = npv(amounts, rate=0.05, day_count="ACT/365F", t0=Y2021)
    assert moved == pytest.approx(base * 1.05, rel=1e-13)
    assert npv([], rate=0.1, day_count="ACT/365F", t0=Y2021) == 0.0


@pytest.mark.parametrize("rate", [-1.0, -1.5, math.nan, math.inf, -math.inf])
def test_npv_refuses_bad_rate(rate: float) -> None:
    with pytest.raises(ValueError, match="rate"):
        npv(_yearly(-1.0, 2.0), rate=rate, day_count="ACT/365F", t0=Y2021)


def test_npv_nets_same_date_legs_before_discounting() -> None:
    # R1 finding 2: +1e16 and -1e16 + 2 on one date are +2 exactly; discounting each leg
    # separately loses the 2 (2.0 instead of 2 / 1.1).
    d = date(2022, 1, 1)
    legs = _series((d, 1e16), (d, -1e16 + 2))
    for rate in (0.1, 0.7, 2.0):
        expected = npv(_series((d, 2.0)), rate=rate, day_count="ACT/365F", t0=Y2021)
        assert npv(legs, rate=rate, day_count="ACT/365F", t0=Y2021) == expected
    assert expected == pytest.approx(2.0 / 3.0, rel=1e-15)


def test_npv_does_not_underflow_the_discount_factor() -> None:
    # R1 finding 3: 1e300 / (1 + r)^2 with ln(1 + r) = 500 is 5.0759588975494563e-135
    # (80-digit Decimal); exp(-1000) alone underflows to 0. The exponent -1000 carries
    # ~1e-13 of rounding from ln(1 + r), hence the tolerance.
    value = npv(
        _series((date(2023, 1, 1), 1e300)), rate=math.expm1(500), day_count="ACT/365F", t0=Y2021
    )
    assert value == pytest.approx(5.0759588975494563e-135, rel=1e-12)


def test_overflow_is_refused_with_value_error() -> None:
    # R1 finding 4: an overflowing same-date net, a huge integer rate.
    end = Y2021 + timedelta(days=365)
    with pytest.raises(ValueError, match="float range"):
        xirr(_series((Y2021, 1e308), (Y2021, 1e308), (end, -1e308)), day_count="ACT/365F")
    with pytest.raises(ValueError, match="float range"):
        npv(_series((Y2021, 1e308), (Y2021, 1e308)), rate=0.1, day_count="ACT/365F", t0=Y2021)
    with pytest.raises(ValueError, match=r"float range") as info:
        npv(_series((Y2021, 1.0)), rate=10**1000, day_count="ACT/365F", t0=Y2021)
    assert len(str(info.value)) < 200


def test_deep_alternating_series_solved_through_all_levels() -> None:
    # R1 observation: +1, -1, ... on 200 yearly dates is (1 - x^200) / (1 + x): the single
    # positive root x = 1 (r = 0) needs 199 derivative levels. Products of floats
    # underflowed there; log-space coefficients cannot, and the bound is always reported.
    series = _yearly(*(1.0 if i % 2 == 0 else -1.0 for i in range(200)))
    result = _solve(series)
    assert result.sign_changes == 199
    assert result.status == "unique"
    assert result.complete
    assert result.irr == pytest.approx(0.0, abs=1e-12)
    assert result.log_root_bound is not None
    _check_consistent(result)


def test_signed_zero_inputs_hash_alike() -> None:
    # R1 finding 7 (irr part): a dropped -0.0 amount must not change the input hash.
    base = _series((Y2021, -100.0), (date(2022, 1, 1), 110.0))
    plus = xirr([*base, DatedAmount(date=date(2021, 6, 1), amount=0.0)], day_count="ACT/365F")
    minus = xirr([*base, DatedAmount(date=date(2021, 6, 1), amount=-0.0)], day_count="ACT/365F")
    assert plus.input_hash == minus.input_hash
    assert plus == minus


def test_npv_refuses_overflow() -> None:
    with pytest.raises(ValueError, match="float range"):
        npv(_yearly(-1.0, 2.0), rate=1e300, day_count="ACT/365F", t0=date(2030, 1, 1))


# --- fund_irr ---------------------------------------------------------------------


def _fund(nav: NavObservation | None) -> FundCashFlows:
    return FundCashFlows(
        name="Fund I",
        currency="USD",
        basis="net_lp",
        flows=(
            CashFlow(date=date(2020, 1, 1), kind="contribution", amount=100.0),
            CashFlow(date=date(2021, 1, 1), kind="contribution", amount=50.0),
            CashFlow(date=date(2022, 6, 30), kind="distribution", amount=40.0),
            CashFlow(date=date(2023, 12, 31), kind="distribution", amount=20.0),
        ),
        nav=nav,
    )


def test_fund_irr_refuses_missing_residual() -> None:
    resolved = resolve(_fund(None), as_of=date(2023, 12, 31), stale_nav="refuse")
    with pytest.raises(ValueError, match="no residual value"):
        fund_irr(resolved, day_count="ACT/365F")
    with pytest.raises(ValueError, match="ResolvedCashFlows"):
        fund_irr(_fund(None), day_count="ACT/365F")  # type: ignore[arg-type]


def test_fund_irr_uses_net_by_date_with_residual() -> None:
    as_of = date(2023, 12, 31)
    resolved = resolve(
        _fund(NavObservation(date=as_of, value=130.0)), as_of=as_of, stale_nav="refuse"
    )
    result = fund_irr(resolved, day_count="ACT/ACT-ISDA")
    assert result.amounts == resolved.net_by_date
    # The as_of date carries the distribution plus the residual: 20 + 130.
    assert result.amounts[-1] == DatedAmount(date=as_of, amount=150.0)
    direct = xirr(
        _series(
            (date(2020, 1, 1), -100.0),
            (date(2021, 1, 1), -50.0),
            (date(2022, 6, 30), 40.0),
            (as_of, 150.0),
        ),
        day_count="ACT/ACT-ISDA",
    )
    assert result.status == direct.status == "unique"
    assert result.irr == direct.irr
    assert npv(
        result.amounts,
        rate=result.irr,
        day_count="ACT/ACT-ISDA",  # type: ignore[arg-type]
        t0=result.t0,
    ) == pytest.approx(0.0, abs=1e-8)
    # Resolution assumptions are carried; the day count is stated.
    text = "\n".join(result.assumptions)
    assert "Perspective: the investor (LP)" in text
    assert "ACT/ACT-ISDA" in text
    assert result.input_hash != resolved.input_hash


def test_fund_irr_rolled_forward_nav() -> None:
    as_of = date(2023, 12, 31)
    fund = _fund(NavObservation(date=date(2023, 6, 30), value=150.0))
    resolved = resolve(fund, as_of=as_of, stale_nav="roll_forward_cash_adjusted")
    # 150 - 20 distributed after the NAV date = 130 rolled; the as_of net is 20 + 130.
    assert resolved.residual_value == 130.0
    result = fund_irr(resolved, day_count="ACT/365F")
    assert result.amounts[-1] == DatedAmount(date=as_of, amount=150.0)


# --- Properties -------------------------------------------------------------------

AMOUNT = st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False)


@st.composite
def conventional_series(draw: st.DrawFn) -> list[DatedAmount]:
    """Contributions, then distributions: exactly one sign change (V = 1)."""
    n_c = draw(st.integers(min_value=1, max_value=6))
    n_d = draw(st.integers(min_value=1, max_value=6))
    offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=15 * 365),
            min_size=n_c + n_d,
            max_size=n_c + n_d,
            unique=True,
        )
    )
    offsets.sort()
    start = draw(st.dates(min_value=date(1950, 1, 1), max_value=date(2060, 1, 1)))
    amounts = [-draw(AMOUNT) for _ in range(n_c)] + [draw(AMOUNT) for _ in range(n_d)]
    # Keep the rate in a range where npv() at the root and nearby is representable.
    total_c = -sum(amounts[:n_c])
    total_d = sum(amounts[n_c:])
    assume(1e-3 < total_d / total_c < 1e3)
    assume(offsets[-1] - offsets[n_c - 1] >= 30)
    return [
        DatedAmount(date=start + timedelta(days=o), amount=a)
        for o, a in zip(offsets, amounts, strict=True)
    ]


@st.composite
def any_series(draw: st.DrawFn) -> list[DatedAmount]:
    n = draw(st.integers(min_value=2, max_value=8))
    offsets = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=20 * 365), min_size=n, max_size=n, unique=True
            )
        )
    )
    signs = draw(st.lists(st.sampled_from([-1.0, 1.0]), min_size=n, max_size=n))
    amounts = [s * draw(AMOUNT) for s in signs]
    return [
        DatedAmount(date=date(2000, 1, 1) + timedelta(days=o), amount=a)
        for o, a in zip(offsets, amounts, strict=True)
    ]


@settings(max_examples=150, deadline=None)
@given(
    series=conventional_series(),
    day_count=st.sampled_from(["ACT/365F", "ACT/365.25", "ACT/ACT-ISDA"]),
)
def test_conventional_series_unique_verified_root(
    series: list[DatedAmount], day_count: str
) -> None:
    try:
        result = _solve(series, day_count)
    except ValueError as exc:  # a root whose rate exceeds the float range: refused
        assert "float range" in str(exc)
        return
    assert result.sign_changes == 1
    assert result.status == "unique"
    assert result.complete
    _check_consistent(result)
    rate = result.irr
    assert rate is not None
    delta = result.roots[0].log_rate
    # Independent NPV at the log rate (1 + r loses precision near r = -1, where the
    # reported rate may even read -1.0); allow its own rounding on top of the tolerance.
    limit = _residual_limit(series, delta, day_count)
    assert abs(_npv_at_log_rate(series, delta, day_count)) <= 10 * limit
    # NPV changes sign around the root: it has the sign of the first amount above it.
    h = 1e-6 * max(1.0, abs(delta))
    assert _npv_at_log_rate(series, delta + h, day_count) < 0
    assert _npv_at_log_rate(series, delta - h, day_count) > 0
    if -0.9 < rate < 1e6:  # the public npv() agrees where 1 + r is well conditioned
        value = npv(series, rate=rate, day_count=day_count, t0=result.t0)  # type: ignore[arg-type]
        assert abs(value) <= 10 * limit


@settings(max_examples=150, deadline=None)
@given(series=conventional_series(), k=st.floats(min_value=1e-6, max_value=1e6))
def test_scaling_amounts_keeps_the_rate(series: list[DatedAmount], k: float) -> None:
    base = _solve(series)
    scaled = _solve([DatedAmount(date=a.date, amount=a.amount * k) for a in series])
    assert scaled.status == base.status == "unique"
    assert scaled.roots[0].log_rate == pytest.approx(base.roots[0].log_rate, rel=1e-9, abs=1e-12)


@settings(max_examples=150, deadline=None)
@given(
    series=any_series(),
    power=st.integers(min_value=-40, max_value=40),
    shift=st.integers(min_value=-5000, max_value=5000),
    seed=st.randoms(),
)
def test_exact_invariances_any_series(
    series: list[DatedAmount], power: int, shift: int, seed: object
) -> None:
    """Scaling by 2^p, shifting every date by N days (ACT/365F) and reordering are exact
    symmetries of the computed problem, so the whole result is identical - including a
    refusal of a root whose rate exceeds the float range."""
    k = 2.0**power
    moved = [DatedAmount(date=a.date + timedelta(days=shift), amount=a.amount * k) for a in series]
    seed.shuffle(moved)  # type: ignore[attr-defined]
    try:
        base = _solve(series)
    except ValueError as exc:
        assert "float range" in str(exc)
        with pytest.raises(ValueError, match="float range"):
            _solve(moved)
        return
    _check_consistent(base)
    other = _solve(moved)
    assert other.status == base.status
    assert other.complete == base.complete
    assert other.sign_changes == base.sign_changes
    assert [r.log_rate for r in other.roots] == [r.log_rate for r in base.roots]
    assert [r.kind for r in other.roots] == [r.kind for r in base.roots]
    assert other.log_root_bound == base.log_root_bound


@settings(max_examples=100, deadline=None)
@given(series=any_series())
def test_reordering_gives_identical_result(series: list[DatedAmount]) -> None:
    try:
        result = _solve(series)
    except ValueError as exc:
        assert "float range" in str(exc)
        with pytest.raises(ValueError, match="float range"):
            _solve(list(reversed(series)))
        return
    reversed_result = _solve(list(reversed(series)))
    assert reversed_result == result


@settings(max_examples=100, deadline=None)
@given(
    rates=st.lists(st.floats(min_value=-0.6, max_value=1.5), min_size=1, max_size=4, unique=True)
)
def test_polynomial_with_known_roots(rates: list[float]) -> None:
    """prod (x - 1/(1+r_j)) on yearly dates has exactly the roots r_j (when well separated)."""
    xs = sorted(1 / (1 + r) for r in rates)
    assume(all(b - a > 0.05 for a, b in zip(xs, xs[1:], strict=False)))
    coeffs = np.poly(xs)[::-1]
    result = _solve(_yearly(*(float(c) for c in coeffs), start=date(2001, 1, 1)))
    assert result.status == ("unique" if len(rates) == 1 else "multiple")
    assert result.complete
    assert _rates(result) == pytest.approx(sorted(rates), abs=1e-7)


# --- Performance ------------------------------------------------------------------


def test_thousand_flows_solve_fast() -> None:
    rng = np.random.default_rng(20260915)
    days = np.sort(rng.choice(20 * 365, size=1000, replace=False))
    amounts = [-float(a) for a in rng.uniform(1, 10, 500)] + [
        float(a) for a in rng.uniform(1, 20, 500)
    ]
    series = [
        DatedAmount(date=date(2001, 1, 1) + timedelta(days=int(d)), amount=a)
        for d, a in zip(days, amounts, strict=True)
    ]
    start = time.perf_counter()
    result = _solve(series)
    elapsed = time.perf_counter() - start
    assert result.status == "unique"
    assert result.sign_changes == 1
    _check_consistent(result)
    assert elapsed < 0.5


# --- Deeply negative roots are verified, never refused (contract §11.1, R2-1) -----

# The three series out/r2/dead_fund_search.py printed as refusals (seed 11, trials 0, 7,
# 12): calls, then a small distribution days later, NAV 0. V = 1, so the root is unique;
# its NPV at t0 compounds the later calls past 1e308, which the former engine refused.
_DEAD_FUNDS = [
    (
        [
            ("2015-02-20", "c", 8564951.8),
            ("2015-04-18", "c", 1980030.11),
            ("2015-10-08", "c", 8058613.1),
            ("2018-10-31", "c", 4810056.04),
            ("2019-09-06", "c", 6178192.46),
            ("2019-09-09", "d", 95029.33),
        ],
        "2019-11-25",
        -507.9091124357413,
    ),
    (
        [
            ("2009-04-02", "c", 1396574.13),
            ("2012-10-26", "c", 6472779.72),
            ("2015-04-27", "c", 1253429.08),
            ("2015-09-28", "c", 4265480.61),
            ("2015-10-02", "d", 1470.44),
        ],
        "2016-03-01",
        -727.5132974160656,
    ),
    (
        [
            ("2008-12-25", "c", 6074988.73),
            ("2011-02-18", "c", 4272426.52),
            ("2012-03-10", "c", 1128012.85),
            ("2014-06-25", "c", 483095.07),
            ("2016-09-02", "c", 9630546.96),
            ("2016-09-06", "d", 740088.83),
        ],
        "2016-12-15",
        -234.14066365518397,
    ),
]


def _dead_fund(flows: list[tuple[str, str, float]], as_of: str) -> FundCashFlows:
    kinds = {"c": "contribution", "d": "distribution"}
    return FundCashFlows(
        name="Dead",
        currency="USD",
        basis="net_lp",
        flows=tuple(
            CashFlow(date=date.fromisoformat(d), kind=kinds[k], amount=a)  # type: ignore[arg-type]
            for d, k, a in flows
        ),
        nav=NavObservation(date=date.fromisoformat(as_of), value=0.0),
    )


def _assert_clamped_root_checks_publicly(result: IrrResult) -> None:
    root = result.roots[0]
    last = result.amounts[-1].date
    value = npv_at_log_rate(
        result.amounts, log_rate=root.log_rate, day_count=result.day_count, t0=last
    )
    assert abs(value) <= 10 * TOLERANCE * math.fsum(abs(a.amount) for a in result.amounts)


@pytest.mark.parametrize(("flows", "as_of", "delta"), _DEAD_FUNDS)
def test_dead_fund_root_is_verified_not_refused(
    flows: list[tuple[str, str, float]], as_of: str, delta: float
) -> None:
    resolved = resolve(
        _dead_fund(flows, as_of), as_of=date.fromisoformat(as_of), stale_nav="refuse"
    )
    result = fund_irr(resolved, day_count="ACT/365F")
    assert result.status == "unique"
    assert result.complete
    root = result.roots[0]
    assert root.rate == -1.0 and root.rate_clamped
    assert root.log_rate == pytest.approx(delta, rel=1e-9)
    assert root.relative_residual <= TOLERANCE
    assert root.npv_residual is None  # compounded past 1e308 at t0
    _check_consistent(result)
    _assert_clamped_root_checks_publicly(result)


def test_dust_trial_3313_is_unique() -> None:
    # out/r2/dust_refusal.py trial 3313: a 2.3e-10 dust amount on its own date. An
    # 80-digit Decimal evaluation puts the root between delta = -178.52 and -177.52.
    series = _series(
        (date(2010, 1, 1), -7375260.778526237),
        (date(2011, 1, 12), -5812495.7677155705),
        (date(2012, 8, 18), -6212121.443247944),
        (date(2014, 5, 21), 2.3283064365386963e-10),
        (date(2014, 5, 26), -6453394.332172901),
        (date(2014, 5, 27), 3957098.355927818),
    )
    result = _solve(series)
    assert result.status == "unique"
    assert result.complete
    root = result.roots[0]
    assert root.rate_clamped
    assert -178.52 < root.log_rate < -177.52
    assert root.log_rate == pytest.approx(-178.51975791155365, rel=1e-9)
    assert root.relative_residual <= TOLERANCE
    _check_consistent(result)
    _assert_clamped_root_checks_publicly(result)


@st.composite
def dead_funds(draw: st.DrawFn) -> tuple[FundCashFlows, date]:
    """1-5 calls, a small distribution 1-10 days after the last, NAV 0 (R2's generator)."""
    start = draw(st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 1, 1)))
    n = draw(st.integers(min_value=1, max_value=5))
    offsets = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=10 * 365), min_size=n, max_size=n, unique=True
            )
        )
    )
    calls = [round(draw(st.floats(min_value=1e5, max_value=1e7)), 2) for _ in range(n)]
    distribution = round(draw(st.floats(min_value=1e3, max_value=1e6)), 2)
    assume(distribution < math.fsum(calls))  # a loss: the root is at a negative rate
    dist_day = start + timedelta(days=offsets[-1] + draw(st.integers(1, 10)))
    as_of = dist_day + timedelta(days=draw(st.integers(0, 200)))
    flows = tuple(
        CashFlow(date=start + timedelta(days=o), kind="contribution", amount=a)
        for o, a in zip(offsets, calls, strict=True)
    ) + (CashFlow(date=dist_day, kind="distribution", amount=distribution),)
    fund = FundCashFlows(
        name="Dead",
        currency="USD",
        basis="net_lp",
        flows=flows,
        nav=NavObservation(date=as_of, value=0.0),
    )
    return fund, as_of


@settings(max_examples=200, deadline=None)
@given(case=dead_funds())
def test_dead_funds_are_never_refused(case: tuple[FundCashFlows, date]) -> None:
    fund, as_of = case
    result = fund_irr(resolve(fund, as_of=as_of, stale_nav="refuse"), day_count="ACT/365F")
    assert result.sign_changes == 1
    assert result.status == "unique"
    assert result.complete
    root = result.roots[0]
    assert root.relative_residual <= TOLERANCE
    assert root.rate < 0.0
    _check_consistent(result)
    _assert_clamped_root_checks_publicly(result)


# --- npv_at_log_rate (R2-10) -------------------------------------------------------


def test_npv_at_log_rate_agrees_with_npv() -> None:
    amounts = _yearly(-100.0, 230.0, -132.0)
    for rate in (-0.5, 0.0, 0.1, 3.0):
        assert npv_at_log_rate(
            amounts, log_rate=math.log1p(rate), day_count="ACT/365F", t0=Y2021
        ) == pytest.approx(
            npv(amounts, rate=rate, day_count="ACT/365F", t0=Y2021), rel=1e-14, abs=1e-12
        )
    # Same-date legs are netted first, as in npv.
    d = date(2022, 1, 1)
    assert npv_at_log_rate(
        _series((d, 1e16), (d, -1e16 + 2)), log_rate=math.log1p(0.1), day_count="ACT/365F", t0=Y2021
    ) == pytest.approx(2 / 1.1, rel=1e-15)
    assert npv_at_log_rate([], log_rate=0.3, day_count="ACT/365F", t0=Y2021) == 0.0


def test_npv_at_log_rate_log_space_and_refusals() -> None:
    # 1e-300 * exp(1000) = exp(ln(1e-300) + 1000) ~ 1.97e134: exp(1000) alone overflows.
    value = npv_at_log_rate(
        _series((date(2022, 1, 1), 1e-300)), log_rate=-1000.0, day_count="ACT/365F", t0=Y2021
    )
    assert value == pytest.approx(math.exp(math.log(1e-300) + 1000.0), rel=1e-12)
    with pytest.raises(ValueError, match="float range"):
        npv_at_log_rate(_yearly(-1.0, 2.0), log_rate=-1000.0, day_count="ACT/365F", t0=Y2021)
    for bad in (math.nan, math.inf, "0.1", True):
        with pytest.raises(ValueError, match="log_rate"):
            npv_at_log_rate(
                _yearly(-1.0, 2.0),
                log_rate=bad,  # type: ignore[arg-type]
                day_count="ACT/365F",
                t0=Y2021,
            )
    with pytest.raises(ValueError, match="npv_at_log_rate"):
        npv(_yearly(-1.0, 2.0), rate=-1.0, day_count="ACT/365F", t0=Y2021)


# --- Wording and hashes (R2-11, R2-13) --------------------------------------------


def test_single_date_write_off_says_why() -> None:
    fund = FundCashFlows(
        name="Gone",
        currency="USD",
        basis="net_lp",
        flows=(CashFlow(date=Y2021, kind="contribution", amount=100.0),),
        nav=NavObservation(date=Y2021, value=0.0),
    )
    resolved = resolve(fund, as_of=Y2021, stale_nav="refuse")
    with pytest.raises(ValueError, match="written off with all flows on one date has no IRR"):
        fund_irr(resolved, day_count="ACT/365F")


def test_total_loss_proof_names_the_display_convention() -> None:
    result = _solve(_yearly(-100.0, -50.0))
    assert result.status == "none"
    assert "display convention, not a root" in result.proof
    assert "display convention" not in _solve(_yearly(100.0, 50.0)).proof


def test_hash_payloads_carry_the_method() -> None:
    series = _series((Y2021, -100.0), (date(2022, 1, 1), 110.0))
    result = xirr(series, day_count="ACT/365F")
    assert result.input_hash == canonical_hash(
        {
            "method": "xirr",
            "amounts": sorted((a.date.isoformat(), a.amount) for a in series),
            "day_count": "ACT/365F",
        }
    )
    fund = FundCashFlows(
        name="F",
        currency="USD",
        basis="net_lp",
        flows=(CashFlow(date=Y2021, kind="contribution", amount=100.0),),
        nav=NavObservation(date=date(2022, 1, 1), value=110.0),
    )
    resolved = resolve(fund, as_of=date(2022, 1, 1), stale_nav="refuse")
    assert fund_irr(resolved, day_count="ACT/365F").input_hash == canonical_hash(
        {
            "method": "fund_irr",
            "resolved_input_hash": resolved.input_hash,
            "day_count": "ACT/365F",
        }
    )
