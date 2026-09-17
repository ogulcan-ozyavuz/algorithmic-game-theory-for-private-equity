"""Named debt fixtures with documented derivations.

Each expected value is derived by hand in `docs/debt.md` and asserted against the
engine in `tests/test_debt.py`. Every fixture pins its time basis: an issue date, an
as-of date and a day count. `reviewed_by` is empty until an external specialist signs
off.

Time basis shared by most cases: issued 2025-01-01, measured 2027-01-01. Neither 2025
nor 2026 is a leap year, so that span is 365 + 365 = 730 days, exactly 2.0 years under
Actual/365 Fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import ovf
from ovf.instruments import (
    ConvertibleNote,
    DebtInstrument,
    convertible_note,
    debt,
    venture_debt,
)

ISSUE = date(2025, 1, 1)
AS_OF = date(2027, 1, 1)  # 730 days after ISSUE
NOTE_ISSUE = date(2026, 1, 1)  # 365 days before AS_OF
NOTE_MATURITY = date(2028, 1, 1)  # 730 days after NOTE_ISSUE
ACT_365 = "actual/365_fixed"
ACT_360 = "actual/360"

SIMPLE_365 = (
    "Simple interest, actual days over a 365-day year. Fenwick seed-stage convertible "
    "note form: interest 'computed based on the actual number of days elapsed and on a "
    "year of three hundred sixty-five (365) days'; D3 note template: 'a simple rate of "
    "8% per annum'. Actual/365 Fixed as named in ISDA 2006 s.4.16(d) (secondary source)."
)
SIMPLE_360 = (
    "Actual/360 as named in ISDA 2006 s.4.16(e) (secondary source): the same days over "
    "a 360-day year, so the same loan accrues more."
)
COMPOUND = (
    "A nominal annual rate r compounded m times a year grows by (1 + r/m) each period "
    "(standard textbook definition, e.g. Hull, Options, Futures, and Other Derivatives, "
    "ch. 4). m is a stated parameter; only whole periods are accepted."
)
PIK = (
    "PIK interest 'is periodically added to the principal balance of the loan, rather "
    "than being paid ... in cash' (Barings BDC 10-K FY2021, PIK income policy)."
)
PRIORITY = (
    "Preferred is paid 'out of the assets of the Corporation available for distribution "
    "to its stockholders' (NVCA Model COI, Oct 2025, Art. Fourth B s.2.1); on "
    "dissolution claims are paid according to their priority before remaining assets go "
    "to stockholders (DGCL s.281(a))."
)
PRO_RATA = (
    "Among claims of equal priority, scarce assets are paid ratably (DGCL s.281(a)); the "
    "engine applies the same pro-rata-by-claim rule it already uses within a preferred tier."
)
VENTURE_FEE = (
    "End-of-term payments are 'generally a fixed percentage of the original principal "
    "balance of the loan', due 'at the maturity date of the loan, including upon "
    "prepayment' (TriplePoint Venture Growth 10-K FY2023). Stated here as an amount: "
    "3% of $2,000,000 = $60,000."
)
NOTE_MULTIPLE = (
    "Change of control: 'the sum of (x) all accrued and unpaid interest ... and (y) two "
    "times (2x) the outstanding principal balance' (D3 note template s.4.3). The Fenwick "
    "form s.2.3 pays the balance plus [one] times the original principal: the same amount."
)
NOTE_FINANCING = (
    "Fenwick seed-stage note: a Next Financing of 'no less than [One Million Dollars]' "
    "converts the balance at 'the lower of' the discounted round price and '$[VALUATION "
    "CAP]' divided by 'the number of shares' the form specifies."
)


@dataclass(frozen=True)
class AccrualFixture:
    case_id: str
    description: str
    convention: str
    instrument: DebtInstrument
    as_of: date
    expected_days: int
    expected_year_fraction: float
    expected_periods: int | None
    expected_outstanding_principal: float
    expected_accrued_interest: float
    expected_claim: float
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class DebtWaterfallFixture:
    case_id: str
    description: str
    convention: str
    exit_valuation: float
    as_of: date
    securities: tuple[ovf.Security, ...]
    expected: dict[str, float]
    expected_claims: dict[str, float]
    expected_converted: dict[str, bool]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class NoteConversionFixture:
    case_id: str
    description: str
    convention: str
    note_security: ConvertibleNote
    financing_date: date
    new_money: float
    round_price: float
    capitalization_shares: float
    expected_amount: float
    expected_cap_price: float
    expected_discount_price: float
    expected_price: float
    expected_binding: str
    expected_shares: float
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


def founders() -> ovf.CommonStock:
    return ovf.common(8_000_000, holder_id="founders", security_id="common")


def series_a(*, seniority: int = 1) -> ovf.PreferredStock:
    """2,000,000 shares at $2.50 = $5,000,000, 1x non-participating."""
    return ovf.preferred(
        2_000_000, 2.50, seniority=seniority, holder_id="series_a", security_id="series_a"
    )


def loan(
    *,
    principal: float = 1_000_000,
    accrual: str = "simple",
    compounding_frequency: int | None = None,
    day_count: str = ACT_365,
    seniority: int = 0,
    security_id: str = "loan",
    maturity_date: date | None = date(2030, 1, 1),
) -> DebtInstrument:
    """$1,000,000 at 8% a year, issued 2025-01-01."""
    return debt(
        principal,
        0.08,
        accrual=accrual,
        compounding_frequency=compounding_frequency,
        day_count=day_count,
        issue_date=ISSUE,
        maturity_date=maturity_date,
        seniority=seniority,
        holder_id="bank",
        security_id=security_id,
    )


def note(**kwargs: object) -> ConvertibleNote:
    """$500,000 at 6% simple, issued 2026-01-01, $8M cap, 20% discount, $1M threshold."""
    terms: dict[str, object] = {
        "accrual": "simple",
        "day_count": ACT_365,
        "issue_date": NOTE_ISSUE,
        "maturity_date": NOTE_MATURITY,
        "seniority": 1,
        "qualified_financing_threshold": 1_000_000,
        "valuation_cap": 8_000_000,
        "discount_rate": 0.20,
        "holder_id": "angel",
        "security_id": "note",
    }
    terms.update(kwargs)
    return convertible_note(500_000, 0.06, **terms)  # type: ignore[arg-type]


def venture_loan() -> ovf.Security:
    """$2,000,000 at 10% simple from 2025-01-01 with a $60,000 exit fee."""
    return venture_debt(
        2_000_000,
        0.10,
        exit_fee=60_000,
        accrual="simple",
        day_count=ACT_365,
        issue_date=ISSUE,
        maturity_date=date(2029, 1, 1),
        seniority=0,
        holder_id="lender",
        security_id="venture_debt",
    )


ACCRUAL_FIXTURES: tuple[AccrualFixture, ...] = (
    AccrualFixture(
        case_id="A1",
        description="simple interest over an exact two-year term",
        convention=SIMPLE_365,
        instrument=loan(),
        as_of=AS_OF,
        expected_days=730,
        expected_year_fraction=2.0,
        expected_periods=None,
        expected_outstanding_principal=1_000_000,
        expected_accrued_interest=160_000,
        expected_claim=1_160_000,
        note="$1,000,000 x 0.08 x 730/365 = $160,000.",
    ),
    AccrualFixture(
        case_id="A2",
        description="annual compounding over the same term",
        convention=COMPOUND,
        instrument=loan(accrual="compound", compounding_frequency=1),
        as_of=AS_OF,
        expected_days=730,
        expected_year_fraction=2.0,
        expected_periods=2,
        expected_outstanding_principal=1_000_000,
        expected_accrued_interest=166_400,
        expected_claim=1_166_400,
        note="1.08^2 = 1.1664; $6,400 above simple, which is 8% of year one's $80,000.",
    ),
    AccrualFixture(
        case_id="A3",
        description="quarterly compounding over the same term",
        convention=COMPOUND,
        instrument=loan(accrual="compound", compounding_frequency=4),
        as_of=AS_OF,
        expected_days=730,
        expected_year_fraction=2.0,
        expected_periods=8,
        expected_outstanding_principal=1_000_000,
        expected_accrued_interest=171_659.3810022656,
        expected_claim=1_171_659.3810022656,
        note="1.02^8 = 102^8 / 10^16 = 1.1716593810022656 exactly.",
    ),
    AccrualFixture(
        case_id="A4",
        description="PIK, semiannual capitalisation",
        convention=PIK,
        instrument=loan(accrual="pik", compounding_frequency=2),
        as_of=AS_OF,
        expected_days=730,
        expected_year_fraction=2.0,
        expected_periods=4,
        expected_outstanding_principal=1_169_858.56,
        expected_accrued_interest=0,
        expected_claim=1_169_858.56,
        note="Principal 1,040,000 -> 1,081,600 -> 1,124,864 -> 1,169,858.56; no cash interest.",
    ),
    AccrualFixture(
        case_id="A5",
        description="simple interest, Actual/360, same dates as A1",
        convention=SIMPLE_360,
        instrument=loan(day_count=ACT_360),
        as_of=AS_OF,
        expected_days=730,
        expected_year_fraction=730 / 360,
        expected_periods=None,
        expected_outstanding_principal=1_000_000,
        expected_accrued_interest=58_400_000 / 360,
        expected_claim=1_000_000 + 58_400_000 / 360,
        note="$80,000 x 730/360 = $162,222.22; the day count alone adds $2,222.22.",
    ),
    AccrualFixture(
        case_id="A6",
        description="simple interest across a leap day",
        convention=SIMPLE_365,
        instrument=debt(
            1_000_000,
            0.08,
            accrual="simple",
            day_count=ACT_365,
            issue_date=date(2027, 1, 1),
            seniority=0,
            holder_id="bank",
            security_id="loan_2027",
        ),
        as_of=date(2029, 1, 1),
        expected_days=731,
        expected_year_fraction=731 / 365,
        expected_periods=None,
        expected_outstanding_principal=1_000_000,
        expected_accrued_interest=58_480_000 / 365,
        expected_claim=1_000_000 + 58_480_000 / 365,
        note="2028 has 29 February: 731 days, so $80,000 x 731/365 = $160,219.18.",
    ),
)


DEBT_WATERFALL_FIXTURES: tuple[DebtWaterfallFixture, ...] = (
    DebtWaterfallFixture(
        case_id="D1",
        description="debt fully covered; equity shares the remainder",
        convention=PRIORITY,
        exit_valuation=36_160_000,
        as_of=AS_OF,
        securities=(founders(), series_a(), loan()),
        expected={"common": 28_000_000, "series_a": 7_000_000, "loan": 1_160_000},
        expected_claims={"loan": 1_160_000},
        expected_converted={"series_a": True},
        note="The $1.16M claim is paid first; the $35M residual reproduces F1.",
    ),
    DebtWaterfallFixture(
        case_id="D2",
        description="debt not covered; every equity holder receives zero",
        convention=PRIORITY,
        exit_valuation=1_000_000,
        as_of=AS_OF,
        securities=(founders(), series_a(), loan()),
        expected={"common": 0, "series_a": 0, "loan": 1_000_000},
        expected_claims={"loan": 1_160_000},
        expected_converted={"series_a": False},
        note="$1M against a $1.16M claim: the lender takes everything, $160,000 short.",
    ),
    DebtWaterfallFixture(
        case_id="D3",
        description="senior and junior debt; proceeds short of the junior claim",
        convention=PRIORITY,
        exit_valuation=1_500_000,
        as_of=AS_OF,
        securities=(founders(), series_a(), loan(), note().resolved("repay")),
        expected={"common": 0, "series_a": 0, "loan": 1_160_000, "note": 340_000},
        expected_claims={"loan": 1_160_000, "note": 530_000},
        expected_converted={"series_a": False},
        note="Senior $1.16M paid in full; the junior note takes the $340,000 left.",
    ),
    DebtWaterfallFixture(
        case_id="D4",
        description="one pari-passu debt tier; proceeds split by claim",
        convention=PRO_RATA,
        exit_valuation=870_000,
        as_of=AS_OF,
        securities=(
            founders(),
            series_a(),
            loan(),
            loan(principal=500_000, security_id="loan_b"),
        ),
        expected={"common": 0, "series_a": 0, "loan": 580_000, "loan_b": 290_000},
        expected_claims={"loan": 1_160_000, "loan_b": 580_000},
        expected_converted={"series_a": False},
        note="Claims $1.16M and $0.58M total $1.74M; $870,000 is half of it, split 2:1.",
    ),
    DebtWaterfallFixture(
        case_id="D5",
        description="venture debt exit fee included in the claim",
        convention=VENTURE_FEE,
        exit_valuation=37_460_000,
        as_of=AS_OF,
        securities=(founders(), series_a(), venture_loan()),
        expected={"common": 28_000_000, "series_a": 7_000_000, "venture_debt": 2_460_000},
        expected_claims={"venture_debt": 2_460_000},
        expected_converted={"series_a": True},
        note="$2M + $400,000 interest + $60,000 fee = $2.46M; the $35M residual is F1.",
    ),
    DebtWaterfallFixture(
        case_id="D6",
        description="PIK debt: the exit claim is the grown principal",
        convention=PIK,
        exit_valuation=16_169_858.56,
        as_of=AS_OF,
        securities=(founders(), series_a(), loan(accrual="pik", compounding_frequency=2)),
        expected={"common": 10_000_000, "series_a": 5_000_000, "loan": 1_169_858.56},
        expected_claims={"loan": 1_169_858.56},
        expected_converted={"series_a": False},
        note="The $15M residual reproduces F2: Series A holds its $5M preference.",
    ),
    DebtWaterfallFixture(
        case_id="D7",
        description="convertible note paid a change-of-control multiple",
        convention=NOTE_MULTIPLE,
        exit_valuation=16_030_000,
        as_of=AS_OF,
        securities=(
            founders(),
            series_a(),
            note().resolved("multiple", exit_principal_multiple=2),
        ),
        expected={"common": 10_000_000, "series_a": 5_000_000, "note": 1_030_000},
        expected_claims={"note": 1_030_000},
        expected_converted={"series_a": False},
        note="2 x $500,000 + $30,000 interest = $1.03M; the $15M residual is F2.",
    ),
)


NOTE_CONVERSION_FIXTURES: tuple[NoteConversionFixture, ...] = (
    NoteConversionFixture(
        case_id="C1",
        description="qualified financing; the cap binds",
        convention=NOTE_FINANCING,
        note_security=note(),
        financing_date=AS_OF,
        new_money=3_000_000,
        round_price=1.50,
        capitalization_shares=8_000_000,
        expected_amount=530_000,
        expected_cap_price=1.00,
        expected_discount_price=1.20,
        expected_price=1.00,
        expected_binding="cap",
        expected_shares=530_000,
        note="$8M / 8M shares = $1.00 beats $1.50 x 0.8 = $1.20.",
    ),
    NoteConversionFixture(
        case_id="C2",
        description="qualified financing; the discount binds",
        convention=NOTE_FINANCING,
        note_security=note(),
        financing_date=AS_OF,
        new_money=3_000_000,
        round_price=1.10,
        capitalization_shares=8_000_000,
        expected_amount=530_000,
        expected_cap_price=1.00,
        expected_discount_price=0.88,
        expected_price=0.88,
        expected_binding="discount",
        expected_shares=530_000 / 0.88,
        note="$1.10 x 0.8 = $0.88 beats the $1.00 cap price; 602,272.73 shares.",
    ),
)
