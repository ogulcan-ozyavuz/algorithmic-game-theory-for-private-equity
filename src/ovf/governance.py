"""Collective conversion: a vote that converts preferred positions before an exit.

Of the three governance mechanisms named in the roadmap, only one changes who is paid what
at an exit. It is the mandatory conversion of Preferred Stock on "the date and time, or
upon the occurrence of an event, specified by vote or written consent of the Requisite
Holders" (NVCA Model Certificate of Incorporation, October 2025, s.5.1(b)). The Requisite
Holders are all Preferred Stock "voting together as a single class on an as-converted to
Common Stock basis" (s.2.3.1). It converts every position in its group whether or not that
position's holder agrees. A preference that the individual conversion game would have paid
can therefore disappear. Alta Berkeley VI C.V. v. Omneon, Inc. (Del. 2012) and Greenmont
Capital Partners I, LP v. Mary's Gone Crackers, Inc. (Del. Ch. 2012), both cited in NVCA
fn 64, concern exactly such a conversion immediately before a merger.

Drag-along and protective provisions are not inputs here. Both gate whether a sale
happens, and neither contains a payout formula; docs/governance.md gives the wording that
settles this.

The model has two stages:

1. Holders vote on the conversion. Each holder votes sincerely: it consents if and only if
   its total cash, across every position it holds in the table, is higher by more than
   the waterfall tolerance with the conversion than without it.
2. The per-position conversion game is played over the positions the vote did not
   convert, by ``ovf.waterfall`` with ``forced_conversions``.

Each holder compares the equilibrium payoff of stage 2 with and without the conversion.
That comparison is defined only because the equilibrium payoff is unique. Uniqueness is
verified here by exhaustive enumeration on every call, and a table where it fails is
refused rather than resolved.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from ovf.contracts.securities import PreferredStock, Security
from ovf.core.types import FinancialBaseModel, Money, ShareCount
from ovf.waterfall import (
    EquilibriumSurvey,
    WaterfallResult,
    enumerate_equilibria,
    solve_waterfall,
    validate_securities,
)

ENGINE_VERSION = "governance-v1"

VoteComparison = Literal["at_least", "more_than"]
"""How the consenting weight is compared with ``threshold x total``. Charters use both:
"the holders of at least [60]%" is ``"at_least"``, "a majority" is ``"more_than"`` one half.
The two differ exactly when the vote lands on the threshold, so there is no default."""


class GovernanceIndeterminateError(ValueError):
    """The stated terms and the model do not determine a single outcome."""


class VoteRequirement(FinancialBaseModel):
    """One approval a collective conversion needs: who votes, and how many must consent.

    ``voters`` are preferred ``security_id``s. Each votes its as-converted shares
    (``shares x conversion_ratio``), cast by its holder. ``threshold`` is a fraction of the
    voters' total as-converted shares. It must be stated exactly, as a ``Fraction`` or a
    string such as ``"1/2"`` or ``"0.6"``; a float is refused. ``comparison`` and
    ``threshold`` have no default: the NVCA percentage is a bracketed blank, and whether
    the threshold itself passes depends on the wording.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    voters: tuple[str, ...] = Field(min_length=1)
    threshold: Fraction
    comparison: VoteComparison
    source: str = Field(min_length=1, description="The charter wording this approval follows")

    @field_validator("threshold", mode="before")
    @classmethod
    def _exact_threshold(cls, value: object) -> Fraction:
        if isinstance(value, bool) or not isinstance(value, int | str | Fraction):
            raise ValueError(
                "state the threshold exactly, as a Fraction or a string such as '3/5' or "
                f"'0.6', not {type(value).__name__}: a float cannot hold 60% exactly, and a "
                "vote that lands on the threshold is decided by that difference"
            )
        try:
            threshold = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"threshold {value!r} is not an exact number") from exc
        if not 0 < threshold <= 1:
            raise ValueError(f"threshold must be above 0 and at most 1, got {threshold}")
        return threshold

    @field_serializer("threshold")
    def _threshold_text(self, value: Fraction) -> str:
        return str(value)

    @model_validator(mode="after")
    def _distinct_voters(self) -> Self:
        if len(set(self.voters)) != len(self.voters):
            raise ValueError(f"approval '{self.name}' names a voter twice")
        return self


class CollectiveConversion(FinancialBaseModel):
    """A charter term converting ``converts`` to common when every approval is given.

    NVCA Model COI (October 2025) s.5.1 converts "all outstanding shares of Preferred
    Stock" on the Requisite Holders' vote. There, ``converts`` is every preferred position
    and one approval is the Requisite Holders. NVCA fn 64 advises considering a series vote
    as well; that is a second approval, and all approvals must be given. The term converts
    only. It cannot stop a position from converting, because optional conversion under
    s.4.1.1 stays with each holder.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    converts: tuple[str, ...] = Field(min_length=1)
    approvals: tuple[VoteRequirement, ...] = Field(min_length=1)
    source: str = Field(min_length=1, description="The charter wording this term follows")

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if len(set(self.converts)) != len(self.converts):
            raise ValueError(f"collective conversion '{self.name}' converts a position twice")
        names = [a.name for a in self.approvals]
        if len(set(names)) != len(names):
            raise ValueError(f"collective conversion '{self.name}' repeats an approval name")
        return self


class HolderDecision(FinancialBaseModel):
    """How one voting holder's cash moves with the conversion, and so how it votes."""

    holder_id: str
    security_ids: list[str] = Field(description="Every position the holder has in the table")
    payout_without_conversion: Money
    payout_with_conversion: Money
    change: float
    decision: Literal["consents", "withholds", "indifferent"]


