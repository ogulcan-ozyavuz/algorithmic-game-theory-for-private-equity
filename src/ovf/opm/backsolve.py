"""Calibrate total equity value so the Option Pricing Method reproduces an observed price.

The backsolve method, as described in the AICPA Accounting and Valuation Guide *Valuation of
Privately-Held-Company Equity Securities Issued as Compensation*, takes the price per share
actually paid for one class in a recent arm's-length financing and finds the total equity
value at which the Option Pricing Method gives that class exactly that value per share. It
calibrates the model to a transaction instead of to a guessed enterprise value. The method is
implemented as described; no conformance with the guide, or with any 409A practice, is
claimed.

**The round's shares must already be in the cap table passed in.** The price was paid for
shares that exist only after the round closes, alongside the preference those shares carry.
Solving with the pre-round table is the common error, and it fails silently: every class
still has a price per share at every equity value, so the solve returns a plausible number
for a different company. A target ``security_id`` missing from the table is refused, but a
target that is present in a table missing some other part of the round cannot be detected.

The root identifies an equity value only if the target's value per share is strictly
increasing in total equity value, so that is checked, not assumed:

1. **Bracket.** Starting from the scale ``price_per_share x as-converted shares`` (the round's
   headline post-money, used only as a place to start), the search widens by a factor of
   ``EXPANSION_FACTOR`` on whichever side does not yet straddle the target, at most
   ``MAX_EXPANSIONS`` times. No straddle raises ``BacksolveError`` with the range searched
   and the prices found at its ends.
2. **Grid.** The price is evaluated on a geometric grid across the bracket, adjacent points a
   factor of at most ``GRID_RATIO`` apart. A step that moves the price by no more than
   ``FLAT_RTOL x price_per_share`` is flat; a step that lowers it by more is falling. A flat
   run whose price level contains the target raises ``BacksolveError``: the equity value is
   not identified, and the interval is reported. A falling step raises too.
3. **Brent** (``scipy.optimize.brentq``) on the stretch of the grid around the crossing on
   which every step rises; that stretch is ``bracket_low`` to ``bracket_high``, so
   ``monotone_verified`` is true of the bracket actually used. Flat stretches elsewhere are
   excluded from it and listed in the assumptions.
4. **At the root**, the price must still rise across ``root x (1 +/- ELASTICITY_STEP)``, and the
   elasticity of equity value to price there is reported.

**The breakpoint schedule is derived once and reused.** ``breakpoint_schedule`` reads the
table, ``as_of`` and the collective-conversion term, and never the assumed equity value, so
the schedule is the same at every point of the search; ``opm_allocate`` still replays the
engine at each equity value it is given. See docs/opm-backsolve.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from scipy.optimize import brentq  # type: ignore[import-untyped]  # scipy ships no stubs

from ovf.contracts.securities import CommonStock, PreferredStock, Security
from ovf.governance import CollectiveConversion
from ovf.opm.allocate import opm_allocate
from ovf.opm.breakpoints import breakpoint_schedule
from ovf.opm.types import (
    BacksolveError,
    BacksolveResult,
    BreakpointSchedule,
    OpmInputs,
    OpmResult,
)
from ovf.waterfall import validate_securities

__all__ = [
    "BRENT_RTOL",
    "ELASTICITY_STEP",
    "EXPANSION_FACTOR",
    "FLAT_RTOL",
    "GRID_RATIO",
    "MAX_EXPANSIONS",
    "RESIDUAL_RTOL",
    "backsolve",
]

# The bracket widens by this factor per step, on the side that does not yet straddle.
EXPANSION_FACTOR = 4.0
# At most this many widenings: 4**40 is about 1.2e24 either way from the starting scale.
MAX_EXPANSIONS = 40
# Adjacent grid points are at most this factor apart (2% of equity value).
GRID_RATIO = 1.02
# A grid step that moves value per share by no more than this fraction of the target price
# is flat. It is the allocation's own conservation tolerance: below it, the change is not
# distinguishable from the arithmetic.
FLAT_RTOL = 1e-9
# The price reproduced at the root must be within this fraction of the target.
RESIDUAL_RTOL = 1e-9
# Brent's relative tolerance on equity value.
BRENT_RTOL = 1e-13
BRENT_XTOL = 1e-9
BRENT_MAXITER = 200
# Relative half-width of the local check at the root.
ELASTICITY_STEP = 1e-4


def _money(amount: float) -> str:
    return f"{amount:,.2f}"


class _Pricer:
    """Value per share of one position as a function of equity value, with a cache.

    Every call reuses the one schedule, so each evaluation is a set of Black-Scholes calls
    and one engine replay rather than a fresh breakpoint derivation.
    """

    def __init__(
        self,
        securities: tuple[Security, ...],
        security_id: str,
        market: tuple[float, float, float, float],
        as_of: date | None,
        schedule: BreakpointSchedule,
        collective_conversion: CollectiveConversion | None,
    ) -> None:
        self.securities = securities
        self.security_id = security_id
        self.market = market
        self.as_of = as_of
        self.schedule = schedule
        self.collective_conversion = collective_conversion
        self.results: dict[float, OpmResult] = {}

    def result(self, equity_value: float) -> OpmResult:
        if equity_value not in self.results:
            volatility, time, rate, dividend_yield = self.market
            self.results[equity_value] = opm_allocate(
                self.securities,
                inputs=OpmInputs(
                    equity_value=equity_value,
                    volatility=volatility,
                    time_to_liquidity=time,
                    risk_free_rate=rate,
                    dividend_yield=dividend_yield,
                ),
                as_of=self.as_of,
                schedule=self.schedule,
                collective_conversion=self.collective_conversion,
            )
        return self.results[equity_value]

    def price(self, equity_value: float) -> float:
        for cv in self.result(equity_value).class_values:
            if cv.security_id == self.security_id:
                assert cv.value_per_share is not None  # the target holds shares
                return cv.value_per_share
        raise AssertionError(f"{self.security_id} missing from the allocation")


def _validate(
    securities: tuple[Security, ...],
    security_id: str,
    price_per_share: float,
    market: dict[str, float],
) -> Security:
    for name, value in {"price_per_share": price_per_share, **market}.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise BacksolveError(f"{name} must be a finite number, got {value!r}")
    if price_per_share <= 0.0:
        raise BacksolveError(
            f"price_per_share must be positive, got {price_per_share!r}; a transaction at no "
            "price identifies no equity value"
        )
    for name in ("volatility", "time_to_liquidity"):
        if market[name] <= 0.0:
            raise BacksolveError(f"{name} must be positive, got {market[name]!r}")
    target = next((s for s in securities if s.security_id == security_id), None)
    if target is None:
        raise BacksolveError(
            f"{security_id} is not a position in the table. The round's shares must already be "
            "in the cap table: add the financing being calibrated to, as issued, before "
            "backsolving. Solving with the pre-round table silently returns a plausible number "
            "for a different company."
        )
    if not isinstance(target, CommonStock | PreferredStock) or target.shares <= 0.0:
        raise BacksolveError(
            f"{security_id} holds no issued shares, so it has no price per share to calibrate to"
        )
    return target


def _as_converted_shares(securities: Sequence[Security]) -> float:
    total = 0.0
    for security in securities:
        if isinstance(security, CommonStock):
            total += security.shares
        elif isinstance(security, PreferredStock):
            total += security.converted_shares
    return total


def _grid(low: float, high: float) -> list[float]:
    steps = max(1, math.ceil(math.log(high / low) / math.log(GRID_RATIO)))
    ratio = high / low
    points = [low * ratio ** (i / steps) for i in range(steps + 1)]
    points[0], points[-1] = low, high
    return points


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Maximal runs of True in ``flags`` as (first step, one past the last step)."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    return runs


def backsolve(
    securities: Sequence[Security],
    *,
    security_id: str,
    price_per_share: float,
    volatility: float,
    time_to_liquidity: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    as_of: date | None = None,
    collective_conversion: CollectiveConversion | None = None,
) -> BacksolveResult:
    """Solve for the total equity value at which ``security_id`` is worth ``price_per_share``.

    ``securities`` must be the table **after** the financing: the round's own shares, with
    their preference, have to be in it. Solving with the pre-round table is the common error
    and returns a plausible number silently.

    ``price_per_share`` is per share of the target's own class, the price the round paid,
    compared with ``ClassValue.value_per_share``. Volatility, time to liquidity and the
    risk-free rate are required; there is no default for any of them. ``collective_conversion``
    is passed to the breakpoint derivation and the allocation, so a governed table is refused
    there rather than calibrated as if ungoverned.

    Raises ``BacksolveError`` when the inputs are invalid, the target is not a share-holding
    position of the table, no bracket straddles the price, the price lies on a flat stretch
    (the equity value is not identified), the price falls somewhere in the bracket, or Brent
    does not converge. A refusal from the breakpoint derivation or the allocation propagates
    unchanged. See the module docstring for the search and docs/opm-backsolve.md.
    """
    securities = tuple(securities)
    validate_securities(securities)
    market = {
        "volatility": volatility,
        "time_to_liquidity": time_to_liquidity,
        "risk_free_rate": risk_free_rate,
        "dividend_yield": dividend_yield,
    }
    _validate(securities, security_id, price_per_share, market)
    target = float(price_per_share)

    schedule = breakpoint_schedule(
        securities, as_of=as_of, collective_conversion=collective_conversion
    )
    pricer = _Pricer(
        securities,
        security_id,
        (float(volatility), float(time_to_liquidity), float(risk_free_rate), float(dividend_yield)),
        as_of,
        schedule,
        collective_conversion,
    )

    as_converted = _as_converted_shares(securities)
    start = target * as_converted
    low, high = start / 2.0, start * 2.0
    low_price, high_price = pricer.price(low), pricer.price(high)
    expansions = 0
    while not low_price < target < high_price:
        if expansions == MAX_EXPANSIONS:
            raise BacksolveError(
                f"No bracket: {security_id}'s value per share is {low_price:.6g} at an equity "
                f"value of {low:.6g} and {high_price:.6g} at {high:.6g}, after "
                f"{MAX_EXPANSIONS} widenings by a factor of {EXPANSION_FACTOR:g} from the "
                f"starting scale {_money(start)} ({target:g} x {as_converted:,.0f} as-converted "
                f"shares). The target {target:g} is not between them, so no equity value in "
                "that range reproduces the price."
            )
        if low_price >= target:
            low /= EXPANSION_FACTOR
            low_price = pricer.price(low)
        if high_price <= target:
            high *= EXPANSION_FACTOR
            high_price = pricer.price(high)
        expansions += 1

    points = _grid(low, high)
    prices = [pricer.price(x) for x in points]
    band = FLAT_RTOL * target
    steps = [b - a for a, b in zip(prices, prices[1:], strict=False)]
    for index, step in enumerate(steps):
        if step < -band:
            raise BacksolveError(
                f"{security_id}'s value per share falls as equity value rises: "
                f"{prices[index]:.9g} at {_money(points[index])}, then {prices[index + 1]:.9g} "
                f"at {_money(points[index + 1])}, a fall of {-step:.3g} beyond the "
                f"{band:.3g} flat band. The root need not be unique, so none is reported."
            )
    flat = [abs(step) <= band for step in steps]
    flat_runs = _runs(flat)
    for first, last in flat_runs:
        level_low = min(prices[first : last + 1])
        level_high = max(prices[first : last + 1])
        if level_low - band <= target <= level_high + band:
            raise BacksolveError(
                f"Equity value is not identified: {security_id}'s value per share stays "
                f"between {level_low:.9g} and {level_high:.9g} (within {band:.3g}) for every "
                f"equity value from at least {_money(points[first])} to "
                f"{_money(points[last])}, over {last - first + 1} grid points, and the target "
                f"{target:g} lies on that level. Every equity value in the interval reproduces "
                "the price. This is what happens when the target class sits inside a tranche "
                "in which it receives nothing, so its value does not move with equity value."
            )

    crossing = max(i for i, p in enumerate(prices) if p < target)
    first, last = crossing, crossing + 1
    while first > 0 and not flat[first - 1]:
        first -= 1
    while last < len(steps) and not flat[last]:
        last += 1
    bracket_low, bracket_high = points[first], points[last]

    root, info = brentq(
        lambda x: pricer.price(x) - target,
        bracket_low,
        bracket_high,
        xtol=BRENT_XTOL,
        rtol=BRENT_RTOL,
        maxiter=BRENT_MAXITER,
        full_output=True,
        disp=False,
    )
    root = float(root)
    if not info.converged:
        raise BacksolveError(
            f"Brent did not converge in {BRENT_MAXITER} iterations on "
            f"[{_money(bracket_low)}, {_money(bracket_high)}]: {info.flag}"
        )
    implied = pricer.price(root)
    residual = implied - target
    if abs(residual) > RESIDUAL_RTOL * target:
        raise BacksolveError(
            f"Brent stopped at an equity value of {_money(root)}, where {security_id} is worth "
            f"{implied:.9g} a share against the target {target:g}, a residual of "
            f"{residual:.3g} beyond {RESIDUAL_RTOL:g} of the price."
        )

    below = pricer.price(root * (1.0 - ELASTICITY_STEP))
    above = pricer.price(root * (1.0 + ELASTICITY_STEP))
    if above - below <= band:
        raise BacksolveError(
            f"Equity value is not identified at the root: {security_id}'s value per share "
            f"moves by only {above - below:.3g} between {_money(root * (1 - ELASTICITY_STEP))} "
            f"and {_money(root * (1 + ELASTICITY_STEP))}, within the {band:.3g} flat band."
        )
    elasticity = math.log((1 + ELASTICITY_STEP) / (1 - ELASTICITY_STEP)) / math.log(above / below)

    excluded = [
        f"{_money(points[a])} to {_money(points[b])}"
        for a, b in flat_runs
        if b <= first or a >= last
    ]
    assumptions = [
        "Backsolve method: total equity value calibrated so that the Option Pricing Method "
        "gives the target class the price paid in a financing (AICPA Accounting and Valuation "
        "Guide, Valuation of Privately-Held-Company Equity Securities Issued as Compensation). "
        "Implemented as described; no conformance with the guide or with any 409A practice is "
        "claimed.",
        f"The table passed in is taken to include the round: {security_id} and every other "
        "position the financing created are assumed present, as issued. A pre-round table "
        "would give a different, plausible number, and this cannot be detected.",
        f"Target: {security_id} at {target:g} a share, per share of its own class, treated as "
        "an arm's-length price for exactly the rights the engine models.",
        f"Market inputs as supplied: volatility {volatility:g}, {time_to_liquidity:g} years to "
        f"liquidity, risk-free rate {risk_free_rate:g}, dividend yield {dividend_yield:g}. "
        "The equity value found depends on each of them; see docs/opm-backsolve.md.",
        f"Breakpoint schedule derived once ({len(schedule.tranches)} tranches) and reused for "
        f"{len(pricer.results)} allocations: it depends on the table, as_of and any "
        "collective-conversion term, not on the equity value. Each allocation replays the "
        "engine at its own equity value.",
        f"Search: starting scale {_money(start)} = {target:g} x {as_converted:,.0f} "
        f"as-converted shares; {expansions} widening(s) by {EXPANSION_FACTOR:g} to "
        f"[{_money(low)}, {_money(high)}]; {len(points)} grid points at most {GRID_RATIO:g} "
        f"apart; every step in the bracket [{_money(bracket_low)}, {_money(bracket_high)}] "
        f"raises the price by more than {FLAT_RTOL:g} of the target.",
        f"Brent: {info.iterations} iterations, residual {residual:.3g} a share.",
        f"Conditioning at the root: a 1% error in the observed price moves the equity value "
        f"by about {elasticity:.3g}%.",
    ]
    if excluded:
        assumptions.append(
            "Flat stretches away from the target, excluded from the bracket: "
            + "; ".join(excluded)
            + "."
        )
    if collective_conversion is not None:
        assumptions.append(
            f"Collective-conversion term '{collective_conversion.name}' passed to the "
            "breakpoint derivation and the allocation."
        )

    return BacksolveResult(
        equity_value=root,
        target_security_id=security_id,
        target_price_per_share=target,
        implied_price_per_share=implied,
        residual=residual,
        iterations=info.iterations,
        bracket_low=bracket_low,
        bracket_high=bracket_high,
        monotone_verified=True,
        opm=pricer.result(root),
        assumptions=assumptions,
    )
