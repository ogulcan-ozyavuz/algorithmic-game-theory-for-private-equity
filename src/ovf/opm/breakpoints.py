"""Exit breakpoints derived from the verified waterfall engine, then checked against it.

A breakpoint is an exit value at which the split of the next marginal dollar changes. In
practice these tables are built by hand from the cap table. Here they are derived in two
independent ways and the two are made to agree:

1. **Analytic candidates**, in exact rational arithmetic, from the same inputs the engine
   reads (``exit_terms(as_of)`` and ``exit_claim(as_of)``): every debt tier repaid, every
   cumulative preference level of every conversion profile, every participation cap
   exhausted, every exit at which a position is indifferent to its own conversion, and,
   under a collective-conversion term, every exit at which a voting holder's gain from the
   conversion changes sign.
2. **Probes of the engine**, ``solve_waterfall`` or ``resolve_collective_conversion``, on
   both sides of every candidate and inside every interval between candidates. Each
   interval must be affine. A candidate across which the map stays affine is dropped; an
   interval that is not affine is bisected, and whatever kink or step it hides is added as
   located numerically. A schedule that still cannot be verified raises ``BreakpointError``.

The schedule is diagnostic. It is returned for a non-monotone or discontinuous table with
the negative weights or the steps recorded as measured; ``opm_allocate`` is what refuses.

The method is the one described in the AICPA Accounting and Valuation Guide, *Valuation of
Privately-Held-Company Equity Securities Issued as Compensation* (2013), for the option
pricing method's breakpoints. Nothing here claims conformance with it. See
docs/opm-breakpoints.md for the derivations and what the schedule does not establish.
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

from ovf.contracts.securities import CommonStock, PreferredStock, Security, StockOptionPool
from ovf.governance import (
    CollectiveConversion,
    GovernanceIndeterminateError,
    resolve_collective_conversion,
)
from ovf.instruments.debt import DebtInstrument
from ovf.opm.types import (
    Breakpoint,
    BreakpointError,
    BreakpointKind,
    BreakpointSchedule,
    Discontinuity,
    Tranche,
)
from ovf.waterfall import WaterfallConvergenceError, solve_waterfall, validate_securities

__all__ = ["breakpoint_schedule"]

MAX_PREFERRED = 12
"""Candidates come from every conversion profile, so the work is 2**n; ``enumerate_equilibria``
uses the same bound."""

MAX_GOVERNED_PREFERRED = 8
"""A vote-flip candidate needs the exact equilibrium of both stage games at every candidate."""

SIDE_OFFSET = 1e-6
"""Both-sides probes sit ``min(SIDE_OFFSET * max(x, interval width), 10% of the interval)``."""

INTERIOR = (0.21132486540518713, 0.5, 0.7886751345948129)
"""Interior probe positions, as fractions of an interval (Gauss-Legendre nodes and the midpoint)."""

VERIFY = (0.3819660112501051, 0.6180339887498949)
"""Fresh probe positions in every final tranche, used only for the final replay check."""

FLOOR_ULPS = 32.0
"""Bisection stops when an interval is this many float spacings wide."""

MAX_BISECTIONS = 400
"""Interval splits allowed, by intersection or bisection, before the schedule is refused."""
DEFAULT_SPAN = 1_000_000.0
"""upper_probe when the table has no candidate at all (only common stock, pool, nothing else)."""

_STRANDED = "\x00stranded"
_KIND_ORDER: tuple[BreakpointKind, ...] = (
    "forced_conversion",
    "debt_repaid",
    "preference",
    "participation_cap",
    "conversion",
    "other",
)


# ---------------------------------------------------------------------------
# Exact model: the engine's allocation rule restated over Fraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Pref:
    security_id: str
    holder_id: str
    seniority: int
    preference: Fraction
    cap: Fraction | None
    units: Fraction
    participating: bool


@dataclass(frozen=True)
class _Model:
    common: tuple[tuple[str, str, Fraction], ...]
    prefs: tuple[_Pref, ...]
    debt: tuple[tuple[int, tuple[tuple[str, Fraction], ...]], ...]
    debt_total: Fraction
    players: tuple[str, ...]
    holder_of: dict[str, str]

    @property
    def equity_ids(self) -> tuple[str, ...]:
        return tuple(c[0] for c in self.common) + tuple(p.security_id for p in self.prefs)


def _exact_model(securities: Sequence[Security], as_of: date | None) -> _Model:
    common: list[tuple[str, str, Fraction]] = []
    prefs: list[_Pref] = []
    tiers: dict[int, list[tuple[str, Fraction]]] = {}
    for s in securities:
        if isinstance(s, DebtInstrument):
            if as_of is None:
                raise BreakpointError(
                    f"{s.security_id} is debt, which accrues interest, so a breakpoint schedule "
                    "holding it needs an explicit as_of date. No implicit clock is used"
                )
            tiers.setdefault(s.seniority, []).append(
                (s.security_id, Fraction(s.exit_claim(as_of).claim))
            )
        elif isinstance(s, PreferredStock):
            terms = s.exit_terms(as_of)
            cap = terms.participation_cap_amount
            prefs.append(
                _Pref(
                    security_id=s.security_id,
                    holder_id=s.holder_id,
                    seniority=s.seniority,
                    preference=Fraction(terms.preference),
                    cap=Fraction(cap) if s.participating and cap is not None else None,
                    units=Fraction(terms.units) if s.shares > 0 else Fraction(0),
                    participating=s.participating,
                )
            )
        elif isinstance(s, CommonStock):
            if s.shares > 0:
                common.append((s.security_id, s.holder_id, Fraction(s.shares)))
        elif isinstance(s, StockOptionPool):
            if s.allocated_shares > 0:
                raise BreakpointError(
                    f"{s.security_id}: allocated options need exercise and settlement terms, "
                    "which the waterfall engine does not model; state issued shares explicitly"
                )
        else:
            raise BreakpointError(
                f"{s.security_id} is a {type(s).__name__}, which the waterfall engine does not "
                "allocate at an exit; resolve its conversion into a priced round first"
            )
    debt = tuple((level, tuple(tiers[level])) for level in sorted(tiers))
    return _Model(
        common=tuple(common),
        prefs=tuple(prefs),
        debt=debt,
        debt_total=sum((c for _, tier in debt for _, c in tier), Fraction(0)),
        players=tuple(sorted(p.security_id for p in prefs if p.units > 0)),
        holder_of={s.security_id: s.holder_id for s in securities},
    )


def _water_fill(
    cash: Fraction, units: dict[str, Fraction], heads: dict[str, Fraction]
) -> tuple[dict[str, Fraction], Fraction]:
    """Split ``cash`` pro rata by units, capping each capped entry at its headroom."""
    out: dict[str, Fraction] = {}
    active = dict(units)
    while active:
        level = cash / sum(active.values(), Fraction(0))
        capped = [j for j in active if j in heads and heads[j] < level * active[j]]
        if not capped:
            out.update({j: level * u for j, u in active.items()})
            return out, Fraction(0)
        for j in capped:
            out[j] = heads[j]
            cash -= heads[j]
            del active[j]
    return out, cash


def _allocate(model: _Model, converted: frozenset[str], equity: Fraction) -> dict[str, Fraction]:
    """Cash to every equity position for a fixed conversion profile, as the engine does it.

    The same rule as ``evaluate_fixed_waterfall``: preferences by ascending seniority, pro
    rata by claim within a tier, then the residual pro rata by as-converted units among
    common, converted and participating positions, each capped participant stopping at its
    cap. Cash nobody is entitled to is returned under a reserved key.
    """
    paid = {p.security_id: Fraction(0) for p in model.prefs}
    remaining = equity
    holding = [p for p in model.prefs if p.security_id not in converted]
    for rank in sorted({p.seniority for p in holding}):
        tier = [p for p in holding if p.seniority == rank]
        needed = sum((p.preference for p in tier), Fraction(0))
        budget = min(remaining, needed)
        if needed:
            for p in tier:
                paid[p.security_id] = budget * p.preference / needed
        remaining -= budget
    units: dict[str, Fraction] = {sid: shares for sid, _, shares in model.common}
    heads: dict[str, Fraction] = {}
    for p in model.prefs:
        if p.units > 0 and (p.security_id in converted or p.participating):
            units[p.security_id] = p.units
            if p.security_id not in converted and p.cap is not None:
                heads[p.security_id] = max(Fraction(0), p.cap - paid[p.security_id])
    share, stranded = _water_fill(remaining, units, heads)
    out = {sid: Fraction(0) for sid, _, _ in model.common} | paid
    for sid, amount in share.items():
        out[sid] += amount
    out[_STRANDED] = stranded
    return out


@dataclass(frozen=True)
class _Reason:
    kind: BreakpointKind
    text: str
    profiles: tuple[frozenset[str], ...] = ()


def _profile_kinks(model: _Model, converted: frozenset[str]) -> list[tuple[Fraction, _Reason]]:
    """Equity values at which this profile's allocation changes slope, with the reason."""
    out: list[tuple[Fraction, _Reason]] = []
    state = _profile_words(converted)
    holding = [p for p in model.prefs if p.security_id not in converted]
    running = Fraction(0)
    for rank in sorted({p.seniority for p in holding}):
        tier = [p for p in holding if p.seniority == rank and p.preference > 0]
        if not tier:
            continue
        running += sum((p.preference for p in tier), Fraction(0))
        claims = ", ".join(f"{p.security_id} {_money(p.preference)}" for p in tier)
        out.append(
            (
                running,
                _Reason(
                    "preference",
                    f"with {state}, the preference stack fills through seniority {rank} "
                    f"({claims}): cumulative preferences {_money(running)}",
                    (converted,),
                ),
            )
        )
    units: dict[str, Fraction] = {sid: shares for sid, _, shares in model.common}
    heads: dict[str, Fraction] = {}
    for p in model.prefs:
        if p.units > 0 and (p.security_id in converted or p.participating):
            units[p.security_id] = p.units
            if p.security_id not in converted and p.cap is not None:
                heads[p.security_id] = max(Fraction(0), p.cap - p.preference)
    total_units = sum(units.values(), Fraction(0))
    for sid, head in heads.items():
        level = head / units[sid]
        residual = sum(
            (min(level * u, heads[k]) if k in heads else level * u for k, u in units.items()),
            Fraction(0),
        )
        pref = next(p for p in model.prefs if p.security_id == sid)
        assert pref.cap is not None  # heads holds only capped participants
        out.append(
            (
                running + residual,
                _Reason(
                    "participation_cap",
                    f"with {state}, {sid} reaches its participation cap of {_money(pref.cap)}: "
                    f"preference {_money(pref.preference)} plus {_money(level)} a unit on "
                    f"{_count(units[sid])} of {_count(total_units)} participating units, once "
                    f"{_money(residual)} of residual follows {_money(running)} of preferences",
                    (converted,),
                ),
            )
        )
    return out


