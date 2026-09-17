"""Typed input specifications for the ovf MCP tools.

Each model mirrors one factory in ``ovf`` (``ovf.common``, ``ovf.preferred``, ...) field for
field, so a cap table written for the CLI (``python -m ovf waterfall --file``) is also a valid
tool argument. These models fix the *shape* of the input, reject unknown keys and document each
term for the calling model. Whether the *economics* are admissible (a positive price, a cap of
at least 1x, a supported instrument) is decided by the library itself, which refuses rather than
guesses; its message is passed back unchanged.

``security_to_spec`` is the inverse: it turns a library security (for example one produced by a
financing) back into a spec, so every tool result that contains a cap table can be passed
straight into the next tool.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

import ovf
from ovf.contracts.securities import (
    CommonStock,
    CumulativeDividend,
    NonCumulativeDividend,
    PostMoneySAFE,
    PreferredStock,
    PreMoneySAFE,
    Security,
    StockOptionPool,
    cumulative_dividend,
    non_cumulative_dividend,
)
from ovf.instruments import ConvertibleNote, DebtInstrument, VentureDebt
from ovf_mcp.errors import DomainError

DayCountName = Literal["actual/365_fixed", "actual/360"]

_SECURITY_ID = (
    "Unique id of this position. If omitted the library derives one from the holder "
    "(e.g. 'pref_sr1_<holder>'); state it explicitly whenever one holder has several positions."
)


class Spec(BaseModel):
    """Base for every input model: unknown keys and non-finite numbers are rejected."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    #: Optional fields that set a number or a right. When the caller omits one, the factory
    #: default applies; ``defaults_applied`` reports it so the default is never silent.
    TERMS_WITH_DEFAULTS: ClassVar[tuple[str, ...]] = ()

    def defaults_applied(self) -> dict[str, Any]:
        """Contract terms the caller omitted, with the default value that was used."""
        return {
            name: getattr(self, name)
            for name in self.TERMS_WITH_DEFAULTS
            if name not in self.model_fields_set
        }


# --------------------------------------------------------------------------- dividends


class CumulativeDividendSpec(Spec):
    """An accruing dividend on a preferred position; every term that sets a number is stated."""

    kind: Literal["cumulative"]
    annual_rate: float = Field(description="Annual rate on the Original Issue Price, e.g. 0.08")
    accrual: Literal["simple", "compound"]
    compounding_frequency: int | None = Field(
        default=None, description="Compounding periods per year; required when accrual='compound'"
    )
    day_count: DayCountName
    accrues_from: date = Field(description="Issue date of the position's shares (YYYY-MM-DD)")
    settlement: Literal["forfeit_on_conversion", "paid_in_kind"] = Field(
        description="What happens to the accrued amount if the position converts"
    )
    participation_cap_basis: Literal["includes_dividends", "excludes_dividends"] | None = Field(
        default=None,
        description="Only for capped participating preferred: whether the cap counts dividends",
    )

    def build(self) -> CumulativeDividend:
        return cumulative_dividend(
            self.annual_rate,
            accrual=self.accrual,
            day_count=self.day_count,
            accrues_from=self.accrues_from,
            settlement=self.settlement,
            compounding_frequency=self.compounding_frequency,
            participation_cap_basis=self.participation_cap_basis,
        )


class NonCumulativeDividendSpec(Spec):
    """A dividend that is owed only when declared; it adds nothing at an exit."""

    kind: Literal["non_cumulative"]
    annual_rate: float

    def build(self) -> NonCumulativeDividend:
        return non_cumulative_dividend(self.annual_rate)


DividendSpec = Annotated[
    CumulativeDividendSpec | NonCumulativeDividendSpec, Field(discriminator="kind")
]

# --------------------------------------------------------------------------- equity


class CommonSpec(Spec):
    """Common stock: the residual claimant."""

    type: Literal["common"]
    shares: float = Field(description="Issued common shares")
    holder_id: str = Field(default="founders", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)
    price: float = Field(
        default=0.0,
        description="Cost basis per share; 0 means unknown and reports the multiple as null",
    )

    def build(self) -> Security:
        return ovf.common(
            self.shares, holder_id=self.holder_id, security_id=self.security_id, price=self.price
        )


