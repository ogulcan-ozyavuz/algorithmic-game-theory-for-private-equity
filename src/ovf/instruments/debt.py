"""Debt instruments: term debt, convertible notes and venture debt.

Every amount owed is a function of an explicit, caller-supplied ``as_of`` date. No
method reads a clock: an instrument has no claim until it is asked for one on a stated
date, so the same inputs give the same number on every day the code is run.

Conventions implemented, each stated rather than defaulted:

- Year fraction is ``days / 365`` (Actual/365 Fixed) or ``days / 360`` (Actual/360),
  chosen per instrument. There is no default day count.
- Simple interest is ``P * r * days / basis``. Compound interest and PIK capitalise at a
  stated number of periods per year and are refused unless the elapsed days span a whole
  number of those periods, because interest over a partial period (the stub) is
  contract-specific.
- Accrual stops at ``maturity_date``: an ``as_of`` after maturity is refused, because
  post-maturity terms (demand, default interest, extension) are not modelled.

Debt carries zero shares. It adds nothing to fully diluted ownership until it converts,
and conversion produces a share count that the caller turns into a new equity security
in a new snapshot. See ``docs/debt.md`` for sources, derivations and what is not
modelled.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ovf.contracts.securities import Security
from ovf.core.types import (
    FinancialBaseModel,
    Money,
    Multiple,
    Percentage,
    Seniority,
    ShareCount,
    SharePrice,
)


class DayCount(StrEnum):
    """Year-fraction conventions named as in ISDA 2006 Definitions Section 4.16(d) and (e)."""

    ACT_365_FIXED = "actual/365_fixed"  # actual days elapsed / 365
    ACT_360 = "actual/360"  # actual days elapsed / 360


_DAY_COUNT_DENOMINATOR = {DayCount.ACT_365_FIXED: 365, DayCount.ACT_360: 360}


class AccrualMethod(StrEnum):
    SIMPLE = "simple"  # interest on original principal only
    COMPOUND = "compound"  # interest on interest; principal unchanged
    PIK = "pik"  # interest capitalised into principal at each period end


class NoteExitTreatment(StrEnum):
    """What a convertible note pays at a liquidity event, as stated by the caller.

    A note that converts at the event is not a debt claim: replace it with the equity
    security it converts into before running the waterfall.
    """

    REPAY = "repay"  # outstanding principal plus accrued interest
    MULTIPLE = "multiple"  # exit_principal_multiple * original principal + accrued interest


class DebtAccrual(FinancialBaseModel):
    """Interest accrued on one instrument from its issue date to an explicit as-of date.

    Under PIK, capitalised interest is part of ``outstanding_principal`` and
    ``accrued_interest`` is zero, because PIK accrual is only computed at period ends.
    """

    security_id: str
    issue_date: date
    as_of: date
    day_count: DayCount
    days: int = Field(ge=0)
    year_fraction: float = Field(ge=0.0)
    method: AccrualMethod
    compounding_frequency: int | None
    compounding_periods: int | None = Field(
        description="Whole compounding periods elapsed; None for simple interest"
    )
    annual_rate: Percentage
    principal: Money
    outstanding_principal: Money
    accrued_interest: Money

    @property
    def outstanding_amount(self) -> Money:
        """Outstanding principal plus uncapitalised accrued interest."""
        return self.outstanding_principal + self.accrued_interest


class DebtClaim(FinancialBaseModel):
    """The amount one debt position is owed at a liquidity event, with its derivation."""

    security_id: str
    holder_id: str
    seniority: Seniority
    accrual: DebtAccrual
    exit_fee: Money = 0.0
    claim: Money
    basis: str = Field(description="The formula that produced `claim`, in words")


class NoteConversion(FinancialBaseModel):
    """Shares a convertible note converts into in a qualified financing, and why."""

    security_id: str
    holder_id: str
    accrual: DebtAccrual
    amount_converted: Money
    cap_price: SharePrice | None
    discount_price: SharePrice
    conversion_price: SharePrice
    binding: Literal["cap", "discount", "round_price"]
    shares: ShareCount


def _whole_periods(days: int, denominator: int, frequency: int, security_id: str) -> int:
    """Number of compounding periods in ``days``; refuses a partial period."""
    numerator = days * frequency
    if numerator % denominator:
        raise ValueError(
            f"{security_id}: {days} days is not a whole number of 1/{frequency}-year "
            f"compounding periods under a {denominator}-day year. Interest over a partial "
            "period (the stub) is contract-specific and not modelled; choose an as_of "
            "on a period end"
        )
    return numerator // denominator


def _positive(name: str, value: float | None) -> float:
    if value is None or not (0 < value < math.inf):
        raise ValueError(f"{name} must be stated, finite and positive")
    return float(value)


class DebtInstrument(Security):
    """Interest-bearing debt that ranks ahead of all equity at a liquidity event.

    ``principal`` is the amount originally advanced. The claim at exit is outstanding
    principal plus accrued interest on an explicit ``as_of``. Scheduled repayments,
    amortisation and default interest are not modelled; a partly repaid loan must be
    represented by a new snapshot with its outstanding balance.

    ``seniority`` ranks debt against other debt only (0 before 1). Every debt position
    ranks ahead of every preferred and common position whatever integers are used.
    """

    principal: Money = Field(..., gt=0, description="Amount originally advanced")
    annual_rate: Percentage = Field(..., description="Nominal annual interest rate, e.g. 0.08")
    accrual: AccrualMethod
    compounding_frequency: int | None = Field(
        default=None,
        ge=1,
        strict=True,
        description="Periods per year for compound or PIK accrual; must be None for simple",
    )
    day_count: DayCount
    issue_date: date
    maturity_date: date | None = None
    seniority: Seniority

    @model_validator(mode="after")
    def validate_debt_terms(self) -> Self:
        if self.shares != 0 or self.price != 0:
            raise ValueError("Debt carries no shares or share price until it converts")
        for name in ("issue_date", "maturity_date"):
            if isinstance(getattr(self, name), datetime):
                raise ValueError(f"{name} must be a date; time of day is not modelled")
        if self.accrual is AccrualMethod.SIMPLE:
            if self.compounding_frequency is not None:
                raise ValueError("Simple interest takes no compounding_frequency")
        elif self.compounding_frequency is None:
            raise ValueError(
                f"{self.accrual.value} accrual requires an explicit compounding_frequency"
            )
        if self.maturity_date is not None and self.maturity_date <= self.issue_date:
            raise ValueError("maturity_date must be after issue_date")
        return self

    @property
    def invested_capital(self) -> Money:
        return self.principal

    def is_convertible(self) -> bool:
        return False

    def base_liquidation_preference(self) -> Money:
        raise TypeError(
            f"{self.security_id} is debt, not a liquidation preference; its claim depends "
            "on a date: call exit_claim(as_of)"
        )

    def accrue(self, as_of: date) -> DebtAccrual:
        """Interest from ``issue_date`` to ``as_of`` under the stated method and day count."""
        if not isinstance(as_of, date) or isinstance(as_of, datetime):
            raise ValueError("as_of must be a datetime.date; time of day is not modelled")
        if as_of < self.issue_date:
            raise ValueError(
                f"{self.security_id}: as_of {as_of} is before issue_date {self.issue_date}"
            )
        if self.maturity_date is not None and as_of > self.maturity_date:
            raise ValueError(
                f"{self.security_id}: as_of {as_of} is after maturity_date "
                f"{self.maturity_date}. Post-maturity terms (repayment on demand, default "
                "interest, extension, optional conversion) are not modelled; settle the "
                "instrument at maturity and model the result"
            )
        days = (as_of - self.issue_date).days
        denominator = _DAY_COUNT_DENOMINATOR[self.day_count]
        principal = self.principal
        periods: int | None = None
        if self.accrual is AccrualMethod.SIMPLE:
            outstanding = principal
            interest = principal * self.annual_rate * days / denominator
        else:
            assert self.compounding_frequency is not None  # enforced by the validator
            periods = _whole_periods(
                days, denominator, self.compounding_frequency, self.security_id
            )
            grown = principal * (1 + self.annual_rate / self.compounding_frequency) ** periods
            if self.accrual is AccrualMethod.PIK:
                outstanding, interest = grown, 0.0
            else:
                outstanding, interest = principal, grown - principal
        return DebtAccrual(
            security_id=self.security_id,
            issue_date=self.issue_date,
            as_of=as_of,
            day_count=self.day_count,
            days=days,
            year_fraction=days / denominator,
            method=self.accrual,
            compounding_frequency=self.compounding_frequency,
            compounding_periods=periods,
            annual_rate=self.annual_rate,
            principal=principal,
            outstanding_principal=outstanding,
            accrued_interest=interest,
        )

    def exit_claim(self, as_of: date) -> DebtClaim:
        """Amount owed at a liquidity event on ``as_of``: outstanding principal plus interest."""
        accrual = self.accrue(as_of)
        return DebtClaim(
            security_id=self.security_id,
            holder_id=self.holder_id,
            seniority=self.seniority,
            accrual=accrual,
            claim=accrual.outstanding_amount,
            basis="outstanding principal + accrued interest",
        )


class VentureDebt(DebtInstrument):
    """Venture term debt with a final payment (exit fee, end-of-term charge) due on repayment.

    ``exit_fee`` is a stated amount in base currency, payable in full when the loan is
    repaid at the liquidity event. Agreements state it either as a fixed amount or as a
    percentage of the original principal; the caller converts a percentage to an amount,
    so no fee base is assumed here.

    Attached warrants are not modelled. Warrant coverage is a material part of a venture
    lender's return, so a claim computed here is not the lender's total return.
    Prepayment charges triggered by a change in control are also not included.
    """

    exit_fee: Money = Field(..., description="Final payment due on repayment, base currency")

    def exit_claim(self, as_of: date) -> DebtClaim:
        accrual = self.accrue(as_of)
        return DebtClaim(
            security_id=self.security_id,
            holder_id=self.holder_id,
            seniority=self.seniority,
            accrual=accrual,
            exit_fee=self.exit_fee,
            claim=accrual.outstanding_amount + self.exit_fee,
            basis="outstanding principal + accrued interest + exit fee",
        )


class ConvertibleNote(DebtInstrument):
    """Convertible promissory note: debt until it converts.

    Behaviours modelled, each on an explicit date:

    - **Qualified financing.** A financing raising at least
      ``qualified_financing_threshold`` of new money converts principal plus accrued
      interest at the lower of the cap price (``valuation_cap / capitalization_shares``)
      and the discounted round price. The capitalization count is supplied by the
      caller, because notes define it differently.
    - **Maturity.** Principal plus accrued interest falls due at ``maturity_date``.
      Accrual stops there; anything later is refused.
    - **Liquidity event.** ``exit_treatment`` states what the note pays. There is no
      default: an unresolved note is rejected at exit. A note that converts at the
      event must be replaced by the equity it converts into.

    Holder elections between these outcomes are not modelled; the caller states the
    outcome that the note's terms and the holder's election produce.
    """

    valuation_cap: Money | None = Field(default=None, gt=0)
    discount_rate: Percentage = Field(
        default=0.0, lt=1, description="Discount to the qualified-financing round price"
    )
    qualified_financing_threshold: Money = Field(
        ..., gt=0, description="Minimum new money for automatic conversion"
    )
    exit_treatment: NoteExitTreatment | None = None
    exit_principal_multiple: Multiple | None = Field(
        default=None,
        ge=1,
        description="Multiple of original principal paid at exit, in addition to interest",
    )

    @model_validator(mode="after")
    def validate_note_terms(self) -> Self:
        if self.maturity_date is None:
            raise ValueError("A convertible note requires a maturity_date")
        multiple = self.exit_treatment is NoteExitTreatment.MULTIPLE
        if multiple != (self.exit_principal_multiple is not None):
            raise ValueError(
                "exit_principal_multiple is required for, and only for, exit_treatment='multiple'"
            )
        if multiple and self.accrual is AccrualMethod.PIK:
            raise ValueError(
                "A principal multiple on a PIK note is ambiguous (original or capitalised "
                "principal) and is not modelled"
            )
        return self

    def is_convertible(self) -> bool:
        return True

    def resolved(
        self,
        exit_treatment: NoteExitTreatment | str,
        *,
        exit_principal_multiple: float | None = None,
    ) -> ConvertibleNote:
        """A new snapshot of this note with its liquidity-event treatment stated."""
        return ConvertibleNote.model_validate(
            {
                **self.model_dump(),
                "exit_treatment": NoteExitTreatment(exit_treatment),
                "exit_principal_multiple": exit_principal_multiple,
            }
        )

    def exit_claim(self, as_of: date) -> DebtClaim:
        if self.exit_treatment is None:
            raise ValueError(
                f"Convertible note {self.security_id} has no stated exit treatment. Whether "
                "a note is repaid, paid a multiple or converted at a liquidity event is set "
                "by its terms, not by arithmetic: use note.resolved('repay') or "
                "note.resolved('multiple', exit_principal_multiple=...), or replace the "
                "note with the equity security it converts into"
            )
        accrual = self.accrue(as_of)
        if self.exit_treatment is NoteExitTreatment.REPAY:
            claim = accrual.outstanding_amount
            basis = "outstanding principal + accrued interest"
        else:
            assert self.exit_principal_multiple is not None  # enforced by the validator
            m = self.exit_principal_multiple
            claim = m * accrual.principal + accrual.accrued_interest
            basis = f"{m:g} x original principal + accrued interest"
        return DebtClaim(
            security_id=self.security_id,
            holder_id=self.holder_id,
            seniority=self.seniority,
            accrual=accrual,
            claim=claim,
            basis=basis,
        )

    def is_qualified_financing(self, new_money: float) -> bool:
        if not (0 <= new_money < math.inf):
            raise ValueError("new_money must be finite and nonnegative")
        return new_money >= self.qualified_financing_threshold

    def convert_at_financing(
        self,
        financing_date: date,
        *,
        new_money: float,
        round_price: float,
        capitalization_shares: float | None = None,
    ) -> NoteConversion:
        """Automatic conversion in a qualified financing closing on ``financing_date``.

        Converts principal plus interest accrued to ``financing_date`` at
        ``min(valuation_cap / capitalization_shares, round_price * (1 - discount_rate))``.
        ``capitalization_shares`` is the count the note's cap is divided by; it is
        required when a cap exists and is never inferred. A non-qualified financing is
        refused: conversion there is at the holder's option and not modelled. On an
        exact tie between the two prices the cap is reported as binding.
        """
        if not self.is_qualified_financing(new_money):
            raise ValueError(
                f"{self.security_id}: new money {new_money:,.2f} is below the qualified "
                f"financing threshold {self.qualified_financing_threshold:,.2f}; optional "
                "conversion in a non-qualified financing is not modelled"
            )
        round_price = _positive("round_price", round_price)
        accrual = self.accrue(financing_date)
        discount_price = round_price * (1 - self.discount_rate)
        cap_price: float | None = None
        if self.valuation_cap is not None:
            cap_price = self.valuation_cap / _positive(
                "capitalization_shares", capitalization_shares
            )
        elif capitalization_shares is not None:
            raise ValueError("capitalization_shares is only used with a valuation_cap")
        binding: Literal["cap", "discount", "round_price"]
        if cap_price is not None and cap_price <= discount_price:
            price, binding = cap_price, "cap"
        else:
            price = discount_price
            binding = "discount" if self.discount_rate else "round_price"
        return NoteConversion(
            security_id=self.security_id,
            holder_id=self.holder_id,
            accrual=accrual,
            amount_converted=accrual.outstanding_amount,
            cap_price=cap_price,
            discount_price=discount_price,
            conversion_price=price,
            binding=binding,
            shares=accrual.outstanding_amount / price,
        )

    def repayment_at_maturity(self) -> DebtAccrual:
        """Principal and interest that fall due at ``maturity_date``."""
        assert self.maturity_date is not None  # enforced by the validator
        return self.accrue(self.maturity_date)


# ---------------------------------------------------------------------------
# Constructors, matching the style of ovf.contracts.securities
# ---------------------------------------------------------------------------


def debt(
    principal: float,
    annual_rate: float,
    *,
    accrual: AccrualMethod | str,
    day_count: DayCount | str,
    issue_date: date,
    seniority: int,
    compounding_frequency: int | None = None,
    maturity_date: date | None = None,
    holder_id: str = "lender",
    security_id: str | None = None,
) -> DebtInstrument:
    """Create a plain debt instrument. Accrual, day count and seniority have no default."""
    return DebtInstrument(
        security_id=security_id or f"debt_sr{seniority}_{holder_id}",
        holder_id=holder_id,
        principal=float(principal),
        annual_rate=float(annual_rate),
        accrual=AccrualMethod(accrual),
        compounding_frequency=compounding_frequency,
        day_count=DayCount(day_count),
        issue_date=issue_date,
        maturity_date=maturity_date,
        seniority=seniority,
    )


def venture_debt(
    principal: float,
    annual_rate: float,
    *,
    exit_fee: float,
    accrual: AccrualMethod | str,
    day_count: DayCount | str,
    issue_date: date,
    seniority: int,
    compounding_frequency: int | None = None,
    maturity_date: date | None = None,
    holder_id: str = "venture_lender",
    security_id: str | None = None,
) -> VentureDebt:
    """Create venture term debt with a stated exit fee; warrants are not modelled."""
    return VentureDebt(
        security_id=security_id or f"venture_debt_{holder_id}",
        holder_id=holder_id,
        principal=float(principal),
        annual_rate=float(annual_rate),
        accrual=AccrualMethod(accrual),
        compounding_frequency=compounding_frequency,
        day_count=DayCount(day_count),
        issue_date=issue_date,
        maturity_date=maturity_date,
        seniority=seniority,
        exit_fee=float(exit_fee),
    )


def convertible_note(
    principal: float,
    annual_rate: float,
    *,
    accrual: AccrualMethod | str,
    day_count: DayCount | str,
    issue_date: date,
    maturity_date: date,
    seniority: int,
    qualified_financing_threshold: float,
    valuation_cap: float | None = None,
    discount_rate: float = 0.0,
    compounding_frequency: int | None = None,
    exit_treatment: NoteExitTreatment | str | None = None,
    exit_principal_multiple: float | None = None,
    holder_id: str = "noteholder",
    security_id: str | None = None,
) -> ConvertibleNote:
    """Create a convertible note. Leaving ``exit_treatment`` unset makes it unresolved at exit."""
    return ConvertibleNote(
        security_id=security_id or f"note_{holder_id}",
        holder_id=holder_id,
        principal=float(principal),
        annual_rate=float(annual_rate),
        accrual=AccrualMethod(accrual),
        compounding_frequency=compounding_frequency,
        day_count=DayCount(day_count),
        issue_date=issue_date,
        maturity_date=maturity_date,
        seniority=seniority,
        valuation_cap=None if valuation_cap is None else float(valuation_cap),
        discount_rate=float(discount_rate),
        qualified_financing_threshold=float(qualified_financing_threshold),
        exit_treatment=None if exit_treatment is None else NoteExitTreatment(exit_treatment),
        exit_principal_multiple=(
            None if exit_principal_multiple is None else float(exit_principal_multiple)
        ),
    )