@dataclass(frozen=True)
class _Linear:
    """An exact piecewise-linear map from equity value to cash, affine between knots."""

    xs: tuple[Fraction, ...]
    ys: tuple[dict[str, Fraction], ...]
    tail: dict[str, Fraction]

    def value(self, key: str, x: Fraction) -> Fraction:
        i = bisect_right(self.xs, x) - 1
        if i >= len(self.xs) - 1:
            last = len(self.xs) - 1
            return self.ys[last][key] + self.tail[key] * (x - self.xs[last])
        x0, x1 = self.xs[i], self.xs[i + 1]
        y0, y1 = self.ys[i][key], self.ys[i + 1][key]
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _linear(model: _Model, converted: frozenset[str], kinks: list[Fraction]) -> _Linear:
    xs = tuple(sorted({Fraction(0), *kinks}))
    ys = tuple(_allocate(model, converted, x) for x in xs)
    beyond = _allocate(model, converted, xs[-1] + 1)
    return _Linear(xs, ys, {k: beyond[k] - ys[-1][k] for k in beyond})


def _sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def _sign_changes(
    g: Callable[[Fraction], Fraction], knots: Sequence[Fraction], tail_slope: Fraction
) -> list[tuple[Fraction, int, int]]:
    """Points x > 0 where a piecewise-linear ``g`` (affine between knots) is zero, as
    (x, sign just left, sign just right), omitting points inside a stretch where g is
    identically zero. A root inside one affine piece is found exactly by interpolation."""
    xs = sorted(set(knots))
    gs = [g(x) for x in xs]
    out: list[tuple[Fraction, int, int]] = []
    for i, (x, gx) in enumerate(zip(xs, gs, strict=True)):
        if i + 1 < len(xs):
            a, b, ga, gb = x, xs[i + 1], gx, gs[i + 1]
            if ga * gb < 0:
                out.append((a - ga * (b - a) / (gb - ga), _sign(ga), _sign(gb)))
        if gx != 0 or x <= 0:
            continue
        left = _sign(gs[i - 1]) if i > 0 else 0
        right = _sign(gs[i + 1]) if i + 1 < len(xs) else _sign(tail_slope)
        if (left, right) != (0, 0):
            out.append((x, left, right))
    if gs and tail_slope and gs[-1] * tail_slope < 0:
        root = xs[-1] - gs[-1] / tail_slope
        out.append((root, _sign(gs[-1]), _sign(tail_slope)))
    return out


