"""Typed models for the subset of Open Cap Format (OCF) v1.2.0 that ovf reads and writes.

Target: OCF v1.2.0, tag commit ``9f987b48e288703ff2cd6c4534f7769bb04e724a`` (2024-08-21),
https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/tree/v1.2.0/schema

Each object model declares every property the v1.2.0 JSON Schema allows for that object
and forbids anything else, as the schema's ``additionalProperties: false`` does. Declaring
a property here does not mean ovf honours it: ``docs/ocf.md`` lists, field by field, what
feeds the cap table, what is refused and what is ignored. Properties ovf never reads are
typed as opaque JSON so that they survive validation unchanged.

Numbers stay as OCF's fixed-point strings (``Numeric``) so nothing is rounded on the way
in; conversion to float happens once, at the ovf boundary, in ``reader.py``.

The OCF schema files are distributed under the Open Cap Table Coalition "Schema and
Documentation License v1.0.1", which is not an OSI-approved licence. This module restates
field names and constraints for interoperability; it does not copy schema files.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal, Self, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

OCF_VERSION = "1.2.0"
OCF_SCHEMA_COMMIT = "9f987b48e288703ff2cd6c4534f7769bb04e724a"
OCF_SCHEMA_URL = (
    "https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/tree/v1.2.0/schema"
)

# types/Numeric: "Fixed-point string representation of a number (up to 10 decimal places)".
NUMERIC_PATTERN = r"^[+-]?[0-9]+(\.[0-9]{1,10})?$"
NUMERIC_MAX_DECIMALS = 10

Numeric = Annotated[str, StringConstraints(pattern=NUMERIC_PATTERN)]
# types/Percentage: "a percentage as a decimal between 0.0 and 1.0 (up to 10 decimal places
# supported)". Restated exactly, including its defect: both alternatives make every part
# optional, so the empty string matches. The reader refuses an empty percentage explicitly.
PERCENTAGE_PATTERN = r"^0?(\.[0-9]{1,10})?$|^1(\.0{1,10})?$"
Percentage = Annotated[str, StringConstraints(pattern=PERCENTAGE_PATTERN)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Md5 = Annotated[str, StringConstraints(pattern=r"^[a-fA-F0-9]{32}$")]
AuthorizedShares = Literal["NOT APPLICABLE", "UNLIMITED"]

ParticipationCapBasis = Literal["total", "participation_only"]
"""How ``StockClass.participation_cap_multiple`` relates to the preference.

``"total"`` (default): the cap bounds the aggregate of preference and participation, as in
the NVCA model certificate of incorporation (Oct 2025), section 2.2 and its drafting
footnote defining the "Maximum Participation Amount". This is what
``PreferredStock.participation_cap`` already means. ``"participation_only"``: the cap
bounds the participation received on top of the preference. OCF v1.2.0 does not say which.
"""

# enums/ObjectType, v1.2.0: every transaction object type the format defines.
TRANSACTION_OBJECT_TYPES: tuple[str, ...] = (
    "TX_ISSUER_AUTHORIZED_SHARES_ADJUSTMENT",
    "TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT",
    "TX_STOCK_CLASS_AUTHORIZED_SHARES_ADJUSTMENT",
    "TX_STOCK_CLASS_SPLIT",
    "TX_STOCK_PLAN_POOL_ADJUSTMENT",
    "TX_STOCK_PLAN_RETURN_TO_POOL",
    "TX_CONVERTIBLE_ACCEPTANCE",
    "TX_CONVERTIBLE_CANCELLATION",
    "TX_CONVERTIBLE_CONVERSION",
    "TX_CONVERTIBLE_ISSUANCE",
    "TX_CONVERTIBLE_RETRACTION",
    "TX_CONVERTIBLE_TRANSFER",
    "TX_EQUITY_COMPENSATION_ACCEPTANCE",
    "TX_EQUITY_COMPENSATION_CANCELLATION",
    "TX_EQUITY_COMPENSATION_EXERCISE",
    "TX_EQUITY_COMPENSATION_ISSUANCE",
    "TX_EQUITY_COMPENSATION_RELEASE",
    "TX_EQUITY_COMPENSATION_RETRACTION",
    "TX_EQUITY_COMPENSATION_TRANSFER",
    "TX_PLAN_SECURITY_ACCEPTANCE",
    "TX_PLAN_SECURITY_CANCELLATION",
    "TX_PLAN_SECURITY_EXERCISE",
    "TX_PLAN_SECURITY_ISSUANCE",
    "TX_PLAN_SECURITY_RELEASE",
    "TX_PLAN_SECURITY_RETRACTION",
    "TX_PLAN_SECURITY_TRANSFER",
    "TX_STOCK_ACCEPTANCE",
    "TX_STOCK_CANCELLATION",
    "TX_STOCK_CONVERSION",
    "TX_STOCK_ISSUANCE",
    "TX_STOCK_REISSUANCE",
    "TX_STOCK_REPURCHASE",
    "TX_STOCK_RETRACTION",
    "TX_STOCK_TRANSFER",
    "TX_WARRANT_ACCEPTANCE",
    "TX_WARRANT_CANCELLATION",
    "TX_WARRANT_EXERCISE",
    "TX_WARRANT_ISSUANCE",
    "TX_WARRANT_RETRACTION",
    "TX_WARRANT_TRANSFER",
    "TX_VESTING_ACCELERATION",
    "TX_VESTING_START",
    "TX_VESTING_EVENT",
)


class OcfError(ValueError):
    """Base class for every error raised by the OCF adapter."""


class OcfSchemaError(OcfError):
    """The input does not have the shape OCF v1.2.0 defines for it."""


class OcfIntegrityError(OcfError):
    """A file's MD5 checksum does not match its manifest entry."""


