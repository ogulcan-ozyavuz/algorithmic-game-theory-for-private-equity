"""Applying a price-based anti-dilution adjustment to a cap table.

One issuance goes in, together with the charter facts that decide its effect. A new
``CapTable`` comes out, holding the issued securities and a replacement ``PreferredStock``
for every protected position whose conversion price the issuance lowered. The input table
and its securities are never modified.

The conversion price itself is computed by ``ovf.antidilution``. This module decides
which positions it is computed for, against which denominator, and turns each new price
into the ``conversion_ratio`` of a new snapshot.

**Every protected position is adjusted from the same pre-issuance capitalization.** The
NVCA Model Certificate of Incorporation (October 2025, 4.4.4) defines ``CP1`` as the
conversion price "in effect immediately prior to such issuance" and ``A`` as the shares
outstanding "immediately prior to such issuance", counting the common "issuable upon ...
conversion ... of Convertible Securities (including the Preferred Stock) outstanding ...
immediately prior to such issue". An adjustment made "concurrently with such issue" is
not prior to it, so one series' adjustment never enters another series' ``A``. The
adjustments are independent, their order is irrelevant, and there is no fixed point to
solve. ``docs/financing.md`` quotes the text and derives every fixture.

Nothing here reads a clock. Nothing here has a default for a charter fact: which
positions are protected and how, the definition of ``A``, and whether the issuance is an
Exempted Security are all required inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, model_validator

from ovf.antidilution import (
    CapitalizationBeforeIssue,
    ConversionPriceAdjustment,
    DeemedOutstandingDefinition,
    DilutiveIssuance,
    conversion_ratio,
    full_ratchet,
    weighted_average,
)
from ovf.contracts.captable import CapTable
from ovf.contracts.securities import (
    CommonStock,
    PostMoneySAFE,
    PreferredStock,
    PreMoneySAFE,
    Security,
    StockOptionPool,
)
from ovf.core.types import FinancialBaseModel, Money, ShareCount, SharePrice
from ovf.instruments.debt import ConvertibleNote, DebtInstrument

ENGINE_VERSION = "financing-v1"

Outcome = Literal["adjusted", "not_triggered", "exempted", "unprotected"]


class AntiDilutionProtection(FinancialBaseModel):
    """The price-based anti-dilution term one preferred position carries under its charter.

    ``method`` is ``"weighted_average"``, ``"full_ratchet"`` or ``"none"``. A weighted
    average needs the charter's definition of ``A`` (see ``ovf.antidilution``); the other
    two take none. Build one with ``weighted_average_protection(definition)``, or use
    ``FULL_RATCHET`` or ``UNPROTECTED``.
    """

    model_config = ConfigDict(frozen=True)

    method: Literal["weighted_average", "full_ratchet", "none"]
    definition: DeemedOutstandingDefinition | None

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.method == "weighted_average" and self.definition is None:
            raise ValueError(
                "a weighted-average protection needs the charter's definition of A; there "
                "is no default, because broad- and narrow-based differ only in A"
            )
        if self.method != "weighted_average" and self.definition is not None:
            raise ValueError(f"a '{self.method}' protection does not use a definition of A")
        return self


def weighted_average_protection(definition: DeemedOutstandingDefinition) -> AntiDilutionProtection:
    """Weighted-average protection with the charter's stated definition of ``A``."""
    return AntiDilutionProtection(method="weighted_average", definition=definition)


FULL_RATCHET = AntiDilutionProtection(method="full_ratchet", definition=None)
UNPROTECTED = AntiDilutionProtection(method="none", definition=None)


class ExemptionDetermination(FinancialBaseModel):
    """The caller's determination of whether the issuance is an Exempted Security.

    Charters list issuances that never trigger an adjustment: plan grants, acquisition
    consideration, lender and lessor warrants, conversions and others, each bracketed and
    negotiated in the NVCA form. Those lists cannot be enumerated here, so the decision is
    taken from the caller and recorded with its ``basis``. Both fields are required.
    """

    model_config = ConfigDict(frozen=True)

    exempted: StrictBool
    basis: str = Field(min_length=1)