@dataclass
class _Candidates:
    reasons: dict[Fraction, list[_Reason]] = field(default_factory=dict)
    profiles: int = 0
    governed_holders: tuple[str, ...] = ()

    def add(self, x: Fraction, reason: _Reason) -> None:
        if x > 0:
            self.reasons.setdefault(x, []).append(reason)


def _analytic_candidates(
    model: _Model, term: CollectiveConversion | None, as_of: date | None
) -> _Candidates:
    found = _Candidates()
    d = model.debt_total
    running = Fraction(0)
    for level, tier in model.debt:
        running += sum((c for _, c in tier), Fraction(0))
        claims = ", ".join(f"{sid} {_money(c)}" for sid, c in tier)
        when = f" as of {as_of.isoformat()}" if as_of is not None else ""
        found.add(
            running,
            _Reason(
                "debt_repaid",
                f"debt through seniority {level} ({claims}) is repaid in full: cumulative "
                f"debt claims{when} {_money(running)}; equity receives nothing below this",
            ),
        )
    players = model.players
    profiles = [
        frozenset(p for p, bit in zip(players, bits, strict=True) if bit)
        for bits in itertools.product((False, True), repeat=len(players))
    ]
    found.profiles = len(profiles)
    kinks = {s: _profile_kinks(model, s) for s in profiles}
    maps = {s: _linear(model, s, [x for x, _ in kinks[s]]) for s in profiles}
    equity: dict[Fraction, list[_Reason]] = {}
    for s in profiles:
        for x, reason in kinks[s]:
            equity.setdefault(x, []).append(reason)
    for s in profiles:
        for sid in players:
            if sid in s:
                continue
            t = s | {sid}

            def gain(
                x: Fraction, sid: str = sid, s: frozenset[str] = s, t: frozenset[str] = t
            ) -> Fraction:
                return maps[t].value(sid, x) - maps[s].value(sid, x)

            for root, _, _ in _sign_changes(
                gain, (*maps[s].xs, *maps[t].xs), maps[t].tail[sid] - maps[s].tail[sid]
            ):
                both = maps[s].value(sid, root)
                equity.setdefault(root, []).append(
                    _Reason(
                        "conversion",
                        f"with {_profile_words(s)}, {sid} is indifferent between holding and "
                        f"converting: both pay it {_money(both)} at an equity value of "
                        f"{_money(root)}",
                        (s, t),
                    )
                )
    if term is not None:
        _vote_candidates(model, term, profiles, maps, equity)
        found.governed_holders = tuple(
            sorted({model.holder_of[i] for a in term.approvals for i in a.voters})
        )
    for x, reasons in equity.items():
        for reason in reasons:
            found.add(
                d + x,
                reason
                if not d
                else _Reason(
                    reason.kind,
                    f"{reason.text}, after {_money(d)} of debt",
                    reason.profiles,
                ),
            )
    return found


def _vote_candidates(
    model: _Model,
    term: CollectiveConversion,
    profiles: list[frozenset[str]],
    maps: dict[frozenset[str], _Linear],
    equity: dict[Fraction, list[_Reason]],
) -> None:
    """Every equity value at which a voting holder's gain from the conversion changes sign.

    Each stage game's equilibrium payoff is affine between the candidates already found
    (no fixed-profile allocation bends and no position's gain from switching changes sign
    there), so each holder's gain is affine between them too and its roots are exact.
    """
    forced = frozenset(term.converts) & frozenset(model.players)
    keys = model.equity_ids
    knots = sorted({Fraction(0), *equity})
    knots.append(knots[-1] + 1)

    def equilibrium(fixed: frozenset[str], x: Fraction) -> dict[str, Fraction]:
        free = [p for p in model.players if p not in fixed]
        vectors: set[tuple[Fraction, ...]] = set()
        for s in profiles:
            if not fixed <= s:
                continue
            m = maps[s]
            if m.value(_STRANDED, x) != 0:
                continue
            if all(maps[s ^ {p}].value(p, x) <= m.value(p, x) for p in free):
                vectors.add(tuple(m.value(k, x) for k in keys))
        if len(vectors) != 1:
            raise BreakpointError(
                f"{term.name}: at an equity value of {_money(x)} the stage game "
                f"{'with' if fixed else 'without'} the conversion has {len(vectors)} "
                "equilibrium payoff vectors in exact arithmetic; a holder's vote is defined "
                "only when there is exactly one"
            )
        return dict(zip(keys, next(iter(vectors)), strict=True))

    without = [equilibrium(frozenset(), x) for x in knots]
    with_ = [equilibrium(forced, x) for x in knots]
    voters = sorted({model.holder_of[i] for a in term.approvals for i in a.voters})
    for holder in voters:
        ids = [k for k in keys if model.holder_of[k] == holder]
        deltas = [
            sum((w[k] - wo[k] for k in ids), Fraction(0))
            for w, wo in zip(with_, without, strict=True)
        ]
        table = dict(zip(knots, deltas, strict=True))
        tail = deltas[-1] - deltas[-2]
        for root, left, right in _sign_changes(table.__getitem__, knots[:-1], tail):
            at_root = equilibrium(frozenset(), root)
            cash = sum((at_root[k] for k in ids), Fraction(0))
            equity.setdefault(root, []).append(
                _Reason(
                    "forced_conversion",
                    f"under '{term.name}', holder {holder}'s total cash is {_money(cash)} with "
                    f"and without the conversion at an equity value of {_money(root)}: it "
                    + (
                        f"{_decision(left)} just below and {_decision(right)} just above"
                        if left != right
                        else f"{_decision(left)} on both sides and is indifferent only here"
                    ),
                )
            )


