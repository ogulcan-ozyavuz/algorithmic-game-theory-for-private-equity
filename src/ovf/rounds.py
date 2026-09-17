"""A priced equity round applied to an existing cap table.

``apply_priced_round(table, *, terms, protection, mfn)`` takes a ``CapTable`` holding
common, preferred, option pools, non-convertible debt and SAFEs, and the terms of one
priced round. It returns a new ``CapTable``: every existing position carried over as the
same object, each SAFE replaced in place by the preferred it converts into, the new-money
series added, and any pool increase added as its own position. The input is not modified.
This is the event shape of ``ovf.financing``: an event object applied to a table, with
every term-sheet and charter fact stated by the caller.

Three families of fact decide the numbers, and none has a default:

- the round-pricing convention: Cooley's pre-money, percentage-ownership and
  dollars-invested methods, which decide whether converting SAFE shares sit inside the
  pre-money share count and whether the SAFE money is added to the valuation;
- the pool change: a target post-round unallocated fraction, an increase by a stated
  number of shares, or none (the NVCA model term sheet shows both forms);
- the new series' seniority and terms, and whether converting SAFEs take their own series
  priced at their conversion price (the YC "Safe Preferred Stock") or the new series
  priced at the round price.

**The round is one scalar fixed point.** Parametrised by the post-round fully diluted
share count ``T``, the inverse price, the post-money SAFE Company Capitalization, the
pre-money SAFE capitalization and the pool are affine in ``T``. Each SAFE takes the larger
of affine functions of ``T``, so its share count is convex, and the balance
``g(T) = shares left for SAFEs - shares the SAFEs take`` is concave with ``g(0) < 0``. When
the slope of ``g`` for large ``T`` is positive, ``g`` is strictly increasing and the root is
unique; otherwise the round is refused. ``docs/rounds.md`` states the system, gives the
argument and derives every fixture by hand.

Nothing here reads a clock.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, model_validator

from ovf.contracts.captable import CapTable
from ovf.contracts.safes import (
    MFNAmendment,
    MFNResolution,
    PostMoneyDiscountSAFE,
    PostMoneyMFNSAFE,
    SafeInstrument,
    resolve_mfn,
)
from ovf.contracts.securities import (
    CommonStock,
    CumulativeDividend,
    PostMoneySAFE,
    PreferredStock,
    PreMoneySAFE,
    Security,
    StockOptionPool,
    option_pool,
)
from ovf.core.types import FinancialBaseModel, Money, Seniority, ShareCount, SharePrice
from ovf.financing import AntiDilutionProtection
from ovf.instruments.debt import ConvertibleNote, DebtInstrument

ENGINE_VERSION = "rounds-v1"

PricingConvention = Literal[
    "pre_money_method", "percentage_ownership_method", "dollars_invested_method"
]
"""Cooley, "Calculating Share Price With Outstanding Convertible Notes or Safes":

- ``pre_money_method``: "the pre-money valuation of the company is fixed and the conversion
  price for the notes or Safes is determined based on that". Converting SAFE shares are
  outside the pre-money share count; they dilute the new investor too.
- ``percentage_ownership_method``: "the percentage ownership of the company that the
  investor is purchasing is fixed". Converting SAFE shares are inside the pre-money count,
  so new money buys exactly ``N / (V + N)``. ``solve_priced_round_with_safes`` implements
  this one.
- ``dollars_invested_method``: "the post-money valuation of the company is fixed to equal
  the agreed upon pre-money valuation plus the dollars invested by the new investors plus
  the principal and accrued interest on the notes that are converting".

