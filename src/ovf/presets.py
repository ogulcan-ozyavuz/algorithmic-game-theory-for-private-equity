"""Presets from the NVCA model charter: the document's structure, the caller's brackets.

The NVCA Model Certificate of Incorporation (October 2025) is a template. Its economic
terms are bracketed blanks, alternative sections and footnoted variants, and the model
states no preference among them. So a preset here cannot resolve them either:

- every bracket, alternative section and footnoted variant is a **required argument with
  no default**. That covers the liquidation multiple, participation and its cap, the
  dividend alternative and its terms, and the anti-dilution alternative.
- only the model's **unbracketed** wording is supplied by the preset: the conversion ratio
  and its starting price, ranking ahead of common, pro rata sharing in a shortfall,
  forfeiture of accruing dividends on conversion, and a participation cap on the total.

Every term in the result records whether it came from the caller or from the model's
text, with the provision and its wording.

``nvca_series_a`` is the preset that maps to the document. ``additional_series`` is not an
NVCA preset: the model charter creates one series, so a further series, its rank and its
terms are the caller's (see its docstring).

Sources, derivations and what is not modelled: ``docs/presets.md``. Nothing here reads a
clock. An accruing dividend takes its start date from the caller, and an exit takes
``as_of`` exactly as for any other table.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, ConfigDict, Field, StrictBool, model_validator

from ovf.antidilution import BROAD_BASED_NVCA
from ovf.contracts.securities import (
    CumulativeDividend,
    DividendDayCount,
    NonCumulativeDividend,
    PreferredStock,
    cumulative_dividend,
    non_cumulative_dividend,
    preferred,
)
from ovf.core.types import FinancialBaseModel
from ovf.financing import (
    FULL_RATCHET,
    UNPROTECTED,
    AntiDilutionProtection,
    weighted_average_protection,
)

ENGINE_VERSION = "presets-v1"

# Integer seniority given to the Series A position. The model charter has one series, so
# among preferred stock this number has no effect until another series is ranked
# against it with ``additional_series``. Every preferred position ranks ahead of common.
SERIES_A_SENIORITY = 1


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("a boolean is not accepted where a number is required")
    return value


Rate = Annotated[float, BeforeValidator(_reject_bool), Field(gt=0.0, le=1.0)]
Multiple = Annotated[float, BeforeValidator(_reject_bool), Field(gt=0.0)]
Frequency = Annotated[int, Field(ge=1, strict=True)]


class ModelDocument(FinancialBaseModel):
    """A published model document, pinned by URL and SHA-256 of the file read."""

    model_config = ConfigDict(frozen=True)

    title: str
    version: str
    url: str
    sha256: str
    read_on: date


NVCA_MODEL_COI = ModelDocument(
    title="NVCA Model Amended and Restated Certificate of Incorporation",
    version="October 2025 (file NVCA-Model-COI-10-1-2025.docx, created 2025-10-01)",
    url="https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx",
    sha256="d75600769c12724990de48149d7a2bb161f3522daa54b1783672f93697d87d29",
    read_on=date(2026, 9, 15),
)

NVCA_MODEL_TERM_SHEET = ModelDocument(
    title="NVCA Model Term Sheet (Series A Preferred Stock Financing)",
    version=(
        "2019 (file NVCA-Model-Term-Sheet-1.doc, uploaded 2019-06). A separate instrument "
        "from the charter; nvca.org/model-legal-documents listed no later venture term "
        "sheet when read"
    ),
    url="https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Term-Sheet-1.doc",
    sha256="6ddf9f59400272a93863790041f9f8057464fb6399aeba801ce391954b697a44",
    read_on=date(2026, 9, 15),
)


# ---------------------------------------------------------------------------
# The caller's choices. Each class is one bracketed alternative of the model; none has a
# default field, and each constructor below takes every term as a required keyword.
# ---------------------------------------------------------------------------


class NonParticipating(FinancialBaseModel):
    """COI s.2.1-2.2, non-participating alternative: the greater of the preference and the
    as-converted amount; the remainder goes to common."""

    model_config = ConfigDict(frozen=True)


class Participating(FinancialBaseModel):
    """COI s.2.1-2.2, participating alternative, with or without the fn 20 cap.

    ``maximum_participation_multiple`` is the fn 20 "Maximum Participation Amount" stated
    as a multiple of the Original Issue Price, or ``None`` when the term sheet specifies
    no cap. fn 20 states the amount as "[$_______] per share"; for one series that is
    ``multiple x Original Issue Price``. The cap bounds the total received under s.2.1
    and s.2.2, preference included.
    """

    model_config = ConfigDict(frozen=True)

    maximum_participation_multiple: Multiple | None


class DividendAsConvertedOnly(FinancialBaseModel):
    """COI s.1, first alternative: "no specific dividend on the Preferred Stock, but an
    equal sharing if dividends are declared on the Common Stock". Nothing accrues, so it
    adds nothing to an exit; the position carries ``dividend=None``."""

    model_config = ConfigDict(frozen=True)


class DividendNonCumulative(FinancialBaseModel):
    """COI s.1, second alternative: a non-cumulative "Dividend Amount" of ``rate`` x the
    Original Issue Price ("[8]%" in the model), payable only if declared."""

    model_config = ConfigDict(frozen=True)

    rate: Rate


class DividendAccruing(FinancialBaseModel):
    """COI s.1, third alternative: cumulative "Accruing Dividends".

    - ``rate``: per annum on the Original Issue Price. The operative text states
      "$[___] per share"; that amount is ``rate x Original Issue Price``.
    - ``accrual``: ``"simple"`` is the operative text ("will by definition be
      non-compounding", fn 13); ``"compound"`` is the fn 13 variant, which must state its
      ``compounding_frequency``. ``compounding_frequency`` is ``None`` for simple.
    - ``day_count``: the text says only "accrue from day to day".
    - ``accrues_from``: "From and after the date of the issuance".
    - ``payable_on_liquidation``: the fn 14 bracket "[or in Section 2.1 [and Section
      6.1]]". Only ``True`` is supported: without it the accrued amount is not in the
      s.2.1 amount and is payable only if declared, which ovf does not model.
    """

    model_config = ConfigDict(frozen=True)

    rate: Rate
    accrual: Literal["simple", "compound"]
    compounding_frequency: Frequency | None
    day_count: DividendDayCount
    accrues_from: date
    payable_on_liquidation: StrictBool

    @model_validator(mode="after")
    def validate_accruing(self) -> Self:
        if isinstance(self.accrues_from, datetime):
            raise ValueError("accrues_from must be a date; time of day is not modelled")
        if self.accrual == "simple" and self.compounding_frequency is not None:
            raise ValueError(
                "simple accrual takes compounding_frequency=None: NVCA fn 13, a dividend "
                "'expressed as \"$____ per share\" will by definition be non-compounding'"
            )
        if self.accrual == "compound" and self.compounding_frequency is None:
            raise ValueError(
                "compound accrual needs a compounding_frequency: NVCA fn 13, 'it should also "
                'be specified whether this "compounding" ... is done on an annual, '
                "quarterly, or other basis'"
            )
        if not self.payable_on_liquidation:
            raise ValueError(
                "payable_on_liquidation=False is not supported. Without the fn 14 bracket "
                "'[or in Section 2.1 ...]' accruing dividends are not part of the liquidation "
                "amount and are payable only when declared; declared dividends are not "
                "modelled, so no exit claim can be built for them"
            )
        return self


class AntiDilutionBroadBasedWeightedAverage(FinancialBaseModel):
    """COI s.4.4.4, broad-based weighted-average alternative, with the model's definition
    of "A" (``ovf.antidilution.BROAD_BASED_NVCA``)."""

    model_config = ConfigDict(frozen=True)


class AntiDilutionFullRatchet(FinancialBaseModel):
    """COI s.4.4.4, full-ratchet alternative.

    ``end_date`` is the bracket "[and prior to [Date]]". Only ``None`` is supported:
    ``ovf.financing`` reads no date, so a ratchet that lapses cannot be applied correctly.
    """

    model_config = ConfigDict(frozen=True)

    end_date: date | None

    @model_validator(mode="after")
    def validate_end_date(self) -> Self:
        if self.end_date is not None:
            raise ValueError(
                "a full-ratchet end date ('[and prior to [Date]]', NVCA COI s.4.4.4 and fn 57) "
                "is not modelled: ovf.financing reads no date, so it would apply the ratchet "
                "after the date too. Pass end_date=None only if the charter has no end date"
            )
        return self


class AntiDilutionNone(FinancialBaseModel):
    """No price-based anti-dilution. This is Alternative 3 of the NVCA Model Term Sheet
    (2019). The charter has no such alternative: its s.4.4.4 would be deleted."""

    model_config = ConfigDict(frozen=True)


Participation = NonParticipating | Participating
PresetDividend = DividendAsConvertedOnly | DividendNonCumulative | DividendAccruing
PresetAntiDilution = (
    AntiDilutionBroadBasedWeightedAverage | AntiDilutionFullRatchet | AntiDilutionNone
)
Rank = Literal["pari_passu", "senior", "junior"]


def non_participating() -> NonParticipating:
    """COI s.2.1-2.2, non-participating alternative."""
    return NonParticipating()


def participating(*, maximum_participation_multiple: float | None) -> Participating:
    """COI s.2.1-2.2, participating alternative. Pass ``None`` for no fn 20 cap; there is no
    default, because whether a cap exists is a term-sheet choice."""
    return Participating(maximum_participation_multiple=maximum_participation_multiple)


def dividend_as_converted_only() -> DividendAsConvertedOnly:
    """COI s.1, first alternative: dividends only as-converted, when declared on common."""
    return DividendAsConvertedOnly()


def dividend_non_cumulative(*, rate: float) -> DividendNonCumulative:
    """COI s.1, second alternative: non-cumulative Dividend Amount of ``rate`` x OIP."""
    return DividendNonCumulative(rate=rate)


def dividend_accruing(
    *,
    rate: float,
    accrual: Literal["simple", "compound"],
    compounding_frequency: int | None,
    day_count: DividendDayCount,
    accrues_from: date,
    payable_on_liquidation: bool,
) -> DividendAccruing:
    """COI s.1, third alternative: Accruing Dividends. Every term is required; see
    ``DividendAccruing``."""
    return DividendAccruing(
        rate=rate,
        accrual=accrual,
        compounding_frequency=compounding_frequency,
        day_count=day_count,
        accrues_from=accrues_from,
        payable_on_liquidation=payable_on_liquidation,
    )


def anti_dilution_broad_based_weighted_average() -> AntiDilutionBroadBasedWeightedAverage:
    """COI s.4.4.4, broad-based weighted-average alternative."""
    return AntiDilutionBroadBasedWeightedAverage()


def anti_dilution_full_ratchet(*, end_date: date | None) -> AntiDilutionFullRatchet:
    """COI s.4.4.4, full-ratchet alternative; ``end_date`` must be stated, and only
    ``None`` is supported."""
    return AntiDilutionFullRatchet(end_date=end_date)


def anti_dilution_none() -> AntiDilutionNone:
    """No price-based protection: NVCA Model Term Sheet (2019), Alternative 3."""
    return AntiDilutionNone()


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------


class TermRecord(FinancialBaseModel):
    """One term of a preset position and where it came from.

    ``origin`` is ``"caller"`` for a bracket, alternative or blank the caller filled, and
    ``"model_text"`` for unbracketed wording the preset supplied. ``within_model`` is
    False when the term is not drafted in the model charter at all. ``source`` names the
    document and provision. ``wording`` is a verbatim excerpt, with typographic quotes
    written as straight quotes and elisions marked "...".
    """

    model_config = ConfigDict(frozen=True)

    term: str
    value: str
    origin: Literal["caller", "model_text"]
    within_model: bool
    source: str
    wording: str


class PresetPosition(FinancialBaseModel):
    """A preferred position built from the model charter's structure, with its provenance.

    ``security`` goes into a ``CapTable``. ``anti_dilution`` is the entry for this
    position in the ``protection`` mapping of ``ovf.financing.apply_dilutive_issuance``;
    ``PreferredStock`` has no anti-dilution field. ``series_in_model`` is False for a
    series built with ``additional_series``. ``not_represented`` lists terms of the model
    charter that this position does not carry.
    """

    model_config = ConfigDict(frozen=True)

    preset: Literal["nvca_series_a", "additional_series"]
    series: str
    series_in_model: bool
    security: PreferredStock
    anti_dilution: AntiDilutionProtection
    document: ModelDocument
    terms: tuple[TermRecord, ...]
    not_represented: tuple[str, ...]
    assumptions: tuple[str, ...]
    input_hash: str
    engine_version: str = ENGINE_VERSION

    def term(self, name: str) -> TermRecord:
        """The record for one term, by name."""
        for record in self.terms:
            if record.term == name:
                return record
        raise KeyError(name)


# ---------------------------------------------------------------------------
# Wording, verbatim from NVCA_MODEL_COI unless another document is named
# ---------------------------------------------------------------------------

_COI = "NVCA Model COI (Oct 2025)"
_TS = "NVCA Model Term Sheet (2019)"

_W_DESIGNATION = (
    '[all] of which are hereby designated as "Series A Preferred Stock". ... References to '
    '"Preferred Stock" mean the Series A Preferred Stock.'
)
_W_OIP = (
    'The "Original Issue Price" shall mean, with respect to the Series A Preferred Stock, '
    "$[insert initial Series A purchase price] per share"
)
_W_SHARES = "Investor No. 1: [_______] shares ([__]%), $[_________]"
_W_MULTIPLE = {
    False: (
        "an amount per share of each such series of Preferred Stock equal to the greater of "
        "(i) [__ times] the applicable Original Issue Price, plus any dividends declared but "
        "unpaid thereon, or (ii) such amount per share as would have been payable had all "
        "shares of such series of Preferred Stock ... been converted into Common Stock"
    ),
    True: (
        "an amount per share equal to [___ times] the applicable Original Issue Price, plus "
        "any dividends declared but unpaid thereon"
    ),
}
_W_PARTICIPATION = {
    False: (
        "[Use the following Sections 2.1 and 2.2 if the term sheet calls for "
        "non-participating Preferred Stock.]"
    ),
    True: (
        "[Use the following Sections 2.1 and 2.2 if the term sheet calls for participating "
        "Preferred Stock.] ... distributed among the holders of the shares of Preferred Stock "
        "and Common Stock, pro rata based on the number of shares held by each such holder, "
        "treating for this purpose all such securities as if they had been converted to "
        "Common Stock"
    ),
}
_W_CAP = (
    "If a cap to the liquidation preference is specified in the term sheet, add the "
    'following language ...: "; provided, however, that if the aggregate amount which the '
    "holders of Preferred Stock are entitled to receive under Sections 2.1 and 2.2 shall "
    'exceed [$_______] per share ... (the "Maximum Participation Amount"), each holder of '
    "Preferred Stock shall be entitled to receive ... the greater of (i) the Maximum "
    "Participation Amount and (ii) the amount such holder would have received if all shares "
    'of Preferred Stock had been converted into Common Stock ..."'
)
_W_DIVIDEND = {
    "as_converted_only": (
        "[Use the following paragraph if the Term Sheet calls for no specific dividend on the "
        "Preferred Stock, but an equal sharing if dividends are declared on the Common Stock.]"
    ),
    "non_cumulative": (
        "The right to receive dividends on shares of Preferred Stock pursuant to the preceding "
        'sentence of this Section 1 shall not be cumulative ... The "Dividend Amount" shall '
        "mean, with respect to any series of Preferred Stock, [8]% of the Original Issue Price "
        "of such series of Preferred Stock."
    ),
    "accruing": (
        "From and after the date of the issuance of any shares of Preferred Stock, dividends at "
        "the rate per annum of $[___] per share shall accrue on such shares of Preferred Stock "
        '... (the "Accruing Dividends"). Accruing Dividends shall accrue from day to day, '
        "whether or not declared, and shall be cumulative"
    ),
}
_DIVIDEND_ALTERNATIVE = {"as_converted_only": 1, "non_cumulative": 2, "accruing": 3}
_W_FN9 = "This model charter provides for three bracketed alternative dividend provisions."
_W_FN13 = (
    'A cumulative dividend expressed as "$____ per share" will by definition be '
    "non-compounding. If a compounding accrued dividend is desired, it should be expressed "
    'as a percentage of a "base amount," ... (it should also be specified whether this '
    '"compounding" of the original purchase price is done on an annual, quarterly, or other '
    "basis)."
)
_W_FN14 = (
    "[or in Section 2.1 [and Section 6.1]] ... Insert the bracketed language if the holders "
    "of Preferred Stock will receive the benefit of the accruing dividends upon a liquidation "
    "event or upon redemption."
)
_W_FN17 = (
    "If accruing dividends are provided for, the following language would generally be used "
    'instead: "the Original Issue Price, plus any Accruing Dividends accrued but unpaid '
    "thereon, whether or not declared, together with any other dividends declared but unpaid "
    'thereon."'
)
_W_TS_LIQUIDATION = (
    "First pay [one] times the Original Purchase Price [plus accrued dividends] [plus "
    "declared and unpaid dividends] on each share of Series A Preferred"
)
_W_FORFEIT = (
    "all rights with respect to such shares shall immediately cease and terminate at the "
    "Conversion Time, except only the right of the holders thereof to receive shares of "
    "Common Stock in exchange therefor and to receive payment of any dividends declared but "
    "unpaid thereon. (fn 46: The effect of using the Original Issue Price is that accruing "
    "dividends are not taken into account in a conversion.)"
)
_W_AHEAD_OF_COMMON = (
    "before any payment shall be made to the holders of Common Stock by reason of their "
    "ownership thereof"
)
_W_PARI_PASSU = (
    "on a pari passu basis based on their respective Liquidation Amounts (fn 16: For "
    "simplicity, this model charter provides for pari passu preferred stock liquidation. If "
    "one or more series of preferred stock has a senior or junior liquidation preference, "
    "this language will need to be revised.)"
)
_W_SHORTFALL = (
    "the holders of shares of Preferred Stock shall share ratably in any distribution of the "
    "assets available for distribution in proportion to the respective amounts which would "
    "otherwise be payable in respect of the shares held by them upon such distribution if all "
    "amounts payable on or with respect to such shares were paid in full"
)
_W_CONVERSION = (
    "as is determined by dividing the applicable Original Issue Price by the applicable "
    'Conversion Price ... The "Conversion Price" applicable to the Preferred Stock as of the '
    "Original Issue Date shall be equal to $_______ [insert original purchase price of Series "
    "A Preferred Stock] per share"
)
_W_FN18 = (
    "That alternative formulation is not intended to result in a substantive difference from "
    "the approach taken in this form; rather, in that alternative formulation, it is assumed "
    "that the holders of a particular series of Preferred Stock would simply convert into "
    "Common Stock if the as-converted payment is greater than the original purchase price "
    "(plus dividends, if applicable)."
)
_W_ANTI_DILUTION = {
    "broad_based_weighted_average": (
        "[Use the following Section 4.4.4 if the terms sheet calls for a broad-based weighted "
        "average anti-dilution provision] ... CP2 = CP1* (A + B) / (A + C)."
    ),
    "full_ratchet": (
        "[Use the following Section 4.4.4 if the term sheet calls for a full ratchet "
        "anti-dilution provision] ... In the event the Corporation at any time after the "
        "Original Issue Date [and prior to [Date]] issues Additional Shares of Common Stock "
        "... the Conversion Price of such series of Preferred Stock shall be reduced ... to "
        "the consideration per share received by the Corporation"
    ),
    "none": "[Alternative 3: No price-based anti-dilution protection.]",
}
_W_A_DEFINITION = (
    '"A" shall mean the number of shares of Common Stock outstanding immediately prior to '
    "such issuance ... (treating for this purpose as outstanding all shares of Common Stock "
    "issuable upon exercise of Options outstanding ... or upon conversion or exchange of "
    "Convertible Securities (including the Preferred Stock) outstanding ...)"
)
_W_FN16_RANK = (
    "For simplicity, this model charter provides for pari passu preferred stock liquidation. "
    "If one or more series of preferred stock has a senior or junior liquidation preference, "
    "this language will need to be revised."
)

NOT_REPRESENTED: tuple[str, ...] = (
    "COI s.1 and s.2.1 dividends declared but unpaid ('plus any dividends declared but unpaid "
    "thereon'): not modelled; settle them outside and net them off.",
    "COI s.2.3 Deemed Liquidation Events and the '[specify percentage]' waiver: the exit "
    "passed to the waterfall is taken to be a liquidation event.",
    "COI s.2.3.2(b) redemption after a Deemed Liquidation Event and s.2.3.3 board valuation of "
    "non-cash consideration: the exit amount is taken as stated.",
    "COI s.2.3.4 escrow and contingent consideration, '[Initial Consideration] [Additional "
    "Consideration]': not modelled; pass the amount distributed.",
    "COI s.3 voting, s.3.2 board election and s.3.3 protective provisions: governance terms, "
    "not carried by this position.",
    "COI s.4.2 rounding of conversion shares to the nearest whole share per holder.",
    "COI s.4.4.1 Exempted Securities brackets, s.4.4.2 waiver '[the Requisite Holders]', "
    "s.4.4.6 '[180] days': stated to ovf.financing per issuance, not held here.",
    "COI s.4.4.4 rounding of CP2 'to the nearest one-hundredth of a cent', and the "
    "full-ratchet deemed consideration '[$0.001]', which the caller passes to ovf.antidilution.",
    "COI s.5 Mandatory Conversion (Qualified IPO thresholds and the Requisite Holders' vote).",
    "COI s.5A Special Mandatory Conversion (pay-to-play), a bracketed section: this position "
    "neither includes nor excludes it, and ovf models no pay-to-play conversion.",
    "COI s.6 Redemption, '[Other than as set forth in Section 2.3.2(b), the Preferred Stock is "
    "not redeemable ...]' or s.6.1-6.5: no redemption is modelled.",
)

_ASSUMPTIONS: tuple[str, ...] = (
    "Terms with origin 'caller' are the caller's statement of a bracket, alternative or "
    "blank of the model; the preset supplies none of them.",
    "Terms with origin 'model_text' are unbracketed wording of the NVCA Model COI (Oct 2025).",
    "The conversion election is solved per position, as the waterfall does for any table; "
    "NVCA fn 18 states that this formulation is 'not intended to result in a substantive "
    "difference' from the charter's greater-of wording.",
    "Liquidation multiple, participation cap and dividend rate are applied to the Original "
    "Issue Price, which is PreferredStock.price.",
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _positive(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive, got {number}")
    return number


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _check_choice(value: object, name: str, allowed: tuple[type, ...], builders: str) -> None:
    if not isinstance(value, allowed):
        raise ValueError(f"{name} must be built with {builders}; got {type(value).__name__}")


def _dividend_term(
    dividend: PresetDividend, *, capped_participation: bool
) -> CumulativeDividend | NonCumulativeDividend | None:
    if isinstance(dividend, DividendAsConvertedOnly):
        return None
    if isinstance(dividend, DividendNonCumulative):
        return non_cumulative_dividend(dividend.rate)
    return cumulative_dividend(
        dividend.rate,
        accrual=dividend.accrual,
        day_count=dividend.day_count,
        accrues_from=dividend.accrues_from,
        # COI s.4.3.3 and fn 46: accruing dividends are lost on conversion.
        settlement="forfeit_on_conversion",
        compounding_frequency=dividend.compounding_frequency,
        # COI fn 20: the cap bounds the s.2.1 + s.2.2 total, and with accruing dividends the
        # s.2.1 amount includes them (fn 17/19). The same footnote sets ovf's default.
        participation_cap_basis="includes_dividends" if capped_participation else None,
    )


def _protection(anti_dilution: PresetAntiDilution) -> AntiDilutionProtection:
    if isinstance(anti_dilution, AntiDilutionBroadBasedWeightedAverage):
        return weighted_average_protection(BROAD_BASED_NVCA)
    if isinstance(anti_dilution, AntiDilutionFullRatchet):
        return FULL_RATCHET
    return UNPROTECTED


def _dividend_kind(dividend: PresetDividend) -> str:
    if isinstance(dividend, DividendAsConvertedOnly):
        return "as_converted_only"
    if isinstance(dividend, DividendNonCumulative):
        return "non_cumulative"
    return "accruing"


def _anti_dilution_kind(anti_dilution: PresetAntiDilution) -> str:
    if isinstance(anti_dilution, AntiDilutionBroadBasedWeightedAverage):
        return "broad_based_weighted_average"
    if isinstance(anti_dilution, AntiDilutionFullRatchet):
        return "full_ratchet"
    return "none"


def _caller(term: str, value: str, source: str, wording: str, *, within: bool = True) -> TermRecord:
    return TermRecord(
        term=term, value=value, origin="caller", within_model=within, source=source, wording=wording
    )


def _model(term: str, value: str, source: str, wording: str) -> TermRecord:
    return TermRecord(
        term=term,
        value=value,
        origin="model_text",
        within_model=True,
        source=source,
        wording=wording,
    )


def _terms(
    *,
    oip: float,
    multiple: float,
    participation: Participation,
    dividend: PresetDividend,
    anti_dilution: PresetAntiDilution,
) -> list[TermRecord]:
    is_participating = isinstance(participation, Participating)
    records = [
        _caller(
            "original_issue_price",
            f"{oip!r} per share",
            f"{_COI} s.1, definition of Original Issue Price",
            _W_OIP,
        ),
        _caller(
            "shares",
            "stated by the caller",
            f"{_TS}, Offering Terms: the shares sold are a term sheet and purchase agreement "
            "term; the charter states only authorized shares",
            _W_SHARES,
        ),
        _caller(
            "liquidation_multiple",
            f"{multiple!r}x the Original Issue Price",
            f"{_COI} s.2.1 ({'participating' if is_participating else 'non-participating'} "
            "alternative)",
            _W_MULTIPLE[is_participating],
        ),
        _caller(
            "participation",
            "participating" if is_participating else "non_participating",
            f"{_COI} s.2.1-2.2 alternatives",
            _W_PARTICIPATION[is_participating],
        ),
    ]
    if isinstance(participation, Participating):
        cap = participation.maximum_participation_multiple
        records.append(
            _caller(
                "maximum_participation_amount",
                "none (no fn 20 cap)"
                if cap is None
                else f"{cap!r}x the Original Issue Price = {cap * oip!r} per share",
                f"{_COI} s.2.2, fn 20",
                _W_CAP,
            )
        )
        if cap is not None:
            records.append(
                _model(
                    "participation_cap_basis",
                    "total of s.2.1 and s.2.2, preference and any accruing dividends included",
                    f"{_COI} fn 20 (and fn 17/19 for the s.2.1 amount with accruing dividends)",
                    _W_CAP,
                )
            )
    kind = _dividend_kind(dividend)
    records.append(
        _caller(
            "dividend",
            kind,
            f"{_COI} s.1, alternative {_DIVIDEND_ALTERNATIVE[kind]} of 3 (fn 9)",
            f"{_W_FN9} {_W_DIVIDEND[kind]}",
        )
    )
    if isinstance(dividend, DividendNonCumulative):
        records.append(
            _caller(
                "dividend_amount",
                f"{dividend.rate!r} x the Original Issue Price, if declared",
                f"{_COI} s.1, second alternative",
                _W_DIVIDEND["non_cumulative"],
            )
        )
    if isinstance(dividend, DividendAccruing):
        records += [
            _caller(
                "accruing_dividend_rate",
                f"{dividend.rate!r} x the Original Issue Price per annum = "
                f"{dividend.rate * oip!r} per share",
                f"{_COI} s.1, third alternative",
                _W_DIVIDEND["accruing"],
            ),
            _caller(
                "accrual",
                dividend.accrual
                if dividend.compounding_frequency is None
                else f"{dividend.accrual}, {dividend.compounding_frequency} period(s) a year",
                f"{_COI} s.1 third alternative (simple) and fn 13 (compounding variant)",
                _W_FN13,
            ),
            _caller(
                "day_count",
                dividend.day_count,
                f"{_COI} s.1: not stated; the text says only that Accruing Dividends 'accrue "
                "from day to day'",
                _W_DIVIDEND["accruing"],
            ),
            _caller(
                "accrues_from",
                dividend.accrues_from.isoformat(),
                f"{_COI} s.1: 'From and after the date of the issuance'",
                _W_DIVIDEND["accruing"],
            ),
            _caller(
                "accruing_dividends_in_liquidation_amount",
                "yes",
                f"{_COI} s.1 bracket and fn 14; s.2.1 wording from fn 17/19. A multiple other "
                f"than 1 combined with accrued dividends follows {_TS}, Liquidation Preference",
                f"{_W_FN14} {_W_FN17} [{_TS}:] {_W_TS_LIQUIDATION}",
            ),
            _model(
                "accruing_dividends_on_conversion",
                "forfeited",
                f"{_COI} s.4.3.3 and fn 46",
                _W_FORFEIT,
            ),
        ]
    ad_kind = _anti_dilution_kind(anti_dilution)
    records.append(
        _caller(
            "anti_dilution",
            ad_kind,
            f"{_TS}, Anti-dilution Provisions, Alternative 3; the charter drafts no such "
            "alternative"
            if ad_kind == "none"
            else f"{_COI} s.4.4.4 alternatives",
            _W_ANTI_DILUTION[ad_kind],
            within=ad_kind != "none",
        )
    )
    if ad_kind == "broad_based_weighted_average":
        records.append(
            _model(
                "anti_dilution_definition_of_a",
                BROAD_BASED_NVCA.name,
                f"{_COI} s.4.4.4, definition of 'A'",
                _W_A_DEFINITION,
            )
        )
    if ad_kind == "full_ratchet":
        records.append(
            _caller(
                "full_ratchet_end_date",
                "none",
                f"{_COI} s.4.4.4 full-ratchet alternative and fn 57",
                "[and prior to [Date]]",
            )
        )
    records += [
        _model(
            "ranking_against_common",
            "every preferred position is paid before common",
            f"{_COI} s.2.1",
            _W_AHEAD_OF_COMMON,
        ),
        _model(
            "shortfall_within_rank",
            "pro rata to the full amount each position would otherwise receive",
            f"{_COI} s.2.1",
            _W_SHORTFALL,
        ),
        _model(
            "conversion_ratio",
            "1.0: Original Issue Price / Conversion Price, with the Conversion Price starting "
            "at the Original Issue Price",
            f"{_COI} s.4.1.1",
            _W_CONVERSION,
        ),
        _model(
            "conversion_election",
            "each position takes the greater of its liquidation amount and its as-converted "
            "amount, solved as an equilibrium",
            f"{_COI} s.2.1(ii) and fn 18",
            _W_FN18,
        ),
    ]
    return records


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot fingerprint {type(value).__name__}")


def _build(
    *,
    preset: Literal["nvca_series_a", "additional_series"],
    series: str,
    series_in_model: bool,
    seniority: int,
    extra_terms: list[TermRecord],
    extra_payload: dict[str, Any],
    shares: float,
    original_issue_price: float,
    liquidation_multiple: float,
    participation: Participation,
    dividend: PresetDividend,
    anti_dilution: PresetAntiDilution,
    holder_id: str,
    security_id: str,
) -> PresetPosition:
    count = _positive("shares", shares)
    oip = _positive("original_issue_price", original_issue_price)
    multiple = _positive("liquidation_multiple", liquidation_multiple)
    holder = _identifier("holder_id", holder_id)
    identifier = _identifier("security_id", security_id)
    _check_choice(
        participation,
        "participation",
        (NonParticipating, Participating),
        "non_participating() or participating(maximum_participation_multiple=...)",
    )
    _check_choice(
        dividend,
        "dividend",
        (DividendAsConvertedOnly, DividendNonCumulative, DividendAccruing),
        "dividend_as_converted_only(), dividend_non_cumulative(...) or dividend_accruing(...)",
    )
    _check_choice(
        anti_dilution,
        "anti_dilution",
        (AntiDilutionBroadBasedWeightedAverage, AntiDilutionFullRatchet, AntiDilutionNone),
        "anti_dilution_broad_based_weighted_average(), anti_dilution_full_ratchet(...) or "
        "anti_dilution_none()",
    )
    cap: float | None = None
    if isinstance(participation, Participating):
        cap = participation.maximum_participation_multiple
        if cap is not None and cap < multiple:
            raise ValueError(
                f"maximum_participation_multiple {cap!r} is below liquidation_multiple "
                f"{multiple!r}. NVCA fn 20 caps 'the aggregate amount ... under Sections 2.1 and "
                "2.2', which includes the preference, so this cap could never be reached"
            )
    security = preferred(
        count,
        oip,
        seniority=seniority,
        liquidation_multiple=multiple,
        participating=isinstance(participation, Participating),
        participation_cap=cap,
        conversion_ratio=1.0,
        holder_id=holder,
        security_id=identifier,
        dividend=_dividend_term(dividend, capped_participation=cap is not None),
    )
    terms = [
        *extra_terms,
        *_terms(
            oip=oip,
            multiple=multiple,
            participation=participation,
            dividend=dividend,
            anti_dilution=anti_dilution,
        ),
    ]
    payload = {
        "preset": preset,
        "series": series,
        **extra_payload,
        "shares": count,
        "original_issue_price": oip,
        "liquidation_multiple": multiple,
        "participation": {type(participation).__name__: participation.model_dump()},
        "dividend": {type(dividend).__name__: dividend.model_dump()},
        "anti_dilution": {type(anti_dilution).__name__: anti_dilution.model_dump()},
        "holder_id": holder,
        "security_id": identifier,
        "document_sha256": NVCA_MODEL_COI.sha256,
        "engine_version": ENGINE_VERSION,
    }
    return PresetPosition(
        preset=preset,
        series=series,
        series_in_model=series_in_model,
        security=security,
        anti_dilution=_protection(anti_dilution),
        document=NVCA_MODEL_COI,
        terms=tuple(terms),
        not_represented=NOT_REPRESENTED,
        assumptions=_ASSUMPTIONS,
        input_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False, default=_json_default).encode()
        ).hexdigest(),
    )


def nvca_series_a(
    *,
    shares: float,
    original_issue_price: float,
    liquidation_multiple: float,
    participation: Participation,
    dividend: PresetDividend,
    anti_dilution: PresetAntiDilution,
    holder_id: str,
    security_id: str,
) -> PresetPosition:
    """Series A preferred as drafted in the NVCA Model COI (October 2025).

    Every argument is required and none has a default. The economic ones fill a bracket,
    an alternative section or a footnoted variant of the model, which states no preference
    among them:

    - ``liquidation_multiple``: s.2.1 "[__ times] the applicable Original Issue Price".
    - ``participation``: the two s.2.1-2.2 alternatives, ``non_participating()`` or
      ``participating(maximum_participation_multiple=...)``, where the cap is fn 20's
      "Maximum Participation Amount" or ``None`` for none.
    - ``dividend``: the three s.1 alternatives (fn 9), ``dividend_as_converted_only()``,
      ``dividend_non_cumulative(rate=...)`` or ``dividend_accruing(...)``.
    - ``anti_dilution``: the two s.4.4.4 alternatives,
      ``anti_dilution_broad_based_weighted_average()`` or
      ``anti_dilution_full_ratchet(end_date=None)``, or ``anti_dilution_none()``
      (Term Sheet Alternative 3; not drafted in the charter).
    - ``original_issue_price`` fills the s.1 blank; ``shares`` is a purchase-agreement term.

    The preset supplies only unbracketed text: ranking ahead of common and pro rata
    shortfall (s.2.1), the conversion ratio (s.4.1.1, starting at 1), forfeiture of accruing
    dividends on conversion (s.4.3.3), and a cap on the s.2.1 + s.2.2 total (fn 20). The
    result's ``terms`` record every term with its origin, provision and wording.
    """
    return _build(
        preset="nvca_series_a",
        series="Series A Preferred Stock",
        series_in_model=True,
        seniority=SERIES_A_SENIORITY,
        extra_terms=[
            _model(
                "series",
                "Series A Preferred Stock, the one series the model charter creates",
                f"{_COI} Article Fourth and Part B",
                _W_DESIGNATION,
            ),
            _model(
                "ranking_among_preferred",
                "one series, so no ranking among preferred arises; the model's wording is "
                "pari passu",
                f"{_COI} s.2.1 and fn 16",
                _W_PARI_PASSU,
            ),
        ],
        extra_payload={},
        shares=shares,
        original_issue_price=original_issue_price,
        liquidation_multiple=liquidation_multiple,
        participation=participation,
        dividend=dividend,
        anti_dilution=anti_dilution,
        holder_id=holder_id,
        security_id=security_id,
    )


def additional_series(
    *,
    series: str,
    rank: Rank,
    relative_to: PresetPosition | PreferredStock,
    shares: float,
    original_issue_price: float,
    liquidation_multiple: float,
    participation: Participation,
    dividend: PresetDividend,
    anti_dilution: PresetAntiDilution,
    holder_id: str,
    security_id: str,
) -> PresetPosition:
    """A further preferred series built with the model's term structure; not an NVCA preset.

    The NVCA Model COI (October 2025) is single-series: it designates only "Series A
    Preferred Stock", and fn 16 and fn 12 say its liquidation and dividend wording "will
    need to be revised" for several series. So the series built here, its rank and all of
    its terms are the caller's, not NVCA's. The result has ``series_in_model=False``.

    ``rank`` places this series against ``relative_to``, with no default:

    - ``"pari_passu"``: the same seniority. This follows the s.2.1 wording "on a pari passu
      basis", the only ranking the model drafts.
    - ``"senior"``: paid before ``relative_to`` (one integer lower); outside the model text.
    - ``"junior"``: paid after it (one integer higher); outside the model text.

    Every other argument has the meaning it has in ``nvca_series_a``, and is required.
    """
    label = _identifier("series", series)
    if rank not in ("pari_passu", "senior", "junior"):
        raise ValueError(f"rank must be 'pari_passu', 'senior' or 'junior', got {rank!r}")
    if isinstance(relative_to, PresetPosition):
        anchor = relative_to.security
    elif isinstance(relative_to, PreferredStock):
        anchor = relative_to
    else:
        raise ValueError(
            "relative_to must be a PresetPosition or a PreferredStock, got "
            f"{type(relative_to).__name__}"
        )
    if security_id == anchor.security_id:
        raise ValueError(f"security_id {security_id!r} is already used by relative_to")
    if rank == "senior" and anchor.seniority == 0:
        raise ValueError(
            f"{anchor.security_id} has seniority 0, the highest rank ovf represents, so no "
            "series can rank above it. Rebuild it at a lower rank (a higher integer) first"
        )
    offset = {"pari_passu": 0, "senior": -1, "junior": 1}[rank]
    if rank == "pari_passu":
        rank_record = _caller(
            "rank",
            f"pari_passu with {anchor.security_id}",
            f"{_COI} s.2.1 wording, applied by the caller to a series the model does not create",
            _W_PARI_PASSU,
        )
    else:
        rank_record = _caller(
            "rank",
            f"{rank} to {anchor.security_id}",
            f"outside the model text: {_COI} fn 16 says a senior or junior preference needs "
            "revised language",
            _W_FN16_RANK,
            within=False,
        )
    return _build(
        preset="additional_series",
        series=label,
        series_in_model=False,
        seniority=anchor.seniority + offset,
        extra_terms=[
            _caller(
                "series",
                f"{label}: a further series stated by the caller",
                f"outside the model text: {_COI} creates only Series A",
                _W_DESIGNATION,
                within=False,
            ),
            rank_record,
        ],
        extra_payload={
            "rank": rank,
            "relative_to": anchor.security_id,
            "relative_to_seniority": anchor.seniority,
        },
        shares=shares,
        original_issue_price=original_issue_price,
        liquidation_multiple=liquidation_multiple,
        participation=participation,
        dividend=dividend,
        anti_dilution=anti_dilution,
        holder_id=holder_id,
        security_id=security_id,
    )


def anti_dilution_terms(*positions: PresetPosition) -> dict[str, AntiDilutionProtection]:
    """``{security_id: anti_dilution}`` for ``ovf.financing.apply_dilutive_issuance``.

    That function needs an entry for every preferred position in the table; add entries
    for positions that were not built here.
    """
    mapping: dict[str, AntiDilutionProtection] = {}
    for position in positions:
        if not isinstance(position, PresetPosition):
            raise ValueError(f"expected a PresetPosition, got {type(position).__name__}")
        key = position.security.security_id
        if key in mapping:
            raise ValueError(f"Duplicate security_id: {key}")
        mapping[key] = position.anti_dilution
    return mapping


__all__ = [
    "ENGINE_VERSION",
    "NOT_REPRESENTED",
    "NVCA_MODEL_COI",
    "NVCA_MODEL_TERM_SHEET",
    "SERIES_A_SENIORITY",
    "AntiDilutionBroadBasedWeightedAverage",
    "AntiDilutionFullRatchet",
    "AntiDilutionNone",
    "DividendAccruing",
    "DividendAsConvertedOnly",
    "DividendNonCumulative",
    "ModelDocument",
    "NonParticipating",
    "Participating",
    "Participation",
    "PresetAntiDilution",
    "PresetDividend",
    "PresetPosition",
    "Rank",
    "TermRecord",
    "additional_series",
    "anti_dilution_broad_based_weighted_average",
    "anti_dilution_full_ratchet",
    "anti_dilution_none",
    "anti_dilution_terms",
    "dividend_accruing",
    "dividend_as_converted_only",
    "dividend_non_cumulative",
    "non_participating",
    "nvca_series_a",
    "participating",
]