# ---------------------------------------------------------------------------
# The engine as an oracle, and verification by probing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Probe:
    x: float
    values: dict[str, float] | None
    state: str
    refusal: str = ""


class _Engine:
    def __init__(
        self,
        securities: tuple[Security, ...],
        as_of: date | None,
        term: CollectiveConversion | None,
    ) -> None:
        self.securities = securities
        self.as_of = as_of
        self.term = term
        self.calls: dict[float, _Probe] = {}
        self.assumptions: dict[str, None] = {}

    def __call__(self, x: float, *, may_be_undefined: bool = False) -> _Probe:
        probe = self.calls.get(x)
        if probe is None:
            probe = self._run(x)
            self.calls[x] = probe
        if probe.values is None and not may_be_undefined:
            raise BreakpointError(
                f"ovf.governance refuses to price an exit of {x!r}, where no voting holder's "
                "gain from the conversion changes sign or touches zero, so the governed payoff "
                f"is not defined there and no schedule can be verified: {probe.refusal}"
            )
        return probe

    def _run(self, x: float) -> _Probe:
        try:
            if self.term is None:
                result = solve_waterfall(self.securities, x, as_of=self.as_of)
                converted = sorted(p.security_id for p in result.payouts if p.converted)
                state = f"converted: {', '.join(converted)}" if converted else "none converted"
                self.assumptions.update(dict.fromkeys(result.assumptions))
            else:
                governed = resolve_collective_conversion(
                    self.securities, x, term=self.term, as_of=self.as_of
                )
                result = governed.result
                converted = sorted(p.security_id for p in result.payouts if p.converted)
                verdict = "approved" if governed.approved else "not approved"
                state = f"'{self.term.name}' {verdict}; " + (
                    f"converted: {', '.join(converted)}" if converted else "none converted"
                )
                tallies = tuple(f"{t.name}:" for t in governed.tallies)
                self.assumptions.update(
                    dict.fromkeys(a for a in governed.assumptions if not a.startswith(tallies))
                )
                self.assumptions.update(dict.fromkeys(result.assumptions))
        except GovernanceIndeterminateError as exc:
            return _Probe(x, None, "undefined", str(exc))
        except (WaterfallConvergenceError, ValueError) as exc:
            raise BreakpointError(f"the engine refused an exit of {x!r}: {exc}") from exc
        return _Probe(x, {p.security_id: p.amount for p in result.payouts}, state)


@dataclass
class _Knot:
    x: float
    exact: Fraction | None
    reasons: list[_Reason]
    probe: _Probe
    located: str = ""  # how a numerically located knot was found; empty for candidates

    @property
    def flip(self) -> bool:
        """A predicted vote flip: the payoff may step here and its value here is undefined."""
        return any(r.kind == "forced_conversion" for r in self.reasons)


@dataclass(frozen=True)
class _Fit:
    """An interval (a, b) of the engine's map, affine within tolerance, fitted from probes."""

    a: float
    b: float
    x0: float
    y0: dict[str, float]
    slope: dict[str, float]
    points: tuple[float, ...]
    deviation: float
    step: bool = False  # a bracket too narrow to split, across which the map steps

    def at(self, x: float) -> dict[str, float]:
        return {k: self.y0[k] + self.slope[k] * (x - self.x0) for k in self.y0}


def _offset(x: float, width: float) -> float:
    """A probe step beside ``x``, floored by the interval rather than by an absolute 1.0.

    The floor used to be ``max(abs(x), 1.0)``, which is an absolute quantity in a function
    whose inputs are exit valuations. On a table denominated in millions the origin probe
    then landed at 1e-6 - not a small exit but effectively zero - where every voting
    holder's gain from a conversion has decayed proportionally to nothing and falls under
    ``ovf.governance``'s absolute indifference tolerance. The engine then declares a tied
    vote and refuses, and the whole table is rejected with a reason that is false: the vote
    is determined at every exit anyone would ask about. Flooring by ``width`` makes the
    probe scale with the table. Small tables are unaffected, because there the width is
    already of order one. Reported by the validation worker, which measured 21 tables in
    roughly 4,000 refused this way, 7 of which would otherwise have priced.
    """
    return min(SIDE_OFFSET * max(abs(x), width), 0.1 * width)


def _deviation(values: dict[str, float], line: dict[str, float]) -> float:
    return max((abs(values[k] - line[k]) for k in line), default=0.0)


def _fit(engine: _Engine, left: _Knot, right: _Knot) -> _Fit:
    """Fit the line through the two probes nearest the ends, and measure how far the other
    probes and both end values lie from it. An end is not measured where the engine has no
    value, or at a predicted vote flip, where the value at the point is not the limit of
    either side. Measuring the ends is what exposes a kink or step hidden between an end and
    its nearest probe, which would otherwise pass as affine and be pinned on the knot."""
    a, b = left.x, right.x
    width = b - a
    lo = a + _offset(a, width)
    hi = b - _offset(b, width)
    inner = [a + t * width for t in INTERIOR]
    p_lo, p_hi = engine(lo), engine(hi)
    assert p_lo.values is not None and p_hi.values is not None
    slope = {k: (p_hi.values[k] - p_lo.values[k]) / (hi - lo) for k in p_lo.values}
    fit = _Fit(a, b, lo, p_lo.values, slope, (lo, *inner, hi), 0.0)
    deviation = 0.0
    for x in inner:
        probe = engine(x)
        assert probe.values is not None
        deviation = max(deviation, _deviation(probe.values, fit.at(x)))
    for knot in (left, right):
        if knot.probe.values is not None and not knot.flip:
            deviation = max(deviation, _deviation(knot.probe.values, fit.at(knot.x)))
    return _Fit(a, b, lo, p_lo.values, slope, fit.points, deviation)


