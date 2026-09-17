"""Modified PME (mPME): a labelled reconstruction of Cambridge Associates' method.

The mPME invests every capital call in a benchmark index and sells, on each
distribution date, the same fraction of the index position as the fund distributes of
its own value. Its benchmark therefore never goes short, which is its purpose: Cambridge
Associates say it avoids "the 'negative NAV' issue inherent in some PME methodologies".

**What this is and is not.** Cambridge Associates describe the method only in prose: the
index shares "are purchased and sold according to the private fund cash flow schedule,
with distributions calculated in the same proportion as the private fund" (US Private
Equity Benchmark Book, methodology page; ``docs/pme-sources.md`` S6.2). No CA document with
the algebra was found (S6.1). The algebra here follows Gredil, Griffiths & Stucke (2014,
SSRN working paper) eq. (9), with their NAV recursion (eq. (11)) read with the period
index throughout. As printed, eq. (11) mixes the period and terminal indices (S6.3), so
it is not cited as the recursion. The algebra also matches the secondary statement S6.5.
It is a reconstruction. It does not claim to reproduce Cambridge Associates' figures:
their dating conventions (which NAV, any quarterly aggregation) are not published, so
vendor figures may differ. "mPME" is CA's label; no equivalence is claimed.

**Recursion** (contract §12). ``T = as_of``, ``I_t`` the index level used for date ``t``,
``C_t`` and ``D_t`` the date's *gross* contributions and distributions, ``NAV_t`` the
fund's end-of-day NAV on ``t`` (after every flow on ``t``, contract §3). On every flow date
and at ``as_of``, in order (grow, invest the call, then sell the fund's fraction)::

    X_t        = NAV_mPME,prev * (I_t / I_prev) + C_t          (NAV_mPME starts at 0)
    w_t        = D_t / (D_t + NAV_t)   if D_t > 0, else 0
    Dist_mPME,t = w_t * X_t
    NAV_mPME,t  = (NAV_t / (D_t + NAV_t)) * X_t                  (so w_t = 1 gives exactly 0)

``D_t + NAV_t`` is the fund's value after the day's call and before its distribution, so
``w_t`` is the fraction of the fund paid out on ``t``. A same-day recall is not netted: it
is invested and then sold. The mPME IRR solves ``{-C_t, +Dist_mPME,t, +NAV_mPME,T at T}``,
netted per date, with ``ovf.pme.irr.xirr``. It is compared with the fund IRR.

**Fund NAV at a distribution date** ``t``: the ``FundNavHistory`` observation dated ``t``.
Otherwise, under ``interim_nav="roll_forward_cash_adjusted"``, the latest observation
``s < t`` with ``(t - s).days <= max_nav_gap_days`` is rolled forward as
``NAV_s + C_(s,t] - D_(s,t]``, with zero return assumed and the distribution on ``t``
included. A negative rolled value, a missing earlier observation or a gap beyond the
limit is refused with ``ValueError`` naming ``t``. Under ``"refuse"`` a missing observation
is refused. At ``as_of`` the NAV is the one residual value every PME uses,
``resolved.residual_value``. It is reported at ``as_of`` or rolled by ``resolve`` under its
``stale_nav`` policy, so there is one ``NAV_T``, never two. A history observation dated
``as_of`` must equal it. Dates without a distribution need no NAV.

**The mPME never goes short.** By induction over the dates:

1. ``NAV_mPME`` starts at 0. Every index level is positive and every ``C_t >= 0``, so
   ``X_t = NAV_mPME,prev * (I_t / I_prev) + C_t >= 0`` whenever ``NAV_mPME,prev >= 0``.
2. ``D_t >= 0`` and ``NAV_t >= 0``: a stated NAV is ``Money`` (``>= 0``), a rolled value
   is checked and refused when negative, and the residual value is ``>= 0``. When
   ``D_t > 0``, ``D_t + NAV_t > 0``, so ``w_t = D_t / (D_t + NAV_t)`` and
   ``1 - w_t = NAV_t / (D_t + NAV_t)`` both lie in ``[0, 1]``. When ``D_t = 0``,
   ``w_t = 0``.
3. Hence ``Dist_mPME,t = w_t X_t >= 0`` and ``NAV_mPME,t = (1 - w_t) X_t >= 0``, which
   carries the induction to the next date.

The argument holds in floating point too. Every operation is a sum, product or quotient
of non-negative floats, and rounding is monotone: ``fl(D + NAV) >= D``, so the computed
``w_t`` and ``1 - w_t`` stay in ``[0, 1]``. The only input that could break the property,
a negative interim NAV, is refused.

**Risk.** Unlike KS-PME, PME+ and the ICM, which use a NAV only at ``T``, the mPME
benchmark's own distributions depend on the manager's interim marks. Smoothed or
strategic valuations (Brown, Gredil & Kaplan 2019) enter the benchmark itself, and
results depend on the NAV frequency and on any zero-return roll-forward. Every NAV used
is reported with its source.

Numerics follow ``ovf.pme.pme`` (contract §9). Growth ratios are formed before they
multiply a position. A sum, product or ratio outside the float range is refused. A
per-date net that contains ``Dist_mPME,t`` or ``NAV_mPME,T`` is a computed net: within the
float rounding bound ``8 * n * eps * G`` of zero it is dropped with an assumption line,
where ``G = C_t + Dist_mPME,t (+ NAV_mPME,T)`` and ``n`` is the step's 1-based number in
the recursion plus one (the netting).

Interim NAVs are rolled with a forward cursor over the date-ordered flows and exact
running sums (Shewchuk partials), prepared once per call: a long series with long
permitted gaps costs linear time, and each window sum is the correctly rounded sum of its
flows, never a difference of large prefix totals (contract §13.4).

The shared PME machinery (input checks, index lookups, future values, netting, IRR
spreads) is imported from ``ovf.pme.pme``, including its private helpers, so the mPME
applies exactly the same rules as the other four methods. This private import is
deliberate: it keeps one implementation of those rules.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

from pydantic import ConfigDict, Field, field_validator

from ovf.core.types import FinancialBaseModel
from ovf.pme.benchmark import BenchmarkIndex, IndexLookup, IndexLookupRecord
from ovf.pme.daycount import DayCountConvention, check_convention
from ovf.pme.flows import (
    DatedAmount,
    NavObservation,
    NearZeroNet,
    PlainDate,
    ResolvedCashFlows,
    canonical_hash,
    finite_fsum,
    finite_product,
    finite_ratio,
)
from ovf.pme.irr import IrrResult
from ovf.pme.metrics import resolved_payload

# Private helpers shared with the other PME methods: one implementation of the input
# checks, lookups, netting and rounding rules (see the module docstring).
from ovf.pme.pme import (
    _EPS,
    PmeResultBase,
    _dust_lines,
    _fund_irr,
    _gross_by_date,
    _net_series,
    _noise_lines,
    _prepare,
    _solve,
    _spread_lines,
    _spreads,
    _zero_net_line,
)

InterimNavPolicy = Literal["refuse", "roll_forward_cash_adjusted"]
FundNavSource = Literal["reported", "rolled_forward", "none"]

_METHOD = "mPME"


class FundNavHistory(FinancialBaseModel):
    """The fund's NAV observations over time, each the LP's end-of-day value on its date.

    ``observations`` holds at least one observation. It is stored in ascending date order
    whatever the input order. Two observations on one date are refused, because choosing
    between them would be a guess.
    """

    model_config = ConfigDict(frozen=True)

    observations: tuple[NavObservation, ...] = Field(min_length=1)

    @field_validator("observations")
    @classmethod
    def _ascending_unique_dates(
        cls, observations: tuple[NavObservation, ...]
    ) -> tuple[NavObservation, ...]:
        ordered = tuple(sorted(observations, key=lambda item: item.date))
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if earlier.date == later.date:
                raise ValueError(
                    f"duplicate NAV date {later.date.isoformat()}: one NAV observation per "
                    "date; remove or correct the duplicate"
                )
        return ordered


class MpmeStep(FinancialBaseModel):
    """One date of the mPME recursion: a flow date or ``as_of``, in date order.

    ``contribution`` and ``distribution`` are the date's gross fund flows.
    ``position_before_sale`` is ``X_t``, the position grown to the date plus the call.
    ``weight`` is ``w_t``. ``mpme_distribution`` is ``w_t * X_t``, and ``position_after``
    is ``NAV_mPME,t``. ``fund_nav`` is the NAV that entered ``w_t``; it is set only on
    distribution dates (``None`` with source ``"none"`` elsewhere).
    ``fund_nav_observation_date`` is the date of the observation it came from, which is
    earlier than ``date`` when the NAV was rolled forward.
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    index_level: float
    contribution: float
    distribution: float
    fund_nav: float | None
    fund_nav_source: FundNavSource
    fund_nav_observation_date: PlainDate | None
    weight: float
    position_before_sale: float
    mpme_distribution: float
    position_after: float


