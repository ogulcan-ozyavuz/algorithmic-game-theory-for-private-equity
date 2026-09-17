"""Certified XIRR: every real root of a dated cash-flow series, or a proof there is none.

For netted per-date amounts ``a_0, ..., a_m`` at strictly increasing dates, with
``t_i = year_fraction(t0, d_i)`` (``t_0 = 0``) and ``delta = ln(1 + r)``, the NPV is the
exponential sum

    f(delta) = sum_i a_i * exp(-delta * t_i),        r in (-1, inf)  <=>  delta in R.

An IRR is a real root of ``f``. This module never picks a root: it finds all of them,
proves the list complete, or says it cannot.

Root policy
-----------
Let ``V`` be the number of sign changes of ``a_0, ..., a_m`` (dates ascending).

*Descartes' rule of signs for exponential sums.* The number of real roots of ``f``,
counted with multiplicity, is at most ``V`` and has the parity of ``V``. Source:
G. J. O. Jameson, "Counting zeros of generalised polynomials: Descartes' rule of signs
and Laguerre's extensions", *Mathematical Gazette* 90 (2006), 223-234: Theorem 3.1 (the
bound, stated for ``sum a_i x**lambda_i`` with real exponents; substitute
``x = exp(-delta)``), Proposition 3.6 (the parity), and Lemma 2.4; Pólya and Szegő
(Part V, ch. 1) as cited by Jameson. The proof is the same construction this module
computes with, so it is restated here:

- Pick ``tau`` strictly between ``t_j`` and ``t_{j+1}`` where ``a_j, a_{j+1}`` change
  sign. ``g(delta) = exp(delta * tau) * f(delta)`` has the roots of ``f`` with the same
  multiplicities, and ``g'(delta) = exp(delta * tau) * f1(delta)`` with
  ``f1(delta) = sum_i a_i * (tau - t_i) * exp(-delta * t_i)``.
- ``tau - t_i`` is positive for ``i <= j`` and negative for ``i > j``, so the
  coefficients of ``f1`` have exactly ``V - 1`` sign changes.
- By Rolle, between two roots of ``g`` lies a root of ``g'``, so
  ``Z(f) <= Z(f1) + 1``; with ``Z = 0`` when ``V = 0`` (all terms of one sign) this gives
  ``Z(f) <= V`` by induction.
- As ``delta -> +inf`` the ``t_0`` term dominates and ``f`` has the sign of ``a_0``; as
  ``delta -> -inf`` the ``t_m`` term dominates and ``f`` has the sign of ``a_m``. ``f``
  changes sign an odd number of times iff those differ, iff ``V`` is odd.

Hence ``V == 0``: no root (``"none"``, complete). ``V == 1``: exactly one root, simple
(``"unique"``, complete). ``V >= 2``: the rule bounds the count but does not give it.

*Rolle isolation.* For ``V >= 2`` the construction above is applied repeatedly:
``f = f_0, f_1, ..., f_V`` where ``f_{k+1}`` is built from ``f_k`` as ``f1`` from ``f``
and has one sign change fewer; ``f_V`` has none and so no root. Going back up, the roots
of ``f_{k+1}`` are all the critical points of ``g_k = exp(delta * tau_k) f_k``; between
consecutive critical points ``g_k`` is strictly monotone, so each such piece holds at most
one root of ``f_k``, and holds one exactly when the signs of ``f_k`` at its ends differ.
Every piece is searched inside a rigorous root bound (below), so every real root of every
level is found, and the root list of ``f`` is complete by construction.

*Root bound (term dominance).* See ``_dominance_bounds``: beyond ``delta_hi`` the block of
leading same-sign terms is at least twice the sum of all other terms in absolute value,
below ``delta_lo`` the block of trailing same-sign terms is; no root lies outside
``[delta_lo, delta_hi]``. It is reported as ``log_root_bound`` and, when representable,
as ``root_bound`` in rates.

*Refinement and verification.* Each root is refined with Brent's method on a bracket
whose ends have opposite signs, and verified on the scaled axis:
``|NPV(root)| <= tolerance * max(sum|a_i|, sum|a_i| (1 + r)**-t_i)`` with
``tolerance = 1e-10``; the ratio is reported as ``relative_residual``, which is finite even
when the NPV at ``t0`` of a deeply negative root exceeds the float range. The second sum is the gross discounted magnitude at the root (the
backward-error scale); it exceeds ``sum|a_i|`` only at negative rates, where compounded
terms of a near-total loss cancel and rounding alone would fail an undiscounted scale. A
failed verification makes the status ``"undetermined"``.

*Tangents and trust.* A sign is used only where ``|f|`` exceeds both the tolerance (on
the same scale) and an a-priori estimate of its rounding error. A critical point where
``|f|`` is within that threshold and ``f`` has the same sign on both sides is a *tangent* root: listed with
``kind="tangent"``, status ``"undetermined"``, ``complete=False``, because floating point
cannot tell a double root from a near miss or from two roots a hair apart. The same
situation in a derivative level ``f_k``, ``k >= 1``, also sets ``complete=False``
(conservative: two unseen critical points could hide a pair of roots).

Otherwise the status follows from the proven count: 0 roots ``"none"``, 1 ``"unique"``,
2 or more ``"multiple"`` (all listed, ``irr=None``).

*Scaled evaluation.* ``f`` is evaluated as ``exp(M) * sum_i s_i exp(L_i - M)`` with
``L_i = ln|a_i| - delta t_i`` and ``M = max L_i``; every exponent is ``<= 0``, so no
``delta`` of any size overflows. Brent's method runs on the scaled sum, which has the
roots and signs of ``f``.

Why Excel ``XIRR`` differs
--------------------------
Per Microsoft's documentation, Excel's ``XIRR`` iterates from a ``guess`` (default 10%)
until the result is accurate within 0.000001 percent, and returns ``#NUM!`` if it has not
converged after 100 tries. It reports one number: with two or more roots, whichever the
iteration reaches from the guess, so the answer depends on an input that has nothing to
do with the flows; with no root, or a missed one, an error rather than a proof. Here the
answer depends on the flows and the day count only, a series with several roots returns
all of them with ``irr=None``, and ``"none"`` is a proof, not a failure to converge. On a
series with one root both compute the same number (the Microsoft example is a test).

Representability: a root with ``1 + r`` below float resolution is reported as
``rate == -1.0`` with ``rate_clamped=True`` and its exact ``log_rate`` (check it with
``npv_at_log_rate``). A root whose rate exceeds the float range (``delta > ln(max
float)``, an annual rate above ~1.8e308) is refused with ``ValueError``; that is the only
representability refusal. A root whose NPV in currency units at ``t0`` overflows is still
reported, with ``npv_residual=None``.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict
from scipy.optimize import brentq  # type: ignore[import-untyped]

from ovf.core.types import FinancialBaseModel
from ovf.pme.daycount import DayCountConvention, check_convention, describe, year_fraction
from ovf.pme.flows import (
    ENGINE_VERSION,
    DatedAmount,
    PlainDate,
    ResolvedCashFlows,
    canonical_hash,
    net_by_date,
)

IrrStatus = Literal["unique", "multiple", "none", "undetermined"]
RootKind = Literal["crossing", "tangent"]

TOLERANCE = 1e-10

_EPS = sys.float_info.epsilon
_LN2 = math.log(2.0)
_MAX_LOG = math.log(sys.float_info.max)  # exp() of anything larger overflows
_BRENT_XTOL = 1e-14
_BRENT_RTOL = 4 * _EPS
_BRENT_MAXITER = 500

FloatArray = NDArray[np.float64]


class IrrRoot(FinancialBaseModel):
    """One real root of the NPV: an annual effective rate and how it was verified.

    ``rate`` is ``exp(log_rate) - 1``. When ``1 + rate`` is below float resolution it reads
    ``-1.0`` and ``rate_clamped`` is ``True``; ``log_rate`` still carries the root and
    ``npv_at_log_rate`` evaluates the NPV there. ``relative_residual`` is ``|NPV(root)|``
    divided by the backward-error scale ``max(sum|a_i|, sum|a_i| (1 + r)^-t_i)``, computed
    on the scaled axis: always finite, at most 1, and the root is verified when it is
    ``<= TOLERANCE``. ``npv_residual`` is the NPV at ``t0`` in currency units, or ``None``
    when that number is outside the float range (a deeply negative root compounds later
    amounts past 1e308 at ``t0``; the relative residual is unaffected).
    """

    model_config = ConfigDict(frozen=True)

    rate: float
    log_rate: float
    npv_residual: float | None
    relative_residual: float
    rate_clamped: bool
    kind: RootKind


class IrrResult(FinancialBaseModel):
    """Every root found, whether the list is proven complete, and why.

    ``irr`` is set only when ``status == "unique"``. ``complete`` is ``True`` when the
    root count is proven (no tangent or near-tangent anywhere in the isolation); it can be
    ``True`` with status ``"undetermined"`` only if a root failed its residual check.
    ``log_root_bound`` is the certified bound ``[delta_lo, delta_hi]`` on ``ln(1 + r)``
    (``None`` only when ``V == 0``: there is nothing to search); ``root_bound`` is the same
    bound as rates, ``None`` when ``V == 0`` or when its upper end overflows as a rate.
    """

    model_config = ConfigDict(frozen=True)

    status: IrrStatus
    irr: float | None
    roots: tuple[IrrRoot, ...]
    sign_changes: int
    complete: bool
    proof: str
    root_bound: tuple[float, float] | None
    log_root_bound: tuple[float, float] | None
    day_count: DayCountConvention
    t0: PlainDate
    amounts: tuple[DatedAmount, ...]
    tolerance: float
    assumptions: list[str]
    input_hash: str
    engine_version: str = ENGINE_VERSION


# --- Exponential sums --------------------------------------------------------------


@dataclass(frozen=True)
class _Probe:
    """``f(delta) = exp(log_scale) * value``; ``magnitude`` is ``sum |terms|`` on that scale."""

    delta: float
    value: float
    log_scale: float
    magnitude: float
    noise: float

    @property
    def sign(self) -> int:
        return (self.value > 0) - (self.value < 0)


def _sign_changes(signs: FloatArray) -> int:
    return int(np.count_nonzero(signs[1:] != signs[:-1]))


def _logsumexp(exponents: FloatArray) -> float:
    top = float(exponents.max())
    return top + math.log(math.fsum(np.exp(exponents - top).tolist()))


class _ExpSum:
    """``sum_i s_i exp(ln|c_i| - delta t_i)``, held in log space, evaluated in scaled form.

    No coefficient is ever formed as a float. Level 0 takes ``ln|a_i|`` of each stated
    amount; each derivative level adds ``ln|tau - t_i|`` and flips the sign where
    ``tau < t_i``. Every level is normalised by subtracting its largest log, so no
    coefficient can become subnormal, zero or infinite, whatever the span of the amounts
    (a quotient such as ``1e-300 / 1e20`` is subnormal and keeps only a few bits).
    ``log_err`` bounds the absolute error carried by each ``ln|c_i|``, i.e. the relative
    error of that coefficient; it enters the noise estimate of every evaluation.
    """

    def __init__(
        self,
        level: int,
        signs: FloatArray,
        log_abs: FloatArray,
        log_err: FloatArray,
        times: FloatArray,
        log_unit: float = 0.0,
    ) -> None:
        if not (np.all(np.isfinite(log_abs)) and np.all(np.isfinite(log_err))):
            raise _DegenerateError(f"level {level}: a log coefficient is not finite")
        offset = float(log_abs.max())
        self.level = level
        self.signs = signs
        self.log_abs: FloatArray = log_abs - offset
        self.log_err: FloatArray = log_err + _EPS * np.abs(self.log_abs)
        # ln of the factor removed from this level (its normalisation plus any unit the
        # caller already took out), so exp(log_scale) * value is in the caller's units.
        self.log_offset = offset + log_unit
        self.times = times
        self.changes = _sign_changes(signs)

    def _exponents(self, delta: float) -> tuple[FloatArray, float]:
        exponents = self.log_abs - delta * self.times
        return exponents, float(exponents.max())

    def scaled(self, delta: float) -> float:
        """``f(delta) / exp(M(delta))``: continuous, same roots and signs as ``f``."""
        exponents, top = self._exponents(delta)
        return math.fsum((self.signs * np.exp(exponents - top)).tolist())

    def probe(self, delta: float) -> _Probe:
        exponents, top = self._exponents(delta)
        shifted = exponents - top
        weights = np.exp(shifted)  # in (0, 1]; a term below 2**-1074 of the largest is
        value = math.fsum((self.signs * weights).tolist())  # dropped, far below noise
        magnitude = math.fsum(weights.tolist())
        # A-priori error of the scaled sum. Term i carries a relative error bounded by the
        # absolute error of its exponent: the coefficient's log_err; t_i's own rounding and
        # the product delta * t_i (eps |delta t_i| each); the two subtractions (eps times
        # their results); exp itself (eps). A common error in M scales every term alike
        # and moves no sign. fsum rounds once more. Doubled to stay an overestimate.
        term_err = self.log_err + _EPS * (
            1.0 + 2.0 * np.abs(delta * self.times) + np.abs(exponents) + np.abs(shifted)
        )
        noise = 2.0 * float(np.sum(weights * term_err)) + _EPS * magnitude
        return _Probe(delta, value, top + self.log_offset, magnitude, noise)

    def derivative(self) -> _ExpSum:
        """``f_{k+1} = sum c_i (tau - t_i) exp(-delta t_i)`` in log space; ``V - 1`` changes."""
        j = int(np.flatnonzero(self.signs[1:] != self.signs[:-1])[0])
        tau = 0.5 * (float(self.times[j]) + float(self.times[j + 1]))
        if not self.times[j] < tau < self.times[j + 1]:
            raise _DegenerateError(
                f"level {self.level}: no float strictly between t_{j} and t_{j + 1}"
            )
        gaps = tau - self.times  # one rounding each: relative error <= eps / 2
        log_gaps = np.log(np.abs(gaps))
        log_abs = self.log_abs + log_gaps
        log_err = self.log_err + _EPS * (2.0 + 2.0 * np.abs(log_gaps) + np.abs(log_abs))
        return _ExpSum(self.level + 1, self.signs * np.sign(gaps), log_abs, log_err, self.times)


class _DegenerateError(Exception):
    """The isolation cannot proceed with trustworthy arithmetic."""


def _brent(func: Callable[[float], float], lo: float, hi: float) -> float:
    root, info = brentq(
        func,
        lo,
        hi,
        xtol=_BRENT_XTOL,
        rtol=_BRENT_RTOL,
        maxiter=_BRENT_MAXITER,
        full_output=True,
    )
    if not info.converged:  # pragma: no cover - brentq converges on any valid bracket
        raise _DegenerateError(f"Brent's method did not converge on [{lo!r}, {hi!r}]")
    return float(root)


def _crossover(
    dom_log: FloatArray,
    dom_t: FloatArray,
    rest_log: FloatArray,
    rest_t: FloatArray,
    gap: float,
) -> float:
    """The unique ``x`` with ``lse(dom_log - x dom_t) == lse(rest_log - x rest_t)``.

    Requires ``max(dom_t) + gap <= min(rest_t)``: the difference ``D(x)`` of the two
    log-sum-exps then has derivative ``mean_w(rest_t) - mean_w(dom_t) >= gap > 0`` (each
    term is minus a softmax-weighted mean of its times), so ``D`` is strictly increasing,
    ``D(x) >= D(0) + gap x`` for ``x >= 0`` and ``D(x) <= D(0) + gap x`` for ``x <= 0``,
    and the root lies between ``0`` and ``-D(0) / gap``.
    """

    def diff(x: float) -> float:
        return _logsumexp(dom_log - x * dom_t) - _logsumexp(rest_log - x * rest_t)

    start = diff(0.0)
    if start == 0.0:
        return 0.0
    lo, hi = sorted((0.0, -start / gap))
    widen = 1.0 + abs(start / gap)
    for _ in range(64):  # the bracket is exact in real arithmetic; widen only for rounding
        if diff(lo) <= 0.0 <= diff(hi):
            return _brent(diff, lo, hi)
        lo, hi = lo - widen, hi + widen
    raise _DegenerateError("the root bound crossover could not be bracketed")


def _dominance_bounds(f: _ExpSum) -> tuple[float, float]:
    """``[delta_lo, delta_hi]`` outside which ``f`` has no root (requires ``V >= 1``).

    Proof. Let ``0..j`` be the leading block of coefficients sharing the sign of ``c_0``
    (``c_{j+1}`` is the first of the other sign) and ``A(delta) = sum_{i<=j} |c_i|
    exp(-delta t_i)``, ``B(delta) = sum_{i>j} |c_i| exp(-delta t_i)``. Then
    ``|f - s_0 A| <= B``, so ``f`` has the sign of ``c_0`` wherever ``A > B``.
    ``d/d delta ln A = -mean_w(t_i, i <= j) >= -t_j`` and
    ``d/d delta ln B = -mean_w(t_i, i > j) <= -t_{j+1}``, so ``D = ln A - ln B`` is strictly
    increasing with slope ``>= g = t_{j+1} - t_j > 0``. With ``D(delta*) = 0``, every
    ``delta >= delta_hi = delta* + ln 2 / g`` has ``D >= ln 2``, i.e. ``A >= 2B`` and
    ``|f| >= A / 2 > 0``. Symmetrically, with the trailing block ``k..m`` (sign of
    ``c_m``) and ``g' = t_k - t_{k-1}``, every ``delta <= delta_lo`` has the trailing block
    at least twice the rest. No root lies outside ``[delta_lo, delta_hi]``, and ``f`` is
    bounded away from zero, by half its dominant block, at both ends.
    """
    changes = np.flatnonzero(f.signs[1:] != f.signs[:-1])
    j = int(changes[0])
    k = int(changes[-1]) + 1
    t, la = f.times, f.log_abs
    lead_gap = float(t[j + 1] - t[j])
    trail_gap = float(t[k] - t[k - 1])
    upper = _crossover(la[: j + 1], t[: j + 1], la[j + 1 :], t[j + 1 :], lead_gap)
    # The trailing block dominates as delta -> -inf; with u = -delta and times negated it
    # is the same crossover problem.
    lower = _crossover(la[k:], -t[k:], la[:k], -t[:k], trail_gap)
    return -(lower + _LN2 / trail_gap), upper + _LN2 / lead_gap


@dataclass
class _LevelRoots:
    crossings: list[float]
    tangents: list[float]
    issues: list[str]
    bound: tuple[float, float]
    pieces: int


def _isolate_level(
    f: _ExpSum, critical: list[float], near_zero: Callable[[_Probe], bool]
) -> _LevelRoots:
    """All real roots of ``f`` given all real roots of the next level (its critical points)."""
    lo, hi = _dominance_bounds(f)
    issues: list[str] = []
    ends = (f.probe(lo), f.probe(hi))
    expected = (int(f.signs[-1]), int(f.signs[0]))
    for probe, sign in zip(ends, expected, strict=True):
        if probe.sign != sign or abs(probe.value) <= probe.noise:
            issues.append(f"level {f.level}: the root bound check failed at delta={probe.delta!r}")
    interior = sorted({c for c in critical if lo < c < hi})
    probes = [ends[0], *(f.probe(c) for c in interior), ends[1]]
    soft = [0 < i < len(probes) - 1 and near_zero(p) for i, p in enumerate(probes)]
    anchors = [i for i, is_soft in enumerate(soft) if not is_soft]

    crossings: list[float] = []
    tangents: list[float] = []
    for a, b in zip(anchors, anchors[1:], strict=False):
        between = list(range(a + 1, b))
        left, right = probes[a], probes[b]
        if not between:
            if left.sign != right.sign:
                crossings.append(_brent(f.scaled, left.delta, right.delta))
            continue
        if len(between) == 1:
            # Two monotone pieces meet at a critical point where f is within tolerance of
            # zero. Opposite end signs: exactly one distinct root in the union, wherever
            # f(c) really lies. Equal end signs: 0, 1 (double) or 2 roots - undecidable.
            if left.sign != right.sign:
                crossings.append(_brent(f.scaled, left.delta, right.delta))
            else:
                tangents.append(probes[between[0]].delta)
            continue
        issues.append(
            f"level {f.level}: {len(between)} adjacent critical points within tolerance of "
            f"zero between delta={left.delta!r} and delta={right.delta!r}"
        )
        tangents.extend(probes[i].delta for i in between)
        span = [left, *(probes[i] for i in between), right]
        for p, q in zip(span, span[1:], strict=False):
            if p.sign * q.sign < 0:
                crossings.append(_brent(f.scaled, p.delta, q.delta))
    return _LevelRoots(crossings, tangents, issues, (lo, hi), len(probes) - 1)


# --- Public API --------------------------------------------------------------------


def _check_amounts(amounts: object) -> list[DatedAmount]:
    if isinstance(amounts, str | bytes) or not isinstance(amounts, Sequence):
        raise ValueError("amounts must be a sequence of DatedAmount")
    for item in amounts:
        if not isinstance(item, DatedAmount):
            raise ValueError(f"amounts must contain DatedAmount, got {type(item).__name__}")
    return list(amounts)


def _net(items: list[DatedAmount]) -> list[DatedAmount]:
    try:
        nets, _ = net_by_date([(a.date, a.amount) for a in items])
    except OverflowError as exc:
        raise ValueError("a same-date net of the amounts exceeds the float range") from exc
    return nets


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    try:
        number = float(value)
    except OverflowError as exc:
        text = repr(value)
        shown = text if len(text) <= 40 else f"{text[:20]}... ({len(text)} digits)"
        raise ValueError(f"{name} {shown} exceeds the float range") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _discounted_sum(nets: list[DatedAmount], exponents: list[float], what: str) -> float:
    """``sum a_i exp(e_i)`` in float, refusing only a result outside the float range.

    Where every term is representable, each is one product with a normal ``exp`` (or, when
    ``exp(e_i)`` alone would underflow or overflow, ``sign * exp(ln|a_i| + e_i)``) and the
    terms are summed with ``fsum``. Otherwise the sum is taken on a scaled axis,
    ``exp(M) * fsum(sign * exp(x_i - M))``, so terms that overflow individually but whose
    total is representable still give a number.
    """
    if not nets:
        return 0.0
    logs = [math.log(abs(a.amount)) + e for a, e in zip(nets, exponents, strict=True)]
    top = max(logs)
    if top < _MAX_LOG - 1.0:
        terms = [
            a.amount * math.exp(e) if -700.0 < e < 700.0 else math.copysign(math.exp(x), a.amount)
            for a, e, x in zip(nets, exponents, logs, strict=True)
        ]
        try:
            total = math.fsum(terms)
        except OverflowError:
            total = math.inf
        if math.isfinite(total):
            return total
    scaled = math.fsum(
        math.copysign(math.exp(x - top), a.amount) for a, x in zip(nets, logs, strict=True)
    )
    if scaled == 0.0:
        return 0.0
    log_total = top + math.log(abs(scaled))
    if log_total > _MAX_LOG:
        raise ValueError(f"{what} exceeds the float range")
    return math.copysign(math.exp(log_total), scaled)


def npv_at_log_rate(
    amounts: Sequence[DatedAmount],
    *,
    log_rate: float,
    day_count: DayCountConvention,
    t0: date,
) -> float:
    """``sum a_i exp(-log_rate * year_fraction(t0, d_i))``: the NPV at ``delta = ln(1 + r)``.

    Evaluates any real ``delta``, including a root whose ``rate`` is clamped to ``-1.0``
    (``IrrRoot.rate_clamped``), where ``npv`` cannot be called. Same-date legs are netted
    first; terms are formed in log space where a discount factor alone would underflow or
    overflow; only a result outside the float range is refused. At a deeply negative root
    the NPV at the first date compounds later amounts past 1e308: pass ``t0`` = the last
    date, where every factor is at most 1.
    """
    convention = check_convention(day_count)
    items = _check_amounts(amounts)
    delta = _finite("log_rate", log_rate)
    nets = _net(items)
    exponents = [-delta * year_fraction(t0, a.date, convention=convention) for a in nets]
    return _discounted_sum(nets, exponents, f"the NPV at log rate {delta!r}")


def npv(
    amounts: Sequence[DatedAmount], *, rate: float, day_count: DayCountConvention, t0: date
) -> float:
    """``sum a_i (1 + rate) ** -year_fraction(t0, d_i)``, discounted (or compounded) to ``t0``.

    Same-date amounts are netted with ``math.fsum`` before discounting (the NPV is the same
    in exact arithmetic; in floats, discounting two large opposite legs separately loses
    their small net). A term whose discount factor alone would underflow or overflow is
    computed in log space, so ``1e300 * exp(-1000)`` is ``5.08e-135``, not ``0``; see
    ``npv_at_log_rate`` for the sum.
    ``rate <= -1`` is refused: ``1 + rate`` must be positive for a real discount factor.
    Refuses a result outside the float range rather than returning ``inf``.
    """
    convention = check_convention(day_count)
    items = _check_amounts(amounts)
    value = _finite("rate", rate)
    if value <= -1.0:
        raise ValueError(
            f"rate must be > -1 (1 + rate is the growth factor), got {rate!r}; for a root "
            "reported as -1.0 use npv_at_log_rate with its log_rate"
        )
    log_growth = math.log1p(value)
    nets = _net(items)
    exponents = [-log_growth * year_fraction(t0, a.date, convention=convention) for a in nets]
    return _discounted_sum(nets, exponents, f"the NPV at rate {value!r}")


def xirr(amounts: Sequence[DatedAmount], *, day_count: DayCountConvention) -> IrrResult:
    """Every IRR of dated signed amounts under ``day_count``, with a completeness proof.

    Same-date amounts are netted (``ovf.pme.flows.net_by_date``) and dates whose net is
    zero are dropped. Input order is irrelevant. Refuses a series with fewer than two dates after
    netting: an IRR needs amounts at two different times.
    """
    convention = check_convention(day_count)
    items = _check_amounts(amounts)
    try:
        nets, zeros = net_by_date([(a.date, a.amount) for a in items])
    except OverflowError as exc:
        raise ValueError("a same-date net of the amounts exceeds the float range") from exc
    extra: list[str] = [
        "Same-date amounts are netted into one signed amount per date before discounting "
        "(NPV is invariant to this)."
    ]
    if zeros:
        extra.append(
            "Dates whose net is zero, exactly or within the float representation of its "
            "legs, are dropped: " + ", ".join(d.isoformat() for d in zeros) + "."
        )
    payload = {  # + 0.0 maps -0.0 to 0.0: equal inputs hash alike
        "method": "xirr",
        "amounts": sorted((a.date.isoformat(), a.amount + 0.0) for a in items),
        "day_count": convention,
    }
    return _solve(nets, convention, extra, canonical_hash(payload))


def fund_irr(resolved: ResolvedCashFlows, *, day_count: DayCountConvention) -> IrrResult:
    """IRR of ``resolved.net_by_date``: the fund's flows plus its residual value at ``as_of``.

    Refuses ``residual_value is None``: without a value at ``as_of`` the series omits the
    LP's remaining claim and its IRR is not the fund's.
    """
    if not isinstance(resolved, ResolvedCashFlows):
        raise ValueError(f"resolved must be a ResolvedCashFlows, got {type(resolved).__name__}")
    convention = check_convention(day_count)
    if resolved.residual_value is None:
        raise ValueError(
            f"fund {resolved.fund_name!r} has no residual value at {resolved.as_of.isoformat()} "
            "(nav_source='none'); state a NAV (0 for a fully realised fund) before solving "
            "its IRR"
        )
    nets = list(resolved.net_by_date)
    if len(nets) < 2:
        detail = []
        if resolved.residual_value == 0.0:
            if len({f.date for f in resolved.flows}) == 1:
                detail.append(
                    "a fund written off with all flows on one date has no IRR: NAV 0 adds "
                    "no amount at as_of"
                )
            else:
                detail.append("NAV 0 adds no amount at as_of")
        if resolved.netted_to_zero:
            detail.append(
                "dates whose net is zero were dropped: "
                + ", ".join(d.isoformat() for d in resolved.netted_to_zero)
            )
        raise ValueError(
            f"fund {resolved.fund_name!r} has non-zero net amounts on {len(nets)} date(s) and "
            "an IRR needs two" + ("; " + "; ".join(detail) if detail else "")
        )
    payload = {
        "method": "fund_irr",
        "resolved_input_hash": resolved.input_hash,
        "day_count": convention,
    }
    return _solve(nets, convention, list(resolved.assumptions), canonical_hash(payload))


def _rate(delta: float) -> float:
    if delta > _MAX_LOG:
        raise ValueError(
            f"a root has log rate delta={delta!r}: the annual rate exp(delta) - 1 exceeds "
            "the float range (above ~1.8e308), so it cannot be reported as a rate"
        )
    return math.expm1(delta)


def _solve(
    nets: list[DatedAmount],
    convention: DayCountConvention,
    context: list[str],
    input_hash: str,
) -> IrrResult:
    if len(nets) < 2:
        raise ValueError(
            f"an IRR needs non-zero net amounts on at least two dates; got {len(nets)} "
            "(same-date amounts are netted and dates whose net is zero are dropped)"
        )
    t0 = nets[0].date
    times = np.array([year_fraction(t0, a.date, convention=convention) for a in nets])
    # Log space from the stated floats, never a quotient that could be subnormal:
    # |a_i| = m_i 2**e_i exactly (frexp, m_i in [0.5, 1), subnormals included), and
    # ln|a_i| = ln m_i + (e_i - e_max) ln 2 up to the common offset e_max ln 2. ln m_i is
    # within an ulp of a number below 0.7, and the integer shift makes scaling every
    # amount by a power of two leave the computed problem bit-for-bit unchanged.
    signs = np.array([1.0 if a.amount > 0 else -1.0 for a in nets])
    parts = [math.frexp(abs(a.amount)) for a in nets]
    e_max = max(e for _, e in parts)
    log_abs = np.array([math.log(m) + (e - e_max) * _LN2 for m, e in parts])
    log_unit = e_max * _LN2
    try:
        gross = math.fsum(abs(a.amount) for a in nets)
    except OverflowError as exc:
        raise ValueError("the sum of |amounts| exceeds the float range") from exc
    if not math.isfinite(gross):
        raise ValueError("the sum of |amounts| exceeds the float range")
    log_gross = math.log(gross)

    try:
        base = _ExpSum(0, signs, log_abs, 2.0 * _EPS * (1.0 + np.abs(log_abs)), times, log_unit)
    except _DegenerateError as exc:  # pragma: no cover - finite non-zero amounts
        raise ValueError(str(exc)) from exc
    v = base.changes
    assumptions = [
        *context,
        describe(convention),
        f"t0 = {t0.isoformat()} (first date of the netted series); the day count is "
        "additive, so the roots do not depend on this choice.",
        "Rates are annual effective: NPV(r) = sum a_i (1 + r)^(-t_i); log_rate = ln(1 + r).",
        "Root policy: every real root is found and listed, none is chosen; irr is set only "
        "when exactly one root is proven and verified.",
        f"Residual tolerance: |NPV(root)| <= {TOLERANCE!r} * max(sum|a_i|, sum|a_i| "
        f"(1 + r)^(-t_i)), NPV at t0, with sum|a_i| = {gross!r}; the second sum, the gross "
        "discounted magnitude at the root, exceeds the first only at negative rates; the "
        "ratio is reported per root as relative_residual.",
    ]

    def result(
        status: IrrStatus,
        roots: list[IrrRoot],
        complete: bool,
        proof: str,
        bound: tuple[float, float] | None,
        log_bound: tuple[float, float] | None,
    ) -> IrrResult:
        roots.sort(key=lambda r: r.log_rate)
        return IrrResult(
            status=status,
            irr=roots[0].rate if status == "unique" else None,
            roots=tuple(roots),
            sign_changes=v,
            complete=complete,
            proof=proof,
            root_bound=bound,
            log_root_bound=log_bound,
            day_count=convention,
            t0=t0,
            amounts=tuple(nets),
            tolerance=TOLERANCE,
            assumptions=assumptions,
            input_hash=input_hash,
        )

    if v == 0:
        return result(
            "none",
            [],
            True,
            f"All {len(nets)} per-date amounts have the same sign (V=0): every term of "
            "f(delta) = sum a_i exp(-delta t_i) has that sign, so f never vanishes and no "
            "rate sets the NPV to zero."
            + (
                " A total loss has no IRR; showing -100% is a display convention, not a root."
                if all(a.amount < 0 for a in nets)
                else ""
            ),
            None,
            None,
        )

    def near_zero(level: int) -> Callable[[_Probe], bool]:
        def test(p: _Probe) -> bool:
            if abs(p.value) <= p.noise:
                return True
            if level == 0:
                # tol * max(sum|a_i|, sum|a_i| e^(-delta t_i)) on the scaled axis: divide
                # both by exp(log_scale), which is in the units of the stated amounts.
                undiscounted = math.exp(min(log_gross - p.log_scale, _MAX_LOG))
                return abs(p.value) <= TOLERANCE * max(undiscounted, p.magnitude)
            return abs(p.value) <= TOLERANCE * p.magnitude

        return test

    issues: list[str] = []
    try:
        levels = [base]
        while levels[-1].changes > 0:
            levels.append(levels[-1].derivative())
        critical: list[float] = []  # roots of the level below; f_V has none
        top: _LevelRoots | None = None
        for f in reversed(levels[:-1]):
            found = _isolate_level(f, critical, near_zero(f.level))
            issues.extend(found.issues)
            if f.level == 0:
                top = found
            else:
                if found.tangents:
                    issues.append(
                        f"derivative level {f.level} has a near-tangent critical point at "
                        "delta="
                        + ", ".join(repr(d) for d in found.tangents)
                        + "; a pair of unseen critical points cannot be excluded there"
                    )
                critical = found.crossings + found.tangents
    except _DegenerateError as exc:
        issues.append(str(exc))
        top = None

    if top is None:
        log_bound: tuple[float, float] | None
        try:  # the level-0 bound does not depend on the derivative levels
            lo0, hi0 = _dominance_bounds(base)
            log_bound = (lo0 + 0.0, hi0 + 0.0)
        except _DegenerateError:
            log_bound = None
        return result(
            "undetermined",
            [],
            False,
            f"V={v}: the isolation could not be completed with trustworthy arithmetic: "
            + "; ".join(issues),
            None
            if log_bound is None or log_bound[1] > _MAX_LOG
            else (math.expm1(log_bound[0]) + 0.0, math.expm1(log_bound[1]) + 0.0),
            log_bound,
        )

    def make_root(delta: float, kind: RootKind) -> IrrRoot:
        # f(delta) = exp(log_scale) * value in currency units at t0. The backward-error
        # scale max(sum|a_i|, exp(log_scale) * magnitude) is compared on the same axis, in
        # logs, so the ratio is finite (|value| <= magnitude makes it at most 1) however
        # far exp(log_scale) is outside the float range.
        probe = base.probe(delta)
        relative: float = 0.0
        residual: float | None = 0.0
        if probe.value != 0.0:
            log_value = math.log(abs(probe.value))
            log_bound = max(log_gross - probe.log_scale, math.log(probe.magnitude))
            relative = math.exp(log_value - log_bound)
            log_residual = log_value + probe.log_scale
            residual = (
                math.copysign(math.exp(log_residual), probe.value)
                if log_residual <= _MAX_LOG
                else None  # compounded past the float range at t0; relative is exact
            )
        rate = _rate(delta)
        return IrrRoot(
            rate=rate,
            log_rate=delta,
            npv_residual=residual,
            relative_residual=relative,
            rate_clamped=rate == -1.0,
            kind=kind,
        )

    roots = [make_root(d, "crossing") for d in top.crossings]
    roots += [make_root(d, "tangent") for d in top.tangents]
    crossing = [r for r in roots if r.kind == "crossing"]
    tangent = [r for r in roots if r.kind == "tangent"]
    if not issues and not tangent:
        if len(crossing) > v or (v - len(crossing)) % 2:
            issues.append(f"internal check failed: {len(crossing)} simple roots contradict V={v}")

    lo, hi = top.bound
    bound: tuple[float, float] | None
    if hi > _MAX_LOG:
        bound = None
        assumptions.append(
            "root_bound is None: the upper end of the root bound overflows as a rate; "
            "log_root_bound carries it."
        )
    else:
        bound = (math.expm1(lo) + 0.0, math.expm1(hi) + 0.0)  # + 0.0 turns -0.0 into 0.0
    if any(r.rate == -1.0 for r in roots):
        assumptions.append(
            "A root with 1 + r below float resolution is reported as rate -1.0; its "
            "log_rate carries the value."
        )

    descartes = (
        f"V={v} sign change(s): by Descartes' rule of signs for exponential sums (Jameson "
        f"2006, Thm 3.1 and Prop. 3.6) f has at most {v} real root(s), counted with "
        f"multiplicity, of the parity of V. Term dominance bounds every root to delta in "
        f"[{lo!r}, {hi!r}]."
    )
    if v == 1:
        method = " V=1 gives exactly one simple root; Brent's method refined it."
    else:
        method = (
            f" Rolle isolation through {v} derivative level(s) split the bound into "
            f"{top.pieces} monotone piece(s) of exp(delta tau) f; f changes sign on "
            f"{len(crossing)} of them" + (", each holding exactly one root." if crossing else ".")
        )
    failed = [r for r in crossing if r.relative_residual > TOLERANCE]
    complete = not issues and not tangent
    rates = ", ".join(f"{r.rate!r} ({r.kind})" for r in sorted(roots, key=lambda r: r.log_rate))
    if not complete:
        status: IrrStatus = "undetermined"
        why = []
        if tangent:
            why.append(
                f"{len(tangent)} critical point(s) with |NPV| within tolerance and no sign "
                "change (tangent: a double root and a near miss are indistinguishable in "
                "floating point)"
            )
        why.extend(issues)
        proof = f"{descartes}{method} Undetermined: " + "; ".join(why) + f". Found: {rates}."
    elif failed:
        status = "undetermined"
        proof = (
            f"{descartes}{method} The count is proven but {len(failed)} root(s) failed "
            "residual verification: "
            + ", ".join(
                f"relative residual {r.relative_residual!r} > {TOLERANCE!r} at log rate "
                f"{r.log_rate!r}"
                for r in failed
            )
            + "."
        )
    else:
        status = "none" if not crossing else "unique" if len(crossing) == 1 else "multiple"
        found_text = f" Roots: {rates}." if roots else " No real root."
        proof = f"{descartes}{method}{found_text} All residuals verified."
    return result(status, roots, complete, proof, bound, (lo + 0.0, hi + 0.0))
