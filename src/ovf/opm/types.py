"""Shared result types for the Option Pricing Method.

This module is the interface contract between the breakpoint derivation, the
option-value allocation, the backsolve calibration and the marketability
discounts. It is owned by the coordinator and holds no logic beyond validation
and replay, so that each of those can be written against a fixed shape.

The Option Pricing Method treats total equity value as a random variable and
each share class's claim on it as a portfolio of call spreads. That
decomposition is only arithmetic if every class's payoff, read as a function of
total equity value, is continuous, piecewise linear, non-decreasing, and shares
each marginal dollar with the other classes in weights that sum to one. Those
four properties are assumptions about a particular cap table, not facts about
cap tables, and `ovf.governance` already produced tables that break the third.
Every type here therefore carries the measured error of the property it relies
on, so a caller can see how far the arithmetic was from the thing it assumed.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ovf.core.types import FinancialBaseModel, Money, Percentage, ShareCount, SharePrice

__all__ = [
    "BacksolveResult",
    "BacksolveError",
    "Breakpoint",
    "BreakpointError",
    "BreakpointKind",
    "BreakpointSchedule",
    "ClassValue",
    "Discontinuity",
    "DlomEstimate",
    "DlomMethod",
    "OpmAssumptionError",
    "OpmError",
    "OpmInputs",
    "OpmResult",
    "Rate",
    "Tranche",
]

Rate = Annotated[
    float,
    Field(
        description=(
            "A continuously compounded annual rate. Unlike the money types this may be "
            "negative: euro and yen risk-free curves have been, and clamping one at zero "
            "would silently change the input."
        )
    ),
]

Discount = Annotated[
    float,
    Field(
        ge=0.0,
        description=(
            "A proportional discount. Deliberately NOT bounded above at 1.0: Longstaff's "
            "lookback bound exceeds 100% for large volatility-time, and that is the "
            "result, not an error to clamp away. A value at or above 1.0 is a signal "
            "that the estimator has left the range where it means anything."
        ),
    ),
]


class OpmError(ValueError):
    """Base for every refusal in `ovf.opm`."""


class OpmAssumptionError(OpmError):
    """The cap table breaks a property the Option Pricing Method's arithmetic needs.

    Raised rather than returning a number, because the number would be arithmetically
    well-formed and financially meaningless. The message states which property failed,
    at which exit value, and by how much.
    """


class BreakpointError(OpmError):
    """The breakpoint schedule could not be derived or could not be verified."""


class BacksolveError(OpmError):
    """No unique total equity value reproduces the observed transaction price."""


BreakpointKind = Literal[
    "origin",
    "debt_repaid",
    "preference",
    "conversion",
    "participation_cap",
    "forced_conversion",
    "other",
]

DlomMethod = Literal["chaffe", "finnerty", "longstaff", "ghaidarov"]


class Breakpoint(FinancialBaseModel):
    """One exit value at which the marginal split of a dollar changes."""

    value: Money
    kind: BreakpointKind
    basis: str = Field(description="Why this is a breakpoint, in words, for a reader")
    exact: bool = Field(
        description=(
            "True when the value came from closed-form rational arithmetic, False when it "
            "was located numerically. A numerically located breakpoint is still verified, "
            "but its position carries solver tolerance."
        )
    )


class Tranche(FinancialBaseModel):
    """A half-open interval of exit value over which every class's share is constant."""

    lower: Money
    upper: Money | None = Field(
        default=None, description="Exclusive upper end; None is the unbounded final tranche"
    )
    weights: dict[str, float] = Field(
        description=(
            "security_id -> share of each marginal dollar inside this tranche. Deliberately "
            "NOT bounded to [0, 1]: a weight outside it is exactly the diagnosis this module "
            "exists to report. A negative weight means a class loses cash as the exit rises, "
            "which is what a forced-conversion vote can do and what makes the call-spread "
            "decomposition invalid. Validation must not hide it."
        )
    )
    basis: str
    weight_sum_error: float = Field(
        ge=0.0, description="abs(sum(weights) - 1.0) as measured, not as assumed"
    )

    @model_validator(mode="after")
    def _ordered(self) -> Tranche:
        if self.upper is not None and self.upper <= self.lower:
            raise ValueError(f"tranche upper {self.upper} must exceed lower {self.lower}")
        return self