class PreferredSpec(Spec):
    """Convertible preferred stock with a liquidation preference."""

    TERMS_WITH_DEFAULTS = (
        "seniority",
        "liquidation_multiple",
        "participating",
        "participation_cap",
        "conversion_ratio",
        "dividend",
    )

    type: Literal["preferred"]
    shares: float = Field(description="Preferred shares issued")
    price: float = Field(description="Original Issue Price per share; invested = shares * price")
    seniority: int = Field(
        default=1, description="Payment rank: 0 is paid first; equal integers are pari passu"
    )
    liquidation_multiple: float = Field(
        default=1.0, description="Preference as a multiple of invested"
    )
    participating: bool = Field(
        default=False,
        description="True if the position also shares the residual after its preference",
    )
    participation_cap: float | None = Field(
        default=None,
        description="Total-return cap as a multiple of invested capital (participating only); null is uncapped",
    )
    conversion_ratio: float = Field(default=1.0, description="Common shares per preferred share")
    holder_id: str = Field(default="investor", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)
    dividend: DividendSpec | None = None

    def defaults_applied(self) -> dict[str, Any]:
        applied = super().defaults_applied()
        if not self.participating:
            applied.pop("participation_cap", None)  # meaningless without participation
        return applied

    def build(self) -> Security:
        return ovf.preferred(
            self.shares,
            self.price,
            seniority=self.seniority,
            liquidation_multiple=self.liquidation_multiple,
            participating=self.participating,
            participation_cap=self.participation_cap,
            conversion_ratio=self.conversion_ratio,
            holder_id=self.holder_id,
            security_id=self.security_id,
            dividend=None if self.dividend is None else self.dividend.build(),
        )


class OptionPoolSpec(Spec):
    """Reserved option-plan capacity. Unallocated capacity receives nothing at an exit."""

    TERMS_WITH_DEFAULTS = ("allocated_shares",)

    type: Literal["pool", "option_pool"]
    reserved_shares: float = Field(description="Total approved pool capacity")
    allocated_shares: float = Field(
        default=0.0,
        description="Granted options. Nonzero is refused by the exit engine (no strike/vesting terms)",
    )
    holder_id: str = Field(default="esop", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)

    def build(self) -> Security:
        return ovf.option_pool(
            self.reserved_shares,
            allocated_shares=self.allocated_shares,
            holder_id=self.holder_id,
            security_id=self.security_id,
        )


class SafeSpec(Spec):
    """An unconverted SAFE. Only the priced-round tool can resolve it; the exit engine refuses it."""

    TERMS_WITH_DEFAULTS = ("discount_rate",)

    type: Literal["safe_post", "safe_pre"]
    amount: float = Field(description="Purchase amount")
    cap: float = Field(description="Valuation cap")
    discount_rate: float = Field(default=0.0, description="Discount, e.g. 0.2; 0 for YC cap-only")
    holder_id: str = Field(default="safe_investor", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)

    def build(self) -> Security:
        factory = ovf.safe_post if self.type == "safe_post" else ovf.safe_pre
        return factory(
            amount=self.amount,
            cap=self.cap,
            discount_rate=self.discount_rate,
            holder_id=self.holder_id,
            security_id=self.security_id,
        )


# --------------------------------------------------------------------------- debt


class _DebtTerms(Spec):
    principal: float = Field(description="Amount originally advanced")
    annual_rate: float = Field(description="Nominal annual interest rate, e.g. 0.08")
    accrual: Literal["simple", "compound", "pik"]
    compounding_frequency: int | None = Field(
        default=None, description="Periods per year; required for compound and pik accrual"
    )
    day_count: DayCountName
    issue_date: date
    seniority: int = Field(
        description="Rank among debt (lower is paid first). All debt is paid ahead of all equity"
    )


