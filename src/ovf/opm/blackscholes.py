"""The Black-Scholes-Merton value of a European call, with its limits taken exactly.

Black and Scholes (1973, *Journal of Political Economy* 81(3), 637-654) priced a European
call on a non-dividend-paying asset; Merton (1973, *Bell Journal of Economics and Management
Science* 4(1), 141-183) extended it to an asset paying a continuous proportional yield ``q``.
With ``F = S * exp((r - q) * T)`` the formula implemented, as published, is

    C = S * exp(-q*T) * N(d1) - K * exp(-r*T) * N(d2)
    d1 = (ln(S / K) + (r - q + sigma**2 / 2) * T) / (sigma * sqrt(T)),   d2 = d1 - sigma * sqrt(T)

The standard normal distribution function is evaluated through ``math.erfc`` as
``N(x) = erfc(-x / sqrt(2)) / 2``. For a negative argument that is a direct evaluation of a
small tail probability, which keeps its relative precision; computing ``1 - N(-x)`` instead
would cancel to zero long before the tail is actually zero. Deep out of the money calls, and
the upper tranches of a cap table, live in that tail.

The limits are returned from their closed forms, not approached numerically:

- ``strike == 0``: the call is the prepaid forward, ``S * exp(-q*T)``.
- ``spot == 0``: the call is worthless.
- ``time == 0``, ``volatility == 0``, or a ``volatility * sqrt(time)`` that underflows to
  zero from two positive factors: the discounted intrinsic value
  ``max(S * exp(-q*T) - K * exp(-r*T), 0)``, the value of a payoff known with certainty.

See docs/opm.md for the derivations and the checks against an independent oracle.
"""

from __future__ import annotations

import math

from ovf.opm.types import OpmError

__all__ = ["call_value", "normal_cdf"]

_SQRT2 = math.sqrt(2.0)


def normal_cdf(x: float) -> float:
    """The standard normal distribution function, ``erfc(-x / sqrt(2)) / 2``."""
    return 0.5 * math.erfc(-x / _SQRT2)


def _discount(amount: float, rate: float, time: float, name: str) -> float:
    """``amount * exp(-rate * time)``, refusing an overflow rather than returning infinity."""
    try:
        value = amount * math.exp(-rate * time)
    except OverflowError:
        value = math.inf
    if not math.isfinite(value):
        raise OpmError(
            f"{name} * exp(-{rate} * {time}) overflows a float; the inputs are outside the "
            "range where this formula can be evaluated"
        )
    return value


def call_value(
    spot: float,
    strike: float,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> float:
    """Black-Scholes-Merton value of a European call; see the module docstring.

    ``spot``, ``strike``, ``volatility`` and ``time`` must be finite and non-negative;
    ``risk_free_rate`` and ``dividend_yield`` must be finite and may be negative. The result
    is never negative, never NaN, and never below the discounted intrinsic value or above the
    prepaid forward except by float rounding of those bounds themselves.
    """
    for name, value in {
        "spot": spot,
        "strike": strike,
        "volatility": volatility,
        "time": time,
        "risk_free_rate": risk_free_rate,
        "dividend_yield": dividend_yield,
    }.items():
        if not math.isfinite(value):
            raise OpmError(f"{name} must be finite, got {value}")
    for name, value in {
        "spot": spot,
        "strike": strike,
        "volatility": volatility,
        "time": time,
    }.items():
        if value < 0.0:
            raise OpmError(f"{name} must not be negative, got {value}")

    prepaid_forward = _discount(spot, dividend_yield, time, "spot")
    if strike == 0.0:
        return prepaid_forward
    if spot == 0.0:
        return 0.0
    discounted_strike = _discount(strike, risk_free_rate, time, "strike")
    total_volatility = volatility * math.sqrt(time)
    if time == 0.0 or volatility == 0.0 or total_volatility == 0.0:
        # The third test is not redundant. `volatility * sqrt(time)` can underflow to zero
        # from two strictly positive factors - 1e-300 and sqrt(1e-60) do it - and `d1` would
        # then divide by zero. The payoff is certain in that limit exactly as it is when
        # either factor is zero outright, so it takes the same branch. Reported by the
        # validation worker; `OpmInputs` admits such a volatility because it only requires
        # one greater than zero, so this is reachable through `opm_allocate`.
        return max(prepaid_forward - discounted_strike, 0.0)

    # ln(S e^{-qT} / (K e^{-rT})) from logs, so an extreme ratio cannot under- or overflow.
    log_moneyness = math.log(spot) - math.log(strike) + (risk_free_rate - dividend_yield) * time
    d1 = log_moneyness / total_volatility + 0.5 * total_volatility
    d2 = d1 - total_volatility
    if log_moneyness >= 0.0:
        # In the money forward: take the small put and add the forward intrinsic value
        # (put-call parity), so the time value is not the difference of two numbers near S.
        put = discounted_strike * normal_cdf(-d2) - prepaid_forward * normal_cdf(-d1)
        return prepaid_forward - discounted_strike + max(put, 0.0)
    return max(prepaid_forward * normal_cdf(d1) - discounted_strike * normal_cdf(d2), 0.0)
