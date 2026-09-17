"""Exit allocation and verified best-response search for independent preferred positions.

Debt is settled first, from net proceeds, ahead of every equity position; the
conversion game is then played over the equity residual exactly as without debt.
A preferred position's cumulative dividend enters through its exit terms on the same
explicit ``as_of`` date (see docs/dividends.md); nothing reads a clock.

``forced_conversions`` names preferred positions already converted before the exit by a
collective decision (docs/governance.md). They hold their as-converted units, claim no
preference and are not players. Left empty, every result is exactly what it was before
the parameter existed.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Collection, Sequence
from datetime import date
from typing import Any

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from ovf.contracts.securities import (
    CommonStock,
    CumulativeDividend,
    DividendAccrual,
    PreferredExitTerms,
    PreferredStock,
    Security,
    StockOptionPool,
)
from ovf.core.types import FinancialBaseModel, Money, Multiple, Percentage
from ovf.instruments.debt import ConvertibleNote, DebtClaim, DebtInstrument


class WaterfallConvergenceError(RuntimeError):
    """No verified equilibrium was found within the search budget."""


class Payout(FinancialBaseModel):
    """Cash to one position.

    For a debt position ``amount`` is the repayment; the preference, participation and
    residual fields describe equity components and stay zero. The derivation of a debt
    payment is in ``WaterfallResult.debt_settlements``.
    """

    security_id: str
    holder_id: str
    amount: Money
    preference_payout: Money = 0.0
    participation_payout: Money = 0.0
    residual_payout: Money = 0.0
    converted: bool = False
    payout_pct: Percentage = 0.0
    invested_capital: Money = 0.0
    effective_multiple: Multiple | None = None

    @property
    def ownership_pct(self) -> Percentage:
        """Compatibility alias for payout_pct; this is NOT equity ownership."""
        return self.payout_pct


class DebtSettlement(FinancialBaseModel):
    """Cash paid to one debt position ahead of all equity, against its claim."""

    claim: DebtClaim
    paid: Money
    shortfall: Money


class WaterfallResult(FinancialBaseModel):
    payouts: list[Payout]
    gross_exit: Money
    transaction_costs: Money
    net_exit: Money
    converged: bool
    iterations: int = Field(ge=0)
    max_unilateral_gain: Money
    tolerance: Money
    conservation_error: float
    input_hash: str
    engine_version: str = "waterfall-v3"
    assumptions: list[str]
    multi_position_holders: list[str] = Field(default_factory=list)
    as_of: date | None = Field(
        default=None,
        description="Accrual date used for debt claims and cumulative dividends; None if unread",
    )
    debt_settlements: list[DebtSettlement] = Field(default_factory=list)
    dividend_accruals: list[DividendAccrual] = Field(default_factory=list)


def validate_securities(securities: Sequence[Security]) -> None:
    ids: set[str] = set()
    for security in securities:
        if not isinstance(security, Security):
            raise ValueError("All positions must be Security instances")
        if security.security_id in ids:
            raise ValueError(f"Duplicate security_id: {security.security_id}")
        ids.add(security.security_id)


def forced_conversion_ids(
    forced_conversions: Collection[str], securities: Sequence[Security]
) -> frozenset[str]:
    """Validate ``forced_conversions`` against the table and return it as a set.

    Each entry must be the ``security_id`` of a preferred position in ``securities``, named
    once. A bare string is refused rather than read as a collection of characters.
    """
    if isinstance(forced_conversions, str):
        raise ValueError(
            "forced_conversions must be a collection of security_ids, not a single string"
        )
    preferred = {s.security_id for s in securities if isinstance(s, PreferredStock)}
    seen: set[str] = set()
    for security_id in forced_conversions:
        if not isinstance(security_id, str):
            raise ValueError(
                f"forced_conversions entries must be security_id strings, got "
                f"{type(security_id).__name__}"
            )
        if security_id in seen:
            raise ValueError(f"forced_conversions names {security_id} twice")
        if security_id not in preferred:
            raise ValueError(
                f"forced_conversions names {security_id}, which is not a preferred position "
                "in the table; only preferred stock converts"
            )
        seen.add(security_id)
    return frozenset(seen)


def evaluate_fixed_waterfall(
    securities: Sequence[Security],
    net_exit: float,
    conversion_state: dict[str, bool],
    *,
    as_of: date | None = None,
) -> tuple[dict[str, Payout], float]:
    """Internal allocation primitive; callers validate instruments and numeric inputs.

    Each preferred position contributes its ``exit_terms(as_of)``: the preference it
    claims, its total participation cap and its common-equivalent units. ``as_of`` is read
    only by positions with a cumulative dividend, which refuse to price without it.
    """
    s: Security
    terms: dict[str, PreferredExitTerms] = {
        s.security_id: s.exit_terms(as_of) for s in securities if isinstance(s, PreferredStock)
    }
    payouts = {
        s.security_id: Payout(
            security_id=s.security_id,
            holder_id=s.holder_id,
            amount=0,
            converted=conversion_state.get(s.security_id, False),
            invested_capital=s.invested_capital,
        )
        for s in securities
    }
    remaining = net_exit
    preferred = [
        s
        for s in securities
        if isinstance(s, PreferredStock) and not conversion_state[s.security_id]
    ]
    for level in sorted({s.seniority for s in preferred}):
        tier = [s for s in preferred if s.seniority == level]
        needed = math.fsum(terms[s.security_id].preference for s in tier)
        budget = min(remaining, needed)
        for s in tier:
            amount = budget * (terms[s.security_id].preference / needed) if needed else 0.0
            payouts[s.security_id].amount = amount
            payouts[s.security_id].preference_payout = amount
        remaining = max(0.0, remaining - budget)

    active: dict[str, float] = {}
    by_id = {s.security_id: s for s in securities}
    for s in securities:
        if isinstance(s, CommonStock) and s.shares > 0:
            active[s.security_id] = s.shares
        elif isinstance(s, PreferredStock) and s.shares > 0:
            if conversion_state[s.security_id] or s.participating:
                active[s.security_id] = terms[s.security_id].units

    while remaining > 0 and active:
        total_units = math.fsum(active.values())
        for sec_id, units in list(active.items()):
            s = by_id[sec_id]
            if (
                isinstance(s, PreferredStock)
                and not conversion_state[sec_id]
                and s.participating
                and s.participation_cap is not None
            ):
                cap_amount = terms[sec_id].participation_cap_amount
                assert cap_amount is not None  # set whenever participation_cap is
                headroom = max(0.0, cap_amount - payouts[sec_id].amount)
                if remaining * (units / total_units) > headroom:
                    payouts[sec_id].amount += headroom
                    payouts[sec_id].participation_payout += headroom
                    remaining = max(0.0, remaining - headroom)
                    del active[sec_id]
                    break
        else:
            for sec_id, units in active.items():
                amount = remaining * (units / total_units)
                payouts[sec_id].amount += amount
                s = by_id[sec_id]
                if (
                    isinstance(s, PreferredStock)
                    and s.participating
                    and not conversion_state[sec_id]
                ):
                    payouts[sec_id].participation_payout += amount
                else:
                    payouts[sec_id].residual_payout += amount
            remaining = 0.0
    return payouts, remaining


def settle_debt(
    securities: Sequence[Security], net_exit: float, as_of: date | None
) -> tuple[list[DebtSettlement], float]:
    """Pay debt from net proceeds ahead of all equity; return settlements and the residual.

    Debt is paid by ascending debt seniority (0 before 1). Where proceeds do not cover a
    tier's claims they are split pro rata by claim, as within a preferred tier, and every
    later debt tier and all equity receive nothing. Claims are computed on ``as_of``,
    which is required whenever debt is present. With no debt the residual is
    ``net_exit`` itself and ``as_of`` is not read.
    """
    debt = [s for s in securities if isinstance(s, DebtInstrument)]
    if not debt:
        return [], net_exit
    if as_of is None:
        raise ValueError(
            "Debt accrues interest, so an exit holding debt needs an explicit as_of date "
            f"({', '.join(s.security_id for s in debt)}). No implicit clock is used"
        )
    claims = {s.security_id: s.exit_claim(as_of) for s in debt}
    paid: dict[str, float] = {}
    remaining = net_exit
    for level in sorted({s.seniority for s in debt}):
        tier = [claims[s.security_id] for s in debt if s.seniority == level]
        needed = math.fsum(c.claim for c in tier)
        if remaining >= needed:
            for c in tier:
                paid[c.security_id] = c.claim
            remaining -= needed
        else:
            for c in tier:
                paid[c.security_id] = remaining * (c.claim / needed)
            remaining = 0.0
    settlements = [
        DebtSettlement(
            claim=claims[s.security_id],
            paid=paid[s.security_id],
            shortfall=max(0.0, claims[s.security_id].claim - paid[s.security_id]),
        )
        for s in debt
    ]
    return settlements, remaining


def accrue_dividends(securities: Sequence[Security], as_of: date | None) -> list[DividendAccrual]:
    """Trace every preferred dividend term at an exit on ``as_of``.

    A table holding a cumulative dividend needs ``as_of``; without it this raises, even at
    a zero exit, rather than assuming a date. Positions without a dividend are skipped,
    and for a table with no cumulative dividend ``as_of`` is not read.
    """
    accruing = [
        s.security_id
        for s in securities
        if isinstance(s, PreferredStock) and isinstance(s.dividend, CumulativeDividend)
    ]
    if accruing and as_of is None:
        raise ValueError(
            "Cumulative preferred dividends accrue with time, so an exit holding them needs an "
            f"explicit as_of date ({', '.join(accruing)}). No implicit clock is used"
        )
    return [
        accrual
        for s in securities
        if isinstance(s, PreferredStock) and (accrual := s.dividend_accrual(as_of)) is not None
    ]


def _hash_default(value: object) -> str:
    """JSON encoding for the input fingerprint of values plain JSON lacks (debt dates)."""
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot fingerprint {type(value).__name__}")


def solve_waterfall(
    securities: Sequence[Security],
    exit_valuation: float,
    transaction_costs: float = 0.0,
    max_iterations: int = 20,
    *,
    atol: float = 1e-8,
    rtol: float = 1e-12,
    as_of: date | None = None,
    forced_conversions: Collection[str] = (),
) -> WaterfallResult:
    """Return a verified approximate pure equilibrium, or raise.

    No existence, uniqueness or monotonic-convergence theorem is asserted.
    Search order is stable by security ID; ties retain the current decision.

    Debt positions are paid first from net proceeds (see ``settle_debt``) and require
    ``as_of``; the conversion search then runs over the equity residual. A table with
    no debt takes exactly the path it took before debt existed.

    ``forced_conversions`` lists preferred positions converted before the exit by a
    collective decision the caller has already resolved (see ``ovf.governance``). They
    are held converted, are not players and are not checked for deviations. Empty, the
    search and the result are exactly those computed before the parameter existed.
    """
    securities = tuple(securities)
    validate_securities(securities)
    for name, value in {
        "exit_valuation": exit_valuation,
        "transaction_costs": transaction_costs,
        "atol": atol,
        "rtol": rtol,
    }.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or max_iterations < 1
    ):
        raise ValueError("max_iterations must be a positive integer")
    for s in securities:
        if not isinstance(s, (CommonStock, PreferredStock, StockOptionPool, DebtInstrument)):
            raise ValueError(
                f"Unsupported exit instrument {s.security_id}; resolve conversion first"
            )
        if isinstance(s, StockOptionPool) and s.allocated_shares > 0:
            raise ValueError(
                "Allocated options require exercise/settlement terms; model issued shares explicitly"
            )
    forced = forced_conversion_ids(forced_conversions, securities)
    net_exit = max(0.0, exit_valuation - transaction_costs)
    tolerance = atol + rtol * net_exit
    settlements, equity_exit = settle_debt(securities, net_exit, as_of)
    equity = tuple(s for s in securities if not isinstance(s, DebtInstrument))
    dividends = accrue_dividends(equity, as_of)
    preferred = sorted(
        (s for s in equity if isinstance(s, PreferredStock)), key=lambda s: s.security_id
    )
    players = [s for s in preferred if s.security_id not in forced]
    state = {s.security_id: s.security_id in forced for s in preferred}
    seen: set[tuple[bool, ...]] = set()
    iterations = 0
    max_gain = 0.0
    for step in range(1, max_iterations + 1):
        iterations = step
        key = tuple(state.values())
        if key in seen:
            raise WaterfallConvergenceError(
                "Conversion search cycled without a verified equilibrium"
            )
        seen.add(key)
        for s in players:
            current, _ = evaluate_fixed_waterfall(equity, equity_exit, state, as_of=as_of)
            alternative = {**state, s.security_id: not state[s.security_id]}
            counter, _ = evaluate_fixed_waterfall(equity, equity_exit, alternative, as_of=as_of)
            if counter[s.security_id].amount > current[s.security_id].amount + tolerance:
                state = alternative
        final, remaining = evaluate_fixed_waterfall(equity, equity_exit, state, as_of=as_of)
        max_gain = 0.0
        for s in players:
            counter, _ = evaluate_fixed_waterfall(
                equity,
                equity_exit,
                {**state, s.security_id: not state[s.security_id]},
                as_of=as_of,
            )
            max_gain = max(max_gain, counter[s.security_id].amount - final[s.security_id].amount)
        if max_gain <= tolerance:
            break
    else:
        raise WaterfallConvergenceError(
            f"No verified equilibrium after {max_iterations} iterations"
        )

    for d in settlements:
        final[d.claim.security_id] = Payout(
            security_id=d.claim.security_id,
            holder_id=d.claim.holder_id,
            amount=d.paid,
            invested_capital=d.claim.accrual.principal,
        )
    error = math.fsum(final[s.security_id].amount for s in securities) - net_exit
    if remaining > tolerance or abs(error) > tolerance:
        raise ValueError("Exit cannot be fully allocated to supported entitled securities")
    for s in securities:
        p = final[s.security_id]
        p.payout_pct = min(1.0, p.amount / net_exit) if net_exit else 0.0
        p.effective_multiple = p.amount / s.invested_capital if s.invested_capital else None
    payload: dict[str, Any] = {
        "securities": [{"kind": type(s).__name__, **s.model_dump()} for s in securities],
        "exit_valuation": exit_valuation,
        "transaction_costs": transaction_costs,
        "max_iterations": max_iterations,
        "atol": atol,
        "rtol": rtol,
    }
    assumptions = [
        "Each preferred position makes an independent conversion decision.",
        "Reserved unallocated option capacity has no exit payment entitlement.",
        "Single base currency; float accounting within reported tolerance.",
    ]
    if forced:
        payload["forced_conversions"] = sorted(forced)
        assumptions[0] = (
            "Each preferred position not converted before the exit makes an independent "
            "conversion decision."
        )
        assumptions.insert(
            1,
            f"Converted before the exit by a collective decision resolved by the caller, and "
            f"not players: {', '.join(sorted(forced))}. See docs/governance.md.",
        )
    if settlements:
        assert as_of is not None  # settle_debt refuses debt without it
        payload["as_of"] = as_of
        assumptions += _debt_assumptions(securities, as_of)
    else:
        assumptions.append(
            "No debt, unexercised option settlement, SAFE liquidity events or class voting."
        )
    accruing = any(d.kind == "cumulative" for d in dividends)
    if accruing:
        payload["as_of"] = as_of
    if dividends:
        assumptions += _dividend_assumptions(dividends, as_of if accruing else None)
    return WaterfallResult(
        payouts=[final[s.security_id] for s in securities],
        gross_exit=exit_valuation,
        transaction_costs=transaction_costs,
        net_exit=net_exit,
        converged=True,
        iterations=iterations,
        max_unilateral_gain=max_gain,
        tolerance=tolerance,
        conservation_error=error,
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False, default=_hash_default).encode()
        ).hexdigest(),
        multi_position_holders=multi_position_holders(securities),
        assumptions=assumptions,
        as_of=as_of if settlements or accruing else None,
        debt_settlements=settlements,
        dividend_accruals=dividends,
    )


def _debt_assumptions(securities: Sequence[Security], as_of: date) -> list[str]:
    lines = [
        "No unexercised option settlement, SAFE liquidity events or class voting.",
        f"Debt claims accrue to as_of {as_of.isoformat()} under each instrument's stated "
        "day count and accrual method; no clock is read.",
        "Transaction costs are deducted first; debt is then paid ahead of every equity "
        "position, by ascending debt seniority, pro rata by claim within a tier.",
        "Debt amortisation, default interest, prepayment charges and lender warrants are "
        "not modelled.",
    ]
    if any(isinstance(s, ConvertibleNote) for s in securities):
        lines.append(
            "Convertible note exit treatment is stated by the caller; holder elections "
            "between repayment and conversion are not optimised."
        )
    return lines


def _dividend_assumptions(dividends: Sequence[DividendAccrual], as_of: date | None) -> list[str]:
    lines: list[str] = []
    if as_of is not None:
        lines.append(
            "Cumulative preferred dividends accrue from each position's accrues_from date to "
            f"as_of {as_of.isoformat()} under its stated accrual method and day count; no "
            "clock is read."
        )
    settlements = {d.settlement for d in dividends}
    if "forfeit_on_conversion" in settlements:
        lines.append(
            "forfeit_on_conversion: accrued dividends are added once to the liquidation "
            "preference (multiple x Original Issue Price, plus accrued dividends) and are "
            "forfeited if the position converts (NVCA Model COI Oct 2025 s.4.3.3 and fn 46)."
        )
    if "paid_in_kind" in settlements:
        lines.append(
            "paid_in_kind: accrued dividends are paid in additional shares of the same series, "
            "accrued / Original Issue Price, which take the preference, participate and "
            "convert like the others (Spark Therapeutics charter s.1.1); fractional shares "
            "are not cashed out."
        )
    for d in dividends:
        if d.participation_cap_basis == "includes_dividends":
            source = "stated" if d.participation_cap_basis_stated else "default"
            lines.append(
                f"{d.security_id}: the participation cap includes accrued dividends "
                f"({source}; NVCA Model COI fn 20)."
            )
        elif d.participation_cap_basis == "excludes_dividends":
            lines.append(
                f"{d.security_id}: the participation cap excludes accrued dividends, which are "
                "paid on top of it (stated; Virtual Piggy charter s.4.2)."
            )
    non_cumulative = [d.security_id for d in dividends if d.kind == "non_cumulative"]
    if non_cumulative:
        lines.append(
            f"Non-cumulative dividends accrue nothing unless declared ({', '.join(non_cumulative)}"
            "; NVCA Model COI s.1)."
        )
    lines.append("Declared-but-unpaid dividends are not modelled; none is treated as declared.")
    return lines


def multi_position_holders(securities: Sequence[Security]) -> list[str]:
    """Holders owning more than one preferred position.

    Each preferred record is treated as an independent player. Where one holder
    controls several positions it may coordinate them, so the independent-position
    assumption is weakest for exactly these holders. This is a disclosure, not a
    coordinated-holder model.
    """
    seen: dict[str, int] = {}
    for s in securities:
        if isinstance(s, PreferredStock):
            seen[s.holder_id] = seen.get(s.holder_id, 0) + 1
    return sorted(h for h, n in seen.items() if n > 1)


class EquilibriumSurvey(FinancialBaseModel):
    """Every pure conversion equilibrium of one exit, found by exhaustive enumeration."""

    positions: list[str]
    states_evaluated: int
    equilibria: list[dict[str, bool]]
    feasible_equilibria: list[dict[str, bool]]
    feasible_payoffs: list[dict[str, Money]]
    payoff_unique: bool
    distinct_payoff_vectors: int
    tolerance: Money
    net_exit: Money
    forced_conversions: list[str] = Field(
        default_factory=list,
        description="Positions converted before the exit; not players, not in `positions`",
    )

    @model_serializer(mode="wrap")
    def _omit_empty_forced_conversions(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave ``forced_conversions`` out of a dump when it is empty.

        A survey with no forced conversion therefore dumps byte-identically to one made
        before the field existed.
        """
        data = handler(self)
        if not self.forced_conversions and isinstance(data, dict):
            data.pop("forced_conversions", None)
        return data