class MpmeResult(PmeResultBase):
    """mPME: the path, the terminal value, the mPME IRR and its spread to the fund IRR.

    ``terminal_value`` is ``NAV_mPME,T``. ``mpme_series`` is the netted series
    ``{-C_t, +Dist_mPME,t, +NAV_mPME,T at T}`` solved as ``mpme_irr``. ``fund_irr`` is
    ``None`` when the fund IRR is refused (contract §11.2). ``spread`` (fund IRR minus mPME
    IRR) and ``log_spread`` (the difference of their ``log_rate``) are ``None`` unless both
    IRRs are unique. ``max_nav_gap_used_days`` is the largest gap, in days, over which an
    interim NAV was rolled forward by ``mpme`` (0 when every NAV used was reported).
    ``dropped_computed_nets`` lists the mPME nets dropped as rounding of an exact zero
    (contract §9, §13.2).
    """

    interim_nav: InterimNavPolicy
    max_nav_gap_days: int
    max_nav_gap_used_days: int
    path: tuple[MpmeStep, ...]
    terminal_value: float
    mpme_series: tuple[DatedAmount, ...]
    mpme_irr: IrrResult
    fund_irr: IrrResult | None
    spread: float | None
    log_spread: float | None
    dropped_computed_nets: tuple[NearZeroNet, ...]