The three are negotiated, not three answers of which two are wrong, so there is no default.
"""

SafeSeries = Literal["safe_preferred", "standard_preferred"]
InstrumentKind = Literal[
    "post_money_valuation_cap",
    "pre_money_valuation_cap",
    "post_money_discount_only",
    "post_money_mfn_only",
]
ConversionBasis = Literal["round_price", "safe_price", "discount_price"]

_Line = tuple[float, float]
"""``a + b * T``."""


def _at(line: _Line, total: float) -> float:
    return line[0] + line[1] * total


# ---------------------------------------------------------------------------
# Round terms
# ---------------------------------------------------------------------------


class PoolChange(FinancialBaseModel):
    """How the round changes the unallocated option pool. Build one with
    ``pool_target_unallocated``, ``pool_increase`` or ``NO_POOL_CHANGE``.

    - ``target_unallocated_fraction``: after the round, the unallocated pool (the existing
      unallocated reserve plus the increase) is ``fraction`` of fully diluted shares. The
      increase is whatever that takes, so it moves with everything else in the round. The
      YC User Guide's worked rounds state "Target available option pool: 10%"; the NVCA
      model term sheet prices the round on "a fully-diluted pre-money valuation ...
      (including an employee pool representing [__]% of the fully-diluted post-money
      capitalization)".
    - ``increase_by_shares``: exactly ``shares`` are added (NVCA model term sheet:
      "[______] shares will be added to the option pool creating an unallocated option pool
      of [_______] shares").
    - ``none``: no increase.

    Either increase sits inside the pre-money share count, which is the NVCA term-sheet
    placement. A target below the existing unallocated reserve is refused, not treated as a
    cancellation. ``security_id`` and ``holder_id`` name the new pool position.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["target_unallocated_fraction", "increase_by_shares", "none"]
    fraction: float | None
    shares: float | None
    security_id: str | None
    holder_id: str | None

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind == "target_unallocated_fraction":
            if self.fraction is None or not 0 < self.fraction < 1:
                raise ValueError("a target unallocated pool fraction must lie strictly in (0, 1)")
            if self.shares is not None:
                raise ValueError("a target pool fraction takes no share count")
        elif self.kind == "increase_by_shares":
            if self.shares is None or not self.shares > 0:
                raise ValueError("a pool increase must add a positive number of shares")
            if self.fraction is not None:
                raise ValueError("a pool increase by shares takes no fraction")
        elif any(v is not None for v in (self.fraction, self.shares, self.security_id)):
            raise ValueError("NO_POOL_CHANGE takes no fraction, share count or security_id")
        if self.kind != "none" and not (self.security_id and self.holder_id):
            raise ValueError("a pool increase needs the security_id and holder_id of its position")
        return self


def pool_target_unallocated(fraction: float, *, security_id: str, holder_id: str) -> PoolChange:
    """Top the unallocated pool up to ``fraction`` of post-round fully diluted shares."""
    return PoolChange(
        kind="target_unallocated_fraction",
        fraction=float(fraction),
        shares=None,
        security_id=security_id,
        holder_id=holder_id,
    )


def pool_increase(shares: float, *, security_id: str, holder_id: str) -> PoolChange:
    """Add exactly ``shares`` to the unallocated pool."""
    return PoolChange(
        kind="increase_by_shares",
        fraction=None,
        shares=float(shares),
        security_id=security_id,
        holder_id=holder_id,
    )


NO_POOL_CHANGE = PoolChange(
    kind="none", fraction=None, shares=None, security_id=None, holder_id=None
)


class SeniorityPlacement(FinancialBaseModel):
    """Where the new series ranks. All three occur in practice, so there is no default.

    ``SENIOR_TO_ALL`` ranks it one step ahead of the most senior existing preferred;
    ``pari_passu_with(security_id)`` gives it that position's rank (a table records no issue
    dates, so "the most recent series" is named, not inferred); ``explicit_seniority(n)``
    uses rank ``n`` (0 is most senior, as everywhere in ``ovf``).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["senior_to_all", "pari_passu_with", "explicit"]
    security_id: str | None
    seniority: Seniority | None

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind == "senior_to_all" and (self.security_id or self.seniority is not None):
            raise ValueError("SENIOR_TO_ALL takes no security_id or seniority")
        if self.kind == "pari_passu_with" and (not self.security_id or self.seniority is not None):
            raise ValueError("pari_passu_with needs a security_id and takes no seniority")
        if self.kind == "explicit" and (self.seniority is None or self.security_id):
            raise ValueError("explicit_seniority needs a seniority and takes no security_id")
        return self


SENIOR_TO_ALL = SeniorityPlacement(kind="senior_to_all", security_id=None, seniority=None)


def pari_passu_with(security_id: str) -> SeniorityPlacement:
    """Rank the new series with the named existing preferred position."""
    return SeniorityPlacement(kind="pari_passu_with", security_id=security_id, seniority=None)


def explicit_seniority(seniority: int) -> SeniorityPlacement:
    """Rank the new series at ``seniority`` (0 is most senior)."""
    return SeniorityPlacement(kind="explicit", security_id=None, seniority=seniority)


class NewSeries(FinancialBaseModel):
    """The new-money series: its identity, rank and liquidation terms. Every field is required.

    Converting SAFEs receive the same rank and terms: the YC post-money forms define Safe
    Preferred Stock as "having the identical rights, privileges, preferences, seniority,
    liquidation multiple and restrictions as the shares of Standard Preferred Stock, except
    that any price-based preferences ... will be based on the Safe Price" (Discount Price in
    the Discount Only form). The initial conversion ratio is 1. Dividend terms are not taken.
    """

    model_config = ConfigDict(frozen=True)

    security_id: str = Field(min_length=1)
    holder_id: str = Field(min_length=1)
    seniority: SeniorityPlacement
    liquidation_multiple: float = Field(gt=0)
    participating: StrictBool
    participation_cap: float | None

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        if self.participation_cap is not None:
            if not self.participating:
                raise ValueError("participation_cap requires participating=True")
            if self.participation_cap < self.liquidation_multiple:
                raise ValueError("participation_cap cannot be below liquidation_multiple")
        return self


class PricedRound(FinancialBaseModel):
    """The term-sheet facts of one priced round. Every field is required.

    ``safe_series`` decides the preference basis of converting SAFEs:

    - ``"safe_preferred"``: the YC post-money forms. A SAFE converting at its Safe Price or
      Discount Price takes its own position whose per-share preference is that price, so
      its preference is its Purchase Amount times the multiple; one converting at the round
      price takes new-series shares at the round price.
    - ``"standard_preferred"``: every converting SAFE takes new-series shares with the round
      price as its per-share preference, so a SAFE that converted below the round price
      claims more than its Purchase Amount (the "liquidation overhang").
    """

    model_config = ConfigDict(frozen=True)

    pre_money_valuation: float = Field(gt=0)
    new_money: float = Field(gt=0)
    convention: PricingConvention
    pool: PoolChange
    new_series: NewSeries
    safe_series: SafeSeries


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


class RoundCapitalization(FinancialBaseModel):
    """Common-equivalent counts of the table immediately before the round.

    Preferred counts at its conversion ratio in effect; granted options gross, one share per
    option, as the YC Company Capitalization counts "all (i) issued and outstanding Options"
    "on an as-converted to Common Stock basis". SAFEs are not counted here.
    """

    model_config = ConfigDict(frozen=True)

    common_outstanding: ShareCount
    preferred_as_converted: ShareCount
    granted_options: ShareCount
    unallocated_pool: ShareCount

    @property
    def outstanding(self) -> ShareCount:
        """Common, preferred as converted and granted options: everything but the reserve."""
        return self.common_outstanding + self.preferred_as_converted + self.granted_options


class SafeConversion(FinancialBaseModel):
    """How one SAFE converted, with the numbers behind it."""

    security_id: str
    holder_id: str
    instrument: InstrumentKind
    purchase_amount: Money
    valuation_cap: Money | None
    discount: float | None
    capitalization: ShareCount | None = Field(
        description="The capitalization its cap is measured against; None without a cap"
    )
    cap_price: SharePrice | None
    discount_price: SharePrice | None
    round_price: SharePrice
    basis: ConversionBasis
    conversion_price: SharePrice
    shares: ShareCount
    series: Literal["safe_preferred", "standard_preferred"]
    preference_price: SharePrice
    position: PreferredStock


class ExistingPreferred(FinancialBaseModel):
    """What the round did to one existing preferred position: nothing, and why that is right."""

    security_id: str
    holder_id: str
    protection: Literal["weighted_average", "full_ratchet", "none"]
    conversion_price: SharePrice
    lowest_round_price: SharePrice
    outcome: Literal["unprotected", "not_triggered"]


class RoundResult(FinancialBaseModel):
    """A new cap table after one priced round, with the trace that produced it."""

    table: CapTable
    terms: PricedRound
    capitalization: RoundCapitalization
    price_per_share: SharePrice
    pre_money_share_count: ShareCount = Field(
        description="The share count the effective pre-money valuation is divided by"
    )
    effective_pre_money_valuation: Money
    implied_post_money_valuation: Money
    new_money_shares: ShareCount
    pool_increase_shares: ShareCount
    unallocated_pool_after: ShareCount
    total_post_shares: ShareCount
    post_money_safe_capitalization: ShareCount
    pre_money_safe_capitalization: ShareCount
    safe_conversions: list[SafeConversion]
    mfn_amendments: list[MFNAmendment]
    existing_preferred: list[ExistingPreferred]
    new_series_seniority: int
    ownership_breakdown: dict[str, float]
    uniqueness_margin: float = Field(
        description="Slope of the balance g(T) for large T; positive means one solution"
    )
    iterations: int = Field(ge=1)
    share_balance_error: float
    pricing_error: float
    input_hash: str
    engine_version: str = ENGINE_VERSION
    assumptions: list[str]

    def conversion(self, security_id: str) -> SafeConversion:
        """The conversion record of one SAFE."""
        for c in self.safe_conversions:
            if c.security_id == security_id:
                return c
        raise KeyError(security_id)


# ---------------------------------------------------------------------------
# The scalar system
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Convertible:
    source: SafeInstrument
    kind: InstrumentKind
    amount: float
    discount: float | None
    price_factor: float  # 1 / (1 - discount); 1 without a discount
    price_basis: ConversionBasis  # "round_price" or "discount_price"
    cap: float | None
    cap_on: Literal["post", "pre"] | None


def _normalise(s: SafeInstrument) -> _Convertible:
    if isinstance(s, PostMoneyDiscountSAFE):
        return _Convertible(
            s, "post_money_discount_only", s.investment_amount, s.discount,
            1.0 / (1.0 - s.discount), "discount_price", None, None,
        )  # fmt: skip
    if isinstance(s, PostMoneyMFNSAFE):
        return _Convertible(
            s, "post_money_mfn_only", s.investment_amount, None, 1.0, "round_price", None, None
        )
    d = s.discount_rate
    return _Convertible(
        source=s,
        kind="post_money_valuation_cap"
        if isinstance(s, PostMoneySAFE)
        else "pre_money_valuation_cap",
        amount=s.investment_amount,
        discount=d if d > 0 else None,
        price_factor=1.0 / (1.0 - d),
        price_basis="discount_price" if d > 0 else "round_price",
        cap=s.valuation_cap,
        cap_on="post" if isinstance(s, PostMoneySAFE) else "pre",
    )


@dataclass(frozen=True)
class _System:
    """Every round quantity as a function of the post-round fully diluted count ``T``."""

    outstanding: float  # F: common, preferred as converted, granted options
    unallocated: float  # E: the existing unallocated reserve
    pool_after: _Line  # unallocated pool after the round, E + increase
    inverse_price: _Line  # 1 / P
    available: _Line  # shares left for SAFEs: T - F - pool_after - N / P
    post_capitalization: _Line  # YC post-money Company Capitalization: F + E + SAFE shares
    pre_capitalization: _Line  # pre-money SAFE capitalization: F + pool_after
    safes: tuple[_Convertible, ...]

    def _lines(self, c: _Convertible) -> tuple[_Line, _Line | None]:
        """A SAFE's share count under its price option and under its cap option."""
        k = c.amount * c.price_factor
        price = (k * self.inverse_price[0], k * self.inverse_price[1])
        if c.cap is None:
            return price, None
        base = self.post_capitalization if c.cap_on == "post" else self.pre_capitalization
        return price, (c.amount * base[0] / c.cap, c.amount * base[1] / c.cap)

    def options(self, c: _Convertible, total: float) -> tuple[float, float | None]:
        price, cap = self._lines(c)
        return _at(price, total), None if cap is None else _at(cap, total)

    def shares(self, c: _Convertible, total: float) -> float:
        price, cap = self.options(c, total)
        return price if cap is None else max(price, cap)

    def balance(self, total: float) -> float:
        return _at(self.available, total) - math.fsum(self.shares(c, total) for c in self.safes)

    def terminal_slope(self) -> float:
        slope = self.available[1]
        for c in self.safes:
            price, cap = self._lines(c)
            slope -= price[1] if cap is None else max(price[1], cap[1])
        return slope

    def piece(self, total: float) -> _Line:
        """The affine piece of ``balance`` in force at ``total``."""
        a, b = self.available
        for c in self.safes:
            price, cap = self._lines(c)
            line = price if cap is None or _at(price, total) >= _at(cap, total) else cap
            a, b = a - line[0], b - line[1]
        return a, b