class DebtSpec(_DebtTerms):
    """A plain term loan, repaid ahead of all equity."""

    TERMS_WITH_DEFAULTS = ("maturity_date",)

    type: Literal["debt"]
    maturity_date: date | None = None
    holder_id: str = Field(default="lender", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)

    def build(self) -> Security:
        return ovf.debt(
            self.principal,
            self.annual_rate,
            accrual=self.accrual,
            day_count=self.day_count,
            issue_date=self.issue_date,
            seniority=self.seniority,
            compounding_frequency=self.compounding_frequency,
            maturity_date=self.maturity_date,
            holder_id=self.holder_id,
            security_id=self.security_id,
        )


class VentureDebtSpec(_DebtTerms):
    """Venture debt with a final exit fee. Warrant coverage is not modelled."""

    TERMS_WITH_DEFAULTS = ("maturity_date",)

    type: Literal["venture_debt"]
    exit_fee: float = Field(description="Final payment due on repayment, base currency")
    maturity_date: date | None = None
    holder_id: str = Field(default="venture_lender", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)

    def build(self) -> Security:
        return ovf.venture_debt(
            self.principal,
            self.annual_rate,
            exit_fee=self.exit_fee,
            accrual=self.accrual,
            day_count=self.day_count,
            issue_date=self.issue_date,
            seniority=self.seniority,
            compounding_frequency=self.compounding_frequency,
            maturity_date=self.maturity_date,
            holder_id=self.holder_id,
            security_id=self.security_id,
        )


class ConvertibleNoteSpec(_DebtTerms):
    """A convertible note. At an exit it is a debt claim settled per ``exit_treatment``."""

    TERMS_WITH_DEFAULTS = ("valuation_cap", "discount_rate")

    type: Literal["convertible_note"]
    maturity_date: date
    qualified_financing_threshold: float = Field(
        description="New money at or above which the note converts automatically"
    )
    valuation_cap: float | None = None
    discount_rate: float = 0.0
    exit_treatment: Literal["repay", "multiple"] | None = Field(
        default=None,
        description="Payout at a liquidity event; required before the note enters an exit waterfall",
    )
    exit_principal_multiple: float | None = Field(
        default=None, description="Principal multiple paid when exit_treatment='multiple'"
    )
    holder_id: str = Field(default="noteholder", min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)

    def build(self) -> ConvertibleNote:
        return ovf.convertible_note(
            self.principal,
            self.annual_rate,
            accrual=self.accrual,
            day_count=self.day_count,
            issue_date=self.issue_date,
            maturity_date=self.maturity_date,
            seniority=self.seniority,
            qualified_financing_threshold=self.qualified_financing_threshold,
            valuation_cap=self.valuation_cap,
            discount_rate=self.discount_rate,
            compounding_frequency=self.compounding_frequency,
            exit_treatment=self.exit_treatment,
            exit_principal_multiple=self.exit_principal_multiple,
            holder_id=self.holder_id,
            security_id=self.security_id,
        )


SecuritySpec = Annotated[
    CommonSpec
    | PreferredSpec
    | OptionPoolSpec
    | SafeSpec
    | DebtSpec
    | VentureDebtSpec
    | ConvertibleNoteSpec,
    Field(discriminator="type"),
]
DebtInstrumentSpec = Annotated[
    DebtSpec | VentureDebtSpec | ConvertibleNoteSpec, Field(discriminator="type")
]

SECURITIES_ADAPTER: TypeAdapter[list[SecuritySpec]] = TypeAdapter(list[SecuritySpec])


def build_securities(specs: Sequence[BaseModel]) -> list[Security]:
    """Build library securities, naming the offending position when the library refuses one."""
    built: list[Security] = []
    for index, spec in enumerate(specs):
        label = getattr(spec, "security_id", None) or getattr(spec, "holder_id", "?")
        try:
            built.append(spec.build())  # type: ignore[attr-defined]
        except ValueError as error:  # pydantic.ValidationError is a ValueError
            raise DomainError(
                "invalid_terms",
                f"securities[{index}] ({label}): {_first_line(error)}",
                hint="Fix this position's terms; the library refuses rather than guesses.",
            ) from error
    return built


