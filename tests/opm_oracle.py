"""A second, independently written Option Pricing Method, used to try to break ``ovf.opm``.

Nothing in the oracle part of this module imports ``ovf.opm.breakpoints``,
``ovf.opm.allocate`` or ``ovf.opm.blackscholes``, and nothing is shared with the exact oracle
in ``tests/test_governance.py`` or with ``tests/opm_breakpoint_fixtures.py``. The routes are
chosen to differ from the ones under test, because a shared bug would defeat the comparison:

- **Breakpoints.** ``ovf.opm.breakpoints`` writes down analytic candidate families (preference
  levels, participation caps, conversion indifference, vote flips) and probes the float
  engine around them. Here no family is written down. The equilibrium payoff of the
  per-position conversion game is computed exactly over ``fractions.Fraction`` and treated as
  a black box: an interval on which it is not affine is split where the affine pieces at its
  two ends meet, or at its midpoint when they do not meet on the function. Under a collective
  conversion the governed payoff is assembled from two such black boxes (without and with the
  conversion) and the exact roots of each voting holder's gain, which is affine between their
  kinks.
- **Allocation.** ``ovf.opm.allocate`` sums Black-Scholes-Merton call spreads. Here the payoff
  is integrated against the lognormal density by Gauss-Legendre quadrature in the standard
  normal variable, with the integration grid split at every kink and step. No normal
  distribution function and no option value is evaluated anywhere in the oracle.

What is shared is the specification only: the waterfall rule of docs/semantics.md, the
two-stage sincere vote of docs/governance.md, and the lognormal model of docs/opm.md.

The second half of the module is the search harness behind docs/opm-findings.md. It calls the
modules under test, and it is the only place that does: every such import is inside
``_system_under_test``, and ``tests/test_opm_validation.py`` checks that. Replay with

    .venv/bin/python -m tests.opm_oracle --tables 1000 --workers 8
"""

from __future__ import annotations

import argparse
import ast
import functools
import itertools
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import numpy as np

import ovf
from ovf.governance import (
    CollectiveConversion,
    GovernanceIndeterminateError,
    VoteRequirement,
    resolve_collective_conversion,
)
from ovf.waterfall import solve_waterfall

Q = Fraction
Vector = tuple[Fraction, ...]

ISSUE_DATE = date(2026, 1, 1)
AS_OF = date(2028, 1, 1)
"""730 days after ISSUE_DATE, so Actual/365 Fixed gives exactly two years."""
DEBT_RATE = Q(1, 16)
"""6.25% simple: dyadic, so the engine's float claim principal x 1.125 is exact."""
DEBT_YEARS = Q(2)

MODULES_UNDER_TEST = ("ovf.opm.breakpoints", "ovf.opm.allocate", "ovf.opm.blackscholes")
"""Imported only inside ``_system_under_test``; checked by tests/test_opm_validation.py."""


class OracleError(Exception):
    """The oracle could not establish the payoff; never a verdict about the code under test."""


class UndeterminedIntervalError(OracleError):
    """The sincere vote is undefined on a whole open interval of exits."""

    def __init__(self, lower: Fraction, upper: Fraction | None) -> None:
        super().__init__(f"vote undefined on ({float(lower)!r}, {upper and float(upper)!r})")
        self.lower = lower
        self.upper = upper


# ---------------------------------------------------------------------------
# Tables, as exact positions
# ---------------------------------------------------------------------------

Kind = Literal["common", "preferred", "debt", "pool"]


@dataclass(frozen=True)
class Position:
    """One position, stated exactly. ``cap`` is the total participation cap as a multiple of
    invested capital; ``principal`` is used by debt only."""

    security_id: str
    holder: str
    kind: Kind
    shares: Fraction = Q(0)
    price: Fraction = Q(0)
    multiple: Fraction = Q(1)
    seniority: int = 1
    participating: bool = False
    cap: Fraction | None = None
    ratio: Fraction = Q(1)
    principal: Fraction = Q(0)

    @property
    def claim(self) -> Fraction:
        """Debt: principal with simple interest to AS_OF. Preferred: its preference."""
        if self.kind == "debt":
            return self.principal * (1 + DEBT_RATE * DEBT_YEARS)
        if self.kind == "preferred":
            return self.shares * self.price * self.multiple
        return Q(0)

    @property
    def cap_amount(self) -> Fraction | None:
        if self.kind != "preferred" or not self.participating or self.cap is None:
            return None
        return self.shares * self.price * self.cap

    @property
    def units(self) -> Fraction:
        """Common-equivalent shares in the residual."""
        if self.kind == "common":
            return self.shares
        if self.kind == "preferred":
            return self.shares * self.ratio
        return Q(0)

    def security(self) -> ovf.Security:
        if self.kind == "common":
            return ovf.common(
                float(self.shares), holder_id=self.holder, security_id=self.security_id
            )
        if self.kind == "preferred":
            return ovf.preferred(
                float(self.shares),
                float(self.price),
                seniority=self.seniority,
                liquidation_multiple=float(self.multiple),
                participating=self.participating,
                participation_cap=None if self.cap is None else float(self.cap),
                conversion_ratio=float(self.ratio),
                holder_id=self.holder,
                security_id=self.security_id,
            )
        if self.kind == "debt":
            return ovf.debt(
                float(self.principal),
                float(DEBT_RATE),
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=ISSUE_DATE,
                seniority=self.seniority,
                holder_id=self.holder,
                security_id=self.security_id,
            )
        return ovf.option_pool(
            float(self.shares), holder_id=self.holder, security_id=self.security_id
        )


Approval = tuple[tuple[str, ...], Fraction, str]
"""(voting security_ids, exact threshold, "at_least" or "more_than")."""


@dataclass(frozen=True)
class Term:
    """A Requisite Holders mandatory conversion (docs/governance.md)."""

    converts: tuple[str, ...]
    approvals: tuple[Approval, ...]


@dataclass(frozen=True)
class Table:
    generator: str
    seed: int
    positions: tuple[Position, ...]
    term: Term | None = None

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(p.security_id for p in self.positions)

    @property
    def as_of(self) -> date | None:
        return AS_OF if any(p.kind == "debt" for p in self.positions) else None

    def plain(self) -> Table:
        return replace(self, term=None)

    def securities(self) -> tuple[ovf.Security, ...]:
        return tuple(p.security() for p in self.positions)

    def collective_conversion(self) -> CollectiveConversion | None:
        if self.term is None:
            return None
        return CollectiveConversion(
            name="Requisite Holders mandatory conversion",
            converts=self.term.converts,
            approvals=tuple(
                VoteRequirement(
                    name=f"approval {k}",
                    voters=voters,
                    threshold=threshold,
                    comparison=comparison,  # type: ignore[arg-type]
                    source="generated, NVCA Model COI s.5.1(b) and fn 64",
                )
                for k, (voters, threshold, comparison) in enumerate(self.term.approvals)
            ),
            source="generated, NVCA Model COI s.5.1(b)",
        )

    def describe(self) -> str:
        parts = []
        for p in self.positions:
            if p.kind == "preferred":
                cap = f" cap {p.cap}x" if p.cap is not None else ""
                part = " participating" if p.participating else ""
                parts.append(
                    f"{p.security_id}[{p.holder}] {p.shares}@{p.price} {p.multiple}x sr{p.seniority}"
                    f"{part}{cap} ratio {p.ratio}"
                )
            elif p.kind == "debt":
                parts.append(f"{p.security_id}[{p.holder}] debt {p.principal}")
            else:
                parts.append(f"{p.security_id}[{p.holder}] {p.kind} {p.shares}")
        if self.term is not None:
            parts.append(f"term converts {self.term.converts} approvals {self.term.approvals}")
        return f"{self.generator}#{self.seed}: " + "; ".join(parts)


# ---------------------------------------------------------------------------
# The exact game: waterfall, equilibrium, vote
# ---------------------------------------------------------------------------


