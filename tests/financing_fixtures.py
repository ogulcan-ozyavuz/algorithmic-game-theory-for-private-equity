"""Named financing fixtures: one issuance applied to a cap table, with documented derivations.

Every expected conversion price, ratio, share count and payout is derived by hand in
`docs/financing.md` and asserted in `tests/test_financing.py` against `ovf.financing`.
Nothing here was copied from engine output; each figure was rechecked with exact rational
arithmetic before being written down. `reviewed_by` stays empty until an external
specialist confirms the term shapes and the arithmetic.

Shared capitalization (continues `docs/fixtures.md` and `docs/antidilution.md`):

- founders: 8,000,000 common;
- Series Seed: 2,000,000 preferred at an original issue price of $1.50 ($3,000,000);
- Series A: 2,000,000 preferred at $2.50 ($5,000,000), as in every other fixture file;
- option pool: 3,000,000 reserved, of which 2,000,000 are granted options and 1,000,000
  is unallocated reserve.

Both series start at a ratio of 1, so CP1 is $1.50 for Seed and $2.50 for Series A.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ovf
from ovf.antidilution import (
    BROAD_BASED_NVCA,
    NARROW_BASED_OUTSTANDING_STOCK,
)
from ovf.financing import (
    FULL_RATCHET,
    UNPROTECTED,
    AntiDilutionProtection,
    ExemptionDetermination,
    NewIssue,
    Outcome,
    weighted_average_protection,
)

BROAD = weighted_average_protection(BROAD_BASED_NVCA)
NARROW = weighted_average_protection(NARROW_BASED_OUTSTANDING_STOCK)

FOUNDERS = ovf.common(8_000_000, holder_id="founders", security_id="common")
SEED = ovf.preferred(2_000_000, 1.50, seniority=3, holder_id="seed_fund", security_id="seed")
SERIES_A = ovf.preferred(2_000_000, 2.50, seniority=2, holder_id="series_a", security_id="series_a")
POOL = ovf.option_pool(3_000_000, allocated_shares=2_000_000, security_id="pool")
TABLE: tuple[ovf.Security, ...] = (FOUNDERS, SEED, SERIES_A, POOL)

# Pre-issuance components of A, counted from TABLE.
COMMON = 8_000_000
PREFERRED_AS_CONVERTED = 4_000_000
OPTIONS = 2_000_000
RESERVE = 1_000_000


def series_b(shares: float, price: float) -> ovf.PreferredStock:
    """The new money: a senior Series B at a 1:1 initial ratio."""
    return ovf.preferred(shares, price, seniority=1, holder_id="series_b", security_id="series_b")


# 4,000,000 Series B shares for $5,000,000: $1.25 a share, below both CP1s. C = 4,000,000.
DOWN_ROUND = NewIssue(securities=(series_b(4_000_000, 1.25),), aggregate_consideration=5_000_000)
# 1,000,000 Series B shares for $3,000,000: $3.00, above both CP1s.
UP_ROUND = NewIssue(securities=(series_b(1_000_000, 3.00),), aggregate_consideration=3_000_000)
# 1,000,000 Series B shares for $2,000,000: $2.00, below Series A's $2.50, above Seed's $1.50.
BETWEEN_ROUND = NewIssue(securities=(series_b(1_000_000, 2.00),), aggregate_consideration=2_000_000)
# 4,000,000 common issued to an acquired company's holders, board value $5,000,000.
ACQUISITION = NewIssue(
    securities=(
        ovf.common(4_000_000, holder_id="acquired_holders", security_id="acquisition_common"),
    ),
    aggregate_consideration=5_000_000,
)

NOT_EXEMPT = ExemptionDetermination(
    exempted=False,
    basis="Cash sale of a new preferred series to investors; not on the charter's list of "
    "Exempted Securities.",
)
ACQUISITION_EXEMPT = ExemptionDetermination(
    exempted=True,
    basis="Common issued as acquisition consideration, an Exempted Security under the "
    "charter (NVCA Model COI Oct 2025, 4.4.1 'Additional Shares of Common Stock', "
    "bracketed acquisition clause).",
)

NVCA_IMMEDIATELY_PRIOR = (
    "NVCA Model COI (Oct 2025) 4.4.4: CP1 is the conversion price 'in effect immediately "
    "prior to such issuance'; A counts common issuable on conversion of the Preferred "
    "Stock 'outstanding ... immediately prior to such issue'. Each series is adjusted "
    "from the same pre-issuance A."
)
NVCA_BROAD = (
    "Broad-based weighted average, NVCA 4.4.4: CP2 = CP1 * (A + B) / (A + C), A counting "
    "common, preferred as converted and granted options, not the unallocated reserve."
)
NARROW_BASED = (
    "Same formula with A narrowed to common and preferred as converted. That composition "
    "was not verified against a charter text; see docs/antidilution.md."
)
NVCA_RATCHET = (
    "NVCA 4.4.4 full-ratchet alternative: CP2 is the consideration per share of the issue. "
    "No charter combining it on one series with weighted average on another was examined."
)
NVCA_EXEMPTED = (
    "NVCA 4.4.1: Additional Shares of Common Stock exclude the Exempted Securities, so an "
    "exempted issuance triggers no adjustment. The determination is the caller's."
)


@dataclass(frozen=True)
class FinancingFixture:
    case_id: str
    description: str
    convention: str
    issue: NewIssue
    protection: dict[str, AntiDilutionProtection]
    exemption: ExemptionDetermination
    expected_outcomes: dict[str, Outcome]
    # Conversion price after the issuance, for each pre-existing preferred position.
    expected_conversion_prices: dict[str, float]
    # Conversion ratio of every preferred position in the new table, new series included.
    expected_ratios: dict[str, float]
    expected_fully_diluted: float
    table: tuple[ovf.Security, ...] = TABLE
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


FINANCING_FIXTURES: tuple[FinancingFixture, ...] = (
    FinancingFixture(
        case_id="FA1",
        description="one protected series, broad-based",
        convention=NVCA_BROAD,
        issue=DOWN_ROUND,
        protection={"seed": UNPROTECTED, "series_a": BROAD},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "unprotected", "series_a": "adjusted"},
        expected_conversion_prices={"seed": 1.50, "series_a": 20 / 9},
        expected_ratios={"seed": 1.0, "series_a": 9 / 8, "series_b": 1.0},
        expected_fully_diluted=19_250_000,
        note="A = 14M, B = 2M, C = 4M: CP2 = $2.50 x 16/18 = $20/9; ratio 9/8.",
    ),
    FinancingFixture(
        case_id="FA1n",
        description="FA1 under a narrow-based definition of A",
        convention=NARROW_BASED,
        issue=DOWN_ROUND,
        protection={"seed": UNPROTECTED, "series_a": NARROW},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "unprotected", "series_a": "adjusted"},
        expected_conversion_prices={"seed": 1.50, "series_a": 35 / 16},
        expected_ratios={"seed": 1.0, "series_a": 8 / 7, "series_b": 1.0},
        expected_fully_diluted=8_000_000 + 2_000_000 + 16_000_000 / 7 + 3_000_000 + 4_000_000,
        note="A = 12M: CP2 = $2.50 x 14/16 = $2.1875; ratio 8/7. Options leave A.",
    ),
    FinancingFixture(
        case_id="FA2",
        description="the FA1 issuance with no series protected",
        convention=NVCA_BROAD,
        issue=DOWN_ROUND,
        protection={"seed": UNPROTECTED, "series_a": UNPROTECTED},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "unprotected", "series_a": "unprotected"},
        expected_conversion_prices={"seed": 1.50, "series_a": 2.50},
        expected_ratios={"seed": 1.0, "series_a": 1.0, "series_b": 1.0},
        expected_fully_diluted=19_000_000,
        note="Nothing is adjusted; the new table is the old one plus Series B.",
    ),
    FinancingFixture(
        case_id="FA3",
        description="two protected series from one issuance, both broad-based",
        convention=NVCA_IMMEDIATELY_PRIOR,
        issue=DOWN_ROUND,
        protection={"seed": BROAD, "series_a": BROAD},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "adjusted", "series_a": "adjusted"},
        expected_conversion_prices={"seed": 13 / 9, "series_a": 20 / 9},
        expected_ratios={"seed": 27 / 26, "series_a": 9 / 8, "series_b": 1.0},
        expected_fully_diluted=251_250_000 / 13,
        note=(
            "Both use A = 14M. Seed: B = 10M/3, CP2 = (14M x 1.50 + 4M x 1.25) / 18M = "
            "$13/9, ratio 27/26. Series A exactly as in FA1."
        ),
    ),
    FinancingFixture(
        case_id="FA4",
        description="Seed on full ratchet, Series A on broad-based weighted average",
        convention=NVCA_RATCHET,
        issue=DOWN_ROUND,
        protection={"seed": FULL_RATCHET, "series_a": BROAD},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "adjusted", "series_a": "adjusted"},
        expected_conversion_prices={"seed": 1.25, "series_a": 20 / 9},
        expected_ratios={"seed": 6 / 5, "series_a": 9 / 8, "series_b": 1.0},
        expected_fully_diluted=19_650_000,
        note=(
            "Seed ratchets to $1.25 (ratio 6/5). Series A's A still counts Seed at its "
            "pre-issuance 2,000,000, so Series A is unchanged from FA1."
        ),
    ),
    FinancingFixture(
        case_id="FA5",
        description="issue above both conversion prices",
        convention=NVCA_BROAD,
        issue=UP_ROUND,
        protection={"seed": FULL_RATCHET, "series_a": BROAD},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "not_triggered", "series_a": "not_triggered"},
        expected_conversion_prices={"seed": 1.50, "series_a": 2.50},
        expected_ratios={"seed": 1.0, "series_a": 1.0, "series_b": 1.0},
        expected_fully_diluted=16_000_000,
        note="$3.00 is above $1.50 and $2.50: no adjustment and no replaced position.",
    ),
    FinancingFixture(
        case_id="FA5b",
        description="issue between the two conversion prices",
        convention=NVCA_BROAD,
        issue=BETWEEN_ROUND,
        protection={"seed": FULL_RATCHET, "series_a": BROAD},
        exemption=NOT_EXEMPT,
        expected_outcomes={"seed": "not_triggered", "series_a": "adjusted"},
        expected_conversion_prices={"seed": 1.50, "series_a": 37 / 15},
        expected_ratios={"seed": 1.0, "series_a": 75 / 74, "series_b": 1.0},
        expected_fully_diluted=8_000_000 + 2_000_000 + 75_000_000 / 37 + 3_000_000 + 1_000_000,
        note=(
            "$2.00 triggers Series A only: A = 14M, B = 0.8M, C = 1M, CP2 = $2.50 x "
            "14.8/15 = $37/15. Seed's full ratchet does not fire: $2.00 > $1.50."
        ),
    ),
    FinancingFixture(
        case_id="FA6",
        description="exempted issuance: acquisition common at the down-round size and price",
        convention=NVCA_EXEMPTED,
        issue=ACQUISITION,
        protection={"seed": BROAD, "series_a": BROAD},
        exemption=ACQUISITION_EXEMPT,
        expected_outcomes={"seed": "exempted", "series_a": "exempted"},
        expected_conversion_prices={"seed": 1.50, "series_a": 2.50},
        expected_ratios={"seed": 1.0, "series_a": 1.0},
        expected_fully_diluted=19_000_000,
        note=(
            "Same C (4M) and consideration ($5M) as FA3, so without the exemption the "
            "result would be FA3's. The exemption suppresses both adjustments."
        ),
    ),
)


# --- Order independence (FA3), and what the naive reading would give ------------------

# If A were recomputed after each series is adjusted, the second series would see the
# first series' increased as-converted count, and the answer would depend on the order.
# Seed first (A' = 12M + 27M/13 = 183M/13) then Series A: CP2 = $209/94.
NAIVE_SEED_THEN_A = {"seed": 13 / 9, "series_a": 209 / 94}
# Series A first (A' = 14.25M) then Seed: CP2 = $211/146.
NAIVE_A_THEN_SEED = {"seed": 211 / 146, "series_a": 20 / 9}


# --- An adjusted table carried into an exit --------------------------------------------

EXIT_FOUNDERS = ovf.common(8_000_000, holder_id="founders", security_id="common")
EXIT_SERIES_A = ovf.preferred(
    2_000_000, 2.50, seniority=2, holder_id="series_a", security_id="series_a"
)
EXIT_POOL = ovf.option_pool(1_000_000, security_id="pool")
EXIT_TABLE: tuple[ovf.Security, ...] = (EXIT_FOUNDERS, EXIT_SERIES_A, EXIT_POOL)
EXIT_VALUATION = 301_000_000


@dataclass(frozen=True)
class ExitAfterFinancingFixture:
    case_id: str
    description: str
    protection: dict[str, AntiDilutionProtection]
    expected_series_a_ratio: float
    expected: dict[str, float]
    expected_converted: dict[str, bool]
    table: tuple[ovf.Security, ...] = EXIT_TABLE
    issue: NewIssue = DOWN_ROUND
    exemption: ExemptionDetermination = NOT_EXEMPT
    exit_valuation: float = EXIT_VALUATION
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


EXIT_FIXTURES: tuple[ExitAfterFinancingFixture, ...] = (
    ExitAfterFinancingFixture(
        case_id="FX1a",
        description="Series A protected broad-based, then a $301M exit",
        protection={"series_a": BROAD},
        expected_series_a_ratio=7 / 6,
        expected={
            "common": 168_000_000,
            "series_a": 49_000_000,
            "pool": 0,
            "series_b": 84_000_000,
        },
        expected_converted={"series_a": True, "series_b": True},
        note=(
            "A = 10M: CP2 = $2.50 x 12/14 = $15/7, ratio 7/6, 7M/3 shares. All convert "
            "over 43M/3 shares: Series A 7/43 x $301M = $49M."
        ),
    ),
    ExitAfterFinancingFixture(
        case_id="FX1b",
        description="same issuance and exit, Series A unprotected",
        protection={"series_a": UNPROTECTED},
        expected_series_a_ratio=1.0,
        expected={
            "common": 172_000_000,
            "series_a": 43_000_000,
            "pool": 0,
            "series_b": 86_000_000,
        },
        expected_converted={"series_a": True, "series_b": True},
        note="All convert over 14M shares: Series A 2/14 x $301M = $43M.",
    ),
)