def _floor(x: float) -> float:
    return FLOOR_ULPS * math.ulp(max(abs(x), 1.0))


def _engine_tolerance(x: float) -> float:
    """``solve_waterfall``'s own default equilibrium tolerance at this exit."""
    return 1e-8 + 1e-12 * x


@dataclass
class _Build:
    knots: list[_Knot]
    fits: dict[tuple[float, float], _Fit]
    located: int = 0
    bisections: int = 0


def _verify(engine: _Engine, knots: list[_Knot], tol: float, atol: float) -> _Build:
    """Fit every interval between knots, splitting any that is not affine.

    A failing interval is split first where the affine pieces at its two ends meet, which
    locates a single missed kink in one step; when the engine is not on both lines there,
    it is split at its midpoint instead.
    """
    build = _Build(knots=list(knots), fits={})
    stack = list(zip(build.knots, build.knots[1:], strict=False))
    while stack:
        left, right = stack.pop()
        fit = _fit(engine, left, right)
        if fit.deviation <= tol:
            build.fits[(left.x, right.x)] = fit
            continue
        width = right.x - left.x
        if width <= _floor(right.x):
            build.fits[(left.x, right.x)] = _step(fit, left, right, atol)
            build.located += 1
            continue
        build.bisections += 1
        if build.bisections > MAX_BISECTIONS:
            raise BreakpointError(
                f"gave up after {MAX_BISECTIONS} interval splits; the interval "
                f"[{left.x!r}, {right.x!r}] still deviates from a line by {fit.deviation:.3g}, "
                f"above the construction tolerance {tol:.3g}"
            )
        middle = _intersection(engine, fit, left, right, tol)
        how = "the intersection of the affine pieces at either end"
        if middle is None:
            middle, how = left.x + width / 2, "bisection"
        knot = _Knot(
            middle,
            None,
            [],
            engine(middle),
            located=(
                f"{how} of [{left.x!r}, {right.x!r}], where the engine's map deviated from a "
                f"line by {fit.deviation:.6g}"
            ),
        )
        build.knots.insert(build.knots.index(right), knot)
        stack.extend([(left, knot), (knot, right)])
    return build


def _intersection(
    engine: _Engine, fit: _Fit, left: _Knot, right: _Knot, tol: float
) -> float | None:
    """Where the lines through each end of a failing interval and its nearest probe meet,
    if the engine's map passes through both lines there; None otherwise."""
    lv, rv = left.probe.values, right.probe.values
    if lv is None or rv is None:
        return None
    a, b, lo, hi = left.x, right.x, fit.points[0], fit.points[-1]
    pl, ph = engine(lo).values, engine(hi).values
    assert pl is not None and ph is not None
    sl = {k: (pl[k] - lv[k]) / (lo - a) for k in lv}
    sr = {k: (rv[k] - ph[k]) / (b - hi) for k in lv}
    k = max(lv, key=lambda key: abs(sl[key] - sr[key]))
    if sl[k] == sr[k]:
        return None
    x = (rv[k] - lv[k] - sr[k] * b + sl[k] * a) / (sl[k] - sr[k])
    if not lo < x < hi:
        return None
    probe = engine(x, may_be_undefined=True)
    if probe.values is None:
        return None
    on_left = {key: lv[key] + sl[key] * (x - a) for key in lv}
    on_right = {key: rv[key] + sr[key] * (x - b) for key in lv}
    if max(_deviation(probe.values, on_left), _deviation(probe.values, on_right)) > tol:
        return None
    return x


