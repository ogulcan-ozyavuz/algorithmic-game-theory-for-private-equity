"""Black-Scholes-Merton call values: an independent oracle, the exact limits, the properties.

The oracle is the same published formula evaluated with ``scipy.stats.norm.cdf`` in place of
``math.erfc``. Two independently written routes agreeing is the evidence; neither is
trusted alone. Derivations are in docs/opm.md.
"""

from __future__ import annotations

import itertools
import math
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.stats import norm

from ovf.opm.blackscholes import call_value, normal_cdf
from ovf.opm.types import OpmError


def _d(spot, strike, volatility, time, rate, dividend_yield):
    root = volatility * math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + volatility**2 / 2) * time) / root
    return d1, d1 - root


def scipy_call(spot, strike, volatility, time, rate, dividend_yield=0.0):
    d1, d2 = _d(spot, strike, volatility, time, rate, dividend_yield)
    return spot * math.exp(-dividend_yield * time) * norm.cdf(d1) - strike * math.exp(
        -rate * time
    ) * norm.cdf(d2)


def scipy_put(spot, strike, volatility, time, rate, dividend_yield=0.0):
    d1, d2 = _d(spot, strike, volatility, time, rate, dividend_yield)
    return strike * math.exp(-rate * time) * norm.cdf(-d2) - spot * math.exp(
        -dividend_yield * time
    ) * norm.cdf(-d1)


def noise(spot, strike):
    """Allowance for float rounding in one call value: 1e-13 of the larger of S and K.

    One evaluation rounds at about 2e-16 of that scale, so this is several hundred ulps.
    """
    return 1e-13 * max(spot, strike)


# --- the normal distribution function -------------------------------------------------


@pytest.mark.parametrize(
    "x", [-37.0, -30.0, -20.0, -10.0, -5.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 5.0, 8.0]
)
def test_normal_cdf_agrees_with_scipy_including_the_far_tail(x):
    assert math.isclose(normal_cdf(x), float(norm.cdf(x)), rel_tol=1e-12)


def test_erfc_keeps_the_tail_that_one_minus_n_loses():
    """The design reason for erfc: 1 - N(30) cancels to zero, N(-30) by erfc does not."""
    assert 1.0 - normal_cdf(30.0) == 0.0
    assert normal_cdf(-30.0) > 0.0
    assert math.isclose(normal_cdf(-30.0), float(norm.sf(30.0)), rel_tol=1e-12)


def test_normal_cdf_is_symmetric():
    for x in (0.1, 0.7, 1.3, 2.9, 4.4):
        assert normal_cdf(x) + normal_cdf(-x) == pytest.approx(1.0, abs=1e-15)


# --- agreement with the oracle ---------------------------------------------------------

SPOTS = (1e3, 2e7, 5e8)
MONEYNESS = (0.01, 0.5, 1.0, 2.0, 50.0)
VOLATILITIES = (0.05, 0.3, 0.9, 2.5)
TIMES = (0.1, 1.0, 5.0)
RATES = (-0.01, 0.0, 0.05)
YIELDS = (0.0, 0.03)


def test_call_agrees_with_the_scipy_oracle_across_a_grid():
    """1,080 cases, negative rates included, within 1e-13 of max(S, K)."""
    worst = 0.0
    for spot, m, vol, time, rate, q in itertools.product(
        SPOTS, MONEYNESS, VOLATILITIES, TIMES, RATES, YIELDS
    ):
        strike = spot * m
        gap = abs(
            call_value(spot, strike, vol, time, rate, q)
            - scipy_call(spot, strike, vol, time, rate, q)
        )
        worst = max(worst, gap / max(spot, strike))
    assert worst <= 1e-13


@pytest.mark.parametrize(
    ("strike", "vol"),
    [(3e7, 0.1), (5e7, 0.1), (1e8, 0.1), (5e7, 0.2), (1e8, 0.3), (1e9, 0.2), (1e10, 0.3)],
)
def test_deep_out_of_the_money_values_keep_relative_precision(strike, vol):
    """Values from 2e-8 down to 3e-110 still agree with the oracle to 1e-9 relative."""
    ours = call_value(1e7, strike, vol, 1.0, 0.03)
    oracle = scipy_call(1e7, strike, vol, 1.0, 0.03)
    assert ours > 0.0
    assert ours == pytest.approx(oracle, rel=1e-9)


def test_deep_in_the_money_is_forward_intrinsic_plus_the_put():
    spot, strike, vol, time, rate, q = 1e7, 1e3, 0.3, 1.0, 0.03, 0.01
    intrinsic = spot * math.exp(-q * time) - strike * math.exp(-rate * time)
    value = call_value(spot, strike, vol, time, rate, q)
    assert value >= intrinsic
    assert value - intrinsic == pytest.approx(scipy_put(spot, strike, vol, time, rate, q), abs=1e-6)