def defaults_applied(
    specs: Sequence[BaseModel], securities: Sequence[Security]
) -> dict[str, dict[str, Any]]:
    """``security_id`` -> omitted contract terms and the defaults used, for built positions."""
    applied: dict[str, dict[str, Any]] = {}
    for spec, security in zip(specs, securities, strict=True):
        omitted = spec.defaults_applied() if isinstance(spec, Spec) else {}
        if omitted:
            applied[security.security_id] = omitted
    return applied


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _dividend_spec(dividend: CumulativeDividend | NonCumulativeDividend | None) -> Any:
    if dividend is None:
        return None
    if isinstance(dividend, NonCumulativeDividend):
        return {"kind": "non_cumulative", "annual_rate": dividend.annual_rate}
    return {
        "kind": "cumulative",
        "annual_rate": dividend.annual_rate,
        "accrual": dividend.accrual,
        "compounding_frequency": dividend.compounding_frequency,
        "day_count": dividend.day_count,
        "accrues_from": _iso(dividend.accrues_from),
        "settlement": dividend.settlement,
        "participation_cap_basis": dividend.participation_cap_basis,
    }


def _debt_terms(s: DebtInstrument) -> dict[str, Any]:
    return {
        "principal": s.principal,
        "annual_rate": s.annual_rate,
        "accrual": str(s.accrual),
        "compounding_frequency": s.compounding_frequency,
        "day_count": str(s.day_count),
        "issue_date": _iso(s.issue_date),
        "seniority": s.seniority,
        "maturity_date": _iso(s.maturity_date),
    }


def _spec_of(s: Security) -> dict[str, Any]:
    """The spec for ``s``, dispatched on its exact type (a subclass is not its parent)."""
    ids = {"holder_id": s.holder_id, "security_id": s.security_id}
    kind = type(s)
    if kind is ConvertibleNote:
        assert isinstance(s, ConvertibleNote)
        return {
            "type": "convertible_note",
            **_debt_terms(s),
            "qualified_financing_threshold": s.qualified_financing_threshold,
            "valuation_cap": s.valuation_cap,
            "discount_rate": s.discount_rate,
            "exit_treatment": None if s.exit_treatment is None else str(s.exit_treatment),
            "exit_principal_multiple": s.exit_principal_multiple,
            **ids,
        }
    if kind is VentureDebt:
        assert isinstance(s, VentureDebt)
        return {"type": "venture_debt", **_debt_terms(s), "exit_fee": s.exit_fee, **ids}
    if kind is DebtInstrument:
        assert isinstance(s, DebtInstrument)
        return {"type": "debt", **_debt_terms(s), **ids}
    if kind is PreferredStock:
        assert isinstance(s, PreferredStock)
        return {
            "type": "preferred",
            "shares": s.shares,
            "price": s.price,
            "seniority": s.seniority,
            "liquidation_multiple": s.liquidation_multiple,
            "participating": s.participating,
            "participation_cap": s.participation_cap,
            "conversion_ratio": s.conversion_ratio,
            "dividend": _dividend_spec(s.dividend),
            **ids,
        }
    if kind is CommonStock:
        return {"type": "common", "shares": s.shares, "price": s.price, **ids}
    if kind is StockOptionPool:
        assert isinstance(s, StockOptionPool)
        return {
            "type": "pool",
            "reserved_shares": s.reserved_shares,
            "allocated_shares": s.allocated_shares,
            **ids,
        }
    if kind is PostMoneySAFE or kind is PreMoneySAFE:
        assert isinstance(s, PostMoneySAFE | PreMoneySAFE)
        return {
            "type": "safe_post" if kind is PostMoneySAFE else "safe_pre",
            "amount": s.investment_amount,
            "cap": s.valuation_cap,
            "discount_rate": s.discount_rate,
            **ids,
        }
    raise DomainError(
        "unrepresentable_security",
        f"{s.security_id}: {kind.__name__} has no MCP spec yet",
        hint="This security type was added to the library after the MCP adapter; "
        "use the Python API for this table.",
    )


