"""Four published discounts for lack of marketability, evaluated separately and never blended.

Each function evaluates one closed form, which prices one stated payoff, and returns a
`DlomEstimate` that says which formula was evaluated, where it is attributed, what it
assumes and what it does not measure. There is no default method, no average across
methods and no single "the DLOM" function. At ordinary inputs the three put-based methods
disagree with one another by about as much as a plausible change in volatility or holding
period moves any one of them, and Longstaff's bound sits far above all three. A blended
number would hide exactly that. The comparison, from `dlom_comparison`, is the output. `docs/dlom.md` holds the derivations,
the Monte Carlo checks and the comparison grid.

Value is normalised to 1 at the valuation date. Write ``s = sigma**2 * T``, ``N`` for the
standard normal distribution function, ``r`` for the risk-free rate and ``q`` for the
dividend yield. The payoffs, as simulated in `tests/test_opm_dlom.py`, are:

- **Chaffe**: a European put struck at the initial price, ``exp(-rT) E[(1 - S_T)^+]``.
  Merton's closed form prices it exactly.
- **Finnerty**: an average-strike put, ``exp(-rT) E[(A_T - S_T)^+]``, where ``A_T`` is
  the continuous arithmetic average of prices carried forward to ``T`` at ``r - q``. The
  closed form is an exchange option after bivariate-lognormal moment matching of
  ``(A_T, S_T)``, so it approximates that payoff rather than pricing it exactly.
- **Ghaidarov**: the same payoff, through a lognormal moment match of ``A_T`` alone. It is
  also an approximation.
- **Longstaff**: ``exp(-rT) E[max_t S_t exp(r(T - t)) - S_T]``, the value of selling at
  the path maximum with hindsight and reinvesting at ``r``. Exact for continuous
  monitoring.

None of the four is a marketability discount. Each prices restricted marketability
through an option analogy, and the analogy is an argument, not an identity.
"""

from __future__ import annotations

import math

from ovf.opm.types import DlomEstimate, DlomMethod, OpmError

__all__ = [
    "DLOM_METHODS",
    "chaffe_dlom",
    "dlom_comparison",
    "finnerty_dlom",
    "ghaidarov_dlom",
    "longstaff_dlom",
]

DLOM_METHODS: tuple[DlomMethod, ...] = ("chaffe", "finnerty", "longstaff", "ghaidarov")
"""The order `dlom_comparison` reports in. An order, not a ranking or a preference."""

_SQRT2 = math.sqrt(2.0)
_LN2 = math.log(2.0)

# The series and closed branches of the two moment ratios meet here. Below it, the closed
# form of e^s - s - 1 loses digits to cancellation; above it, the series needs more terms.
_SERIES_BELOW = 0.5

_COMMON_CAVEATS = [
    "Prices restricted marketability through one option analogy. A marketability discount "
    "is not an option price; the analogy is an argument, not an identity.",
    "The AICPA Accounting and Valuation Guide, Valuation of Privately-Held-Company Equity "
    "Securities Issued as Compensation, treats a discount for lack of marketability as a "
    "separate judgment applied after the allocation, not as an output of it. This number "
    "is one input to that judgment, not the judgment.",
    "No conformance with IRC section 409A, the AICPA Guide or the IPEV Valuation "
    "Guidelines is claimed. The formula is implemented as stated in docs/dlom.md.",
    "One of four estimators whose disagreement at ordinary inputs is about as large as the "
    "effect of a plausible change in volatility or holding period, and with Longstaff far "
    "larger (docs/dlom.md). Read it beside the other three from dlom_comparison. Do not "
    "average them.",
]

_COMMON_ASSUMPTIONS = [
    "Value follows geometric Brownian motion with constant volatility over the holding period.",
    "The holding period is a known constant; an uncertain or state-dependent liquidity date "
    "is not modelled.",
    "Rates and yields are continuously compounded and constant over the holding period.",
    "Value is normalised to 1 at the valuation date; the discount is a fraction of it.",
]

_ATTRIBUTION_STATUS = (
    "attribution recalled, NOT verified against the publication in this checkout; the "
    "algebra evaluated is stated in full in docs/dlom.md and can be checked without it"
)