# --- the exact limits ------------------------------------------------------------------


@pytest.mark.parametrize("q", [0.0, 0.03, -0.01])
def test_zero_strike_is_the_prepaid_forward_exactly(q):
    for vol, time in ((0.6, 3.0), (1e-9, 0.5), (4.0, 10.0)):
        assert call_value(2e7, 0.0, vol, time, 0.04, q) == 2e7 * math.exp(-q * time)


@pytest.mark.parametrize("strike", [5e6, 2e7, 2.5e7, 9e7])
def test_zero_time_is_intrinsic_exactly(strike):
    assert call_value(2e7, strike, 0.6, 0.0, 0.04, 0.02) == max(2e7 - strike, 0.0)


@pytest.mark.parametrize("strike", [5e6, 2e7, 2.5e7, 9e7])
def test_zero_volatility_is_discounted_intrinsic_exactly(strike):
    forward = 2e7 * math.exp(-0.02 * 3.0)
    discounted = strike * math.exp(-0.04 * 3.0)
    assert call_value(2e7, strike, 0.0, 3.0, 0.04, 0.02) == max(forward - discounted, 0.0)


def test_zero_spot_is_worthless():
    assert call_value(0.0, 5e6, 0.6, 3.0, 0.04) == 0.0
    assert call_value(0.0, 0.0, 0.6, 3.0, 0.04) == 0.0


@pytest.mark.parametrize("strike", [1e100, 1e200, 1e300, sys.float_info.max])
@pytest.mark.parametrize("vol", [0.3, 2.0])
@pytest.mark.parametrize("rate", [0.0, 0.05])
def test_a_very_large_strike_is_zero_not_nan_or_negative(strike, vol, rate):
    assert call_value(2e7, strike, vol, 3.0, rate) == 0.0


def test_strike_sweep_to_the_float_limit_stays_finite_non_negative_and_falling():
    strikes = [10.0**k for k in range(0, 309)] + [sys.float_info.max]
    values = [call_value(2e7, k, 1.5, 5.0, 0.04) for k in strikes]
    assert all(math.isfinite(v) and v >= 0.0 for v in values)
    assert all(a >= b for a, b in itertools.pairwise(values))
    assert values[-1] == 0.0


def test_volatility_to_zero_converges_to_intrinsic():
    """Away from the forward the time value vanishes; at the forward it falls linearly.

    At K = F = S exp((r - q)T) the call is S exp(-qT) (2 N(sigma sqrt(T) / 2) - 1), which is
    S exp(-qT) sqrt(T / (2 pi)) sigma to first order.
    """
    spot, time, rate, q = 2e7, 3.0, 0.04, 0.01
    for strike in (5e6, 1.5e7, 3e7, 9e7):
        intrinsic = max(spot * math.exp(-q * time) - strike * math.exp(-rate * time), 0.0)
        gaps = [
            abs(call_value(spot, strike, v, time, rate, q) - intrinsic) for v in (1e-1, 1e-2, 1e-3)
        ]
        assert gaps[0] >= gaps[1] >= gaps[2]
        assert gaps[2] <= 1e-9 * spot

    forward = spot * math.exp((rate - q) * time)
    slope = spot * math.exp(-q * time) * math.sqrt(time / (2 * math.pi))
    for vol in (1e-3, 1e-4, 1e-5, 1e-6):
        value = call_value(spot, forward, vol, time, rate, q)
        exact = spot * math.exp(-q * time) * (2 * norm.cdf(vol * math.sqrt(time) / 2) - 1)
        assert value == pytest.approx(exact, rel=1e-6)
        assert value / vol == pytest.approx(slope, rel=1e-6)


def test_time_to_zero_converges_to_intrinsic():
    """The time value vanishes against the discounted intrinsic value at each T, and that
    in turn reaches the undiscounted max(S - K, 0) only at rate K(1 - exp(-rT)), i.e. O(T)."""
    spot, rate = 2e7, 0.04
    for strike in (5e6, 1.5e7, 3e7):
        gaps = []
        for t in (1e-2, 1e-4, 1e-6):
            discounted = max(spot - strike * math.exp(-rate * t), 0.0)
            gaps.append(abs(call_value(spot, strike, 0.6, t, rate) - discounted))
        assert gaps[0] >= gaps[1] >= gaps[2]
        assert gaps[2] <= 1e-9 * spot
        undiscounted = abs(call_value(spot, strike, 0.6, 1e-6, rate) - max(spot - strike, 0.0))
        assert undiscounted <= strike * (1 - math.exp(-rate * 1e-6)) + 1e-9 * spot


# --- properties ------------------------------------------------------------------------

