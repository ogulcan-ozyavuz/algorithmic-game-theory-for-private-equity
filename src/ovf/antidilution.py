"""Price-based anti-dilution: the conversion-price adjustment for one dilutive issuance.

Pure functions over stated numbers. Nothing here reads or mutates a ``CapTable`` or a
``Security``: the caller states every share count, receives a new conversion price, and
turns it into the ``PreferredStock.conversion_ratio`` of a new snapshot with
``conversion_ratio``.

Formula text is taken from the NVCA Model Certificate of Incorporation, Subsection 4.4.4
(broad-based weighted-average and full-ratchet alternatives), read in its June 2019 and
October 2025 versions. Derivations, sources and what is not modelled are in
``docs/antidilution.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictBool

from ovf.core.types import FinancialBaseModel, Money, ShareCount, SharePrice

ENGINE_VERSION = "antidilution-v1"


class CapitalizationBeforeIssue(FinancialBaseModel):
    """Common-equivalent share counts immediately prior to the dilutive issuance.

    Every field is required and has no default. Which fields count toward ``A`` is the
    charter's definition of "deemed outstanding", stated separately as a
    ``DeemedOutstandingDefinition``; a zero here says a component is empty, not that it
    was forgotten. Convertible and exercisable positions are counted as-converted or
    as-exercised at the ratios in effect before this issuance, and the protected series
    is itself part of ``preferred_as_converted``.

    Component boundaries follow the NVCA definitions. "Options" are rights, options or
    warrants to acquire common stock or convertible securities. "Convertible Securities"
    are other securities convertible into common stock, excluding Options; preferred
    stock is split out of them here because narrow-based definitions treat it
    differently. ``reserved_unissued_pool`` is plan capacity not yet granted, which is
    not an Option outstanding.
    """

    model_config = ConfigDict(frozen=True)

    common_outstanding: ShareCount
    preferred_as_converted: ShareCount
    options_and_warrants_as_exercised: ShareCount
    other_convertibles_as_converted: ShareCount
    reserved_unissued_pool: ShareCount


class DeemedOutstandingDefinition(FinancialBaseModel):
    """Which capitalization components the charter deems outstanding in ``A``.

    Every flag is required. The named compositions in this module are documented
    conveniences, not defaults; a charter that reads differently needs its own
    instance. ``source`` records where the composition comes from and how far that
    source was verified.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    include_common: StrictBool
    include_preferred_as_converted: StrictBool
    include_options_and_warrants: StrictBool
    include_other_convertibles: StrictBool
    include_reserved_pool: StrictBool

    def included(self) -> dict[str, bool]:
        """Map each ``CapitalizationBeforeIssue`` field to whether ``A`` counts it."""
        return {
            "common_outstanding": self.include_common,
            "preferred_as_converted": self.include_preferred_as_converted,
            "options_and_warrants_as_exercised": self.include_options_and_warrants,
            "other_convertibles_as_converted": self.include_other_convertibles,
            "reserved_unissued_pool": self.include_reserved_pool,
        }


BROAD_BASED_NVCA = DeemedOutstandingDefinition(
    name="broad_based_nvca",
    source=(
        "NVCA Model Certificate of Incorporation 4.4.4, definition of 'A' (June 2019 and "
        "October 2025 text): common outstanding, treating as outstanding the common "
        "issuable on exercise of Options outstanding and on conversion of Convertible "
        "Securities (including the Preferred Stock) outstanding. Reserved but ungranted "
        "plan shares are not Options outstanding, so they are excluded."
    ),
    include_common=True,
    include_preferred_as_converted=True,
    include_options_and_warrants=True,
    include_other_convertibles=True,
    include_reserved_pool=False,
)

BROAD_BASED_WITH_RESERVED_POOL = DeemedOutstandingDefinition(
    name="broad_based_with_reserved_pool",
    source=(
        "The NVCA composition plus shares reserved but not yet granted under the equity "
        "plan. A charter may deem these outstanding as well; no primary charter text "
        "doing so was verified for this project. Use only when the charter says so."
    ),
    include_common=True,
    include_preferred_as_converted=True,
    include_options_and_warrants=True,
    include_other_convertibles=True,
    include_reserved_pool=True,
)

NARROW_BASED_OUTSTANDING_STOCK = DeemedOutstandingDefinition(
    name="narrow_based_outstanding_stock",
    source=(
        "Outstanding capital stock only: common outstanding and preferred as-converted; "
        "Options, warrants, other Convertible Securities and the reserve excluded. "
        "Narrow-based definitions vary by charter and this one was not verified against "
        "a charter text. A charter that narrows differently needs its own definition."
    ),
    include_common=True,
    include_preferred_as_converted=True,
    include_options_and_warrants=False,
    include_other_convertibles=False,
    include_reserved_pool=False,
)