def _check_inputs(
    method: DlomMethod,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float:
    """Refuse inputs the formulas cannot take, and return ``s = volatility**2 * time``."""
    for name, value in (
        ("volatility", volatility),
        ("time", time),
        ("risk_free_rate", risk_free_rate),
        ("dividend_yield", dividend_yield),
    ):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise OpmError(f"{method}: {name} must be a real number, got {value!r}")
        if not math.isfinite(value):
            raise OpmError(f"{method}: {name} must be finite, got {value!r}")
    if volatility <= 0.0:
        raise OpmError(f"{method}: volatility must be positive, got {volatility!r}")
    if time <= 0.0:
        raise OpmError(f"{method}: time (holding period in years) must be positive, got {time!r}")
    variance = volatility * volatility * time
    if not (variance > 0.0 and math.isfinite(variance)):
        raise OpmError(
            f"{method}: volatility**2 * time = {variance!r} is not a positive finite number "
            f"(volatility={volatility!r}, time={time!r})"
        )
    return variance


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / _SQRT2)


def _central_mass(v: float) -> float:
    """``N(v/2) - N(-v/2)``, written as an erf so a small ``v`` loses no digits."""
    return math.erf(v / (2.0 * _SQRT2))


def _log_average_second_moment(s: float) -> float:
    """``ln(2 (e^s - s - 1) / s^2)``: ``ln E[A^2] / E[A]^2`` for a driftless average.

    For small ``s`` this sums ``2 s^k / (k + 2)!`` for ``k >= 1``, because the closed form
    subtracts two nearly equal numbers. For larger ``s`` it factors ``e^s`` out so that
    the closed form cannot overflow.
    """
    if s < _SERIES_BELOW:
        return math.log1p(_series_from_first(s, first=s / 3.0, offset=2))
    return _LN2 + s + math.log1p(-(s + 1.0) * math.exp(-s)) - 2.0 * math.log(s)


def _log_growth_ratio(s: float) -> float:
    """``ln((e^s - 1) / s)``: ``ln E[A S_T] / (E[A] E[S_T])`` for a driftless average."""
    if s < _SERIES_BELOW:
        return math.log1p(_series_from_first(s, first=s / 2.0, offset=1))
    return s + math.log1p(-math.exp(-s)) - math.log(s)


def _series_from_first(s: float, *, first: float, offset: int) -> float:
    """Sum ``c s^k / (k + offset)!`` over ``k >= 1``, given the ``k = 1`` term.

    ``2 (e^s - s - 1) / s^2 - 1`` is the case ``c = 2, offset = 2`` (first term ``s/3``)
    and ``(e^s - 1) / s - 1`` is ``c = 1, offset = 1`` (first term ``s/2``). Each term is
    the previous one times ``s / (k + offset)``, so for ``s < 0.5`` the terms shrink at
    least fourfold and the loop stops within about twenty terms.
    """
    term, total, k = first, first, 1
    while term > 1e-17 * total:
        k += 1
        term *= s / (k + offset)
        total += term
    return total


def _estimate(
    *,
    method: DlomMethod,
    discount: float,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float,
    formula: str,
    source: str,
    assumptions: list[str],
    caveats: list[str],
) -> DlomEstimate:
    if not math.isfinite(discount):
        raise OpmError(
            f"{method}: the closed form evaluated to {discount!r} at volatility={volatility!r}, "
            f"time={time!r}; it has left floating-point range"
        )
    if discount < 0.0:
        raise OpmError(
            f"{method}: the closed form evaluated to {discount!r} < 0 at "
            f"volatility={volatility!r}, time={time!r}, risk_free_rate={risk_free_rate!r}, "
            f"dividend_yield={dividend_yield!r}; the value is non-negative in exact "
            "arithmetic, so this is lost precision and is refused rather than clamped"
        )
    return DlomEstimate(
        method=method,
        discount=discount,
        volatility=volatility,
        time=time,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        formula=formula,
        source=source,
        assumptions=[*_COMMON_ASSUMPTIONS, *assumptions],
        caveats=[*caveats, *_COMMON_CAVEATS],
    )