class OcfUnsupportedError(OcfError):
    """Valid OCF that expresses something ovf cannot represent without guessing.

    The message names the object, the field and the reason. Nothing is approximated.
    """


class OcfModel(BaseModel):
    """Strict, immutable OCF object: unknown properties are rejected, as in the schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


_M = TypeVar("_M", bound=BaseModel)


def validate_model(model: type[_M], data: object, where: str) -> _M:
    """Validate ``data`` as ``model``; a failure becomes an ``OcfSchemaError`` naming the path."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()
        )
        raise OcfSchemaError(
            f"{where} does not match OCF v1.2.0 {model.__name__}: {details}"
        ) from exc


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Monetary(OcfModel):
    """types/Monetary: an amount in one ISO 4217 currency."""

    amount: Numeric
    currency: CurrencyCode


class Ratio(OcfModel):
    """types/Ratio: numerator and denominator of A:B, i.e. the fraction A/B."""

    numerator: Numeric
    denominator: Numeric


class Name(OcfModel):
    """types/Name."""

    legal_name: str
    first_name: str | None = None
    last_name: str | None = None


class RatioConversionMechanism(OcfModel):
    """types/conversion_mechanisms/RatioConversionMechanism.

    ``ratio``: "One share of this stock class converts into this many target stock class
    shares". ovf reads only ``ratio``; see docs/ocf.md for ``conversion_price`` and
    ``rounding_type``.
    """

    type: Literal["RATIO_CONVERSION"]
    conversion_price: Monetary
    ratio: Ratio
    rounding_type: Literal["CEILING", "FLOOR", "NORMAL"]


class StockClassConversionRight(OcfModel):
    """types/conversion_rights/StockClassConversionRight (ratio mechanism only in v1.2.0)."""

    type: Literal["STOCK_CLASS_CONVERSION_RIGHT"] | None = None
    conversion_mechanism: RatioConversionMechanism
    converts_to_future_round: bool | None = None
    converts_to_stock_class_id: str | None = None


class InterestRate(OcfModel):
    """types/InterestRate: one rate and the dates between which it accrues.

    ``accrual_end_date`` (v1.2.0, verbatim): "Optional end date (inclusive) for interest
    accruing at the specified rate. If none specified, interest will accrue indefinitely or
    until accrual of next interest rate commences".
    """

    rate: Percentage
    accrual_start_date: dt.date
    accrual_end_date: dt.date | None = None


DayCountType = Literal["ACTUAL_365", "30_360"]
AccrualPeriodType = Literal["DAILY", "MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"]