def _step(fit: _Fit, left: _Knot, right: _Knot, atol: float) -> _Fit:
    """Classify an interval that is too narrow to split and still not affine."""
    lv, rv = left.probe.values, right.probe.values
    if lv is None or rv is None:
        raise BreakpointError(
            f"the interval [{left.x!r}, {right.x!r}] is not affine (deviation "
            f"{fit.deviation:.6g}) and the engine cannot price one of its ends"
        )
    change = max(abs(rv[k] - lv[k]) for k in lv)
    width = right.x - left.x
    band = 10 * _engine_tolerance(right.x)
    if change <= width + atol or change <= band:
        raise BreakpointError(
            f"the interval [{left.x!r}, {right.x!r}] cannot be verified: it deviates from a "
            f"line by {fit.deviation:.6g} and is too narrow to split, but its ends differ by "
            f"only {change:.6g}, which is within the engine's own tie tolerance "
            f"({band:.3g}) or its width; neither a kink nor a step explains it"
        )
    slope = dict.fromkeys(lv, 0.0)
    return _Fit(left.x, right.x, left.x, dict(lv), slope, fit.points, fit.deviation, step=True)


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def breakpoint_schedule(
    securities: Sequence[Security],
    *,
    as_of: date | None = None,
    upper_probe: float | None = None,
    atol: float = 1e-6,
    collective_conversion: CollectiveConversion | None = None,
) -> BreakpointSchedule:
    """Derive the exit breakpoints of a cap table from the waterfall engine, and verify them.

    Candidates are computed in exact rational arithmetic (see the module docstring), then
    the engine is probed on both sides of every candidate and inside every interval. Each
    interval must be affine to within ``atol / 2``; a candidate across which the map stays
    affine is dropped, and an interval that is not affine is split, where the lines at its
    ends meet or else at its midpoint, until whatever it hides is located numerically. The finished schedule is replayed against the engine
    at every probe and at fresh probes in every tranche; the largest gap is reported as
    ``max_linearity_error`` and must not exceed ``atol``.

    ``collective_conversion`` prices the table under that charter term with
    ``ovf.governance.resolve_collective_conversion``. The payoff can then step at an exit
    where a voting holder's gain from the conversion changes sign; each step is recorded
    in ``discontinuities`` with its exact location and measured jumps, and ``continuous``
    and ``monotone`` are set accordingly.

    The schedule is diagnostic: negative weights and steps are reported, not refused.
    ``BreakpointError`` is raised when the schedule cannot be derived or verified: the
    engine refuses an exit, a probe disagrees with the schedule by more than ``atol``, an
    interval cannot be made affine by splitting, or the table is too large to enumerate.
    """
    securities = tuple(securities)
    try:
        validate_securities(securities)
    except ValueError as exc:
        raise BreakpointError(str(exc)) from exc
    if isinstance(atol, bool) or not isinstance(atol, int | float) or not 0 < atol < math.inf:
        raise BreakpointError(f"atol must be finite and positive, got {atol!r}")
    atol = float(atol)
    if upper_probe is not None and (
        isinstance(upper_probe, bool)
        or not isinstance(upper_probe, int | float)
        or not 0 < upper_probe < math.inf
    ):
        raise BreakpointError(f"upper_probe must be finite and positive, got {upper_probe!r}")
    term = collective_conversion
    if term is not None and not isinstance(term, CollectiveConversion):
        raise BreakpointError(
            f"collective_conversion must be a CollectiveConversion, got {type(term).__name__}"
        )

    try:
        model = _exact_model(securities, as_of)
    except BreakpointError:
        raise
    except ValueError as exc:
        raise BreakpointError(f"cannot state the exit terms exactly: {exc}") from exc
    limit = MAX_PREFERRED if term is None else MAX_GOVERNED_PREFERRED
    if len(model.players) > limit:
        raise BreakpointError(
            f"{len(model.players)} preferred positions hold shares; candidates come from all "
            f"2**n conversion profiles{' of both stage games' if term else ''}, and this is "
            f"limited to {limit}"
        )
    candidates = _analytic_candidates(model, term, as_of)

    exact_values = sorted(candidates.reasons)
    largest = float(exact_values[-1]) if exact_values else 0.0
    if upper_probe is None:
        upper = 2.0 * largest if exact_values else DEFAULT_SPAN
        upper_rule = (
            f"upper_probe {upper:,.2f} is twice the largest analytic candidate ({largest:,.2f})"
            if exact_values
            else f"upper_probe {upper:,.2f}: the table has no analytic candidate at all"
        )
    else:
        upper = float(upper_probe)
        if upper <= largest:
            raise BreakpointError(
                f"upper_probe {upper!r} must lie above every analytic candidate; the largest "
                f"is {largest!r}, and the tail above it is verified only up to upper_probe"
            )
        upper_rule = f"upper_probe {upper:,.2f} was supplied by the caller"

    engine = _Engine(securities, as_of, term)
    tol = atol / 2
    by_float: dict[float, _Knot] = {}
    for value in exact_values:
        x = float(value)
        if x in by_float:
            by_float[x].reasons.extend(candidates.reasons[value])
            continue
        reasons = list(candidates.reasons[value])
        flip = any(r.kind == "forced_conversion" for r in reasons)
        by_float[x] = _Knot(x, value, reasons, engine(x, may_be_undefined=flip))
    origin = _Knot(
        0.0, Fraction(0), [_Reason("origin", "no exit value, nothing to pay")], engine(0.0)
    )
    end = _Knot(upper, None, [], engine(upper), located="upper probe")
    knots = [origin, *(by_float[x] for x in sorted(by_float)), end]

    build = _verify(engine, knots, tol, atol)
    knots = build.knots
    fits = build.fits

    # One-sided limits at every knot, and the steps between them.
    left_limit: dict[float, dict[str, float]] = {}
    right_limit: dict[float, dict[str, float]] = {}
    for a, b in zip(knots, knots[1:], strict=False):
        fit = fits[(a.x, b.x)]
        right_limit[a.x] = fit.at(a.x) if not fit.step else dict(fit.y0)
        left_limit[b.x] = fit.at(b.x) if not fit.step else dict(fit.y0)
    steps: dict[float, dict[str, float]] = {}
    undefined: list[_Knot] = []
    for knot in knots[1:-1]:
        jumps = {k: right_limit[knot.x][k] - left_limit[knot.x][k] for k in left_limit[knot.x]}
        if max(abs(j) for j in jumps.values()) > tol:
            steps[knot.x] = jumps
            continue
        if knot.probe.values is None:
            undefined.append(knot)
            continue
        gap = max(
            _deviation(knot.probe.values, left_limit[knot.x]),
            _deviation(knot.probe.values, right_limit[knot.x]),
        )
        if gap > tol:
            raise BreakpointError(
                f"at {knot.x!r} the engine's cash differs from both one-sided limits of its map "
                f"by {gap:.6g}, above the construction tolerance {tol:.3g}"
            )

    def start(knot: _Knot) -> dict[str, float]:
        if knot.x in steps or knot.probe.values is None:
            return right_limit[knot.x]
        return knot.probe.values

    def finish(knot: _Knot) -> dict[str, float]:
        if knot.x in steps or knot.probe.values is None:
            return left_limit[knot.x]
        return knot.probe.values

    step_interiors = [(a, b) for (a, b), f in fits.items() if f.step]

    def in_step(x: float) -> bool:
        return any(a < x < b for a, b in step_interiors)

    # Drop every knot across which the map stays affine.
    kept: list[_Knot] = [knots[0]]
    for i in range(1, len(knots) - 1):
        knot, following = knots[i], knots[i + 1]
        if knot.x in steps:
            kept.append(knot)
            continue
        a = kept[-1]
        ya, yb = start(a), finish(following)
        chord = {k: (yb[k] - ya[k]) / (following.x - a.x) for k in ya}
        worst = 0.0
        for x, probe in engine.calls.items():
            if not a.x < x < following.x or probe.values is None or in_step(x) or x in steps:
                continue
            line = {k: ya[k] + chord[k] * (x - a.x) for k in ya}
            worst = max(worst, _deviation(probe.values, line))
        if worst > tol:
            kept.append(knot)

    # Tranches: weights measured from the engine at each end.
    ids = [s.security_id for s in securities]
    tranches: list[Tranche] = []
    for j, knot in enumerate(kept):
        is_last = j == len(kept) - 1
        top = knots[-1] if is_last else kept[j + 1]
        ya, yb = start(knot), finish(top)
        width = top.x - knot.x
        weights = {k: (yb[k] - ya[k]) / width for k in ids}
        # `may_be_undefined` because this probe is COSMETIC: it fills in the basis text and
        # nothing else. The interval's midpoint can be exactly where a pivotal holder's gain
        # crosses zero, and `ovf.governance` rightly declines to call a tied vote there. A
        # probe chosen for the derivation's convenience must never be able to refuse a table
        # it is only describing. Reported by the validation worker on a table that steps for
        # unrelated reasons, so the verdict was right and the reason was false - the same
        # probe on a table whose only tie is a midpoint would have refused a priceable table.
        mid = engine(knot.x + width / 2, may_be_undefined=True)
        seen = (
            f"engine at X = {mid.x:,.2f}: {mid.state}"
            if mid.values is not None
            else (
                f"the engine is undefined at this tranche's midpoint X = {mid.x:,.2f}, where "
                "the vote is exactly tied; the weights either side of it are unaffected"
            )
        )
        shares = ", ".join(f"{k} {w:.6g}" for k, w in weights.items() if abs(w) > 1e-12)
        tranches.append(
            Tranche(
                lower=knot.x,
                upper=None if is_last else top.x,
                weights=weights,
                basis=(
                    f"{seen}; each marginal dollar goes to "
                    f"{shares or 'nobody'}"
                    + (f" (measured up to the upper probe {top.x:,.2f})" if is_last else "")
                ),
                weight_sum_error=abs(math.fsum(weights.values()) - 1.0),
            )
        )

    breakpoints = [_breakpoint(knot, knots, engine, steps, candidates) for knot in kept]
    discontinuities = [
        _discontinuity(knot, steps[knot.x], left_limit, right_limit, engine)
        for knot in kept
        if knot.x in steps
    ]
    schedule = BreakpointSchedule(
        breakpoints=breakpoints,
        tranches=tranches,
        security_ids=ids,
        discontinuities=discontinuities,
        monotone=True,
        continuous=not discontinuities,
        max_weight_sum_error=max(t.weight_sum_error for t in tranches),
        max_linearity_error=0.0,
        linearity_samples=0,
        as_of=as_of,
        assumptions=[],
    )

    # Re-verify: replay against the engine at every probe and at fresh ones.
    for j, tranche in enumerate(tranches):
        ceiling = tranche.upper if tranche.upper is not None else upper
        for t in VERIFY:
            engine(tranche.lower + t * (ceiling - tranche.lower))
        if j == len(tranches) - 1:
            engine(2.0 * upper)
    worst, where, who, replayed, observed = 0.0, 0.0, "", 0.0, 0.0
    for x, probe in engine.calls.items():
        if probe.values is None or x in steps or in_step(x):
            continue
        replay = schedule.payout(x)
        for k in ids:
            gap = abs(replay[k] - probe.values[k])
            if gap > worst:
                worst, where, who, replayed, observed = gap, x, k, replay[k], probe.values[k]
    if worst > atol:
        raise BreakpointError(
            f"the schedule does not replay the engine: at X = {where!r} it pays {who} "
            f"{replayed!r} where the engine pays {observed!r}, a gap of {worst:.6g} above "
            f"atol {atol:g}"
        )

    decreasing = [
        f"{k} falls {w:.6g} a dollar on [{t.lower:,.2f}, "
        f"{'inf' if t.upper is None else f'{t.upper:,.2f}'})"
        for t in tranches
        for k, w in t.weights.items()
        if w * ((t.upper if t.upper is not None else upper) - t.lower) < -atol
    ] + [
        f"{k} falls {-j:,.2f} at X = {d.value:,.2f}"
        for d in discontinuities
        for k, j in d.jumps.items()
        if j < -atol
    ]
    assumptions = _assumptions(
        candidates=candidates,
        retained=len(kept) - 1,
        located=sum(1 for k in kept if k.exact is None),
        bisections=build.bisections,
        tol=tol,
        atol=atol,
        undefined=[k.x for k in undefined],
        upper_rule=upper_rule,
        upper=upper,
        term=term,
        discontinuities=discontinuities,
        decreasing=decreasing,
        engine=engine,
    )
    return schedule.model_copy(
        update={
            "monotone": not decreasing,
            "max_linearity_error": worst,
            "linearity_samples": sum(1 for p in engine.calls.values() if p.values is not None),
            "assumptions": assumptions,
        }
    )


