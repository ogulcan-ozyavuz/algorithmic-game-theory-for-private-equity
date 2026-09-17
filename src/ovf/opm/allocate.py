"""Allocate total equity value across positions by the Option Pricing Method.

The method, as set out in the AICPA Accounting and Valuation Guide *Valuation of
Privately-Held-Company Equity Securities Issued as Compensation*, treats total equity value
as lognormal at a liquidity date and each position as a portfolio of call spreads on it.
With breakpoints ``0 = k_0 < k_1 < ... < k_n`` and ``C(k)`` the Black-Scholes-Merton value of
a call on total equity value struck at ``k`` (``ovf.opm.blackscholes``), tranche ``t`` is
worth ``C(k_t) - C(k_{t+1})``, with ``C`` of the unbounded upper end equal to zero, and a
position taking share ``w_t`` of each marginal dollar in tranche ``t`` is worth
``sum_t w_t * (C(k_t) - C(k_{t+1}))``. The formula is implemented as published. No claim of
conformance with the guide, or with any 409A practice, is made.

That sum is an allocation only if every payoff is continuous, piecewise linear and
non-decreasing in total equity value, and the weights in each tranche are non-negative and
sum to one. Those are properties of a particular cap table, not of cap tables, so they are
checked here, in this order, and a failure is a refusal that says what failed, where and by
how much:

1. continuity: any recorded step in a payoff (``OpmAssumptionError``);
2. monotonicity: a weight below ``-NEGATIVE_WEIGHT_FLOOR``, or ``monotone=False``
   (``OpmAssumptionError``);
3. weight sums: off one by more than ``WEIGHT_SUM_TOLERANCE`` in any tranche
   (``OpmAssumptionError``);
4. linearity: a schedule never replayed against the engine (``BreakpointError``: a zero error
   that was never measured is not evidence), or one whose replay gap exceeds
   ``linearity_tolerance(equity_value)`` (``OpmAssumptionError``);
5. correspondence: the schedule must name exactly this table's positions, carry no other
   ``as_of``, and replay the engine at the equity value itself (``BreakpointError``).

There is no option to skip them. Derivations and fixtures: docs/opm.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from ovf.contracts.securities import Security, StockOptionPool
from ovf.governance import (
    CollectiveConversion,
    GovernanceIndeterminateError,
    resolve_collective_conversion,
)
from ovf.opm.blackscholes import call_value
from ovf.opm.types import (
    BreakpointError,
    BreakpointSchedule,
    ClassValue,
    OpmAssumptionError,
    OpmError,
    OpmInputs,
    OpmResult,
    Tranche,
)
from ovf.waterfall import solve_waterfall, validate_securities

__all__ = [
    "CONSERVATION_RTOL",
    "LINEARITY_ATOL",
    "LINEARITY_RTOL",
    "NEGATIVE_WEIGHT_FLOOR",
    "OPTION_VALUE_NOISE_RTOL",
    "WEIGHT_SUM_TOLERANCE",
    "linearity_tolerance",
    "opm_allocate",
]

# A weight below minus this refuses. A negative weight produced by a vote is of order 0.1 to 1,
# so the floor separates the real case from float noise by about eleven orders of magnitude.
NEGATIVE_WEIGHT_FLOOR = 1e-12
# abs(fsum(weights) - 1) above this, in any tranche, refuses.
WEIGHT_SUM_TOLERANCE = 1e-9
# The replay gap stood behind is max(LINEARITY_ATOL, LINEARITY_RTOL * equity_value).
LINEARITY_ATOL = 1e-6
LINEARITY_RTOL = 1e-9
# sum(class values) must equal equity_value * exp(-q*T) to this relative error.
CONSERVATION_RTOL = 1e-9
# A tranche value C(k_t) - C(k_{t+1}) below zero is float noise if within this fraction of the
# equity value, and is snapped to zero with its size added to conservation_error. Below it,
# the call routine is wrong and the allocation raises.
OPTION_VALUE_NOISE_RTOL = 1e-12


def linearity_tolerance(equity_value: float) -> float:
    """The largest schedule replay gap this allocation stands behind, in currency units.

    A schedule whose payoff is within ``eps`` of the engine's at every probed exit moves a
    position's value by at most ``exp(-r*T) * eps`` over that range, so this bounds the
    valuation error at one part in 10**9 of equity value. It never asks for less than the
    1e-6 at which a schedule is replayed by default.
    """
    return max(LINEARITY_ATOL, LINEARITY_RTOL * equity_value)


def _money(amount: float) -> str:
    return f"{amount:,.2f}"


def _gap(amount: float) -> str:
    """A discrepancy: to the cent when it is a dollar or more, else in significant figures."""
    return _money(amount) if abs(amount) >= 1.0 else f"{amount:.3g}"


def _tranche_label(index: int, tranche: Tranche) -> str:
    upper = "unbounded" if tranche.upper is None else _money(tranche.upper)
    return f"tranches[{index}] = [{_money(tranche.lower)}, {upper})"


def _check_continuity(schedule: BreakpointSchedule) -> None:
    if schedule.continuous:
        return
    step = max(schedule.discontinuities, key=lambda d: d.size)
    security_id, jump = max(
        step.jumps.items(), key=lambda item: abs(item[1]), default=("no position", 0.0)
    )
    raise OpmAssumptionError(
        f"Payoff is not continuous: the schedule records {len(schedule.discontinuities)} "
        f"step(s), the largest at an exit of {_money(step.value)}, where {security_id}'s cash "
        f"jumps by {jump:+,.2f} ({step.basis}). A call spread is continuous, so no combination "
        "of call spreads, in any weights, reproduces a step, and the Option Pricing Method "
        "cannot value this table."
    )


def _check_monotone(schedule: BreakpointSchedule) -> None:
    negatives = [
        (weight, security_id, index, tranche)
        for index, tranche in enumerate(schedule.tranches)
        for security_id, weight in tranche.weights.items()
        if weight < -NEGATIVE_WEIGHT_FLOOR
    ]
    if negatives:
        weight, security_id, index, tranche = min(negatives, key=lambda item: item[0])
        others = f", and {len(negatives) - 1} more below the floor" if len(negatives) > 1 else ""
        raise OpmAssumptionError(
            f"Payoff is not non-decreasing: {security_id}'s share of each marginal dollar in "
            f"{_tranche_label(index, tranche)} is {weight:.6g}, below the floor of "
            f"-{NEGATIVE_WEIGHT_FLOOR:g}{others} (schedule monotone={schedule.monotone}). "
            "A negative weight makes that position short a call spread, a claim the other "
            "positions fund rather than a share of equity value, so the call-spread "
            "decomposition stops being an allocation."
        )
    if not schedule.monotone:
        raise OpmAssumptionError(
            "Payoff is not non-decreasing: the schedule reports monotone=False although no "
            f"tranche weight is below -{NEGATIVE_WEIGHT_FLOOR:g}. The flag is the schedule's "
            "own finding about the engine and is taken over the weights: some position's cash "
            "falls as the exit rises, which a sum of long call spreads cannot represent."
        )


def _check_weight_sums(schedule: BreakpointSchedule) -> float:
    """Refuse a tranche that does not share out its marginal dollar exactly once."""
    sums = [math.fsum(tranche.weights.values()) for tranche in schedule.tranches]
    errors = [abs(total - 1.0) for total in sums]
    index = max(range(len(errors)), key=errors.__getitem__)
    if errors[index] > WEIGHT_SUM_TOLERANCE:
        raise OpmAssumptionError(
            f"Weights do not sum to one: in {_tranche_label(index, schedule.tranches[index])} "
            f"they sum to {sums[index]:.15g}, off by {errors[index]:.3g}, above the tolerance "
            f"of {WEIGHT_SUM_TOLERANCE:g}. Each marginal dollar must be shared out exactly "
            "once; otherwise the tranche values create or destroy equity value."
        )
    reported = max(
        [schedule.max_weight_sum_error, *(t.weight_sum_error for t in schedule.tranches)]
    )
    if reported > WEIGHT_SUM_TOLERANCE:
        raise OpmAssumptionError(
            f"Weights do not sum to one by the schedule's own measurement: it reports a "
            f"weight-sum error of {reported:.3g}, above the tolerance of "
            f"{WEIGHT_SUM_TOLERANCE:g}, although the stored weights are within "
            f"{errors[index]:.3g}. The two disagree, and neither is preferred over the other."
        )
    return errors[index]


def _check_linearity(schedule: BreakpointSchedule, tolerance: float, equity_value: float) -> None:
    if schedule.linearity_samples == 0:
        raise BreakpointError(
            "Schedule was never replayed against the waterfall engine (linearity_samples = 0), "
            f"so its max_linearity_error of {schedule.max_linearity_error:g} is not evidence: "
            "a zero error that was never measured says nothing about whether the payoff is "
            "piecewise linear on these breakpoints."
        )
    if schedule.max_linearity_error > tolerance:
        raise OpmAssumptionError(
            "Payoff is not piecewise linear on these breakpoints to tolerance: the schedule's "
            f"replay differs from the engine by up to {_gap(schedule.max_linearity_error)} over "
            f"{schedule.linearity_samples} probed exits, above the {tolerance:,.6g} this "
            f"allocation stands behind (max({LINEARITY_ATOL:g}, {LINEARITY_RTOL:g} x equity "
            f"value {_money(equity_value)})). Each position's value could be wrong by up to "
            "exp(-rT) times that gap."
        )


def _check_correspondence(
    securities: Sequence[Security], schedule: BreakpointSchedule, as_of: date | None
) -> None:
    table_ids = [s.security_id for s in securities]
    listed = set(schedule.security_ids)
    problems: list[str] = []
    missing = [i for i in table_ids if i not in listed]
    if missing:
        problems.append(f"in the table but not the schedule: {', '.join(missing)}")
    extra = sorted(listed - set(table_ids))
    if extra:
        problems.append(f"in the schedule but not the table: {', '.join(extra)}")
    unlisted = sorted({i for t in schedule.tranches for i in t.weights} - listed)
    if unlisted:
        problems.append(f"weighted in a tranche but not listed: {', '.join(unlisted)}")
    if problems:
        raise BreakpointError(
            "Schedule does not describe this table; positions " + "; ".join(problems) + "."
        )
    if schedule.as_of is not None and as_of is not None and schedule.as_of != as_of:
        raise BreakpointError(
            f"Schedule was derived as of {schedule.as_of.isoformat()} but the allocation is as "
            f"of {as_of.isoformat()}; accruing terms make those different tables."
        )


def _engine_payouts(
    securities: Sequence[Security],
    exit_value: float,
    as_of: date | None,
    collective_conversion: CollectiveConversion | None,
) -> tuple[dict[str, float], str]:
    """Cash at one exit from the engine that defines this table's payoff, and its name.

    A governed table's payoff is a different function from the ungoverned one, so under a
    collective-conversion term the oracle is ``resolve_collective_conversion``.
    """
    if collective_conversion is None:
        result = solve_waterfall(securities, exit_value, as_of=as_of)
        oracle = "solve_waterfall"
    else:
        result = resolve_collective_conversion(
            securities, exit_value, term=collective_conversion, as_of=as_of
        ).result
        oracle = f"resolve_collective_conversion under '{collective_conversion.name}'"
    return {p.security_id: p.amount for p in result.payouts}, oracle


_INDETERMINATE_PROBE_OFFSET = 1e-9
"""Relative step used when the engine is undefined at exactly the equity value.