class Discontinuity(FinancialBaseModel):
    """An exit value at which a class's cash jumps rather than bending.

    A collective-conversion vote does this. Below the flip the vote fails and a
    dissenting series keeps its preference; above it the vote carries and that series
    is converted, losing the preference outright. The payoff therefore steps, and the
    step is the whole reason the Option Pricing Method cannot price such a table: a
    call spread is continuous, so no combination of them - in any weights, positive or
    negative - reproduces a step. The decomposition is not merely ill-conditioned
    here, the function is not in its span.

    Recorded as a first-class fact rather than smeared into a narrow steep tranche.
    A smeared window would let `payout` replay to within tolerance while making the
    weights an artifact of the window width, which is exactly the kind of number that
    looks right and is not.
    """

    value: Money
    jumps: dict[str, float] = Field(
        description=(
            "security_id -> right limit minus left limit, signed. A negative entry is a "
            "class whose cash falls as the company sells for more."
        )
    )
    basis: str
    exact: bool

    @property
    def size(self) -> float:
        """The largest absolute jump at this exit value."""
        return max((abs(j) for j in self.jumps.values()), default=0.0)


class BreakpointSchedule(FinancialBaseModel):
    """The piecewise-linear payoff map, derived from the engine and then verified."""

    breakpoints: list[Breakpoint]
    tranches: list[Tranche]
    security_ids: list[str]
    discontinuities: list[Discontinuity] = Field(
        default_factory=list,
        description=(
            "Exit values at which the payoff steps. Empty for every table without a "
            "collective-conversion term. A non-empty list makes the Option Pricing Method "
            "inapplicable outright, which is a stronger refusal than non-monotonicity."
        ),
    )
    monotone: bool = Field(
        description=(
            "True when no class's payoff decreases as the exit rises. False makes the "
            "Option Pricing Method inapplicable; it is reported rather than hidden so a "
            "caller can see the reason for the refusal."
        )
    )
    continuous: bool = Field(
        default=True,
        description="False when `discontinuities` is non-empty; kept explicit for readers",
    )
    max_weight_sum_error: float = Field(ge=0.0)
    max_linearity_error: float = Field(
        ge=0.0,
        description="Largest gap between this schedule's replay and the engine, over all probes",
    )
    linearity_samples: int = Field(ge=0, description="How many exit values were probed")
    as_of: date | None = None
    assumptions: list[str]
    engine_version: str = "opm-breakpoints-v1"

    @model_validator(mode="after")
    def _continuity_flag_matches(self) -> BreakpointSchedule:
        if self.continuous != (not self.discontinuities):
            raise ValueError(
                "continuous must be False exactly when discontinuities is non-empty; "
                f"got continuous={self.continuous} with {len(self.discontinuities)} recorded"
            )
        return self

    @model_validator(mode="after")
    def _contiguous(self) -> BreakpointSchedule:
        if not self.tranches:
            raise ValueError("a schedule needs at least one tranche")
        if self.tranches[0].lower != 0.0:
            raise ValueError("the first tranche must start at an exit of zero")
        for lower, upper in zip(self.tranches, self.tranches[1:], strict=False):
            if lower.upper != upper.lower:
                raise ValueError(
                    f"tranches must tile the line without gaps: {lower.upper} then {upper.lower}"
                )
        if self.tranches[-1].upper is not None:
            raise ValueError("the final tranche must be unbounded above")
        return self

    def tranche_at(self, exit_valuation: float) -> Tranche:
        """The tranche containing `exit_valuation`, treating each as [lower, upper)."""
        if exit_valuation < 0.0:
            raise ValueError(f"exit valuation must not be negative: {exit_valuation}")
        edges = [t.lower for t in self.tranches]
        return self.tranches[max(0, bisect_right(edges, exit_valuation) - 1)]

    def weights_at(self, exit_valuation: float) -> dict[str, float]:
        """Each class's share of the next marginal dollar at this exit value."""
        return dict(self.tranche_at(exit_valuation).weights)

    def payout(self, exit_valuation: float) -> dict[str, float]:
        """Replay the piecewise-linear map: integrate the tranche weights up to the exit.

        This is the schedule's own answer, not the engine's. `max_linearity_error`
        records how far the two were from each other over the probed range, which is
        the only reason to trust this method.

        Any recorded discontinuity at or below `exit_valuation` is added in full. That
        is the right-continuous convention, and it is a convention rather than a fact:
        at the step itself the vote is tied and `ovf.governance` refuses to call it, so
        the payoff there is undefined and this method reports the limit from above.
        """
        if exit_valuation < 0.0:
            raise ValueError(f"exit valuation must not be negative: {exit_valuation}")
        totals = dict.fromkeys(self.security_ids, 0.0)
        for tranche in self.tranches:
            if exit_valuation <= tranche.lower:
                break
            upper = exit_valuation if tranche.upper is None else min(tranche.upper, exit_valuation)
            width = upper - tranche.lower
            if width <= 0.0:
                continue
            for security_id, weight in tranche.weights.items():
                totals[security_id] = totals.get(security_id, 0.0) + weight * width
        for step in self.discontinuities:
            if step.value <= exit_valuation:
                for security_id, jump in step.jumps.items():
                    totals[security_id] = totals.get(security_id, 0.0) + jump
        return totals