class ExactGame:
    """The per-position conversion game at an exit, in exact arithmetic.

    The rule is docs/semantics.md restated from the text, not from ``ovf.waterfall``: debt by
    seniority, pro rata by claim within a tier; preferred preferences by ascending seniority,
    pro rata by preference within a tier; the residual pro rata by common-equivalent units
    among common, converted and participating positions, with a capped participant stopping
    at its total cap. A feasible profile allocates the whole exit; an equilibrium is a
    feasible profile in which no player gains by switching alone. ``payoff`` returns the
    unique equilibrium payoff vector and raises ``OracleError`` if there is not exactly one.
    """

    def __init__(self, table: Table, forced: frozenset[str] = frozenset()) -> None:
        self.ids = table.ids
        index = {sid: i for i, sid in enumerate(self.ids)}
        positions = table.positions
        debt_ranks = sorted({p.seniority for p in positions if p.kind == "debt"})
        self.debt_tiers = [
            [
                (index[p.security_id], p.claim)
                for p in positions
                if p.kind == "debt" and p.seniority == r
            ]
            for r in debt_ranks
        ]
        prefs = [p for p in positions if p.kind == "preferred" and p.shares > 0]
        ranks = sorted({p.seniority for p in prefs})
        self.tiers = [
            [(index[p.security_id], p.security_id, p.claim) for p in prefs if p.seniority == r]
            for r in ranks
        ]
        self.commons = [
            (index[p.security_id], p.units)
            for p in positions
            if p.kind == "common" and p.shares > 0
        ]
        self.prefs = [
            (index[p.security_id], p.security_id, p.units, p.participating, p.cap_amount)
            for p in prefs
        ]
        self.players = [p.security_id for p in prefs if p.security_id not in forced]
        self.player_index = [index[sid] for sid in self.players]
        self.profiles = [
            forced | frozenset(sid for j, sid in enumerate(self.players) if mask >> j & 1)
            for mask in range(1 << len(self.players))
        ]
        self.cache: dict[Fraction, tuple[Vector, Vector]] = {}

    def allocate(
        self, equity: Fraction, converted: frozenset[str]
    ) -> tuple[list[Fraction], Fraction]:
        """Cash to every position for a fixed profile, and the cash nobody may take."""
        out = [Q(0)] * len(self.ids)
        cash = equity
        for tier in self.tiers:
            holding = [(i, pref) for i, sid, pref in tier if sid not in converted]
            need = sum((pref for _, pref in holding), Q(0))
            if not need:
                continue
            pay = min(cash, need)
            for i, pref in holding:
                out[i] = pay * pref / need
            cash -= pay
        units: dict[int, Fraction] = dict(self.commons)
        room: dict[int, Fraction] = {}
        for i, sid, u, participating, cap_amount in self.prefs:
            if sid in converted:
                units[i] = u
            elif participating:
                units[i] = u
                if cap_amount is not None:
                    room[i] = max(Q(0), cap_amount - out[i])
        while cash > 0 and units:
            level = cash / sum(units.values(), Q(0))
            full = [i for i in units if i in room and room[i] < level * units[i]]
            if not full:
                for i, u in units.items():
                    out[i] += level * u
                return out, Q(0)
            for i in full:
                out[i] += room[i]
                cash -= room[i]
                del units[i]
        return out, cash

    def payoff(self, x: Fraction) -> Vector:
        """The unique equilibrium payoff vector at an exit of ``x``."""
        return self.evaluate(x)[0]

    def extended(self, x: Fraction) -> Vector:
        """The payoff followed by every profile's allocation and its stranded cash.

        The kink finder tests this whole vector for affinity. Probing the equilibrium payoff
        alone missed, on generated tables, a feature that leaves its chord and returns to it
        between probes: a junior non-participating series fills its preference, holds, and
        then converts back onto the very line its conversion would have followed from the
        start (docs/opm-findings.md, search 1). A fixed-profile allocation changes regime in
        one direction as the exit rises, so it is argued, not proven, that it cannot hide
        such a return, and an equilibrium switch inside an interval where every profile
        allocation is affine makes a single kink, which any interior probe sees.
        """
        return self.evaluate(x)[1]

    def evaluate(self, x: Fraction) -> tuple[Vector, Vector]:
        hit = self.cache.get(x)
        if hit is not None:
            return hit
        if x < 0:
            raise OracleError(f"negative exit {x}")
        debt = [Q(0)] * len(self.ids)
        equity = x
        for tier in self.debt_tiers:
            need = sum((c for _, c in tier), Q(0))
            pay = min(equity, need)
            for i, c in tier:
                debt[i] = pay * c / need
            equity -= pay
        allocations = [self.allocate(equity, s) for s in self.profiles]
        vectors: set[Vector] = set()
        for mask, (out, stranded) in enumerate(allocations):
            if stranded:
                continue
            if all(
                allocations[mask ^ (1 << j)][0][i] <= out[i]
                for j, i in enumerate(self.player_index)
            ):
                vectors.add(tuple(out))
        if len(vectors) != 1:
            raise OracleError(f"{len(vectors)} equilibrium payoff vectors at an exit of {x}")
        vector = tuple(d + e for d, e in zip(debt, next(iter(vectors)), strict=True))
        flat = tuple(v for out, stranded in allocations for v in (*out, stranded))
        self.cache[x] = (vector, vector + flat)
        return self.cache[x]


Regime = Literal["without", "with", "undefined"]


class ExactVote:
    """The two-stage sincere vote of docs/governance.md, in exact arithmetic.

    Each voting holder compares its total cash, over every position it holds, with and
    without the conversion; it consents on a strict gain, withholds on a strict loss, and is
    indifferent otherwise. Weights are as-converted shares. When indifferent holders decide
    the vote and the two outcomes pay differently, the outcome is undefined.
    """

    def __init__(self, table: Table) -> None:
        assert table.term is not None
        self.term = table.term
        self.without = ExactGame(table)
        self.with_ = ExactGame(table, frozenset(table.term.converts))
        by_id = {p.security_id: p for p in table.positions}
        self.holdings: dict[str, list[int]] = {}
        for i, p in enumerate(table.positions):
            self.holdings.setdefault(p.holder, []).append(i)
        self.weights: list[dict[str, Fraction]] = []
        for voters, _, _ in self.term.approvals:
            weights: dict[str, Fraction] = {}
            for sid in voters:
                holder = by_id[sid].holder
                weights[holder] = weights.get(holder, Q(0)) + by_id[sid].units
            self.weights.append(weights)
        self.voters = sorted({h for w in self.weights for h in w})

    def gains(self, x: Fraction) -> dict[str, Fraction]:
        base, forced = self.without.payoff(x), self.with_.payoff(x)
        return {h: sum((forced[i] - base[i] for i in self.holdings[h]), Q(0)) for h in self.voters}

    def outcome(self, x: Fraction) -> tuple[Regime, Vector | None]:
        base, forced = self.without.payoff(x), self.with_.payoff(x)
        gains = self.gains(x)

        def approved(indifferent_consent: bool) -> bool:
            for (_, threshold, comparison), weights in zip(
                self.term.approvals, self.weights, strict=True
            ):
                total = sum(weights.values(), Q(0))
                yes = sum(
                    (
                        w
                        for h, w in weights.items()
                        if gains[h] > 0 or (indifferent_consent and gains[h] == 0)
                    ),
                    Q(0),
                )
                if not (
                    yes >= threshold * total
                    if comparison == "at_least"
                    else yes > threshold * total
                ):
                    return False
            return True

        passes, passes_if_indifferent = approved(False), approved(True)
        if base != forced and passes != passes_if_indifferent:
            return "undefined", None
        return ("with", forced) if passes else ("without", base)


# ---------------------------------------------------------------------------
# Kinks of a black-box continuous piecewise-linear map, exactly
# ---------------------------------------------------------------------------

PROBE_T = (Q(17, 71), Q(1, 2), Q(53, 71))
"""Fixed interior probes of every interval, as fractions of its width."""
MAX_SPLITS = 20_000


def _on_chord(y: Vector, ya: Vector, yb: Vector, t: Fraction) -> bool:
    return all(v == a + t * (b - a) for v, a, b in zip(y, ya, yb, strict=True))


def _meeting_point(f: Callable[[Fraction], Vector], a: Fraction, b: Fraction) -> Fraction | None:
    """Where the lines through each end of [a, b] and a point just inside it meet, if f
    passes through both lines there; otherwise None."""
    h = (b - a) / 4096
    ya, yb, yl, yr = f(a), f(b), f(a + h), f(b - h)
    left = [(v - u) / h for v, u in zip(yl, ya, strict=True)]
    right = [(u - v) / h for v, u in zip(yr, yb, strict=True)]
    j = max(range(len(left)), key=lambda c: abs(left[c] - right[c]))
    if left[j] == right[j]:
        return None
    k = (yb[j] - ya[j] + left[j] * a - right[j] * b) / (left[j] - right[j])
    if not a < k < b:
        return None
    yk = f(k)
    for c in range(len(yk)):
        if yk[c] != ya[c] + left[c] * (k - a) or yk[c] != yb[c] + right[c] * (k - b):
            return None
    return k


def continuous_kinks(
    f: Callable[[Fraction], Vector],
    lower: Fraction,
    upper: Fraction,
    *,
    seed: int = 0,
    leading: int | None = None,
    max_splits: int = MAX_SPLITS,
) -> list[Fraction]:
    """Every exit in (lower, upper) at which some component of f changes slope, exactly.

    An interval is accepted as affine when f lies on its chord at three fixed interior
    points and two random rational ones. That is a finite test, so a feature confined
    between probes could in principle be missed; the harness also replays the result against
    the float engine. f must be continuous: a step makes the splitting run out of budget.
    Only the first ``leading`` components decide which knots are kinks; the rest of the
    vector only guides the splitting.
    """
    rng = random.Random(seed)
    todo = [(lower, upper)]
    pieces: list[tuple[Fraction, Fraction]] = []
    splits = 0
    while todo:
        a, b = todo.pop()
        ya, yb, width = f(a), f(b), b - a
        probes = [*PROBE_T, Q(rng.randint(1, 9_999), 10_000), Q(rng.randint(1, 9_999), 10_000)]
        if all(_on_chord(f(a + t * width), ya, yb, t) for t in probes):
            pieces.append((a, b))
            continue
        splits += 1
        if splits > max_splits:
            raise OracleError(
                f"no piecewise-linear description after {max_splits} splits near "
                f"[{float(a)!r}, {float(b)!r}]: the map is not continuous there"
            )
        k = _meeting_point(f, a, b)
        middle = k if k is not None else a + width / 2
        todo += [(a, middle), (middle, b)]
    pieces.sort()

    def slope(a: Fraction, b: Fraction) -> Vector:
        ends = zip(f(a)[:leading], f(b)[:leading], strict=True)
        return tuple((v - u) / (b - a) for u, v in ends)

    return [
        b0 for (a0, b0), (a1, b1) in itertools.pairwise(pieces) if slope(a0, b0) != slope(a1, b1)
    ]


