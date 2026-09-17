"""Capped SAFE conversion for a common-only starting cap table and a new option pool.

All rounds use pre-money + new cash = post-money, with converting SAFEs and
pool included in the negotiated pre-money. This is one explicit pricing convention,
not an implementation of all three Cooley financing conventions.

The second half of this module adds the YC post-money Discount Only and MFN Only forms
and the MFN amendment. Those instruments are converted by ``ovf.rounds``, which prices a
round over an existing cap table under any of the three Cooley conventions;
``solve_priced_round_with_safes`` accepts exactly what it accepted before and returns the
same numbers. See docs/rounds.md.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from ovf.contracts.captable import CapTable
from ovf.contracts.securities import (
    PostMoneySAFE,
    PreferredStock,
    PreMoneySAFE,
    Security,
    common,
    option_pool,
    preferred,
)
from ovf.core.types import FinancialBaseModel, Money, Percentage, ShareCount, SharePrice


class SafeConversionResult(FinancialBaseModel):
    method: str
    share_price: SharePrice
    prior_common_shares: ShareCount
    pre_money_valuation: Money
    post_money_valuation: Money
    new_money_invested: Money
    new_preferred_shares: ShareCount
    new_option_pool_shares: ShareCount
    total_post_shares: ShareCount
    safe_shares: dict[str, ShareCount]
    safe_conversion_prices: dict[str, SharePrice]
    ownership_breakdown: dict[str, Percentage]
    converted_safes: list[PreferredStock]
    converged: bool = True
    iterations: int = Field(ge=1)
    share_balance_error: float
    input_hash: str
    engine_version: str = "safe-round-v2"
    assumptions: list[str]

    def to_cap_table(self) -> CapTable:
        """Explicit post-round snapshot: 1x, nonparticipating, pari-passu preferred.

        Prior common is grouped as 'founders' with unknown cost basis (price=0).
        Option capacity is entirely unallocated. Other negotiated rights require
        explicit PreferredStock objects instead of this convenience snapshot.
        """
        table = CapTable().add(
            common(self.prior_common_shares, price=0, security_id="round:common")
        )
        for position in self.converted_safes:
            table.add(position)
        if self.new_preferred_shares:
            table.add(
                preferred(
                    self.new_preferred_shares,
                    self.share_price,
                    holder_id="new_preferred",
                    security_id="round:new",
                )
            )
        if self.new_option_pool_shares:
            table.add(
                option_pool(
                    self.new_option_pool_shares, holder_id="option_pool", security_id="round:pool"
                )
            )
        return table


def solve_priced_round_with_safes(
    prior_common_shares: float,
    new_money: float,
    pre_money_valuation: float,
    target_pool_pct: float = 0.10,
    safes: Sequence[PostMoneySAFE | PreMoneySAFE] | None = None,
    method: Literal["post_money_yc", "pre_money"] = "post_money_yc",
) -> SafeConversionResult:
    """Solve one homogeneous capped-SAFE round; see docs/semantics.md for equations.

    No existing preferred, options/pool, notes, MFN or pro-rata reinvestment are
    modeled. Mixed pre/post-money instruments are rejected. Nonzero discounts on
    post-money capped SAFEs model a custom best-of-cap-and-discount contract,
    not YC's separate discount-only form. target_pool_pct is a post-round fraction.
    """
    for name, value in {
        "prior_common_shares": prior_common_shares,
        "new_money": new_money,
        "pre_money_valuation": pre_money_valuation,
        "target_pool_pct": target_pool_pct,
    }.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if prior_common_shares <= 0 or pre_money_valuation <= 0:
        raise ValueError("prior_common_shares and pre_money_valuation must be positive")
    if target_pool_pct >= 1:
        raise ValueError("target_pool_pct must be less than one")
    if method not in ("post_money_yc", "pre_money"):
        raise ValueError(f"Unknown SAFE conversion method: {method}")
    instruments = tuple(safes or ())
    expected_type = PostMoneySAFE if method == "post_money_yc" else PreMoneySAFE
    ids: set[str] = {"round:common", "round:new", "round:pool"}
    for s in instruments:
        if not isinstance(s, expected_type):
            raise ValueError("Mixed SAFE types or method/type mismatch are unsupported")
        if s.security_id in ids:
            raise ValueError(f"Duplicate or reserved security_id: {s.security_id}")
        ids.add(s.security_id)
    post = pre_money_valuation + new_money
    if not math.isfinite(post):
        raise ValueError("Combined valuation exceeds the finite numeric range")
    new_pct = new_money / post
    available = 1.0 - new_pct - target_pool_pct
    if available <= 0:
        raise ValueError(
            "Dilution exceeds feasible ownership: round and pool leave no prior equity"
        )

    iterations = 1
    if method == "post_money_yc":
        # B = prior common + converted SAFEs, excluding the new pool and new money.
        # P*B = post*(1 - new_pct - pool_pct). Each SAFE chooses the lower price.
        fractions = {
            s.security_id: s.investment_amount
            / min(s.valuation_cap, post * available * (1 - s.discount_rate))
            for s in instruments
        }
        total_safe_fraction = math.fsum(fractions.values())
        if total_safe_fraction >= 1:
            raise ValueError(
                "Dilution exceeds feasible ownership: converting SAFEs consume all prior equity"
            )
        founder_pct = (1.0 - total_safe_fraction) * available
        total = prior_common_shares / founder_pct
        base = total * available
        safe_shares = {s.security_id: base * fractions[s.security_id] for s in instruments}
    else:
        # u = P*C/post (founder fraction). Pre-money cap denominator includes C+pool.
        # u + sum(max(I/cap*(u+pool), I/post/(1-discount))) = available.
        def balance(u: float) -> float:
            return (
                u
                + math.fsum(
                    max(
                        s.investment_amount / s.valuation_cap * (u + target_pool_pct),
                        s.investment_amount / post / (1 - s.discount_rate),
                    )
                    for s in instruments
                )
                - available
            )

        if balance(0) >= 0:
            raise ValueError(
                "Dilution exceeds feasible ownership: no positive founder share remains"
            )
        lower, upper = 0.0, available
        for step in range(1, 201):
            iterations = step
            middle = (lower + upper) / 2
            if balance(middle) > 0:
                upper = middle
            else:
                lower = middle
            if upper - lower <= 1e-13 * max(middle, 1e-15):
                break
        else:
            raise RuntimeError("Pre-money SAFE price solver did not converge")
        founder_pct = (lower + upper) / 2
        total = prior_common_shares / founder_pct
        price = post / total
        pool = target_pool_pct * total
        safe_shares = {
            s.security_id: s.investment_amount
            / min(s.valuation_cap / (prior_common_shares + pool), price * (1 - s.discount_rate))
            for s in instruments
        }

    price = post / total
    if not math.isfinite(total) or not math.isfinite(price) or price <= 0:
        raise ValueError("Round lies outside the supported finite numeric range")
    new_shares, pool = total * new_pct, total * target_pool_pct
    error = math.fsum([prior_common_shares, new_shares, pool, *safe_shares.values()]) - total
    if abs(error) > max(1e-8, total * 1e-10):
        raise RuntimeError("SAFE solution failed share conservation")
    ownership = {"founders": founder_pct, "new_preferred": new_pct, "option_pool": target_pool_pct}
    prices = {}
    converted = []
    for s in instruments:
        ownership[s.holder_id] = (
            ownership.get(s.holder_id, 0.0) + safe_shares[s.security_id] / total
        )
        prices[s.security_id] = s.investment_amount / safe_shares[s.security_id]
        converted.append(
            preferred(
                safe_shares[s.security_id],
                prices[s.security_id],
                holder_id=s.holder_id,
                security_id=s.security_id,
            )
        )
    payload = {
        "method": method,
        "prior_common_shares": prior_common_shares,
        "new_money": new_money,
        "pre_money_valuation": pre_money_valuation,
        "target_pool_pct": target_pool_pct,
        "safes": [s.model_dump() for s in instruments],
    }
    return SafeConversionResult(
        method=method,
        share_price=price,
        prior_common_shares=prior_common_shares,
        pre_money_valuation=pre_money_valuation,
        post_money_valuation=post,
        new_money_invested=new_money,
        new_preferred_shares=new_shares,
        new_option_pool_shares=pool,
        total_post_shares=total,
        safe_shares=safe_shares,
        safe_conversion_prices=prices,
        ownership_breakdown=ownership,
        converted_safes=converted,
        iterations=iterations,
        share_balance_error=error,
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        assumptions=[
            "Prior capitalization is common only; no existing pool, options or preferred.",
            "Negotiated pre-money includes converted SAFEs and the new option pool.",
            "Post-money SAFE cap excludes new money and the new pool; pre-money cap includes the pool.",
            "New pool is entirely unallocated; no pro-rata reinvestment, MFN or convertible notes.",
            "Nonzero post-money discounts represent a custom capped-plus-discount variant.",
            "to_cap_table uses 1x nonparticipating pari-passu preferred and no founder cost basis.",
        ],
    )


# ---------------------------------------------------------------------------
# The other YC post-money forms, and the MFN amendment (docs/rounds.md)
#
# Forms read: "Postmoney Safe - Discount Only" and "Postmoney Safe - MFN Only", both from
# https://www.ycombinator.com/documents, together with the Post-Money Safe User Guide.
# ``solve_priced_round_with_safes`` does not accept these instruments; ``ovf.rounds`` does.
# ---------------------------------------------------------------------------


class PostMoneyDiscountSAFE(Security):
    """YC Postmoney Safe - Discount Only: a discount and no valuation cap.

    Section 1(a): the Safe converts "into the number of shares of Safe Preferred Stock equal
    to the Purchase Amount divided by the Discount Price", where "'Discount Price' means the
    lowest price per share of the Standard Preferred Stock sold in the Equity Financing
    multiplied by the Discount Rate", and the form states the Discount Rate as "[100 minus
    the discount]%". ``discount`` is the discount itself (0.20 for 20%), so YC's Discount
    Rate is ``1 - discount``; ``PostMoneySAFE.discount_rate`` holds the same quantity as
    ``discount``, not YC's Discount Rate.

    No Company Capitalization enters its own conversion. It is still one of the "other
    Safes" in a capped post-money Safe's Converting Securities, so its conversion shares
    count in that Safe's Company Capitalization.
    """

    investment_amount: Money = Field(..., gt=0, description="Purchase Amount")
    discount: float = Field(
        ..., gt=0, lt=1, description="Discount off the round price; YC Discount Rate = 1 - it"
    )

    @property
    def invested_capital(self) -> Money:
        return self.investment_amount

    def is_convertible(self) -> bool:
        return True

    def base_liquidation_preference(self) -> Money:
        return self.investment_amount


class PostMoneyMFNSAFE(Security):
    """YC Postmoney Safe - MFN Only: no valuation cap, no discount, and an MFN amendment right.

    Unamended, Section 1(a) converts it "into the number of shares of Standard Preferred
    Stock equal to the Purchase Amount divided by the lowest price per share of the Standard
    Preferred Stock", which is the new-money price. Section 3 lets its holder have it amended
    to be identical to a later Safe; ``resolve_mfn`` applies that amendment.
    """

    investment_amount: Money = Field(..., gt=0, description="Purchase Amount")

    @property
    def invested_capital(self) -> Money:
        return self.investment_amount

    def is_convertible(self) -> bool:
        return True

    def base_liquidation_preference(self) -> Money:
        return self.investment_amount


SafeInstrument = PostMoneySAFE | PreMoneySAFE | PostMoneyDiscountSAFE | PostMoneyMFNSAFE
"""Every SAFE form ``ovf.rounds`` converts."""

_SAFE_TYPES = (PostMoneySAFE, PreMoneySAFE, PostMoneyDiscountSAFE, PostMoneyMFNSAFE)


def safe_post_discount(
    amount: float, discount: float, *, holder_id: str, security_id: str
) -> PostMoneyDiscountSAFE:
    """A YC post-money Discount Only Safe. ``discount`` is 0.20 for a 20% discount."""
    return PostMoneyDiscountSAFE(
        security_id=security_id,
        holder_id=holder_id,
        investment_amount=float(amount),
        discount=float(discount),
    )


def safe_post_mfn(amount: float, *, holder_id: str, security_id: str) -> PostMoneyMFNSAFE:
    """A YC post-money MFN Only Safe."""
    return PostMoneyMFNSAFE(
        security_id=security_id, holder_id=holder_id, investment_amount=float(amount)
    )


class MFNResolution(FinancialBaseModel):
    """The facts an MFN amendment turns on: the order of issue and the holders' elections.

    ``issue_order`` lists the ``security_id`` of every Safe converting in the round, earliest
    first. A cap table records no issue dates, so the order is stated rather than inferred.
    ``elections`` names every MFN Only Safe, mapped to the ``security_id`` of the later Safe
    its holder elected to adopt, or to ``None`` if it made no election.

    Neither field has a default. Section 3 amends the Safe only after "the Investor
    determines that the terms of the Subsequent Convertible Securities are preferable" and
    notifies the Company "within 10 days of the receipt of the MFN Notice". Whether a cap or
    a discount is preferable depends on a round that has not happened yet (docs/rounds.md,
    MF fixtures), so the election is a recorded fact, not something computed here.
    """

    model_config = ConfigDict(frozen=True)

    issue_order: tuple[str, ...]
    elections: dict[str, str | None]

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if not self.issue_order:
            raise ValueError("issue_order must list every Safe converting in the round")
        if len(set(self.issue_order)) != len(self.issue_order):
            raise ValueError("issue_order lists a Safe more than once")
        return self


class MFNAmendment(FinancialBaseModel):
    """One MFN Only Safe after resolution: ``after`` is ``before`` unless it elected a Safe."""

    model_config = ConfigDict(frozen=True)

    security_id: str
    holder_id: str
    elected_security_id: str | None
    before: PostMoneyMFNSAFE
    after: SafeInstrument


def resolve_mfn(
    safes: Sequence[SafeInstrument], resolution: MFNResolution
) -> tuple[list[SafeInstrument], list[MFNAmendment]]:
    """Rewrite every MFN Only Safe that elected a later Safe, before anything converts.

    Section 3 ("MFN" Amendment Provision) of the YC MFN Only form, verbatim: "If the Company
    issues any Subsequent Convertible Securities with terms more favorable than those of this
    Safe (including, without limitation, a valuation cap and/or discount) prior to
    termination of this Safe, ... the Company agrees to amend and restate this instrument to
    be identical to the instrument(s) evidencing the Subsequent Convertible Securities."

    So the amended Safe is a copy of ONE later instrument, cap and discount together, keeping
    only its own Purchase Amount, holder and identity. The User Guide (Appendix I): "the MFN
    Provision does not permit the 'cherry-picking' of terms ... the amended safe will be
    identical to the later safe (other than the Purchase Amount)", and "the MFN of the safe
    is amended away once the safe holder decides the MFN is triggered".

    Refused: an election of a Safe issued at or before the MFN Safe; of an MFN Only Safe,
    whose terms (no cap, no discount) are not more favourable; of an id that is not a Safe in
    the round; an ``issue_order`` that does not list every Safe exactly once; and
    ``elections`` that do not name exactly the MFN Only Safes. Returns the Safes in their
    input order and one ``MFNAmendment`` per MFN Only Safe.
    """
    if not isinstance(resolution, MFNResolution):
        raise ValueError(f"resolution must be an MFNResolution, got {type(resolution).__name__}")
    by_id: dict[str, SafeInstrument] = {}
    for s in safes:
        if not isinstance(s, _SAFE_TYPES):
            raise ValueError(f"{getattr(s, 'security_id', s)!r} is not a Safe form")
        if s.security_id in by_id:
            raise ValueError(f"Duplicate Safe security_id: {s.security_id}")
        by_id[s.security_id] = s
    if set(resolution.issue_order) != set(by_id):
        missing = sorted(set(by_id) - set(resolution.issue_order))
        unknown = sorted(set(resolution.issue_order) - set(by_id))
        raise ValueError(
            "issue_order must list every Safe in the round exactly once; "
            f"missing: {missing}, not a Safe in the round: {unknown}"
        )
    position = {security_id: i for i, security_id in enumerate(resolution.issue_order)}
    mfn_ids = {s.security_id for s in safes if isinstance(s, PostMoneyMFNSAFE)}
    if set(resolution.elections) != mfn_ids:
        raise ValueError(
            "elections must name every MFN Only Safe and nothing else; MFN Only Safes: "
            f"{sorted(mfn_ids)}, named: {sorted(resolution.elections)}. Map a Safe whose "
            "holder made no election to None"
        )

    resolved: list[SafeInstrument] = []
    amendments: list[MFNAmendment] = []
    for s in safes:
        if not isinstance(s, PostMoneyMFNSAFE):
            resolved.append(s)
            continue
        elected_id = resolution.elections[s.security_id]
        after: SafeInstrument = s
        if elected_id is not None:
            elected = by_id.get(elected_id)
            if elected is None:
                raise ValueError(
                    f"{s.security_id}: elected {elected_id!r}, not a Safe in the round"
                )
            if position[elected_id] <= position[s.security_id]:
                raise ValueError(
                    f"{s.security_id}: elected {elected_id}, which was not issued after it. "
                    "Section 3 reaches only Subsequent Convertible Securities, issued 'after "
                    "the issuance of this instrument'"
                )
            if isinstance(elected, PostMoneyMFNSAFE):
                raise ValueError(
                    f"{s.security_id}: elected {elected_id}, another MFN Only Safe. Its terms "
                    "(no cap, no discount) are not more favorable, so Section 3 does not apply"
                )
            data = {
                **elected.model_dump(),
                "security_id": s.security_id,
                "holder_id": s.holder_id,
                "investment_amount": s.investment_amount,
            }
            after = type(elected).model_validate(data)
        resolved.append(after)
        amendments.append(
            MFNAmendment(
                security_id=s.security_id,
                holder_id=s.holder_id,
                elected_security_id=elected_id,
                before=s,
                after=after,
            )
        )
    return resolved, amendments


def mfn_resolution(
    *, issue_order: Sequence[str], elections: Mapping[str, str | None]
) -> MFNResolution:
    """Build an ``MFNResolution``. Both arguments are required."""
    return MFNResolution(issue_order=tuple(issue_order), elections=dict(elections))