@dataclass(frozen=True)
class _FundNav:
    """The fund NAV used for the weight on one distribution date, with its provenance."""

    value: float
    source: Literal["reported", "rolled_forward"]
    observed: date
    gap_days: int  # counts toward max_nav_gap_used_days (interim rolls by mpme only)
    line: str | None  # assumption line for a rolled value


def _share(fraction: float, position: float, *, what: str) -> float:
    """``fraction * position``, exactly 0 when either factor is 0.

    A zero here is exact, not an underflow: a full sale keeps ``0 * X_t``, and a sale from
    an empty position (after an earlier full sale) sells ``w_t * 0``. Any other product
    keeps the ``finite_product`` range checks.
    """
    if fraction == 0.0 or position == 0.0:
        return 0.0
    return finite_product(fraction, position, what=what)


def check_interim_policy(interim_nav: object, max_nav_gap_days: object) -> None:
    """Refuse an interim-NAV policy outside its domain, or ``"refuse"`` with a gap above 0.

    Shared with ``ovf.pme.report`` so a report refuses a contradictory policy before any
    method runs (contract §13.5).
    """
    if interim_nav not in get_args(InterimNavPolicy):
        raise ValueError(
            f"{_METHOD}: interim_nav must be one of {list(get_args(InterimNavPolicy))}, got "
            f"{interim_nav!r}"
        )
    if isinstance(max_nav_gap_days, bool) or not isinstance(max_nav_gap_days, int):
        raise ValueError(
            f"{_METHOD}: max_nav_gap_days must be an integer, got {type(max_nav_gap_days).__name__}"
        )
    if max_nav_gap_days < 0:
        raise ValueError(f"{_METHOD}: max_nav_gap_days must be >= 0, got {max_nav_gap_days}")
    if interim_nav == "refuse" and max_nav_gap_days != 0:
        raise ValueError(
            f"{_METHOD}: interim_nav 'refuse' rolls no NAV forward, so max_nav_gap_days must "
            f"be 0, got {max_nav_gap_days}; use 'roll_forward_cash_adjusted' to allow a gap"
        )