def upper_bound(table: Table) -> Fraction:
    """An exit beyond which every conversion choice is settled and the map is affine.

    Above ``debt + preferences + max_i M_i * U / u_i``, where M_i is the most position i can
    receive without converting (its cap, or its preference if non-participating) and U all
    common-equivalent units, converting pays each such position at least (X - debt -
    preferences) * u_i / U >= M_i whatever the others do. Uncapped participants never convert.
    """
    debt = sum((p.claim for p in table.positions if p.kind == "debt"), Q(0))
    prefs = [p for p in table.positions if p.kind == "preferred" and p.shares > 0]
    total_pref = sum((p.claim for p in prefs), Q(0))
    total_units = sum((p.units for p in table.positions), Q(0))
    reach = [
        (p.cap_amount if p.cap_amount is not None else p.claim) * total_units / p.units
        for p in prefs
        if not p.participating or p.cap is not None
    ]
    return debt + total_pref + max(reach, default=Q(0))


# ---------------------------------------------------------------------------
# The oracle schedule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleSchedule:
    """The payoff as exact tranches. Tranche j is [knots[j], knots[j+1]); the last is
    unbounded. ``starts[j]`` is the right limit at knots[j]; ``steps`` holds every knot at
    which the payoff jumps, with the jump (right limit minus left limit)."""

    ids: tuple[str, ...]
    knots: tuple[Fraction, ...]
    starts: tuple[Vector, ...]
    slopes: tuple[Vector, ...]
    steps: tuple[tuple[Fraction, Vector], ...]

    @property
    def continuous(self) -> bool:
        return not self.steps

    @property
    def negative_weight(self) -> bool:
        return any(w < 0 for s in self.slopes for w in s)

    @property
    def monotone(self) -> bool:
        return not self.negative_weight and all(j >= 0 for _, js in self.steps for j in js)

    def tranche(self, x: Fraction) -> int:
        lo, hi = 0, len(self.knots)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.knots[mid] <= x:
                lo = mid
            else:
                hi = mid
        return lo

    def payout(self, x: Fraction) -> Vector:
        j = self.tranche(x)
        return tuple(
            s + w * (x - self.knots[j]) for s, w in zip(self.starts[j], self.slopes[j], strict=True)
        )

    def weights(self, x: Fraction) -> Vector:
        return self.slopes[self.tranche(x)]

    def payout_float(self, x: float) -> dict[str, float]:
        return dict(zip(self.ids, (float(v) for v in self.payout(Q(x))), strict=True))

    def pieces(self) -> tuple[np.ndarray, np.ndarray]:
        """Intercepts and slopes of each tranche's line, in floats, for integration."""
        alpha = np.array(
            [
                [float(s - w * k) for s, w in zip(st, sl, strict=True)]
                for k, st, sl in zip(self.knots, self.starts, self.slopes, strict=True)
            ]
        )
        beta = np.array([[float(w) for w in sl] for sl in self.slopes])
        return alpha, beta


def _assemble(
    ids: tuple[str, ...],
    knots: list[Fraction],
    functions: list[Callable[[Fraction], Vector]],
) -> OracleSchedule:
    """Tranches from per-interval affine functions, dropping knots that change nothing."""
    starts, slopes, lefts = [], [], []
    for j, (k, fn) in enumerate(zip(knots, functions, strict=True)):
        top = knots[j + 1] if j + 1 < len(knots) else k + 1
        y0, y1 = fn(k), fn(top)
        starts.append(y0)
        slopes.append(tuple((b - a) / (top - k) for a, b in zip(y0, y1, strict=True)))
        lefts.append(functions[j - 1](k) if j else y0)
    kept = [0]
    steps: list[tuple[Fraction, Vector]] = []
    for j in range(1, len(knots)):
        jump = tuple(r - left for r, left in zip(starts[j], lefts[j], strict=True))
        if any(jump):
            steps.append((knots[j], jump))
            kept.append(j)
        elif slopes[j] != slopes[kept[-1]]:
            kept.append(j)
    return OracleSchedule(
        ids=ids,
        knots=tuple(knots[j] for j in kept),
        starts=tuple(starts[j] for j in kept),
        slopes=tuple(slopes[j] for j in kept),
        steps=tuple(steps),
    )


def _verify(
    schedule: OracleSchedule, truth: Callable[[Fraction], Vector | None], seed: int
) -> None:
    """Replay the assembled schedule against the exact payoff at random rational exits."""
    rng = random.Random(seed)
    for j, k in enumerate(schedule.knots):
        top = schedule.knots[j + 1] if j + 1 < len(schedule.knots) else 2 * k + 1
        for _ in range(3):
            x = k + (top - k) * Q(rng.randint(1, 9_999), 10_000)
            expected = truth(x)
            if expected is not None and schedule.payout(x) != expected:
                raise OracleError(f"assembled schedule misses the exact payoff at {float(x)!r}")


def oracle_schedule(table: Table) -> OracleSchedule:
    """The exact payoff of ``table`` as a function of the exit, under its term if it has one.

    Raises ``UndeterminedIntervalError`` where the governed payoff is undefined on an interval, and
    ``OracleError`` where the oracle itself cannot establish it.
    """
    hi = 2 * upper_bound(table) + 1
    n = len(table.ids)
    plain = ExactGame(table)
    if table.term is None:
        knots = [Q(0), *continuous_kinks(plain.extended, Q(0), hi, seed=table.seed, leading=n)]
        _check_tail(plain.payoff, knots, hi)
        schedule = _assemble(table.ids, knots, [plain.payoff] * len(knots))
        _verify(schedule, plain.payoff, table.seed)
        return schedule

    vote = ExactVote(table)
    base = sorted(
        {
            Q(0),
            *continuous_kinks(vote.without.extended, Q(0), hi, seed=table.seed, leading=n),
            *continuous_kinks(vote.with_.extended, Q(0), hi, seed=table.seed + 1, leading=n),
        }
    )
    _check_tail(vote.without.payoff, base, hi)
    _check_tail(vote.with_.payoff, base, hi)
    # Each gain is affine between the kinks of the two stage payoffs: find its roots exactly.
    probe = [*base, base[-1] + 1]
    gains = [vote.gains(x) for x in probe]
    roots: set[Fraction] = set()
    for (a, ga), (b, gb) in itertools.pairwise(zip(probe, gains, strict=True)):
        for h in vote.voters:
            if ga[h] * gb[h] < 0:
                roots.add(a + ga[h] * (b - a) / (ga[h] - gb[h]))
    last, g_last, g_next = base[-1], gains[-2], gains[-1]
    for h in vote.voters:
        slope = g_next[h] - g_last[h]
        if slope and g_last[h] * slope < 0:
            roots.add(last - g_last[h] / slope)
    knots = sorted(set(base) | roots)
    functions: list[Callable[[Fraction], Vector]] = []
    for j, k in enumerate(knots):
        top = knots[j + 1] if j + 1 < len(knots) else None
        middle = (k + top) / 2 if top is not None else k + 1
        regime, _ = vote.outcome(middle)
        if regime == "undefined":
            raise UndeterminedIntervalError(k, top)
        functions.append(vote.with_.payoff if regime == "with" else vote.without.payoff)
    schedule = _assemble(table.ids, knots, functions)

    def truth(x: Fraction) -> Vector | None:
        return vote.outcome(x)[1]

    _verify(schedule, truth, table.seed)
    return schedule


def _check_tail(f: Callable[[Fraction], Vector], knots: Sequence[Fraction], hi: Fraction) -> None:
    far = [hi, 3 * hi + 7, 10 * hi + 1]
    ys = [f(x) for x in far]
    t = (far[1] - far[0]) / (far[2] - far[0])
    if knots and knots[-1] > hi or not _on_chord(ys[1], ys[0], ys[2], t):
        raise OracleError("the payoff is not affine beyond the stated upper bound")


def exact_payout(table: Table, x: Fraction) -> Vector | None:
    """The exact payoff at one exit; None where the vote is undefined."""
    if table.term is None:
        return ExactGame(table).payoff(x)
    return ExactVote(table).outcome(x)[1]


# ---------------------------------------------------------------------------
# Value by integrating the payoff against the lognormal density
# ---------------------------------------------------------------------------

GL_NODES, GL_WEIGHTS = np.polynomial.legendre.leggauss(20)
Z_REACH = 40.0
"""Integrate over +-40 standard deviations; the density there is below 1e-347."""
Z_STEP = 0.5
LOG_SQRT_2PI = 0.5 * math.log(2.0 * math.pi)


@dataclass(frozen=True)
class Integral:
    values: dict[str, float]
    mass_error: float
    """|integral of the density - 1|, the quadrature's own error on the constant."""
    mean_error: float
    """|discounted E[X] - spot * exp(-q T)| / (spot * exp(-q T)), its error on X itself."""


