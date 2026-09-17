"""Public-market equivalents: KS-PME, Direct Alpha, PME+ and Long-Nickels (ICM).

Each method compares a fund's dated flows with the same cash invested in, or taken out
of, a benchmark index. All four consume a ``ResolvedCashFlows`` (from
``ovf.pme.flows.resolve``) and a ``BenchmarkIndex``, and all four need the same things:
a residual value at ``as_of``, paid-in capital above zero, one currency on both sides
(there is no FX) and an index level for every flow date and for ``as_of`` under the
stated lookup. Anything missing is refused with ``ValueError``; nothing is guessed.

With ``T = as_of``, ``I_t`` the index level used for date ``t`` and ``NAV_T`` the
residual value, every flow is grown to ``T`` at ``I_T / I_t``::

    FV(C) = sum_t C_t * I_T / I_t        FV(D) = sum_t D_t * I_T / I_t

- KS-PME (Kaplan & Schoar 2005; the residual value enters as a terminal distribution
  following Harris, Jenkinson & Kaplan 2014): ``(FV(D) + NAV_T) / FV(C)``.
- Direct Alpha (Gredil, Griffiths & Stucke 2014, SSRN working paper): the IRR of the
  compounded series ``{-C_t * I_T/I_t, +D_t * I_T/I_t, +NAV_T at T}``.
- PME+ (Rouvinez 2003, Venture Capital Journal, Aug. 2003, pp. 34-38): distributions
  scaled by ``s = (FV(C) - NAV_T) / FV(D)`` so the benchmark position ends at ``NAV_T``;
  its IRR solves ``{-C_t, +s * D_t, +NAV_T at T}``.
- Long-Nickels ICM (Long & Nickels 1996): the index position
  ``V_d = V_prev * I_d / I_prev + C_d - D_d`` rolled to ``T``, which equals
  ``FV(C) - FV(D)``; its IRR solves ``{-C_t, +D_t, +V_T at T}``.

Rates are solved by ``ovf.pme.irr``, which never picks a root: an IRR-based figure is
``None`` unless the root is proven unique, and the full ``IrrResult`` is attached. The
known pathologies of PME+ (``s < 0``, where the spread is withheld) and of the ICM (a
short index position) are reported, not hidden. A refused fund IRR does not abort PME+ or
the ICM: it is carried as ``None`` with the reason (contract §11.2).

KS-PME and PME+ use gross legs (every contribution in ``FV(C)``, every distribution in
``FV(D)``), so recallable distributions count on both sides; Direct Alpha and the ICM are
linear in per-date nets. Every result reports the largest index-lookup gap it used, and,
for a NAV rolled forward from an earlier date, the index growth over that gap
(contract §11.5).

Numerics (contract §9). Growth ratios are formed first and then applied
(``amount * (I_T / I_t)``, ``V_prev * (I_d / I_prev)``), so no intermediate product of an
amount and an index level can underflow or overflow. Subnormal index levels are refused
by ``IndexLevel``; a growth ratio, future value, product or sum that overflows the float
range, or a non-zero one that underflows it, is refused with ``ValueError`` naming it,
before any result model is built. The ICM and PME+ series contain computed amounts
(``V_T``, ``s * D_t``). A computed net within the float rounding bound ``8 * n * eps * G``
of zero (``n`` the rounded steps that produced it, ``G`` the gross magnitude of its terms)
is cancellation noise of an exact zero and is dropped from that series with an assumption
line. Stated legs are netted first with ``ovf.pme.flows.net_stated_by_date``: exact zeros
and decimal-representation noise (``|net| <= eps * sum|legs|``, contract §11.3) count as
zero; computed amounts are added afterwards with exact netting. The same
computed bound, with ``G_d`` the gross flows grown to ``d``, separates a short ICM position
from rounding.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ConfigDict

from ovf.core.types import FinancialBaseModel
from ovf.pme.benchmark import (
    BenchmarkIndex,
    IndexLookup,
    IndexLookupRecord,
    ReturnBasis,
    benchmark_assumptions,
    index_level,
)
from ovf.pme.daycount import DayCountConvention, check_convention
from ovf.pme.flows import (
    ENGINE_VERSION,
    DatedAmount,
    FlowKind,
    NearZeroNet,
    PlainDate,
    ResolvedCashFlows,
    canonical_hash,
    finite_fsum,
    finite_product,
    finite_ratio,
    net_by_date,
    net_stated_by_date,
)
from ovf.pme.irr import IrrResult, fund_irr, xirr
from ovf.pme.metrics import GROSS_LEGS_ASSUMPTION, resolved_payload

_EPS = sys.float_info.epsilon


def _rounding_bound(steps: int, scale: float) -> float:
    """``8 * n * eps * G``: the float rounding bound of a value built in ``n`` rounded steps
    from terms of gross magnitude ``G`` (contract §9)."""
    return 8.0 * steps * _EPS * scale


class FlowValuation(FinancialBaseModel):
    """One fund flow grown to ``as_of`` at the benchmark's return; canonical order.

    ``index_gap_days`` is how many days before the flow date the level used is dated
    (0 for an exact match).
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    kind: FlowKind
    amount: float
    index_date: PlainDate
    index_level: float
    index_gap_days: int
    growth_to_as_of: float
    future_value: float