class NewIssue(FinancialBaseModel):
    """Securities issued in one transaction and the consideration the company received.

    ``securities`` are added to the new table. Only common and preferred stock are
    accepted. ``C`` is their common-equivalent count: common shares plus each preferred
    position's shares at its initial conversion ratio, following the NVCA 4.4.3(a) count
    of common "issuable ... without regard to any provision contained therein for a
    subsequent adjustment of such number". ``aggregate_consideration`` is stated by the
    caller and is not inferred from the securities' prices: under NVCA 4.4.5 it is the
    cash received, or the board's fair value of property, which need not equal
    ``shares x price``.
    """

    model_config = ConfigDict(frozen=True)

    securities: tuple[Security, ...]
    aggregate_consideration: Money

    @model_validator(mode="after")
    def validate_securities(self) -> Self:
        if not self.securities:
            raise ValueError("an issuance must contain at least one security")
        ids: set[str] = set()
        for s in self.securities:
            if isinstance(s, StockOptionPool):
                raise ValueError(
                    f"{s.security_id}: an option pool reserve is not an issuance of shares. "
                    "Model a pool change as its own snapshot, placed before or after this "
                    "issuance as the financing documents require"
                )
            if not isinstance(s, CommonStock | PreferredStock):
                raise ValueError(
                    f"{s.security_id}: only common and preferred stock can be issued here; "
                    f"{type(s).__name__} needs the deemed-issuance and consideration rules of "
                    "NVCA 4.4.3 and 4.4.5, which are not modelled"
                )
            if s.security_id in ids:
                raise ValueError(f"Duplicate security_id in issuance: {s.security_id}")
            ids.add(s.security_id)
        if self.common_equivalent_shares <= 0:
            raise ValueError("an issuance must issue a positive number of shares")
        return self

    @property
    def common_equivalent_shares(self) -> ShareCount:
        """``C``: issued common plus issued preferred at its initial conversion ratio."""
        return math.fsum(
            s.converted_shares if isinstance(s, PreferredStock) else s.shares
            for s in self.securities
        )

    def dilutive_issuance(self) -> DilutiveIssuance:
        """The ``C`` and consideration that ``ovf.antidilution`` takes."""
        return DilutiveIssuance(
            shares_issued=self.common_equivalent_shares,
            aggregate_consideration=self.aggregate_consideration,
        )


class PositionAdjustment(FinancialBaseModel):
    """What one issuance did to one preferred position, with the numbers behind it.

    ``outcome`` is ``"adjusted"`` (the price fell), ``"not_triggered"`` (the issue price
    was not below ``CP1``), ``"exempted"`` (the caller determined the issuance exempt) or
    ``"unprotected"`` (the caller stated no protection). ``adjustment`` is the
    ``ovf.antidilution`` result, and is ``None`` for the last two. ``position_after`` is
    the input object itself unless the outcome is ``"adjusted"``.
    """

    model_config = ConfigDict(frozen=True)

    security_id: str
    holder_id: str
    protection: Literal["weighted_average", "full_ratchet", "none"]
    outcome: Outcome
    original_issue_price: SharePrice
    conversion_price_before: SharePrice
    conversion_price_after: SharePrice
    conversion_ratio_before: float = Field(gt=0.0)
    conversion_ratio_after: float = Field(gt=0.0)
    converted_shares_before: ShareCount
    converted_shares_after: ShareCount
    adjustment: ConversionPriceAdjustment | None
    position_after: PreferredStock


class FinancingResult(FinancialBaseModel):
    """A new cap table after one issuance, with the trace that produced it."""

    table: CapTable
    capitalization: CapitalizationBeforeIssue
    issuance: DilutiveIssuance
    exemption: ExemptionDetermination
    positions: list[PositionAdjustment]
    issued_security_ids: list[str]
    input_hash: str
    engine_version: str = ENGINE_VERSION
    assumptions: list[str]

    def position(self, security_id: str) -> PositionAdjustment:
        """The adjustment record of one pre-existing preferred position."""
        for p in self.positions:
            if p.security_id == security_id:
                return p
        raise KeyError(security_id)