def lognormal_value(
    schedule: OracleSchedule,
    *,
    spot: float,
    volatility: float,
    time: float,
    rate: float,
    dividend_yield: float = 0.0,
) -> Integral:
    """exp(-r T) E[payoff(X_T)] with ln X_T ~ N(ln S + (r - q - s^2/2) T, s^2 T).

    In the standard normal variable z, X_T = S exp(m + v z) with v = s sqrt(T). On each
    tranche the payoff is alpha + beta X, so its integral is alpha * int(phi) + beta * int(X
    phi), and X phi is evaluated as one exponential so nothing overflows. Both integrals are
    taken by 20-point Gauss-Legendre on subintervals no wider than 0.5, split at the z of
    every knot. No distribution function is evaluated.
    """
    v = volatility * math.sqrt(time)
    drift = (rate - dividend_yield - 0.5 * volatility * volatility) * time
    log_spot = math.log(spot)
    lo, hi = -Z_REACH, max(Z_REACH, v + Z_REACH)
    kz = np.array([(math.log(float(k)) - log_spot - drift) / v for k in schedule.knots[1:]])
    inside = kz[(kz > lo) & (kz < hi)]
    edges = np.unique(np.concatenate([np.arange(lo, hi, Z_STEP), [hi], inside]))
    a, b = edges[:-1], edges[1:]
    mid, half = (a + b) / 2, (b - a) / 2
    z = mid[:, None] + half[:, None] * GL_NODES[None, :]
    w = half[:, None] * GL_WEIGHTS[None, :]
    density = np.exp(-0.5 * z * z - LOG_SQRT_2PI)
    first = np.exp(log_spot + drift + v * z - 0.5 * z * z - LOG_SQRT_2PI)
    mass = (w * density).sum(axis=1)
    mean = (w * first).sum(axis=1)
    tranche = np.searchsorted(kz, mid, side="right")
    n = len(schedule.knots)
    mass_by = np.bincount(tranche, weights=mass, minlength=n)
    mean_by = np.bincount(tranche, weights=mean, minlength=n)
    alpha, beta = schedule.pieces()
    discount = math.exp(-rate * time)
    values = {
        sid: discount
        * math.fsum(
            float(alpha[j, c]) * float(mass_by[j]) + float(beta[j, c]) * float(mean_by[j])
            for j in range(n)
        )
        for c, sid in enumerate(schedule.ids)
    }
    forward = spot * math.exp(-dividend_yield * time)
    return Integral(
        values=values,
        mass_error=abs(math.fsum(mass_by.tolist()) - 1.0),
        mean_error=abs(discount * math.fsum(mean_by.tolist()) - forward) / forward,
    )