def _check_history(nav_history: object, resolved: ResolvedCashFlows) -> FundNavHistory:
    if not isinstance(nav_history, FundNavHistory):
        raise ValueError(
            f"{_METHOD}: nav_history must be a FundNavHistory, got {type(nav_history).__name__}"
        )
    as_of = resolved.as_of
    late = [item for item in nav_history.observations if item.date > as_of]
    if late:
        raise ValueError(
            f"{_METHOD}: the NAV observation dated {late[0].date.isoformat()} is after as_of "
            f"{as_of.isoformat()}; a valuation after the as-of date cannot be used, so "
            "remove it or move as_of"
        )
    at_as_of = [item for item in nav_history.observations if item.date == as_of]
    if at_as_of and float(at_as_of[0].value) != resolved.residual_value:
        raise ValueError(
            f"{_METHOD}: the NAV observation dated as_of {as_of.isoformat()} is "
            f"{at_as_of[0].value!r} but the residual value of fund '{resolved.fund_name}' "
            f"at that date is {resolved.residual_value!r}; the two must be the same NAV, so "
            "correct one of them"
        )
    return nav_history


def _residual_nav(resolved: ResolvedCashFlows, residual: float) -> _FundNav:
    """``NAV_T`` for a distribution dated ``as_of`` without a history observation there.

    It is the residual value (contract §12 as amended): one ``NAV_T``, never two. A value
    rolled by ``resolve`` follows its ``stale_nav`` policy, not ``max_nav_gap_days``.
    """
    as_of = resolved.as_of
    roll = resolved.nav_roll_forward
    if resolved.nav_source != "rolled_forward" or roll is None:
        return _FundNav(value=residual, source="reported", observed=as_of, gap_days=0, line=None)
    return _FundNav(
        value=residual,
        source="rolled_forward",
        observed=roll.reported_date,
        gap_days=0,
        line=(
            f"Fund NAV on {as_of.isoformat()} (a distribution date and as_of) is the residual "
            f"value {residual!r}, rolled forward by resolve from {roll.reported_date.isoformat()} "
            "under its stale_nav policy (not under interim_nav or max_nav_gap_days, and not "
            "counted in max_nav_gap_used_days)."
        ),
    )


class _ExactSum:
    """A running sum kept exactly as Shewchuk's non-overlapping partials, rounded on read.

    ``total`` is the correctly rounded sum of every term added, the number ``math.fsum``
    gives for the whole window, so a window sum is never formed as the difference of two
    large prefix totals (contract §13.4).
    """

    __slots__ = ("partials",)

    def __init__(self) -> None:
        self.partials: list[float] = []

    def add(self, value: float, *, what: str) -> None:
        partials = self.partials
        count = 0
        for other in partials:
            if abs(value) < abs(other):
                value, other = other, value
            high = value + other
            if not math.isfinite(high):
                raise ValueError(f"{what} overflows the float range")
            low = other - (high - value)
            if low:
                partials[count] = low
                count += 1
            value = high
        partials[count:] = [value]

    def total(self, *, what: str) -> float:
        return finite_fsum(self.partials, what=what)