class DeemedOutstanding(FinancialBaseModel):
    """``A`` with its composition: every stated component, counted or excluded."""

    model_config = ConfigDict(frozen=True)

    definition: str
    counted: dict[str, ShareCount]
    excluded: dict[str, ShareCount]
    total: ShareCount


class DilutiveIssuance(FinancialBaseModel):
    """One issuance of additional common-equivalent shares and what the company received.

    ``shares_issued`` is ``C``: common shares issued, or the common issuable on
    conversion of a new preferred series at its initial ratio. ``aggregate_consideration``
    is the caller's figure for what the company received for them; zero is an issuance
    without consideration. Whether the issuance is excluded from adjustment (an
    "Exempted Security"), and how non-cash, option or convertible consideration is
    valued, are charter questions settled before this object is built.
    """

    model_config = ConfigDict(frozen=True)

    shares_issued: float = Field(gt=0.0)
    aggregate_consideration: Money

    @property
    def price_per_share(self) -> SharePrice:
        return self.aggregate_consideration / self.shares_issued


class ConversionPriceAdjustment(FinancialBaseModel):
    """A new conversion price with the terms that produced it.

    ``a``, ``b`` and ``deemed_outstanding`` are ``None`` for full ratchet, which does not
    use them. ``triggered`` is False when the issue price was not below ``CP1``; the price
    is then unchanged.
    """

    model_config = ConfigDict(frozen=True)

    method: Literal["weighted_average", "full_ratchet"]
    conversion_price_before: SharePrice
    conversion_price_after: SharePrice
    issue_price: SharePrice
    triggered: bool
    a: ShareCount | None
    b: ShareCount | None
    c: ShareCount
    deemed_outstanding: DeemedOutstanding | None
    input_hash: str
    engine_version: str = ENGINE_VERSION
    assumptions: list[str]

    @property
    def adjustment_factor(self) -> float:
        """``CP2 / CP1``; 1.0 when no adjustment was made."""
        return self.conversion_price_after / self.conversion_price_before


_COMMON_ASSUMPTIONS = (
    "One issuance; whether it is an Exempted Security is the caller's determination.",
    "Aggregate consideration is taken as stated; valuation of property and of options or "
    "convertible securities (NVCA 4.4.5) is not computed.",
    "Adjusts only downward: applies only when the issue price is strictly below the "
    "conversion price in effect immediately prior.",
    "CP2 is unrounded; the NVCA form rounds it to the nearest one-hundredth of a cent.",
    "One protected series; each series is adjusted separately against its own CP1.",
)