def _build_system(
    capitalization: RoundCapitalization,
    terms: PricedRound,
    safes: Sequence[_Convertible],
) -> _System:
    outstanding = capitalization.outstanding
    unallocated = capitalization.unallocated_pool
    pool = terms.pool
    if pool.kind == "target_unallocated_fraction":
        assert pool.fraction is not None  # enforced by PoolChange
        pool_after: _Line = (0.0, pool.fraction)
    elif pool.kind == "increase_by_shares":
        assert pool.shares is not None
        pool_after = (unallocated + pool.shares, 0.0)
    else:
        pool_after = (unallocated, 0.0)
    pre, new = terms.pre_money_valuation, terms.new_money
    post = pre + new
    if terms.convention == "percentage_ownership_method":
        # P * (T - N/P) = V  =>  P * T = V + N.
        inverse: _Line = (0.0, 1.0 / post)
    elif terms.convention == "dollars_invested_method":
        # P * (T - N/P) = V + sum(I)  =>  P * T = V + N + sum(I).
        inverse = (0.0, 1.0 / (post + math.fsum(c.amount for c in safes)))
    else:
        # P * (F + E + increase) = V, the SAFE shares outside the count.
        inverse = ((outstanding + pool_after[0]) / pre, pool_after[1] / pre)
    available = (
        -outstanding - pool_after[0] - new * inverse[0],
        1.0 - pool_after[1] - new * inverse[1],
    )
    return _System(
        outstanding=outstanding,
        unallocated=unallocated,
        pool_after=pool_after,
        inverse_price=inverse,
        available=available,
        post_capitalization=(outstanding + unallocated + available[0], available[1]),
        pre_capitalization=(outstanding + pool_after[0], pool_after[1]),
        safes=tuple(safes),
    )