def capitalization_before_issue(table: CapTable) -> CapitalizationBeforeIssue:
    """The five components of ``A``, counted from a table immediately prior to an issuance.

    - common: every ``CommonStock`` position's shares;
    - preferred as converted: every ``PreferredStock`` at its current ratio;
    - options and warrants: a pool's ``allocated_shares`` (granted options);
    - other convertibles: zero, because the convertibles that could fill it are refused;
    - reserve: a pool's unallocated capacity.

    Debt that cannot convert holds no shares and counts nothing. A table holding a SAFE or
    a convertible note is refused: the common issuable on its conversion is not
    determined before the priced round that converts it (the final paragraph of NVCA
    4.4.3 deems a security with "a cap on the valuation of the Corporation" not
    calculable), so it cannot be counted in ``A``.
    """
    if not isinstance(table, CapTable):
        raise ValueError(f"table must be a CapTable, got {type(table).__name__}")
    common: list[float] = []
    preferred: list[float] = []
    options: list[float] = []
    reserve: list[float] = []
    for s in table.securities:
        if isinstance(s, PostMoneySAFE | PreMoneySAFE | ConvertibleNote):
            raise ValueError(
                f"{s.security_id}: a {type(s).__name__} is a Convertible Security whose "
                "common issuable on conversion is not determined, so A cannot be counted. "
                "Resolve its conversion into a new snapshot first"
            )
        if isinstance(s, CommonStock):
            common.append(s.shares)
        elif isinstance(s, PreferredStock):
            preferred.append(s.converted_shares)
        elif isinstance(s, StockOptionPool):
            options.append(s.allocated_shares)
            reserve.append(s.unallocated_shares)
        elif not isinstance(s, DebtInstrument):
            raise ValueError(
                f"{s.security_id}: {type(s).__name__} has no defined place in the "
                "deemed-outstanding count"
            )
    return CapitalizationBeforeIssue(
        common_outstanding=math.fsum(common),
        preferred_as_converted=math.fsum(preferred),
        options_and_warrants_as_exercised=math.fsum(options),
        other_convertibles_as_converted=0.0,
        reserved_unissued_pool=math.fsum(reserve),
    )


def adjust_position(
    position: PreferredStock,
    *,
    protection: AntiDilutionProtection,
    capitalization: CapitalizationBeforeIssue,
    issuance: DilutiveIssuance,
    exemption: ExemptionDetermination,
) -> PositionAdjustment:
    """Apply one issuance to one preferred position.

    ``capitalization`` must be the table immediately prior to the issuance. The result
    depends on this position and on the four stated inputs only; nothing about any other
    position's adjustment enters it. That is the whole reason several series can be
    adjusted in any order.

    The Original Issue Price is ``position.price``, the same figure the waterfall uses as
    the preference basis. The conversion price in effect is recovered from the NVCA 4.1.1
    ratio, ``ratio = OIP / CP``, as ``CP1 = OIP / conversion_ratio``. An adjusted
    position is replaced by a new ``PreferredStock`` whose only changed field is
    ``conversion_ratio = OIP / CP2``.
    """
    if not isinstance(position, PreferredStock):
        raise ValueError(f"position must be a PreferredStock, got {type(position).__name__}")
    for name, value, expected in (
        ("protection", protection, AntiDilutionProtection),
        ("capitalization", capitalization, CapitalizationBeforeIssue),
        ("issuance", issuance, DilutiveIssuance),
        ("exemption", exemption, ExemptionDetermination),
    ):
        if not isinstance(value, expected):
            raise ValueError(f"{name} must be a {expected.__name__}, got {type(value).__name__}")
    oip = position.price
    ratio_before = position.conversion_ratio
    cp1 = oip / ratio_before
    if protection.method != "none" and not oip > 0:
        raise ValueError(
            f"{position.security_id}: protected preferred needs a positive Original Issue "
            f"Price (price is {oip}); its conversion price OIP / ratio is undefined"
        )

    adjustment: ConversionPriceAdjustment | None = None
    outcome: Outcome
    if protection.method == "none":
        outcome = "unprotected"
    elif exemption.exempted:
        outcome = "exempted"
    else:
        try:
            if protection.method == "full_ratchet":
                adjustment = full_ratchet(conversion_price=cp1, issuance=issuance)
            else:
                assert protection.definition is not None  # enforced by the validator
                adjustment = weighted_average(
                    conversion_price=cp1,
                    capitalization=capitalization,
                    definition=protection.definition,
                    issuance=issuance,
                )
        except ValueError as exc:
            raise ValueError(f"{position.security_id}: {exc}") from exc
        moved = adjustment.triggered and adjustment.conversion_price_after < cp1
        outcome = "adjusted" if moved else "not_triggered"

    after = position
    cp2 = cp1
    if outcome == "adjusted":
        assert adjustment is not None
        cp2 = adjustment.conversion_price_after
        ratio = conversion_ratio(original_issue_price=oip, conversion_price=cp2)
        after = type(position).model_validate({**position.model_dump(), "conversion_ratio": ratio})
    return PositionAdjustment(
        security_id=position.security_id,
        holder_id=position.holder_id,
        protection=protection.method,
        outcome=outcome,
        original_issue_price=oip,
        conversion_price_before=cp1,
        conversion_price_after=cp2,
        conversion_ratio_before=ratio_before,
        conversion_ratio_after=after.conversion_ratio,
        converted_shares_before=position.converted_shares,
        converted_shares_after=after.converted_shares,
        adjustment=adjustment,
        position_after=after,
    )


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot fingerprint {type(value).__name__}")


