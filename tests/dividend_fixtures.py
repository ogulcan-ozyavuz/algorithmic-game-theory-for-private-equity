"""Named preferred-dividend fixtures with documented derivations.

Each expected value is derived by hand in `docs/dividends.md` and asserted against the
engine in `tests/test_dividends.py`. Every fixture pins its time basis: an accrual start
date, an as-of date and a day count. `reviewed_by` is empty until an external specialist
signs off.

Shared time basis: dividends accrue from 2025-01-01 and are measured on 2027-01-01. Neither
2025 nor 2026 is a leap year, so the span is 365 + 365 = 730 days, exactly 2.0 years under
Actual/365 Fixed. The long-horizon cases run to 2039-12-29, which is 5,475 = 15 x 365 days.

Shared equity, as in `docs/fixtures.md`: founders hold 8,000,000 common. Series A holds
2,000,000 preferred at a $2.50 Original Issue Price, $5,000,000 invested, 1x, converting
1:1. An 8% dividend on the Original Issue Price is $0.20 per share, or $400,000 a year for
the position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import ovf
from ovf.contracts.securities import (
    CumulativeDividend,
    DividendCapBasis,
    DividendDayCount,
    DividendSettlement,
    NonCumulativeDividend,
    cumulative_dividend,
    non_cumulative_dividend,
)
from ovf.instruments import debt

ACCRUES_FROM = date(2025, 1, 1)
AS_OF = date(2027, 1, 1)  # 730 days after ACCRUES_FROM
LONG_AS_OF = date(2039, 12, 29)  # 5,475 days = 15 x 365 after ACCRUES_FROM
ACT_365: DividendDayCount = "actual/365_fixed"
ACT_360: DividendDayCount = "actual/360"
RATE = 0.08

NVCA_SIMPLE = (
    "A cumulative dividend of a fixed amount per share per annum that 'shall accrue from "
    "day to day, whether or not declared, and shall be cumulative' (NVCA Model COI, Oct "
    "2025, s.1, third alternative). A '$____ per share' dividend 'will by definition be "
    "non-compounding' (fn 13). 8% of the $2.50 Original Issue Price is $0.20 per share."
)
NVCA_COMPOUND = (
    "NVCA fn 13 compounding variant: 'dividends at the rate per annum of [8]% of the "
    "Original Issue Price ..., plus the amount of previously accrued dividends, compounded "
    "annually'."
)
DAY_COUNT_360 = (
    "The NVCA text says only 'accrue from day to day'; the year basis is a separate term. "
    "Actual/360 as named in ISDA 2006 s.4.16(e) (secondary source), as in docs/debt.md."
)
NVCA_PREFERENCE = (
    "With accruing dividends the preference is 'the Original Issue Price, plus any "
    "Accruing Dividends accrued but unpaid thereon, whether or not declared' (NVCA fn "
    "18/20). On conversion all rights cease 'except only the right ... to receive shares "
    "of Common Stock in exchange therefor and to receive payment of any dividends declared "
    "but unpaid thereon' (s.4.3.3); 'accruing dividends are not taken into account in a "
    "conversion' (fn 46)."
)
NVCA_PRO_RATA = (
    "A short tier shares 'ratably ... in proportion to the respective amounts which would "
    "otherwise be payable in respect of the shares held by them upon such distribution if "
    "all amounts payable on or with respect to such shares were paid in full' (NVCA Model "
    "COI s.2.1), so the accrued dividends weight the split."
)
CAP_INSIDE = (
    "NVCA fn 20: the cap applies where 'the aggregate amount which the holders of Preferred "
    "Stock are entitled to receive under Sections 2.1 and 2.2 shall exceed [$___] per "
    "share', and 2.1 holds the accrued dividends (fn 19). The holder then receives 'the "
    "greater of (i) the Maximum Participation Amount and (ii)' its as-converted amount. "
    "Filed charters drafted this way: Sage Therapeutics (2014), Global Blood Therapeutics "
    "(2015), Spark Therapeutics (2014)."
)
CAP_OUTSIDE = (
    "Virtual Piggy charter (8-K 2014, Ex. 3.1 s.4.2): the cap is 'two-and-a-half times "
    "(2.5x) the Series B Original Issue Price, plus any Accruing Dividends accrued but "
    "unpaid thereon, whether or not declared'. The accrued amount sits on top of the "
    "multiple."
)
PIK = (
    "Spark Therapeutics charter (S-1 2014, Ex. 3.1 s.1.1): accruing dividends due on a "
    "liquidation or a conversion 'shall be paid by the issuance of shares of Series B "
    "Preferred Stock determined by dividing the aggregate amount of the Series B Accruing "
    "Dividends by the Series B Original Issue Price'. Those shares 'receive the same "
    "consideration' as the other shares of the series (s.2.1)."
)
NON_CUMULATIVE = (
    "NVCA Model COI s.1, second alternative: the right 'shall not be cumulative, and no "
    "right to dividends shall accrue to holders of Preferred Stock by reason of the fact "
    "that dividends on such shares are not declared or paid'."
)
DEBT_FIRST = (
    "Debt is paid ahead of all equity (docs/debt.md, NVCA s.2.1 'assets ... available for "
    "distribution to its stockholders'); debt interest and dividends accrue to one as_of."
)


def founders() -> ovf.CommonStock:
    return ovf.common(8_000_000, holder_id="founders", security_id="common")


def dividend(
    *,
    accrual: str = "simple",
    compounding_frequency: int | None = None,
    day_count: DividendDayCount = ACT_365,
    settlement: DividendSettlement = "forfeit_on_conversion",
    participation_cap_basis: DividendCapBasis | None = None,
) -> CumulativeDividend:
    """8% of the Original Issue Price a year, accruing from 2025-01-01."""
    return cumulative_dividend(
        RATE,
        accrual=accrual,  # type: ignore[arg-type]
        compounding_frequency=compounding_frequency,
        day_count=day_count,
        accrues_from=ACCRUES_FROM,
        settlement=settlement,
        participation_cap_basis=participation_cap_basis,
    )


def series_a(
    term: CumulativeDividend | NonCumulativeDividend | None = None,
    *,
    participating: bool = False,
    participation_cap: float | None = None,
) -> ovf.PreferredStock:
    """2,000,000 shares at $2.50 = $5,000,000, 1x, seniority 1."""
    return ovf.preferred(
        2_000_000,
        2.50,
        seniority=1,
        participating=participating,
        participation_cap=participation_cap,
        holder_id="series_a",
        security_id="series_a",
        dividend=term,
    )


def series_b() -> ovf.PreferredStock:
    """1,500,000 shares at $6.00 = $9,000,000, 1x, no dividend, pari passu with Series A."""
    return ovf.preferred(1_500_000, 6.00, seniority=1, holder_id="series_b", security_id="series_b")


def loan() -> ovf.Security:
    """$1,000,000 at 8% simple, Actual/365 Fixed, from 2025-01-01: docs/debt.md case A1."""
    return debt(
        1_000_000,
        0.08,
        accrual="simple",
        day_count="actual/365_fixed",
        issue_date=ACCRUES_FROM,
        maturity_date=date(2030, 1, 1),
        seniority=0,
        holder_id="bank",
        security_id="loan",
    )


@dataclass(frozen=True)
class DividendAccrualFixture:
    case_id: str
    description: str
    convention: str
    position: ovf.PreferredStock
    as_of: date
    expected_days: int | None
    expected_periods: int | None
    expected_accrued_per_share: float
    expected_accrued: float
    expected_preference: float
    expected_units: float
    expected_paid_in_kind_shares: float | None = None
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class DividendWaterfallFixture:
    case_id: str
    description: str
    convention: str
    exit_valuation: float
    as_of: date | None
    securities: tuple[ovf.Security, ...]
    expected: dict[str, float]
    expected_converted: dict[str, bool]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class FlipFixture:
    """The exit at which Series A is indifferent between its preference and converting."""

    case_id: str
    description: str
    convention: str
    securities: tuple[ovf.Security, ...]
    as_of: date | None
    flip_exit: float
    expected_at_flip: dict[str, float]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


ACCRUAL_FIXTURES: tuple[DividendAccrualFixture, ...] = (
    DividendAccrualFixture(
        case_id="DV1",
        description="simple accrual over an exact two-year term",
        convention=NVCA_SIMPLE,
        position=series_a(dividend()),
        as_of=AS_OF,
        expected_days=730,
        expected_periods=None,
        expected_accrued_per_share=0.40,
        expected_accrued=800_000,
        expected_preference=5_800_000,
        expected_units=2_000_000,
        note="$0.20 x 730/365 = $0.40 a share; x 2,000,000 = $800,000.",
    ),
    DividendAccrualFixture(
        case_id="DV2",
        description="annual compounding over the same term",
        convention=NVCA_COMPOUND,
        position=series_a(dividend(accrual="compound", compounding_frequency=1)),
        as_of=AS_OF,
        expected_days=730,
        expected_periods=2,
        expected_accrued_per_share=0.416,
        expected_accrued=832_000,
        expected_preference=5_832_000,
        expected_units=2_000_000,
        note="1.08^2 - 1 = 0.1664; $32,000 above simple, which is 8% of year one's $400,000.",
    ),
    DividendAccrualFixture(
        case_id="DV3",
        description="simple accrual, Actual/360, same dates as DV1",
        convention=DAY_COUNT_360,
        position=series_a(dividend(day_count=ACT_360)),
        as_of=AS_OF,
        expected_days=730,
        expected_periods=None,
        expected_accrued_per_share=0.20 * 730 / 360,
        expected_accrued=292_000_000 / 360,
        expected_preference=5_000_000 + 292_000_000 / 360,
        expected_units=2_000_000,
        note="$400,000 x 730/360 = $811,111.11; the day count alone adds $11,111.11.",
    ),
    DividendAccrualFixture(
        case_id="DV4",
        description="non-cumulative dividend accrues nothing",
        convention=NON_CUMULATIVE,
        position=series_a(non_cumulative_dividend(RATE)),
        as_of=AS_OF,
        expected_days=None,
        expected_periods=None,
        expected_accrued_per_share=0,
        expected_accrued=0,
        expected_preference=5_000_000,
        expected_units=2_000_000,
        note="No right accrues unless declared, so the preference stays 1x = $5,000,000.",
    ),
    DividendAccrualFixture(
        case_id="DV5",
        description="simple accrual over fifteen 365-day years",
        convention=NVCA_SIMPLE,
        position=series_a(dividend()),
        as_of=LONG_AS_OF,
        expected_days=5_475,
        expected_periods=None,
        expected_accrued_per_share=3.00,
        expected_accrued=6_000_000,
        expected_preference=11_000_000,
        expected_units=2_000_000,
        note="$0.20 x 15 = $3.00 a share; $6,000,000 accrued; the preference is $11,000,000.",
    ),
    DividendAccrualFixture(
        case_id="DV6",
        description="paid in kind: the accrued amount becomes shares of the series",
        convention=PIK,
        position=series_a(dividend(settlement="paid_in_kind")),
        as_of=AS_OF,
        expected_days=730,
        expected_periods=None,
        expected_accrued_per_share=0.40,
        expected_accrued=800_000,
        expected_preference=5_800_000,
        expected_units=2_320_000,
        expected_paid_in_kind_shares=320_000,
        note="$800,000 / $2.50 = 320,000 new shares; 2,320,000 x $2.50 = $5,800,000.",
    ),
)


WATERFALL_FIXTURES: tuple[DividendWaterfallFixture, ...] = (
    DividendWaterfallFixture(
        case_id="DW1",
        description="accrued dividends change who converts",
        convention=NVCA_PREFERENCE,
        exit_valuation=27_000_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend())),
        expected={"common": 21_200_000, "series_a": 5_800_000},
        expected_converted={"series_a": False},
        note="20% x $27M = $5.4M is below the $5.8M preference; without dividends A converts.",
    ),
    DividendWaterfallFixture(
        case_id="DW1-none",
        description="the same exit without a dividend: Series A converts",
        convention=NVCA_PREFERENCE,
        exit_valuation=27_000_000,
        as_of=None,
        securities=(founders(), series_a()),
        expected={"common": 21_600_000, "series_a": 5_400_000},
        expected_converted={"series_a": True},
        note="20% x $27M = $5.4M beats the $5M preference.",
    ),
    DividendWaterfallFixture(
        case_id="DW2",
        description="participation cap includes the accrued amount (default)",
        convention=CAP_INSIDE,
        exit_valuation=40_000_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend(), participating=True, participation_cap=2.0)),
        expected={"common": 30_000_000, "series_a": 10_000_000},
        expected_converted={"series_a": False},
        note="$5.8M + 20% x $34.2M = $12.64M, capped at 2 x $5M = $10M; converting pays $8M.",
    ),
    DividendWaterfallFixture(
        case_id="DW3",
        description="participation cap excludes the accrued amount",
        convention=CAP_OUTSIDE,
        exit_valuation=40_000_000,
        as_of=AS_OF,
        securities=(
            founders(),
            series_a(
                dividend(participation_cap_basis="excludes_dividends"),
                participating=True,
                participation_cap=2.0,
            ),
        ),
        expected={"common": 29_200_000, "series_a": 10_800_000},
        expected_converted={"series_a": False},
        note="The cap is $10M + $0.8M = $10.8M; $12.64M uncapped exceeds it.",
    ),
    DividendWaterfallFixture(
        case_id="DW4",
        description="paid in kind with a per-share cap: the cap scales with the new shares",
        convention=PIK,
        exit_valuation=40_000_000,
        as_of=AS_OF,
        securities=(
            founders(),
            series_a(
                dividend(settlement="paid_in_kind"), participating=True, participation_cap=2.0
            ),
        ),
        expected={"common": 28_400_000, "series_a": 11_600_000},
        expected_converted={"series_a": False},
        note="Cap 2 x 2,320,000 x $2.50 = $11.6M; uncapped $13.49M; converting pays $8.99M.",
    ),
    DividendWaterfallFixture(
        case_id="DW5",
        description="accrued preference above the cap: clamped at the cap (inside)",
        convention=CAP_INSIDE,
        exit_valuation=40_000_000,
        as_of=LONG_AS_OF,
        securities=(founders(), series_a(dividend(), participating=True, participation_cap=2.0)),
        expected={"common": 30_000_000, "series_a": 10_000_000},
        expected_converted={"series_a": False},
        note="$11M preference exceeds the $10M cap, so A receives $10M; converting pays $8M.",
    ),
    DividendWaterfallFixture(
        case_id="DW6",
        description="the same fifteen-year case with the cap outside",
        convention=CAP_OUTSIDE,
        exit_valuation=40_000_000,
        as_of=LONG_AS_OF,
        securities=(
            founders(),
            series_a(
                dividend(participation_cap_basis="excludes_dividends"),
                participating=True,
                participation_cap=2.0,
            ),
        ),
        expected={"common": 24_000_000, "series_a": 16_000_000},
        expected_converted={"series_a": False},
        note="Cap $10M + $6M = $16M; $11M + 20% x $29M = $16.8M exceeds it.",
    ),
    DividendWaterfallFixture(
        case_id="DW7",
        description="proceeds short of preference plus dividends, split pro rata in one tier",
        convention=NVCA_PRO_RATA,
        exit_valuation=7_400_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend()), series_b()),
        expected={"common": 0, "series_a": 2_900_000, "series_b": 4_500_000},
        expected_converted={"series_a": False, "series_b": False},
        note="Claims $5.8M and $9M total $14.8M; $7.4M is half, so $2.9M and $4.5M.",
    ),
    DividendWaterfallFixture(
        case_id="DW7-none",
        description="the same shortfall without the dividend",
        convention=NVCA_PRO_RATA,
        exit_valuation=7_400_000,
        as_of=None,
        securities=(founders(), series_a(), series_b()),
        expected={
            "common": 0,
            "series_a": 7_400_000 * 5 / 14,
            "series_b": 7_400_000 * 9 / 14,
        },
        expected_converted={"series_a": False, "series_b": False},
        note="Claims 5:9, so $2,642,857.14 and $4,757,142.86.",
    ),
    DividendWaterfallFixture(
        case_id="DW8",
        description="non-cumulative class: nothing accrues and no date is needed",
        convention=NON_CUMULATIVE,
        exit_valuation=15_000_000,
        as_of=None,
        securities=(founders(), series_a(non_cumulative_dividend(RATE))),
        expected={"common": 10_000_000, "series_a": 5_000_000},
        expected_converted={"series_a": False},
        note="Identical to F2: the $5M preference beats 20% x $15M = $3M.",
    ),
    DividendWaterfallFixture(
        case_id="DW9",
        description="paid in kind, participating: the new shares participate",
        convention=PIK,
        exit_valuation=31_600_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend(settlement="paid_in_kind"), participating=True)),
        expected={"common": 20_000_000, "series_a": 11_600_000},
        expected_converted={"series_a": False},
        note="$5.8M, then $25.8M over 10,320,000 units = $2.50 a unit: A 2,320,000 units.",
    ),
    DividendWaterfallFixture(
        case_id="DW9-forfeit",
        description="the same exit with the dividend added to the preference instead",
        convention=NVCA_PREFERENCE,
        exit_valuation=31_600_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend(), participating=True)),
        expected={"common": 20_640_000, "series_a": 10_960_000},
        expected_converted={"series_a": False},
        note="$5.8M, then 20% x $25.8M = $5.16M.",
    ),
    DividendWaterfallFixture(
        case_id="DW10",
        description="paid in kind, converting: the new shares convert and dilute common",
        convention=PIK,
        exit_valuation=30_960_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend(settlement="paid_in_kind"))),
        expected={"common": 24_000_000, "series_a": 6_960_000},
        expected_converted={"series_a": True},
        note="$30.96M over 10,320,000 units = $3.00 a unit; beats the $5.8M preference.",
    ),
    DividendWaterfallFixture(
        case_id="DW11",
        description="debt and a dividend accrue to one as_of",
        convention=DEBT_FIRST,
        exit_valuation=28_160_000,
        as_of=AS_OF,
        securities=(founders(), series_a(dividend()), loan()),
        expected={"common": 21_200_000, "series_a": 5_800_000, "loan": 1_160_000},
        expected_converted={"series_a": False},
        note="The loan takes $1.16M (debt A1); the $27M residual is DW1.",
    ),
)


FLIP_FIXTURES: tuple[FlipFixture, ...] = (
    FlipFixture(
        case_id="FL0",
        description="no dividend (F3)",
        convention=NVCA_PREFERENCE,
        securities=(founders(), series_a()),
        as_of=None,
        flip_exit=25_000_000,
        expected_at_flip={"common": 20_000_000, "series_a": 5_000_000},
        note="0.20 x X = $5M at X = $25M.",
    ),
    FlipFixture(
        case_id="FL1",
        description="simple dividend, forfeited on conversion",
        convention=NVCA_PREFERENCE,
        securities=(founders(), series_a(dividend())),
        as_of=AS_OF,
        flip_exit=29_000_000,
        expected_at_flip={"common": 23_200_000, "series_a": 5_800_000},
        note="0.20 x X = $5.8M at X = $29M: the flip moves up by $0.8M / 0.20 = $4M.",
    ),
    FlipFixture(
        case_id="FL2",
        description="annually compounded dividend, forfeited on conversion",
        convention=NVCA_COMPOUND,
        securities=(founders(), series_a(dividend(accrual="compound", compounding_frequency=1))),
        as_of=AS_OF,
        flip_exit=29_160_000,
        expected_at_flip={"common": 23_328_000, "series_a": 5_832_000},
        note="0.20 x X = $5.832M at X = $29.16M.",
    ),
    FlipFixture(
        case_id="FL3",
        description="simple dividend paid in kind",
        convention=PIK,
        securities=(founders(), series_a(dividend(settlement="paid_in_kind"))),
        as_of=AS_OF,
        flip_exit=25_800_000,
        expected_at_flip={"common": 20_000_000, "series_a": 5_800_000},
        note="2.32/10.32 x X = $5.8M at X = $2.50 x 10,320,000 = $25.8M.",
    ),
)