_MIN_MARGIN = 1e-12


def _solve(system: _System) -> tuple[float, int, float]:
    """The unique root of the balance, its bisection count and the uniqueness margin."""
    margin = system.terminal_slope()
    if not margin > _MIN_MARGIN:
        raise ValueError(
            "No unique solution: the round leaves too little room for the SAFEs. The share "
            "balance g(T) is concave, and its slope for large T is "
            f"{margin:.6g}; only a positive slope guarantees exactly one post-round "
            "capitalization. With a non-positive slope the round has no solution or more "
            "than one, and either way no answer is reported (docs/rounds.md)"
        )
    at_zero = system.balance(0.0)
    if not at_zero < 0:
        raise ValueError("The round has no positive capitalization; check the inputs")
    # g is concave with every slope at least `margin`, so g(T) >= g(0) + margin * T.
    upper = -at_zero / margin * (1 + 1e-9) + 1.0
    for _ in range(64):
        if system.balance(upper) > 0:
            break
        upper *= 2
    else:  # pragma: no cover - excluded by the margin argument above
        raise RuntimeError("Round solver could not bracket the solution")
    lower = 0.0
    iterations = 0
    for iterations in range(1, 401):  # noqa: B007 - the count is reported
        middle = 0.5 * (lower + upper)
        if system.balance(middle) > 0:
            upper = middle
        else:
            lower = middle
        if upper - lower <= 1e-14 * upper:
            break
    else:  # pragma: no cover - 400 halvings exhaust any double
        raise RuntimeError("Round solver did not converge")
    # g is piecewise affine: solve the piece in force exactly, unless a kink sits on the root.
    a, b = system.piece(0.5 * (lower + upper))
    width = upper - lower
    total = -a / b
    if not lower - width <= total <= upper + width:
        total = 0.5 * (lower + upper)
    return total, iterations, margin