class NoteConversionMechanism(OcfModel):
    """types/conversion_mechanisms/NoteConversionMechanism.

    The only OCF v1.2.0 structure that carries interest terms. It sits inside a conversion
    right inside one conversion trigger, so the terms are recorded per trigger, not per
    instrument. ``interest_rates`` is required but may be empty ("Interest rate(s) of the
    convertible (if applicable)"). There is no maturity date and no compounding frequency.
    """

    type: Literal["CONVERTIBLE_NOTE_CONVERSION"]
    interest_rates: tuple[InterestRate, ...]
    day_count_convention: DayCountType
    interest_payout: Literal["DEFERRED", "CASH"]
    interest_accrual_period: AccrualPeriodType
    compounding_type: Literal["COMPOUNDING", "SIMPLE"]
    conversion_discount: Percentage | None = None
    conversion_valuation_cap: Monetary | None = None
    capitalization_definition: str | None = None
    capitalization_definition_rules: JsonValue = None
    exit_multiple: Ratio | None = None
    conversion_mfn: bool | None = None


class ConversionRight(OcfModel):
    """The ``conversion_right`` of a conversion trigger.

    The trigger primitive allows a convertible, warrant or stock-class conversion right, and
    ``type`` is optional in all three, so ``type`` is kept here and the reader refuses any
    right but ``CONVERTIBLE_CONVERSION_RIGHT``. The mechanism stays raw JSON until the
    reader has checked its ``type``; only ``NoteConversionMechanism`` is ever typed.
    """

    type: (
        Literal[
            "CONVERTIBLE_CONVERSION_RIGHT",
            "WARRANT_CONVERSION_RIGHT",
            "STOCK_CLASS_CONVERSION_RIGHT",
        ]
        | None
    ) = None
    conversion_mechanism: dict[str, JsonValue]
    converts_to_future_round: bool | None = None
    converts_to_stock_class_id: str | None = None


ConversionTriggerType = Literal[
    "AUTOMATIC_ON_CONDITION",
    "AUTOMATIC_ON_DATE",
    "ELECTIVE_IN_RANGE",
    "ELECTIVE_ON_CONDITION",
    "ELECTIVE_AT_WILL",
    "UNSPECIFIED",
]
# The properties each types/conversion_triggers/* schema adds to the common ones, all
# required by that schema and forbidden (additionalProperties: false) by every other.
TRIGGER_TYPE_FIELDS: dict[str, frozenset[str]] = {
    "AUTOMATIC_ON_CONDITION": frozenset({"trigger_condition"}),
    "AUTOMATIC_ON_DATE": frozenset({"trigger_date"}),
    "ELECTIVE_IN_RANGE": frozenset({"start_date", "end_date"}),
    "ELECTIVE_ON_CONDITION": frozenset({"trigger_condition"}),
    "ELECTIVE_AT_WILL": frozenset(),
    "UNSPECIFIED": frozenset(),
}


class ConversionTrigger(OcfModel):
    """types/conversion_triggers/*: the six trigger schemas as one model.

    Each trigger type requires its own extra properties and forbids the others', which
    the validator enforces. ``trigger_condition`` is "Legal language describing what
    conditions must be satisfied": free text, never parsed by ovf.
    """

    type: ConversionTriggerType
    trigger_id: str
    conversion_right: ConversionRight
    nickname: str | None = None
    trigger_description: str | None = None
    trigger_condition: str | None = None
    trigger_date: dt.date | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None

    @model_validator(mode="after")
    def fields_match_trigger_type(self) -> Self:
        allowed = TRIGGER_TYPE_FIELDS[self.type]
        for name in ("trigger_condition", "trigger_date", "start_date", "end_date"):
            present = getattr(self, name) is not None
            if name in allowed and not present:
                raise ValueError(f"a {self.type} trigger requires {name}")
            if name not in allowed and present:
                raise ValueError(f"a {self.type} trigger does not allow {name}")
        return self


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------


class Issuer(OcfModel):
    """objects/Issuer. ovf reads ``legal_name`` for the import trace and nothing else."""

    object_type: Literal["ISSUER"]
    id: str
    legal_name: str
    formation_date: dt.date
    country_of_formation: CountryCode
    dba: str | None = None
    country_subdivision_of_formation: str | None = None
    tax_ids: JsonValue = None
    email: JsonValue = None
    phone: JsonValue = None
    address: JsonValue = None
    initial_shares_authorized: Numeric | AuthorizedShares | None = None
    comments: tuple[str, ...] | None = None


class Stakeholder(OcfModel):
    """objects/Stakeholder. ``id`` becomes the ovf ``holder_id``; nothing else is read."""

    object_type: Literal["STAKEHOLDER"]
    id: str
    name: Name
    stakeholder_type: Literal["INDIVIDUAL", "INSTITUTION"]
    issuer_assigned_id: str | None = None
    current_relationship: str | None = None
    primary_contact: JsonValue = None
    contact_info: JsonValue = None
    addresses: JsonValue = None
    tax_ids: JsonValue = None
    comments: tuple[str, ...] | None = None


