"""Named breakpoint fixtures BP1-BP7 with documented derivations, and a table generator.

Every expected breakpoint, tranche weight and jump below is derived by hand in
`docs/opm-breakpoints.md` and independently recomputed there with `fractions.Fraction`;
none was copied from engine output. `tests/test_opm_breakpoints.py` asserts them against
`ovf.opm.breakpoints.breakpoint_schedule`, which derives them from the waterfall engine.

The tables reuse the repository's shared cap table (`docs/fixtures.md`): founders 8,000,000
common, Series A 2,000,000 shares at $2.50 ($5,000,000), Series B 1,500,000 shares at $6.00
($9,000,000). BP7 is the README table under the Requisite Holders term of
`tests/governance_fixtures.py`. `reviewed_by` stays empty until an external specialist
confirms the arithmetic.

Amounts are base-currency units. Fractions such as 207/19 are written as they were derived.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

import ovf
from ovf.governance import CollectiveConversion
from tests import governance_fixtures as gv
from tests.test_governance import Pos, to_securities

Q = Fraction
M = 1_000_000
AS_OF = date(2027, 1, 1)  # 730 days after 2025-01-01, as in tests/debt_fixtures.py

TEXTBOOK = (
    "The textbook two-class table: 1x non-participating preferred over common. Cooley's Q2 "
    "2026 venture financing report records a 1x preference in 95.8% and non-participating "
    "terms in 96.4% of reported financings (docs/fixtures.md)."
)
PARTICIPATING = (
    "Participating preferred with a total cap of 2x invested, repository fixtures F5a/F5b; "
    "shape per Kaplan & Stromberg (2003, Review of Economic Studies 70(2))."
)
SENIORITY = (
    "Stacked seniority and pari passu, the two standard conventions for ranking several "
    "preferred series (docs/fixtures.md F6-F8)."
)
DEBT = (
    "A $1,000,000 loan at 8% simple interest, Actual/365 Fixed, issued 2025-01-01 and "
    "measured 2027-01-01, paid ahead of every equity position (tests/governance_fixtures.py "
    "LOAN; docs/debt.md)."
)
POOL = (
    "An unallocated option reserve counts in fully diluted ownership, holds no issued shares "
    "and receives no exit cash (docs/fixtures.md F9, docs/semantics.md)."
)
GOVERNED = (
    "NVCA Model COI (Oct 2025) s.5.1(b) mandatory conversion of all preferred on a Requisite "
    "Holders vote, 'more than 1/2' of the as-converted preferred (tests/governance_fixtures.py "
    "MAJORITY; docs/governance.md GV1-GV6)."
)


def founders() -> ovf.CommonStock:
    return ovf.common(8_000_000, holder_id="founders", security_id="common")


def series_a(
    *,
    seniority: int = 2,
    participating: bool = False,
    participation_cap: float | None = None,
) -> ovf.PreferredStock:
    """2,000,000 shares at $2.50 = $5,000,000 invested, 1x."""
    return ovf.preferred(
        2_000_000,
        2.50,
        seniority=seniority,
        participating=participating,
        participation_cap=participation_cap,
        holder_id="series_a",
        security_id="series_a",
    )


def series_b(*, seniority: int = 1) -> ovf.PreferredStock:
    """1,500,000 shares at $6.00 = $9,000,000 invested, 1x non-participating."""
    return ovf.preferred(
        1_500_000, 6.00, seniority=seniority, holder_id="series_b", security_id="series_b"
    )


@dataclass(frozen=True)
class BreakpointFixture:
    case_id: str
    description: str
    convention: str
    securities: tuple[ovf.Security, ...]
    breakpoints: tuple[tuple[Fraction, str], ...]
    """(exit value, kind) of every breakpoint after the origin, ascending."""
    weights: tuple[dict[str, Fraction], ...]
    """Each tranche's weights, one per tranche; a security absent here has weight zero."""
    jumps: tuple[tuple[Fraction, dict[str, Fraction]], ...] = ()
    """(exit value, right limit minus left limit) at every step."""
    not_breakpoints: tuple[Fraction, ...] = ()
    """Exit values a hand-built table would list that the engine's map shows are not kinks."""
    payouts: tuple[tuple[Fraction, dict[str, Fraction], str], ...] = ()
    """(exit, expected cash, where that number is derived) cross-checks of the replay."""
    monotone: bool = True
    as_of: date | None = None
    term: CollectiveConversion | None = None
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


