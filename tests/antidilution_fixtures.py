"""Named anti-dilution fixtures with documented derivations.

Every expected conversion price and ratio is derived by hand in `docs/antidilution.md`
and asserted here against `ovf.antidilution`. The capitalization continues the shared
cap table of `docs/fixtures.md` (8,000,000 founder common; Series A 2,000,000 shares at
$2.50) and adds granted options and an unallocated reserve, so that the definitions of
`A` give different numbers. `reviewed_by` stays empty until an external specialist
confirms the term shapes and the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ovf.antidilution import (
    BROAD_BASED_NVCA,
    BROAD_BASED_WITH_RESERVED_POOL,
    NARROW_BASED_OUTSTANDING_STOCK,
    CapitalizationBeforeIssue,
    ConversionPriceAdjustment,
    DeemedOutstandingDefinition,
    DilutiveIssuance,
    full_ratchet,
    weighted_average,
)

# Series A: 2,000,000 shares at an original issue price of $2.50 = $5,000,000 invested.
# Its conversion price starts equal to the original issue price, so CP1 = $2.50.
SERIES_A_SHARES = 2_000_000
SERIES_A_ORIGINAL_ISSUE_PRICE = 2.50
SERIES_A_INVESTED = 5_000_000
CP1 = 2.50

CAPITALIZATION = CapitalizationBeforeIssue(
    common_outstanding=8_000_000,
    preferred_as_converted=2_000_000,
    options_and_warrants_as_exercised=2_000_000,
    other_convertibles_as_converted=0,
    reserved_unissued_pool=1_000_000,
)

# 4,000,000 shares for $5,000,000: $1.25 a share, half of CP1.
DOWN_ROUND = DilutiveIssuance(shares_issued=4_000_000, aggregate_consideration=5_000_000)
# 1,000,000 shares for $3,000,000: $3.00 a share, above CP1.
UP_ROUND = DilutiveIssuance(shares_issued=1_000_000, aggregate_consideration=3_000_000)
# 4,000,000 shares for nothing.
FREE_ISSUE = DilutiveIssuance(shares_issued=4_000_000, aggregate_consideration=0)

NVCA_WEIGHTED_AVERAGE = (
    "NVCA Model Certificate of Incorporation 4.4.4, broad-based weighted average: "
    "CP2 = CP1 * (A + B) / (A + C), applied when Additional Shares of Common Stock are "
    "issued without consideration or below the conversion price in effect. WilmerHale's "
    "2026 Venture Capital Report records weighted average in 100% of its 2025 first "
    "rounds; Kaplan & Stromberg (2003) record 78.1% of 1987-1999 rounds with protection."
)
NARROW_BASED = (
    "Same formula with a smaller A. The narrowing is charter-dependent; this composition "
    "(common plus preferred as-converted) was not verified against a charter text."
)
RESERVE_IN_A = (
    "Same formula with the reserved but ungranted pool deemed outstanding. The NVCA "
    "definition of A does not count it; a charter that does must say so."
)
NVCA_FULL_RATCHET = (
    "NVCA Model Certificate of Incorporation, full-ratchet alternative to 4.4.4: CP2 is "
    "the consideration per share of the dilutive issue. WilmerHale's 2026 report records "
    "it in 0% of 2025 first rounds and 3% of later rounds; Kaplan & Stromberg (2003) "
    "record 21.9% of 1987-1999 rounds with protection."
)


@dataclass(frozen=True)
class AntidilutionFixture:
    case_id: str
    description: str
    convention: str
    method: Literal["weighted_average", "full_ratchet"]
    issuance: DilutiveIssuance
    definition: DeemedOutstandingDefinition | None
    expected_a: float | None
    expected_b: float | None
    expected_conversion_price: float
    expected_triggered: bool
    expected_conversion_ratio: float
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


ANTIDILUTION_FIXTURES: tuple[AntidilutionFixture, ...] = (
    AntidilutionFixture(
        case_id="AD1",
        description="broad-based weighted average, NVCA definition of A",
        convention=NVCA_WEIGHTED_AVERAGE,
        method="weighted_average",
        issuance=DOWN_ROUND,
        definition=BROAD_BASED_NVCA,
        expected_a=12_000_000,
        expected_b=2_000_000,
        expected_conversion_price=2.50 * 14 / 16,
        expected_triggered=True,
        expected_conversion_ratio=8 / 7,
        note="A = 8M + 2M + 2M; CP2 = $2.50 x 14M / 16M = $2.1875.",
    ),
    AntidilutionFixture(
        case_id="AD2",
        description="narrow-based weighted average on the same issuance",
        convention=NARROW_BASED,
        method="weighted_average",
        issuance=DOWN_ROUND,
        definition=NARROW_BASED_OUTSTANDING_STOCK,
        expected_a=10_000_000,
        expected_b=2_000_000,
        expected_conversion_price=15 / 7,
        expected_triggered=True,
        expected_conversion_ratio=7 / 6,
        note="A = 8M + 2M; CP2 = $2.50 x 12M / 14M = $15/7, below AD1's $2.1875.",
    ),
    AntidilutionFixture(
        case_id="AD3",
        description="full ratchet on the same issuance",
        convention=NVCA_FULL_RATCHET,
        method="full_ratchet",
        issuance=DOWN_ROUND,
        definition=None,
        expected_a=None,
        expected_b=None,
        expected_conversion_price=1.25,
        expected_triggered=True,
        expected_conversion_ratio=2.0,
        note="CP2 = $5M / 4M shares = $1.25, the largest of the three adjustments.",
    ),
    AntidilutionFixture(
        case_id="AD4",
        description="broad-based with the reserved pool deemed outstanding",
        convention=RESERVE_IN_A,
        method="weighted_average",
        issuance=DOWN_ROUND,
        definition=BROAD_BASED_WITH_RESERVED_POOL,
        expected_a=13_000_000,
        expected_b=2_000_000,
        expected_conversion_price=75 / 34,
        expected_triggered=True,
        expected_conversion_ratio=17 / 15,
        note="A = 13M; CP2 = $2.50 x 15M / 17M = $75/34, above AD1: a larger A softens it.",
    ),
    AntidilutionFixture(
        case_id="AD5a",
        description="issue above the conversion price, broad-based",
        convention=NVCA_WEIGHTED_AVERAGE,
        method="weighted_average",
        issuance=UP_ROUND,
        definition=BROAD_BASED_NVCA,
        expected_a=12_000_000,
        expected_b=1_200_000,
        expected_conversion_price=2.50,
        expected_triggered=False,
        expected_conversion_ratio=1.0,
        note="$3.00 > $2.50: no adjustment. The raw formula would give $2.50 x 13.2/13.",
    ),
    AntidilutionFixture(
        case_id="AD5b",
        description="issue above the conversion price, narrow-based",
        convention=NARROW_BASED,
        method="weighted_average",
        issuance=UP_ROUND,
        definition=NARROW_BASED_OUTSTANDING_STOCK,
        expected_a=10_000_000,
        expected_b=1_200_000,
        expected_conversion_price=2.50,
        expected_triggered=False,
        expected_conversion_ratio=1.0,
        note="$3.00 > $2.50: no adjustment. The raw formula would give $2.50 x 11.2/11.",
    ),
    AntidilutionFixture(
        case_id="AD5c",
        description="issue above the conversion price, full ratchet",
        convention=NVCA_FULL_RATCHET,
        method="full_ratchet",
        issuance=UP_ROUND,
        definition=None,
        expected_a=None,
        expected_b=None,
        expected_conversion_price=2.50,
        expected_triggered=False,
        expected_conversion_ratio=1.0,
        note="$3.00 > $2.50: no adjustment. A ratchet to the issue price would raise it.",
    ),
    AntidilutionFixture(
        case_id="AD6a",
        description="issuance without consideration, broad-based",
        convention=NVCA_WEIGHTED_AVERAGE,
        method="weighted_average",
        issuance=FREE_ISSUE,
        definition=BROAD_BASED_NVCA,
        expected_a=12_000_000,
        expected_b=0,
        expected_conversion_price=1.875,
        expected_triggered=True,
        expected_conversion_ratio=4 / 3,
        note="B = 0; CP2 = $2.50 x 12M / 16M = $1.875, the floor for this A and C.",
    ),
    AntidilutionFixture(
        case_id="AD6b",
        description="issuance without consideration, narrow-based",
        convention=NARROW_BASED,
        method="weighted_average",
        issuance=FREE_ISSUE,
        definition=NARROW_BASED_OUTSTANDING_STOCK,
        expected_a=10_000_000,
        expected_b=0,
        expected_conversion_price=25 / 14,
        expected_triggered=True,
        expected_conversion_ratio=7 / 5,
        note="B = 0; CP2 = $2.50 x 10M / 14M = $25/14.",
    ),
)


def adjust(fixture: AntidilutionFixture) -> ConversionPriceAdjustment:
    if fixture.method == "full_ratchet":
        return full_ratchet(conversion_price=CP1, issuance=fixture.issuance)
    assert fixture.definition is not None
    return weighted_average(
        conversion_price=CP1,
        capitalization=CAPITALIZATION,
        definition=fixture.definition,
        issuance=fixture.issuance,
    )