# ---------------------------------------------------------------------------
# The event
# ---------------------------------------------------------------------------


_SAFE_TYPES = (PostMoneySAFE, PreMoneySAFE, PostMoneyDiscountSAFE, PostMoneyMFNSAFE)


def round_capitalization(table: CapTable) -> RoundCapitalization:
    """Count the table immediately before a round: see ``RoundCapitalization``.

    SAFEs and non-convertible debt count nothing here. Refused: a convertible note (the
    round does not price notes); preferred carrying a paid-in-kind cumulative dividend,
    whose as-converted count depends on an accrual date; any other instrument.
    """
    if not isinstance(table, CapTable):
        raise ValueError(f"table must be a CapTable, got {type(table).__name__}")
    common: list[float] = []
    preferred_units: list[float] = []
    granted: list[float] = []
    reserve: list[float] = []
    for s in table.securities:
        if isinstance(s, ConvertibleNote):
            raise ValueError(
                f"{s.security_id}: a convertible note converting in a priced round is not "
                "modelled (its conversion needs accrued interest to a date and the note's "
                "own qualified-financing terms); settle or convert it into a snapshot first"
            )
        if isinstance(s, CommonStock):
            common.append(s.shares)
        elif isinstance(s, PreferredStock):
            dividend = s.dividend
            if isinstance(dividend, CumulativeDividend) and dividend.settlement == "paid_in_kind":
                raise ValueError(
                    f"{s.security_id}: a paid-in-kind dividend adds shares that accrue with "
                    "time, so its as-converted count at the round is date-dependent; not "
                    "modelled in a round"
                )
            preferred_units.append(s.converted_shares)
        elif isinstance(s, StockOptionPool):
            granted.append(s.allocated_shares)
            reserve.append(s.unallocated_shares)
        elif not isinstance(s, _SAFE_TYPES + (DebtInstrument,)):
            raise ValueError(f"{s.security_id}: {type(s).__name__} has no defined place in a round")
    return RoundCapitalization(
        common_outstanding=math.fsum(common),
        preferred_as_converted=math.fsum(preferred_units),
        granted_options=math.fsum(granted),
        unallocated_pool=math.fsum(reserve),
    )


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot fingerprint {type(value).__name__}")


def _dump(security: Security) -> dict[str, Any]:
    return {"kind": type(security).__name__, **security.model_dump()}