# Shared quantities, all exact.
U_ALL = Q(23, 2) * M  # 11,500,000 units with every position converted
TOP = {"series_a": Q(4, 23), "series_b": Q(3, 23), "common": Q(16, 23)}
FLIP_LOW = Q(207 * M, 19)  # 10,894,736.84...: series_a's gain from the vote changes sign
FLIP_HIGH = Q(115 * M, 2)  # 57,500,000: GV6

LOAN = gv.LOAN

FIXTURES: tuple[BreakpointFixture, ...] = (
    BreakpointFixture(
        case_id="BP1",
        description="1x non-participating over common: the textbook table",
        convention=TEXTBOOK,
        securities=(founders(), series_a()),
        breakpoints=((Q(5 * M), "preference"), (Q(25 * M), "conversion")),
        weights=(
            {"series_a": Q(1)},
            {"common": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
        ),
        payouts=(
            (Q(35 * M), {"common": Q(28 * M), "series_a": Q(7 * M)}, "F1"),
            (Q(15 * M), {"common": Q(10 * M), "series_a": Q(5 * M)}, "F2"),
            (Q(25 * M), {"common": Q(20 * M), "series_a": Q(5 * M)}, "F3"),
        ),
        note="0.2 X = 5,000,000 at X = 25,000,000.",
    ),
    BreakpointFixture(
        case_id="BP2",
        description="participating with a 2x total cap: the cap bends, then conversion",
        convention=PARTICIPATING,
        securities=(founders(), series_a(participating=True, participation_cap=2.0)),
        breakpoints=(
            (Q(5 * M), "preference"),
            (Q(30 * M), "participation_cap"),
            (Q(50 * M), "conversion"),
        ),
        weights=(
            {"series_a": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
            {"common": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
        ),
        payouts=(
            (Q(40 * M), {"common": Q(30 * M), "series_a": Q(10 * M)}, "F5a"),
            (Q(60 * M), {"common": Q(48 * M), "series_a": Q(12 * M)}, "F5b"),
        ),
        note="5M + 0.2 (X - 5M) = 10M at X = 30M; 0.2 X = 10M at X = 50M.",
    ),
    BreakpointFixture(
        case_id="BP3",
        description="two series, stacked seniority (B senior)",
        convention=SENIORITY,
        securities=(founders(), series_a(seniority=2), series_b(seniority=1)),
        breakpoints=(
            (Q(9 * M), "preference"),
            (Q(14 * M), "preference"),
            (Q(34 * M), "conversion"),
            (Q(69 * M), "conversion"),
        ),
        weights=(
            {"series_b": Q(1)},
            {"series_a": Q(1)},
            {"common": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
            TOP,
        ),
        not_breakpoints=(Q(62 * M),),
        payouts=(
            (Q(10 * M), {"common": Q(0), "series_a": Q(1 * M), "series_b": Q(9 * M)}, "F6"),
            (Q(14 * M), {"common": Q(0), "series_a": Q(5 * M), "series_b": Q(9 * M)}, "F8a"),
            (Q(20 * M), {"common": Q(6 * M), "series_a": Q(5 * M), "series_b": Q(9 * M)}, "F8b"),
        ),
        note=(
            "62M is where B would convert if A still held; A has converted at 34M, so the "
            "candidate is not a kink of the equilibrium map."
        ),
    ),
    BreakpointFixture(
        case_id="BP4",
        description="two series, pari passu",
        convention=SENIORITY,
        securities=(founders(), series_a(seniority=2), series_b(seniority=2)),
        breakpoints=(
            (Q(14 * M), "preference"),
            (Q(34 * M), "conversion"),
            (Q(69 * M), "conversion"),
        ),
        weights=(
            {"series_a": Q(5, 14), "series_b": Q(9, 14)},
            {"common": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
            TOP,
        ),
        not_breakpoints=(Q(5 * M), Q(9 * M)),
        payouts=(
            (
                Q(10 * M),
                {"common": Q(0), "series_a": Q(50 * M, 14), "series_b": Q(90 * M, 14)},
                "F7",
            ),
        ),
        note=(
            "5M and 9M are the one-series preference levels of the profiles in which the "
            "other series has converted; neither is played below 14M."
        ),
    ),
    BreakpointFixture(
        case_id="BP5",
        description="debt at seniority 0: the first breakpoint is repayment",
        convention=DEBT,
        securities=(LOAN, founders(), series_a()),
        breakpoints=(
            (Q(1_160_000), "debt_repaid"),
            (Q(6_160_000), "preference"),
            (Q(26_160_000), "conversion"),
        ),
        weights=(
            {"loan": Q(1)},
            {"series_a": Q(1)},
            {"common": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
        ),
        payouts=(
            (
                Q(36_160_000),
                {"loan": Q(1_160_000), "common": Q(28 * M), "series_a": Q(7 * M)},
                "F1 behind the loan",
            ),
        ),
        as_of=AS_OF,
        note="1,000,000 x (1 + 0.08 x 730/365) = 1,160,000; BP1 shifted right by it.",
    ),
    BreakpointFixture(
        case_id="BP6",
        description="an unallocated pool dilutes ownership and takes no cash",
        convention=POOL,
        securities=(
            founders(),
            series_a(),
            ovf.option_pool(1_000_000, holder_id="esop", security_id="pool"),
        ),
        breakpoints=((Q(5 * M), "preference"), (Q(25 * M), "conversion")),
        weights=(
            {"series_a": Q(1), "pool": Q(0)},
            {"common": Q(1), "pool": Q(0)},
            {"series_a": Q(1, 5), "common": Q(4, 5), "pool": Q(0)},
        ),
        not_breakpoints=(Q(55 * M, 2),),
        payouts=((Q(35 * M), {"common": Q(28 * M), "series_a": Q(7 * M), "pool": Q(0)}, "F9"),),
        note=(
            "Series A holds 2/11 of fully diluted equity but takes 2/10 of each dollar above "
            "25M. A table built on fully diluted shares would put the conversion at 27.5M."
        ),
    ),
    BreakpointFixture(
        case_id="BP7",
        description="the README table under a majority Requisite Holders conversion",
        convention=GOVERNED,
        securities=gv.TABLE,
        breakpoints=(
            (FLIP_LOW, "forced_conversion"),
            (Q(14 * M), "preference"),
            (Q(39 * M), "participation_cap"),
            (FLIP_HIGH, "forced_conversion"),
        ),
        weights=(
            TOP,
            {"series_a": Q(1)},
            {"series_a": Q(1, 5), "common": Q(4, 5)},
            {"common": Q(1)},
            TOP,
        ),
        jumps=(
            (FLIP_LOW, {"common": -Q(144 * M, 19), "series_a": Q(0), "series_b": Q(144 * M, 19)}),
            (FLIP_HIGH, {"common": Q(3 * M, 2), "series_a": Q(0), "series_b": -Q(3 * M, 2)}),
        ),
        not_breakpoints=(Q(9 * M), Q(59 * M), Q(69 * M)),
        payouts=(
            (
                Q(60 * M),
                {"common": Q(960 * M, 23), "series_a": Q(240 * M, 23), "series_b": Q(180 * M, 23)},
                "GV1",
            ),
            (
                Q(100 * M),
                {"common": Q(1600 * M, 23), "series_a": Q(400 * M, 23), "series_b": Q(300 * M, 23)},
                "GV4",
            ),
            (
                Q(20 * M),
                {"common": Q(48 * M, 10), "series_a": Q(62 * M, 10), "series_b": Q(9 * M)},
                "GV5",
            ),
            (
                Q(576 * M, 10),
                {
                    "common": Q(9216 * M, 230),
                    "series_a": Q(2304 * M, 230),
                    "series_b": Q(1728 * M, 230),
                },
                "GV6a",
            ),
            (
                Q(574 * M, 10),
                {"common": Q(384 * M, 10), "series_a": Q(10 * M), "series_b": Q(9 * M)},
                "GV6b",
            ),
            (
                Q(10 * M),
                {"common": Q(160 * M, 23), "series_a": Q(40 * M, 23), "series_b": Q(30 * M, 23)},
                "BP7",
            ),
            (Q(12 * M), {"common": Q(0), "series_a": Q(3 * M), "series_b": Q(9 * M)}, "BP7"),
        ),
        monotone=False,
        term=gv.MAJORITY,
        note=(
            "Two steps. At 207/19 M the vote stops carrying: common falls by 144/19 M = "
            "7,578,947.37 and series_b rises by the same. At 57.5M (GV6) it starts carrying "
            "again: series_b falls by 1,500,000 and common rises by the same."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Generated tables
# ---------------------------------------------------------------------------

MULTIPLES = (Q(1), Q(1), Q(3, 2), Q(2))
RATIOS = (Q(1), Q(1), Q(1), Q(3, 2), Q(2), Q(1, 2))


@dataclass(frozen=True)
class GeneratedTable:
    """A random table as exact positions (for the oracle) and as securities (for ovf)."""

    seed: int
    positions: tuple[Pos, ...]
    debt: Fraction
    pool: bool
    securities: tuple[ovf.Security, ...]
    as_of: date | None


def generated_table(seed: int) -> GeneratedTable:
    """1-3 preferred positions with adversarial terms, common from none to 2,000 shares,
    sometimes a loan at seniority 0 (claim equal to principal: zero rate, measured on its
    issue date) and sometimes an unallocated pool. Every input is exact in binary floating
    point, so the oracle and the engine read the same numbers."""
    rng = random.Random(seed)
    n = rng.randint(1, 3)
    prefs: list[Pos] = []
    for i in range(n):
        multiple = rng.choice(MULTIPLES)
        participating = rng.random() < 0.5
        cap = None
        if participating and rng.random() < 0.6:
            cap = multiple + rng.choice((Q(0), Q(1, 2), Q(1), Q(2)))
        prefs.append(
            Pos(
                holder=f"h{i}",
                shares=Q(rng.randint(1, 10) * 100),
                price=Q(rng.randint(1, 6)),
                seniority=rng.randint(1, 3),
                multiple=multiple,
                participating=participating,
                cap=cap,
                ratio=rng.choice(RATIOS),
            )
        )
    common = rng.choice((0, 1, 2, 5, 8, 10, 20)) * 100
    positions = tuple(([Pos("founders", Q(common), common=True)] if common else []) + prefs)
    securities: list[ovf.Security] = to_securities(positions)
    debt = Q(0)
    as_of = None
    if rng.random() < 0.25:
        debt = Q(rng.randint(1, 20) * 100)
        issued = date(2026, 1, 1)
        securities.insert(
            0,
            ovf.debt(
                float(debt),
                0.0,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=issued,
                seniority=0,
                holder_id="lender",
                security_id="loan",
            ),
        )
        as_of = issued
    pool = rng.random() < 0.25
    if pool:
        securities.append(ovf.option_pool(rng.randint(1, 10) * 100, security_id="pool"))
    return GeneratedTable(seed, positions, debt, pool, tuple(securities), as_of)