def _breakpoint(
    knot: _Knot,
    knots: list[_Knot],
    engine: _Engine,
    steps: dict[float, dict[str, float]],
    candidates: _Candidates,
) -> Breakpoint:
    if knot.x == 0.0:
        return Breakpoint(value=0.0, kind="origin", basis="zero exit: nothing to pay", exact=True)
    if knot.exact is None:
        families = "debt tiers, preference levels, participation caps, conversion indifference"
        if candidates.governed_holders:
            families += ", vote flips"
        return Breakpoint(
            value=knot.x,
            kind="other",
            basis=(
                f"located numerically by {knot.located}; no candidate family ({families}) "
                "predicted it, so its position carries the bisection's resolution"
            ),
            exact=False,
        )
    reason = _chosen_reason(knot, knots, engine, steps)
    others = sorted({r.kind for r in knot.reasons} - {reason.kind})
    exact = "" if knot.exact.denominator == 1 else f" (exactly {_money(knot.exact)})"
    basis = f"X = {knot.x:,.2f}{exact}: {reason.text}"
    if others:
        basis += f"; also a {', '.join(others)} candidate here"
    if knot.x in steps:
        basis += "; the payoff steps here (see discontinuities)"
    return Breakpoint(value=knot.x, kind=reason.kind, basis=basis, exact=True)


def _chosen_reason(
    knot: _Knot, knots: list[_Knot], engine: _Engine, steps: dict[float, dict[str, float]]
) -> _Reason:
    """The reason whose conversion profile the engine actually plays next to this knot."""
    ranked = sorted(knot.reasons, key=lambda r: _KIND_ORDER.index(r.kind))
    if knot.x in steps:
        flips = [r for r in ranked if r.kind == "forced_conversion"]
        if flips:
            return flips[0]
    i = knots.index(knot)
    width = min(knot.x - knots[i - 1].x, knots[i + 1].x - knot.x)
    sides = {
        engine(knot.x + s * _offset(knot.x, width)).state.rsplit("; ", 1)[-1] for s in (-1.0, 1.0)
    }
    for reason in ranked:
        if reason.profiles and any(_state_of(p) in sides for p in reason.profiles):
            return reason
    return ranked[0]