def digital_value(
    level: float, *, spot: float, volatility: float, time: float, rate: float, dividend_yield: float
) -> float:
    """exp(-r T) P(X_T >= level), from math.erfc: the value of a unit step at ``level``."""
    v = volatility * math.sqrt(time)
    drift = (rate - dividend_yield - 0.5 * volatility * volatility) * time
    z = (math.log(level) - math.log(spot) - drift) / v
    return math.exp(-rate * time) * 0.5 * math.erfc(z / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

THRESHOLDS: tuple[tuple[Fraction, str], ...] = (
    (Q(1, 2), "more_than"),
    (Q(1, 2), "at_least"),
    (Q(3, 5), "at_least"),
    (Q(2, 3), "at_least"),
)


def _term(rng: random.Random, prefs: list[Position], subset: bool) -> Term:
    ids = [p.security_id for p in prefs]
    converts = (
        ids
        if not subset or rng.random() < 0.7
        else sorted(rng.sample(ids, rng.randint(1, len(ids))))
    )
    threshold, comparison = rng.choice(THRESHOLDS)
    approvals: list[Approval] = [(tuple(ids), threshold, comparison)]
    if rng.random() < 0.3:  # NVCA fn 64: a series consent on top of the Requisite Holders
        approvals.append(((rng.choice(converts),), Q(1, 2), "more_than"))
    return Term(tuple(converts), tuple(approvals))


def adversarial_table(seed: int) -> Table:
    """2-4 preferred positions with adversarial terms at small integer scale.

    Multiples 1, 1.5, 2; half participating, most of those capped at the multiple or above
    it; conversion ratios 0.5-2; seniority 1-3 with collisions; common from none to 2,000
    shares; sometimes one holder with two positions or an investor holding the common; a
    6.25% loan ahead of everything in 20% of tables and an unallocated pool in 20%. The term
    converts every preferred position (70%) or a random subset. Every input is dyadic, so
    the engine's floats and the oracle's fractions are the same numbers.
    """
    rng = random.Random(f"adversarial-{seed}")
    prefs: list[Position] = []
    for i in range(rng.randint(2, 4)):
        multiple = rng.choice((Q(1), Q(1), Q(3, 2), Q(2)))
        participating = rng.random() < 0.5
        cap = (
            multiple + rng.choice((Q(0), Q(1, 2), Q(1), Q(2)))
            if participating and rng.random() < 0.6
            else None
        )
        prefs.append(
            Position(
                security_id=f"p{i}",
                holder=f"h{i}",
                kind="preferred",
                shares=Q(rng.randint(1, 10) * 100),
                price=Q(rng.randint(1, 6)),
                multiple=multiple,
                seniority=rng.randint(1, 3),
                participating=participating,
                cap=cap,
                ratio=rng.choice((Q(1), Q(1), Q(1), Q(3, 2), Q(2), Q(1, 2))),
            )
        )
    if rng.random() < 0.3:
        i, j = rng.sample(range(len(prefs)), 2)
        prefs[j] = replace(prefs[j], holder=prefs[i].holder)
    positions: list[Position] = []
    common = rng.choice((0, 1, 2, 5, 8, 10, 20)) * 100
    if common:
        holder = rng.choice(prefs).holder if rng.random() < 0.2 else "founders"
        positions.append(Position("common", holder, "common", shares=Q(common)))
    if rng.random() < 0.2:
        positions.insert(
            0, Position("loan", "lender", "debt", seniority=0, principal=Q(rng.randint(1, 20) * 80))
        )
    positions.extend(prefs)
    if rng.random() < 0.2:
        positions.append(Position("pool", "esop", "pool", shares=Q(rng.randint(1, 10) * 100)))
    return Table("adversarial", seed, tuple(positions), _term(rng, prefs, subset=True))


def venture_table(seed: int) -> Table:
    """2-4 priced rounds in the usual shape, at the scale of a real company.

    Founders 4-10 million common, sometimes employee common, an unallocated pool in half of
    tables. Each round sells 10-25% of the post-money fully diluted shares; the first price
    is $0.25-$1.00 and each later round is priced 1.5x-4x the last (a 0.75x down round in
    one round in ten). Terms: 1x non-participating in about four rounds of five; otherwise
    1x participating (capped at 3x in most), 1.5x or 2x. Seniority stacked, later senior,
    or pari passu, half each. Each round has its own lead; in 30% an earlier lead also holds
    the new series. The term is the NVCA Requisite Holders mandatory conversion of all
    preferred, "more than 1/2", "at least 1/2", "at least 3/5" or "at least 2/3", with a
    series consent for one converted series in 30% of tables (fn 64). All prices are dyadic.
    """
    rng = random.Random(f"venture-{seed}")
    positions: list[Position] = [
        Position("common", "founders", "common", shares=Q(rng.choice((4, 5, 6, 8, 10)) * 1_000_000))
    ]
    if rng.random() < 0.4:
        positions.append(
            Position("staff", "employees", "common", shares=Q(rng.choice((250, 500, 1000)) * 1_000))
        )
    pool = Q(rng.choice((0, 0, 500, 1000, 1500)) * 1_000)
    fully_diluted = sum((p.shares for p in positions), Q(0)) + pool
    price = rng.choice((Q(1, 4), Q(1, 2), Q(3, 4), Q(1)))
    stacked = rng.random() < 0.5
    rounds = rng.randint(2, 4)
    prefs: list[Position] = []
    for k in range(rounds):
        sold = rng.choice((Q(1, 10), Q(3, 20), Q(1, 5), Q(1, 4)))
        shares = Q(round(fully_diluted * sold / (1 - sold) / 1000) * 1000)
        draw = rng.random()
        multiple, participating, cap = Q(1), False, None
        if draw < 0.08:
            participating, cap = True, Q(3) if rng.random() < 0.7 else None
        elif draw < 0.14:
            multiple = Q(3, 2)
        elif draw < 0.2:
            multiple = Q(2)
        holder = f"fund{k}"
        if k and rng.random() < 0.3:
            holder = rng.choice(prefs).holder
        prefs.append(
            Position(
                security_id=f"series{k}",
                holder=holder,
                kind="preferred",
                shares=shares,
                price=price,
                multiple=multiple,
                seniority=rounds - k if stacked else 1,
                participating=participating,
                cap=cap,
            )
        )
        fully_diluted += shares
        price *= Q(3, 4) if rng.random() < 0.1 else rng.choice((Q(3, 2), Q(2), Q(5, 2), Q(3), Q(4)))
    positions.extend(prefs)
    if pool:
        positions.append(Position("pool", "esop", "pool", shares=pool))
    return Table("venture", seed, tuple(positions), _term(rng, prefs, subset=False))


GENERATORS: dict[str, Callable[[int], Table]] = {
    "adversarial": adversarial_table,
    "venture": venture_table,
}


def pick_spot(schedule: OracleSchedule, rng: random.Random) -> float:
    """An equity value log-uniform between half the first breakpoint and twice the last."""
    lo = float(schedule.knots[1]) / 2 if len(schedule.knots) > 1 else 1.0
    hi = 2 * float(schedule.knots[-1]) if len(schedule.knots) > 1 else 10.0
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


# ---------------------------------------------------------------------------
# The search harness: everything below calls the code under test
# ---------------------------------------------------------------------------


def _system_under_test() -> SimpleNamespace:
    """The modules being validated. The only place in this file that imports them."""
    import ovf.opm.allocate as allocate
    from ovf.opm.breakpoints import breakpoint_schedule
    from ovf.opm.types import BreakpointError, OpmAssumptionError, OpmInputs

    return SimpleNamespace(
        allocate=allocate,
        opm_allocate=allocate.opm_allocate,
        breakpoint_schedule=breakpoint_schedule,
        BreakpointError=BreakpointError,
        OpmAssumptionError=OpmAssumptionError,
        OpmInputs=OpmInputs,
    )


def engine_payout(table: Table, x: float) -> dict[str, float] | None:
    """The float engine's cash at one exit; None where ovf.governance refuses the vote."""
    securities = table.securities()
    try:
        if table.term is None:
            result = solve_waterfall(securities, x, as_of=table.as_of)
        else:
            term = table.collective_conversion()
            assert term is not None
            result = resolve_collective_conversion(
                securities, x, term=term, as_of=table.as_of
            ).result
    except GovernanceIndeterminateError:
        return None
    return {p.security_id: p.amount for p in result.payouts}


def replay_gap(table: Table, schedule: OracleSchedule) -> tuple[float, int]:
    """Largest gap between the oracle and the float engine, and how many exits were priced.
    Probes: 0.3, 0.5, 0.7 of every tranche, 0.1 to 0.9 of the last one out to twice the
    oracle's upper bound, and 1e-7 relative either side of every knot."""
    probes: list[float] = []
    knots = [float(k) for k in schedule.knots]
    reach = float(2 * upper_bound(table) + 1)
    for j, k in enumerate(knots):
        last = j + 1 == len(knots)
        top = max(2 * k + 1, reach) if last else knots[j + 1]
        spots = (0.1, 0.3, 0.5, 0.7, 0.9) if last else (0.3, 0.5, 0.7)
        probes += [k + t * (top - k) for t in spots]
        if k:
            probes += [k * (1 - 1e-7), k * (1 + 1e-7)]
    worst, priced = 0.0, 0
    for x in probes:
        engine = engine_payout(table, x)
        if engine is None:
            continue
        priced += 1
        ours = schedule.payout_float(x)
        worst = max(worst, max(abs(engine[k] - ours[k]) for k in ours))
    return worst, priced


def compare_schedules(ours: OracleSchedule, theirs: Any) -> dict[str, Any]:
    """Count, position and weights of the two derivations, and their steps and flags."""
    mine = [float(k) for k in ours.knots[1:]]
    other = [b.value for b in theirs.breakpoints[1:]]

    def nearest(x: float, pool: list[float]) -> float:
        return min((abs(x - y) for y in pool), default=math.inf)

    def matched(x: float, pool: list[float]) -> bool:
        return nearest(x, pool) <= 1e-9 * max(1.0, abs(x))

    edges = sorted({0.0, *mine, *other})
    tops = [*edges[1:], 2 * edges[-1] + 1]
    weight_gap = 0.0
    for lo, hi in zip(edges, tops, strict=True):
        x = lo + (hi - lo) / 2
        theirs_w = theirs.weights_at(x)
        ours_w = ours.weights(Q(x))
        weight_gap = max(
            weight_gap,
            max(
                abs(theirs_w.get(sid, 0.0) - float(w))
                for sid, w in zip(ours.ids, ours_w, strict=True)
            ),
        )
    our_steps = {float(c): j for c, j in ours.steps}
    their_steps = {d.value: d.jumps for d in theirs.discontinuities}
    jump_gap = 0.0
    for c, jumps in our_steps.items():
        partner = next((v for v in their_steps if abs(v - c) <= 1e-9 * max(1.0, c)), None)
        if partner is not None:
            jump_gap = max(
                jump_gap,
                max(
                    abs(their_steps[partner].get(sid, 0.0) - float(j))
                    for sid, j in zip(ours.ids, jumps, strict=True)
                ),
            )
    return {
        "count_ours": len(mine),
        "count_theirs": len(other),
        "unmatched_ours": [x for x in mine if not matched(x, other)],
        "unmatched_theirs": [x for x in other if not matched(x, mine)],
        "position_gap": max((nearest(x, other) for x in mine if matched(x, other)), default=0.0),
        "exact_positions": sum(1 for x in mine if x in set(other)),
        "weight_gap": weight_gap,
        "steps_ours": len(our_steps),
        "steps_theirs": len(their_steps),
        "unmatched_steps": [c for c in our_steps if not matched(c, list(their_steps))]
        + [c for c in their_steps if not matched(c, list(our_steps))],
        "jump_gap": jump_gap,
        "monotone": (ours.monotone, theirs.monotone),
        "continuous": (ours.continuous, theirs.continuous),
        "negative_weight_ours": ours.negative_weight,
        "negative_weight_theirs": any(w < 0 for t in theirs.tranches for w in t.weights.values()),
    }


@contextmanager
def checks_disabled(sut: SimpleNamespace) -> Iterator[None]:
    """What opm_allocate would report if it did not check continuity and monotonicity."""
    module = sut.allocate
    saved = module._check_continuity, module._check_monotone
    module._check_continuity = lambda schedule: None
    module._check_monotone = lambda schedule: None
    try:
        yield
    finally:
        module._check_continuity, module._check_monotone = saved


SIGMAS = (1e-3, 1e-2, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
TIMES = (1 / 12, 0.5, 1.0, 3.0, 5.0, 10.0)
RATES = ((0.04, 0.0), (-0.01, 0.02))
LIMIT_SIGMAS = tuple(10.0**-k for k in range(0, 11))
MARKETS = ((0.6, 3.0, 0.04), (0.3, 1.0, 0.04), (1.0, 5.0, 0.04))
"""(volatility, years, rate) for the error-size search; the first is the headline."""


def classify_refusal(exc: BaseException) -> str:
    text = str(exc)
    name = type(exc).__name__
    if name == "OpmAssumptionError":
        if text.startswith("Payoff is not continuous"):
            return "refused: step"
        if text.startswith("Payoff is not non-decreasing"):
            return "refused: negative weight"
        return "refused: other assumption"
    if name == "BreakpointError":
        if "refuses to price" in text:
            return "refused: vote undefined on an interval"
        if "gave up after" in text or "does not replay" in text:
            return "refused: schedule not verified"
        return "refused: other breakpoint error"
    if isinstance(exc, GovernanceIndeterminateError):
        return "refused: vote undefined at the equity value"
    return f"error: {name}"


def _allocate(
    sut: SimpleNamespace,
    table: Table,
    spot: float,
    market: tuple[float, float, float, float],
    schedule: Any = None,
) -> Any:
    sigma, years, rate, dividend = market
    return sut.opm_allocate(
        table.securities(),
        inputs=sut.OpmInputs(
            equity_value=spot,
            volatility=sigma,
            time_to_liquidity=years,
            risk_free_rate=rate,
            dividend_yield=dividend,
        ),
        as_of=table.as_of,
        schedule=schedule,
        collective_conversion=table.collective_conversion(),
    )


def _oracle_verdict(table: Table) -> tuple[str, OracleSchedule | None, str]:
    try:
        schedule = oracle_schedule(table)
    except UndeterminedIntervalError as exc:
        return "vote undefined on an interval", None, str(exc)
    except OracleError as exc:
        return "oracle error", None, str(exc)
    if not schedule.continuous:
        return "step", schedule, ""
    if schedule.negative_weight:
        return "negative weight, no step", schedule, ""
    return "applies", schedule, ""


def examine(generator: str, seed: int, *, grid: bool = True) -> dict[str, Any]:
    """Every search for one generated table, with and without its term. Returns plain data."""
    sut = _system_under_test()
    governed = GENERATORS[generator](seed)
    record: dict[str, Any] = {"generator": generator, "seed": seed, "table": governed.describe()}
    rng = random.Random(f"examine-{generator}-{seed}")
    schedules: dict[str, OracleSchedule | None] = {}
    theirs: dict[str, Any] = {}
    for variant, table in (("plain", governed.plain()), ("governed", governed)):
        verdict, ours, why = _oracle_verdict(table)
        schedules[variant] = ours
        entry: dict[str, Any] = {"oracle": verdict, "oracle_note": why}
        started = time.perf_counter()
        try:
            theirs[variant] = sut.breakpoint_schedule(
                table.securities(),
                as_of=table.as_of,
                collective_conversion=table.collective_conversion(),
            )
            entry["ovf"] = "schedule"
        except sut.BreakpointError as exc:
            theirs[variant] = None
            entry["ovf"] = classify_refusal(exc)
            entry["ovf_note"] = str(exc)[:300]
        entry["ovf_seconds"] = time.perf_counter() - started
        if ours is not None:
            entry["replay_gap"], entry["replay_probes"] = replay_gap(table, ours)
            if theirs[variant] is not None:
                entry["compare"] = compare_schedules(ours, theirs[variant])
                entry["ovf_linearity"] = theirs[variant].max_linearity_error
        # Search 5: what a caller of opm_allocate gets on the default path.
        spot = pick_spot(ours, rng) if ours is not None else 1.0
        if ours is None and theirs[variant] is not None:
            edges = [b.value for b in theirs[variant].breakpoints[1:]] or [1.0]
            spot = math.sqrt(edges[0] * edges[-1])
        entry["spot"] = spot
        try:
            _allocate(sut, table, spot, (0.6, 3.0, 0.04, 0.0))
            entry["allocate"] = "applies"
        except Exception as exc:  # classified, never swallowed silently
            entry["allocate"] = classify_refusal(exc)
            entry["allocate_note"] = str(exc)[:300]
        record[variant] = entry

    plain_ours, plain_theirs = schedules["plain"], theirs["plain"]
    if (
        grid
        and plain_ours is not None
        and plain_theirs is not None
        and record["plain"]["allocate"] == "applies"
    ):
        record["allocation"] = _allocation_grid(
            sut, governed.plain(), plain_ours, plain_theirs, rng
        )
        record["limit"] = _deterministic_limit(sut, governed.plain(), plain_ours, plain_theirs, rng)
    gov_ours, gov_theirs = schedules["governed"], theirs["governed"]
    if gov_ours is not None and gov_ours.steps and gov_theirs is not None:
        record["gap"] = _error_size(sut, governed, gov_ours, gov_theirs, record["governed"]["spot"])
    return record


def _allocation_grid(
    sut: SimpleNamespace, table: Table, ours: OracleSchedule, theirs: Any, rng: random.Random
) -> dict[str, Any]:
    """Search 2 and 3: call spreads against quadrature, and conservation, on one table."""
    spot = pick_spot(ours, rng)
    cells: dict[str, dict[str, float]] = {}
    for sigma, years, (rate, dividend) in itertools.product(SIGMAS, TIMES, RATES):
        result = _allocate(sut, table, spot, (sigma, years, rate, dividend), schedule=theirs)
        call_spread = {cv.security_id: cv.value for cv in result.class_values}
        integral = lognormal_value(
            ours, spot=spot, volatility=sigma, time=years, rate=rate, dividend_yield=dividend
        )
        forward = spot * math.exp(-dividend * years)
        gaps = {k: abs(call_spread[k] - integral.values[k]) for k in call_spread}
        relative = [
            gaps[k] / integral.values[k] for k in gaps if integral.values[k] > 1e-6 * forward
        ]
        key = f"{sigma}|{years}|{rate}|{dividend}"
        cells[key] = {
            "abs": max(gaps.values()) / forward,
            "class_rel": max(relative, default=0.0),
            "conservation_reported": result.conservation_error / forward,
            "conservation_measured": abs(math.fsum(call_spread.values()) - forward) / forward,
            "integral_mean_error": integral.mean_error,
            "integral_mass_error": integral.mass_error,
            "total_volatility": sigma * math.sqrt(years),
        }
    return {"spot": spot, "cells": cells}


def _deterministic_limit(
    sut: SimpleNamespace, table: Table, ours: OracleSchedule, theirs: Any, rng: random.Random
) -> dict[str, Any]:
    """Search 4: with r = q = 0, T = 1, the OPM value against the engine payout at S."""
    knots = [float(k) for k in ours.knots[1:]]
    lows = [0.0, *knots]
    tops = [*knots, 2 * knots[-1] if knots else 1.0]
    j = rng.randrange(len(lows))
    hi = tops[j]
    off = lows[j] + (hi - lows[j]) * rng.uniform(0.3, 0.7)
    spots = {"off": off}
    if knots:
        on = rng.choice(knots)
        if not any(float(c) == on for c, _ in ours.steps):
            spots["on"] = on
    out: dict[str, Any] = {}
    for label, spot in spots.items():
        engine = engine_payout(table, spot)
        assert engine is not None
        exact = ours.payout(Q(spot))
        kink = Q(spot) in set(ours.knots)
        before = ours.slopes[ours.tranche(Q(spot)) - 1] if kink else None
        after = ours.weights(Q(spot))
        series = []
        for sigma in LIMIT_SIGMAS:
            result = _allocate(sut, table, spot, (sigma, 1.0, 0.0, 0.0), schedule=theirs)
            value = {cv.security_id: cv.value for cv in result.class_values}
            vs_engine = max(abs(value[k] - engine[k]) for k in engine) / spot
            vs_exact = (
                max(abs(value[k] - float(e)) for k, e in zip(ours.ids, exact, strict=True)) / spot
            )
            predicted = 0.0
            if before is not None:
                kink_option = spot * math.erf(sigma / (2 * math.sqrt(2.0)))
                predicted = (
                    max(abs(float(a - b)) for a, b in zip(after, before, strict=True))
                    * kink_option
                    / spot
                )
            series.append(
                {
                    "sigma": sigma,
                    "vs_engine": vs_engine,
                    "vs_exact": vs_exact,
                    "predicted": predicted,
                }
            )
        distance = min((abs(math.log(spot / k)) for k in knots), default=math.inf)
        out[label] = {"spot": spot, "log_distance": distance, "series": series}
    return out


def _error_size(
    sut: SimpleNamespace, table: Table, ours: OracleSchedule, theirs: Any, spot: float
) -> dict[str, Any]:
    """Search 6: on a stepped table, the unchecked construction and the vote-blind standard
    against the integral of the true governed payoff."""
    out: dict[str, Any] = {"spot": spot, "markets": []}
    for sigma, years, rate in MARKETS:
        truth = lognormal_value(ours, spot=spot, volatility=sigma, time=years, rate=rate)
        with checks_disabled(sut):
            unchecked = _allocate(sut, table, spot, (sigma, years, rate, 0.0), schedule=theirs)
        unchecked_v = {cv.security_id: cv.value for cv in unchecked.class_values}
        try:
            blind = _allocate(sut, table.plain(), spot, (sigma, years, rate, 0.0))
            blind_v: dict[str, float] | None = {
                cv.security_id: cv.value for cv in blind.class_values
            }
        except Exception:
            blind_v = None
        digital = {
            sid: -math.fsum(
                float(jumps[c])
                * digital_value(
                    float(level),
                    spot=spot,
                    volatility=sigma,
                    time=years,
                    rate=rate,
                    dividend_yield=0.0,
                )
                for level, jumps in ours.steps
            )
            for c, sid in enumerate(ours.ids)
        }
        market: dict[str, Any] = {"market": [sigma, years, rate], "classes": {}}
        for sid in ours.ids:
            market["classes"][sid] = {
                "truth": truth.values[sid],
                "unchecked": unchecked_v[sid],
                "blind": None if blind_v is None else blind_v[sid],
                "identity_residual": unchecked_v[sid] - truth.values[sid] - digital[sid],
            }
        market["unchecked_total_error"] = abs(math.fsum(unchecked_v.values()) - spot) / spot
        market["truth_mean_error"] = truth.mean_error
        out["markets"].append(market)
    return out


# ---------------------------------------------------------------------------
# Aggregation and reporting
# ---------------------------------------------------------------------------


def _quantiles(values: Sequence[float]) -> str:
    if not values:
        return "none"
    ordered = sorted(values)

    def q(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(p * len(ordered)))]

    return (
        f"n={len(ordered)} median {statistics.median(ordered):.3g}, p90 {q(0.9):.3g}, "
        f"p99 {q(0.99):.3g}, max {ordered[-1]:.3g}"
    )


def _wilson(k: int, n: int) -> str:
    if not n:
        return "n/a"
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{100 * p:.1f}% (95% Wilson {100 * (centre - half):.1f}-{100 * (centre + half):.1f}%)"


def summarize(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    by_gen: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_gen.setdefault(r["generator"], []).append(r)
    for gen, rs in sorted(by_gen.items()):
        seeds = sorted(r["seed"] for r in rs)
        lines.append(f"## generator {gen}: {len(rs)} tables, seeds {seeds[0]}-{seeds[-1]}")
        errors = [r for r in rs if "crash" in r]
        if errors:
            lines.append(f"harness crashes: {[(r['seed'], r['crash']) for r in errors][:10]}")
        rs = [r for r in rs if "crash" not in r]
        for variant in ("plain", "governed"):
            entries = [r[variant] for r in rs]
            lines.append(f"### {variant}")
            lines.append(f"oracle verdicts: {dict(Counter(e['oracle'] for e in entries))}")
            lines.append(f"ovf schedule: {dict(Counter(e['ovf'] for e in entries))}")
            lines.append(
                f"opm_allocate default path: {dict(Counter(e['allocate'] for e in entries))}"
            )
            cross = Counter((e["oracle"], e["allocate"]) for e in entries)
            lines.append(f"oracle x allocate: {dict(cross)}")
            n = len(entries)
            applies = sum(1 for e in entries if e["allocate"] == "applies")
            lines.append(
                f"OPM applies: {applies}/{n} = {_wilson(applies, n)}; refused {n - applies}/{n} = {_wilson(n - applies, n)}"
            )
            comps = [e["compare"] for e in entries if "compare" in e]
            if comps:
                count_diff = sum(1 for c in comps if c["count_ours"] != c["count_theirs"])
                unmatched = sum(1 for c in comps if c["unmatched_ours"] or c["unmatched_theirs"])
                lines.append(
                    f"compared {len(comps)}: breakpoints ours {sum(c['count_ours'] for c in comps)} / "
                    f"ovf {sum(c['count_theirs'] for c in comps)}; count differs in {count_diff}; "
                    f"position unmatched in {unmatched}; exact float equality "
                    f"{sum(c['exact_positions'] for c in comps)}; largest matched position gap "
                    f"{max(c['position_gap'] for c in comps):.3g}; largest weight gap "
                    f"{max(c['weight_gap'] for c in comps):.3g}"
                )
                lines.append(
                    f"steps ours {sum(c['steps_ours'] for c in comps)} / ovf "
                    f"{sum(c['steps_theirs'] for c in comps)}; unmatched steps in "
                    f"{sum(1 for c in comps if c['unmatched_steps'])}; largest jump gap "
                    f"{max(c['jump_gap'] for c in comps):.3g}; monotone flag disagrees in "
                    f"{sum(1 for c in comps if c['monotone'][0] != c['monotone'][1])}; continuous "
                    f"flag disagrees in {sum(1 for c in comps if c['continuous'][0] != c['continuous'][1])}; "
                    f"negative weight ours/ovf {sum(c['negative_weight_ours'] for c in comps)}/"
                    f"{sum(c['negative_weight_theirs'] for c in comps)}"
                )
                bad = [
                    (r["seed"], r[variant]["compare"])
                    for r in rs
                    if "compare" in r[variant]
                    and (
                        r[variant]["compare"]["unmatched_ours"]
                        or r[variant]["compare"]["unmatched_theirs"]
                        or r[variant]["compare"]["unmatched_steps"]
                        or r[variant]["compare"]["weight_gap"] > 1e-9
                        or r[variant]["compare"]["jump_gap"] > 1e-6
                        or r[variant]["compare"]["monotone"][0]
                        != r[variant]["compare"]["monotone"][1]
                    )
                ]
                if bad:
                    lines.append(
                        f"DISAGREEMENTS ({len(bad)}): "
                        + "; ".join(f"seed {s}: {c}" for s, c in bad[:12])
                    )
            gaps = [e["replay_gap"] for e in entries if "replay_gap" in e]
            if gaps:
                lines.append(
                    f"oracle vs float engine: {len(gaps)} tables, {sum(e['replay_probes'] for e in entries if 'replay_probes' in e)} "
                    f"exits, largest gap {max(gaps):.3g}"
                )
            refusals = [
                (r["seed"], e["ovf"], e.get("ovf_note", "")[:160])
                for r in rs
                for e in (r[variant],)
                if e["ovf"] != "schedule"
            ]
            if refusals:
                lines.append(f"ovf schedule refusals ({len(refusals)}): {refusals[:6]}")
            oracle_errors = [
                (r["seed"], r[variant]["oracle_note"][:160])
                for r in rs
                if r[variant]["oracle"] == "oracle error"
            ]
            if oracle_errors:
                lines.append(f"oracle errors ({len(oracle_errors)}): {oracle_errors[:6]}")
        grids = [r["allocation"] for r in rs if "allocation" in r]
        if grids:
            lines.append(f"### search 2/3: {len(grids)} tables x {len(grids[0]['cells'])} markets")
            worst_abs = max(c["abs"] for g in grids for c in g["cells"].values())
            worst_rel = max(c["class_rel"] for g in grids for c in g["cells"].values())
            lines.append(
                f"call spread vs quadrature: worst |diff|/(S e^-qT) {worst_abs:.3g}; worst class-relative {worst_rel:.3g}"
            )
            by_v: dict[str, list[float]] = {}
            by_v_rel: dict[str, list[float]] = {}
            for g in grids:
                for c in g["cells"].values():
                    v = c["total_volatility"]
                    band = (
                        "<0.01"
                        if v < 0.01
                        else "<0.1"
                        if v < 0.1
                        else "<0.5"
                        if v < 0.5
                        else "<1"
                        if v < 1
                        else "<2"
                        if v < 2
                        else "<4"
                        if v < 4
                        else ">=4"
                    )
                    by_v.setdefault(band, []).append(c["abs"])
                    by_v_rel.setdefault(band, []).append(c["class_rel"])
            for band in ("<0.01", "<0.1", "<0.5", "<1", "<2", "<4", ">=4"):
                if band in by_v:
                    lines.append(
                        f"  sigma*sqrt(T) {band}: abs max {max(by_v[band]):.3g}; class-rel max {max(by_v_rel[band]):.3g}; cells {len(by_v[band])}"
                    )
            lines.append(
                "conservation: worst reported "
                f"{max(c['conservation_reported'] for g in grids for c in g['cells'].values()):.3g}, worst measured "
                f"{max(c['conservation_measured'] for g in grids for c in g['cells'].values()):.3g}; quadrature "
                f"mean error {max(c['integral_mean_error'] for g in grids for c in g['cells'].values()):.3g}, mass error "
                f"{max(c['integral_mass_error'] for g in grids for c in g['cells'].values()):.3g}"
            )
            worst_cell = max(
                (
                    (r["seed"], k, c)
                    for r in rs
                    if "allocation" in r
                    for k, c in r["allocation"]["cells"].items()
                ),
                key=lambda t: t[2]["abs"],
            )
            lines.append(
                f"  worst cell: seed {worst_cell[0]} market {worst_cell[1]} {worst_cell[2]}"
            )
        limits = [r["limit"] for r in rs if "limit" in r]
        if limits:
            lines.append(f"### search 4: {len(limits)} tables")
            for label in ("off", "on"):
                rows = [lim[label] for lim in limits if label in lim]
                for k, sigma in enumerate(LIMIT_SIGMAS):
                    vs_engine = [row["series"][k]["vs_engine"] for row in rows]
                    vs_exact = [row["series"][k]["vs_exact"] for row in rows]
                    ratio = [
                        row["series"][k]["vs_exact"] / row["series"][k]["predicted"]
                        for row in rows
                        if row["series"][k]["predicted"] > 0
                    ]
                    lines.append(
                        f"  {label} sigma {sigma:.0e}: vs engine {_quantiles(vs_engine)}; vs exact {_quantiles(vs_exact)}"
                        + (
                            f"; vs exact / predicted kink option {_quantiles(ratio)}"
                            if ratio
                            else ""
                        )
                    )
        gap_rows = [r for r in rs if "gap" in r]
        if gap_rows:
            lines.append(f"### search 6: {len(gap_rows)} stepped tables")
            for m, market in enumerate(MARKETS):
                (
                    unchecked_abs,
                    unchecked_pct,
                    unchecked_class,
                    blind_abs,
                    blind_pct,
                    blind_class,
                    residual,
                ) = [], [], [], [], [], [], []
                total_err = []
                for r in gap_rows:
                    mk = r["gap"]["markets"][m]
                    spot = r["gap"]["spot"]
                    classes = mk["classes"]
                    u = max(abs(c["unchecked"] - c["truth"]) for c in classes.values())
                    unchecked_abs.append(u)
                    unchecked_pct.append(100 * u / spot)
                    unchecked_class.append(
                        max(
                            (
                                100 * abs(c["unchecked"] - c["truth"]) / c["truth"]
                                for c in classes.values()
                                if c["truth"] >= 0.01 * spot
                            ),
                            default=0.0,
                        )
                    )
                    if all(c["blind"] is not None for c in classes.values()):
                        b = max(abs(c["blind"] - c["truth"]) for c in classes.values())
                        blind_abs.append(b)
                        blind_pct.append(100 * b / spot)
                        blind_class.append(
                            max(
                                (
                                    100 * abs(c["blind"] - c["truth"]) / c["truth"]
                                    for c in classes.values()
                                    if c["truth"] >= 0.01 * spot
                                ),
                                default=0.0,
                            )
                        )
                    residual.append(
                        max(abs(c["identity_residual"]) for c in classes.values()) / spot
                    )
                    total_err.append(mk["unchecked_total_error"])
                lines.append(f"  market {market}:")
                lines.append(f"    unchecked, largest class gap $: {_quantiles(unchecked_abs)}")
                lines.append(
                    f"    unchecked, largest class gap % of S: {_quantiles(unchecked_pct)}"
                )
                lines.append(
                    f"    unchecked, largest gap % of class value (classes >= 1% of S): {_quantiles(unchecked_class)}"
                )
                lines.append(f"    vote-blind, largest class gap $: {_quantiles(blind_abs)}")
                lines.append(f"    vote-blind, largest class gap % of S: {_quantiles(blind_pct)}")
                lines.append(
                    f"    vote-blind, largest gap % of class value: {_quantiles(blind_class)}"
                )
                lines.append(
                    f"    identity residual / S: {_quantiles(residual)}; unchecked total vs S: max {max(total_err):.3g}"
                )
    return "\n".join(lines)


def _safe_examine(job: tuple[str, int]) -> dict[str, Any]:
    generator, seed = job
    try:
        return examine(generator, seed)
    except Exception as exc:  # recorded with its seed so it can be replayed
        return {"generator": generator, "seed": seed, "crash": f"{type(exc).__name__}: {exc}"[:400]}


def run(generators: Sequence[str], start: int, count: int, workers: int) -> list[dict[str, Any]]:
    jobs = [(g, s) for g in generators for s in range(start, start + count)]
    if workers <= 1:
        return [_safe_examine(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_safe_examine, jobs, chunksize=4))


SCALES = (1, 3, 10, 30, 100, 300, 1000)


def scale_probe(job: tuple[int, int]) -> dict[str, Any]:
    """One venture table with every share count and principal multiplied by ``factor``.

    Prices are unchanged, so every breakpoint scales by the factor and the table is the same
    table in larger units. Records whether the default path (``breakpoint_schedule`` with its
    default ``atol``, then ``opm_allocate``) still accepts it, and the largest breakpoint.
    """
    seed, factor = job
    base = venture_table(seed).plain()
    table = replace(
        base,
        positions=tuple(
            replace(p, shares=p.shares * factor, principal=p.principal * factor)
            for p in base.positions
        ),
    )
    sut = _system_under_test()
    ours = oracle_schedule(table)
    out: dict[str, Any] = {"seed": seed, "factor": factor, "top": float(ours.knots[-1])}
    try:
        schedule = sut.breakpoint_schedule(table.securities(), as_of=table.as_of)
        out["schedule"] = "schedule"
        out["linearity"] = schedule.max_linearity_error
    except sut.BreakpointError as exc:
        out["schedule"] = classify_refusal(exc)
        out["note"] = str(exc)[:200]
    spot = pick_spot(ours, random.Random(f"scale-{seed}"))
    try:
        _allocate(sut, table, spot, (0.6, 3.0, 0.04, 0.0))
        out["allocate"] = "applies"
    except Exception as exc:
        out["allocate"] = classify_refusal(exc)
    return out


EXTREME_SIGMAS = (3.0, 5.0, 8.0, 12.0, 20.0)
EXTREME_TIMES = (10.0, 30.0)


def extreme_probe(job: tuple[str, int]) -> dict[str, Any]:
    """Search 2 beyond its grid: total volatility from 9.5 to 110, on one table without its
    term, at a 4% rate."""
    generator, seed = job
    sut = _system_under_test()
    table = GENERATORS[generator](seed).plain()
    ours = oracle_schedule(table)
    theirs = sut.breakpoint_schedule(table.securities(), as_of=table.as_of)
    spot = pick_spot(ours, random.Random(f"extreme-{generator}-{seed}"))
    cells = []
    for sigma, years in itertools.product(EXTREME_SIGMAS, EXTREME_TIMES):
        result = _allocate(sut, table, spot, (sigma, years, 0.04, 0.0), schedule=theirs)
        values = {cv.security_id: cv.value for cv in result.class_values}
        integral = lognormal_value(ours, spot=spot, volatility=sigma, time=years, rate=0.04)
        cells.append(
            {
                "total_volatility": sigma * math.sqrt(years),
                "abs": max(abs(values[k] - integral.values[k]) for k in values) / spot,
                "class_rel": max(
                    (
                        abs(values[k] - integral.values[k]) / integral.values[k]
                        for k in values
                        if integral.values[k] > 1e-6 * spot
                    ),
                    default=0.0,
                ),
                "quadrature_mean_error": integral.mean_error,
            }
        )
    return {"generator": generator, "seed": seed, "cells": cells}


def summarize_extreme(rows: list[dict[str, Any]]) -> str:
    crashed = [r for r in rows if "crash" in r]
    rows = [r for r in rows if "crash" not in r]
    lines = [
        f"## search 2 beyond the grid: {len(rows)} tables x {len(EXTREME_SIGMAS) * len(EXTREME_TIMES)} markets"
    ]
    by_v: dict[float, list[dict[str, float]]] = {}
    for r in rows:
        for c in r["cells"]:
            by_v.setdefault(round(c["total_volatility"], 1), []).append(c)
    for v in sorted(by_v):
        cells = by_v[v]
        lines.append(
            f"  sigma*sqrt(T) {v}: abs max {max(c['abs'] for c in cells):.3g}; class-rel max "
            f"{max(c['class_rel'] for c in cells):.3g}; quadrature mean error max "
            f"{max(c['quadrature_mean_error'] for c in cells):.3g}"
        )
    if crashed:
        lines.append(f"  crashes: {crashed[:6]}")
    return "\n".join(lines)


def blind_spot_probe(job: tuple[str, int]) -> dict[str, Any]:
    """Kinks found by probing the equilibrium payoff alone, against the full-vector finder.

    Measures the failure the first version of this oracle had (``ExactGame.extended``): the
    same splitting and the same five probes per interval, applied to the payoff only.
    """
    generator, seed = job
    table = GENERATORS[generator](seed).plain()
    hi = 2 * upper_bound(table) + 1
    game = ExactGame(table)
    full = set(continuous_kinks(game.extended, Q(0), hi, seed=seed, leading=len(table.ids)))
    alone = set(continuous_kinks(game.payoff, Q(0), hi, seed=seed))
    return {
        "generator": generator,
        "seed": seed,
        "full": len(full),
        "missed": len(full - alone),
        "extra": len(alone - full),
    }


def summarize_blind_spot(rows: list[dict[str, Any]]) -> str:
    lines = ["## blind spot of probing the payoff alone"]
    for gen in sorted({r["generator"] for r in rows}):
        at = [r for r in rows if r["generator"] == gen and "crash" not in r]
        crashed = [r["seed"] for r in rows if r["generator"] == gen and "crash" in r]
        missing = [r for r in at if r["missed"]]
        lines.append(
            f"  {gen}: {len(at)} tables, {sum(r['full'] for r in at)} kinks; payoff-only probing "
            f"missed {sum(r['missed'] for r in at)} kinks in {len(missing)} tables "
            f"(seeds {[r['seed'] for r in missing][:12]}); spurious {sum(r['extra'] for r in at)}"
            + (f"; oracle failures {crashed}" if crashed else "")
        )
    return "\n".join(lines)


def _guarded(fn: Callable[[Any], dict[str, Any]], job: Any) -> dict[str, Any]:
    try:
        return fn(job)
    except Exception as exc:  # recorded with its job so it can be replayed
        return {"job": job, "crash": f"{type(exc).__name__}: {exc}"[:300]}


def summarize_scale(rows: list[dict[str, Any]]) -> str:
    crashed = [r for r in rows if "crash" in r]
    rows = [r for r in rows if "crash" not in r]
    lines = [f"## scale search: {len({r['seed'] for r in rows})} venture tables x {SCALES}"]
    for factor in SCALES:
        at = [r for r in rows if r["factor"] == factor]
        refused = [r for r in at if r["allocate"] != "applies"]
        tops = sorted(r["top"] for r in at)
        lines.append(
            f"  x{factor}: largest breakpoint {tops[0]:.3g}-{tops[-1]:.3g}; default path refused "
            f"{len(refused)}/{len(at)} {dict(Counter(r['allocate'] for r in refused))}"
        )
    decades: dict[int, list[bool]] = {}
    for r in rows:
        decades.setdefault(math.floor(math.log10(r["top"])), []).append(r["allocate"] != "applies")
    for d in sorted(decades):
        flags = decades[d]
        lines.append(
            f"  largest breakpoint in [1e{d}, 1e{d + 1}): refused {sum(flags)}/{len(flags)}"
        )
    accepted = [r["top"] for r in rows if r["allocate"] == "applies"]
    refused_tops = [r["top"] for r in rows if r["allocate"] != "applies"]
    if refused_tops:
        lines.append(
            f"  smallest largest-breakpoint refused {min(refused_tops):.4g}; largest accepted "
            f"{max(accepted, default=0.0):.4g}"
        )
    worst = max((r.get("linearity", 0.0) for r in rows if r["factor"] == 1), default=0.0)
    lines.append(f"  largest replay error at x1: {worst:.3g}")
    if crashed:
        lines.append(f"  crashes: {crashed[:6]}")
    return "\n".join(lines)


def oracle_import_violations(path: Path | None = None) -> list[str]:
    """Imports of the modules under test anywhere but ``_system_under_test``."""
    source = (path or Path(__file__)).read_text()
    tree = ast.parse(source)
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_system_under_test":
            allowed |= {id(n) for n in ast.walk(node)}
    found = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        forbidden = [
            n
            for n in names
            if n.startswith(MODULES_UNDER_TEST)
            or n.startswith(
                ("tests.test_governance", "tests.opm_breakpoint_fixtures", "tests.test_opm_")
            )
        ]
        if forbidden and id(node) not in allowed:
            found.append(f"line {node.lineno}: {forbidden}")
    return found


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tables", type=int, default=1000, help="tables per generator")
    parser.add_argument("--start", type=int, default=0, help="first seed")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--generators", default="adversarial,venture")
    parser.add_argument("--json", type=Path, default=None, help="write every record here")
    parser.add_argument("--scale", type=int, default=0, help="venture tables for the scale search")
    parser.add_argument("--blind-spot", type=int, default=0, help="tables per generator")
    parser.add_argument("--extreme", type=int, default=0, help="tables per generator")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    print(f"ovf {ovf.__version__}; numpy {np.__version__}; python {sys.version.split()[0]}")
    if args.scale:
        jobs = [(seed, f) for seed in range(args.start, args.start + args.scale) for f in SCALES]
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            rows = pool.map(functools.partial(_guarded, scale_probe), jobs, chunksize=4)
            print(summarize_scale(list(rows)), flush=True)
    if args.blind_spot:
        gens = args.generators.split(",")
        jobs2 = [(g, s) for g in gens for s in range(args.start, args.start + args.blind_spot)]
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            rows = pool.map(functools.partial(_guarded, blind_spot_probe), jobs2, chunksize=4)
            print(summarize_blind_spot(list(rows)), flush=True)
    if args.extreme:
        gens = args.generators.split(",")
        jobs3 = [(g, s) for g in gens for s in range(args.start, args.start + args.extreme)]
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            rows = pool.map(functools.partial(_guarded, extreme_probe), jobs3, chunksize=2)
            print(summarize_extreme(list(rows)), flush=True)
    records = run(args.generators.split(","), args.start, args.tables, args.workers)
    if records:
        print(summarize(records))
    print(f"elapsed {time.perf_counter() - started:.1f}s on {args.workers} worker(s)")
    if args.json is not None:
        args.json.write_text(json.dumps(records, default=str))


if __name__ == "__main__":
    main()