def _new_seniority(table: CapTable, placement: SeniorityPlacement) -> int:
    ranks = {s.security_id: s.seniority for s in table.securities if isinstance(s, PreferredStock)}
    if placement.kind == "explicit":
        assert placement.seniority is not None
        return placement.seniority
    if placement.kind == "pari_passu_with":
        assert placement.security_id is not None
        if placement.security_id not in ranks:
            raise ValueError(
                f"pari_passu_with names {placement.security_id!r}, which is not a preferred "
                "position in the table"
            )
        return ranks[placement.security_id]
    if not ranks:
        raise ValueError(
            "SENIOR_TO_ALL needs existing preferred to rank ahead of; the table has none. "
            "Use explicit_seniority for a first priced round"
        )
    most_senior = min(ranks.values())
    if most_senior == 0:
        raise ValueError(
            "SENIOR_TO_ALL cannot rank ahead of seniority 0, the most senior rank. Renumber the "
            "existing preferred in a new snapshot, or use explicit_seniority"
        )
    return most_senior - 1


def apply_priced_round(
    table: CapTable,
    *,
    terms: PricedRound,
    protection: Mapping[str, AntiDilutionProtection],
    mfn: MFNResolution | None,
) -> RoundResult:
    """Apply one priced round to ``table`` and return the new snapshot with its trace.

    ``protection`` must name every preferred position in ``table`` with its price-based
    anti-dilution term, exactly as ``ovf.financing.apply_dilutive_issuance`` requires; pass
    ``UNPROTECTED`` for a position whose charter gives it none. A protected position is
    carried unchanged when no share in the round is issued below its conversion price. When
    one is, the round is refused: see docs/rounds.md, "Anti-dilution inside a round".

    ``mfn`` must be an ``MFNResolution`` when the table holds an MFN Only SAFE and ``None``
    otherwise. Elected amendments are applied before anything converts.

    Every SAFE converts; the round is solved as the fixed point described in the module
    docstring and refused when that fixed point is not unique. The result is checked for
    share conservation and for the pricing identity of the stated convention.
    """
    if not isinstance(terms, PricedRound):
        raise ValueError(f"terms must be a PricedRound, got {type(terms).__name__}")
    capitalization = round_capitalization(table)
    if not capitalization.outstanding > 0:
        raise ValueError("The table must hold outstanding shares before a round")
    if not isinstance(protection, Mapping):
        raise ValueError(f"protection must be a mapping, got {type(protection).__name__}")
    preferred_ids = [s.security_id for s in table.securities if isinstance(s, PreferredStock)]
    missing = [i for i in preferred_ids if i not in protection]
    if missing:
        raise ValueError(
            "state the anti-dilution term of every preferred position; missing: "
            f"{', '.join(missing)}. Pass UNPROTECTED for a position whose charter gives it "
            "no price-based protection"
        )
    unknown = sorted(set(protection) - set(preferred_ids))
    if unknown:
        raise ValueError(
            f"protection names positions that are not preferred stock in the table: "
            f"{', '.join(unknown)}"
        )
    for security_id, term in protection.items():
        if not isinstance(term, AntiDilutionProtection):
            raise ValueError(
                f"protection for {security_id} must be an AntiDilutionProtection, got "
                f"{type(term).__name__}"
            )

    table_ids = {s.security_id for s in table.securities}
    new_ids = [terms.new_series.security_id]
    if terms.pool.security_id is not None:
        new_ids.append(terms.pool.security_id)
    for security_id in new_ids:
        if security_id in table_ids:
            raise ValueError(f"Duplicate security_id: {security_id} is already in the table")
    if len(set(new_ids)) != len(new_ids):
        raise ValueError("the new series and the pool increase need different security_ids")
    seniority = _new_seniority(table, terms.new_series.seniority)

    safes_in: list[SafeInstrument] = [s for s in table.securities if isinstance(s, _SAFE_TYPES)]
    has_mfn = any(isinstance(s, PostMoneyMFNSAFE) for s in safes_in)
    amendments: list[MFNAmendment] = []
    if has_mfn:
        if not isinstance(mfn, MFNResolution):
            raise ValueError(
                "the table holds an MFN Only SAFE, so mfn must be an MFNResolution stating the "
                "issue order and each holder's election (None for no election)"
            )
        safes, amendments = resolve_mfn(safes_in, mfn)
    else:
        if mfn is not None:
            raise ValueError("mfn must be None: the table holds no MFN Only SAFE")
        safes = safes_in
    convertibles = [_normalise(s) for s in safes]

    system = _build_system(capitalization, terms, convertibles)
    total, iterations, margin = _solve(system)
    tolerance = max(1e-8, total * 1e-10)

    outstanding, unallocated = capitalization.outstanding, capitalization.unallocated_pool
    pool_after = _at(system.pool_after, total)
    increase = pool_after - unallocated
    if increase < 0:
        if increase < -tolerance:
            raise ValueError(
                f"The existing unallocated pool ({unallocated:,.2f} shares) already exceeds "
                f"the target of {terms.pool.fraction} of post-round shares "
                f"({pool_after:,.2f}). A target does not cancel reserve; state the pool "
                "change as NO_POOL_CHANGE or as an increase by shares"
            )
        increase, pool_after = 0.0, unallocated
    inverse = _at(system.inverse_price, total)
    price = 1.0 / inverse
    if not (math.isfinite(total) and math.isfinite(price) and price > 0):
        raise ValueError("Round lies outside the supported finite numeric range")
    post_cap = _at(system.post_capitalization, total)
    pre_cap = _at(system.pre_capitalization, total)
    new_shares = terms.new_money * inverse

    series = terms.new_series
    conversions: list[SafeConversion] = []
    safe_shares: dict[str, float] = {}
    for c in convertibles:
        by_price, by_cap = system.options(c, total)
        shares = by_price if by_cap is None else max(by_price, by_cap)
        basis: ConversionBasis = (
            "safe_price" if by_cap is not None and by_cap > by_price else c.price_basis
        )
        conversion_price = price if basis == "round_price" else c.amount / shares
        if terms.safe_series == "standard_preferred":
            label: Literal["safe_preferred", "standard_preferred"] = "standard_preferred"
            preference_price = price
        else:
            label = "standard_preferred" if basis == "round_price" else "safe_preferred"
            preference_price = conversion_price
        capitalization_used = None
        if c.cap_on == "post":
            capitalization_used = post_cap
        elif c.cap_on == "pre":
            capitalization_used = pre_cap
        source = c.source
        position = PreferredStock(
            security_id=source.security_id,
            holder_id=source.holder_id,
            shares=shares,
            price=preference_price,
            seniority=seniority,
            liquidation_multiple=series.liquidation_multiple,
            participating=series.participating,
            participation_cap=series.participation_cap,
            conversion_ratio=1.0,
        )
        safe_shares[source.security_id] = shares
        conversions.append(
            SafeConversion(
                security_id=source.security_id,
                holder_id=source.holder_id,
                instrument=c.kind,
                purchase_amount=c.amount,
                valuation_cap=c.cap,
                discount=c.discount,
                capitalization=capitalization_used,
                cap_price=None
                if c.cap is None or capitalization_used is None
                else c.cap / capitalization_used,
                discount_price=None if c.discount is None else price * (1 - c.discount),
                round_price=price,
                basis=basis,
                conversion_price=conversion_price,
                shares=shares,
                series=label,
                preference_price=preference_price,
                position=position,
            )
        )

    all_safe_shares = math.fsum(safe_shares.values())
    error = math.fsum([outstanding, pool_after, all_safe_shares, new_shares]) - total
    if abs(error) > tolerance:
        raise RuntimeError("Round solution failed share conservation")
    safe_money = math.fsum(c.amount for c in convertibles)
    if terms.convention == "pre_money_method":
        counted = outstanding + pool_after
        effective_pre = terms.pre_money_valuation
    else:
        counted = outstanding + pool_after + all_safe_shares
        effective_pre = terms.pre_money_valuation + (
            safe_money if terms.convention == "dollars_invested_method" else 0.0
        )
    pricing_error = price * counted - effective_pre
    if abs(pricing_error) > 1e-9 * effective_pre:
        raise RuntimeError("Round solution failed the pricing identity of its convention")

    lowest = min([price, *(c.conversion_price for c in conversions)])
    existing: list[ExistingPreferred] = []
    for s in table.securities:
        if not isinstance(s, PreferredStock):
            continue
        term = protection[s.security_id]
        if term.method == "none":
            existing.append(
                ExistingPreferred(
                    security_id=s.security_id,
                    holder_id=s.holder_id,
                    protection="none",
                    conversion_price=s.price / s.conversion_ratio,
                    lowest_round_price=lowest,
                    outcome="unprotected",
                )
            )
            continue
        if not s.price > 0:
            raise ValueError(
                f"{s.security_id}: protected preferred needs a positive Original Issue Price "
                f"(price is {s.price}); its conversion price is undefined"
            )
        conversion_price = s.price / s.conversion_ratio
        if lowest < conversion_price:
            raise ValueError(
                f"{s.security_id}: its {term.method.replace('_', ' ')} protection would be "
                f"triggered. The round issues shares at {lowest:.6g}, below its conversion "
                f"price of {conversion_price:.6g}. Price-based anti-dilution inside a round is "
                "not modelled: whether the round's pre-money share count includes the "
                "adjustment shares is circular and is not settled by the NVCA model term "
                "sheet, and a SAFE converting below the conversion price raises NVCA 4.4.3's "
                "deemed-issuance question. Pass UNPROTECTED only if the charter gives this "
                "position no price-based protection"
            )
        existing.append(
            ExistingPreferred(
                security_id=s.security_id,
                holder_id=s.holder_id,
                protection=term.method,
                conversion_price=conversion_price,
                lowest_round_price=lowest,
                outcome="not_triggered",
            )
        )

    converted = {c.security_id: c.position for c in conversions}
    after: list[Security] = [converted.get(s.security_id, s) for s in table.securities]
    after.append(
        PreferredStock(
            security_id=series.security_id,
            holder_id=series.holder_id,
            shares=new_shares,
            price=price,
            seniority=seniority,
            liquidation_multiple=series.liquidation_multiple,
            participating=series.participating,
            participation_cap=series.participation_cap,
            conversion_ratio=1.0,
        )
    )
    if increase > 0:
        assert terms.pool.security_id is not None and terms.pool.holder_id is not None
        after.append(
            option_pool(
                increase, holder_id=terms.pool.holder_id, security_id=terms.pool.security_id
            )
        )
    new_table = CapTable(securities=after)

    payload: dict[str, Any] = {
        "table": [_dump(s) for s in table.securities],
        "terms": terms.model_dump(),
        "protection": {k: protection[k].model_dump() for k in sorted(protection)},
        "mfn": None if mfn is None else mfn.model_dump(),
    }
    return RoundResult(
        table=new_table,
        terms=terms,
        capitalization=capitalization,
        price_per_share=price,
        pre_money_share_count=counted,
        effective_pre_money_valuation=effective_pre,
        implied_post_money_valuation=price * total,
        new_money_shares=new_shares,
        pool_increase_shares=increase,
        unallocated_pool_after=pool_after,
        total_post_shares=total,
        post_money_safe_capitalization=post_cap,
        pre_money_safe_capitalization=pre_cap,
        safe_conversions=conversions,
        mfn_amendments=amendments,
        existing_preferred=existing,
        new_series_seniority=seniority,
        ownership_breakdown=new_table.ownership_breakdown(),
        uniqueness_margin=margin,
        iterations=iterations,
        share_balance_error=error,
        pricing_error=pricing_error,
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False, default=_json_default).encode()
        ).hexdigest(),
        assumptions=_assumptions(terms),
    )


