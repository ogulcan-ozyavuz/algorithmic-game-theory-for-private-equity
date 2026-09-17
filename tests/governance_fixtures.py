"""Named collective-conversion fixtures with documented derivations.

Every expected number is derived by hand in `docs/governance.md` and asserted in
`tests/test_governance.py` against `ovf.governance.resolve_collective_conversion`. None was
copied from engine output. The shared table is the README example: founders 8,000,000
common; Series A 2,000,000 junior participating preferred at $2.50 with a 2x cap; Series B
1,500,000 senior non-participating preferred at $6.00. `reviewed_by` stays empty until an
external specialist confirms the term shapes and the arithmetic.

Amounts are base-currency units. Fractions such as 960/23 are written as they were derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Literal

import ovf
from ovf.governance import CollectiveConversion, VoteRequirement

M = 1_000_000
AS_OF = date(2027, 1, 1)  # 730 days after 2025-01-01

NVCA_REQUISITE_HOLDERS = (
    "NVCA Model COI (Oct 2025) s.2.3.1: 'the holders of at least [specify percentage] of the "
    "outstanding shares of Preferred Stock, voting together as a single class on an "
    'as-converted to Common Stock basis (the "Requisite Holders")\'.'
)
NVCA_MANDATORY_CONVERSION = (
    "NVCA Model COI (Oct 2025) s.5.1(b): all outstanding Preferred Stock converts on 'the "
    "date and time, or upon the occurrence of an event, specified by vote or written consent "
    "of the Requisite Holders'. Upheld when used immediately before a merger in Alta "
    "Berkeley VI C.V. v. Omneon, Inc. (Del. 2012), cited in NVCA fn 64."
)
NVCA_SERIES_CONSENT = (
    "NVCA Model COI (Oct 2025) fn 64: 'where there are multiple series of Preferred Stock, "
    "investors should give consideration to the vote required to trigger a mandatory "
    "conversion'. Modelled as a second approval by a majority of Series B."
)


def founders(shares: float = 8_000_000) -> ovf.CommonStock:
    return ovf.common(shares, holder_id="founders", security_id="common")


def series_a(
    shares: float = 2_000_000, *, holder_id: str = "series_a", security_id: str = "series_a"
) -> ovf.PreferredStock:
    """Junior (seniority 2) 1x participating preferred at $2.50, total capped at 2x."""
    return ovf.preferred(
        shares,
        2.50,
        seniority=2,
        participating=True,
        participation_cap=2.0,
        holder_id=holder_id,
        security_id=security_id,
    )


def series_b(
    *, holder_id: str = "series_b", dividend: ovf.CumulativeDividend | None = None
) -> ovf.PreferredStock:
    """Senior (seniority 1) 1x non-participating preferred: 1,500,000 at $6.00."""
    return ovf.preferred(
        1_500_000, 6.00, seniority=1, holder_id=holder_id, security_id="series_b", dividend=dividend
    )


TABLE: tuple[ovf.Security, ...] = (founders(), series_a(), series_b())
PREFERRED_IDS = ("series_a", "series_b")


def requisite_holders(
    threshold: str, comparison: Literal["at_least", "more_than"], voters: tuple[str, ...]
) -> VoteRequirement:
    return VoteRequirement(
        name="Requisite Holders",
        voters=voters,
        threshold=Fraction(threshold),
        comparison=comparison,
        source=NVCA_REQUISITE_HOLDERS,
    )


def mandatory_conversion(
    threshold: str = "1/2",
    comparison: Literal["at_least", "more_than"] = "more_than",
    *,
    converts: tuple[str, ...] = PREFERRED_IDS,
    extra: tuple[VoteRequirement, ...] = (),
) -> CollectiveConversion:
    return CollectiveConversion(
        name="mandatory conversion",
        converts=converts,
        approvals=(requisite_holders(threshold, comparison, converts), *extra),
        source=NVCA_MANDATORY_CONVERSION,
    )


MAJORITY = mandatory_conversion()
AT_LEAST_60 = mandatory_conversion("3/5", "at_least")
SERIES_B_CONSENT = VoteRequirement(
    name="Series B majority",
    voters=("series_b",),
    threshold=Fraction(1, 2),
    comparison="more_than",
    source=NVCA_SERIES_CONSENT,
)
MAJORITY_WITH_SERIES_B = mandatory_conversion(extra=(SERIES_B_CONSENT,))

# GV7: Series A split between two funds; fund_b also holds all of Series B.
SPLIT_TABLE: tuple[ovf.Security, ...] = (
    founders(),
    series_a(1_500_000, holder_id="fund_a", security_id="series_a1"),
    series_a(500_000, holder_id="fund_b", security_id="series_a2"),
    series_b(holder_id="fund_b"),
)
SPLIT_IDS = ("series_a1", "series_a2", "series_b")

# GV8: a loan ahead of the GV1 table. $1,000,000 at 8% simple, Actual/365 Fixed, issued
# 2025-01-01: 730 days of interest to AS_OF is $160,000, so the claim is $1,160,000.
LOAN = ovf.debt(
    1_000_000,
    0.08,
    accrual="simple",
    day_count="actual/365_fixed",
    issue_date=date(2025, 1, 1),
    seniority=0,
    holder_id="lender",
    security_id="loan",
)

# GV9: Series B with an 8% simple cumulative dividend from 2025-01-01, forfeited on
# conversion. At AS_OF it has accrued $9,000,000 x 0.08 x 2 = $1,440,000.
B_DIVIDEND = ovf.cumulative_dividend(
    0.08,
    accrual="simple",
    day_count="actual/365_fixed",
    accrues_from=date(2025, 1, 1),
    settlement="forfeit_on_conversion",
)


@dataclass(frozen=True)
class GovernanceFixture:
    case_id: str
    description: str
    convention: str
    securities: tuple[ovf.Security, ...]
    exit_valuation: float
    term: CollectiveConversion
    expected_approved: bool
    expected_changes_payout: bool
    expected: dict[str, float]
    expected_decisions: dict[str, str]
    expected_changes: dict[str, float]
    as_of: date | None = None
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


GOVERNANCE_FIXTURES: tuple[GovernanceFixture, ...] = (
    GovernanceFixture(
        case_id="GV1",
        description="Requisite Holders majority converts the dissenting senior series",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=TABLE,
        exit_valuation=60 * M,
        term=MAJORITY,
        expected_approved=True,
        expected_changes_payout=True,
        expected={"common": 960 / 23 * M, "series_a": 240 / 23 * M, "series_b": 180 / 23 * M},
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 5.4 / 23 * M, "series_b": -27 / 23 * M},
        note="Series A holds 4/7 of the as-converted preferred vote and gains; B loses 27/23 M.",
    ),
    GovernanceFixture(
        case_id="GV2",
        description="the same vote at an 'at least 60%' threshold fails",
        convention=NVCA_REQUISITE_HOLDERS,
        securities=TABLE,
        exit_valuation=60 * M,
        term=AT_LEAST_60,
        expected_approved=False,
        expected_changes_payout=True,
        expected={"common": 40.8 * M, "series_a": 10.2 * M, "series_b": 9 * M},
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 5.4 / 23 * M, "series_b": -27 / 23 * M},
        note="4/7 = 57.1% is below 60%, so the README equilibrium stands.",
    ),
    GovernanceFixture(
        case_id="GV3",
        description="a Series B consent added under NVCA fn 64 blocks the conversion",
        convention=NVCA_SERIES_CONSENT,
        securities=TABLE,
        exit_valuation=60 * M,
        term=MAJORITY_WITH_SERIES_B,
        expected_approved=False,
        expected_changes_payout=True,
        expected={"common": 40.8 * M, "series_a": 10.2 * M, "series_b": 9 * M},
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 5.4 / 23 * M, "series_b": -27 / 23 * M},
        note="The Requisite Holders approve; Series B, voting alone, does not.",
    ),
    GovernanceFixture(
        case_id="GV4",
        description="every position converts anyway, so the vote moves nothing",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=TABLE,
        exit_valuation=100 * M,
        term=MAJORITY,
        expected_approved=False,
        expected_changes_payout=False,
        expected={"common": 1600 / 23 * M, "series_a": 400 / 23 * M, "series_b": 300 / 23 * M},
        expected_decisions={"series_a": "indifferent", "series_b": "indifferent"},
        expected_changes={"series_a": 0.0, "series_b": 0.0},
        note="$100M / 11.5M units = $200/23 a unit on both branches.",
    ),
    GovernanceFixture(
        case_id="GV5",
        description="a conversion no holder wants",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=TABLE,
        exit_valuation=20 * M,
        term=MAJORITY,
        expected_approved=False,
        expected_changes_payout=True,
        expected={"common": 4.8 * M, "series_a": 6.2 * M, "series_b": 9 * M},
        expected_decisions={"series_a": "withholds", "series_b": "withholds"},
        expected_changes={"series_a": -62.6 / 23 * M, "series_b": -147 / 23 * M},
        note="Converted, A would get 80/23 M and B 60/23 M; both prefer their preferences.",
    ),
    GovernanceFixture(
        case_id="GV6a",
        description="just above the knife edge: A gains, B is converted",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=TABLE,
        exit_valuation=57.6 * M,
        term=MAJORITY,
        expected_approved=True,
        expected_changes_payout=True,
        expected={
            "common": 921.6 / 23 * M,
            "series_a": 230.4 / 23 * M,
            "series_b": 172.8 / 23 * M,
        },
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 0.4 / 23 * M, "series_b": (172.8 / 23 - 9) * M},
        note="A's cap of $10M is below 2/11.5 x $57.6M, so A consents.",
    ),
    GovernanceFixture(
        case_id="GV6b",
        description="just below the knife edge: A loses, the vote fails",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=TABLE,
        exit_valuation=57.4 * M,
        term=MAJORITY,
        expected_approved=False,
        expected_changes_payout=True,
        expected={"common": 38.4 * M, "series_a": 10 * M, "series_b": 9 * M},
        expected_decisions={"series_a": "withholds", "series_b": "withholds"},
        expected_changes={"series_a": -0.4 / 23 * M, "series_b": (172.2 / 23 - 9) * M},
        note="2/11.5 x $57.4M = 229.6/23 M is below A's capped $10M.",
    ),
    GovernanceFixture(
        case_id="GV7",
        description="holder-level voting: fund_b votes Series A and Series B together",
        convention=NVCA_REQUISITE_HOLDERS,
        securities=SPLIT_TABLE,
        exit_valuation=60 * M,
        term=mandatory_conversion(converts=SPLIT_IDS),
        expected_approved=False,
        expected_changes_payout=True,
        expected={
            "common": 40.8 * M,
            "series_a1": 7.65 * M,
            "series_a2": 2.55 * M,
            "series_b": 9 * M,
        },
        expected_decisions={"fund_a": "consents", "fund_b": "withholds"},
        expected_changes={"fund_a": 4.05 / 23 * M, "fund_b": -25.65 / 23 * M},
        note=(
            "Counted by holder, 1.5M of 3.5M votes consent (3/7). Counted by position, "
            "series_a2 would consent too and 2.0M of 3.5M (4/7) would pass."
        ),
    ),
    GovernanceFixture(
        case_id="GV8",
        description="GV1 behind a loan: debt is paid first, the vote plays over the rest",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=(LOAN, *TABLE),
        exit_valuation=61.16 * M,
        term=MAJORITY,
        expected_approved=True,
        expected_changes_payout=True,
        expected={
            "loan": 1.16 * M,
            "common": 960 / 23 * M,
            "series_a": 240 / 23 * M,
            "series_b": 180 / 23 * M,
        },
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 5.4 / 23 * M, "series_b": -27 / 23 * M},
        as_of=AS_OF,
        note="$61.16M less the $1.16M loan claim leaves GV1's $60M.",
    ),
    GovernanceFixture(
        case_id="GV9",
        description="the conversion forfeits Series B's accrued dividend as well",
        convention=NVCA_MANDATORY_CONVERSION,
        securities=(founders(), series_a(), series_b(dividend=B_DIVIDEND)),
        exit_valuation=60 * M,
        term=MAJORITY,
        expected_approved=True,
        expected_changes_payout=True,
        expected={"common": 960 / 23 * M, "series_a": 240 / 23 * M, "series_b": 180 / 23 * M},
        expected_decisions={"series_a": "consents", "series_b": "withholds"},
        expected_changes={"series_a": 10 / 23 * M, "series_b": -60.12 / 23 * M},
        as_of=AS_OF,
        note="Without the vote B takes $10.44M and A holds at its $10M cap.",
    ),
)