def enumerate_equilibria(
    securities: Sequence[Security],
    exit_valuation: float,
    transaction_costs: float = 0.0,
    *,
    max_positions: int = 12,
    atol: float = 1e-8,
    rtol: float = 1e-12,
    as_of: date | None = None,
    forced_conversions: Collection[str] = (),
) -> EquilibriumSurvey:
    """Enumerate all 2**n conversion profiles and report every pure equilibrium.

    Exponential in the number of preferred positions and refused above
    ``max_positions``. ``solve_waterfall`` returns one verified equilibrium; this
    function reports whether others exist and whether they pay the same amounts.
    A profile is feasible when it allocates the whole net exit within tolerance.
    Debt is settled first, as in ``solve_waterfall``; its payments are the same in every
    profile and appear in each payoff vector.

    Positions in ``forced_conversions`` are held converted in every profile. They are
    not players: ``n`` counts only the others, and the profiles in the survey name only
    the others.
    """
    securities = tuple(securities)
    validate_securities(securities)
    for name, value in {
        "exit_valuation": exit_valuation,
        "transaction_costs": transaction_costs,
        "atol": atol,
        "rtol": rtol,
    }.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    forced = forced_conversion_ids(forced_conversions, securities)
    preferred = sorted(
        (s for s in securities if isinstance(s, PreferredStock)), key=lambda s: s.security_id
    )
    ids = [s.security_id for s in preferred if s.security_id not in forced]
    forced_state = dict.fromkeys(sorted(forced), True)
    if len(ids) > max_positions:
        raise ValueError(
            f"Exhaustive enumeration needs 2**{len(ids)} evaluations; "
            f"max_positions is {max_positions}"
        )
    net_exit = max(0.0, exit_valuation - transaction_costs)
    tolerance = atol + rtol * net_exit
    settlements, equity_exit = settle_debt(securities, net_exit, as_of)
    equity = tuple(s for s in securities if not isinstance(s, DebtInstrument))
    accrue_dividends(equity, as_of)  # refuses a cumulative dividend without as_of
    debt_paid = {d.claim.security_id: d.paid for d in settlements}

    table: dict[tuple[bool, ...], tuple[dict[str, Payout], float]] = {}
    for bits in itertools.product([False, True], repeat=len(ids)):
        state = dict(zip(ids, bits, strict=True))
        state.update(forced_state)
        table[bits] = evaluate_fixed_waterfall(equity, equity_exit, state, as_of=as_of)

    def amount(bits: tuple[bool, ...], security_id: str) -> float:
        if security_id in debt_paid:
            return debt_paid[security_id]
        return table[bits][0][security_id].amount

    equilibria: list[tuple[bool, ...]] = []
    for bits, (payouts, _) in table.items():
        stable = True
        for index, sec_id in enumerate(ids):
            deviation = tuple(not b if j == index else b for j, b in enumerate(bits))
            if table[deviation][0][sec_id].amount > payouts[sec_id].amount + tolerance:
                stable = False
                break
        if stable:
            equilibria.append(bits)

    feasible = [
        bits
        for bits in equilibria
        if table[bits][1] <= tolerance
        and abs(math.fsum(amount(bits, s.security_id) for s in securities) - net_exit) <= tolerance
    ]
    vectors: list[tuple[float, ...]] = []
    for bits in feasible:
        vector = tuple(amount(bits, s.security_id) for s in securities)
        if not any(
            all(abs(a - b) <= tolerance for a, b in zip(vector, known, strict=True))
            for known in vectors
        ):
            vectors.append(vector)
    return EquilibriumSurvey(
        positions=ids,
        states_evaluated=len(table),
        equilibria=[dict(zip(ids, bits, strict=True)) for bits in equilibria],
        feasible_equilibria=[dict(zip(ids, bits, strict=True)) for bits in feasible],
        feasible_payoffs=[
            {s.security_id: amount(bits, s.security_id) for s in securities} for bits in feasible
        ],
        payoff_unique=len(vectors) <= 1,
        distinct_payoff_vectors=len(vectors),
        tolerance=tolerance,
        net_exit=net_exit,
        forced_conversions=sorted(forced),
    )
