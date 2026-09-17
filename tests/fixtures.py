"""Named exit-waterfall fixtures with documented derivations.

Each case states a cap table, an exit value and the expected cash allocation.
Expected values are derived by hand in `docs/fixtures.md` and independently
recomputed there with exact rational arithmetic. Term shapes follow documented
market conventions; see that document for the provenance of each shape and for
the review status. `reviewed_by` is empty until an external specialist signs off.

Amounts are whole base-currency units. `expected` covers every security in the
table, so a fixture also asserts that nothing is left unallocated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ovf

# Shared starting capitalization: 8,000,000 founder common shares.
FOUNDER_SHARES = 8_000_000


@dataclass(frozen=True)
class WaterfallFixture:
    case_id: str
    description: str
    convention: str
    exit_valuation: float
    securities: tuple[ovf.Security, ...]
    expected: dict[str, float]
    expected_converted: dict[str, bool]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


def _founders() -> ovf.CommonStock:
    return ovf.common(FOUNDER_SHARES, holder_id="founders", security_id="common")


def _series_a(
    *,
    seniority: int = 2,
    liquidation_multiple: float = 1.0,
    participating: bool = False,
    participation_cap: float | None = None,
) -> ovf.PreferredStock:
    """2,000,000 shares at $2.50 = $5,000,000 invested."""
    return ovf.preferred(
        shares=2_000_000,
        price=2.50,
        seniority=seniority,
        liquidation_multiple=liquidation_multiple,
        participating=participating,
        participation_cap=participation_cap,
        holder_id="series_a",
        security_id="series_a",
    )


def _series_b(*, seniority: int = 1) -> ovf.PreferredStock:
    """1,500,000 shares at $6.00 = $9,000,000 invested."""
    return ovf.preferred(
        shares=1_500_000,
        price=6.00,
        seniority=seniority,
        holder_id="series_b",
        security_id="series_b",
    )


MARKET_1X_NONPART = (
    "1x non-participating preferred. Cooley's Q2 2026 venture financing report "
    "records a 1x preference in 95.8% and non-participating terms in 96.4% of "
    "reported financings, so this is the dominant reported shape."
)
MARKET_PARTICIPATING = (
    "Participating preferred. Kaplan & Stromberg (2003, Review of Economic Studies "
    "70(2)) record participating preferred in roughly 40% of 1987-1999 rounds; "
    "Carta reports 4.1% of primary rounds in Q3 2024. Structure is now uncommon "
    "but reappears in down rounds, so it stays in the supported scope."
)
MARKET_SENIORITY = (
    "Stacked seniority (later series senior) and pari passu are the two standard "
    "conventions for ranking multiple preferred series; both are modeled."
)
MARKET_POOL = (
    "An unallocated option reserve counts in fully diluted ownership but holds no "
    "issued shares, so it receives no exit cash. See docs/semantics.md."
)


FIXTURES: tuple[WaterfallFixture, ...] = (
    WaterfallFixture(
        case_id="F1",
        description="1x non-participating above the conversion threshold",
        convention=MARKET_1X_NONPART,
        exit_valuation=35_000_000,
        securities=(_founders(), _series_a()),
        expected={"common": 28_000_000, "series_a": 7_000_000},
        expected_converted={"series_a": True},
        note="20% of $35M is $7M, above the $5M preference, so Series A converts.",
    ),
    WaterfallFixture(
        case_id="F2",
        description="1x non-participating below the conversion threshold",
        convention=MARKET_1X_NONPART,
        exit_valuation=15_000_000,
        securities=(_founders(), _series_a()),
        expected={"common": 10_000_000, "series_a": 5_000_000},
        expected_converted={"series_a": False},
        note="20% of $15M is $3M, below the $5M preference, so Series A holds it.",
    ),
    WaterfallFixture(
        case_id="F3",
        description="exact conversion indifference point",
        convention=MARKET_1X_NONPART,
        exit_valuation=25_000_000,
        securities=(_founders(), _series_a()),
        expected={"common": 20_000_000, "series_a": 5_000_000},
        expected_converted={"series_a": False},
        note=(
            "Preference equals as-converted value at $25M. Both conversion profiles "
            "are equilibria and both pay the same amounts; the solver keeps the "
            "incumbent decision on a tie."
        ),
    ),
    WaterfallFixture(
        case_id="F4",
        description="participating preferred, uncapped",
        convention=MARKET_PARTICIPATING,
        exit_valuation=35_000_000,
        securities=(_founders(), _series_a(participating=True)),
        expected={"common": 24_000_000, "series_a": 11_000_000},
        expected_converted={"series_a": False},
        note="$5M preference plus 20% of the $30M residual is $11M, above $7M converted.",
    ),
    WaterfallFixture(
        case_id="F5a",
        description="participation cap binds",
        convention=MARKET_PARTICIPATING,
        exit_valuation=40_000_000,
        securities=(_founders(), _series_a(participating=True, participation_cap=2.0)),
        expected={"common": 30_000_000, "series_a": 10_000_000},
        expected_converted={"series_a": False},
        note=(
            "Uncapped participation would pay $12M; the 2x cap stops it at $10M, "
            "still above the $8M as-converted value."
        ),
    ),
    WaterfallFixture(
        case_id="F5b",
        description="cap makes conversion the better action",
        convention=MARKET_PARTICIPATING,
        exit_valuation=60_000_000,
        securities=(_founders(), _series_a(participating=True, participation_cap=2.0)),
        expected={"common": 48_000_000, "series_a": 12_000_000},
        expected_converted={"series_a": True},
        note="Above a $50M exit the 20% as-converted share beats the $10M cap.",
    ),
    WaterfallFixture(
        case_id="F6",
        description="stacked seniority, proceeds below total preference",
        convention=MARKET_SENIORITY,
        exit_valuation=10_000_000,
        securities=(_founders(), _series_a(), _series_b(seniority=1)),
        expected={"common": 0, "series_a": 1_000_000, "series_b": 9_000_000},
        expected_converted={"series_a": False, "series_b": False},
        note="Senior Series B takes $9M first; Series A receives the $1M remainder.",
    ),
    WaterfallFixture(
        case_id="F7",
        description="pari passu, proceeds below total preference",
        convention=MARKET_SENIORITY,
        exit_valuation=10_000_000,
        securities=(_founders(), _series_a(), _series_b(seniority=2)),
        expected={
            "common": 0,
            "series_a": 10_000_000 * 5 / 14,
            "series_b": 10_000_000 * 9 / 14,
        },
        expected_converted={"series_a": False, "series_b": False},
        note="$10M splits 5:9 across the $5M and $9M claims in one tier.",
    ),
    WaterfallFixture(
        case_id="F8a",
        description="upper edge of the common dead zone",
        convention=MARKET_SENIORITY,
        exit_valuation=14_000_000,
        securities=(_founders(), _series_a(), _series_b(seniority=1)),
        expected={"common": 0, "series_a": 5_000_000, "series_b": 9_000_000},
        expected_converted={"series_a": False, "series_b": False},
        note="Total preference is $14M; common receives zero at and below this exit.",
    ),
    WaterfallFixture(
        case_id="F8b",
        description="first exit above the dead zone",
        convention=MARKET_SENIORITY,
        exit_valuation=20_000_000,
        securities=(_founders(), _series_a(), _series_b(seniority=1)),
        expected={"common": 6_000_000, "series_a": 5_000_000, "series_b": 9_000_000},
        expected_converted={"series_a": False, "series_b": False},
        note="Preferences absorb $14M; the $6M residual goes entirely to common.",
    ),
    WaterfallFixture(
        case_id="F9",
        description="unallocated pool dilutes ownership but takes no proceeds",
        convention=MARKET_POOL,
        exit_valuation=35_000_000,
        securities=(
            _founders(),
            _series_a(),
            ovf.option_pool(1_000_000, holder_id="esop", security_id="pool"),
        ),
        expected={"common": 28_000_000, "series_a": 7_000_000, "pool": 0},
        expected_converted={"series_a": True},
        note=(
            "Series A is 2/11 = 18.18% of fully diluted equity but receives 20% of "
            "proceeds, because the unallocated reserve holds no issued shares."
        ),
    ),
    WaterfallFixture(
        case_id="F10",
        description="2x participating preferred",
        convention=MARKET_PARTICIPATING,
        exit_valuation=30_000_000,
        securities=(
            _founders(),
            _series_a(liquidation_multiple=2.0, participating=True),
        ),
        expected={"common": 16_000_000, "series_a": 14_000_000},
        expected_converted={"series_a": False},
        note="A $10M double preference plus 20% of the $20M residual pays $14M.",
    ),
)


def cap_table(fixture: WaterfallFixture) -> ovf.CapTable:
    return ovf.CapTable(securities=list(fixture.securities))
