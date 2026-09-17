"""
Contract combinators and securities for venture capital cap tables.
Follows denotational semantics for private market instruments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Annotated, Any, Literal, NamedTuple, Self

from pydantic import (
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from ovf.core.types import (
    FinancialBaseModel,
    Money,
    Multiple,
    Percentage,
    Seniority,
    ShareCount,
    SharePrice,
)


class Security(FinancialBaseModel, ABC):
    """Abstract base class for all equity, convertible, and derivative securities."""

    model_config = ConfigDict(frozen=True)

    security_id: str = Field(
        ..., min_length=1, description="Unique identifier for the security issue"
    )
    holder_id: str = Field(
        ..., min_length=1, description="Identifier for the security holder / investor"
    )
    shares: ShareCount = Field(default=0.0, description="Number of underlying or issued shares")
    price: SharePrice = Field(default=0.0, description="Issuance price per share in base currency")

    @property
    def invested_capital(self) -> Money:
        """Total capital invested into this security issue."""
        return self.shares * self.price

    @abstractmethod
    def is_convertible(self) -> bool:
        """Whether this security can convert into common shares."""
        pass

    @abstractmethod
    def base_liquidation_preference(self) -> Money:
        """Fixed monetary preference paid prior to common residual."""
        pass


class CommonStock(Security):
    """
    Common Stock issued to founders, employees, and advisors.
    Subordinated to all preferred classes in liquidation.
    """

    def is_convertible(self) -> bool:
        return False

    def base_liquidation_preference(self) -> Money:
        return 0.0


# ---------------------------------------------------------------------------
# Preferred dividends
#
# Sources, derivations and what is not modelled: docs/dividends.md. Every accrual is a
# function of an explicit caller-supplied ``as_of`` date; nothing here reads a clock.
# ---------------------------------------------------------------------------

DividendDayCount = Literal["actual/365_fixed", "actual/360"]
"""Year fraction for daily accrual. The same two conventions, with the same names, as
``ovf.instruments.debt.DayCount`` (actual days / 365 and actual days / 360). The NVCA text
says only that Accruing Dividends "accrue from day to day", so the basis is required."""

_DIVIDEND_DAY_COUNT_DENOMINATOR: dict[str, int] = {"actual/365_fixed": 365, "actual/360": 360}

DividendSettlement = Literal["forfeit_on_conversion", "paid_in_kind"]
DividendCapBasis = Literal["includes_dividends", "excludes_dividends"]


class CumulativeDividend(FinancialBaseModel):
    """A cumulative ("accruing") dividend on one preferred position.

    Accrues from ``accrues_from`` at ``annual_rate`` of the Original Issue Price (the
    position's ``price``), whether or not declared. Every term that sets a number is
    required, except ``participation_cap_basis`` (see below):

    - ``accrual``: ``"simple"`` is the NVCA operative text, a fixed "$[___] per share" per
      annum, which footnote 13 says "will by definition be non-compounding". ``"compound"``
      is its footnote-13 variant: the rate applies to "the Original Issue Price ... plus the
      amount of previously accrued dividends", compounded ``compounding_frequency`` times a
      year. Only whole periods are accepted, as for debt.
    - ``day_count``: required. The charter says only "accrue from day to day".
    - ``settlement``: what happens to the accrued amount at the exit. It has no default,
      because filed charters differ and the charter decides:

      * ``"forfeit_on_conversion"``: the accrued amount is added once to the liquidation
        preference ("[__ times] the applicable Original Issue Price, plus any Accruing
        Dividends accrued but unpaid thereon", NVCA fn 17/19) and is lost if the position
        converts. NVCA Model COI (Oct 2025) s.4.3.3 keeps only "the right ... to receive
        shares of Common Stock ... and to receive payment of any dividends declared but
        unpaid", and fn 46 says "accruing dividends are not taken into account in a
        conversion".
      * ``"paid_in_kind"``: the accrued amount is paid in additional shares of the same
        series, accrued / Original Issue Price, on liquidation and on conversion alike
        (Spark Therapeutics charter, S-1 2014 Ex. 3.1, s.1.1). The position then behaves
        as ``shares x (1 + d)`` on both branches, where ``d`` = accrued / invested.

    - ``participation_cap_basis`` is consulted only for a participating position with a
      participation cap and ``"forfeit_on_conversion"``. ``None`` means the NVCA default,
      ``"includes_dividends"``: the cap bounds "the aggregate amount ... under Sections 2.1
      and 2.2" (NVCA Model COI fn 20), and 2.1 contains the accrued amount.
      ``"excludes_dividends"`` puts the accrued amount on top of the cap ("two-and-a-half
      times (2.5x) the Series B Original Issue Price, plus any Accruing Dividends accrued
      but unpaid thereon", Virtual Piggy charter, 8-K 2014 Ex. 3.1 s.4.2). Wherever the
      basis is consulted, the value used is written into ``WaterfallResult.assumptions``,
      including when it is the default.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["cumulative"] = "cumulative"
    annual_rate: float = Field(
        ..., gt=0.0, le=1.0, description="Annual rate on the Original Issue Price, e.g. 0.08"
    )
    accrual: Literal["simple", "compound"]
    compounding_frequency: int | None = Field(
        default=None,
        ge=1,
        strict=True,
        description="Periods per year for compound accrual; must be None for simple",
    )
    day_count: DividendDayCount
    accrues_from: date = Field(..., description="Issue date of the position's shares")
    settlement: DividendSettlement
    participation_cap_basis: DividendCapBasis | None = None

    @model_validator(mode="after")
    def validate_dividend_terms(self) -> Self:
        if isinstance(self.accrues_from, datetime):
            raise ValueError("accrues_from must be a date; time of day is not modelled")
        if self.accrual == "simple":
            if self.compounding_frequency is not None:
                raise ValueError("Simple accrual takes no compounding_frequency")
        elif self.compounding_frequency is None:
            raise ValueError(
                "Compound accrual requires an explicit compounding_frequency. NVCA fn 13: "
                "'it should also be specified whether this compounding ... is done on an "
                "annual, quarterly, or other basis'"
            )
        if self.settlement == "paid_in_kind" and self.participation_cap_basis is not None:
            raise ValueError(
                "participation_cap_basis does not apply to paid_in_kind: each paid-in-kind "
                "share carries the per-share cap like any other share of the series, so the "
                "cap scales with the position"
            )
        return self


class NonCumulativeDividend(FinancialBaseModel):
    """A non-cumulative dividend, payable only when declared. It accrues nothing.

    NVCA Model COI (Oct 2025) s.1, second alternative: the right "shall not be cumulative,
    and no right to dividends shall accrue to holders of Preferred Stock by reason of the
    fact that dividends on such shares are not declared or paid". It is accepted so that a
    class carrying one is described accurately. It is not treated as cumulative, and it
    adds nothing to an exit. Declared-but-unpaid dividends are not modelled.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["non_cumulative"] = "non_cumulative"
    annual_rate: float = Field(
        ..., gt=0.0, le=1.0, description="Dividend Amount as a fraction of the OIP, if declared"
    )


PreferredDividend = Annotated[
    CumulativeDividend | NonCumulativeDividend, Field(discriminator="kind")
]


class DividendAccrual(FinancialBaseModel):
    """What one preferred position's dividend term contributes at an exit on ``as_of``.

    ``preference`` is the amount claimed if the position does not convert,
    ``participation_cap_amount`` the total it can receive while participating (``None``
    when uncapped or non-participating) and ``conversion_units`` the common-equivalent
    units it holds when converting or participating.
    """

    security_id: str
    holder_id: str
    kind: Literal["cumulative", "non_cumulative"]
    settlement: DividendSettlement | None
    accrues_from: date | None
    as_of: date | None
    day_count: DividendDayCount | None
    days: int | None = Field(default=None, ge=0)
    year_fraction: float | None = Field(default=None, ge=0.0)
    method: Literal["simple", "compound"] | None
    compounding_frequency: int | None
    compounding_periods: int | None
    annual_rate: float
    original_issue_price: SharePrice
    accrued_per_share: Money
    accrued: Money
    paid_in_kind_shares: ShareCount | None
    participation_cap_basis: DividendCapBasis | None = Field(
        description="Cap basis applied; None when the basis was not consulted"
    )
    participation_cap_basis_stated: bool = Field(
        description="False when the basis applied is the default"
    )
    preference: Money
    participation_cap_amount: Money | None
    conversion_units: ShareCount
    basis: str = Field(description="The formula that produced `preference`, in words")


class PreferredExitTerms(NamedTuple):
    """Amounts one preferred position brings to an exit allocation."""

    preference: float
    participation_cap_amount: float | None
    units: float


class PreferredStock(Security):
    """
    Preferred Stock issued to institutional investors (Series Seed, A, B, etc.).
    Carries liquidation preferences, optional participation rights, and conversion options.

    ``dividend`` is ``None`` (no dividend right), a ``CumulativeDividend`` or a
    ``NonCumulativeDividend``. A position with a cumulative dividend has no date-free
    preference: use ``exit_terms(as_of)``. With ``dividend=None`` every result, dump and
    fingerprint is exactly what it was before dividends were modelled.
    """

    seniority: Seniority = Field(
        default=1,
        description="Priority in liquidation queue. 1 is highest / senior, 2 is junior, etc.",
    )
    liquidation_multiple: Multiple = Field(
        default=1.0, description="Multiplier on invested capital (e.g. 1.0x, 1.5x, 2.0x)"
    )
    participating: bool = Field(
        default=False,
        description="If True, receives both preference and residual pro-rata ('double dip')",
    )
    participation_cap: Multiple | None = Field(
        default=None,
        description="Maximum total payout as a multiple of invested capital if participating",
    )
    conversion_ratio: float = Field(
        default=1.0,
        gt=0.0,
        description="Number of common shares received per preferred share upon conversion",
    )
    dividend: PreferredDividend | None = Field(
        default=None, description="Dividend right; None means none. See docs/dividends.md"
    )

    def is_convertible(self) -> bool:
        return True

    @model_validator(mode="after")
    def validate_participation(self) -> Self:
        if self.participation_cap is not None:
            if not self.participating:
                raise ValueError("participation_cap requires participating=True")
            if self.participation_cap < self.liquidation_multiple:
                raise ValueError("participation_cap cannot be below liquidation_multiple")
        dividend = self.dividend
        if isinstance(dividend, CumulativeDividend):
            if self.price <= 0:
                raise ValueError(
                    f"{self.security_id}: a cumulative dividend accrues on the Original Issue "
                    "Price, so price must be positive"
                )
            if dividend.participation_cap_basis is not None and self.participation_cap is None:
                raise ValueError(
                    f"{self.security_id}: participation_cap_basis applies only to a "
                    "participating position with a participation_cap"
                )
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_dividend(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave ``dividend`` out of a dump when it is None.

        Dumps, and the waterfall input fingerprint built from them, of a position without a
        dividend are therefore byte-identical to those made before the field existed.
        """
        data = handler(self)
        if self.dividend is None and isinstance(data, dict):
            data.pop("dividend", None)
        return data

    def base_liquidation_preference(self) -> Money:
        if isinstance(self.dividend, CumulativeDividend):
            raise TypeError(
                f"{self.security_id} carries a cumulative dividend, so its preference depends "
                "on a date: call exit_terms(as_of) or liquidation_preference(as_of)"
            )
        return self.invested_capital * self.liquidation_multiple

    @property
    def converted_shares(self) -> ShareCount:
        """Number of common shares resulting from conversion (before any paid-in-kind shares)."""
        return self.shares * self.conversion_ratio

    def _accrued(self, as_of: date | None) -> tuple[int, int | None, float, float]:
        """Days, compounding periods, accrued per share and accrued for the position."""
        dividend = self.dividend
        assert isinstance(dividend, CumulativeDividend)
        if as_of is None:
            raise ValueError(
                f"{self.security_id} carries a cumulative dividend, which accrues with time, so "
                "an exit holding it needs an explicit as_of date. No implicit clock is used"
            )
        if not isinstance(as_of, date) or isinstance(as_of, datetime):
            raise ValueError("as_of must be a datetime.date; time of day is not modelled")
        if as_of < dividend.accrues_from:
            raise ValueError(
                f"{self.security_id}: as_of {as_of} is before accrues_from {dividend.accrues_from}"
            )
        days = (as_of - dividend.accrues_from).days
        denominator = _DIVIDEND_DAY_COUNT_DENOMINATOR[dividend.day_count]
        rate = dividend.annual_rate
        if dividend.accrual == "simple":
            return (
                days,
                None,
                self.price * rate * days / denominator,
                self.invested_capital * rate * days / denominator,
            )
        frequency = dividend.compounding_frequency
        assert frequency is not None  # enforced by CumulativeDividend
        if (days * frequency) % denominator:
            raise ValueError(
                f"{self.security_id}: {days} days is not a whole number of 1/{frequency}-year "
                f"compounding periods under a {denominator}-day year. A dividend over a partial "
                "period (the stub) is contract-specific and not modelled; choose an as_of on "
                "a period end"
            )
        periods = days * frequency // denominator
        growth = (1 + rate / frequency) ** periods - 1
        return days, periods, self.price * growth, self.invested_capital * growth

    def _paid_in_kind_position(self, accrued: float) -> PreferredStock:
        """This position after its accrued dividends are paid in shares of the same series.

        ``accrued / price`` new shares join the position (Spark charter s.1.1), so it holds
        ``shares x (1 + d)`` with ``d = accrued / invested``. The result carries no
        dividend: the preference, participation units, per-share cap and conversion units
        that follow are the ordinary no-dividend terms of the enlarged position.
        """
        return self.model_copy(
            update={"shares": self.shares + accrued / self.price, "dividend": None}
        )

    def exit_terms(self, as_of: date | None) -> PreferredExitTerms:
        """Preference, total participation cap and common-equivalent units at an exit.

        ``as_of`` is required when the position carries a cumulative dividend and is not
        read otherwise. Without one, the terms are ``invested x multiple``,
        ``invested x participation_cap`` and ``shares x conversion_ratio``, computed
        exactly as before dividends were modelled.
        """
        dividend = self.dividend
        if not isinstance(dividend, CumulativeDividend):
            cap = None
            if self.participation_cap is not None:
                cap = self.invested_capital * self.participation_cap
            return PreferredExitTerms(
                self.invested_capital * self.liquidation_multiple, cap, self.converted_shares
            )
        accrued = self._accrued(as_of)[3]
        if dividend.settlement == "paid_in_kind":
            return self._paid_in_kind_position(accrued).exit_terms(None)
        preference = self.invested_capital * self.liquidation_multiple + accrued
        cap = None
        if self.participation_cap is not None:
            cap = self.invested_capital * self.participation_cap
            if dividend.participation_cap_basis == "excludes_dividends":
                cap += accrued
            else:  # NVCA fn 20: the cap bounds the 2.1 amount, accrued dividends included
                preference = min(preference, cap)
        return PreferredExitTerms(preference, cap, self.converted_shares)

    def liquidation_preference(self, as_of: date | None) -> Money:
        """Amount claimed at an exit on ``as_of`` if the position does not convert."""
        return self.exit_terms(as_of).preference

    def dividend_accrual(self, as_of: date | None) -> DividendAccrual | None:
        """Trace of the dividend term at an exit on ``as_of``; None without a dividend."""
        dividend = self.dividend
        if dividend is None:
            return None
        terms = self.exit_terms(as_of)
        common: dict[str, Any] = {
            "security_id": self.security_id,
            "holder_id": self.holder_id,
            "annual_rate": dividend.annual_rate,
            "original_issue_price": self.price,
            "preference": terms.preference,
            "participation_cap_amount": terms.participation_cap_amount,
            "conversion_units": terms.units,
        }
        if isinstance(dividend, NonCumulativeDividend):
            return DividendAccrual(
                **common,
                kind="non_cumulative",
                settlement=None,
                accrues_from=None,
                as_of=None,
                day_count=None,
                method=None,
                compounding_frequency=None,
                compounding_periods=None,
                accrued_per_share=0.0,
                accrued=0.0,
                paid_in_kind_shares=None,
                participation_cap_basis=None,
                participation_cap_basis_stated=False,
                basis="non-cumulative: nothing accrues unless declared; multiple x invested",
            )
        assert as_of is not None  # exit_terms refuses a cumulative dividend without it
        days, periods, per_share, accrued = self._accrued(as_of)
        pik = dividend.settlement == "paid_in_kind"
        consulted = not pik and self.participation_cap is not None
        cap_basis = dividend.participation_cap_basis
        if pik:
            basis = (
                "multiple x Original Issue Price x (shares + accrued / Original Issue Price "
                "paid-in-kind shares); the added shares also participate and convert"
            )
        else:
            basis = "multiple x invested + accrued dividends; forfeited on conversion"
            if consulted and cap_basis == "excludes_dividends":
                basis += "; participation cap = cap x invested + accrued dividends"
            elif consulted:
                basis += "; at most the participation cap, which includes accrued dividends"
        return DividendAccrual(
            **common,
            kind="cumulative",
            settlement=dividend.settlement,
            accrues_from=dividend.accrues_from,
            as_of=as_of,
            day_count=dividend.day_count,
            days=days,
            year_fraction=days / _DIVIDEND_DAY_COUNT_DENOMINATOR[dividend.day_count],
            method=dividend.accrual,
            compounding_frequency=dividend.compounding_frequency,
            compounding_periods=periods,
            accrued_per_share=per_share,
            accrued=accrued,
            paid_in_kind_shares=accrued / self.price if pik else None,
            participation_cap_basis=(cap_basis or "includes_dividends") if consulted else None,
            participation_cap_basis_stated=consulted and cap_basis is not None,
            basis=basis,
        )


class PostMoneySAFE(Security):
    """
    Y Combinator Post-Money SAFE (Simple Agreement for Future Equity v1.2).
    Locks in investor ownership before the priced equity round.
    """

    investment_amount: Money = Field(..., gt=0, description="Cash investment in base currency")
    valuation_cap: Money = Field(..., gt=0, description="Post-money valuation cap")
    discount_rate: Percentage = Field(
        default=0.0,
        lt=1,
        description="Discount rate; nonzero is a custom cap-plus-discount variant",
    )

    @property
    def target_ownership(self) -> Percentage:
        """Cap-implied ownership before new money/pool dilution, if the cap binds."""
        if self.investment_amount >= self.valuation_cap:
            raise ValueError("SAFE investment must be below its cap to imply feasible ownership")
        return self.investment_amount / self.valuation_cap

    @property
    def invested_capital(self) -> Money:
        return self.investment_amount

    def is_convertible(self) -> bool:
        return True

    def base_liquidation_preference(self) -> Money:
        return self.investment_amount


class PreMoneySAFE(Security):
    """
    Pre-Money SAFE. SAFEs dilute each other and option pool increases precede conversion.
    """

    investment_amount: Money = Field(..., gt=0, description="Cash investment in base currency")
    valuation_cap: Money = Field(..., gt=0, description="Pre-money valuation cap")
    discount_rate: Percentage = Field(default=0.0, lt=1, description="Discount rate")

    @property
    def invested_capital(self) -> Money:
        return self.investment_amount

    def is_convertible(self) -> bool:
        return True

    def base_liquidation_preference(self) -> Money:
        return self.investment_amount


class StockOptionPool(Security):
    """
    Employee Stock Option Pool (ESOP / Equity Incentive Plan).
    Contains both allocated options and unallocated reserved shares.
    """

    allocated_shares: ShareCount = Field(default=0.0, description="Granted/exercisable options")
    reserved_shares: ShareCount = Field(..., description="Total approved pool capacity")

    @model_validator(mode="before")
    @classmethod
    def set_reserved_shares(cls, data: Any) -> Any:
        if isinstance(data, dict) and "reserved_shares" in data:
            data = dict(data)
            if "shares" in data and data["shares"] != data["reserved_shares"]:
                raise ValueError("Pool shares must equal reserved_shares")
            data["shares"] = data["reserved_shares"]
        return data

    @model_validator(mode="after")
    def validate_allocations(self) -> Self:
        if self.allocated_shares > self.reserved_shares:
            raise ValueError("allocated_shares cannot exceed reserved_shares")
        return self

    @property
    def unallocated_shares(self) -> ShareCount:
        return max(0.0, self.reserved_shares - self.allocated_shares)

    def is_convertible(self) -> bool:
        return False

    def base_liquidation_preference(self) -> Money:
        return 0.0


# ---------------------------------------------------------------------------
# Combinator Constructors (Functional API following Peyton Jones & Eber)
# ---------------------------------------------------------------------------


def common(
    shares: float,
    holder_id: str = "founders",
    security_id: str | None = None,
    price: float = 0.0,
) -> CommonStock:
    """Create a Common Stock security combinator.

    ``price`` defaults to zero because a founder cost basis is normally unknown.
    A zero basis leaves ``Payout.effective_multiple`` undefined (``None``) rather
    than reporting a return computed against a nominal par value. Pass the real
    purchase price when it is known and a multiple is wanted.
    """
    sec_id = security_id or f"common_{holder_id}"
    return CommonStock(
        security_id=sec_id,
        holder_id=holder_id,
        shares=float(shares),
        price=float(price),
    )


def preferred(
    shares: float,
    price: float,
    seniority: int = 1,
    liquidation_multiple: float = 1.0,
    participating: bool = False,
    participation_cap: float | None = None,
    conversion_ratio: float = 1.0,
    holder_id: str = "investor",
    security_id: str | None = None,
    dividend: CumulativeDividend | NonCumulativeDividend | None = None,
) -> PreferredStock:
    """Create a Preferred Stock security combinator.

    ``dividend`` defaults to no dividend right, which reproduces every pre-dividend result.
    """
    sec_id = security_id or f"pref_sr{seniority}_{holder_id}"
    return PreferredStock(
        security_id=sec_id,
        holder_id=holder_id,
        shares=float(shares),
        price=float(price),
        seniority=seniority,
        liquidation_multiple=liquidation_multiple,
        participating=participating,
        participation_cap=participation_cap,
        conversion_ratio=conversion_ratio,
        dividend=dividend,
    )


def cumulative_dividend(
    annual_rate: float,
    *,
    accrual: Literal["simple", "compound"],
    day_count: DividendDayCount,
    accrues_from: date,
    settlement: DividendSettlement,
    compounding_frequency: int | None = None,
    participation_cap_basis: DividendCapBasis | None = None,
) -> CumulativeDividend:
    """Create a cumulative dividend term. Accrual, day count, start date and settlement have
    no default. ``participation_cap_basis=None`` applies the NVCA Model COI fn 20 reading
    (accrued dividends inside the cap), and the result's assumptions say so."""
    return CumulativeDividend(
        annual_rate=float(annual_rate),
        accrual=accrual,
        compounding_frequency=compounding_frequency,
        day_count=day_count,
        accrues_from=accrues_from,
        settlement=settlement,
        participation_cap_basis=participation_cap_basis,
    )


def non_cumulative_dividend(annual_rate: float) -> NonCumulativeDividend:
    """Create a non-cumulative dividend term. It accrues nothing (NVCA Model COI s.1)."""
    return NonCumulativeDividend(annual_rate=float(annual_rate))


def safe_post(
    amount: float,
    cap: float,
    discount_rate: float = 0.0,
    holder_id: str = "safe_investor",
    security_id: str | None = None,
) -> PostMoneySAFE:
    """Create a YC Post-Money SAFE security combinator."""
    sec_id = security_id or f"safe_post_{holder_id}"
    return PostMoneySAFE(
        security_id=sec_id,
        holder_id=holder_id,
        investment_amount=float(amount),
        valuation_cap=float(cap),
        discount_rate=float(discount_rate),
    )


def safe_pre(
    amount: float,
    cap: float,
    discount_rate: float = 0.0,
    holder_id: str = "safe_investor",
    security_id: str | None = None,
) -> PreMoneySAFE:
    """Create a Pre-Money SAFE security combinator."""
    sec_id = security_id or f"safe_pre_{holder_id}"
    return PreMoneySAFE(
        security_id=sec_id,
        holder_id=holder_id,
        investment_amount=float(amount),
        valuation_cap=float(cap),
        discount_rate=float(discount_rate),
    )


def option_pool(
    reserved_shares: float,
    allocated_shares: float = 0.0,
    holder_id: str = "esop",
    security_id: str | None = None,
) -> StockOptionPool:
    """Create a Stock Option Pool combinator."""
    sec_id = security_id or "esop_pool"
    return StockOptionPool(
        security_id=sec_id,
        holder_id=holder_id,
        reserved_shares=float(reserved_shares),
        allocated_shares=float(allocated_shares),
        price=0.0,
    )