def security_to_spec(s: Security) -> dict[str, Any]:
    """The spec that rebuilds ``s`` exactly; the inverse of ``SecuritySpec.build``.

    The spec is rebuilt and compared with ``s`` field by field. A term the spec cannot
    carry (for example a field the library added after this adapter) is refused rather
    than dropped, so a cap table passed from one tool to the next never loses a right.
    """
    spec = _spec_of(s)
    rebuilt = SECURITIES_ADAPTER.validate_python([spec])[0].build()
    if type(rebuilt) is not type(s) or rebuilt.model_dump() != s.model_dump():
        raise DomainError(
            "unrepresentable_security",
            f"{s.security_id}: {type(s).__name__} carries terms the MCP spec cannot express",
            hint="Use the Python API for this table; the adapter will not drop a term.",
        )
    return spec


def securities_to_specs(securities: Sequence[Security]) -> list[dict[str, Any]]:
    return [security_to_spec(s) for s in securities]


def securities_json_schema() -> dict[str, Any]:
    """JSON Schema of the ``securities`` argument, published as a resource."""
    return SECURITIES_ADAPTER.json_schema()


# --------------------------------------------------------------------------- other tool inputs


class SafeTerms(Spec):
    """One SAFE in a priced round; its form (post- or pre-money) is the round's ``method``."""

    TERMS_WITH_DEFAULTS = ("discount_rate",)

    amount: float = Field(description="Purchase amount")
    cap: float = Field(description="Valuation cap")
    discount_rate: float = Field(
        default=0.0,
        description="0 for the YC cap-only form; nonzero models a custom cap-plus-discount SAFE",
    )
    holder_id: str = Field(min_length=1)
    security_id: str | None = Field(default=None, min_length=1, description=_SECURITY_ID)


class CapitalizationInput(Spec):
    """Common-equivalent share counts immediately before the dilutive issuance. All required."""

    common_outstanding: float
    preferred_as_converted: float = Field(
        description="All preferred as-converted at pre-issuance ratios, protected series included"
    )
    options_and_warrants_as_exercised: float
    other_convertibles_as_converted: float
    reserved_unissued_pool: float = Field(description="Plan capacity not yet granted")


class CustomDefinition(Spec):
    """A charter's own definition of 'A' (deemed outstanding), when no named one fits."""

    name: str = Field(min_length=1)
    source: str = Field(min_length=1, description="Where this composition comes from")
    include_common: bool
    include_preferred_as_converted: bool
    include_options_and_warrants: bool
    include_other_convertibles: bool
    include_reserved_pool: bool


DefinitionName = Literal[
    "broad_based_nvca", "broad_based_with_reserved_pool", "narrow_based_outstanding_stock"
]
DefinitionChoice = DefinitionName | CustomDefinition


class ProtectionInput(Spec):
    """The price-based anti-dilution term one preferred position carries under its charter."""

    method: Literal["weighted_average", "full_ratchet", "none"]
    definition: DefinitionChoice | None = Field(
        default=None, description="Required for weighted_average; must be omitted otherwise"
    )


class ExemptionInput(Spec):
    """The caller's determination of whether the issuance is an Exempted Security."""

    exempted: bool
    basis: str = Field(min_length=1, description="Why, e.g. the charter clause relied on")


class NoteTermsInput(Spec):
    """Terms an OCF v1.2.0 convertible does not carry but ovf's ConvertibleNote requires."""

    maturity_date: date
    qualified_financing_threshold: float
    day_count: DayCountName


class IssuerInput(Spec):
    """The OCF Issuer object; OCF requires it and ovf does not hold it."""

    id: str = Field(min_length=1)
    legal_name: str = Field(min_length=1)
    formation_date: date
    country_of_formation: str = Field(description="ISO 3166-1 alpha-2, e.g. 'US'")