class PmeResultBase(FinancialBaseModel):
    """What every PME result carries: the inputs, the lookups and the future values.

    ``max_gap_used_days`` is the largest gap of every index lookup used: the flow dates,
    ``as_of`` and, for a rolled-forward NAV, the NAV date (contract §13.3).
    ``index_growth_over_nav_gap`` is ``I_T / I_navdate`` when the residual value is a NAV
    rolled forward from an earlier date, with that NAV-date lookup in
    ``index_at_nav_date`` (both ``None`` otherwise, or when the index has no usable level
    for the NAV date; the assumptions then say why). The NAV-date lookup adds no step to
    the ICM or mPME path.
    """

    model_config = ConfigDict(frozen=True)

    as_of: PlainDate
    benchmark_name: str
    return_basis: ReturnBasis
    lookup: IndexLookup
    max_gap_days: int
    max_gap_used_days: int
    index_at_as_of: IndexLookupRecord
    flows: tuple[FlowValuation, ...]
    fv_contributions: float
    fv_distributions: float
    residual_value: float
    index_growth_over_nav_gap: float | None
    index_at_nav_date: IndexLookupRecord | None
    assumptions: list[str]
    input_hash: str
    engine_version: str = ENGINE_VERSION


class KsPmeResult(PmeResultBase):
    """Kaplan-Schoar PME: ``(FV(D) + NAV_T) / FV(C)``."""

    ks_pme: float


class DirectAlphaResult(PmeResultBase):
    """Direct Alpha: the IRR of the compounded series, with the full root analysis.

    ``alpha_annual_effective`` and ``alpha_continuous`` (``ln(1 + alpha)``, the root's
    ``log_rate``) are ``None`` unless ``irr.status == "unique"``.
    """

    compounded_series: tuple[DatedAmount, ...]
    irr: IrrResult
    alpha_annual_effective: float | None
    alpha_continuous: float | None


class PmePlusResult(PmeResultBase):
    """PME+: the distribution scale ``s``, the PME+ IRR and its spread to the fund IRR.

    ``scale`` is ``None`` when ``FV(D) == 0`` (no distributions to scale); the PME+ series
    is then empty and its IRR ``None``. ``identity_residual`` is
    ``FV(C) - s * FV(D) - NAV_T``, zero in exact arithmetic. ``fund_irr`` is ``None`` when
    the fund IRR is refused. ``spread`` (fund IRR minus PME+ IRR) and ``log_spread`` (the
    difference of their ``log_rate``) are ``None`` unless both IRRs are unique, and are
    ``None`` whenever ``s < 0``. ``dropped_computed_nets`` lists the PME+ nets dropped as
    rounding of an exact zero (contract §9, §13.2).
    """

    scale: float | None
    scale_negative: bool
    identity_residual: float | None
    pme_plus_series: tuple[DatedAmount, ...]
    pme_plus_irr: IrrResult | None
    fund_irr: IrrResult | None
    spread: float | None
    log_spread: float | None
    dropped_computed_nets: tuple[NearZeroNet, ...]