class StockClass(OcfModel):
    """objects/StockClass.

    ``seniority`` (v1.2.0, verbatim): "Seniority is ordered by increasing number so that
    stock classes with a higher seniority have higher repayment priority." It is a
    ``Numeric``, not an integer: the schema allows a new class to take "some decimal number
    between the numbers representing seniority of the respective classes".
    """

    object_type: Literal["STOCK_CLASS"]
    id: str
    name: str
    class_type: Literal["COMMON", "PREFERRED"]
    default_id_prefix: str
    initial_shares_authorized: Numeric | AuthorizedShares
    votes_per_share: Numeric
    seniority: Numeric
    board_approval_date: dt.date | None = None
    stockholder_approval_date: dt.date | None = None
    par_value: Monetary | None = None
    price_per_share: Monetary | None = None
    conversion_rights: tuple[StockClassConversionRight, ...] | None = None
    liquidation_preference_multiple: Numeric | None = None
    participation_cap_multiple: Numeric | None = None
    comments: tuple[str, ...] | None = None


class StockPlan(OcfModel):
    """objects/StockPlan. Exactly one of ``stock_class_id`` (deprecated) and
    ``stock_class_ids`` must be present, as the schema's ``oneOf`` requires."""

    object_type: Literal["STOCK_PLAN"]
    id: str
    plan_name: str
    initial_shares_reserved: Numeric
    board_approval_date: dt.date | None = None
    stockholder_approval_date: dt.date | None = None
    default_cancellation_behavior: (
        Literal["RETIRE", "RETURN_TO_POOL", "HOLD_AS_CAPITAL_STOCK", "DEFINED_PER_PLAN_SECURITY"]
        | None
    ) = None
    stock_class_id: str | None = None
    stock_class_ids: Annotated[tuple[str, ...], Field(min_length=1)] | None = None
    comments: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def exactly_one_class_reference(self) -> Self:
        if (self.stock_class_id is None) == (self.stock_class_ids is None):
            raise ValueError(
                "exactly one of stock_class_id (deprecated) and stock_class_ids is required"
            )
        return self

    @property
    def class_ids(self) -> tuple[str, ...]:
        if self.stock_class_ids is not None:
            return self.stock_class_ids
        assert self.stock_class_id is not None
        return (self.stock_class_id,)


# ---------------------------------------------------------------------------
# Transactions ovf applies
# ---------------------------------------------------------------------------


class StockIssuance(OcfModel):
    """objects/transactions/issuance/StockIssuance: one outstanding stock security."""

    object_type: Literal["TX_STOCK_ISSUANCE"]
    id: str
    date: dt.date
    security_id: str
    custom_id: str
    stakeholder_id: str
    security_law_exemptions: tuple[JsonValue, ...]
    stock_class_id: str
    share_price: Monetary
    quantity: Numeric
    stock_legend_ids: tuple[str, ...]
    stock_plan_id: str | None = None
    share_numbers_issued: JsonValue = None
    vesting_terms_id: str | None = None
    vestings: JsonValue = None
    cost_basis: Monetary | None = None
    issuance_type: Literal["RSA", "FOUNDERS_STOCK"] | None = None
    board_approval_date: dt.date | None = None
    stockholder_approval_date: dt.date | None = None
    consideration_text: str | None = None
    comments: tuple[str, ...] | None = None


class StockPlanPoolAdjustment(OcfModel):
    """objects/transactions/adjustment/StockPlanPoolAdjustment.

    ``shares_reserved`` is absolute: "The number of shares reserved in the pool ... as of
    the effective date of this pool adjustment."
    """

    object_type: Literal["TX_STOCK_PLAN_POOL_ADJUSTMENT"]
    id: str
    date: dt.date
    stock_plan_id: str
    shares_reserved: Numeric
    board_approval_date: dt.date | None = None
    stockholder_approval_date: dt.date | None = None
    comments: tuple[str, ...] | None = None