def _positive_price(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive, got {number}")
    return number


def _require(value: object, expected: type, name: str) -> None:
    if not isinstance(value, expected):
        raise ValueError(f"{name} must be a {expected.__name__}, got {type(value).__name__}")


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def deemed_outstanding(
    capitalization: CapitalizationBeforeIssue, definition: DeemedOutstandingDefinition
) -> DeemedOutstanding:
    """Compose ``A`` from stated share counts under a stated definition.

    Records what was excluded as well as what was counted, so the charter choice that
    produced ``A`` is visible in every result.
    """
    _require(capitalization, CapitalizationBeforeIssue, "capitalization")
    _require(definition, DeemedOutstandingDefinition, "definition")
    counted: dict[str, float] = {}
    excluded: dict[str, float] = {}
    for component, include in definition.included().items():
        shares = getattr(capitalization, component)
        (counted if include else excluded)[component] = shares
    return DeemedOutstanding(
        definition=definition.name,
        counted=counted,
        excluded=excluded,
        total=math.fsum(counted.values()),
    )


def weighted_average(
    *,
    conversion_price: float,
    capitalization: CapitalizationBeforeIssue,
    definition: DeemedOutstandingDefinition,
    issuance: DilutiveIssuance,
) -> ConversionPriceAdjustment:
    """Weighted-average adjustment ``CP2 = CP1 * (A + B) / (A + C)``.

    ``CP1`` is ``conversion_price``, the price in effect immediately prior. ``A`` is
    ``deemed_outstanding(capitalization, definition).total``. ``B`` is the aggregate
    consideration divided by ``CP1``: the shares the money would have bought at the old
    price. ``C`` is the shares actually issued. Broad- and narrow-based differ only in
    ``definition``; there is no default, because the charter decides it.

    The adjustment applies only when the issue price ``p`` is strictly below ``CP1``,
    as in the NVCA trigger; otherwise ``CP2 = CP1``. Where it applies,
    ``CP2 - p = A * (CP1 - p) / (A + C)``, so ``p <= CP2 <= CP1`` and a larger ``A``
    gives a smaller adjustment. The result is also clamped at ``CP1`` so that float
    rounding at an issue price within an ulp of ``CP1`` cannot move the price upward.

    Raises ``ValueError`` when ``A`` is zero: the protected series is itself
    outstanding, so a composition that counts no shares is not a usable base.
    """
    cp1 = _positive_price("conversion_price", conversion_price)
    _require(issuance, DilutiveIssuance, "issuance")
    base = deemed_outstanding(capitalization, definition)
    if base.total <= 0:
        raise ValueError(
            f"A is zero under definition '{definition.name}'; a weighted-average base "
            "must count at least the outstanding shares of the protected series"
        )
    a = base.total
    b = issuance.aggregate_consideration / cp1
    c = issuance.shares_issued
    price = issuance.price_per_share
    triggered = price < cp1
    cp2 = min(cp1, cp1 * (a + b) / (a + c)) if triggered else cp1
    return ConversionPriceAdjustment(
        method="weighted_average",
        conversion_price_before=cp1,
        conversion_price_after=cp2,
        issue_price=price,
        triggered=triggered,
        a=a,
        b=b,
        c=c,
        deemed_outstanding=base,
        input_hash=_hash(
            {
                "method": "weighted_average",
                "conversion_price": cp1,
                "capitalization": capitalization.model_dump(),
                "definition": definition.model_dump(),
                "issuance": issuance.model_dump(),
            }
        ),
        assumptions=[
            *_COMMON_ASSUMPTIONS,
            f"A uses the stated composition '{definition.name}'; the charter's "
            "definition of deemed outstanding decides it.",
            "Counts in A are as-converted or as-exercised at the ratios in effect "
            "immediately prior to this issuance.",
        ],
    )


def full_ratchet(
    *, conversion_price: float, issuance: DilutiveIssuance
) -> ConversionPriceAdjustment:
    """Full-ratchet adjustment: ``CP2`` is the issue price, whatever the number of shares.

    Applies only when the issue price is strictly below ``CP1``, as in the NVCA
    full-ratchet alternative to 4.4.4; otherwise ``CP2 = CP1``. ``A`` does not enter, so
    there is no base definition. Algebraically this is the weighted-average formula in
    the limit ``A -> 0``.

    An issuance without consideration is rejected: the formula would set ``CP2`` to zero
    and the conversion ratio to infinity. The NVCA alternative instead deems the company
    to have received a bracketed, negotiated aggregate amount ("[$0.001]" in the October
    2025 text) for such an issuance; pass the charter's amount as
    ``aggregate_consideration``.
    """
    cp1 = _positive_price("conversion_price", conversion_price)
    _require(issuance, DilutiveIssuance, "issuance")
    if issuance.aggregate_consideration == 0:
        raise ValueError(
            "full ratchet on an issuance without consideration sets the conversion price "
            "to zero; pass the charter's deemed consideration (the NVCA form brackets "
            "[$.001] in aggregate) as aggregate_consideration"
        )
    price = issuance.price_per_share
    triggered = price < cp1
    cp2 = price if triggered else cp1
    return ConversionPriceAdjustment(
        method="full_ratchet",
        conversion_price_before=cp1,
        conversion_price_after=cp2,
        issue_price=price,
        triggered=triggered,
        a=None,
        b=None,
        c=issuance.shares_issued,
        deemed_outstanding=None,
        input_hash=_hash(
            {
                "method": "full_ratchet",
                "conversion_price": cp1,
                "issuance": issuance.model_dump(),
            }
        ),
        assumptions=[
            *_COMMON_ASSUMPTIONS,
            "Full ratchet: CP2 is the issue price whatever the number of shares issued.",
            "Any negotiated end date on the ratchet is not checked.",
        ],
    )


def conversion_ratio(*, original_issue_price: float, conversion_price: float) -> float:
    """Common shares per preferred share: ``original_issue_price / conversion_price``.

    NVCA Model COI 4.1.1: each preferred share converts into the number of common
    shares found by dividing the Original Issue Price by the Conversion Price in effect
    at conversion. The value is what ``PreferredStock.conversion_ratio`` expects.

    Identity: for ``n`` preferred shares bought at the original issue price,
    ``n * ratio = n * OIP / CP = invested capital / CP``. The converted share count is
    the original investment re-priced at the adjusted conversion price. The ratio is 1
    before any adjustment (``CP = OIP``) and above 1 after a downward one. Both arguments
    are keyword-only because swapping them returns the reciprocal, a plausible wrong
    number.
    """
    oip = _positive_price("original_issue_price", original_issue_price)
    cp = _positive_price("conversion_price", conversion_price)
    return oip / cp