def _discontinuity(
    knot: _Knot,
    jumps: dict[str, float],
    left: dict[float, dict[str, float]],
    right: dict[float, dict[str, float]],
    engine: _Engine,
) -> Discontinuity:
    moved = ", ".join(f"{k} {j:+,.2f}" for k, j in jumps.items() if abs(j) > 1e-9)
    if knot.exact is not None:
        flips = [r for r in knot.reasons if r.kind == "forced_conversion"]
        why = flips[0].text if flips else knot.reasons[0].text
        where = f"X = {knot.x:,.2f}" + (
            "" if knot.exact.denominator == 1 else f" (exactly {_money(knot.exact)})"
        )
    else:
        why = f"located numerically by {knot.located}"
        where = f"X = {knot.x!r}"
    at_point = (
        f"the engine refuses the exit itself ({knot.probe.refusal.split('.')[0]})"
        if knot.probe.values is None
        else f"the engine at the exit itself reports {knot.probe.state}"
    )
    below = engine(knot.x - _offset(knot.x, knot.x)).state
    above = engine(knot.x + _offset(knot.x, knot.x)).state
    return Discontinuity(
        value=knot.x,
        jumps=dict(jumps),
        basis=(
            f"{where}: {why}. Just below: {below}; just above: {above}. Right limit minus "
            f"left limit, each extrapolated from the affine piece on its side: {moved}. "
            f"The value at the step is undefined: {at_point}; payout() reports the limit "
            "from above"
        ),
        exact=knot.exact is not None,
    )


def _assumptions(
    *,
    candidates: _Candidates,
    retained: int,
    located: int,
    bisections: int,
    tol: float,
    atol: float,
    undefined: list[float],
    upper_rule: str,
    upper: float,
    term: CollectiveConversion | None,
    discontinuities: list[Discontinuity],
    decreasing: list[str],
    engine: _Engine,
) -> list[str]:
    families = (
        "cumulative debt tiers; cumulative preference levels by seniority, participation-cap "
        "exhaustion, and each position's indifference to its own conversion, in every one of "
        f"{candidates.profiles} conversion profiles"
    )
    if term is not None:
        families += (
            f"; every exit at which a voting holder's gain from '{term.name}' changes sign "
            f"(holders: {', '.join(candidates.governed_holders)})"
        )
    oracle = (
        "ovf.waterfall.solve_waterfall"
        if term is None
        else f"ovf.governance.resolve_collective_conversion under '{term.name}'"
    )
    lines = [
        "X is the gross exit value with no transaction costs. A breakpoint is an X at which "
        "some position's share of the next marginal dollar changes.",
        f"Analytic candidates, exact in fractions.Fraction from exit_terms(as_of) and "
        f"exit_claim(as_of): {families}. {len(candidates.reasons)} distinct candidates.",
        f"Every candidate was tested against {oracle}: probes at X - d and X + d with d = "
        f"min({SIDE_OFFSET:g} * max(X, interval width), 10% of the interval), and at fractions "
        f"{', '.join(f'{t:.4f}' for t in INTERIOR)} of every interval. An interval is affine "
        f"when every interior probe lies within {tol:.3g} (atol / 2) of the line through the "
        "two end probes.",
        f"A candidate is kept only when the chord across it misses some probe by more than "
        f"{tol:.3g}: {retained} breakpoints kept of {len(candidates.reasons)} candidates"
        + (f", {located} located numerically" if located else "")
        + (f" after {bisections} interval splits" if bisections else "")
        + ".",
        "Weights are measured, (cash at the upper end - cash at the lower end) / width, from "
        "the engine's own values at each end; they are not assigned from the candidate "
        "families and are not clipped to [0, 1].",
        f"{upper_rule}. Above the largest candidate no fixed-profile allocation changes slope "
        "and no position's gain from switching changes sign, so the map is affine there; the "
        f"tail was probed up to {upper:,.2f} and once more at {2 * upper:,.2f}.",
        f"Replay tolerance atol = {atol:g}, absolute, per position, per probe; the finished "
        "schedule was replayed at every probe and at fresh probes at fractions "
        f"{', '.join(f'{t:.4f}' for t in VERIFY)} of every tranche.",
        "The engine keeps an incumbent decision unless switching gains more than its own "
        "tolerance, 1e-8 + 1e-12 * X; probes sit at least d from every candidate, far "
        "outside that band.",
    ]
    if discontinuities:
        lines.append(
            f"The payoff steps at {len(discontinuities)} exit value(s): "
            + "; ".join(f"X = {d.value:,.2f} (largest jump {d.size:,.2f})" for d in discontinuities)
            + ". A call spread is continuous, so no combination of call spreads in any "
            "weights reproduces a step: this payoff is not in the span of the Option Pricing "
            "Method's decomposition. At each step the value is undefined and payout() reports "
            "the limit from above."
        )
    if undefined:
        lines.append(
            "ovf.governance refuses to price the isolated exit value(s) "
            + ", ".join(f"{x:,.2f}" for x in undefined)
            + ", where a pivotal voting holder's gain touches zero without changing sign. The "
            "map is continuous there (both one-sided limits agree), so no step is recorded; "
            "payout() reports that common limit and the replay check skips the point itself."
        )
    if decreasing:
        lines.append("Not monotone: " + "; ".join(decreasing) + ".")
    lines.extend(f"engine: {a}" for a in engine.assumptions)
    return lines


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def _money(value: Fraction | float) -> str:
    if isinstance(value, Fraction) and value.denominator != 1:
        return f"{value.numerator}/{value.denominator} (= {float(value):,.2f})"
    return f"{float(value):,.2f}".removesuffix(".00")


def _count(value: Fraction) -> str:
    return f"{float(value):,.6g}"


def _profile_words(converted: frozenset[str]) -> str:
    if not converted:
        return "no preferred position converted"
    return f"{', '.join(sorted(converted))} converted"


def _state_of(converted: frozenset[str]) -> str:
    return f"converted: {', '.join(sorted(converted))}" if converted else "none converted"


def _decision(sign: int) -> str:
    return {1: "consents", -1: "withholds", 0: "is indifferent"}[sign]