class ApprovalTally(FinancialBaseModel):
    """One approval, counted in as-converted shares by holder."""

    name: str
    threshold: str
    comparison: VoteComparison
    weights: dict[str, ShareCount] = Field(description="Holder to as-converted shares voting")
    total_weight: ShareCount
    consenting_weight: ShareCount
    indifferent_weight: ShareCount
    approved: bool = Field(description="Indifferent holders counted as not consenting")
    approved_if_indifferent_consent: bool


class CollectiveConversionResult(FinancialBaseModel):
    """The vote, both stage-two outcomes, and the one that applies.

    ``result`` is ``with_conversion`` when ``approved``, else ``without_conversion``.
    Both are verified equilibria of their stage-two game, and both surveys show a unique
    equilibrium payoff.
    """

    term: CollectiveConversion
    approved: bool
    changes_payout: bool = Field(description="False when the conversion moves no cash")
    holders: list[HolderDecision]
    tallies: list[ApprovalTally]
    survey_without_conversion: EquilibriumSurvey
    survey_with_conversion: EquilibriumSurvey
    without_conversion: WaterfallResult
    with_conversion: WaterfallResult
    result: WaterfallResult
    tolerance: Money
    input_hash: str
    engine_version: str = ENGINE_VERSION
    assumptions: list[str]


def _passes(consenting: Fraction, total: Fraction, requirement: VoteRequirement) -> bool:
    needed = requirement.threshold * total
    if requirement.comparison == "at_least":
        return consenting >= needed
    return consenting > needed