def chaffe_dlom(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> DlomEstimate:
    """Chaffe (1993): an at-the-money European protective put over the restriction period.

    Evaluates the Black-Scholes-Merton put with spot and strike both equal to the value
    at the valuation date, as a fraction of that value::

        D  = exp(-rT) N(-d2) - exp(-qT) N(-d1)
        d1 = ((r - q) + sigma^2 / 2) T / (sigma sqrt(T)),   d2 = d1 - sigma sqrt(T)

    This prices ``exp(-rT) E[(1 - S_T)^+]`` exactly under geometric Brownian motion.
    The strike is the initial price, not the forward price. The rate enters, and a
    negative rate is accepted as given.
    """
    s = _check_inputs("chaffe", volatility, time, risk_free_rate, dividend_yield)
    root = math.sqrt(s)
    d1 = ((risk_free_rate - dividend_yield) * time + 0.5 * s) / root
    d2 = d1 - root
    put = math.exp(-risk_free_rate * time) * _norm_cdf(-d2) - math.exp(
        -dividend_yield * time
    ) * _norm_cdf(-d1)
    return _estimate(
        method="chaffe",
        discount=put,
        volatility=volatility,
        time=time,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        formula=(
            "D = exp(-r*T)*N(-d2) - exp(-q*T)*N(-d1), d1 = ((r - q) + sigma^2/2)*T / "
            "(sigma*sqrt(T)), d2 = d1 - sigma*sqrt(T): the Black-Scholes-Merton put with "
            "spot = strike = 1"
        ),
        source=(
            "attributed to Chaffe, D. B. H. (1993), 'Option pricing as a proxy for discount "
            "for lack of marketability in private company valuations', Business Valuation "
            "Review 12(4); the put is Merton's (1973) closed form; " + _ATTRIBUTION_STATUS
        ),
        assumptions=[
            "Strike equals the value at the valuation date (spot, not forward).",
            "A continuous dividend yield enters as exp(-q*T) on the underlying (Merton).",
        ],
        caveats=[
            "A protective put insures against every fall below the initial value. It "
            "measures the cost of downside insurance over the period, not the cost of being "
            "unable to sell, and a marketable holder does not hold that insurance either.",
            "With a positive rate and a non-negative yield it tends to zero as the holding "
            "period grows without bound, so it is not monotone in the holding period. It is "
            "bounded above by exp(-r*T), which exceeds 1 only when the rate is negative.",
        ],
    )


def finnerty_dlom(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> DlomEstimate:
    """The average-strike put formula attributed to Finnerty (2012), Journal of Derivatives.

    **Which version.** This evaluates exactly the formula below, which is attributed to
    the 2012 journal article. That attribution was recalled, not checked against the
    publication. How the 2002 working paper differs is not established here; a reader with
    both documents should check it. The formula::

        D   = exp(-qT) [N(v/2) - N(-v/2)]
        v^2 = s + ln(2 (e^s - s - 1)) - 2 ln(e^s - 1),   s = sigma^2 T

    Structurally, this is Margrabe's exchange option (receive the average ``A_T``, give
    up ``S_T``) with ``(ln A_T, ln S_T)`` replaced by a bivariate normal whose three
    second moments are matched. ``v^2`` is that normal's variance of ``ln(A_T / S_T)``.
    The formula tends to ``exp(-qT) erf(sqrt(ln 2) / (2 sqrt 2))``, about 32.28%, as
    ``s`` grows. The payoff it approximates tends to ``exp(-qT)``, so the ceiling belongs
    to the moment match and not to the payoff. ``docs/dlom.md`` derives both statements
    and measures the formula against a simulation of the payoff.

    ``risk_free_rate`` does not enter; it is recorded on the estimate and not used.
    """
    s = _check_inputs("finnerty", volatility, time, risk_free_rate, dividend_yield)
    v_squared = s + _log_average_second_moment(s) - 2.0 * _log_growth_ratio(s)
    if not v_squared > 0.0:
        raise OpmError(
            f"finnerty: v^2 = {v_squared!r} is not positive at s = sigma^2*T = {s!r}; "
            "it is positive in exact arithmetic, so this is lost precision"
        )
    discount = math.exp(-dividend_yield * time) * _central_mass(math.sqrt(v_squared))
    return _estimate(
        method="finnerty",
        discount=discount,
        volatility=volatility,
        time=time,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        formula=(
            "D = exp(-q*T)*[N(v/2) - N(-v/2)], v^2 = s + ln(2*(e^s - s - 1)) - "
            "2*ln(e^s - 1), s = sigma^2*T"
        ),
        source=(
            "attributed to Finnerty, J. D. (2012), 'An average-strike put option model of "
            "the marketability discount', The Journal of Derivatives 19(4), 53-69; the "
            "difference from the 2002 working paper is NOT established here; " + _ATTRIBUTION_STATUS
        ),
        assumptions=[
            "Continuous arithmetic averaging over the whole holding period.",
            "The average is of prices each carried forward to T at r - q; with q = 0 that is "
            "the proceeds of selling evenly over the period and reinvesting at r. Under that "
            "convention r drops out and the yield enters as exp(-q*T).",
            "risk_free_rate does not enter the formula; it is recorded, not used.",
        ],
        caveats=[
            "An approximation to its payoff, not its price: an exchange option after "
            "bivariate-lognormal moment matching of the average and the terminal price. The "
            "simulation in docs/dlom.md measures it below the value of that payoff by more "
            "than four standard errors at every point simulated, sigma*sqrt(T) from 0.21 to "
            "2.08: by 0.03 percentage points at 0.21, about 1.1 at 0.85 and 12.3 at 2.08.",
            "Bounded above by exp(-q*T)*erf(sqrt(ln 2)/(2*sqrt 2)), about 32.28%, as "
            "sigma^2*T grows, while the payoff it approximates tends to exp(-q*T). The "
            "ceiling belongs to the moment match, not to the payoff.",
        ],
    )


def ghaidarov_dlom(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> DlomEstimate:
    """The average-strike formula attributed to Ghaidarov (2009) as a critique of Finnerty.

    Evaluates::

        D   = exp(-qT) [N(v/2) - N(-v/2)]
        v^2 = ln(2 (e^s - s - 1)) - 2 ln(s),   s = sigma^2 T

    ``v^2`` is ``ln(E[A^2] / E[A]^2)`` for the arithmetic average of a driftless
    geometric Brownian motion, so this is an at-the-money option on a lognormal variable
    carrying the average's first two moments. At zero net carry, a put-call symmetry for
    Asian options makes that at-the-money fixed-strike option equal in value to the
    average-strike put, and ``docs/dlom.md`` checks the symmetry by simulation. The
    formula is therefore an approximation to the same payoff as Finnerty's. It is not
    that payoff's exact price, and the simulation measures by how much. The content of the
    critique it is attributed to is neither reproduced nor verified here.

    ``risk_free_rate`` does not enter; it is recorded on the estimate and not used.
    """
    s = _check_inputs("ghaidarov", volatility, time, risk_free_rate, dividend_yield)
    v_squared = _log_average_second_moment(s)
    if not v_squared > 0.0:
        raise OpmError(
            f"ghaidarov: v^2 = {v_squared!r} is not positive at s = sigma^2*T = {s!r}; "
            "it is positive in exact arithmetic, so this is lost precision"
        )
    discount = math.exp(-dividend_yield * time) * _central_mass(math.sqrt(v_squared))
    return _estimate(
        method="ghaidarov",
        discount=discount,
        volatility=volatility,
        time=time,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        formula=(
            "D = exp(-q*T)*[N(v/2) - N(-v/2)], v^2 = ln(2*(e^s - s - 1)) - 2*ln(s), s = sigma^2*T"
        ),
        source=(
            "attributed to Ghaidarov, S. (2009), 'Analysis and critique of the average "
            "strike put option marketability discount model', working paper; " + _ATTRIBUTION_STATUS
        ),
        assumptions=[
            "Continuous arithmetic averaging over the whole holding period.",
            "The average is of prices each carried forward to T at r - q, as for Finnerty; "
            "under that convention r drops out and the yield enters as exp(-q*T). Whether "
            "the publication states the yield term in this form is not verified.",
            "risk_free_rate does not enter the formula; it is recorded, not used.",
        ],
        caveats=[
            "An approximation to its payoff, not its price: a lognormal moment match of the "
            "arithmetic average. The simulation in docs/dlom.md measures it above the value "
            "of the average-strike put by more than four standard errors once sigma*sqrt(T) "
            "reaches about 0.42: by about 0.06 percentage points there, 0.65 at 0.85 and 8.6 "
            "at 2.08. Below 0.42 the gap is within the noise of a million paths.",
            "The content of the critique of Finnerty's derivation that this formula is "
            "attributed to is not reproduced or verified here.",
        ],
    )


def longstaff_dlom(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> DlomEstimate:
    """Longstaff (1995): the upper bound on the value of perfect market timing.

    Evaluates the lookback value::

        D = (2 + s/2) N(sqrt(s)/2) + sqrt(s / (2 pi)) exp(-s/8) - 1,   s = sigma^2 T

    That is ``E[max_t S~_t] - 1`` for the discounted price ``S~``, a driftless geometric
    Brownian motion. It is the value of selling at the maximum over the period with
    hindsight and reinvesting at ``r``, measured against holding to ``T``.

    **Not clamped.** It exceeds 1 once ``s`` passes about 0.886 (``sigma sqrt(T)``
    about 0.941) and grows without bound. It is an upper bound on the value of perfect
    market timing, not a marketability discount, and past that point it tells you nothing
    about one. A clamped value would be a different number that no source supports.

    **No dividend term.** The formula has none, so a nonzero ``dividend_yield`` is refused
    rather than quietly dropped. ``risk_free_rate`` does not enter; it is recorded and not
    used.
    """
    s = _check_inputs("longstaff", volatility, time, risk_free_rate, dividend_yield)
    if dividend_yield != 0.0:
        raise OpmError(
            f"longstaff: dividend_yield={dividend_yield!r} refused. Longstaff (1995) has no "
            "dividend term, and dropping the yield would answer a different question from "
            "the one asked. Pass dividend_yield=0.0 to evaluate the published bound."
        )
    root = math.sqrt(s)
    # (2 + s/2) N(a) - 1 = erf(a / sqrt 2) + (s/2) N(a), with a = sqrt(s)/2: no cancellation.
    half_root = 0.5 * root
    discount = (
        math.erf(half_root / _SQRT2)
        + 0.5 * s * _norm_cdf(half_root)
        + math.sqrt(s / (2.0 * math.pi)) * math.exp(-s / 8.0)
    )
    return _estimate(
        method="longstaff",
        discount=discount,
        volatility=volatility,
        time=time,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        formula=(
            "D = (2 + s/2)*N(sqrt(s)/2) + sqrt(s/(2*pi))*exp(-s/8) - 1, s = sigma^2*T: "
            "E[max of the discounted price] - 1 under a driftless geometric Brownian motion"
        ),
        source=(
            "attributed to Longstaff, F. A. (1995), 'How much can marketability affect "
            "security values?', The Journal of Finance 50(5), 1767-1774; " + _ATTRIBUTION_STATUS
        ),
        assumptions=[
            "Continuous monitoring of the maximum over the holding period.",
            "Proceeds of the hindsight sale are reinvested at r, so r does not enter; it is "
            "recorded, not used.",
            "No dividend yield: the formula has no dividend term, and a nonzero yield is refused.",
        ],
        caveats=[
            "An upper bound on the value of perfect market timing (selling at the maximum "
            "with hindsight), not a marketability discount.",
            "Exceeds 100% once sigma*sqrt(T) passes about 0.941 (sigma^2*T about 0.886) and "
            "grows without bound. Past that point it stops being informative about a "
            "marketability discount. It is reported unclamped.",
        ],
    )


def dlom_comparison(
    *,
    volatility: float,
    time: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> list[DlomEstimate]:
    """All four estimators on the same inputs, side by side, in `DLOM_METHODS` order.

    This is the deliverable, not a step towards one. No summary, average, range midpoint
    or preferred method is computed, because the spread between these four is the one
    thing the comparison reliably shows.

    Refused as a whole when ``dividend_yield`` is nonzero: Longstaff has no dividend term,
    and returning three of the four would hide the missing one.
    """
    if dividend_yield != 0.0:
        raise OpmError(
            f"dlom_comparison: dividend_yield={dividend_yield!r} refused for the whole set. "
            "longstaff_dlom has no dividend term (Longstaff 1995), and returning the other "
            "three alone would hide the missing one. Call chaffe_dlom, finnerty_dlom and "
            "ghaidarov_dlom individually if a yield is needed."
        )
    kwargs = {
        "volatility": volatility,
        "time": time,
        "risk_free_rate": risk_free_rate,
        "dividend_yield": dividend_yield,
    }
    return [
        chaffe_dlom(**kwargs),
        finnerty_dlom(**kwargs),
        longstaff_dlom(**kwargs),
        ghaidarov_dlom(**kwargs),
    ]
