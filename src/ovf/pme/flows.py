"""Signed dated fund cash flows, the residual value, and their resolution at a date.

Perspective is the investor (LP) in the fund. A *contribution* is cash the LP pays in, a
*distribution* is cash the LP receives, and the *NAV* is the LP's residual value in the
fund at a date. Inputs are typed: a kind and a strictly positive amount. Discounting uses
the signed form: contribution ``-amount``, distribution ``+amount``, residual ``+value``
dated at ``as_of``.

``resolve`` is the one step between stated inputs and every metric. It fixes the
valuation date, checks that the flows and the NAV are consistent with it, decides where
the residual value comes from (reported at ``as_of``, rolled forward from an earlier NAV
under a stated policy, or absent), and nets same-date amounts into the per-date series
that IRR and PME solvers discount. Nothing is truncated, interpolated or guessed: an
inconsistent input is refused with ``ValueError``.

Timing: a NAV dated ``d`` is end of day, after every flow dated ``d``. Conventions are
in ``docs/pme.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, ConfigDict, Field, field_validator

from ovf.core.types import FinancialBaseModel, Money

ENGINE_VERSION = "pme-v1"

FlowKind = Literal["contribution", "distribution"]
FlowBasis = Literal["net_lp", "gross_fund"]
StaleNavPolicy = Literal["refuse", "roll_forward_cash_adjusted"]
NavSource = Literal["reported_at_as_of", "rolled_forward", "none"]

_KIND_ORDER: dict[str, int] = {"contribution": 0, "distribution": 1}

_BASIS_TEXT: dict[str, str] = {
    "net_lp": (
        "Basis: net_lp (LP-level flows after management fees and carried interest, as "
        "reported to the investor)."
    ),
    "gross_fund": (
        "Basis: gross_fund (fund-level investment flows before management fees and "
        "carried interest); results are not what an LP earned."
    ),
}


def _refuse_datetime(value: object) -> object:
    """Refuse a ``datetime`` (midnight and timezone-aware included) for a date field.

    Dates here carry no intraday time; pydantic would otherwise truncate a midnight
    ``datetime`` to its date silently.
    """
    if isinstance(value, datetime):
        raise ValueError(
            f"a date field must be a datetime.date, not a datetime ({value!r}); there is no "
            "intraday time here"
        )
    return value


PlainDate = Annotated[date, BeforeValidator(_refuse_datetime)]
"""A calendar date that refuses ``datetime`` before any coercion (contract §2, §13.6).

Every date field of every ``ovf.pme`` model uses it, records and results included."""


class CashFlow(FinancialBaseModel):
    """One contribution or distribution between the LP and the fund.

    ``amount`` is strictly positive: the sign comes from ``kind``. A zero amount is not a
    flow and is refused. ``flow_id`` is optional metadata (e.g. a capital-call notice
    number); two flows with the same non-``None`` id are refused by ``FundCashFlows``.
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    kind: FlowKind
    amount: float = Field(gt=0.0)
    flow_id: str | None = None

    @property
    def signed_amount(self) -> float:
        """``-amount`` for a contribution, ``+amount`` for a distribution."""
        return -self.amount if self.kind == "contribution" else self.amount


class NavObservation(FinancialBaseModel):
    """The LP's residual value in the fund at the end of ``date``."""

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    value: Money


class DatedAmount(FinancialBaseModel):
    """A signed, finite amount at a date: the unit of every discounted series."""

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    amount: float