class OpmInputs(FinancialBaseModel):
    """The four market assumptions, none of them defaulted except a zero dividend yield."""

    equity_value: Money = Field(gt=0.0, description="Total equity value being allocated")
    volatility: float = Field(
        gt=0.0, description="Annualized volatility of total equity value, as a decimal"
    )
    time_to_liquidity: float = Field(gt=0.0, description="Years to the assumed liquidity event")
    risk_free_rate: Rate
    dividend_yield: Rate = Field(
        default=0.0, description="Continuous yield leaking out of equity value before the exit"
    )


class ClassValue(FinancialBaseModel):
    """What the Option Pricing Method allocates to one position."""

    security_id: str
    holder_id: str
    value: Money
    shares: ShareCount
    value_per_share: SharePrice | None = Field(
        default=None, description="None when the position holds no shares, e.g. an unissued pool"
    )
    pct_of_equity: Percentage
    tranche_values: list[Money] = Field(
        description="This position's share of each tranche's option value, aligned with the schedule"
    )


class OpmResult(FinancialBaseModel):
    inputs: OpmInputs
    class_values: list[ClassValue]
    tranche_option_values: list[Money] = Field(
        description="C(lower) - C(upper) per tranche, before any class weighting"
    )
    total_allocated: Money
    conservation_error: float = Field(
        ge=0.0,
        description=(
            "abs(sum of class values - equity_value * exp(-q*T)). The call struck at zero "
            "is the whole discounted equity value, so the tranches must exhaust it."
        ),
    )
    schedule: BreakpointSchedule
    assumptions: list[str]
    engine_version: str = "opm-v1"


class BacksolveResult(FinancialBaseModel):
    """A total equity value calibrated so the model reproduces an observed price."""

    equity_value: Money
    target_security_id: str
    target_price_per_share: SharePrice
    implied_price_per_share: SharePrice
    residual: float = Field(description="implied minus target, signed, in price per share")
    iterations: int = Field(ge=0)
    bracket_low: Money
    bracket_high: Money
    monotone_verified: bool = Field(
        description=(
            "True when the target's value was checked to be strictly increasing in total "
            "equity value across the bracket, which is what makes the root unique."
        )
    )
    opm: OpmResult
    assumptions: list[str]
    engine_version: str = "opm-backsolve-v1"


class DlomEstimate(FinancialBaseModel):
    """One published marketability discount, reported on its own terms.

    There is no combined or default discount here, and no averaging across methods.
    The methods disagree with each other by more than most inputs move any one of
    them, so a single blended number would conceal the only thing the comparison
    reliably shows.
    """

    method: DlomMethod
    discount: Discount
    volatility: float = Field(gt=0.0)
    time: float = Field(gt=0.0, description="Holding period in years")
    risk_free_rate: Rate
    dividend_yield: Rate = 0.0
    formula: str = Field(description="The formula actually evaluated, in words")
    source: str = Field(description="The publication this formula comes from")
    assumptions: list[str]
    caveats: list[str] = Field(
        description="What this estimator measures that a marketability discount is not"
    )
    engine_version: str = "opm-dlom-v1"
