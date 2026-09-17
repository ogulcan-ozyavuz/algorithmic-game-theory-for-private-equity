"""Independent exact-arithmetic PME oracle, written from pme-contract sections 3-12.

No production imports. Fractions carry cash, indices and day counts exactly; all
transcendentals use a private 60-digit Decimal context. IRR uses a dense log-rate
grid and bisection, never derivative-root/Rolle recursion. Descartes' bound is the
contract's exponential-sum version (Jameson, Math. Gazette 90 (2006), 223-234).
Finding fewer crossings than that bound is explicitly inconclusive, except for
the elementary negative-discriminant quadratic certificate used by PME-F4.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Literal

DayCount = Literal["ACT/365F", "ACT/365.25", "ACT/ACT-ISDA"]
Number = Fraction | Decimal | int | str
Series = tuple[tuple[date, Fraction], ...]
PRECISION = 60


def dec(value: Number) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        if isinstance(value, Fraction):
            return Decimal(value.numerator) / Decimal(value.denominator)
        return Decimal(value)


def year_fraction(start: date, end: date, *, convention: DayCount) -> Fraction:
    if end < start:
        return -year_fraction(end, start, convention=convention)
    if convention == "ACT/365F":
        return Fraction((end - start).days, 365)
    if convention == "ACT/365.25":
        return Fraction(4 * (end - start).days, 1461)
    if convention != "ACT/ACT-ISDA":
        raise ValueError("unknown day count")
    result = Fraction(0)
    cursor = start
    while cursor < end:
        year = cursor.year
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        boundary = min(end, date(year + 1, 1, 1)) if year < 9999 else end
        result += Fraction((boundary - cursor).days, 366 if leap else 365)
        cursor = boundary
    return result


def net(amounts: Series) -> tuple[Series, tuple[date, ...]]:
    totals: dict[date, Fraction] = defaultdict(Fraction)
    for on, amount in amounts:
        totals[on] += Fraction(amount)
    ordered = sorted(totals.items())
    return tuple((d, a) for d, a in ordered if a), tuple(d for d, a in ordered if not a)


@dataclass(frozen=True)
class Flow:
    date: date
    kind: Literal["contribution", "distribution"]
    amount: Fraction

    def __post_init__(self) -> None:
        if self.kind not in ("contribution", "distribution") or self.amount <= 0:
            raise ValueError("typed flows require a positive amount and valid kind")

    @property
    def signed(self) -> Fraction:
        return -self.amount if self.kind == "contribution" else self.amount


@dataclass(frozen=True)
class Resolved:
    flows: tuple[Flow, ...]
    as_of: date
    paid_in: Fraction
    distributed: Fraction
    residual: Fraction | None
    nav_source: str
    net_by_date: Series
    netted_to_zero: tuple[date, ...]
    contributions_after: Fraction
    distributions_after: Fraction
    nav_observation_date: date | None


def resolve(
    flows: tuple[Flow, ...],
    *,
    as_of: date,
    nav: tuple[date, Fraction] | None,
    stale_nav: Literal["refuse", "roll_forward_cash_adjusted"],
) -> Resolved:
    if not flows or any(f.date > as_of for f in flows):
        raise ValueError("require flows, all on or before as_of")
    if stale_nav not in ("refuse", "roll_forward_cash_adjusted"):
        raise ValueError("unknown NAV policy")
    flows = tuple(sorted(flows, key=lambda f: (f.date, f.kind, f.amount)))
    paid = sum((f.amount for f in flows if f.kind == "contribution"), Fraction())
    distributed = sum((f.amount for f in flows if f.kind == "distribution"), Fraction())
    residual = None
    source = "none"
    calls_after = dists_after = Fraction()
    if nav is not None:
        on, value = nav
        if on > as_of or value < 0:
            raise ValueError("NAV must be nonnegative and on or before as_of")
        residual = value
        source = "reported_at_as_of"
        if on < as_of:
            if stale_nav == "refuse":
                raise ValueError("stale NAV requires explicit roll-forward policy")
            calls_after = sum(
                (f.amount for f in flows if f.date > on and f.kind == "contribution"),
                Fraction(),
            )
            dists_after = sum(
                (f.amount for f in flows if f.date > on and f.kind == "distribution"),
                Fraction(),
            )
            residual += calls_after - dists_after
            source = "rolled_forward"
            if residual < 0:
                raise ValueError("negative rolled NAV: inconsistent cash adjustments")
    signed = tuple((f.date, f.signed) for f in flows)
    if residual:
        signed += ((as_of, residual),)
    amounts, zeros = net(signed)
    return Resolved(
        flows,
        as_of,
        paid,
        distributed,
        residual,
        source,
        amounts,
        zeros,
        calls_after,
        dists_after,
        nav[0] if nav is not None else None,
    )


@dataclass(frozen=True)
class Irr:
    status: str
    roots: tuple[Decimal, ...]
    log_roots: tuple[Decimal, ...]
    kinds: tuple[str, ...]
    complete: bool
    sign_changes: int
    grid_inconclusive: bool
    proof: str

    @property
    def irr(self) -> Decimal | None:
        return self.roots[0] if self.status == "unique" else None


def npv(amounts: Series, *, rate: Number, day_count: DayCount, t0: date) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        rate_d = dec(rate)
        if rate_d <= -1:
            raise ValueError("rate must exceed -1")
        delta = (1 + rate_d).ln()
        return sum(
            (
                dec(a) * (-delta * dec(year_fraction(t0, d, convention=day_count))).exp()
                for d, a in amounts
            ),
            Decimal(),
        )


def xirr(amounts: Series, *, day_count: DayCount) -> Irr:
    """Scan [-12, 12] at 0.01 spacing; bisect crossings to 40 decimal delta places.

    Bound exhaustion proves completeness, not grid resolution. A missed pair,
    off-grid tangent, or out-of-range root yields grid_inconclusive=True and
    status=undetermined. Exact sampled tangents follow the contract's deliberately
    conservative status even where this rational oracle knows the double root.
    """
    amounts, _ = net(amounts)
    if len(amounts) < 2:
        raise ValueError("IRR requires at least two nonzero distinct dates")
    signs = [a > 0 for _, a in amounts]
    changes = sum(a != b for a, b in zip(signs, signs[1:], strict=False))
    if changes == 0:
        return Irr("none", (), (), (), True, 0, False, "no coefficient sign changes")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        times_f = [year_fraction(amounts[0][0], d, convention=day_count) for d, _ in amounts]
        times = [dec(t) for t in times_f]
        coeffs = [dec(a) for _, a in amounts]

        def evaluate(delta: Decimal) -> Decimal:
            return sum(
                (a * (-delta * t).exp() for a, t in zip(coeffs, times, strict=True)), Decimal()
            )

        def bisect(lo: Decimal, hi: Decimal) -> Decimal:
            flo = evaluate(lo)
            while hi - lo > Decimal("1e-42"):
                mid = (lo + hi) / 2
                fm = evaluate(mid)
                if not fm:
                    return mid
                if (fm > 0) == (flo > 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            return (lo + hi) / 2

        # Independent algebraic certificate; no root finder/derivative recursion.
        if len(amounts) == 3 and times_f[2] == 2 * times_f[1]:
            a, b, c = (v for _, v in amounts)
            if b * b - 4 * a * c < 0:
                return Irr(
                    "none",
                    (),
                    (),
                    (),
                    True,
                    changes,
                    False,
                    "quadratic in exp(-delta*t) has negative discriminant",
                )

        step = Decimal("0.01")
        terms = [a * (12 * t).exp() for a, t in zip(coeffs, times, strict=True)]
        factors = [(-step * t).exp() for t in times]
        samples: list[tuple[Decimal, Decimal]] = []
        for i in range(2401):
            delta = Decimal(i - 1200) * step
            # Restart periodically to limit accumulated multiplication roundoff.
            if i % 100 == 0:
                terms = [a * (-delta * t).exp() for a, t in zip(coeffs, times, strict=True)]
            samples.append((delta, sum(terms, Decimal())))
            terms = [v * factor for v, factor in zip(terms, factors, strict=True)]
        found: list[tuple[Decimal, str]] = []
        for i, (delta, value) in enumerate(samples):
            if value == 0:
                derivative = sum(
                    (-a * t * (-delta * t).exp() for a, t in zip(coeffs, times, strict=True)),
                    Decimal(),
                )
                found.append((delta, "tangent" if derivative == 0 else "crossing"))
            elif i and samples[i - 1][1] and (samples[i - 1][1] > 0) != (value > 0):
                found.append((bisect(samples[i - 1][0], delta), "crossing"))
        logs = tuple(d for d, _ in found)
        roots = tuple(d.exp() - 1 for d in logs)
        kinds = tuple(k for _, k in found)
        complete = len(roots) == changes and "tangent" not in kinds
        status = "undetermined"
        if complete:
            status = "unique" if len(roots) == 1 else "multiple"
        proof = (
            "crossings exhaust Descartes bound"
            if complete
            else f"grid found {len(roots)} distinct roots; bound {changes}; may miss roots"
        )
        return Irr(status, roots, logs, kinds, complete, changes, not complete, proof)


def fund_irr(resolved: Resolved, *, day_count: DayCount) -> Irr:
    if resolved.residual is None:
        raise ValueError("fund IRR requires a residual valuation")
    return xirr(resolved.net_by_date, day_count=day_count)


def index_level(
    levels: Series,
    on: date,
    *,
    lookup: Literal["exact", "last_on_or_before"],
    max_gap_days: int,
) -> tuple[date, Fraction, int]:
    if max_gap_days < 0 or (lookup == "exact" and max_gap_days != 0):
        raise ValueError("invalid maximum index gap")
    if lookup not in ("exact", "last_on_or_before"):
        raise ValueError("unknown index lookup")
    if not levels or len({d for d, _ in levels}) != len(levels):
        raise ValueError("index dates must be nonempty and unique")
    if any(v <= 0 for _, v in levels):
        raise ValueError("index levels must be positive")
    candidates = [(d, v) for d, v in levels if d <= on]
    if not candidates:
        raise ValueError(f"no index level on or before {on}")
    used, level = max(candidates)
    gap = (on - used).days
    if gap > max_gap_days:
        raise ValueError(f"index level too old for {on}")
    return used, level, gap


def multiples(resolved: Resolved) -> dict[str, Fraction | None]:
    c, d, v = resolved.paid_in, resolved.distributed, resolved.residual
    return {
        "dpi": d / c if c else None,
        "rvpi": v / c if c and v is not None else None,
        "tvpi": (d + v) / c if c and v is not None else None,
    }


def future_values(
    resolved: Resolved,
    levels: Series,
    *,
    lookup: Literal["exact", "last_on_or_before"],
    max_gap_days: int,
) -> tuple[Fraction, Fraction, Series]:
    if resolved.residual is None or resolved.paid_in <= 0:
        raise ValueError("PME requires NAV and positive paid-in capital")
    terminal = index_level(levels, resolved.as_of, lookup=lookup, max_gap_days=max_gap_days)[1]
    fv_c = fv_d = Fraction()
    series = []
    for flow in resolved.flows:
        level = index_level(levels, flow.date, lookup=lookup, max_gap_days=max_gap_days)[1]
        fv = flow.amount * terminal / level
        if flow.kind == "contribution":
            fv_c += fv
            series.append((flow.date, -fv))
        else:
            fv_d += fv
            series.append((flow.date, fv))
    series.append((resolved.as_of, resolved.residual))
    return fv_c, fv_d, tuple(series)


def ks_pme(resolved: Resolved, levels: Series, *, lookup: str, max_gap_days: int) -> Fraction:
    c, d, _ = future_values(resolved, levels, lookup=lookup, max_gap_days=max_gap_days)
    assert resolved.residual is not None
    return (d + resolved.residual) / c


def direct_alpha(
    resolved: Resolved,
    levels: Series,
    *,
    lookup: str,
    max_gap_days: int,
    day_count: DayCount,
) -> Irr:
    _, _, series = future_values(resolved, levels, lookup=lookup, max_gap_days=max_gap_days)
    return xirr(series, day_count=day_count)


@dataclass(frozen=True)
class Plus:
    scale: Fraction | None
    irr: Irr | None
    fund_irr: Irr
    spread: Decimal | None
    log_spread: Decimal | None
    identity_residual: Fraction | None


def pme_plus(
    resolved: Resolved,
    levels: Series,
    *,
    lookup: str,
    max_gap_days: int,
    day_count: DayCount,
) -> Plus:
    c, d, _ = future_values(resolved, levels, lookup=lookup, max_gap_days=max_gap_days)
    assert resolved.residual is not None
    fund = fund_irr(resolved, day_count=day_count)
    if not d:
        return Plus(None, None, fund, None, None, None)
    scale = (c - resolved.residual) / d
    series = tuple(
        (f.date, -f.amount if f.kind == "contribution" else scale * f.amount)
        for f in resolved.flows
    ) + ((resolved.as_of, resolved.residual),)
    result = xirr(series, day_count=day_count)
    spread = log_spread = None
    if scale >= 0 and fund.irr is not None and result.irr is not None:
        with localcontext() as ctx:
            ctx.prec = PRECISION
            spread = fund.irr - result.irr
            log_spread = fund.log_roots[0] - result.log_roots[0]
    return Plus(scale, result, fund, spread, log_spread, c - scale * d - resolved.residual)


@dataclass(frozen=True)
class LongNickels:
    terminal: Fraction
    closed_form: Fraction
    positions: Series
    went_short: bool
    first_short_date: date | None
    minimum_position: Fraction
    irr: Irr
    fund_irr: Irr
    spread: Decimal | None
    log_spread: Decimal | None


def ln_pme(
    resolved: Resolved,
    levels: Series,
    *,
    lookup: str,
    max_gap_days: int,
    day_count: DayCount,
) -> LongNickels:
    c, d, _ = future_values(resolved, levels, lookup=lookup, max_gap_days=max_gap_days)
    by_date: dict[date, Fraction] = defaultdict(Fraction)
    for f in resolved.flows:
        by_date[f.date] -= f.signed
    by_date[resolved.as_of] += 0
    position = Fraction()
    prev_level = Fraction(1)
    positions = []
    for on, cash in sorted(by_date.items()):
        level = index_level(levels, on, lookup=lookup, max_gap_days=max_gap_days)[1]
        position = position * level / prev_level + cash
        positions.append((on, position))
        prev_level = level
    series = tuple((f.date, f.signed) for f in resolved.flows) + ((resolved.as_of, position),)
    result = xirr(series, day_count=day_count)
    fund = fund_irr(resolved, day_count=day_count)
    short_dates = [on for on, value in positions if value < 0]
    with localcontext() as ctx:
        ctx.prec = PRECISION
        spread = fund.irr - result.irr if fund.irr is not None and result.irr is not None else None
        log_spread = (
            fund.log_roots[0] - result.log_roots[0]
            if fund.irr is not None and result.irr is not None
            else None
        )
    return LongNickels(
        position,
        c - d,
        tuple(positions),
        bool(short_dates),
        short_dates[0] if short_dates else None,
        min(v for _, v in positions),
        result,
        fund,
        spread,
        log_spread,
    )


InterimNavPolicy = Literal["refuse", "roll_forward_cash_adjusted"]


@dataclass(frozen=True)
class MpmeStep:
    date: date
    index_level: Fraction
    contribution: Fraction
    distribution: Fraction
    fund_nav: Fraction | None
    fund_nav_source: Literal["reported", "rolled_forward", "none"]
    fund_nav_observation_date: date | None
    weight: Fraction
    position_before_sale: Fraction
    mpme_distribution: Fraction
    position_after: Fraction


@dataclass(frozen=True)
class Mpme:
    path: tuple[MpmeStep, ...]
    terminal_value: Fraction
    mpme_series: Series
    mpme_irr: Irr
    fund_irr: Irr | None
    spread: Decimal | None
    log_spread: Decimal | None
    max_nav_gap_used_days: int


def mpme(
    resolved: Resolved,
    nav_history: Series,
    levels: Series,
    *,
    lookup: Literal["exact", "last_on_or_before"],
    max_gap_days: int,
    day_count: DayCount,
    interim_nav: InterimNavPolicy,
    max_nav_gap_days: int,
) -> Mpme:
    """Reconstruct contract section 12 independently, with exact cash accounting.

    Source: docs/pme-sources.md S6, labelled reconstruction, not CA's figures.
    Observed NAVs are end-of-day marks; roll-forward includes flows in (s, t].
    Start at zero, grow by a positive index ratio, then add nonnegative calls:
    X >= 0. For D > 0, NAV >= 0 implies D/(D+NAV) in [0, 1], so both the sale
    and the remaining position are nonnegative and sum exactly to X. Compute
    the retained fraction directly, giving exactly zero when NAV is zero.
    Fraction nets need no floating-point rounding bound: zero is exact.
    """
    if resolved.residual is None or resolved.paid_in <= 0:
        raise ValueError("mPME requires NAV and positive paid-in capital")
    if interim_nav not in ("refuse", "roll_forward_cash_adjusted"):
        raise ValueError("unknown interim NAV policy")
    if max_nav_gap_days < 0 or (interim_nav == "refuse" and max_nav_gap_days != 0):
        raise ValueError("invalid maximum interim NAV gap")
    if not nav_history or len({d for d, _ in nav_history}) != len(nav_history):
        raise ValueError("NAV history dates must be nonempty and unique")
    for on, value in nav_history:
        if on > resolved.as_of or value < 0:
            raise ValueError(f"NAV on {on} must be nonnegative and on or before as_of")
        if on == resolved.as_of and value != resolved.residual:
            raise ValueError(f"NAV history at {on} must equal the resolved residual")
    marks = dict(nav_history)

    def nav_at(on: date) -> tuple[Fraction, str, date]:
        if on in marks:
            return marks[on], "reported", on
        if on == resolved.as_of:
            # Section 12 clarification: resolve owns terminal NAV, including its
            # own stale-NAV policy; interim gap limits never override NAV_T.
            source = "reported" if resolved.nav_source == "reported_at_as_of" else "rolled_forward"
            assert resolved.nav_observation_date is not None
            return resolved.residual, source, resolved.nav_observation_date
        if interim_nav == "refuse":
            raise ValueError(f"missing interim NAV on {on}")
        prior = [d for d in marks if d < on]
        if not prior:
            raise ValueError(f"no earlier interim NAV for {on}")
        observed = max(prior)
        if (on - observed).days > max_nav_gap_days:
            raise ValueError(f"interim NAV gap exceeds limit for {on}")
        # The observation already includes every flow on its own date.
        value = marks[observed] - sum(
            (f.signed for f in resolved.flows if observed < f.date <= on), Fraction()
        )
        if value < 0:
            raise ValueError(f"negative rolled interim NAV for {on}")
        return value, "rolled_forward", observed

    calls: dict[date, Fraction] = defaultdict(Fraction)
    distributions: dict[date, Fraction] = defaultdict(Fraction)
    for flow in resolved.flows:
        totals = calls if flow.kind == "contribution" else distributions
        totals[flow.date] += flow.amount
    dates = sorted(calls.keys() | distributions.keys() | {resolved.as_of})
    position, previous_index = Fraction(), Fraction(1)
    path = []
    cash = []
    maximum_gap = 0
    for on in dates:
        level = index_level(levels, on, lookup=lookup, max_gap_days=max_gap_days)[1]
        contribution, distribution = calls[on], distributions[on]
        before = position * (level / previous_index) + contribution
        weight, sale = Fraction(), Fraction()
        fund_nav, source, observed = None, "none", None
        if distribution:
            fund_nav, source, observed = nav_at(on)
            if on != resolved.as_of:
                maximum_gap = max(maximum_gap, (on - observed).days)
            denominator = distribution + fund_nav
            weight = distribution / denominator
            sale = weight * before
            position = (fund_nav / denominator) * before
        else:
            position = before
        path.append(
            MpmeStep(
                on,
                level,
                contribution,
                distribution,
                fund_nav,
                source,
                observed,
                weight,
                before,
                sale,
                position,
            )
        )
        cash.extend(((on, -contribution), (on, sale)))
        previous_index = level
    cash.append((resolved.as_of, position))
    amounts, _ = net(tuple(cash))
    result = xirr(amounts, day_count=day_count)
    try:
        fund = fund_irr(resolved, day_count=day_count)
    except ValueError:
        fund = None
    spread = log_spread = None
    if fund is not None and fund.irr is not None and result.irr is not None:
        with localcontext() as ctx:
            ctx.prec = PRECISION
            spread = fund.irr - result.irr
            log_spread = fund.log_roots[0] - result.log_roots[0]
    return Mpme(tuple(path), position, amounts, result, fund, spread, log_spread, maximum_gap)