def resolve_collective_conversion(
    securities: Sequence[Security],
    exit_valuation: float,
    transaction_costs: float = 0.0,
    max_iterations: int = 20,
    *,
    term: CollectiveConversion,
    atol: float = 1e-8,
    rtol: float = 1e-12,
    as_of: date | None = None,
    max_positions: int = 12,
) -> CollectiveConversionResult:
    """Resolve a collective conversion vote at one exit, then the conversion game.

    Arguments other than ``term`` mean what they mean in ``solve_waterfall`` and
    ``enumerate_equilibria``; ``max_positions`` bounds both enumerations.

    Raises ``GovernanceIndeterminateError`` when either stage has more than one
    equilibrium payoff vector, or when holders indifferent within the reported tolerance
    decide the vote and the two outcomes pay differently. Raises ``ValueError`` for a term
    naming positions that are not preferred stock in the table.
    """
    securities = tuple(securities)
    validate_securities(securities)
    if not isinstance(term, CollectiveConversion):
        raise ValueError(f"term must be a CollectiveConversion, got {type(term).__name__}")
    by_id = {s.security_id: s for s in securities}
    preferred = {i for i, s in by_id.items() if isinstance(s, PreferredStock)}
    named = [("converts", i) for i in term.converts] + [
        (f"approval '{a.name}'", i) for a in term.approvals for i in a.voters
    ]
    for role, security_id in named:
        if security_id not in preferred:
            raise ValueError(
                f"{term.name}: {role} names {security_id}, which is not a preferred position "
                "in the table. Only preferred stock converts, and the Requisite Holders vote "
                "only preferred shares"
            )

    options: dict[str, Any] = {"atol": atol, "rtol": rtol, "as_of": as_of}
    surveys: dict[str, EquilibriumSurvey] = {}
    for label, forced in (("without", ()), ("with", term.converts)):
        survey = enumerate_equilibria(
            securities,
            exit_valuation,
            transaction_costs,
            max_positions=max_positions,
            forced_conversions=forced,
            **options,
        )
        if not survey.feasible_equilibria:
            raise ValueError(
                f"{term.name}: no conversion profile {label} the collective conversion "
                "allocates the whole exit"
            )
        if not survey.payoff_unique:
            raise GovernanceIndeterminateError(
                f"{term.name}: {survey.distinct_payoff_vectors} distinct equilibrium payoff "
                f"vectors {label} the collective conversion. Each holder's vote compares "
                "its equilibrium cash with and without the conversion, which is defined only "
                "when that cash is unique"
            )
        surveys[label] = survey
    without = solve_waterfall(
        securities, exit_valuation, transaction_costs, max_iterations, **options
    )
    with_conversion = solve_waterfall(
        securities,
        exit_valuation,
        transaction_costs,
        max_iterations,
        forced_conversions=term.converts,
        **options,
    )
    tolerance = without.tolerance
    paid_without = {p.security_id: p.amount for p in without.payouts}
    paid_with = {p.security_id: p.amount for p in with_conversion.payouts}

    positions_of: dict[str, list[str]] = {}
    for s in securities:
        positions_of.setdefault(s.holder_id, []).append(s.security_id)
    voting_holders = sorted({by_id[i].holder_id for a in term.approvals for i in a.voters})
    holders: list[HolderDecision] = []
    decision_of: dict[str, str] = {}
    for holder in voting_holders:
        ids = positions_of[holder]
        before = math.fsum(paid_without[i] for i in ids)
        after = math.fsum(paid_with[i] for i in ids)
        change = after - before
        decision: Literal["consents", "withholds", "indifferent"]
        if change > tolerance:
            decision = "consents"
        elif change < -tolerance:
            decision = "withholds"
        else:
            decision = "indifferent"
        decision_of[holder] = decision
        holders.append(
            HolderDecision(
                holder_id=holder,
                security_ids=ids,
                payout_without_conversion=before,
                payout_with_conversion=after,
                change=change,
                decision=decision,
            )
        )

    tallies: list[ApprovalTally] = []
    for approval in term.approvals:
        weights: dict[str, Fraction] = {}
        for security_id in approval.voters:
            position = by_id[security_id]
            assert isinstance(position, PreferredStock)  # checked above
            weights[position.holder_id] = weights.get(position.holder_id, Fraction(0)) + (
                Fraction(position.converted_shares)
            )
        total = sum(weights.values(), Fraction(0))
        if total == 0:
            raise ValueError(f"{term.name}: the voters in '{approval.name}' hold no shares")
        consenting = sum(
            (w for h, w in weights.items() if decision_of[h] == "consents"), Fraction(0)
        )
        indifferent = sum(
            (w for h, w in weights.items() if decision_of[h] == "indifferent"), Fraction(0)
        )
        tallies.append(
            ApprovalTally(
                name=approval.name,
                threshold=str(approval.threshold),
                comparison=approval.comparison,
                weights={h: float(w) for h, w in weights.items()},
                total_weight=float(total),
                consenting_weight=float(consenting),
                indifferent_weight=float(indifferent),
                approved=_passes(consenting, total, approval),
                approved_if_indifferent_consent=_passes(consenting + indifferent, total, approval),
            )
        )
    approved = all(t.approved for t in tallies)
    changes_payout = any(abs(paid_with[i] - paid_without[i]) > tolerance for i in by_id)
    if changes_payout and approved != all(t.approved_if_indifferent_consent for t in tallies):
        pivotal = {h.holder_id: h.change for h in holders if h.decision == "indifferent"}
        raise GovernanceIndeterminateError(
            f"{term.name}: holders indifferent within the reported tolerance "
            f"({tolerance:.6g} in base currency) decide the vote: {pivotal}. Counted as not "
            f"consenting, the conversion is {'' if approved else 'not '}approved; counted "
            f"as consenting, it is {'not ' if approved else ''}approved. The two outcomes "
            "pay differently, and neither the charter nor this model says how a holder with "
            "nothing at stake votes"
        )

    payload: dict[str, Any] = {
        "securities": [{"kind": type(s).__name__, **s.model_dump(mode="json")} for s in securities],
        "exit_valuation": exit_valuation,
        "transaction_costs": transaction_costs,
        "max_iterations": max_iterations,
        "atol": atol,
        "rtol": rtol,
        "max_positions": max_positions,
        "collective_conversion": term.model_dump(mode="json"),
    }
    if as_of is not None:
        payload["as_of"] = as_of.isoformat()
    assumptions = [
        f"Collective conversion '{term.name}' of {', '.join(term.converts)}: {term.source}",
        "Two stages: a vote on the conversion, then the per-position conversion game over "
        "the positions not converted.",
        "Sincere voting: each holder consents if and only if its total cash across all its "
        "positions is higher, by more than the tolerance, with the conversion than without. "
        "Coalitions, side payments and strategic votes are not modelled.",
        "Each stage's equilibrium payoff is unique, verified by exhaustive enumeration; the "
        "vote is undefined without that uniqueness.",
        "Vote weight is as-converted shares (shares x conversion ratio), unrounded; every "
        "approval must be given.",
        "A holder votes once, on its total across positions; in the conversion game each "
        "position still decides independently.",
        "Drag-along and protective provisions gate whether a sale happens and move no cash; "
        "they are not inputs.",
    ]
    for t in tallies:
        assumptions.append(
            f"{t.name}: {t.consenting_weight:,.6g} of {t.total_weight:,.6g} as-converted "
            f"votes consent; it needs {t.comparison.replace('_', ' ')} {t.threshold}: "
            f"{'given' if t.approved else 'not given'}."
        )
    return CollectiveConversionResult(
        term=term,
        approved=approved,
        changes_payout=changes_payout,
        holders=holders,
        tallies=tallies,
        survey_without_conversion=surveys["without"],
        survey_with_conversion=surveys["with"],
        without_conversion=without,
        with_conversion=with_conversion,
        result=with_conversion if approved else without,
        tolerance=tolerance,
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        assumptions=assumptions,
    )