def _dump(security: Security) -> dict[str, Any]:
    return {"kind": type(security).__name__, **security.model_dump()}


def apply_dilutive_issuance(
    table: CapTable,
    *,
    issue: NewIssue,
    protection: Mapping[str, AntiDilutionProtection],
    exemption: ExemptionDetermination,
) -> FinancingResult:
    """Issue ``issue`` against ``table`` and apply each position's anti-dilution term.

    ``protection`` must name every preferred position in ``table`` by ``security_id``,
    each with its charter term; pass ``UNPROTECTED`` for a position that has none. A
    missing or unknown key is refused, so no position is adjusted, or left alone, by
    omission. ``exemption`` is the caller's determination of whether the issuance is an
    Exempted Security; an exempted issuance adjusts nothing.

    All positions are adjusted from one ``capitalization_before_issue(table)``, the
    capitalization immediately prior to the issuance (NVCA 4.4.4, definitions of ``CP1``
    and ``A``). Returns a new table: the input positions in their input order, each
    adjusted one replaced, followed by ``issue.securities``.
    """
    if not isinstance(issue, NewIssue):
        raise ValueError(f"issue must be a NewIssue, got {type(issue).__name__}")
    if not isinstance(exemption, ExemptionDetermination):
        raise ValueError(
            f"exemption must be an ExemptionDetermination, got {type(exemption).__name__}"
        )
    if not isinstance(protection, Mapping):
        raise ValueError(f"protection must be a mapping, got {type(protection).__name__}")
    capitalization = capitalization_before_issue(table)
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
    issuance = issue.dilutive_issuance()

    positions: list[PositionAdjustment] = []
    after: list[Security] = []
    for s in table.securities:
        if isinstance(s, PreferredStock):
            record = adjust_position(
                s,
                protection=protection[s.security_id],
                capitalization=capitalization,
                issuance=issuance,
                exemption=exemption,
            )
            positions.append(record)
            after.append(record.position_after)
        else:
            after.append(s)
    new_table = CapTable(securities=[*after, *issue.securities])

    payload: dict[str, Any] = {
        "table": [_dump(s) for s in table.securities],
        "issue": {
            "securities": [_dump(s) for s in issue.securities],
            "aggregate_consideration": issue.aggregate_consideration,
        },
        "protection": {k: protection[k].model_dump() for k in sorted(protection)},
        "exemption": exemption.model_dump(),
    }
    return FinancingResult(
        table=new_table,
        capitalization=capitalization,
        issuance=issuance,
        exemption=exemption,
        positions=positions,
        issued_security_ids=[s.security_id for s in issue.securities],
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False, default=_json_default).encode()
        ).hexdigest(),
        assumptions=_assumptions(exemption),
    )


def _assumptions(exemption: ExemptionDetermination) -> list[str]:
    status = "exempted" if exemption.exempted else "not exempted"
    return [
        "CP1, A and the trigger are taken immediately prior to the issuance (NVCA Model "
        "COI Oct 2025, 4.4.4): every protected position is adjusted from the same "
        "pre-issuance capitalization, so the adjustments are independent of one another "
        "and of the order in which they are applied.",
        f"The issuance is {status} as an Exempted Security by the caller's determination: "
        f"{exemption.basis}",
        "Original Issue Price is PreferredStock.price; the conversion price in effect is "
        "price / conversion_ratio (NVCA 4.1.1: ratio = Original Issue Price / Conversion "
        "Price).",
        "C counts issued common plus issued preferred at its initial conversion ratio "
        "(NVCA 4.4.3(a)); aggregate consideration is as stated, not computed under 4.4.5.",
        "A counts pool allocated shares as Options outstanding and unallocated capacity "
        "as the reserve; which of them enters A is each protection's stated definition.",
        "Only conversion ratios change. Preference, seniority, participation and every "
        "other term are carried over unchanged; pay-to-play, waivers, board and "
        "protective-provision changes are not applied.",
        "CP2 is unrounded; the NVCA form rounds it to the nearest one-hundredth of a cent.",
    ]