class NearZeroNet(FinancialBaseModel):
    """A per-date net dropped as rounding of an exact zero, with the bound that dropped it.

    ``raw_net`` is the net as computed and ``gross`` the gross magnitude of the terms that
    produced it. ``bound`` is the threshold ``|raw_net|`` did not exceed: ``eps * gross``
    for stated legs within decimal-representation noise (contract §11.3), or
    ``8 * n * eps * G`` for a computed net (contract §9). Report flags are derived from
    these records, never from assumption text (contract §13.2).
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    raw_net: float
    gross: float = Field(ge=0.0)
    bound: float = Field(ge=0.0)


def _canonical_key(flow: CashFlow) -> tuple[date, int, float, bool, str]:
    return (
        flow.date,
        _KIND_ORDER[flow.kind],
        flow.amount,
        flow.flow_id is not None,
        flow.flow_id or "",
    )


class FundCashFlows(FinancialBaseModel):
    """A fund's stated flows, currency, basis and latest NAV, as the LP sees them.

    ``flows`` is stored in canonical order (date, contributions before distributions,
    amount, flow_id) whatever the input order, so two orderings of the same flows are the
    same object and hash identically. Input order carries no meaning. ``nav`` is ``None``
    when no residual valuation is available; a fully realised fund states
    ``NavObservation(date=as_of, value=0)`` instead.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    basis: FlowBasis
    flows: tuple[CashFlow, ...] = Field(min_length=1)
    nav: NavObservation | None

    @field_validator("flows")
    @classmethod
    def _canonical_flows(cls, flows: tuple[CashFlow, ...]) -> tuple[CashFlow, ...]:
        seen: set[str] = set()
        for flow in flows:
            if flow.flow_id is None:
                continue
            if flow.flow_id in seen:
                raise ValueError(
                    f"duplicate flow_id {flow.flow_id!r}; each non-None flow_id must name "
                    "exactly one flow"
                )
            seen.add(flow.flow_id)
        return tuple(sorted(flows, key=_canonical_key))

    def through(self, d: date) -> tuple[FundCashFlows, tuple[CashFlow, ...]]:
        """The fund cut at ``d``: flows dated on or before ``d``, and the flows left out.

        This is the explicit, listed truncation that ``resolve`` never performs (R2-7):
        measuring at a quarter-end NAV date while flows have been booked since means
        choosing to leave those flows out, and the excluded flows are returned so the
        choice stays visible. The NAV is kept when dated on or before ``d``; a NAV dated
        after ``d`` is refused, since it cannot be the value at ``d``. Name, currency and
        basis are unchanged. A cut before the first flow is refused (a fund needs a flow).
        """
        if isinstance(d, datetime) or not isinstance(d, date):
            raise ValueError(f"d must be a datetime.date, got {type(d).__name__}")
        cut = d.isoformat()
        if self.nav is not None and self.nav.date > d:
            raise ValueError(
                f"the NAV is dated {self.nav.date.isoformat()}, after {cut}; a NAV after the "
                f"cut cannot be the value at {cut}, so state the NAV at or before {cut}"
            )
        kept = tuple(flow for flow in self.flows if flow.date <= d)
        excluded = tuple(flow for flow in self.flows if flow.date > d)
        if not kept:
            raise ValueError(
                f"no flow is dated on or before {cut} (the first is "
                f"{self.flows[0].date.isoformat()}); a fund needs at least one flow"
            )
        fund = FundCashFlows(
            name=self.name, currency=self.currency, basis=self.basis, flows=kept, nav=self.nav
        )
        return fund, excluded


class NavRollForward(FinancialBaseModel):
    """How a stale NAV was carried to ``as_of`` with zero return assumed in between."""

    model_config = ConfigDict(frozen=True)

    reported_date: PlainDate
    reported_value: float
    contributions_after: float
    distributions_after: float
    rolled_value: float


class ResolvedCashFlows(FinancialBaseModel):
    """Flows fixed at a valuation date: the only input every metric consumes.

    ``net_by_date`` is the discounting series: one signed amount per date (flows netted,
    the residual added at ``as_of``), zero nets dropped and listed in ``netted_to_zero``,
    dates ascending. ``paid_in`` and ``distributed`` are gross sums for the multiples.
    """

    model_config = ConfigDict(frozen=True)

    fund_name: str
    currency: str
    basis: FlowBasis
    as_of: PlainDate
    flows: tuple[CashFlow, ...]
    paid_in: float
    distributed: float
    residual_value: float | None
    nav_source: NavSource
    nav_roll_forward: NavRollForward | None
    net_by_date: tuple[DatedAmount, ...]
    netted_to_zero: tuple[PlainDate, ...]
    stated_nets_within_noise: tuple[NearZeroNet, ...]
    assumptions: list[str]
    input_hash: str
    engine_version: str = ENGINE_VERSION


