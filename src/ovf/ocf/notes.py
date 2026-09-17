"""Convertible notes from OCF v1.2.0 into ``ovf.instruments.ConvertibleNote``.

An OCF v1.2.0 ``TX_CONVERTIBLE_ISSUANCE`` does not carry a convertible note's economics in
full. It has no maturity date. It states the qualified-financing threshold only as free
text in a trigger's ``trigger_condition``. It has a compounding type but no compounding
frequency. It names its day count ``ACTUAL_365`` without saying whether the year is fixed at
365 days: OCF issue #423 has asked what the value means since 2023-05-10. ovf's
``ConvertibleNote`` requires all of these. So the reader builds a note only from an OCF
record together with caller-supplied ``OcfNoteTerms``, and refuses everything else, naming
the field. ``docs/ocf.md`` states each rule and its source.

The subset that is read:

* ``convertible_type`` NOTE. SAFE and CONVERTIBLE_SECURITY are refused.
* Exactly one trigger, of type AUTOMATIC_ON_CONDITION, read as the qualified financing.
  Its ``trigger_condition`` text is not parsed. The threshold comes from the caller, who
  asserts that it and the text agree. This is a trust boundary, not a check.
* A ``CONVERTIBLE_NOTE_CONVERSION`` mechanism with one SIMPLE, DAILY, DEFERRED interest
  rate that starts on the issuance date and has no end date.
* ``day_count_convention`` ACTUAL_365, used only as a consistency check: the caller's day
  count must be Actual/365 Fixed. 30_360 is refused.
* Seniority: "1 being highest seniority", the opposite direction to
  ``StockClass.seniority``. The distinct values, lowest first, become ovf debt seniority
  ranks 1, 2, ... They rank notes against other debt only. Every debt position is paid
  ahead of all equity, and the two seniority scales are never compared.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from ovf.contracts.captable import CapTable
from ovf.core.types import FinancialBaseModel
from ovf.instruments.debt import AccrualMethod, ConvertibleNote, DayCount
from ovf.ocf.schema import (
    ConvertibleIssuance,
    NoteConversionMechanism,
    OcfUnsupportedError,
    validate_model,
)

OCF_ISSUE_423 = "https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/issues/423"


class OcfNoteTerms(FinancialBaseModel):
    """Terms ovf's ``ConvertibleNote`` requires that an OCF v1.2.0 convertible does not carry.

    No field has a default.

    * ``maturity_date``: OCF has no maturity field. Its only dated trigger,
      AUTOMATIC_ON_DATE, converts the note on that date instead of making it repayable.
    * ``qualified_financing_threshold``: OCF records the condition only as free text.
    * ``day_count``: OCF's ``ACTUAL_365`` does not say whether the year is fixed at 365
      days (OCF issue #423). The OCF value is checked against this one and is never its
      source.
    """

    model_config = ConfigDict(frozen=True)

    maturity_date: dt.date
    qualified_financing_threshold: float = Field(gt=0)
    day_count: DayCount


_TYPE_REFUSALS = {
    "SAFE": (
        "SAFEs are not mapped from OCF: ovf's exit engine rejects an unconverted SAFE, OCF's "
        "conversion_valuation_cap is optional where ovf's SAFE requires one, and OCF's "
        "capitalization_definition_rules may contradict the capitalization that ovf's SAFE "
        "solver fixes (docs/ocf.md)."
    ),
    "CONVERTIBLE_SECURITY": (
        "OCF defines no economics for this generic type, and ovf has no instrument for it."
    ),
}
_ELECTIVE = (
    "gives the holder an option to convert. ovf does not model optional conversion; the "
    "caller states the outcome of a holder election (docs/debt.md)."
)
_TRIGGER_REFUSALS = {
    "AUTOMATIC_ON_DATE": (
        "converts automatically on a date. ovf's ConvertibleNote is repaid at maturity; "
        "conversion on a date is not implemented (docs/debt.md, Not modelled)."
    ),
    "ELECTIVE_AT_WILL": _ELECTIVE,
    "ELECTIVE_IN_RANGE": _ELECTIVE,
    "ELECTIVE_ON_CONDITION": _ELECTIVE,
    "UNSPECIFIED": (
        "has no structured terms: OCF uses this type where the system of record 'cannot "
        "represent this data in a structured form'."
    ),
}


@dataclass
class NotesRead:
    """The notes built from a package, with the trace of how they were read."""

    notes: list[ConvertibleNote] = field(default_factory=list)
    seniority_ranks: dict[str, int] = field(default_factory=dict)
    qualified_financing_conditions: dict[str, str] = field(default_factory=dict)
    ignored_fields: list[str] = field(default_factory=list)
    currencies: set[str] = field(default_factory=set)


def _positive(text: str, where: str) -> Decimal:
    value = Decimal(text)
    if value <= 0:
        raise OcfUnsupportedError(f"{where} is {text}; ovf requires a positive amount.")
    return value


def _note_fields(
    tx: ConvertibleIssuance, terms: OcfNoteTerms | None, read: NotesRead
) -> dict[str, Any]:
    """ConvertibleNote fields for one issuance, except seniority; refuse anything else."""
    where = f"TX_CONVERTIBLE_ISSUANCE {tx.id!r}"
    if tx.convertible_type != "NOTE":
        raise OcfUnsupportedError(
            f"{where}.convertible_type is {tx.convertible_type}. "
            f"{_TYPE_REFUSALS[tx.convertible_type]}"
        )
    for index, trigger in enumerate(tx.conversion_triggers):
        if trigger.type != "AUTOMATIC_ON_CONDITION":
            raise OcfUnsupportedError(
                f"{where}.conversion_triggers[{index}] ({trigger.trigger_id!r}) is "
                f"{trigger.type}: it {_TRIGGER_REFUSALS[trigger.type]}"
            )
    if len(tx.conversion_triggers) != 1:
        raise OcfUnsupportedError(
            f"{where} has {len(tx.conversion_triggers)} AUTOMATIC_ON_CONDITION triggers. ovf "
            "reads exactly one, as the qualified financing; with several it would have to "
            "choose which one that is."
        )
    trigger = tx.conversion_triggers[0]
    right = trigger.conversion_right
    right_where = f"{where}.conversion_triggers[0].conversion_right"
    if right.type not in (None, "CONVERTIBLE_CONVERSION_RIGHT"):
        raise OcfUnsupportedError(
            f"{right_where}.type is {right.type}; a convertible note converts under a "
            "CONVERTIBLE_CONVERSION_RIGHT."
        )
    mwhere = f"{right_where}.conversion_mechanism"
    mechanism_type = right.conversion_mechanism.get("type")
    if mechanism_type != "CONVERTIBLE_NOTE_CONVERSION":
        raise OcfUnsupportedError(
            f"{mwhere}.type is {mechanism_type!r}. ovf reads a note only through "
            "CONVERTIBLE_NOTE_CONVERSION, the one OCF mechanism that carries interest terms."
        )
    m = validate_model(NoteConversionMechanism, right.conversion_mechanism, mwhere)

    if m.day_count_convention == "30_360":
        raise OcfUnsupportedError(
            f"{mwhere}.day_count_convention is 30_360. OCF does not say which 30/360 variant "
            "it means (30/360 US, Bond Basis, 30E/360, 30E/360 ISDA), and ovf implements none."
        )
    if m.interest_payout == "CASH":
        raise OcfUnsupportedError(
            f"{mwhere}.interest_payout is CASH. ovf's claim assumes no interest has been paid "
            "since issue, and OCF records no payment dates."
        )
    if m.compounding_type == "COMPOUNDING":
        raise OcfUnsupportedError(
            f"{mwhere}.compounding_type is COMPOUNDING. OCF v1.2.0 has a compounding type and "
            "an accrual period but no compounding frequency (OCF issue #423 works an example "
            "of daily accrual with annual compounding), and ovf requires an explicit frequency."
        )
    if m.interest_accrual_period != "DAILY":
        raise OcfUnsupportedError(
            f"{mwhere}.interest_accrual_period is {m.interest_accrual_period}. ovf's simple "
            "interest is principal x rate x days / 365, which is daily accrual; OCF does not "
            f"define how simple interest accrues over a {m.interest_accrual_period} period."
        )
    if len(m.interest_rates) != 1:
        detail = (
            "none; OCF describes them as 'if applicable', and ovf will not assume a 0% rate"
            if not m.interest_rates
            else "a schedule of rates; ovf's note has one rate from its issue date"
        )
        raise OcfUnsupportedError(
            f"{mwhere}.interest_rates has {len(m.interest_rates)} entries: {detail}."
        )
    rate = m.interest_rates[0]
    rate_where = f"{mwhere}.interest_rates[0]"
    if rate.rate == "":
        raise OcfUnsupportedError(
            f"{rate_where}.rate is the empty string. The OCF v1.2.0 Percentage pattern admits "
            "it, but it states no rate."
        )
    if rate.accrual_start_date != tx.date:
        raise OcfUnsupportedError(
            f"{rate_where}.accrual_start_date {rate.accrual_start_date} differs from the "
            f"issuance date {tx.date}; ovf accrues interest from the issue date."
        )
    if rate.accrual_end_date is not None:
        raise OcfUnsupportedError(
            f"{rate_where}.accrual_end_date is {rate.accrual_end_date}; ovf accrues until "
            "maturity and has no separate accrual end."
        )
    if m.exit_multiple is not None:
        raise OcfUnsupportedError(
            f"{mwhere}.exit_multiple is {m.exit_multiple.numerator}/"
            f"{m.exit_multiple.denominator}. OCF says only 'For cash proceeds calculation "
            "during a liquidity event', not whether it multiplies principal, principal plus "
            "interest, or replaces interest; ovf will not choose."
        )
    if m.conversion_mfn:
        raise OcfUnsupportedError(
            f"{mwhere}.conversion_mfn is true; most-favoured-nation terms are not modelled."
        )
    discount = Decimal(0)
    if m.conversion_discount is not None:
        if m.conversion_discount == "":
            raise OcfUnsupportedError(
                f"{mwhere}.conversion_discount is the empty string, which the OCF v1.2.0 "
                "Percentage pattern admits but which states no discount."
            )
        discount = Decimal(m.conversion_discount)
        if discount >= 1:
            raise OcfUnsupportedError(
                f"{mwhere}.conversion_discount is {m.conversion_discount}; a discount of 100% "
                "makes the conversion price zero."
            )
    cap: Decimal | None = None
    if m.conversion_valuation_cap is not None:
        cap = _positive(
            m.conversion_valuation_cap.amount, f"{mwhere}.conversion_valuation_cap.amount"
        )
        read.currencies.add(m.conversion_valuation_cap.currency)
    principal = _positive(tx.investment_amount.amount, f"{where}.investment_amount.amount")
    read.currencies.add(tx.investment_amount.currency)

    if terms is None:
        raise OcfUnsupportedError(
            f"{where} (security_id {tx.security_id!r}) has no note_terms. OCF v1.2.0 carries "
            "no maturity date and no structured qualified-financing threshold for a "
            "convertible, and its ACTUAL_365 does not settle the day count (OCF issue #423); "
            "ovf's ConvertibleNote requires all three. Pass note_terms={"
            f"{tx.security_id!r}: OcfNoteTerms(maturity_date=..., "
            "qualified_financing_threshold=..., day_count=...)}."
        )
    if not isinstance(terms, OcfNoteTerms):
        raise TypeError(f"note_terms[{tx.security_id!r}] must be an OcfNoteTerms")
    if terms.day_count is not DayCount.ACT_365_FIXED:
        raise OcfUnsupportedError(
            f"{mwhere}.day_count_convention is ACTUAL_365 but note_terms[{tx.security_id!r}]"
            f".day_count is {terms.day_count.value}. The two contradict each other; ovf "
            "prefers neither."
        )

    if m.capitalization_definition is not None or m.capitalization_definition_rules is not None:
        read.ignored_fields.append(
            f"{mwhere}.capitalization_definition(_rules): not read; ovf's "
            "ConvertibleNote.convert_at_financing takes capitalization_shares from the caller."
        )
    if tx.pro_rata is not None:
        read.ignored_fields.append(
            f"{where}.pro_rata = {tx.pro_rata}: pro-rata purchase rights do not change an exit "
            "payout and are not modelled."
        )
    read.qualified_financing_conditions[tx.security_id] = trigger.trigger_condition or ""
    return {
        "security_id": tx.security_id,
        "holder_id": tx.stakeholder_id,
        "principal": float(principal),
        "annual_rate": float(Decimal(rate.rate)),
        "accrual": AccrualMethod.SIMPLE,
        "compounding_frequency": None,
        "day_count": terms.day_count,
        "issue_date": tx.date,
        "maturity_date": terms.maturity_date,
        "valuation_cap": None if cap is None else float(cap),
        "discount_rate": float(discount),
        "qualified_financing_threshold": terms.qualified_financing_threshold,
    }


def read_notes(
    issuances: Sequence[ConvertibleIssuance], note_terms: Mapping[str, OcfNoteTerms]
) -> NotesRead:
    """Build one unresolved ``ConvertibleNote`` per issuance, or refuse naming the field.

    Notes come back with ``exit_treatment`` unset: OCF records no repayment outcome, so the
    caller must state one with ``ConvertibleNote.resolved`` before an exit.
    """
    read = NotesRead()
    fields: list[dict[str, Any]] = []
    ocf_seniority: dict[str, int] = {}
    for tx in issuances:
        fields.append(_note_fields(tx, note_terms.get(tx.security_id), read))
        ocf_seniority[tx.security_id] = tx.seniority
    unknown = sorted(set(note_terms) - set(ocf_seniority))
    if unknown:
        raise ValueError(
            f"note_terms given for security_ids that are not convertible issuances in this "
            f"package: {unknown}"
        )
    # "1 being highest seniority": ascending, the reverse of the StockClass ordering.
    levels = sorted(set(ocf_seniority.values()))
    rank_of = {level: index + 1 for index, level in enumerate(levels)}
    for values in fields:
        security_id = values["security_id"]
        rank = rank_of[ocf_seniority[security_id]]
        read.seniority_ranks[security_id] = rank
        try:
            read.notes.append(ConvertibleNote(**values, seniority=rank))
        except ValidationError as exc:
            details = "; ".join(error["msg"] for error in exc.errors())
            raise OcfUnsupportedError(
                f"TX_CONVERTIBLE_ISSUANCE for security_id {security_id!r}: ovf rejects the "
                f"note built from OCF and note_terms: {details}"
            ) from exc
    return read


def note_terms_from(table: CapTable) -> dict[str, OcfNoteTerms]:
    """The note terms ``to_ocf`` cannot express, keyed by security_id, for ``from_ocf``.

    Keep this alongside an exported package: OCF v1.2.0 has no place for these values, so
    reading the package back requires them to be supplied again.
    """
    terms: dict[str, OcfNoteTerms] = {}
    for security in table.securities:
        if isinstance(security, ConvertibleNote):
            assert security.maturity_date is not None  # required by ConvertibleNote
            terms[security.security_id] = OcfNoteTerms(
                maturity_date=security.maturity_date,
                qualified_financing_threshold=security.qualified_financing_threshold,
                day_count=security.day_count,
            )
    return terms


def note_assumptions() -> list[str]:
    return [
        "OCF ConvertibleIssuance.seniority: 1 is the highest, the opposite of "
        "StockClass.seniority. Read ascending into ovf debt ranks (1 paid first), which rank "
        "debt only; all debt is paid ahead of all equity.",
        "Each note's maturity_date, qualified_financing_threshold and day_count come from "
        "note_terms, not from OCF, which has no field for the first two and does not define "
        f"ACTUAL_365 ({OCF_ISSUE_423}).",
        "The qualified-financing trigger's trigger_condition text is not parsed; the caller "
        "asserts it agrees with the supplied qualified_financing_threshold.",
        "Notes are read unresolved: state the exit treatment with ConvertibleNote.resolved() "
        "before an exit.",
    ]
