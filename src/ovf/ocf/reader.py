"""Read an OCF v1.2.0 package into an ovf ``CapTable``.

OCF standardises cap-table data and defines no computation over it. This reader maps the
payout-relevant subset into ovf securities and refuses, with an error naming the field,
anything it would otherwise have to approximate. ``docs/ocf.md`` is the field-by-field
specification. The conventions that set numbers are:

* Seniority. OCF v1.2.0 ``StockClass.seniority``: "Seniority is ordered by increasing
  number so that stock classes with a higher seniority have higher repayment priority."
  ovf pays the lowest integer first, so the order is inverted: the distinct PREFERRED
  seniority values, highest first, become ovf ranks 1, 2, 3, ... Equal values share a rank
  and are paid pari passu, shortfalls split in proportion to preference (NVCA model
  certificate of incorporation, Oct 2025, section 2.1).
* Preference. ``liquidation_preference_multiple`` x ``StockClass.price_per_share`` per
  share. The NVCA model charter (section 2.1) sets the preference as a multiple of the
  class "Original Issue Price". A missing value refuses the class, and so does an
  issuance whose ``share_price`` differs from the class price, rather than choosing
  between them.
* Participation. OCF v1.2.0 has no participating flag. An absent
  ``participation_cap_multiple`` is read as non-participating. A present one means
  participating with a cap whose basis is ``participation_cap_basis`` (see
  ``ovf.ocf.schema.ParticipationCapBasis``).
* Conversion. Exactly one RATIO_CONVERSION right into a COMMON class. The ratio is
  ``numerator / denominator`` evaluated exactly, then converted to float once.
* Convertible notes (``ovf.ocf.notes``). ``ConvertibleIssuance.seniority`` runs the other
  way ("1 being highest seniority"), is read with its own comparator, and ranks debt only.
  Maturity, the qualified-financing threshold and the day count come from caller-supplied
  ``note_terms``, because OCF v1.2.0 does not carry them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Protocol, TypeVar, get_args

from pydantic import BaseModel, Field, JsonValue

from ovf.contracts.captable import CapTable
from ovf.contracts.securities import CommonStock, PreferredStock, Security, StockOptionPool
from ovf.core.types import FinancialBaseModel
from ovf.ocf.notes import OcfNoteTerms, note_assumptions, read_notes
from ovf.ocf.schema import (
    OCF_VERSION,
    ConvertibleIssuance,
    FileReference,
    Manifest,
    OcfIntegrityError,
    OcfPackage,
    OcfSchemaError,
    OcfUnsupportedError,
    ParticipationCapBasis,
    Ratio,
    StakeholdersFile,
    StockClass,
    StockClassConversionRatioAdjustment,
    StockClassesFile,
    StockIssuance,
    StockPlan,
    StockPlanPoolAdjustment,
    StockPlansFile,
    TransactionsFile,
)
from ovf.ocf.schema import validate_model as _validate

APPLIED_TRANSACTIONS: dict[str, str] = {
    "TX_STOCK_ISSUANCE": "Creates one ovf position per security_id.",
    "TX_CONVERTIBLE_ISSUANCE": (
        "A NOTE becomes one unresolved ovf ConvertibleNote per security_id, with maturity, "
        "qualified-financing threshold and day count supplied by note_terms; SAFE and "
        "CONVERTIBLE_SECURITY are refused."
    ),
    "TX_STOCK_PLAN_POOL_ADJUSTMENT": (
        "Sets the plan's reserved shares as of its date; the latest date wins."
    ),
    "TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT": (
        "Replaces the class conversion ratio as of its date; the latest date wins."
    ),
}

_VESTING_REASON = (
    "ovf treats issued stock as outstanding and entitled at exit whether vested or not; "
    "option vesting is moot because option grants are refused."
)
IGNORED_TRANSACTIONS: dict[str, str] = {
    "TX_STOCK_ACCEPTANCE": (
        "Records the holder's acceptance; shares, class and holder are unchanged."
    ),
    "TX_CONVERTIBLE_ACCEPTANCE": (
        "Records the holder's acceptance; the convertible's amount, terms and holder are unchanged."
    ),
    "TX_ISSUER_AUTHORIZED_SHARES_ADJUSTMENT": "Changes authorized, not issued, shares.",
    "TX_STOCK_CLASS_AUTHORIZED_SHARES_ADJUSTMENT": "Changes authorized, not issued, shares.",
    "TX_VESTING_START": _VESTING_REASON,
    "TX_VESTING_EVENT": _VESTING_REASON,
    "TX_VESTING_ACCELERATION": _VESTING_REASON,
}

_PLAN_AWARD_REASON = (
    "Granted options, RSUs and other plan awards need strike, vesting and settlement terms "
    "that ovf does not model (docs/limitations.md)."
)
_PLAN_AWARD_ACTIONS = (
    "ACCEPTANCE",
    "CANCELLATION",
    "EXERCISE",
    "ISSUANCE",
    "RELEASE",
    "RETRACTION",
    "TRANSFER",
)
_INSTRUMENT_ACTIONS = ("ACCEPTANCE", "CANCELLATION", "ISSUANCE", "RETRACTION", "TRANSFER")
REFUSED_TRANSACTIONS: dict[str, str] = {
    "TX_STOCK_CANCELLATION": "Reduces or removes an outstanding stock position; not applied.",
    "TX_STOCK_REPURCHASE": "Removes repurchased shares from a holder; not applied.",
    "TX_STOCK_RETRACTION": "Voids an issuance as if it never happened; not applied.",
    "TX_STOCK_TRANSFER": "Moves shares to another stakeholder; not applied.",
    "TX_STOCK_CONVERSION": "Converts stock into another class; not applied.",
    "TX_STOCK_REISSUANCE": "Replaces a security with new securities; not applied.",
    "TX_STOCK_CLASS_SPLIT": (
        "Changes every share count in the class and, under the NVCA model charter, the "
        "Original Issue Price; not applied."
    ),
    "TX_STOCK_PLAN_RETURN_TO_POOL": (
        "Returns plan-security shares to the pool; plan securities are not supported."
    ),
    **{f"TX_EQUITY_COMPENSATION_{action}": _PLAN_AWARD_REASON for action in _PLAN_AWARD_ACTIONS},
    **{f"TX_PLAN_SECURITY_{action}": _PLAN_AWARD_REASON for action in _PLAN_AWARD_ACTIONS},
    **{
        f"TX_WARRANT_{action}": (
            "Warrants are not a supported ovf instrument (docs/ocf.md, 'What a warrant model "
            "would have to carry')."
        )
        for action in (*_INSTRUMENT_ACTIONS, "EXERCISE")
    },
    "TX_CONVERTIBLE_CANCELLATION": "Cancels all or part of a convertible's amount; not applied.",
    "TX_CONVERTIBLE_RETRACTION": "Voids a convertible issuance as if it never happened; not applied.",
    "TX_CONVERTIBLE_TRANSFER": "Moves a convertible to another stakeholder; not applied.",
    "TX_CONVERTIBLE_CONVERSION": (
        "Converts a convertible into other securities; retiring the note against its "
        "resulting issuances is not applied."
    ),
}

_UNREAD_FILE_LISTS = (
    "stock_legend_templates_files",
    "vesting_terms_files",
    "valuations_files",
    "financings_files",
    "documents_files",
)


class OcfImport(FinancialBaseModel):
    """A cap table read from OCF, with the trace of how it was read."""

    cap_table: CapTable
    ocf_version: str
    issuer_legal_name: str
    as_of: dt.date
    currency: str | None = Field(description="The single currency of all read amounts")
    participation_cap_basis: ParticipationCapBasis
    seniority_ranks: dict[str, int] = Field(
        description="PREFERRED stock_class_id -> ovf seniority, where 1 is paid first"
    )
    debt_seniority_ranks: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Convertible note security_id -> ovf debt seniority, where 1 is paid first. "
            "Ranks debt only; every debt position is paid ahead of all equity."
        ),
    )
    qualified_financing_conditions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Convertible note security_id -> the OCF trigger_condition text that the "
            "supplied qualified_financing_threshold stands for. Not parsed."
        ),
    )
    applied_transactions: list[str]
    ignored_transactions: list[str]
    ignored_fields: list[str]
    unread_files: list[str]
    assumptions: list[str]


# ---------------------------------------------------------------------------
# Loading files
# ---------------------------------------------------------------------------

_M = TypeVar("_M", bound=BaseModel)


def _reject_constant(name: str) -> None:
    raise OcfSchemaError(f"JSON constant {name} is not valid in OCF")


def _parse_json(data: bytes, where: str) -> object:
    try:
        return json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OcfSchemaError(f"{where} is not valid UTF-8 JSON: {exc}") from exc


def _find_manifest(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.is_dir():
        raise OcfSchemaError(f"{path} is neither an OCF manifest file nor a directory")
    found = []
    for candidate in sorted(path.glob("*.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("file_type") == "OCF_MANIFEST_FILE":
            found.append(candidate)
    if len(found) != 1:
        raise OcfSchemaError(
            f"{path} must contain exactly one OCF_MANIFEST_FILE JSON file; found {len(found)}"
        )
    return found[0]


def _load_files(
    base: Path, refs: Sequence[FileReference], model: type[_M], verify_md5: bool
) -> list[_M]:
    loaded = []
    for ref in refs:
        filepath = ref.filepath
        expected = ref.md5
        target = (base / filepath).resolve()
        if not target.is_relative_to(base):
            raise OcfSchemaError(f"{filepath} resolves outside the package directory")
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise OcfSchemaError(
                f"{filepath} is listed in the manifest but unreadable: {exc}"
            ) from exc
        if verify_md5:
            actual = hashlib.md5(data, usedforsecurity=False).hexdigest()
            if actual != expected.lower():
                raise OcfIntegrityError(
                    f"{filepath}: manifest md5 is {expected} but the file hashes to {actual}. "
                    "Pass verify_md5=False to read it anyway (OCF's own v1.2.0 sample "
                    "package carries placeholder checksums)."
                )
        loaded.append(_validate(model, _parse_json(data, filepath), filepath))
    return loaded


def load_ocf_package(path: str | os.PathLike[str], *, verify_md5: bool = True) -> OcfPackage:
    """Load an OCF v1.2.0 package from a directory or from its manifest file.

    A directory must contain exactly one JSON file whose ``file_type`` is
    ``OCF_MANIFEST_FILE``. Referenced files resolve relative to the manifest and must stay
    inside its directory. ZIP containers are not read. Stock classes, stakeholders, stock
    plans and transactions are opened and validated; every other file list is recorded in
    ``unread_files`` without being opened.
    """
    manifest_path = _find_manifest(Path(path))
    raw = _parse_json(manifest_path.read_bytes(), manifest_path.name)
    if not isinstance(raw, dict):
        raise OcfSchemaError(f"{manifest_path.name} is not a JSON object")
    version = raw.get("ocf_version")
    if version != OCF_VERSION:
        raise OcfUnsupportedError(
            f"{manifest_path.name}: ocf_version {version!r} is not supported; "
            f"this adapter targets OCF {OCF_VERSION} only"
        )
    manifest = _validate(Manifest, raw, manifest_path.name)
    base = manifest_path.parent.resolve()
    unread = [
        f"{name}: {ref.filepath}"
        for name in _UNREAD_FILE_LISTS
        for ref in (getattr(manifest, name) or ())
    ]
    return OcfPackage(
        ocf_version=manifest.ocf_version,
        issuer=manifest.issuer,
        as_of=manifest.as_of,
        generated_at=manifest.generated_at,
        comments=manifest.comments or (),
        stock_classes=tuple(
            item
            for file in _load_files(
                base, manifest.stock_classes_files, StockClassesFile, verify_md5
            )
            for item in file.items
        ),
        stakeholders=tuple(
            item
            for file in _load_files(base, manifest.stakeholders_files, StakeholdersFile, verify_md5)
            for item in file.items
        ),
        stock_plans=tuple(
            item
            for file in _load_files(base, manifest.stock_plans_files, StockPlansFile, verify_md5)
            for item in file.items
        ),
        transactions=tuple(
            item
            for file in _load_files(base, manifest.transactions_files, TransactionsFile, verify_md5)
            for item in file.items
        ),
        unread_files=tuple(unread),
    )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


_I = TypeVar("_I", bound=_Identified)


def _index(objects: Iterable[_I], kind: str) -> dict[str, _I]:
    index: dict[str, _I] = {}
    for obj in objects:
        if obj.id in index:
            raise OcfSchemaError(f"Duplicate {kind} id {obj.id!r}")
        index[obj.id] = obj
    return index


def _nonnegative(text: str, where: str) -> Decimal:
    value = Decimal(text)
    if value < 0:
        raise OcfUnsupportedError(f"{where} is negative ({text})")
    return value


def _ratio(ratio: Ratio, where: str) -> Fraction:
    numerator = Fraction(Decimal(ratio.numerator))
    denominator = Fraction(Decimal(ratio.denominator))
    if numerator <= 0 or denominator <= 0:
        raise OcfUnsupportedError(
            f"{where} must have a positive numerator and denominator; "
            f"got {ratio.numerator}/{ratio.denominator}"
        )
    return numerator / denominator


@dataclass(frozen=True)
class _PreferredTerms:
    price: Decimal
    currency: str
    liquidation_multiple: Decimal
    cap_total: Decimal | None
    ratio: Fraction
    seniority: Decimal


def _check_common_class(
    stock_class: StockClass, ignore_preference_fields: bool, ignored: list[str]
) -> None:
    where = f"COMMON StockClass {stock_class.id!r}"
    if stock_class.conversion_rights:
        raise OcfUnsupportedError(
            f"{where} has conversion_rights. ovf pays all common from one residual and does "
            "not model conversion between common classes."
        )
    for name in ("liquidation_preference_multiple", "participation_cap_multiple"):
        value = getattr(stock_class, name)
        if value is None:
            continue
        if not ignore_preference_fields:
            raise OcfUnsupportedError(
                f"{where}.{name} is {value}. ovf pays common only from the residual after "
                "preferred preferences and cannot represent this term on common. OCF's own "
                "v1.2.0 sample sets it on its common class as apparent placeholder data; to "
                "treat it as placeholder, pass ignore_common_preference_fields=True."
            )
        ignored.append(f"{where}.{name} = {value} (ignore_common_preference_fields=True)")


def _preferred_terms(
    stock_class: StockClass, classes: Mapping[str, StockClass], basis: ParticipationCapBasis
) -> _PreferredTerms:
    where = f"PREFERRED StockClass {stock_class.id!r}"
    if stock_class.price_per_share is None:
        raise OcfUnsupportedError(
            f"{where} has no price_per_share. ovf bases the liquidation preference on the "
            "class Original Issue Price (NVCA model charter section 2.1) and will not infer "
            "it from conversion_price or from issuance prices."
        )
    price = _nonnegative(stock_class.price_per_share.amount, f"{where}.price_per_share.amount")
    if stock_class.liquidation_preference_multiple is None:
        raise OcfUnsupportedError(
            f"{where} has no liquidation_preference_multiple; ovf will not assume 1x."
        )
    multiple = _nonnegative(
        stock_class.liquidation_preference_multiple, f"{where}.liquidation_preference_multiple"
    )
    cap_total: Decimal | None = None
    if stock_class.participation_cap_multiple is not None:
        cap = _nonnegative(
            stock_class.participation_cap_multiple, f"{where}.participation_cap_multiple"
        )
        if basis == "participation_only":
            cap_total = multiple + cap
        elif cap < multiple:
            raise OcfUnsupportedError(
                f"{where}.participation_cap_multiple {cap} is below "
                f"liquidation_preference_multiple {multiple}. Under "
                "participation_cap_basis='total' the cap includes the preference (NVCA model "
                "charter section 2.2, 'Maximum Participation Amount' footnote), so it cannot "
                "be met. If the system of record caps the participation alone, pass "
                "participation_cap_basis='participation_only'."
            )
        else:
            cap_total = cap

    rights = stock_class.conversion_rights or ()
    if len(rights) != 1:
        raise OcfUnsupportedError(
            f"{where} has {len(rights)} conversion_rights; ovf requires exactly one. With none, "
            "the class could not convert, and every ovf preferred position can. With several, "
            "ovf would have to choose between them."
        )
    right = rights[0]
    right_where = f"{where}.conversion_rights[0]"
    if right.converts_to_future_round:
        raise OcfUnsupportedError(
            f"{right_where}.converts_to_future_round is true; conversion into an undetermined "
            "future class cannot be valued."
        )
    target_id = right.converts_to_stock_class_id
    if target_id is None:
        raise OcfUnsupportedError(f"{right_where} has no converts_to_stock_class_id")
    target = classes.get(target_id)
    if target is None:
        raise OcfSchemaError(
            f"{right_where}.converts_to_stock_class_id {target_id!r} is not a stock class "
            "in this package"
        )
    if target.class_type != "COMMON":
        raise OcfUnsupportedError(
            f"{where} converts into {target.class_type} class {target_id!r}; ovf models "
            "conversion into common only."
        )
    return _PreferredTerms(
        price=price,
        currency=stock_class.price_per_share.currency,
        liquidation_multiple=multiple,
        cap_total=cap_total,
        ratio=_ratio(right.conversion_mechanism.ratio, f"{right_where}.conversion_mechanism.ratio"),
        seniority=Decimal(stock_class.seniority),
    )


def _check_seniority_order(
    classes: Mapping[str, StockClass], preferred: Mapping[str, _PreferredTerms]
) -> None:
    common_levels = sorted(
        {Decimal(c.seniority) for c in classes.values() if c.class_type == "COMMON"}
    )
    if len(common_levels) > 1:
        raise OcfUnsupportedError(
            "COMMON stock classes have different seniority values "
            f"{[str(v) for v in common_levels]}. ovf pays all common from one residual and "
            "cannot rank one common class ahead of another."
        )
    if not common_levels:
        return
    level = common_levels[0]
    blocking = sorted(class_id for class_id, t in preferred.items() if t.seniority <= level)
    if blocking:
        raise OcfUnsupportedError(
            f"PREFERRED stock classes {blocking} have seniority at or below the COMMON "
            f"seniority {level}. OCF repays a higher seniority first, so these would rank "
            "level with or behind common, which ovf cannot represent."
        )


def _seniority_ranks(preferred: Mapping[str, _PreferredTerms]) -> dict[str, int]:
    """Invert OCF seniority (higher repaid first) into ovf ranks (1 repaid first)."""
    levels = sorted({t.seniority for t in preferred.values()}, reverse=True)
    rank_of = {level: index + 1 for index, level in enumerate(levels)}
    return {class_id: rank_of[t.seniority] for class_id, t in preferred.items()}


_V = TypeVar("_V")


def _latest(entries: Sequence[tuple[dt.date, str, _V]], what: str) -> _V:
    """Value of the latest-dated entry; refuse if several entries share that date and differ."""
    latest = max(date for date, _, _ in entries)
    on_latest = [(tx_id, value) for date, tx_id, value in entries if date == latest]
    if len({value for _, value in on_latest}) > 1:
        raise OcfUnsupportedError(
            f"{what}: adjustments {[tx_id for tx_id, _ in on_latest]} are all dated "
            f"{latest} and disagree; OCF gives no order within a day."
        )
    return on_latest[-1][1]


@dataclass
class _Classified:
    issuances: list[StockIssuance]
    convertibles: list[ConvertibleIssuance]
    pool_adjustments: list[StockPlanPoolAdjustment]
    ratio_adjustments: list[StockClassConversionRatioAdjustment]
    ignored: list[str]


def _classify(transactions: Sequence[Mapping[str, JsonValue]]) -> _Classified:
    issuances: list[StockIssuance] = []
    convertibles: list[ConvertibleIssuance] = []
    pool_adjustments: list[StockPlanPoolAdjustment] = []
    ratio_adjustments: list[StockClassConversionRatioAdjustment] = []
    ignored: list[str] = []
    for index, raw in enumerate(transactions):
        object_type = raw.get("object_type")
        tx_id = raw.get("id")
        where = f"transaction {tx_id!r}" if isinstance(tx_id, str) else f"transactions[{index}]"
        if object_type == "TX_STOCK_ISSUANCE":
            issuances.append(_validate(StockIssuance, raw, where))
        elif object_type == "TX_CONVERTIBLE_ISSUANCE":
            convertibles.append(_validate(ConvertibleIssuance, raw, where))
        elif object_type == "TX_STOCK_PLAN_POOL_ADJUSTMENT":
            pool_adjustments.append(_validate(StockPlanPoolAdjustment, raw, where))
        elif object_type == "TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT":
            ratio_adjustments.append(_validate(StockClassConversionRatioAdjustment, raw, where))
        elif isinstance(object_type, str) and object_type in IGNORED_TRANSACTIONS:
            ignored.append(f"{object_type} {tx_id}")
        elif isinstance(object_type, str) and object_type in REFUSED_TRANSACTIONS:
            raise OcfUnsupportedError(
                f"{where}: {object_type} is not supported. {REFUSED_TRANSACTIONS[object_type]}"
            )
        else:
            raise OcfSchemaError(
                f"{where}: object_type {object_type!r} is not an OCF v1.2.0 transaction type"
            )
    return _Classified(issuances, convertibles, pool_adjustments, ratio_adjustments, ignored)


def _check_basis(basis: str) -> None:
    if basis not in get_args(ParticipationCapBasis):
        raise ValueError(
            f"participation_cap_basis must be one of {get_args(ParticipationCapBasis)}; "
            f"got {basis!r}"
        )


def import_ocf(
    source: OcfPackage | str | os.PathLike[str],
    *,
    participation_cap_basis: ParticipationCapBasis = "total",
    ignore_common_preference_fields: bool = False,
    verify_md5: bool = True,
    note_terms: Mapping[str, OcfNoteTerms] | None = None,
) -> OcfImport:
    """Read an OCF v1.2.0 package into a cap table and report how it was read.

    ``source`` is an in-memory ``OcfPackage``, a package directory or its manifest file.
    Raises ``OcfUnsupportedError`` naming the field for any right ovf cannot represent,
    ``OcfSchemaError`` for input that is not v1.2.0-shaped or not internally consistent,
    and ``OcfIntegrityError`` for a checksum mismatch. The module docstring states the
    conventions that set numbers; ``OcfImport.assumptions`` repeats them per import.

    ``note_terms`` maps each convertible note's security_id to the ``OcfNoteTerms`` OCF
    does not carry. A NOTE without an entry is refused, and so is an entry for a
    security_id that is not a convertible issuance in the package.
    """
    _check_basis(participation_cap_basis)
    package = (
        source
        if isinstance(source, OcfPackage)
        else load_ocf_package(source, verify_md5=verify_md5)
    )
    classes = _index(package.stock_classes, "StockClass")
    stakeholders = _index(package.stakeholders, "Stakeholder")
    plans = _index(package.stock_plans, "StockPlan")

    ignored_fields: list[str] = []
    preferred: dict[str, _PreferredTerms] = {}
    for stock_class in package.stock_classes:
        if stock_class.class_type == "COMMON":
            _check_common_class(stock_class, ignore_common_preference_fields, ignored_fields)
        else:
            preferred[stock_class.id] = _preferred_terms(
                stock_class, classes, participation_cap_basis
            )
    _check_seniority_order(classes, preferred)

    classified = _classify(package.transactions)
    issuances = classified.issuances
    pool_adjustments = classified.pool_adjustments
    ratio_adjustments = classified.ratio_adjustments
    applied: list[
        StockIssuance
        | ConvertibleIssuance
        | StockPlanPoolAdjustment
        | StockClassConversionRatioAdjustment
    ]
    applied = [*issuances, *classified.convertibles, *pool_adjustments, *ratio_adjustments]
    for tx in applied:
        if tx.date > package.as_of:
            raise OcfUnsupportedError(
                f"{tx.object_type} {tx.id!r} is dated {tx.date}, after the package as_of "
                f"{package.as_of}; the package would not describe the state it claims."
            )

    ratio_entries: dict[str, list[tuple[dt.date, str, Fraction]]] = {}
    for adjustment in ratio_adjustments:
        where = f"{adjustment.object_type} {adjustment.id!r}"
        if adjustment.stock_class_id not in classes:
            raise OcfSchemaError(
                f"{where} references unknown stock_class_id {adjustment.stock_class_id!r}"
            )
        if adjustment.stock_class_id not in preferred:
            raise OcfUnsupportedError(
                f"{where} adjusts COMMON class {adjustment.stock_class_id!r}, which has no "
                "conversion right in ovf's reading."
            )
        ratio = _ratio(
            adjustment.new_ratio_conversion_mechanism.ratio,
            f"{where}.new_ratio_conversion_mechanism.ratio",
        )
        ratio_entries.setdefault(adjustment.stock_class_id, []).append(
            (adjustment.date, adjustment.id, ratio)
        )
    for class_id, entries in ratio_entries.items():
        ratio = _latest(entries, f"conversion ratio of StockClass {class_id!r}")
        preferred[class_id] = replace(preferred[class_id], ratio=ratio)

    ranks = _seniority_ranks(preferred)
    currencies = {t.currency for t in preferred.values()}
    securities: list[Security] = []
    for tx in issuances:
        where = f"TX_STOCK_ISSUANCE {tx.id!r}"
        if tx.stakeholder_id not in stakeholders:
            raise OcfSchemaError(f"{where} references unknown stakeholder {tx.stakeholder_id!r}")
        issued_class = classes.get(tx.stock_class_id)
        if issued_class is None:
            raise OcfSchemaError(f"{where} references unknown stock_class_id {tx.stock_class_id!r}")
        if tx.stock_plan_id is not None:
            raise OcfUnsupportedError(
                f"{where}.stock_plan_id is {tx.stock_plan_id!r}. Stock issued from a plan "
                "consumes pool capacity, which ovf would have to net against the pool "
                "reserve; that accounting is not implemented."
            )
        quantity = _nonnegative(tx.quantity, f"{where}.quantity")
        share_price = _nonnegative(tx.share_price.amount, f"{where}.share_price.amount")
        currencies.add(tx.share_price.currency)
        if issued_class.class_type == "COMMON":
            securities.append(
                CommonStock(
                    security_id=tx.security_id,
                    holder_id=tx.stakeholder_id,
                    shares=float(quantity),
                    price=float(share_price),
                )
            )
            continue
        terms = preferred[issued_class.id]
        if share_price != terms.price or tx.share_price.currency != terms.currency:
            raise OcfUnsupportedError(
                f"{where}.share_price {tx.share_price.amount} {tx.share_price.currency} "
                f"differs from StockClass {issued_class.id!r} price_per_share {terms.price} "
                f"{terms.currency}. ovf would have to choose which price bases the preference."
            )
        securities.append(
            PreferredStock(
                security_id=tx.security_id,
                holder_id=tx.stakeholder_id,
                shares=float(quantity),
                price=float(terms.price),
                seniority=ranks[issued_class.id],
                liquidation_multiple=float(terms.liquidation_multiple),
                participating=terms.cap_total is not None,
                participation_cap=None if terms.cap_total is None else float(terms.cap_total),
                conversion_ratio=float(terms.ratio),
            )
        )

    for convertible in classified.convertibles:
        if convertible.stakeholder_id not in stakeholders:
            raise OcfSchemaError(
                f"TX_CONVERTIBLE_ISSUANCE {convertible.id!r} references unknown stakeholder "
                f"{convertible.stakeholder_id!r}"
            )
    notes = read_notes(classified.convertibles, note_terms or {})
    securities.extend(notes.notes)
    currencies |= notes.currencies
    ignored_fields.extend(notes.ignored_fields)

    pool_entries: dict[str, list[tuple[dt.date, str, Decimal]]] = {}
    for pool_adjustment in pool_adjustments:
        where = f"{pool_adjustment.object_type} {pool_adjustment.id!r}"
        if pool_adjustment.stock_plan_id not in plans:
            raise OcfSchemaError(
                f"{where} references unknown stock_plan_id {pool_adjustment.stock_plan_id!r}"
            )
        reserved = _nonnegative(pool_adjustment.shares_reserved, f"{where}.shares_reserved")
        pool_entries.setdefault(pool_adjustment.stock_plan_id, []).append(
            (pool_adjustment.date, pool_adjustment.id, reserved)
        )
    for plan in package.stock_plans:
        securities.append(_pool(plan, classes, pool_entries.get(plan.id)))

    seen: set[str] = set()
    for security in securities:
        if security.security_id in seen:
            raise OcfSchemaError(
                f"security_id {security.security_id!r} appears twice (issuance security_ids "
                "and stock plan ids must be distinct, because both become ovf security_ids)"
            )
        seen.add(security.security_id)
    if len(currencies) > 1:
        raise OcfUnsupportedError(
            f"Amounts use several currencies {sorted(currencies)}; ovf has one base currency "
            "and performs no FX conversion."
        )
    currency = next(iter(currencies), None)

    return OcfImport(
        cap_table=CapTable(securities=securities),
        ocf_version=package.ocf_version,
        issuer_legal_name=package.issuer.legal_name,
        as_of=package.as_of,
        currency=currency,
        participation_cap_basis=participation_cap_basis,
        seniority_ranks=ranks,
        debt_seniority_ranks=notes.seniority_ranks,
        qualified_financing_conditions=notes.qualified_financing_conditions,
        applied_transactions=[f"{tx.object_type} {tx.id}" for tx in applied],
        ignored_transactions=classified.ignored,
        ignored_fields=ignored_fields,
        unread_files=list(package.unread_files),
        assumptions=[
            *_assumptions(participation_cap_basis, currency),
            *(note_assumptions() if notes.notes else []),
        ],
    )


def _pool(
    plan: StockPlan,
    classes: Mapping[str, StockClass],
    adjustments: Sequence[tuple[dt.date, str, Decimal]] | None,
) -> StockOptionPool:
    where = f"StockPlan {plan.id!r}"
    for class_id in plan.class_ids:
        stock_class = classes.get(class_id)
        if stock_class is None:
            raise OcfSchemaError(f"{where} references unknown stock class {class_id!r}")
        if stock_class.class_type != "COMMON":
            raise OcfUnsupportedError(
                f"{where} reserves {stock_class.class_type} class {class_id!r}; ovf's option "
                "pool is common-equivalent capacity only."
            )
    reserved = _nonnegative(plan.initial_shares_reserved, f"{where}.initial_shares_reserved")
    if adjustments:
        reserved = _latest(adjustments, f"reserved shares of {where}")
    return StockOptionPool(
        security_id=plan.id,
        holder_id=plan.id,
        reserved_shares=float(reserved),
        allocated_shares=0.0,
        price=0.0,
    )


def _assumptions(basis: ParticipationCapBasis, currency: str | None) -> list[str]:
    cap = (
        "participation_cap_multiple includes the preference (NVCA model charter section 2.2, "
        "'Maximum Participation Amount' footnote)."
        if basis == "total"
        else "participation_cap_multiple bounds participation on top of the preference."
    )
    return [
        "OCF v1.2.0 StockClass.seniority: a higher number is repaid first. Inverted into ovf "
        "ranks, where 1 is paid first; equal values are pari passu.",
        "Preferred preference per share = liquidation_preference_multiple x "
        "StockClass.price_per_share (NVCA model charter section 2.1, Original Issue Price).",
        "An absent participation_cap_multiple means non-participating; " + cap,
        "Each issuance security_id is one independent ovf position held by its stakeholder.",
        "All COMMON classes share the residual per share; OCF v1.2.0 has no field for "
        "unequal common economics.",
        "Issued stock is outstanding and entitled at exit whether or not it has vested.",
        "Stock plans become unallocated option pools; OCF plans have no holder, so the plan "
        "id is used as holder_id.",
        f"All amounts are in {currency}; no FX conversion."
        if currency
        else "No monetary amounts were read.",
    ]


def from_ocf(
    source: OcfPackage | str | os.PathLike[str],
    *,
    participation_cap_basis: ParticipationCapBasis = "total",
    ignore_common_preference_fields: bool = False,
    verify_md5: bool = True,
    note_terms: Mapping[str, OcfNoteTerms] | None = None,
) -> CapTable:
    """Read an OCF v1.2.0 package into a ``CapTable``; see ``import_ocf`` for the trace."""
    return import_ocf(
        source,
        participation_cap_basis=participation_cap_basis,
        ignore_common_preference_fields=ignore_common_preference_fields,
        verify_md5=verify_md5,
        note_terms=note_terms,
    ).cap_table