class IcmStep(FinancialBaseModel):
    """One date of the Long-Nickels index position recursion.

    ``position_grown`` is ``V_prev * (I_d / I_prev)`` (zero on the first date);
    ``position_after`` adds the date's gross contributions and subtracts its gross
    distributions.
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    index_level: float
    position_grown: float
    contribution: float
    distribution: float
    position_after: float


class LnPmeResult(PmeResultBase):
    """Long-Nickels ICM: the index position path, its terminal value and IRR spread.

    ``terminal_value_recursive`` comes from the path and ``terminal_value_closed_form`` is
    ``FV(C) - FV(D)``; ``reconciliation_residual`` is their difference. ``went_short``
    flags the method's documented pathology, a negative index position beyond the float
    rounding bound. ``fund_irr`` is ``None`` when the fund IRR is refused; ``spread`` and
    ``log_spread`` need two unique IRRs. ``dropped_computed_nets`` lists the ICM terminal
    net when it was dropped as rounding of an exact zero (contract §9, §13.2).
    """

    path: tuple[IcmStep, ...]
    terminal_value_recursive: float
    terminal_value_closed_form: float
    reconciliation_residual: float
    went_short: bool
    first_short_date: PlainDate | None
    min_position: float
    icm_series: tuple[DatedAmount, ...]
    icm_irr: IrrResult
    fund_irr: IrrResult | None
    spread: float | None
    log_spread: float | None
    dropped_computed_nets: tuple[NearZeroNet, ...]


@dataclass(frozen=True)
class _Prepared:
    resolved: ResolvedCashFlows
    benchmark: BenchmarkIndex
    lookup: IndexLookup
    max_gap_days: int
    records: dict[date, IndexLookupRecord]
    growth: dict[date, float]  # I_T / I_t for every flow date and as_of (1.0 there)
    flows: tuple[FlowValuation, ...]
    fv_contributions: float
    fv_distributions: float
    nav: float
    nav_gap_growth: float | None
    nav_record: IndexLookupRecord | None  # the NAV-date lookup; no path step
    assumptions: list[str]

    @property
    def as_of(self) -> date:
        return self.resolved.as_of

    def common_fields(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "benchmark_name": self.benchmark.name,
            "return_basis": self.benchmark.return_basis,
            "lookup": self.lookup,
            "max_gap_days": self.max_gap_days,
            "max_gap_used_days": max(record.gap_days for record in self.lookups()),
            "index_at_as_of": self.records[self.as_of],
            "flows": self.flows,
            "fv_contributions": self.fv_contributions,
            "fv_distributions": self.fv_distributions,
            "residual_value": self.nav,
            "index_growth_over_nav_gap": self.nav_gap_growth,
            "index_at_nav_date": self.nav_record,
        }

    def lookups(self) -> list[IndexLookupRecord]:
        """Every index lookup used: flow dates and as_of, then the NAV-date one if any."""
        extra = [] if self.nav_record is None else [self.nav_record]
        return [*self.records.values(), *extra]

    def input_hash(self, method: str, day_count: DayCountConvention | None) -> str:
        return canonical_hash(
            {
                "method": method,
                "resolved": resolved_payload(self.resolved),
                "benchmark": self.benchmark.model_dump(mode="json"),
                "lookup": self.lookup,
                "max_gap_days": self.max_gap_days,
                "day_count": day_count,
            }
        )


def _nav_gap(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    lookup: IndexLookup,
    max_gap_days: int,
    at_as_of: IndexLookupRecord,
    method: str,
) -> tuple[float | None, list[str], IndexLookupRecord | None]:
    """``I_T / I_navdate`` for a NAV rolled forward from an earlier date (contract §11.5).

    Returns the growth, its assumption line and the NAV-date lookup record, which counts
    in ``max_gap_used_days`` (contract §13.3).
    """
    roll = resolved.nav_roll_forward
    if resolved.nav_source != "rolled_forward" or roll is None:
        return None, [], None
    nav_date = roll.reported_date.isoformat()
    try:
        at_nav = index_level(
            benchmark, roll.reported_date, lookup=lookup, max_gap_days=max_gap_days
        )
    except ValueError as exc:
        return (
            None,
            [
                f"The NAV is rolled forward with zero return from {nav_date}, but the index move "
                f"over that gap cannot be quantified: {exc}"
            ],
            None,
        )
    growth = finite_ratio(
        at_as_of.level,
        at_nav.level,
        what=f"{method}: the index growth I_T / I_navdate from {nav_date}",
    )
    return (
        growth,
        [
            f"The NAV is rolled forward with zero return from {nav_date}, while the index grew "
            f"by I_T / I_navdate = {growth!r} over that gap (level {at_nav.level!r} dated "
            f"{at_nav.used.isoformat()}). Above 1 the PME moves against the fund, whose residual "
            "value misses that market move; below 1 it moves in the fund's favour."
        ],
        at_nav,
    )


def _prepare(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    lookup: IndexLookup,
    max_gap_days: int,
    method: str,
) -> _Prepared:
    if not isinstance(resolved, ResolvedCashFlows):
        raise ValueError(
            f"{method}: resolved must be a ResolvedCashFlows (from ovf.pme.flows.resolve), "
            f"got {type(resolved).__name__}"
        )
    if not isinstance(benchmark, BenchmarkIndex):
        raise ValueError(
            f"{method}: benchmark must be a BenchmarkIndex, got {type(benchmark).__name__}"
        )
    as_of = resolved.as_of
    if resolved.residual_value is None:
        raise ValueError(
            f"{method} needs a residual value at {as_of.isoformat()}, but fund "
            f"'{resolved.fund_name}' states no NAV; a fully realised fund must say so with "
            "NavObservation(date=as_of, value=0)"
        )
    if not resolved.paid_in > 0:
        raise ValueError(
            f"{method} needs paid-in capital above zero; fund '{resolved.fund_name}' has no "
            "contributions, so there is nothing to invest in the benchmark"
        )
    if benchmark.currency != resolved.currency:
        raise ValueError(
            f"{method}: benchmark '{benchmark.name}' is in {benchmark.currency} but fund "
            f"'{resolved.fund_name}' is in {resolved.currency}; no FX conversion is "
            f"performed, so supply a benchmark in {resolved.currency}"
        )
    records: dict[date, IndexLookupRecord] = {}
    for on in sorted({flow.date for flow in resolved.flows} | {as_of}):
        try:
            records[on] = index_level(benchmark, on, lookup=lookup, max_gap_days=max_gap_days)
        except ValueError as exc:
            what = "the as-of date" if on == as_of else "flow date"
            raise ValueError(
                f"{method}: no usable index level for {what} {on.isoformat()}: {exc}"
            ) from exc
    at_as_of = records[as_of]
    # The growth ratio first, then the product: amount * (I_T / I_t) (contract §9). Every
    # ratio is range-checked here, before any result model is built (R2-12).
    growth = {
        on: finite_ratio(
            at_as_of.level,
            record.level,
            what=f"{method}: the index growth I_T / I_t from {on.isoformat()} to "
            f"{as_of.isoformat()}",
        )
        for on, record in records.items()
    }
    future_values = [
        finite_product(
            flow.amount,
            growth[flow.date],
            what=f"{method}: the future value of the {flow.kind} on {flow.date.isoformat()}",
        )
        for flow in resolved.flows
    ]
    flows = tuple(
        FlowValuation(
            date=flow.date,
            kind=flow.kind,
            amount=flow.amount,
            index_date=records[flow.date].used,
            index_level=records[flow.date].level,
            index_gap_days=records[flow.date].gap_days,
            growth_to_as_of=growth[flow.date],
            future_value=future_value,
        )
        for flow, future_value in zip(resolved.flows, future_values, strict=True)
    )
    nav_gap_growth, nav_gap_lines, nav_record = _nav_gap(
        resolved, benchmark, lookup, max_gap_days, at_as_of, method
    )
    assumptions = [
        *resolved.assumptions,
        *benchmark_assumptions(benchmark, lookup=lookup, max_gap_days=max_gap_days),
        f"No FX: the fund flows and the benchmark are both in {resolved.currency}.",
        f"Every flow is grown to {as_of.isoformat()} at I_T / I_t, with I_T = "
        f"{at_as_of.level!r} (level dated {at_as_of.used.isoformat()}); the ratio is formed "
        "before it multiplies the amount.",
        *nav_gap_lines,
    ]
    used = [*records.values(), *([] if nav_record is None else [nav_record])]
    stale = [record for record in used if record.gap_days > 0]
    if stale:
        listed = ", ".join(
            f"{r.requested.isoformat()} used {r.used.isoformat()} ({r.gap_days} days)"
            + (" for the NAV date" if r is nav_record else "")
            for r in stale
        )
        assumptions.append(f"Stale index levels used: {listed}.")
    return _Prepared(
        resolved=resolved,
        benchmark=benchmark,
        lookup=lookup,
        max_gap_days=max_gap_days,
        records=records,
        growth=growth,
        flows=flows,
        fv_contributions=finite_fsum(
            (f.future_value for f in flows if f.kind == "contribution"),
            what=f"{method}: FV(C), the contributions grown to {as_of.isoformat()}",
        ),
        fv_distributions=finite_fsum(
            (f.future_value for f in flows if f.kind == "distribution"),
            what=f"{method}: FV(D), the distributions grown to {as_of.isoformat()}",
        ),
        nav=resolved.residual_value,
        nav_gap_growth=nav_gap_growth,
        nav_record=nav_record,
        assumptions=assumptions,
    )


def _signed(resolved: ResolvedCashFlows) -> list[tuple[date, float]]:
    """Signed fund flows: contribution ``-amount``, distribution ``+amount``."""
    return [(flow.date, flow.signed_amount) for flow in resolved.flows]


def _gross_by_date(
    resolved: ResolvedCashFlows, method: str
) -> tuple[dict[date, float], dict[date, float]]:
    """Gross contributions and gross distributions per date, each a checked ``fsum``."""
    contributions: dict[date, list[float]] = defaultdict(list)
    distributions: dict[date, list[float]] = defaultdict(list)
    for flow in resolved.flows:
        (contributions if flow.kind == "contribution" else distributions)[flow.date].append(
            flow.amount
        )
    return (
        {
            on: finite_fsum(amounts, what=f"{method}: contributions on {on.isoformat()}")
            for on, amounts in contributions.items()
        },
        {
            on: finite_fsum(amounts, what=f"{method}: distributions on {on.isoformat()}")
            for on, amounts in distributions.items()
        },
    )


def _net_series(
    stated: list[tuple[date, float]],
    computed: list[tuple[date, float]] | None = None,
    computed_scale: dict[date, tuple[float, int]] | None = None,
) -> tuple[tuple[DatedAmount, ...], tuple[date, ...], list[NearZeroNet], list[NearZeroNet]]:
    """Per-date nets of stated legs plus computed amounts, ascending; zero nets dropped.

    Stated legs (fund flows, ``NAV_T``) are netted first with
    ``ovf.pme.flows.net_stated_by_date``: exact zeros and legs within decimal-representation
    noise count as zero (contract §11.3), and the near-zero dates are returned for the
    assumption line. Computed amounts (``V_T``, ``s * D_t``) are then added to each date's
    stated net with exact netting. ``computed_scale`` maps each date holding a computed
    amount to ``(G, n)``: the gross magnitude of the terms that produced its net and the
    number of rounded steps. Such a net with ``|net| <= 8 * n * eps * G`` is float
    cancellation noise of an exact zero (contract §9): it is dropped as well and returned
    as a ``NearZeroNet`` record (contract §13.2), like the stated near-zero dates. Zero-valued terms (a zero NAV, a zero scale) are ignored, so
    only a genuine cancellation is listed.
    """
    stated_nets, stated_zeros, dust = net_stated_by_date(
        [(on, amount) for on, amount in stated if amount != 0.0]
    )
    extra = [(on, amount) for on, amount in (computed or []) if amount != 0.0]
    if not extra:
        return tuple(stated_nets), tuple(stated_zeros), [], dust
    computed_dates = {on for on, _ in extra}
    nets, exact_zeros = net_by_date([*((item.date, item.amount) for item in stated_nets), *extra])
    zeros = sorted({*exact_zeros, *(on for on in stated_zeros if on not in computed_dates)})
    kept: list[DatedAmount] = []
    dropped: list[NearZeroNet] = []
    for item in nets:
        rounding = None if computed_scale is None else computed_scale.get(item.date)
        bound = None if rounding is None else _rounding_bound(rounding[1], rounding[0])
        if rounding is not None and bound is not None and abs(item.amount) <= bound:
            dropped.append(
                NearZeroNet(date=item.date, raw_net=item.amount, gross=rounding[0], bound=bound)
            )
        else:
            kept.append(item)
    return tuple(kept), tuple(zeros), dropped, dust


def _dust_lines(label: str, dust: list[NearZeroNet]) -> list[str]:
    return [
        f"{label}: the stated legs on {record.date.isoformat()} cancel within "
        f"decimal-representation noise (raw net {record.raw_net!r}, gross legs "
        f"{record.gross!r}, |net| <= eps x sum|legs| = {record.bound!r}) and count as zero "
        "(contract §11.3)."
        for record in dust
    ]


def _noise_lines(label: str, dropped: list[NearZeroNet]) -> list[str]:
    return [
        f"{label}: the net {record.raw_net!r} on {record.date.isoformat()} is within the "
        f"float rounding bound 8 x n x eps x G = {record.bound!r} (G = {record.gross!r}, the "
        "gross magnitude of its terms), i.e. within rounding of zero; it is dropped from "
        "the series."
        for record in dropped
    ]


def _zero_net_line(label: str, dates: tuple[date, ...]) -> list[str]:
    if not dates:
        return []
    listed = ", ".join(on.isoformat() for on in dates)
    return [
        f"{label}: per-date nets that are zero (exactly, or within the decimal-representation "
        f"noise of their stated legs) on {listed} are dropped before solving."
    ]


def _solve(series: tuple[DatedAmount, ...], day_count: DayCountConvention, label: str) -> IrrResult:
    if len(series) < 2:
        raise ValueError(
            f"the {label} has fewer than two dates with a non-zero net amount, so no rate "
            "of return is defined"
        )
    return xirr(series, day_count=day_count)


def _fund_irr(
    resolved: ResolvedCashFlows, day_count: DayCountConvention, method: str
) -> tuple[IrrResult | None, list[str]]:
    """The fund IRR, or ``None`` with the reason when it is refused (contract §11.2)."""
    try:
        return fund_irr(resolved, day_count=day_count), []
    except ValueError as exc:
        return None, [
            f"{method}: the fund IRR is refused ({exc}); fund_irr, spread and log_spread are "
            "None, and every figure that does not need the fund IRR is still reported."
        ]


def _unique_rate(result: IrrResult | None) -> float | None:
    if result is None or result.status != "unique":
        return None
    return result.irr


def _spreads(fund: IrrResult | None, other: IrrResult | None) -> tuple[float | None, float | None]:
    """``(fund IRR - other IRR, difference of their log rates)`` when both are unique."""
    fund_rate, other_rate = _unique_rate(fund), _unique_rate(other)
    if fund is None or other is None or fund_rate is None or other_rate is None:
        return None, None
    return fund_rate - other_rate, fund.roots[0].log_rate - other.roots[0].log_rate


def _spread_lines(
    name: str,
    day_count: DayCountConvention,
    fund: IrrResult | None,
    other: IrrResult | None,
    spread: float | None,
) -> list[str]:
    if spread is not None:
        return [
            f"spread = fund IRR - {name} IRR and log_spread = ln(1 + fund IRR) - ln(1 + "
            f"{name} IRR), both under {day_count}."
        ]
    fund_status = "refused" if fund is None else f"status '{fund.status}'"
    other_status = "not solved" if other is None else f"status '{other.status}'"
    return [
        f"spread and log_spread are None: the fund IRR is {fund_status} and the {name} IRR "
        f"is {other_status}; they need two unique IRRs."
    ]


def ks_pme(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    *,
    lookup: IndexLookup,
    max_gap_days: int,
) -> KsPmeResult:
    """Kaplan-Schoar PME: ``(FV(D) + NAV_T) / FV(C)``.

    Above 1 the fund returned more than its contributions would have earned in the
    benchmark over the same dates; below 1, less. It needs no day count. Kaplan & Schoar
    (2005) used largely liquidated funds; the ``NAV_T`` term, a terminal distribution at
    ``T``, follows Harris, Jenkinson & Kaplan (2014, Journal of Finance 69(5)). It uses
    gross legs, so recallable distributions count in both ``FV(C)`` and ``FV(D)``.

    For per-date nets with exactly one sign change and a negative first net, KS-PME > 1
    if and only if Direct Alpha > 0. Without the negative first net the equivalence fails:
    nets ``+50`` then ``-100`` a year later at a constant index give KS-PME 0.5 and an IRR
    of +100%.
    """
    prepared = _prepare(resolved, benchmark, lookup, max_gap_days, "KS-PME")
    fv_c, fv_d, nav = prepared.fv_contributions, prepared.fv_distributions, prepared.nav
    term_by_term: list[str] = []
    numerator = fv_d + nav
    if math.isfinite(numerator):
        ratio = finite_ratio(numerator, fv_c, what="KS-PME = (FV(D) + NAV_T) / FV(C)")
    else:
        # FV(D) + NAV_T overflows, but the ratio may still be representable term by term.
        ratio = finite_fsum(
            (
                finite_ratio(fv_d, fv_c, what="KS-PME: FV(D) / FV(C)"),
                finite_ratio(nav, fv_c, what="KS-PME: NAV_T / FV(C)"),
            ),
            what="KS-PME = FV(D) / FV(C) + NAV_T / FV(C)",
        )
        term_by_term.append(
            "FV(D) + NAV_T overflows the float range, so KS-PME was computed term by term "
            "as FV(D) / FV(C) + NAV_T / FV(C)."
        )
    return KsPmeResult(
        **prepared.common_fields(),
        ks_pme=ratio,
        assumptions=[
            *prepared.assumptions,
            "KS-PME (Kaplan & Schoar 2005) = (FV(D) + NAV_T) / FV(C), FV(x) = sum x_t * "
            "I_T / I_t; above 1 the fund beat the benchmark over the same dates.",
            "Kaplan & Schoar used largely liquidated funds and no NAV; the residual value "
            "enters as a terminal distribution at T, following Harris, Jenkinson & Kaplan "
            "(2014, Journal of Finance 69(5)).",
            GROSS_LEGS_ASSUMPTION,
            *term_by_term,
        ],
        input_hash=prepared.input_hash("ks_pme", None),
    )


def direct_alpha(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    *,
    lookup: IndexLookup,
    max_gap_days: int,
    day_count: DayCountConvention,
) -> DirectAlphaResult:
    """Direct Alpha: the IRR of the fund flows compounded to ``as_of`` at the index return.

    The compounded series is ``(sum of signed flows on d) * g_d`` with ``g_d = I_T / I_d``,
    plus ``NAV_T`` at ``T``, netted per date and solved with ``ovf.pme.irr.xirr``. The
    as-of net is used as stated (``g_T = 1`` is not applied). Alpha is reported only when
    that IRR is proven unique; with no root or several roots it is ``None`` and the
    ``IrrResult`` says why.
    """
    day_count = check_convention(day_count)
    prepared = _prepare(resolved, benchmark, lookup, max_gap_days, "Direct Alpha")
    stated, zeros, _, dust = _net_series([*_signed(resolved), (prepared.as_of, prepared.nav)])
    series = tuple(
        item
        if item.date == prepared.as_of
        else DatedAmount(
            date=item.date,
            amount=finite_product(
                item.amount,
                prepared.growth[item.date],
                what=f"Direct Alpha: the compounded net on {item.date.isoformat()}",
            ),
        )
        for item in stated
    )
    result = _solve(series, day_count, "compounded (Direct Alpha) series")
    alpha = _unique_rate(result)
    assumptions = [
        *prepared.assumptions,
        "Direct Alpha (Gredil, Griffiths & Stucke 2014, SSRN working paper): IRR of "
        "{-C_t * I_T/I_t, +D_t * I_T/I_t, +NAV_T at T} netted per date, solved under "
        f"{day_count}; alpha_continuous = ln(1 + alpha), taken from the root's log_rate.",
        *_zero_net_line("Compounded series", zeros),
        *_dust_lines("Compounded series", dust),
    ]
    if alpha is None:
        assumptions.append(
            f"The compounded series has IRR status '{result.status}', so Direct Alpha is "
            f"undefined and reported as None: {result.proof}"
        )
    return DirectAlphaResult(
        **prepared.common_fields(),
        compounded_series=series,
        irr=result,
        alpha_annual_effective=alpha,
        # The root's own log rate: exact even where 1 + alpha underflows (contract §6).
        alpha_continuous=None if alpha is None else result.roots[0].log_rate,
        assumptions=assumptions,
        input_hash=prepared.input_hash("direct_alpha", day_count),
    )


def pme_plus(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    *,
    lookup: IndexLookup,
    max_gap_days: int,
    day_count: DayCountConvention,
) -> PmePlusResult:
    """PME+: scale distributions by ``s`` so the benchmark position ends at ``NAV_T``.

    ``s = (FV(C) - NAV_T) / FV(D)``. The PME+ IRR solves ``{-C_t, +s * D_t, +NAV_T at T}``
    and is compared with the fund IRR. ``FV(D) == 0`` leaves nothing to scale: ``s``, the
    PME+ series and its IRR are then ``None``/empty. ``s < 0`` (``NAV_T > FV(C)``) is
    flagged and withholds the spread: the scaled distributions become contributions, so
    the difference is not a performance difference (contract §11.4). A refused fund IRR is
    carried as ``fund_irr=None`` with the reason (§11.2). PME+ uses gross legs.

    A PME+ net that contains ``s * D_t`` is dropped when it is within the rounding bound
    ``8 * n * eps * G`` of zero, with ``G = C_t + |s| D_t (+ NAV_T at T)`` and ``n`` the
    number of flows plus two (the FV sums behind ``s``, ``NAV_T`` and the netting).
    """
    day_count = check_convention(day_count)
    prepared = _prepare(resolved, benchmark, lookup, max_gap_days, "PME+")
    fund, fund_lines = _fund_irr(resolved, day_count, "PME+")
    fv_c, fv_d, nav = prepared.fv_contributions, prepared.fv_distributions, prepared.nav
    assumptions = [
        *prepared.assumptions,
        "PME+ (Rouvinez 2003, Venture Capital Journal, Aug. 2003, pp. 34-38): s = (FV(C) - "
        "NAV_T) / FV(D) scales every distribution so the benchmark position ends at NAV_T; "
        f"the PME+ IRR solves {{-C_t, +s * D_t, +NAV_T at T}} under {day_count}.",
        "Known PME+ pathology: when NAV_T > FV(C), s < 0 and the scaled distributions become "
        "further contributions; the PME+ IRR is then not a return an index investor earns.",
        GROSS_LEGS_ASSUMPTION,
        *fund_lines,
    ]
    scale: float | None = None
    identity: float | None = None
    series: tuple[DatedAmount, ...] = ()
    plus: IrrResult | None = None
    dropped: list[NearZeroNet] = []
    if fv_d == 0:
        assumptions.append(
            "FV(D) is zero (no distributions), so there is nothing to scale: s, the PME+ "
            "series, the PME+ IRR and the spread are None."
        )
    else:
        scale = finite_ratio(fv_c - nav, fv_d, what="PME+: s = (FV(C) - NAV_T) / FV(D)")
        identity = finite_fsum(
            (fv_c, -finite_product(scale, fv_d, what="PME+: s * FV(D)"), -nav),
            what="PME+: FV(C) - s * FV(D) - NAV_T",
        )
        stated = [
            (flow.date, -flow.amount) for flow in resolved.flows if flow.kind == "contribution"
        ]
        scaled = [
            (
                flow.date,
                finite_product(
                    scale, flow.amount, what=f"PME+: s * D_t on {flow.date.isoformat()}"
                ),
            )
            for flow in resolved.flows
            if flow.kind == "distribution"
        ]
        contributions, distributions = _gross_by_date(resolved, "PME+")
        steps = len(resolved.flows) + 2
        computed = {
            on: (
                finite_fsum(
                    (
                        contributions.get(on, 0.0),
                        abs(scale) * paid_out,
                        nav if on == prepared.as_of else 0.0,
                    ),
                    what=f"PME+: the gross magnitude of the net on {on.isoformat()}",
                ),
                steps,
            )
            for on, paid_out in distributions.items()
        }
        series, zeros, dropped, dust = _net_series(
            [*stated, (prepared.as_of, nav)], scaled, computed
        )
        plus = _solve(series, day_count, "PME+ series")
        assumptions.extend(_zero_net_line("PME+ series", zeros))
        assumptions.extend(_noise_lines("PME+ series", dropped))
        assumptions.extend(_dust_lines("PME+ series", dust))
    if scale is not None and scale < 0:
        spread: float | None = None
        log_spread: float | None = None
        assumptions.append(
            f"s = {scale!r} < 0: NAV_T exceeds FV(C), the pathology above. spread and "
            "log_spread are None: with s < 0 the scaled distributions turn into further "
            "contributions (Gredil, Griffiths & Stucke 2014), so the difference to the fund "
            "IRR is not a performance difference; the PME+ IRR stays attached."
        )
    else:
        spread, log_spread = _spreads(fund, plus)
        assumptions.extend(_spread_lines("PME+", day_count, fund, plus, spread))
    return PmePlusResult(
        **prepared.common_fields(),
        scale=scale,
        scale_negative=scale is not None and scale < 0,
        identity_residual=identity,
        pme_plus_series=series,
        pme_plus_irr=plus,
        fund_irr=fund,
        spread=spread,
        log_spread=log_spread,
        dropped_computed_nets=tuple(dropped),
        assumptions=assumptions,
        input_hash=prepared.input_hash("pme_plus", day_count),
    )


def ln_pme(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    *,
    lookup: IndexLookup,
    max_gap_days: int,
    day_count: DayCountConvention,
) -> LnPmeResult:
    """Long–Nickels (LN) PME, the index comparison method (ICM).

    "LN" names Long & Nickels (1996), not a natural logarithm. On every flow date in
    order, and then at ``as_of``, the index position is grown and the date's flows
    applied: ``V_d = V_prev * (I_d / I_prev) + C_d - D_d``. The terminal ``V_T`` is checked
    against the closed form ``FV(C) - FV(D)``. The ICM IRR solves
    ``{-C_t, +D_t, +V_T at T}`` and is compared with the fund IRR; a refused fund IRR is
    carried as ``fund_irr=None`` with the reason (contract §11.2).

    ``G_d``, the gross flows grown the same way, is the scale of the terms whose signed
    sum is ``V_d``. At step ``n`` (1-based) a position below ``-8 * n * eps * G_d`` is
    short (``went_short``, the method's documented pathology, reported with its first date
    and the minimum position); a smaller negative is float rounding of zero. The terminal
    ICM net, which contains ``V_T``, is dropped when within ``8 * (N + 1) * eps * G_T`` of
    zero, ``N`` the number of steps.
    """
    method = "Long-Nickels PME"
    day_count = check_convention(day_count)
    prepared = _prepare(resolved, benchmark, lookup, max_gap_days, method)
    fund, fund_lines = _fund_irr(resolved, day_count, method)
    contributions, distributions = _gross_by_date(resolved, method)
    path: list[IcmStep] = []
    first_short: date | None = None
    position = 0.0
    gross = 0.0
    previous: IndexLookupRecord | None = None
    previous_date: date | None = None
    for step, on in enumerate(sorted(prepared.records), start=1):
        record = prepared.records[on]
        if previous is None or previous_date is None:
            grown = gross_grown = 0.0
        else:
            ratio = finite_ratio(
                record.level,
                previous.level,
                what=f"{method}: the index growth I_d / I_prev from "
                f"{previous_date.isoformat()} to {on.isoformat()}",
            )
            grown = finite_product(
                position, ratio, what=f"{method}: the position grown to {on.isoformat()}"
            )
            gross_grown = finite_product(
                gross, ratio, what=f"{method}: the gross flows grown to {on.isoformat()}"
            )
        contribution = contributions.get(on, 0.0)
        distribution = distributions.get(on, 0.0)
        position = finite_fsum(
            (grown, contribution, -distribution),
            what=f"{method}: the index position on {on.isoformat()}",
        )
        gross = finite_fsum(
            (gross_grown, contribution, distribution),
            what=f"{method}: the gross flows grown to {on.isoformat()}",
        )
        if first_short is None and position < -_rounding_bound(step, gross):
            first_short = on
        path.append(
            IcmStep(
                date=on,
                index_level=record.level,
                position_grown=grown,
                contribution=contribution,
                distribution=distribution,
                position_after=position,
            )
        )
        previous, previous_date = record, on
    terminal = path[-1].position_after
    closed_form = prepared.fv_contributions - prepared.fv_distributions
    min_position = min(step.position_after for step in path)
    # The terminal net contains V_T; G_T (``gross``) is the gross flows grown to T.
    series, zeros, dropped, dust = _net_series(
        _signed(resolved),
        [(prepared.as_of, terminal)],
        {prepared.as_of: (gross, len(path) + 1)},
    )
    icm = _solve(series, day_count, "ICM series")
    spread, log_spread = _spreads(fund, icm)
    assumptions = [
        *prepared.assumptions,
        "Long-Nickels ICM (Long & Nickels 1996): V_d = V_prev * (I_d / I_prev) + C_d - D_d "
        "on each flow date in order, rolled to T; the ICM IRR solves {-C_t, +D_t, +V_T at "
        f"T}} under {day_count}. V_T is reconciled with the closed form FV(C) - FV(D).",
        "Known ICM pathology (Long & Nickels 1996, fn. 5): distributions larger than the "
        "index position drive it negative, a short benchmark position; the ICM IRR then "
        "describes a levered short, not an investable index holding.",
        f"A position below -8 x n x eps x G_d (eps = {_EPS!r}, n = the step's number in "
        "the recursion, G_d = the gross flows grown to that date), the float rounding bound "
        "of V_d, counts as short; a smaller negative is rounding of zero.",
        *fund_lines,
        *_zero_net_line("ICM series", zeros),
        *_noise_lines("ICM series", dropped),
        *_dust_lines("ICM series", dust),
    ]
    if first_short is not None:
        assumptions.append(
            f"The index position went short on {first_short.isoformat()} (minimum "
            f"{min_position!r}); read the ICM IRR and spread with the pathology above in "
            "mind."
        )
    assumptions.extend(_spread_lines("ICM", day_count, fund, icm, spread))
    return LnPmeResult(
        **prepared.common_fields(),
        path=tuple(path),
        terminal_value_recursive=terminal,
        terminal_value_closed_form=closed_form,
        reconciliation_residual=terminal - closed_form,
        went_short=first_short is not None,
        first_short_date=first_short,
        min_position=min_position,
        icm_series=series,
        icm_irr=icm,
        fund_irr=fund,
        spread=spread,
        log_spread=log_spread,
        dropped_computed_nets=tuple(dropped),
        assumptions=assumptions,
        input_hash=prepared.input_hash("ln_pme", day_count),
    )