class _NavRoller:
    """The fund's end-of-day NAV on distribution dates visited in ascending order (§12).

    The observation dates are prepared once. Rolling observation ``s`` forward to ``t``
    needs the contributions and distributions dated in ``(s, t]``; they are accumulated
    exactly by a forward cursor over the date-ordered flows and reused while the same
    observation serves later distribution dates. Each call costs a bisection plus the
    flows newly passed, so long series with long permitted gaps stay linear (§13.4).
    """

    def __init__(
        self,
        history: FundNavHistory,
        resolved: ResolvedCashFlows,
        residual: float,
        interim_nav: InterimNavPolicy,
        max_nav_gap_days: int,
    ) -> None:
        self.observations = history.observations
        self.dates = [item.date for item in self.observations]
        self.flows = resolved.flows  # canonical order: ascending date
        self.flow_dates = [flow.date for flow in self.flows]
        self.resolved = resolved
        self.residual = residual
        self.interim_nav = interim_nav
        self.max_nav_gap_days = max_nav_gap_days
        self.anchor: int | None = None  # the observation the running sums start after
        self.cursor = 0  # the next flow not yet accumulated
        self.contributed = _ExactSum()
        self.distributed = _ExactSum()

    def nav_at(self, on: date) -> _FundNav:
        """The fund NAV on the distribution date ``on`` (contract §12)."""
        position = bisect.bisect_right(self.dates, on) - 1
        if position >= 0 and self.dates[position] == on:
            return _FundNav(
                value=float(self.observations[position].value),
                source="reported",
                observed=on,
                gap_days=0,
                line=None,
            )
        if on == self.resolved.as_of:
            return _residual_nav(self.resolved, self.residual)
        if self.interim_nav == "refuse":
            raise ValueError(
                f"{_METHOD}: no fund NAV observation dated {on.isoformat()}, a distribution "
                "date; interim_nav='refuse' needs one dated every distribution date: state "
                "it, or pass interim_nav='roll_forward_cash_adjusted' with a max_nav_gap_days"
            )
        if position < 0:
            raise ValueError(
                f"{_METHOD}: no fund NAV observation on or before the distribution date "
                f"{on.isoformat()} (the first is dated {self.dates[0].isoformat()}), so there "
                "is nothing to roll forward; a NAV is never taken from a later date"
            )
        observation = self.observations[position]
        gap = (on - observation.date).days
        if gap > self.max_nav_gap_days:
            raise ValueError(
                f"{_METHOD}: the latest fund NAV before the distribution date "
                f"{on.isoformat()} is dated {observation.date.isoformat()}, {gap} days "
                f"earlier, beyond max_nav_gap_days {self.max_nav_gap_days}; state a NAV for "
                f"{on.isoformat()} or a larger max_nav_gap_days"
            )
        window = f"({observation.date.isoformat()}, {on.isoformat()}]"
        if position != self.anchor:
            # Flows dated on the observation date are already in it (end-of-day NAV).
            self.anchor = position
            self.cursor = bisect.bisect_right(self.flow_dates, observation.date)
            self.contributed = _ExactSum()
            self.distributed = _ExactSum()
        # Flows in (s, t] are applied, the distribution on t itself included.
        while self.cursor < len(self.flows) and self.flows[self.cursor].date <= on:
            flow = self.flows[self.cursor]
            if flow.kind == "contribution":
                self.contributed.add(flow.amount, what=f"{_METHOD}: the contributions in {window}")
            else:
                self.distributed.add(flow.amount, what=f"{_METHOD}: the distributions in {window}")
            self.cursor += 1
        contributed = self.contributed.total(what=f"{_METHOD}: the contributions in {window}")
        distributed = self.distributed.total(what=f"{_METHOD}: the distributions in {window}")
        rolled = finite_fsum(
            (float(observation.value), contributed, -distributed),
            what=f"{_METHOD}: the fund NAV rolled forward to {on.isoformat()}",
        )
        if rolled < 0:
            raise ValueError(
                f"{_METHOD}: rolling the fund NAV {observation.value!r} from "
                f"{observation.date.isoformat()} to the distribution date {on.isoformat()} "
                f"gives {rolled!r}: distributions in between exceed the NAV plus "
                "contributions, so the inputs are inconsistent; state a NAV for that date"
            )
        return _FundNav(
            value=rolled,
            source="rolled_forward",
            observed=observation.date,
            gap_days=gap,
            line=(
                f"Fund NAV on {on.isoformat()} rolled forward with zero return from "
                f"{observation.date.isoformat()} ({gap} days; reported {observation.value!r}): "
                f"+ contributions {contributed!r} - distributions {distributed!r} dated in "
                f"{window} = {rolled!r}. Any market movement of the fund in that window is "
                "ignored, which mis-states w_t."
            ),
        )