_CONVENTION_TEXT: dict[str, str] = {
    "pre_money_method": (
        "Round priced by Cooley's pre-money method: price = pre-money valuation / (outstanding "
        "+ unallocated pool after the round); converting SAFE shares are outside that count "
        "and dilute the new investor as well."
    ),
    "percentage_ownership_method": (
        "Round priced by Cooley's percentage-ownership method: price = pre-money valuation / "
        "(outstanding + unallocated pool after the round + converting SAFE shares), so new "
        "money buys exactly new / (pre + new)."
    ),
    "dollars_invested_method": (
        "Round priced by Cooley's dollars-invested method: price = (pre-money valuation + SAFE "
        "purchase amounts) / (outstanding + unallocated pool after the round + converting "
        "SAFE shares)."
    ),
}


def _assumptions(terms: PricedRound) -> list[str]:
    pool = terms.pool
    if pool.kind == "target_unallocated_fraction":
        pool_text = (
            f"Pool topped up so the unallocated pool after the round is {pool.fraction} of "
            "fully diluted shares; the increase sits inside the pre-money share count."
        )
    elif pool.kind == "increase_by_shares":
        pool_text = (
            f"Pool increased by exactly {pool.shares} shares, inside the pre-money share count."
        )
    else:
        pool_text = "No pool change."
    series_text = (
        "Converting SAFEs take their own series with the per-share preference at their "
        "conversion price (YC Safe Preferred Stock), or new-series shares at the round price."
        if terms.safe_series == "safe_preferred"
        else "Converting SAFEs take new-series shares with the round price as their per-share "
        "preference, whatever price they converted at."
    )
    return [
        _CONVENTION_TEXT[terms.convention],
        pool_text,
        series_text,
        "Post-money SAFE cap denominator (YC Company Capitalization): outstanding stock as "
        "converted, granted options, the existing unallocated pool and every converting SAFE; "
        "not the pool increase or the new money. Promised options are not represented.",
        "Pre-money SAFE cap denominator (YC User Guide's original-safe column): outstanding "
        "stock as converted, granted options, the unallocated pool including the increase; no "
        "SAFEs.",
        "Granted options count gross, one share per option; no treasury method.",
        "Existing positions are carried unchanged; no protected position is issued below its "
        "conversion price (otherwise the round is refused). Pay-to-play, pro rata rights, "
        "side letters and notes are not modelled.",
        "Solved as one scalar fixed point in post-round fully diluted shares; the solution is "
        "unique because the balance is concave with a positive slope for large T.",
    ]