def canonical_hash(payload: Mapping[str, Any]) -> str:
    """sha256 of ``payload`` as canonical JSON (``sort_keys``, no NaN, dates as ISO text).

    Pass ``model_dump(mode="json")`` output for models so dates are already ISO strings.
    ``-0.0`` is normalised to ``0.0`` at every depth: the two are equal as numbers and as
    model fields, so they must hash equally.
    """
    text = json.dumps(
        _without_signed_zero(payload), sort_keys=True, allow_nan=False, default=_json_default
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _without_signed_zero(value: Any) -> Any:
    if isinstance(value, float) and value == 0.0:
        return 0.0
    if isinstance(value, Mapping):
        return {key: _without_signed_zero(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_without_signed_zero(item) for item in value]
    return value


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"cannot hash a {type(value).__name__}")


def finite_fsum(values: Iterable[float], *, what: str) -> float:
    """``math.fsum(values)``, refused with ``ValueError`` when the sum leaves the float range.

    ``fsum`` raises ``OverflowError`` on an intermediate overflow (e.g. ``1e308 + 1e308``);
    that and a non-finite total are reported as a ``ValueError`` naming ``what``.
    """
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise ValueError(
            f"{what} overflows the float range (intermediate overflow in the sum)"
        ) from exc
    if not math.isfinite(total):
        raise ValueError(f"{what} overflows the float range")
    return total


def finite_product(value: float, factor: float, *, what: str) -> float:
    """``value * factor``, refused when it overflows or when a non-zero product underflows.

    A product of two non-zero operands below the smallest normal float
    (``sys.float_info.min``) has lost precision or vanished; it is refused rather than
    reported as zero. A zero operand gives an exact zero, which is not an underflow.
    """
    product = value * factor
    if not math.isfinite(product):
        raise ValueError(f"{what} = {value!r} x {factor!r} overflows the float range")
    if value != 0.0 and factor != 0.0 and abs(product) < sys.float_info.min:
        raise ValueError(
            f"{what} = {value!r} x {factor!r} underflows below the smallest normal float "
            f"({sys.float_info.min!r})"
        )
    return product


def finite_ratio(numerator: float, denominator: float, *, what: str) -> float:
    """``numerator / denominator``, with the same range checks as ``finite_product``.

    A zero numerator gives an exact zero, which is not an underflow. The denominator must
    be non-zero; that is the caller's duty.
    """
    ratio = numerator / denominator
    if not math.isfinite(ratio):
        raise ValueError(f"{what} = {numerator!r} / {denominator!r} overflows the float range")
    if numerator != 0.0 and abs(ratio) < sys.float_info.min:
        raise ValueError(
            f"{what} = {numerator!r} / {denominator!r} underflows below the smallest normal "
            f"float ({sys.float_info.min!r})"
        )
    return ratio


def _grouped(amounts: list[tuple[date, float]]) -> dict[date, list[float]]:
    grouped: dict[date, list[float]] = {}
    for day, amount in amounts:
        grouped.setdefault(day, []).append(amount)
    return grouped


def _representation_bound(legs: list[float]) -> float | None:
    """``eps * sum|legs|`` for ``n >= 2`` legs of mixed sign, else ``None`` (contract §11.3)."""
    if len(legs) < 2 or not (any(leg > 0 for leg in legs) and any(leg < 0 for leg in legs)):
        return None
    # eps * |leg| summed term by term cannot overflow even when sum|legs| would.
    return math.fsum(sys.float_info.epsilon * abs(leg) for leg in legs)


def near_zero_nets(amounts: list[tuple[date, float]]) -> list[NearZeroNet]:
    """Dates whose stated legs cancel within decimal-representation noise (contract §11.3).

    Cents stated as binary floats rarely cancel exactly (``300000.30 - 100000.10 -
    200000.20 = -2.9e-11``). Each leg's binary representation error is at most
    ``eps/2 * |leg|``, so a date with ``n >= 2`` legs of mixed sign whose ``fsum`` net is
    non-zero but at most ``sys.float_info.epsilon * sum|legs|`` is indistinguishable from
    a net of zero. Returns a ``NearZeroNet`` (date, raw net, ``sum|legs|``, bound) for each
    such date, ascending; ``net_stated_by_date`` treats these dates as zero. A net above
    the bound is kept, however small.
    """
    found: list[NearZeroNet] = []
    grouped = _grouped(amounts)
    for day in sorted(grouped):
        legs = grouped[day]
        net = finite_fsum(legs, what=f"the net amount on {day.isoformat()}")
        bound = _representation_bound(legs)
        if net != 0.0 and bound is not None and abs(net) <= bound:
            gross = finite_fsum(
                (abs(leg) for leg in legs), what=f"the gross legs on {day.isoformat()}"
            )
            found.append(NearZeroNet(date=day, raw_net=net, gross=gross, bound=bound))
    return found


def net_by_date(amounts: list[tuple[date, float]]) -> tuple[list[DatedAmount], list[date]]:
    """Net signed ``(date, amount)`` pairs per date with ``math.fsum``, exactly.

    Returns the non-zero nets in ascending date order and the dates whose net is exactly
    zero. ``fsum`` is correctly rounded, so a net is zero exactly when the amounts cancel
    exactly. This is the generic numeric layer (``xirr``, ``npv``); stated fund flows go
    through ``net_stated_by_date``, which adds the decimal-representation rule of contract
    §11.3. A net outside the float range is refused with ``ValueError``.
    """
    grouped = _grouped(amounts)
    nets: list[DatedAmount] = []
    zeros: list[date] = []
    for day in sorted(grouped):
        net = finite_fsum(grouped[day], what=f"the net amount on {day.isoformat()}")
        if net == 0.0:
            zeros.append(day)
        else:
            nets.append(DatedAmount(date=day, amount=net))
    return nets, zeros


def net_stated_by_date(
    amounts: list[tuple[date, float]],
) -> tuple[list[DatedAmount], list[date], list[NearZeroNet]]:
    """Net stated fund amounts per date: ``net_by_date`` plus contract §11.3.

    A date whose ``n >= 2`` stated legs of mixed sign cancel within decimal-representation
    noise (``|net| <= eps * sum|legs|``, see ``near_zero_nets``) counts as zero. Returns
    ``(nets, zero_dates, near_zero)``: the kept nets ascending, every date counted as zero
    (exact zeros and near-zero dates) ascending, and a ``NearZeroNet`` record for each
    near-zero date.
    """
    nets, zeros = net_by_date(amounts)
    near_zero = near_zero_nets(amounts)
    near_dates = {record.date for record in near_zero}
    kept = [item for item in nets if item.date not in near_dates]
    return kept, sorted([*zeros, *near_dates]), near_zero


def resolve(fund: FundCashFlows, *, as_of: date, stale_nav: StaleNavPolicy) -> ResolvedCashFlows:
    """Fix ``fund`` at ``as_of`` under a stated stale-NAV policy.

    Rules, each refused with ``ValueError`` rather than repaired:

    1. Every flow must be dated on or before ``as_of`` (flows are never truncated), and
       ``as_of`` must not precede the first flow.
    2. ``nav is None``: no residual value; ``nav_source="none"``.
    3. A NAV dated after ``as_of`` is refused.
    4. A NAV dated ``as_of`` is the residual value (``nav_source="reported_at_as_of"``).
    5. A NAV dated before ``as_of`` is refused under ``stale_nav="refuse"``. Under
       ``"roll_forward_cash_adjusted"`` the residual is NAV + contributions -
       distributions dated in ``(nav.date, as_of]``, zero return assumed in between.
       Flows dated on the NAV date are already in it (end-of-day NAV). A negative rolled
       value is refused: distributions after the NAV date exceeding it mean the inputs
       are inconsistent.
    6. ``net_by_date`` nets flows per date and adds the residual at ``as_of``.
    """
    if not isinstance(fund, FundCashFlows):
        raise ValueError(f"fund must be a FundCashFlows, got {type(fund).__name__}")
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise ValueError(f"as_of must be a datetime.date, got {type(as_of).__name__}")
    if stale_nav not in ("refuse", "roll_forward_cash_adjusted"):
        raise ValueError(
            f"unknown stale_nav policy {stale_nav!r}; expected 'refuse' or "
            "'roll_forward_cash_adjusted'"
        )

    flows = fund.flows
    first, last = flows[0].date, flows[-1].date
    if as_of < first:
        raise ValueError(
            f"as_of {as_of.isoformat()} is before the first flow ({first.isoformat()}); "
            "choose a valuation date on or after the first flow"
        )
    late = [f for f in flows if f.date > as_of]
    if late:
        raise ValueError(
            f"{len(late)} flow(s) dated after as_of {as_of.isoformat()} (latest "
            f"{last.isoformat()}); flows are never truncated: move as_of to "
            f"{last.isoformat()} or later, or remove those flows explicitly"
        )

    nav = fund.nav
    roll: NavRollForward | None = None
    residual: float | None
    source: NavSource
    if nav is None:
        residual, source = None, "none"
        nav_line = (
            "NAV source: none. No residual valuation was stated, so every metric that "
            "needs a value at as_of (RVPI, TVPI, IRR, PME) is undefined; a fully realised "
            "fund must state NAV 0 at as_of."
        )
    elif nav.date > as_of:
        raise ValueError(
            f"NAV dated {nav.date.isoformat()} is after as_of {as_of.isoformat()}; a "
            "valuation after the as_of date cannot be used"
        )
    elif nav.date == as_of:
        residual, source = float(nav.value), "reported_at_as_of"
        nav_line = (
            f"NAV source: reported at as_of ({as_of.isoformat()}), value {nav.value!r} "
            f"{fund.currency}."
        )
    elif stale_nav == "refuse":
        raise ValueError(
            f"NAV is dated {nav.date.isoformat()}, before as_of {as_of.isoformat()}, and "
            "stale_nav='refuse'; state a NAV at as_of, set as_of to the NAV date, or pass "
            "stale_nav='roll_forward_cash_adjusted'"
        )
    else:
        after = [f for f in flows if nav.date < f.date <= as_of]
        contributed = [f.amount for f in after if f.kind == "contribution"]
        distributed_after = [f.amount for f in after if f.kind == "distribution"]
        rolled = finite_fsum(
            [nav.value, *contributed, *(-a for a in distributed_after)],
            what=f"the NAV rolled forward from {nav.date.isoformat()} to {as_of.isoformat()}",
        )
        if rolled < 0:
            raise ValueError(
                f"rolling NAV {nav.value!r} from {nav.date.isoformat()} to "
                f"{as_of.isoformat()} gives {rolled!r}: distributions after the NAV date "
                "exceed the NAV plus contributions, so the inputs are inconsistent"
            )
        roll = NavRollForward(
            reported_date=nav.date,
            reported_value=float(nav.value),
            contributions_after=finite_fsum(
                contributed, what="the contributions after the NAV date"
            ),
            distributions_after=finite_fsum(
                distributed_after, what="the distributions after the NAV date"
            ),
            rolled_value=rolled,
        )
        residual, source = rolled, "rolled_forward"
        nav_line = (
            f"NAV source: rolled forward with zero return from {nav.date.isoformat()} "
            f"(reported {nav.value!r}) to as_of {as_of.isoformat()}: + contributions "
            f"{roll.contributions_after!r} - distributions {roll.distributions_after!r} "
            f"dated in ({nav.date.isoformat()}, {as_of.isoformat()}] = {rolled!r} "
            f"{fund.currency}. Any market movement in that window is ignored."
        )

    signed = [(f.date, f.signed_amount) for f in flows]
    if residual:  # a zero residual adds nothing to the discounting series
        signed.append((as_of, residual))
    nets, zeros, noise = net_stated_by_date(signed)
    noise_dates = {record.date for record in noise}
    exact_zeros = [day for day in zeros if day not in noise_dates]

    assumptions = [
        f"Perspective: the investor (LP) in fund {fund.name!r}; contributions are cash "
        "paid in, distributions are cash received, NAV is the LP's residual value.",
        "Sign convention for discounting: contribution -> -amount, distribution -> "
        f"+amount, residual value -> +value dated at as_of ({as_of.isoformat()}).",
        "NAV timing: a NAV dated d is end of day, after every flow dated d.",
        _BASIS_TEXT[fund.basis],
        f"Currency: {fund.currency}; every amount is in this currency (no FX).",
        nav_line,
        "Same-date amounts are netted into one signed amount per date for discounting; "
        "gross contribution and distribution sums are kept for the multiples.",
    ]
    if exact_zeros:
        assumptions.append(
            "Dates whose net is exactly zero are dropped from the discounting series: "
            + ", ".join(d.isoformat() for d in exact_zeros)
            + "."
        )
    if noise:
        assumptions.append(
            "Dates whose stated legs cancel within decimal-representation noise (|net| <= "
            f"eps x sum|legs|, eps = {sys.float_info.epsilon!r}; each leg's binary "
            "representation error is at most eps/2 x |leg|) are treated as zero and dropped "
            "from the discounting series: "
            + ", ".join(
                f"{record.date.isoformat()} (raw net {record.raw_net!r}, gross legs "
                f"{record.gross!r})"
                for record in noise
            )
            + "."
        )

    return ResolvedCashFlows(
        fund_name=fund.name,
        currency=fund.currency,
        basis=fund.basis,
        as_of=as_of,
        flows=flows,
        paid_in=finite_fsum(
            (f.amount for f in flows if f.kind == "contribution"),
            what="paid-in capital (the sum of contributions)",
        ),
        distributed=finite_fsum(
            (f.amount for f in flows if f.kind == "distribution"),
            what="distributed capital (the sum of distributions)",
        ),
        residual_value=residual,
        nav_source=source,
        nav_roll_forward=roll,
        net_by_date=tuple(nets),
        netted_to_zero=tuple(zeros),
        stated_nets_within_noise=tuple(noise),
        assumptions=assumptions,
        input_hash=canonical_hash(
            {
                "method": "resolve",
                "fund": fund.model_dump(mode="json"),
                "as_of": as_of.isoformat(),
                "stale_nav": stale_nav,
            }
        ),
    )