def mpme(
    resolved: ResolvedCashFlows,
    nav_history: FundNavHistory,
    benchmark: BenchmarkIndex,
    *,
    lookup: IndexLookup,
    max_gap_days: int,
    day_count: DayCountConvention,
    interim_nav: InterimNavPolicy,
    max_nav_gap_days: int,
) -> MpmeResult:
    """mPME, a labelled reconstruction of Cambridge Associates' modified PME.

    Not CA's published algebra, which was never found. This follows Gredil, Griffiths &
    Stucke (2014) eq. (9) and does not claim to reproduce CA's figures; see the module
    docstring. With ``X_t = NAV_mPME,prev * (I_t / I_prev) + C_t`` and
    ``w_t = D_t / (D_t + NAV_t)`` on distribution dates (else 0), the benchmark
    distributes ``w_t * X_t`` and keeps ``(NAV_t / (D_t + NAV_t)) * X_t``. The mPME IRR
    solves ``{-C_t, +Dist_mPME,t, +NAV_mPME,T at T}``.

    Requirements, each refused with ``ValueError``: a residual value at ``as_of``, paid-in
    capital above zero, one currency, and an index level at every flow date and at
    ``as_of`` (NAV dates need none). Every NAV observation must be dated on or before
    ``as_of``, and one dated ``as_of`` must equal ``resolved.residual_value``.
    ``interim_nav="refuse"`` needs an observation on every distribution date and
    ``max_nav_gap_days == 0``. ``"roll_forward_cash_adjusted"`` rolls the latest earlier
    observation within ``max_nav_gap_days`` forward with zero return; a negative rolled
    value, a missing earlier observation or a gap beyond the limit is refused, naming the
    date. A distribution dated ``as_of`` uses the residual value when the history has no
    observation there.

    **Never short.** ``NAV_mPME`` starts at 0; ``I > 0`` and ``C_t >= 0`` give
    ``X_t >= 0``; ``D_t > 0`` gives ``D_t + NAV_t > 0`` and ``w_t``, ``1 - w_t`` in
    ``[0, 1]`` (every NAV is ``>= 0``: stated as ``Money``, rolled values checked). By
    induction every ``NAV_mPME,t >= 0`` and every ``Dist_mPME,t >= 0``, in floating point
    too, since every step combines non-negative floats with monotone rounding.

    A refused fund IRR is carried as ``fund_irr=None`` with the reason (contract §11.2);
    ``spread`` and ``log_spread`` need two unique IRRs.
    """
    day_count = check_convention(day_count)
    check_interim_policy(interim_nav, max_nav_gap_days)
    prepared = _prepare(resolved, benchmark, lookup, max_gap_days, _METHOD)
    history = _check_history(nav_history, resolved)
    residual = prepared.nav
    fund, fund_lines = _fund_irr(resolved, day_count, _METHOD)
    contributions, distributions = _gross_by_date(resolved, _METHOD)
    roller = _NavRoller(history, resolved, residual, interim_nav, max_nav_gap_days)

    path: list[MpmeStep] = []
    nav_lines: list[str] = []
    reported_dates: list[date] = []
    max_nav_gap_used = 0
    position = 0.0
    previous: IndexLookupRecord | None = None
    previous_date: date | None = None
    for on in sorted(prepared.records):
        record = prepared.records[on]
        if previous is None or previous_date is None:
            grown = 0.0
        else:
            ratio = finite_ratio(
                record.level,
                previous.level,
                what=f"{_METHOD}: the index growth I_t / I_prev from "
                f"{previous_date.isoformat()} to {on.isoformat()}",
            )
            grown = finite_product(
                position, ratio, what=f"{_METHOD}: the position grown to {on.isoformat()}"
            )
        contribution = contributions.get(on, 0.0)
        distribution = distributions.get(on, 0.0)
        before = finite_fsum(
            (grown, contribution),
            what=f"{_METHOD}: the position before the sale on {on.isoformat()}",
        )
        fund_nav: _FundNav | None = None
        if distribution > 0:
            fund_nav = roller.nav_at(on)
            value_before = finite_fsum(
                (distribution, fund_nav.value),
                what=f"{_METHOD}: D_t + NAV_t on {on.isoformat()}",
            )
            weight = finite_ratio(
                distribution, value_before, what=f"{_METHOD}: w_t on {on.isoformat()}"
            )
            # 1 - w_t as NAV_t / (D_t + NAV_t), so that w_t = 1 keeps exactly 0.
            kept = finite_ratio(
                fund_nav.value, value_before, what=f"{_METHOD}: 1 - w_t on {on.isoformat()}"
            )
            sold = _share(weight, before, what=f"{_METHOD}: Dist_mPME on {on.isoformat()}")
            after = _share(kept, before, what=f"{_METHOD}: NAV_mPME on {on.isoformat()}")
            max_nav_gap_used = max(max_nav_gap_used, fund_nav.gap_days)
            if fund_nav.line is None:
                reported_dates.append(on)
            else:
                nav_lines.append(fund_nav.line)
        else:
            weight, sold, after = 0.0, 0.0, before
        path.append(
            MpmeStep(
                date=on,
                index_level=record.level,
                contribution=contribution,
                distribution=distribution,
                fund_nav=None if fund_nav is None else fund_nav.value,
                fund_nav_source="none" if fund_nav is None else fund_nav.source,
                fund_nav_observation_date=None if fund_nav is None else fund_nav.observed,
                weight=weight,
                position_before_sale=before,
                mpme_distribution=sold,
                position_after=after,
            )
        )
        position = after
        previous, previous_date = record, on

    as_of = prepared.as_of
    terminal = path[-1].position_after
    # Stated legs are the contributions; Dist_mPME,t and NAV_mPME,T are computed amounts.
    stated = [(flow.date, -flow.amount) for flow in resolved.flows if flow.kind == "contribution"]
    computed: list[tuple[date, float]] = []
    computed_scale: dict[date, tuple[float, int]] = {}
    for number, step in enumerate(path, start=1):
        extra = terminal if step.date == as_of else 0.0
        if step.mpme_distribution == 0.0 and extra == 0.0:
            continue
        computed.extend(
            item
            for item in ((step.date, step.mpme_distribution), (step.date, extra))
            if item[1] != 0.0
        )
        # G = C_t + Dist_mPME,t (+ NAV_mPME,T); n = the step's number plus the netting.
        computed_scale[step.date] = (
            finite_fsum(
                (step.contribution, step.mpme_distribution, extra),
                what=f"{_METHOD}: the gross magnitude of the net on {step.date.isoformat()}",
            ),
            number + 1,
        )
    series, zeros, dropped, dust = _net_series(stated, computed, computed_scale)
    mpme_irr = _solve(series, day_count, "mPME series")
    spread, log_spread = _spreads(fund, mpme_irr)

    if interim_nav == "refuse":
        policy_line = (
            "Interim NAV policy: refuse; every distribution date before as_of needs a fund "
            "NAV observation dated that day (max_nav_gap_days 0)."
        )
    else:
        policy_line = (
            "Interim NAV policy: roll_forward_cash_adjusted with max_nav_gap_days "
            f"{max_nav_gap_days}; a distribution date without an observation uses the latest "
            "earlier one rolled forward as NAV_s + C_(s,t] - D_(s,t] with zero return. "
            "Interpolation between NAVs and index-adjusted roll-forward are not offered."
        )
    if reported_dates:
        nav_lines.insert(
            0,
            "Fund NAV reported on the distribution date(s) "
            + ", ".join(on.isoformat() for on in reported_dates)
            + ".",
        )
    if not any(step.distribution > 0 for step in path):
        nav_lines.append(
            "The fund made no distribution, so the mPME never sells: every w_t is 0, no "
            "interim NAV is used and NAV_mPME,T = FV(C)."
        )
    assumptions = [
        *prepared.assumptions,
        "mPME is a labelled reconstruction of Cambridge Associates' modified PME: CA "
        "describe the method only in prose (index shares bought and sold on the fund's "
        "schedule, distributions in the same proportion as the fund's), so this is not "
        "CA's algebra and does not claim to reproduce CA's figures; CA's dating conventions "
        "are not published and vendor figures may differ.",
        "Algebra: Gredil, Griffiths & Stucke (2014, SSRN working paper) eq. (9), with the "
        "NAV recursion read with the period index throughout (their eq. (11) as printed "
        "mixes the period and terminal indices and is not used).",
        "Recursion on every flow date and at as_of, in order (grow, invest the call, then "
        "sell the fund's fraction): X_t = NAV_mPME,prev * (I_t / I_prev) + C_t; w_t = D_t / "
        "(D_t + NAV_t) when D_t > 0, else 0; Dist_mPME,t = w_t * X_t; NAV_mPME,t = (NAV_t / "
        "(D_t + NAV_t)) * X_t, so w_t = 1 leaves exactly 0. The mPME IRR solves "
        f"{{-C_t, +Dist_mPME,t, +NAV_mPME,T at T}} netted per date under {day_count}.",
        "Weight timing: NAV_t is the fund's end-of-day NAV on the distribution date, after "
        "every flow on that date, so D_t + NAV_t is its value after the day's call and "
        "before its distribution; the benchmark sells the same fraction w_t of its position.",
        "Gross legs: C_t and D_t are the date's gross contributions and distributions; a "
        "same-day recall is not netted (it is invested, then sold), and netting it gives a "
        "different w_t. A recallable policy is not modelled in pme-v1.",
        policy_line,
        "At as_of the fund NAV is the residual value, the same NAV_T every PME uses; a "
        "history observation dated as_of must equal it.",
        *nav_lines,
        "The mPME position never goes short: it starts at 0, index levels are positive, "
        "contributions are non-negative and w_t lies in [0, 1] (a negative interim NAV is "
        "refused), so every NAV_mPME,t and Dist_mPME,t is >= 0.",
        "Risk: the benchmark's distributions depend on the manager's interim NAVs. Unlike "
        "KS-PME, PME+ and the ICM, which use a NAV only at T, smoothed or strategic "
        "valuations (Brown, Gredil & Kaplan 2019) enter the mPME benchmark itself, and the "
        "result depends on the NAV frequency and on any zero-return roll-forward.",
        f"A net containing Dist_mPME,t or NAV_mPME,T within 8 x n x eps x G of zero (eps = "
        f"{_EPS!r}, n = the step's number in the recursion plus one, G = C_t + Dist_mPME,t "
        "(+ NAV_mPME,T)) is rounding of an exact zero and is dropped.",
        *fund_lines,
        *_zero_net_line("mPME series", zeros),
        *_noise_lines("mPME series", dropped),
        *_dust_lines("mPME series", dust),
        *_spread_lines("mPME", day_count, fund, mpme_irr, spread),
    ]
    return MpmeResult(
        **prepared.common_fields(),
        interim_nav=interim_nav,
        max_nav_gap_days=max_nav_gap_days,
        max_nav_gap_used_days=max_nav_gap_used,
        path=tuple(path),
        terminal_value=terminal,
        mpme_series=series,
        mpme_irr=mpme_irr,
        fund_irr=fund,
        spread=spread,
        log_spread=log_spread,
        dropped_computed_nets=tuple(dropped),
        assumptions=assumptions,
        input_hash=canonical_hash(
            {
                "method": "mpme",
                "resolved": resolved_payload(resolved),
                "nav_history": history.model_dump(mode="json"),
                "benchmark": benchmark.model_dump(mode="json"),
                "lookup": lookup,
                "max_gap_days": max_gap_days,
                "day_count": day_count,
                "interim_nav": interim_nav,
                "max_nav_gap_days": max_nav_gap_days,
            }
        ),
    )