spots = st.floats(min_value=1e3, max_value=1e9)
moneyness = st.floats(min_value=1e-3, max_value=1e3)
vols = st.floats(min_value=0.01, max_value=3.0)
times = st.floats(min_value=0.01, max_value=10.0)
rates = st.floats(min_value=-0.05, max_value=0.10)
yields = st.floats(min_value=-0.02, max_value=0.10)
PROPERTY = settings(max_examples=300, deadline=None)


@PROPERTY
@given(spots, moneyness, moneyness, vols, times, rates, yields)
def test_non_increasing_in_strike(spot, m1, m2, vol, time, rate, q):
    low, high = sorted((spot * m1, spot * m2))
    assert call_value(spot, low, vol, time, rate, q) >= call_value(
        spot, high, vol, time, rate, q
    ) - noise(spot, high)


@PROPERTY
@given(spots, moneyness, st.floats(min_value=1e-3, max_value=0.9), vols, times, rates, yields)
def test_convex_in_strike(spot, m, fraction, vol, time, rate, q):
    strike = spot * m
    step = strike * fraction

    def c(k):
        return call_value(spot, k, vol, time, rate, q)

    assert c(strike - step) - 2 * c(strike) + c(strike + step) >= -4 * noise(spot, strike + step)


@PROPERTY
@given(spots, moneyness, vols, vols, times, rates, yields)
def test_non_decreasing_in_volatility(spot, m, v1, v2, time, rate, q):
    low, high = sorted((v1, v2))
    strike = spot * m
    assert call_value(spot, strike, high, time, rate, q) >= call_value(
        spot, strike, low, time, rate, q
    ) - noise(spot, strike)


@PROPERTY
@given(spots, moneyness, vols, times, times, st.floats(min_value=0.0, max_value=0.10))
def test_non_decreasing_in_time_without_yield_and_with_non_negative_rate(
    spot, m, vol, t1, t2, rate
):
    """Holds for q = 0 and r >= 0 only; with a yield or a negative rate a European call can
    lose value with time, so the property is not asserted there."""
    low, high = sorted((t1, t2))
    strike = spot * m
    assert call_value(spot, strike, vol, high, rate) >= call_value(
        spot, strike, vol, low, rate
    ) - noise(spot, strike)


@PROPERTY
@given(spots, moneyness, vols, times, rates, yields)
def test_no_arbitrage_bounds(spot, m, vol, time, rate, q):
    strike = spot * m
    forward = spot * math.exp(-q * time)
    value = call_value(spot, strike, vol, time, rate, q)
    assert max(forward - strike * math.exp(-rate * time), 0.0) - noise(spot, strike) <= value
    assert value <= forward + noise(spot, strike)


@PROPERTY
@given(spots, moneyness, vols, times, rates, yields)
def test_put_call_parity_against_the_scipy_put(spot, m, vol, time, rate, q):
    strike = spot * m
    lhs = call_value(spot, strike, vol, time, rate, q) - scipy_put(spot, strike, vol, time, rate, q)
    rhs = spot * math.exp(-q * time) - strike * math.exp(-rate * time)
    assert lhs == pytest.approx(rhs, abs=4 * noise(spot, strike))


@PROPERTY
@given(spots, moneyness, vols, times, rates, yields)
def test_put_call_parity_through_put_call_symmetry(spot, m, vol, time, rate, q):
    """P(S, K, r, q) = C(K, S, q, r), so parity is checked with call_value alone.

    One side of each pair is in the money and the other out, so this crosses the two branches
    the implementation takes.
    """
    strike = spot * m
    call = call_value(spot, strike, vol, time, rate, q)
    put = call_value(strike, spot, vol, time, q, rate)
    rhs = spot * math.exp(-q * time) - strike * math.exp(-rate * time)
    assert call - put == pytest.approx(rhs, abs=4 * noise(spot, strike))


# --- refusals --------------------------------------------------------------------------

BASE = {"spot": 2e7, "strike": 5e6, "volatility": 0.6, "time": 3.0, "risk_free_rate": 0.04}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spot", -1.0),
        ("strike", -1.0),
        ("volatility", -0.1),
        ("time", -0.5),
        ("spot", math.nan),
        ("strike", math.inf),
        ("volatility", math.nan),
        ("time", math.inf),
        ("risk_free_rate", math.nan),
        ("dividend_yield", -math.inf),
    ],
)
def test_invalid_inputs_are_refused_by_name(field, value):
    with pytest.raises(OpmError, match=field):
        call_value(**{**BASE, field: value})


def test_an_overflowing_discount_is_refused_rather_than_infinite():
    with pytest.raises(OpmError, match="overflows"):
        call_value(1e300, 5e6, 0.6, 10.0, 0.04, dividend_yield=-100.0)