Small enough that no breakpoint of a table this engine can schedule separates the two, and
large enough to leave the tie, which is a single point.
"""


def _spot_check(
    securities: Sequence[Security],
    schedule: BreakpointSchedule,
    equity_value: float,
    tolerance: float,
    as_of: date | None,
    collective_conversion: CollectiveConversion | None,
) -> tuple[float, str]:
    """Replay the schedule at the equity value against the engine; refuse a gap.

    The engine can be undefined at exactly this exit and nowhere near it. Under a
    collective-conversion term a pivotal holder can be indifferent at a single exit, and
    `ovf.governance` refuses there rather than calling a tied vote. That says nothing about
    whether the table can be priced: the point has measure zero under the lognormal, the
    schedule either side of it is one line, and the neighbouring exits allocate normally.
    So an indeterminate probe is retried a hair away rather than allowed to fail the
    allocation, and the substitution is recorded in the returned oracle description so it
    reaches `OpmResult.assumptions` instead of being silent. Found by the validation
    worker, which hit it on a table whose schedule is continuous and monotone.
    """
    try:
        engine, oracle = _engine_payouts(securities, equity_value, as_of, collective_conversion)
    except GovernanceIndeterminateError as undefined:
        probe = equity_value * (1.0 + _INDETERMINATE_PROBE_OFFSET)
        try:
            engine, oracle = _engine_payouts(securities, probe, as_of, collective_conversion)
        except GovernanceIndeterminateError:
            raise OpmAssumptionError(
                f"The engine is indeterminate at an exit of {_money(equity_value)} and again "
                f"at {_money(probe)}, so the schedule cannot be checked against it here: "
                f"{undefined}"
            ) from undefined
        replay = schedule.payout(probe)
        gaps = {i: abs(replay.get(i, 0.0) - amount) for i, amount in engine.items()}
        worst = max(gaps, key=gaps.__getitem__)
        oracle = (
            f"{oracle} at {probe:,.6f} rather than at the equity value {equity_value:,.2f} "
            f"(a relative {_INDETERMINATE_PROBE_OFFSET:g} above it), because the vote is "
            f"exactly tied at the equity value and the engine refuses to call it there"
        )
        if gaps[worst] > tolerance:
            raise BreakpointError(
                f"Schedule does not replay this table beside the equity value: at an exit of "
                f"{_money(probe)} it pays {worst} {_money(replay.get(worst, 0.0))}, but "
                f"{oracle} pays {_money(engine[worst])}, a gap of {_gap(gaps[worst])} above "
                f"the tolerance of {tolerance:,.6g}."
            ) from undefined
        return gaps[worst], oracle
    replay = schedule.payout(equity_value)
    gaps = {i: abs(replay.get(i, 0.0) - amount) for i, amount in engine.items()}
    worst = max(gaps, key=gaps.__getitem__)
    if gaps[worst] > tolerance:
        raise BreakpointError(
            f"Schedule does not replay this table at the equity value: at an exit of "
            f"{_money(equity_value)} it pays {worst} {_money(replay.get(worst, 0.0))}, but "
            f"{oracle} pays {_money(engine[worst])}, a gap of {_gap(gaps[worst])} above the "
            f"tolerance of {tolerance:,.6g}. It describes a different table, date or "
            "collective-conversion term."
        )
    return gaps[worst], oracle


def _issued_shares(security: Security) -> float:
    """Shares the position holds; an option reserve holds only its allocated options."""
    if isinstance(security, StockOptionPool):
        return security.allocated_shares
    return security.shares


def opm_allocate(
    securities: Sequence[Security],
    *,
    inputs: OpmInputs,
    as_of: date | None = None,
    schedule: BreakpointSchedule | None = None,
    collective_conversion: CollectiveConversion | None = None,
    atol: float | None = None,
) -> OpmResult:
    """Value each position as its weighted call spreads on total equity value, or refuse.

    ``atol`` is forwarded to the breakpoint construction when this call derives the
    schedule, and is ignored when ``schedule`` is supplied. It is an ABSOLUTE tolerance:
    leave it alone unless the table's breakpoints run to roughly 1e10 or beyond, where the
    default refuses a table that is otherwise fine.

    ``schedule`` defaults to ``breakpoint_schedule(securities, as_of=as_of,
    collective_conversion=collective_conversion)``, the breakpoints derived from the waterfall
    engine. A schedule supplied by the caller passes the same checks as a derived one,
    including a replay against the engine at ``inputs.equity_value``; see the module
    docstring for the order and the tolerances.

    Raises ``OpmAssumptionError`` when the table breaks a property the arithmetic needs,
    ``BreakpointError`` when the schedule is unverified or belongs to another table, and
    ``OpmError`` when the numbers themselves fail conservation.
    """
    securities = tuple(securities)
    validate_securities(securities)
    derived = schedule is None
    if schedule is None:
        # Imported here so that allocating against a supplied schedule does not depend on
        # the breakpoint derivation module.
        from ovf.opm.breakpoints import breakpoint_schedule

        # `atol` in the breakpoint construction is ABSOLUTE, so a table whose breakpoints
        # run to 1e10 is refused on the default tolerance even though nothing is wrong with
        # it. Reported by the validation worker. Passing it through is the honest fix: the
        # caller who knows their table is denominated in units this large can say so, and a
        # caller who does not is left exactly where they were. Choosing a scaled default
        # here instead would quietly change what every existing table is verified against.
        kwargs = {} if atol is None else {"atol": atol}
        schedule = breakpoint_schedule(
            securities, as_of=as_of, collective_conversion=collective_conversion, **kwargs
        )

    equity_value = inputs.equity_value
    tolerance = linearity_tolerance(equity_value)
    _check_continuity(schedule)
    _check_monotone(schedule)
    weight_sum_error = _check_weight_sums(schedule)
    _check_linearity(schedule, tolerance, equity_value)
    _check_correspondence(securities, schedule, as_of)
    spot_gap, oracle = _spot_check(
        securities, schedule, equity_value, tolerance, as_of, collective_conversion
    )

    market = (
        inputs.volatility,
        inputs.time_to_liquidity,
        inputs.risk_free_rate,
        inputs.dividend_yield,
    )
    calls = [call_value(equity_value, t.lower, *market) for t in schedule.tranches]
    calls.append(0.0)  # C of the unbounded upper end
    target = calls[0]  # C(0) = equity_value * exp(-q*T), taken exactly
    if not target > 0.0:
        raise OpmError(
            f"Discounted equity value {equity_value:g} x exp(-{inputs.dividend_yield:g} x "
            f"{inputs.time_to_liquidity:g}) underflows to zero; there is nothing to allocate"
        )

    noise_floor = OPTION_VALUE_NOISE_RTOL * equity_value
    snapped = 0.0
    tranche_values: list[float] = []
    for index, tranche in enumerate(schedule.tranches):
        option_value = calls[index] - calls[index + 1]
        if option_value < 0.0:
            if option_value < -noise_floor:
                raise OpmError(
                    f"Call value rises with the strike across {_tranche_label(index, tranche)}: "
                    f"C(lower) - C(upper) = {option_value:.6g}, beyond the float-noise floor "
                    f"of {noise_floor:.3g}. A call is non-increasing in its strike, so this is "
                    "a failure of the call routine, not of the table."
                )
            snapped -= option_value
            option_value = 0.0
        tranche_values.append(option_value)

    positions: list[tuple[Security, list[float], float]] = []
    for security in securities:
        parts: list[float] = []
        for tranche, option_value in zip(schedule.tranches, tranche_values, strict=True):
            part = tranche.weights.get(security.security_id, 0.0) * option_value
            if part < 0.0:  # only a weight inside the floor, in [-1e-12, 0)
                snapped -= part
                part = 0.0
            parts.append(part)
        positions.append((security, parts, math.fsum(parts)))

    total = math.fsum(value for _, _, value in positions)
    conservation_error = abs(total - target) + snapped
    if conservation_error > CONSERVATION_RTOL * target:
        raise OpmError(
            f"Value is not conserved: positions sum to {_money(total)} against a discounted "
            f"equity value of {_money(target)}, an error of {conservation_error:.6g} (including "
            f"{snapped:.3g} of snapped float noise), above the relative tolerance of "
            f"{CONSERVATION_RTOL:g}."
        )

    class_values = []
    for security, parts, value in positions:
        shares = _issued_shares(security)
        class_values.append(
            ClassValue(
                security_id=security.security_id,
                holder_id=security.holder_id,
                value=value,
                shares=shares,
                value_per_share=value / shares if shares > 0 else None,
                pct_of_equity=value / total,
                tranche_values=parts,
            )
        )

    assumptions = [
        "Option Pricing Method: total equity value is lognormal at the liquidity date and each "
        "position is a portfolio of call spreads between breakpoints (AICPA Accounting and "
        "Valuation Guide, Valuation of Privately-Held-Company Equity Securities Issued as "
        "Compensation). The formula is implemented as published; no conformance with the "
        "guide or with any 409A practice is claimed.",
        f"Black-Scholes-Merton calls on an equity value of {_money(equity_value)} with "
        f"volatility {inputs.volatility:g}, {inputs.time_to_liquidity:g} years to liquidity, "
        f"risk-free rate {inputs.risk_free_rate:g} and dividend yield "
        f"{inputs.dividend_yield:g}, continuously compounded, as supplied by the caller.",
        "Breakpoints derived from the waterfall engine by ovf.opm.breakpoints."
        if derived
        else "Breakpoints supplied by the caller; checked here, not derived here.",
        f"Checked: continuous; no weight below -{NEGATIVE_WEIGHT_FLOOR:g}; weight sums within "
        f"{WEIGHT_SUM_TOLERANCE:g} (largest measured {weight_sum_error:.3g}); replay gap "
        f"{schedule.max_linearity_error:.3g} over {schedule.linearity_samples} probed exits and "
        f"{spot_gap:.3g} against {oracle}, both within {tolerance:.6g}.",
        "pct_of_equity is a share of the total allocated, which is equity value x exp(-q*T). "
        "value_per_share is per share of the position's own class, a preferred share rather "
        "than its as-converted common; an unallocated option reserve holds no issued shares.",
        "No discount for lack of marketability is applied.",
    ]
    if collective_conversion is not None:
        assumptions.append(
            f"Collective-conversion term '{collective_conversion.name}' passed to the "
            "breakpoint derivation and used as the engine for the replay check."
        )
    if snapped:
        assumptions.append(
            f"Float noise of {snapped:.3g} in total, from option-value differences below zero "
            "or weights inside the negative floor, was set to zero and is included in "
            "conservation_error."
        )

    return OpmResult(
        inputs=inputs,
        class_values=class_values,
        tranche_option_values=tranche_values,
        total_allocated=total,
        conservation_error=conservation_error,
        schedule=schedule,
        assumptions=assumptions,
    )
