"""Marketability discounts (`ovf.opm.dlom`): fixtures, limits and a Monte Carlo check.

Every fixed number asserted here is derived by hand in `docs/dlom.md` (DL1-DL6) and was
recomputed independently at 60 significant digits with `decimal`. `_reference` below is
that recomputation. It shares no code with `ovf.opm.dlom`: it evaluates each closed form
directly, with its own series for erf.

`simulate_payoffs` is the Monte Carlo oracle. It also shares no code with the module. It
simulates geometric Brownian motion under the pricing measure and prices each formula's
payoff literally: a European put struck at the initial price for Chaffe, a put struck at
the arithmetic average for Finnerty and Ghaidarov, and the hindsight maximum against the
terminal price for Longstaff. The maximum is sampled exactly between time steps from the
Brownian-bridge law, so the lookback has no discretisation bias. Every tolerance is
``Z_TOLERANCE`` standard errors of the simulation that produced it.

The pytest runs use small seeded simulations. The large runs recorded in `docs/dlom.md`
are replayed with

    python -m tests.test_opm_dlom            # the recorded Monte Carlo table
    python -m tests.test_opm_dlom --grid     # the closed-form comparison grid
    python -m tests.test_opm_dlom --seeds    # 100 independent seeds at one point
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from decimal import Decimal, localcontext

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import norm

import ovf.opm.dlom as dlom_module
from ovf.opm.dlom import (
    DLOM_METHODS,
    chaffe_dlom,
    dlom_comparison,
    finnerty_dlom,
    ghaidarov_dlom,
    longstaff_dlom,
)
from ovf.opm.types import DlomEstimate, OpmError

ESTIMATORS = {
    "chaffe": chaffe_dlom,
    "finnerty": finnerty_dlom,
    "longstaff": longstaff_dlom,
    "ghaidarov": ghaidarov_dlom,
}

# Four standard errors: under normality a correct closed form fails one comparison with
# two-sided probability 6.3e-5. The simulations are seeded, so a run is reproducible; the
# tolerance is what makes a pass mean something.
Z_TOLERANCE = 4.0
TEST_SEED = 20260915
TEST_PATHS = 100_000
TEST_STEPS_PER_YEAR = 50


# --------------------------------------------------------------------------------------
# Independent high-precision reference
# --------------------------------------------------------------------------------------

_PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494")


def _erf(x: Decimal) -> Decimal:
    """Maclaurin series; adequate at 60 digits for |x| below about 3."""
    total, term, n = Decimal(0), x, 0
    while True:
        add = term / (2 * n + 1)
        total += add
        if abs(add) < Decimal("1e-58"):
            return 2 / _PI.sqrt() * total
        n += 1
        term = -term * x * x / n


def _ncdf(x: Decimal) -> Decimal:
    return (1 + _erf(x / Decimal(2).sqrt())) / 2


def _reference(method: str, volatility: str, time: str, rate: str, yield_: str) -> float:
    """Each closed form evaluated at 60 digits straight from its stated algebra."""
    with localcontext() as ctx:
        ctx.prec = 60
        sig, t, r, q = Decimal(volatility), Decimal(time), Decimal(rate), Decimal(yield_)
        s = sig * sig * t
        if method == "chaffe":
            d1 = ((r - q) * t + s / 2) / s.sqrt()
            d2 = d1 - s.sqrt()
            value = (-r * t).exp() * _ncdf(-d2) - (-q * t).exp() * _ncdf(-d1)
        elif method in ("finnerty", "ghaidarov"):
            es = s.exp()
            if method == "finnerty":
                v2 = s + (2 * (es - s - 1)).ln() - 2 * (es - 1).ln()
            else:
                v2 = (2 * (es - s - 1)).ln() - 2 * s.ln()
            v = v2.sqrt()
            value = (-q * t).exp() * (_ncdf(v / 2) - _ncdf(-v / 2))
        elif method == "longstaff":
            value = (2 + s / 2) * _ncdf(s.sqrt() / 2) + (s / (2 * _PI)).sqrt() * (-s / 8).exp() - 1
        else:
            raise AssertionError(method)
        return float(value)


# --------------------------------------------------------------------------------------
# Monte Carlo oracle
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class McEstimate:
    mean: float
    stderr: float
    paths: int

    def within(self, value: float, z: float = Z_TOLERANCE) -> bool:
        return abs(value - self.mean) <= z * self.stderr


def simulate_payoffs(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float,
    paths: int,
    steps: int,
    seed: int,
    batch: int = 250_000,
) -> dict[str, McEstimate]:
    """Price each formula's payoff by simulation, as a fraction of the initial value 1.

    The price follows ``dS = (r - q) S dt + sigma S dW``. Payoffs, all discounted at r:

    - ``european_put``: ``(1 - S_T)^+``.
    - ``average_strike_put``: ``(A - S_T)^+``, ``A`` the trapezoid average over the
      ``steps + 1`` dates of ``S_t exp((r - q)(T - t))``, each price carried to ``T``.
    - ``average_price_put``: ``(F - A)^+`` with ``F = exp((r - q) T)``. At zero net carry
      this equals the average-strike put in value by the Asian put-call symmetry, and
      ``symmetry_gap`` is the paired difference of the two.
    - ``lookback``: ``max_t S_t exp(r (T - t)) - S_T``, the maximum sampled exactly
      between dates from the Brownian-bridge law.
    - ``discounted_terminal``: ``S_T`` itself, whose true value is ``exp(-qT)``. It is not
      a DLOM payoff. It measures how far this particular sample of paths sits from the
      martingale it should be, which is the common cause of same-signed errors when
      several payoffs are read off the same paths.
    """
    rng = np.random.default_rng(seed)
    dt = time / steps
    drift = (risk_free_rate - dividend_yield - 0.5 * volatility**2) * dt
    shock = volatility * math.sqrt(dt)
    bridge_variance = volatility**2 * dt
    carry = risk_free_rate - dividend_yield
    discount = math.exp(-risk_free_rate * time)
    forward = math.exp(carry * time)
    names = (
        "european_put",
        "average_strike_put",
        "average_price_put",
        "symmetry_gap",
        "lookback",
        "discounted_terminal",
    )
    sums = dict.fromkeys(names, 0.0)
    squares = dict.fromkeys(names, 0.0)
    done = 0
    while done < paths:
        n = min(batch, paths - done)
        log_s = np.zeros(n)
        # y_t = ln S_t - r t: the log of the discounted price, whose maximum is the lookback.
        running_max = np.zeros(n)
        carried = np.full(n, 0.5 * forward)
        for k in range(1, steps + 1):
            step = log_s + drift + shock * rng.standard_normal(n)
            uniform = 1.0 - rng.random(n)  # in (0, 1], so its log is finite
            y0 = log_s - risk_free_rate * (k - 1) * dt
            y1 = step - risk_free_rate * k * dt
            bridge_max = 0.5 * (
                y0 + y1 + np.sqrt((y1 - y0) ** 2 - 2.0 * bridge_variance * np.log(uniform))
            )
            np.maximum(running_max, bridge_max, out=running_max)
            weight = 0.5 if k == steps else 1.0
            carried += weight * np.exp(step + carry * (time - k * dt))
            log_s = step
        average = carried / steps
        terminal = np.exp(log_s)
        strike_put = discount * np.maximum(average - terminal, 0.0)
        price_put = discount * np.maximum(forward - average, 0.0)
        values = {
            "european_put": discount * np.maximum(1.0 - terminal, 0.0),
            "average_strike_put": strike_put,
            "average_price_put": price_put,
            "symmetry_gap": strike_put - price_put,
            "lookback": np.exp(running_max) - discount * terminal,
            "discounted_terminal": discount * terminal,
        }
        for name in names:
            sums[name] += float(values[name].sum())
            squares[name] += float(np.square(values[name]).sum())
        done += n
    out: dict[str, McEstimate] = {}
    for name in names:
        mean = sums[name] / paths
        variance = max(squares[name] / paths - mean * mean, 0.0) * paths / (paths - 1)
        out[name] = McEstimate(mean=mean, stderr=math.sqrt(variance / paths), paths=paths)
    return out


def _simulate_for_test(
    volatility: float, time: float, rate: float, yield_: float = 0.0
) -> dict[str, McEstimate]:
    return simulate_payoffs(
        volatility=volatility,
        time=time,
        risk_free_rate=rate,
        dividend_yield=yield_,
        paths=TEST_PATHS,
        steps=max(10, round(TEST_STEPS_PER_YEAR * time)),
        seed=TEST_SEED,
    )


def _discount(method: str, volatility: float, time: float, rate: float, yield_: float) -> float:
    return ESTIMATORS[method](
        volatility=volatility, time=time, risk_free_rate=rate, dividend_yield=yield_
    ).discount


# --------------------------------------------------------------------------------------
# DL1-DL6: hand-derived fixtures (docs/dlom.md)
# --------------------------------------------------------------------------------------

# (fixture, method, volatility, time, rate, yield, expected from the 60-digit recomputation)
FIXTURES = [
    ("DL1", "chaffe", 0.6, 2.0, 0.04, 0.0, 0.278872217516708),
    ("DL1", "finnerty", 0.6, 2.0, 0.04, 0.0, 0.182002096928826),
    ("DL1", "ghaidarov", 0.6, 2.0, 0.04, 0.0, 0.199273529588148),
    ("DL1", "longstaff", 0.6, 2.0, 0.04, 0.0, 0.877157849047459),
    ("DL2", "chaffe", 0.6, 2.0, 0.04, 0.03, 0.297180911982105),
    ("DL2", "finnerty", 0.6, 2.0, 0.04, 0.03, 0.171403119925531),
    ("DL2", "ghaidarov", 0.6, 2.0, 0.04, 0.03, 0.187668742648269),
    ("DL3", "longstaff", 1.0, 2.0, 0.04, 0.0, 1.720141106187292),
    ("DL4", "chaffe", 0.6, 2.0, -0.005, 0.0, 0.335324812011035),
]


@pytest.mark.parametrize(
    ("fixture", "method", "volatility", "time", "rate", "yield_", "expected"), FIXTURES
)
def test_hand_derived_fixtures(
    fixture: str,
    method: str,
    volatility: float,
    time: float,
    rate: float,
    yield_: float,
    expected: float,
) -> None:
    got = _discount(method, volatility, time, rate, yield_)
    assert got == pytest.approx(expected, rel=1e-12, abs=0.0), fixture


def test_dl3_longstaff_is_reported_above_one_unclamped() -> None:
    estimate = longstaff_dlom(volatility=1.0, time=2.0, risk_free_rate=0.04)
    assert estimate.discount > 1.0
    assert estimate.discount == pytest.approx(1.720141106187292, rel=1e-12)


def test_dl4_negative_rate_is_accepted_as_given() -> None:
    estimate = chaffe_dlom(volatility=0.6, time=2.0, risk_free_rate=-0.005)
    assert estimate.risk_free_rate == -0.005
    # Chaffe is bounded by exp(-rT), which a negative rate lifts above 1.
    assert estimate.discount < math.exp(0.005 * 2.0)


def test_dl5_finnerty_ceiling() -> None:
    ceiling = math.erf(math.sqrt(math.log(2.0)) / (2.0 * math.sqrt(2.0)))
    assert ceiling == pytest.approx(0.322792902826673, rel=1e-13)
    # s = sigma^2 T = 10,000: v^2 = ln 2 to within e^{-s}; approached from below.
    assert _discount("finnerty", 10.0, 100.0, 0.0, 0.0) == pytest.approx(ceiling, rel=1e-13)
    below = [_discount("finnerty", sigma, 4.0, 0.0, 0.0) for sigma in (0.5, 1.0, 1.5, 2.5)]
    assert below == sorted(below)
    assert all(value < ceiling for value in below)
    # The ceiling carries the dividend factor with it.
    assert _discount("finnerty", 10.0, 100.0, 0.0, 0.001) == pytest.approx(
        ceiling * math.exp(-0.1), rel=1e-13
    )


def test_dl6_longstaff_crosses_one_at_s_star() -> None:
    s_star = 0.886065843793
    below = _discount("longstaff", math.sqrt(s_star * (1 - 1e-9)), 1.0, 0.0, 0.0)
    above = _discount("longstaff", math.sqrt(s_star * (1 + 1e-9)), 1.0, 0.0, 0.0)
    assert below < 1.0 < above
    assert math.sqrt(s_star) == pytest.approx(0.941310705237, rel=1e-11)


@pytest.mark.parametrize("s", [0.01, 0.72, 2.0, 9.0])
def test_longstaff_equals_quadrature_of_the_running_maximum_law(s: float) -> None:
    # E[e^M] - 1 = int_0^inf e^m P(M > m) dm, M the running maximum of a Brownian motion
    # with drift -sigma^2/2 and P(M > m) from the reflection principle (docs/dlom.md).
    # Numerical quadrature of that law, independent of the closed form's algebra.
    root = math.sqrt(s)

    def tail(m: float) -> float:
        return math.exp(m + norm.logsf((m + s / 2) / root)) + norm.cdf((s / 2 - m) / root)

    integral, error = quad(tail, 0.0, math.inf, limit=200, epsabs=1e-13, epsrel=1e-12)
    got = _discount("longstaff", root, 1.0, 0.0, 0.0)
    assert got == pytest.approx(integral, rel=1e-9), (integral, error)


# --------------------------------------------------------------------------------------
# Numerics: every branch against the independent reference
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", DLOM_METHODS)
@pytest.mark.parametrize(
    "s",
    ["1e-10", "1e-6", "1e-4", "0.01", "0.2", "0.4999", "0.5", "0.5001", "1", "2", "5", "20", "50"],
)
def test_all_branches_match_the_60_digit_reference(method: str, s: str) -> None:
    volatility = str(Decimal(s).sqrt())
    expected = _reference(method, volatility, "1", "0", "0")
    got = _discount(method, float(volatility), 1.0, 0.0, 0.0)
    assert got == pytest.approx(expected, rel=1e-10, abs=0.0)


@pytest.mark.parametrize("method", ["finnerty", "ghaidarov"])
def test_both_sides_of_the_series_edge_match_the_reference(method: str) -> None:
    # The series branch ends at s = 0.5. Each side is checked against the 60-digit value
    # at the same input, so the function's own slope does not enter the tolerance.
    for s in (0.5 * (1 - 1e-12), 0.5 * (1 + 1e-12)):
        volatility = math.sqrt(s)
        expected = _reference(method, repr(volatility), "1", "0", "0")
        got = _discount(method, volatility, 1.0, 0.0, 0.0)
        assert got == pytest.approx(expected, rel=1e-13, abs=0.0), s


def test_small_variance_ratios() -> None:
    """As sigma sqrt(T) -> 0 with r = q = 0, derived in docs/dlom.md:

    Chaffe ~ sigma sqrt(T) / sqrt(2 pi); Longstaff ~ 2 x Chaffe; Finnerty and Ghaidarov
    ~ Chaffe / sqrt 3, because all three average-based variances start at s/3.
    """
    root = 1e-4
    chaffe = _discount("chaffe", root, 1.0, 0.0, 0.0)
    assert chaffe / (root / math.sqrt(2 * math.pi)) == pytest.approx(1.0, rel=1e-6)
    assert _discount("longstaff", root, 1.0, 0.0, 0.0) / chaffe == pytest.approx(2.0, rel=1e-4)
    for method in ("finnerty", "ghaidarov"):
        ratio = _discount(method, root, 1.0, 0.0, 0.0) / chaffe
        assert ratio == pytest.approx(1 / math.sqrt(3), rel=1e-6), method


# --------------------------------------------------------------------------------------
# Structure: how each input enters
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", DLOM_METHODS)
def test_increasing_in_volatility(method: str) -> None:
    values = [_discount(method, sigma, 2.0, 0.04, 0.0) for sigma in (0.05, 0.2, 0.4, 0.8, 1.6, 3.2)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_chaffe_is_not_monotone_in_holding_period() -> None:
    # r > 0, q = 0: the put is struck at spot, so it tends to zero as T grows.
    assert _discount("chaffe", 0.3, 200.0, 0.05, 0.0) < _discount("chaffe", 0.3, 5.0, 0.05, 0.0)


@pytest.mark.parametrize("method", ["finnerty", "ghaidarov", "longstaff"])
def test_rate_does_not_enter_and_is_recorded(method: str) -> None:
    estimates = [
        ESTIMATORS[method](volatility=0.6, time=2.0, risk_free_rate=rate)
        for rate in (-0.01, 0.0, 0.1)
    ]
    assert len({estimate.discount for estimate in estimates}) == 1
    assert [estimate.risk_free_rate for estimate in estimates] == [-0.01, 0.0, 0.1]


def test_chaffe_depends_on_the_rate() -> None:
    assert _discount("chaffe", 0.6, 2.0, 0.0, 0.0) != _discount("chaffe", 0.6, 2.0, 0.04, 0.0)


@pytest.mark.parametrize("method", ["finnerty", "ghaidarov"])
def test_dividend_yield_scales_by_exp_minus_q_t(method: str) -> None:
    base = _discount(method, 0.6, 2.0, 0.04, 0.0)
    assert _discount(method, 0.6, 2.0, 0.04, 0.03) == pytest.approx(
        base * math.exp(-0.06), rel=1e-14
    )


# --------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------


def test_longstaff_refuses_a_dividend_yield() -> None:
    with pytest.raises(OpmError, match=r"longstaff: dividend_yield=0\.02 refused"):
        longstaff_dlom(volatility=0.6, time=2.0, risk_free_rate=0.04, dividend_yield=0.02)


def test_comparison_refuses_a_dividend_yield_for_the_whole_set() -> None:
    with pytest.raises(OpmError, match="longstaff_dlom has no dividend term"):
        dlom_comparison(volatility=0.6, time=2.0, risk_free_rate=0.04, dividend_yield=0.02)


@pytest.mark.parametrize("method", DLOM_METHODS)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volatility", 0.0),
        ("volatility", -0.3),
        ("volatility", math.nan),
        ("volatility", math.inf),
        ("time", 0.0),
        ("time", -1.0),
        ("time", math.inf),
        ("risk_free_rate", math.nan),
        ("dividend_yield", math.inf),
        ("volatility", True),
    ],
)
def test_bad_inputs_are_refused_with_the_method_and_field_named(
    method: str, field: str, value: float
) -> None:
    kwargs: dict[str, float] = {
        "volatility": 0.6,
        "time": 2.0,
        "risk_free_rate": 0.04,
        "dividend_yield": 0.0,
    }
    kwargs[field] = value
    with pytest.raises(OpmError, match=rf"^{method}: {field}"):
        ESTIMATORS[method](**kwargs)


def test_underflowing_variance_is_refused() -> None:
    with pytest.raises(OpmError, match=r"volatility\*\*2 \* time"):
        finnerty_dlom(volatility=1e-200, time=1.0, risk_free_rate=0.0)


def test_volatility_and_time_and_rate_have_no_defaults() -> None:
    for function in (*ESTIMATORS.values(), dlom_comparison):
        with pytest.raises(TypeError):
            function()  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            function(volatility=0.6, time=2.0)  # type: ignore[call-arg]


# --------------------------------------------------------------------------------------
# The comparison and the absence of a blended number
# --------------------------------------------------------------------------------------


def test_comparison_is_the_four_individual_estimates_in_order() -> None:
    compared = dlom_comparison(volatility=0.6, time=2.0, risk_free_rate=0.04)
    assert [estimate.method for estimate in compared] == list(DLOM_METHODS)
    assert DLOM_METHODS == ("chaffe", "finnerty", "longstaff", "ghaidarov")
    for estimate in compared:
        alone = ESTIMATORS[estimate.method](volatility=0.6, time=2.0, risk_free_rate=0.04)
        assert estimate == alone


def test_there_is_no_default_average_or_single_dlom() -> None:
    assert set(dlom_module.__all__) == {
        "DLOM_METHODS",
        "chaffe_dlom",
        "dlom_comparison",
        "finnerty_dlom",
        "ghaidarov_dlom",
        "longstaff_dlom",
    }
    public = {name for name in vars(dlom_module) if not name.startswith("_")}
    for word in ("average", "mean", "blend", "default", "combined", "median", "select"):
        assert not any(word in name.lower() for name in public), word
    assert not hasattr(dlom_module, "dlom")
    fields = set(DlomEstimate.model_fields)
    assert fields.isdisjoint({"average", "mean", "blended", "combined", "range"})


def test_every_estimate_carries_its_formula_source_status_and_caveats() -> None:
    for estimate in dlom_comparison(volatility=0.6, time=2.0, risk_free_rate=0.04):
        caveats = " ".join(estimate.caveats)
        assert "not an option price" in caveats
        assert "the analogy is an argument, not an identity" in caveats
        assert "AICPA Accounting and Valuation Guide" in caveats
        assert "separate judgment applied after the allocation" in caveats
        assert "409A" in caveats and "IPEV" in caveats and "No conformance" in caveats
        assert "Do not average them" in caveats
        assert "NOT verified against the publication" in estimate.source
        assert estimate.formula.startswith("D = ")
        assert estimate.assumptions
        assert estimate.engine_version == "opm-dlom-v1"
    finnerty = finnerty_dlom(volatility=0.6, time=2.0, risk_free_rate=0.04)
    assert "Finnerty, J. D. (2012)" in finnerty.source
    assert "2002 working paper is NOT established" in finnerty.source
    longstaff = longstaff_dlom(volatility=0.6, time=2.0, risk_free_rate=0.04)
    assert "not a marketability discount" in " ".join(longstaff.caveats)
    assert "unclamped" in " ".join(longstaff.caveats)


# --------------------------------------------------------------------------------------
# Monte Carlo: each closed form against a simulation of its own payoff
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volatility", "time", "rate", "yield_"),
    [(0.3, 1.0, 0.04, 0.0), (0.6, 2.0, 0.04, 0.0), (0.9, 3.0, 0.0, 0.0), (0.6, 2.0, -0.005, 0.02)],
)
def test_chaffe_matches_a_simulated_european_put(
    volatility: float, time: float, rate: float, yield_: float
) -> None:
    mc = _simulate_for_test(volatility, time, rate, yield_)["european_put"]
    closed = _discount("chaffe", volatility, time, rate, yield_)
    assert mc.within(closed), (closed, mc)


@pytest.mark.parametrize(
    ("volatility", "time", "rate"), [(0.3, 1.0, 0.04), (0.6, 2.0, 0.04), (0.9, 3.0, 0.0)]
)
def test_longstaff_matches_a_simulated_hindsight_maximum(
    volatility: float, time: float, rate: float
) -> None:
    mc = _simulate_for_test(volatility, time, rate)["lookback"]
    closed = _discount("longstaff", volatility, time, rate, 0.0)
    assert mc.within(closed), (closed, mc)


@pytest.mark.parametrize(("volatility", "time", "rate", "yield_"), [(0.6, 2.0, 0.04, 0.0)])
def test_average_strike_put_lies_strictly_between_finnerty_and_ghaidarov(
    volatility: float, time: float, rate: float, yield_: float
) -> None:
    """The headline of docs/dlom.md, at the test path count.

    Neither closed form prices its payoff exactly. At sigma sqrt(T) = 0.85 Finnerty is
    below the simulated value, and Ghaidarov above it, each by more than
    Z_TOLERANCE standard errors.
    """
    mc = _simulate_for_test(volatility, time, rate, yield_)["average_strike_put"]
    finnerty = _discount("finnerty", volatility, time, rate, yield_)
    ghaidarov = _discount("ghaidarov", volatility, time, rate, yield_)
    assert finnerty < mc.mean - Z_TOLERANCE * mc.stderr, (finnerty, mc)
    assert ghaidarov > mc.mean + Z_TOLERANCE * mc.stderr, (ghaidarov, mc)


def test_bracket_holds_with_a_rate_and_a_dividend_yield() -> None:
    # r = 0.05, q = 0.02: the simulation carries each price at r - q and discounts at r,
    # so this checks that r drops out and q enters as exp(-qT), not only the q = 0 case.
    mc = _simulate_for_test(0.6, 2.0, 0.05, 0.02)["average_strike_put"]
    finnerty = _discount("finnerty", 0.6, 2.0, 0.05, 0.02)
    ghaidarov = _discount("ghaidarov", 0.6, 2.0, 0.05, 0.02)
    assert finnerty < mc.mean - Z_TOLERANCE * mc.stderr < mc.mean + Z_TOLERANCE * mc.stderr
    assert mc.mean + Z_TOLERANCE * mc.stderr < ghaidarov


def test_both_average_formulas_agree_with_simulation_at_small_sigma_sqrt_t() -> None:
    # sigma sqrt(T) = 0.2 (s = 0.04): all three share the leading term s/3. This checks
    # for gross error only. At this point Finnerty's recorded gap, about 0.03 percentage
    # points (docs/dlom.md), is detectable at a million paths but sits inside this test's
    # four-standard-error band of about 0.08 at 100,000 paths.
    mc = _simulate_for_test(0.2, 1.0, 0.04)["average_strike_put"]
    for method in ("finnerty", "ghaidarov"):
        assert mc.within(_discount(method, 0.2, 1.0, 0.04, 0.0)), (method, mc)


@pytest.mark.parametrize(("volatility", "time"), [(0.6, 2.0), (0.9, 3.0)])
def test_asian_put_call_symmetry_holds_in_the_simulation(volatility: float, time: float) -> None:
    # At zero net carry the average-strike put and the at-the-money average-price put
    # have the same value. That is why Ghaidarov's moment match of the average alone is
    # an approximation to the average-strike put at all.
    gap = _simulate_for_test(volatility, time, 0.0)["symmetry_gap"]
    assert gap.within(0.0), gap


@pytest.mark.parametrize(("rate", "yield_"), [(0.04, 0.0), (0.05, 0.02), (-0.005, 0.0)])
def test_the_simulated_price_is_a_martingale_after_carry(rate: float, yield_: float) -> None:
    # exp(-rT) E[S_T] = exp(-qT). If this failed, every payoff above would be biased.
    s_t = _simulate_for_test(0.6, 2.0, rate, yield_)["discounted_terminal"]
    assert s_t.within(math.exp(-yield_ * 2.0)), s_t


def test_simulation_is_reproducible_from_its_seed() -> None:
    first = _simulate_for_test(0.3, 1.0, 0.04)
    second = _simulate_for_test(0.3, 1.0, 0.04)
    assert first == second


# --------------------------------------------------------------------------------------
# Replay of the recorded runs in docs/dlom.md
# --------------------------------------------------------------------------------------

RECORDED_SEED = 1995
RECORDED_PATHS = 1_000_000
RECORDED_STEPS_PER_YEAR = 100
RECORDED_RATE = 0.04
RECORDED_GRID = [
    (sigma, time) for time in (0.5, 1.0, 2.0, 3.0) for sigma in (0.3, 0.45, 0.6, 0.75, 0.9, 1.2)
]
COMPARISON_RATE = 0.04
COMPARISON_VOLATILITIES = (0.3, 0.45, 0.6, 0.75, 0.9, 1.2)
COMPARISON_TIMES = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0)


def _pct(value: float, digits: int = 2) -> str:
    return f"{100 * value:.{digits}f}"


def _recorded_monte_carlo() -> None:
    print(
        f"seed {RECORDED_SEED}, {RECORDED_PATHS:,} paths, {RECORDED_STEPS_PER_YEAR} steps "
        f"per year, r = {RECORDED_RATE}, q = 0; values in % of value, MC as mean (s.e.)"
    )
    harness: list[str] = []
    finding: list[str] = []
    for sigma, time in RECORDED_GRID:
        mc = simulate_payoffs(
            volatility=sigma,
            time=time,
            risk_free_rate=RECORDED_RATE,
            dividend_yield=0.0,
            paths=RECORDED_PATHS,
            steps=round(RECORDED_STEPS_PER_YEAR * time),
            seed=RECORDED_SEED,
        )
        values = {m: _discount(m, sigma, time, RECORDED_RATE, 0.0) for m in DLOM_METHODS}
        avg = mc["average_strike_put"]
        gap = mc["symmetry_gap"]

        def cell(estimate: McEstimate) -> str:
            return f"{_pct(estimate.mean, 3)} ({_pct(estimate.stderr, 3)})"

        put, look, s_t = mc["european_put"], mc["lookback"], mc["discounted_terminal"]
        lead = f"| {sigma} | {time} | {sigma * math.sqrt(time):.3f} "
        harness.append(
            lead + f"| {_pct(values['chaffe'], 3)} | {cell(put)} "
            f"| {(values['chaffe'] - put.mean) / put.stderr:+.1f} "
            f"| {_pct(values['longstaff'], 3)} | {cell(look)} "
            f"| {(values['longstaff'] - look.mean) / look.stderr:+.1f} "
            f"| {(s_t.mean - 1.0) / s_t.stderr:+.1f} "
            f"| {cell(gap)} | {gap.mean / gap.stderr:+.1f} |"
        )
        finding.append(
            lead + f"| {_pct(values['finnerty'], 3)} | {cell(avg)} "
            f"| {_pct(values['ghaidarov'], 3)} "
            f"| {100 * (values['finnerty'] - avg.mean):+.3f} "
            f"| {100 * (values['ghaidarov'] - avg.mean):+.3f} "
            f"| {(values['finnerty'] - avg.mean) / avg.stderr:+.1f} "
            f"| {(values['ghaidarov'] - avg.mean) / avg.stderr:+.1f} |"
        )
    print("\nharness: the exact closed forms, the martingale and the Asian symmetry")
    print(
        "| sigma | T | sigma*sqrt(T) | Chaffe | MC put | (C - MC)/se | Longstaff | MC max "
        "| (L - MC)/se | (MC S_T - 1)/se | MC symmetry gap | gap/se |"
    )
    print("|---:" * 12 + "|")
    print("\n".join(harness))
    print("\nfinding: the average-strike put against its two closed forms")
    print(
        "| sigma | T | sigma*sqrt(T) | Finnerty | MC avg-strike put | Ghaidarov "
        "| F - MC (pp) | G - MC (pp) | (F - MC)/se | (G - MC)/se |"
    )
    print("|---:" * 10 + "|")
    print("\n".join(finding), flush=True)
    print("\nChaffe and Longstaff against five seeds, sigma = 0.6, T = 2, (closed - MC)/se:")
    for seed in range(RECORDED_SEED, RECORDED_SEED + 5):
        mc = simulate_payoffs(
            volatility=0.6,
            time=2.0,
            risk_free_rate=RECORDED_RATE,
            dividend_yield=0.0,
            paths=RECORDED_PATHS,
            steps=round(RECORDED_STEPS_PER_YEAR * 2.0),
            seed=seed,
        )
        put, look, s_t = mc["european_put"], mc["lookback"], mc["discounted_terminal"]
        print(
            f"  seed {seed}: Chaffe "
            f"{(_discount('chaffe', 0.6, 2.0, RECORDED_RATE, 0.0) - put.mean) / put.stderr:+.1f}"
            f", Longstaff "
            f"{(_discount('longstaff', 0.6, 2.0, RECORDED_RATE, 0.0) - look.mean) / look.stderr:+.1f}"
            f", (MC S_T - 1)/se {(s_t.mean - 1.0) / s_t.stderr:+.1f}",
            flush=True,
        )
    print("\ntime-step sensitivity of the average-strike put, sigma = 0.6, T = 2:")
    for steps in (25, 50, 100, 200, 400):
        avg = simulate_payoffs(
            volatility=0.6,
            time=2.0,
            risk_free_rate=RECORDED_RATE,
            dividend_yield=0.0,
            paths=RECORDED_PATHS,
            steps=steps,
            seed=RECORDED_SEED,
        )["average_strike_put"]
        print(f"  {steps:>3} steps: {_pct(avg.mean, 3)} ({_pct(avg.stderr, 3)})", flush=True)


def _comparison_grid() -> None:
    print(f"r = {COMPARISON_RATE}, q = 0; each cell C / F / G / L in % of value")
    header = " | ".join(f"T = {time}" for time in COMPARISON_TIMES)
    print(f"| sigma | {header} |")
    print("|---:|" + "---|" * len(COMPARISON_TIMES))
    for sigma in COMPARISON_VOLATILITIES:
        cells = []
        for time in COMPARISON_TIMES:
            v = [_discount(m, sigma, time, COMPARISON_RATE, 0.0) for m in DLOM_METHODS]
            chaffe, finnerty, longstaff, ghaidarov = v
            cells.append(
                f"{_pct(chaffe, 1)} / {_pct(finnerty, 1)} / {_pct(ghaidarov, 1)} / "
                f"{'**' if longstaff >= 1 else ''}{_pct(longstaff, 1)}"
                f"{'**' if longstaff >= 1 else ''}"
            )
        print(f"| {sigma} | " + " | ".join(cells) + " |")
    print("\nspread in percentage points, max - min over the three put-based estimators")
    print("(Chaffe, Finnerty, Ghaidarov), and with Longstaff included:")
    print(f"| sigma | {header} |")
    print("|---:|" + "---|" * len(COMPARISON_TIMES))
    for sigma in COMPARISON_VOLATILITIES:
        cells = []
        for time in COMPARISON_TIMES:
            v = {m: _discount(m, sigma, time, COMPARISON_RATE, 0.0) for m in DLOM_METHODS}
            three = [v["chaffe"], v["finnerty"], v["ghaidarov"]]
            four = [*three, v["longstaff"]]
            cells.append(f"{_pct(max(three) - min(three), 1)} / {_pct(max(four) - min(four), 1)}")
        print(f"| {sigma} | " + " | ".join(cells) + " |")


SEED_STUDY_FIRST = 300_000
SEED_STUDY_COUNT = 100
SEED_STUDY_PATHS = 200_000


def _seed_study() -> None:
    """Many independent seeds at sigma = 0.6, T = 2: bias, or one draw of shared-path noise?

    The recorded grid shares its paths across cells, so a sign repeated down a column is one
    draw. Independent seeds are what separate a bias from that draw.
    """
    chaffe = _discount("chaffe", 0.6, 2.0, RECORDED_RATE, 0.0)
    longstaff = _discount("longstaff", 0.6, 2.0, RECORDED_RATE, 0.0)
    scores: dict[str, list[float]] = {"chaffe": [], "longstaff": [], "martingale": []}
    for seed in range(SEED_STUDY_FIRST, SEED_STUDY_FIRST + SEED_STUDY_COUNT):
        mc = simulate_payoffs(
            volatility=0.6,
            time=2.0,
            risk_free_rate=RECORDED_RATE,
            dividend_yield=0.0,
            paths=SEED_STUDY_PATHS,
            steps=200,
            seed=seed,
        )
        put, look, s_t = mc["european_put"], mc["lookback"], mc["discounted_terminal"]
        scores["chaffe"].append((chaffe - put.mean) / put.stderr)
        scores["longstaff"].append((longstaff - look.mean) / look.stderr)
        scores["martingale"].append((s_t.mean - 1.0) / s_t.stderr)
    print(
        f"{SEED_STUDY_COUNT} independent seeds from {SEED_STUDY_FIRST}, "
        f"{SEED_STUDY_PATHS:,} paths, 200 steps, sigma = 0.6, T = 2, r = {RECORDED_RATE}"
    )
    for name, values in scores.items():
        z = np.array(values)
        print(
            f"  {name:10s} mean z {z.mean():+.3f}, pooled z {z.mean() * math.sqrt(z.size):+.2f}, "
            f"sd {z.std(ddof=1):.2f}, |z| > 2 in {int((np.abs(z) > 2).sum())} of {z.size}"
        )


if __name__ == "__main__":
    if "--grid" in sys.argv[1:]:
        _comparison_grid()
    elif "--seeds" in sys.argv[1:]:
        _seed_study()
    else:
        _recorded_monte_carlo()