class ConvertibleIssuance(OcfModel):
    """objects/transactions/issuance/ConvertibleIssuance: one note, SAFE or other convertible.

    ``seniority`` (v1.2.0, verbatim): "If different convertible instruments have seniorty
    over one another, use this value to build a seniority stack, with 1 being highest
    seniority and equal seniority values assumed to be equal priority". That is the
    OPPOSITE direction to ``StockClass.seniority``, where a higher number is repaid first.
    It is a JSON integer, not a ``Numeric``.
    """

    object_type: Literal["TX_CONVERTIBLE_ISSUANCE"]
    id: str
    date: dt.date
    security_id: str
    custom_id: str
    stakeholder_id: str
    security_law_exemptions: tuple[JsonValue, ...]
    investment_amount: Monetary
    convertible_type: Literal["NOTE", "SAFE", "CONVERTIBLE_SECURITY"]
    conversion_triggers: Annotated[tuple[ConversionTrigger, ...], Field(min_length=1)]
    seniority: int
    pro_rata: Numeric | None = None
    board_approval_date: dt.date | None = None
    stockholder_approval_date: dt.date | None = None
    consideration_text: str | None = None
    comments: tuple[str, ...] | None = None

    @field_validator("seniority", mode="before")
    @classmethod
    def json_integer(cls, value: object) -> object:
        """JSON Schema ``integer``: any number with no fractional part; no strings or bools."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("seniority must be a JSON integer")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("seniority must be a JSON integer")
        return int(value)


class StockClassConversionRatioAdjustment(OcfModel):
    """objects/transactions/adjustment/StockClassConversionRatioAdjustment.

    Carries the new ratio in effect after a repricing. OCF states that "the actual
    determination of the new conversion ratio / conversion price is calculated outside of
    OCF"; ovf applies the stated ratio and computes nothing.
    """

    object_type: Literal["TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT"]
    id: str
    date: dt.date
    stock_class_id: str
    new_ratio_conversion_mechanism: RatioConversionMechanism
    comments: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class FileReference(OcfModel):
    """types/File: a path inside the package and its MD5 checksum."""

    filepath: str
    md5: Md5


class Manifest(OcfModel):
    """files/OCFManifestFile. ``ocf_version`` is the schema constant ``"1.2.0"``."""

    file_type: Literal["OCF_MANIFEST_FILE"]
    ocf_version: Literal["1.2.0"]
    issuer: Issuer
    as_of: dt.date
    generated_at: AwareDatetime
    stock_plans_files: tuple[FileReference, ...]
    stock_legend_templates_files: tuple[FileReference, ...]
    stock_classes_files: tuple[FileReference, ...]
    vesting_terms_files: tuple[FileReference, ...]
    valuations_files: tuple[FileReference, ...]
    transactions_files: tuple[FileReference, ...]
    stakeholders_files: tuple[FileReference, ...]
    financings_files: tuple[FileReference, ...] | None = None
    documents_files: tuple[FileReference, ...] | None = None
    comments: tuple[str, ...] | None = None


class StockClassesFile(OcfModel):
    file_type: Literal["OCF_STOCK_CLASSES_FILE"]
    items: tuple[StockClass, ...]


class StakeholdersFile(OcfModel):
    file_type: Literal["OCF_STAKEHOLDERS_FILE"]
    items: tuple[Stakeholder, ...]


class StockPlansFile(OcfModel):
    file_type: Literal["OCF_STOCK_PLANS_FILE"]
    items: tuple[StockPlan, ...]


class TransactionsFile(OcfModel):
    """Transactions stay raw JSON here; the reader types the ones it applies."""

    file_type: Literal["OCF_TRANSACTIONS_FILE"]
    items: tuple[dict[str, JsonValue], ...]


class OcfPackage(OcfModel):
    """An OCF package held in memory: the manifest's own fields plus the objects ovf reads.

    ``transactions`` are raw JSON objects because v1.2.0 defines 43 transaction types; the
    reader types the ones it applies and classifies every other one as ignored or refused.
    ``unread_files`` lists manifest entries ovf does not open (legend templates, vesting
    terms, valuations, financings, documents). They are reported, never validated.
    """

    ocf_version: Literal["1.2.0"] = "1.2.0"
    issuer: Issuer
    as_of: dt.date
    generated_at: AwareDatetime
    comments: tuple[str, ...] = ()
    stock_classes: tuple[StockClass, ...] = ()
    stakeholders: tuple[Stakeholder, ...] = ()
    stock_plans: tuple[StockPlan, ...] = ()
    transactions: tuple[dict[str, JsonValue], ...] = ()
    unread_files: tuple[str, ...] = ()
