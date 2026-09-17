"""Named priced-round fixtures with documented derivations.

Every expected price, share count, capitalization, ownership fraction and payout below is
derived by hand in `docs/rounds.md` and asserted in `tests/test_rounds.py` against
`ovf.rounds.apply_priced_round`. Expected values are written as the exact fractions of those
derivations. Nothing was copied from engine output; each figure was rechecked with exact
rational arithmetic, independently of the engine, before it was written down.

`published` holds figures printed by the source a fixture reproduces (the YC Post-Money Safe
User Guide or Cooley's share-price article). Those sources round prices to four decimals or
to cents, and share counts to whole shares, so they are compared with a relative tolerance
stated per fixture, never used as expected values. `reviewed_by` stays empty until an
external specialist confirms the term shapes and the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ovf
from ovf.contracts.safes import (
    MFNResolution,
    mfn_resolution,
    safe_post_discount,
    safe_post_mfn,
)
from ovf.financing import UNPROTECTED, AntiDilutionProtection
from ovf.rounds import (
    NO_POOL_CHANGE,
    SENIOR_TO_ALL,
    ConversionBasis,
    NewSeries,
    PoolChange,
    PricedRound,
    PricingConvention,
    SafeSeries,
    SeniorityPlacement,
    explicit_seniority,
    pari_passu_with,
    pool_increase,
    pool_target_unallocated,
)

M = 1_000_000

FOUNDERS = ovf.common(8 * M, holder_id="founders", security_id="common")


def series(security_id: str = "series_a", seniority: SeniorityPlacement | None = None) -> NewSeries:
    """A 1x non-participating new-money series, the dominant reported shape."""
    return NewSeries(
        security_id=security_id,
        holder_id=security_id,
        seniority=seniority if seniority is not None else explicit_seniority(1),
        liquidation_multiple=1.0,
        participating=False,
        participation_cap=None,
    )


def terms(
    pre_money: float,
    new_money: float,
    convention: PricingConvention,
    pool: PoolChange,
    *,
    new_series: NewSeries | None = None,
    safe_series: SafeSeries = "safe_preferred",
) -> PricedRound:
    return PricedRound(
        pre_money_valuation=pre_money,
        new_money=new_money,
        convention=convention,
        pool=pool,
        new_series=new_series if new_series is not None else series(),
        safe_series=safe_series,
    )


# --- Sources ------------------------------------------------------------------------

YC_CAP = (
    "YC Postmoney Safe - Valuation Cap Only v1.2, s.1(a) and s.2: converts into the greater "
    "of Purchase Amount / lowest Standard Preferred price and Purchase Amount / Safe Price; "
    "Safe Price = Post-Money Valuation Cap / Company Capitalization, which includes issued "
    "stock, Converting Securities, issued and Promised Options and the Unissued Option Pool, "
    "but not an increase to the pool made in connection with the Equity Financing."
)
YC_GUIDE_EX1 = (
    "YC Post-Money Safe User Guide, Appendix II, Example 1 (post-money safes only): pre-money "
    "includes 'an ungranted and unallocated employee option pool representing 10% of the "
    "fully-diluted post-closing capitalization and ... all shares of Company capital stock "
    "issued in respect of outstanding safes'. The Guide fixes the pool increase in shares."
)
YC_GUIDE_EX2 = (
    "YC Post-Money Safe User Guide, Appendix II, Example 2 (combination of pre-money and "
    "post-money safes): the pre-money Safe Price is the cap over 'Pre-Financing Fully Diluted "
    "Shares + Option Pool Increase'; the post-money Company Capitalization includes the "
    "pre-money safe's conversion shares."
)
YC_DISCOUNT = (
    "YC Postmoney Safe - Discount Only, s.1(a) and s.2: converts into Safe Preferred Stock at "
    "the Discount Price, the lowest Standard Preferred price times the Discount Rate "
    "(100 minus the discount). As an 'other Safe' it is a Converting Security in the capped "
    "form's Company Capitalization."
)
YC_MFN = (
    "YC Postmoney Safe - MFN Only, s.3: on a later Safe with more favorable terms, and on the "
    "Investor's written election, the Safe is amended 'to be identical to the instrument(s) "
    "evidencing the Subsequent Convertible Securities'. Unamended, it converts at the lowest "
    "Standard Preferred price."
)
PRE_MONEY_SAFE = (
    "Pre-money (original) safe capitalization per the YC User Guide's comparison table: "
    "outstanding stock, outstanding and promised options, the unissued pool and the pool "
    "increase included; safes and notes excluded. The original form's own text was not read."
)
COOLEY = (
    "Cooley, 'Calculating Share Price With Outstanding Convertible Notes or Safes' (Derek "
    "Colla, last reviewed 24 January 2022): pre-money, percentage-ownership and "
    "dollars-invested methods. The three are negotiated, not reconciled."
)


# --- Shared tables ------------------------------------------------------------------

YC_FOUNDERS = ovf.common(9_250_000, holder_id="founders", security_id="common")
# 300,000 outstanding options and 350,000 promised options, both inside the reserve.
YC_POOL = ovf.option_pool(750_000, allocated_shares=650_000, holder_id="esop", security_id="pool")
YC_SAFE_A_POST = ovf.safe_post(200_000, 4 * M, holder_id="investor_a", security_id="safe_a")
YC_SAFE_A_PRE = ovf.safe_pre(200_000, 3_800_000, holder_id="investor_a", security_id="safe_a")
YC_SAFE_B = ovf.safe_post(800_000, 8 * M, holder_id="investor_b", security_id="safe_b")

COOLEY_FOUNDERS = ovf.common(M, holder_id="founders", security_id="common")
COOLEY_SAFE = safe_post_discount(M, 0.30, holder_id="safe_holders", security_id="safe")

S1_ANGEL = ovf.safe_post(M, 10 * M, holder_id="angel", security_id="angel")

MFN_SAFE = safe_post_mfn(M / 2, holder_id="mfn_angel", security_id="mfn")
CAP_SAFE = ovf.safe_post(M, 10 * M, holder_id="cap_angel", security_id="cap")
DISCOUNT_SAFE = safe_post_discount(M, 0.20, holder_id="discount_angel", security_id="discount")
MFN_TABLE: tuple[ovf.Security, ...] = (FOUNDERS, MFN_SAFE, CAP_SAFE, DISCOUNT_SAFE)


def mfn_elects(elected: str | None) -> MFNResolution:
    return mfn_resolution(issue_order=("mfn", "cap", "discount"), elections={"mfn": elected})


@dataclass(frozen=True)
class RoundFixture:
    case_id: str
    description: str
    source: str
    table: tuple[ovf.Security, ...]
    terms: PricedRound
    expected_price: float
    expected_total: float
    expected_new_shares: float
    expected_pool_increase: float
    expected_safe_shares: dict[str, float]
    expected_basis: dict[str, ConversionBasis]
    expected_post_capitalization: float | None = None
    expected_pre_capitalization: float | None = None
    expected_ownership: dict[str, float] = field(default_factory=dict)
    protection: dict[str, AntiDilutionProtection] = field(default_factory=dict)
    mfn: MFNResolution | None = None
    published: dict[str, float] = field(default_factory=dict)
    published_rel_tol: float = 0.0
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


ROUND_FIXTURES: tuple[RoundFixture, ...] = (
    # --- Item 1: an existing pool and granted options -------------------------------
    RoundFixture(
        case_id="EP1",
        description="existing pool with grants; target 10% unallocated; one post-money SAFE",
        source=YC_CAP,
        table=(
            FOUNDERS,
            ovf.option_pool(M, allocated_shares=M / 2, holder_id="esop", security_id="pool"),
            S1_ANGEL,
        ),
        terms=terms(
            12 * M,
            3 * M,
            "percentage_ownership_method",
            pool_target_unallocated(0.10, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=21 / 19,
        expected_total=95 * M / 7,
        expected_new_shares=19 * M / 7,
        expected_pool_increase=6 * M / 7,
        expected_safe_shares={"angel": M},
        expected_basis={"angel": "safe_price"},
        expected_post_capitalization=10 * M,
        expected_pre_capitalization=69 * M / 7,
        expected_ownership={
            "founders": 56 / 95,
            "angel": 7 / 95,
            "esop": 13 / 95,
            "series_a": 19 / 95,
        },
        note=(
            "Company Capitalization = 8M common + 0.5M granted + 0.5M unallocated + 1M SAFE "
            "= 10M: the existing pool and grants are in, the 6M/7 increase is out."
        ),
    ),
    RoundFixture(
        case_id="YC1-Q2",
        description="YC Guide Example 1 Q2: two post-money SAFEs, pool increase of 1,695,000",
        source=YC_GUIDE_EX1,
        table=(YC_FOUNDERS, YC_POOL, YC_SAFE_A_POST, YC_SAFE_B),
        terms=terms(
            15 * M,
            5 * M,
            "percentage_ownership_method",
            pool_increase(1_695_000, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=51_000 / 45_763,
        expected_total=915_260_000 / 51,
        expected_new_shares=228_815_000 / 51,
        expected_pool_increase=1_695_000,
        expected_safe_shares={"safe_a": 10 * M / 17, "safe_b": 20 * M / 17},
        expected_basis={"safe_a": "safe_price", "safe_b": "safe_price"},
        expected_post_capitalization=200 * M / 17,
        published={
            "price": 1.1144,
            "total": 17_946_424,
            "new_shares": 4_486_719,
            "safe_a": 588_235,
            "safe_b": 1_176_470,
            "post_capitalization": 11_764_705,
        },
        published_rel_tol=1e-4,
        note="Company Capitalization = 10,000,000 / 0.85; price = $15M / (that + 1,695,000).",
    ),
    RoundFixture(
        case_id="YC1-Q2t",
        description="YC1-Q2 with the Guide's stated 10% available-pool target instead",
        source=YC_GUIDE_EX1,
        table=(YC_FOUNDERS, YC_POOL, YC_SAFE_A_POST, YC_SAFE_B),
        terms=terms(
            15 * M,
            5 * M,
            "percentage_ownership_method",
            pool_target_unallocated(0.10, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=2_210 / 1_983,
        expected_total=3_966_000_000 / 221,
        expected_new_shares=991_500_000 / 221,
        expected_pool_increase=374_500_000 / 221,
        expected_safe_shares={"safe_a": 10 * M / 17, "safe_b": 20 * M / 17},
        expected_basis={"safe_a": "safe_price", "safe_b": "safe_price"},
        expected_post_capitalization=200 * M / 17,
        note=(
            "T = (Company Capitalization - 100,000) / 0.65; increase = 0.1 T - 100,000 = "
            "1,694,570.14, not the Guide's rounded 1,695,000."
        ),
    ),
    RoundFixture(
        case_id="YC1-Q5",
        description="YC Guide Example 1 Q5: safe_b converts at the round price",
        source=YC_GUIDE_EX1,
        table=(YC_FOUNDERS, YC_POOL, YC_SAFE_A_POST, YC_SAFE_B),
        terms=terms(
            8_800_000,
            2_200_000,
            "percentage_ownership_method",
            pool_increase(1_573_000, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=2_400 / 3_649,
        expected_total=50_173_750 / 3,
        expected_new_shares=10_034_750 / 3,
        expected_pool_increase=1_573_000,
        expected_safe_shares={"safe_a": 1_771_000 / 3, "safe_b": 3_649_000 / 3},
        expected_basis={"safe_a": "safe_price", "safe_b": "round_price"},
        expected_post_capitalization=35_420_000 / 3,
        published={
            "price": 0.6577,
            "total": 16_724_684,
            "new_shares": 3_344_990,
            "safe_a": 590_334,
            "safe_b": 1_216_360,
        },
        published_rel_tol=1e-4,
        note=(
            "safe_b's round-price shares enter safe_a's Company Capitalization, and the "
            "price depends on both: the system is simultaneous even with a fixed pool."
        ),
    ),
    # --- Item 5: mixed pre- and post-money SAFEs ------------------------------------
    RoundFixture(
        case_id="YC2-Q2",
        description="YC Guide Example 2 Q2: a pre-money and a post-money SAFE, caps bind",
        source=YC_GUIDE_EX2,
        table=(YC_FOUNDERS, YC_POOL, YC_SAFE_A_PRE, YC_SAFE_B),
        terms=terms(
            15 * M,
            5 * M,
            "percentage_ownership_method",
            pool_increase(1_700_000, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=25_650 / 23_077,
        expected_total=9_230_800_000 / 513,
        expected_new_shares=2_307_700_000 / 513,
        expected_pool_increase=1_700_000,
        expected_safe_shares={"safe_a": 11_700_000 / 19, "safe_b": 201_700_000 / 171},
        expected_basis={"safe_a": "safe_price", "safe_b": "safe_price"},
        expected_post_capitalization=2_017_000_000 / 171,
        expected_pre_capitalization=11_700_000,
        published={
            "price": 1.1115,
            "total": 17_993_718,
            "new_shares": 4_498_426,
            "safe_a": 615_763,
            "safe_b": 1_179_529,
            "post_capitalization": 11_795_292,
        },
        published_rel_tol=1e-4,
        note="safe_a against 11,700,000 (no SAFEs); safe_b against 10,000,000 + safe_a + 10%.",
    ),
    RoundFixture(
        case_id="YC2-Q5",
        description="YC Guide Example 2 Q5: mixed SAFEs, safe_b converts at the round price",
        source=YC_GUIDE_EX2,
        table=(YC_FOUNDERS, YC_POOL, YC_SAFE_A_PRE, YC_SAFE_B),
        terms=terms(
            8_800_000,
            2_200_000,
            "percentage_ownership_method",
            pool_increase(1_575_000, security_id="pool_increase", holder_id="esop"),
        ),
        expected_price=304 / 463,
        expected_total=318_312_500 / 19,
        expected_new_shares=63_662_500 / 19,
        expected_pool_increase=1_575_000,
        expected_safe_shares={"safe_a": 11_575_000 / 19, "safe_b": 23_150_000 / 19},
        expected_basis={"safe_a": "safe_price", "safe_b": "round_price"},
        expected_post_capitalization=224_725_000 / 19,
        expected_pre_capitalization=11_575_000,
        published={
            "price": 0.6566,
            "total": 16_753_189,
            "new_shares": 3_350_594,
            "safe_a": 609_198,
            "safe_b": 1_218_397,
        },
        published_rel_tol=1e-4,
    ),
    RoundFixture(
        case_id="MX1",
        description="mixed: post-money $1M at $10M and pre-money $1M at $8M, no pool",
        source=f"{YC_CAP} {PRE_MONEY_SAFE}",
        table=(
            FOUNDERS,
            ovf.safe_post(M, 10 * M, holder_id="post_angel", security_id="post"),
            ovf.safe_pre(M, 8 * M, holder_id="pre_angel", security_id="pre"),
        ),
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        expected_price=6 / 5,
        expected_total=12.5 * M,
        expected_new_shares=2.5 * M,
        expected_pool_increase=0,
        expected_safe_shares={"post": M, "pre": M},
        expected_basis={"post": "safe_price", "pre": "safe_price"},
        expected_post_capitalization=10 * M,
        expected_pre_capitalization=8 * M,
        expected_ownership={
            "founders": 0.64,
            "post_angel": 0.08,
            "pre_angel": 0.08,
            "series_a": 0.20,
        },
        note="Both denominators at once: 10M counts the pre-money SAFE's 1M; 8M counts neither.",
    ),
    RoundFixture(
        case_id="MX2",
        description="mixed SAFEs with a 10% target pool: both denominators move with T",
        source=f"{YC_CAP} {PRE_MONEY_SAFE}",
        table=(
            FOUNDERS,
            ovf.safe_post(M, 10 * M, holder_id="post_angel", security_id="post"),
            ovf.safe_pre(M / 2, 5 * M, holder_id="pre_angel", security_id="pre"),
        ),
        terms=terms(
            16 * M,
            4 * M,
            "percentage_ownership_method",
            pool_target_unallocated(0.10, security_id="pool", holder_id="esop"),
        ),
        expected_price=31 / 22,
        expected_total=440 * M / 31,
        expected_new_shares=88 * M / 31,
        expected_pool_increase=44 * M / 31,
        expected_safe_shares={"post": 30.8 * M / 31, "pre": 29.2 * M / 31},
        expected_basis={"post": "safe_price", "pre": "safe_price"},
        expected_post_capitalization=308 * M / 31,
        expected_pre_capitalization=292 * M / 31,
        expected_ownership={
            "founders": 31 / 55,
            "post_angel": 7 / 100,
            "pre_angel": 73 / 1100,
            "series_a": 1 / 5,
            "esop": 1 / 10,
        },
    ),
    # --- Item 3: discount-only SAFEs ------------------------------------------------
    RoundFixture(
        case_id="DO1",
        description="one discount-only SAFE, 20% discount, no pool",
        source=YC_DISCOUNT,
        table=(FOUNDERS, safe_post_discount(M, 0.20, holder_id="angel", security_id="angel")),
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        expected_price=43 / 32,
        expected_total=480 * M / 43,
        expected_new_shares=96 * M / 43,
        expected_pool_increase=0,
        expected_safe_shares={"angel": 40 * M / 43},
        expected_basis={"angel": "discount_price"},
        expected_ownership={"founders": 43 / 60, "angel": 1 / 12, "series_a": 1 / 5},
    ),
    RoundFixture(
        case_id="DO2",
        description="a discount-only SAFE beside a capped post-money SAFE",
        source=YC_DISCOUNT,
        table=(FOUNDERS, CAP_SAFE, DISCOUNT_SAFE),
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        expected_price=191 / 160,
        expected_total=2400 * M / 191,
        expected_new_shares=480 * M / 191,
        expected_pool_increase=0,
        expected_safe_shares={"cap": 192 * M / 191, "discount": 200 * M / 191},
        expected_basis={"cap": "safe_price", "discount": "discount_price"},
        expected_post_capitalization=1920 * M / 191,
        expected_ownership={
            "founders": 191 / 300,
            "cap_angel": 2 / 25,
            "discount_angel": 1 / 12,
            "series_a": 1 / 5,
        },
        note=(
            "The discount SAFE's shares are in the capped SAFE's Company Capitalization, so "
            "the capped SAFE still takes exactly 10% of it; founders bear the discount SAFE."
        ),
    ),
    # --- Item 5: Cooley's three conventions on identical inputs ---------------------
    RoundFixture(
        case_id="CM-pre",
        description="Cooley's example, pre-money method",
        source=COOLEY,
        table=(COOLEY_FOUNDERS, COOLEY_SAFE),
        terms=terms(8 * M, 2 * M, "pre_money_method", NO_POOL_CHANGE),
        expected_price=8.0,
        expected_total=10 * M / 7,
        expected_new_shares=250_000,
        expected_pool_increase=0,
        expected_safe_shares={"safe": 1.25 * M / 7},
        expected_basis={"safe": "discount_price"},
        expected_ownership={"founders": 7 / 10, "safe_holders": 1 / 8, "series_a": 7 / 40},
        published={
            "price": 8.00,
            "conversion_price": 5.60,
            "safe": 178_571,
            "new_shares": 250_000,
            "total": 1_428_571,
        },
        published_rel_tol=1e-5,
    ),
    RoundFixture(
        case_id="CM-pct",
        description="Cooley's example, percentage-ownership method",
        source=COOLEY,
        table=(COOLEY_FOUNDERS, COOLEY_SAFE),
        terms=terms(8 * M, 2 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        expected_price=46 / 7,
        expected_total=35 * M / 23,
        expected_new_shares=7 * M / 23,
        expected_pool_increase=0,
        expected_safe_shares={"safe": 5 * M / 23},
        expected_basis={"safe": "discount_price"},
        expected_ownership={"founders": 23 / 35, "safe_holders": 1 / 7, "series_a": 1 / 5},
        published={
            "price": 6.57,
            "conversion_price": 4.60,
            "safe": 217_391,
            "new_shares": 304_348,
            "total": 1_521_739,
        },
        published_rel_tol=1e-3,
    ),
    RoundFixture(
        case_id="CM-dol",
        description="Cooley's example, dollars-invested method",
        source=COOLEY,
        table=(COOLEY_FOUNDERS, COOLEY_SAFE),
        terms=terms(8 * M, 2 * M, "dollars_invested_method", NO_POOL_CHANGE),
        expected_price=53 / 7,
        expected_total=77 * M / 53,
        expected_new_shares=14 * M / 53,
        expected_pool_increase=0,
        expected_safe_shares={"safe": 10 * M / 53},
        expected_basis={"safe": "discount_price"},
        expected_ownership={"founders": 53 / 77, "safe_holders": 10 / 77, "series_a": 2 / 11},
        published={
            "price": 7.57,
            "conversion_price": 5.30,
            "safe": 188_679,
            "new_shares": 264_151,
            "total": 1_452_830,
        },
        published_rel_tol=1e-3,
    ),
    RoundFixture(
        case_id="CS-pre",
        description="S1's inputs (capped post-money SAFE), pre-money method",
        source=COOLEY,
        table=(FOUNDERS, S1_ANGEL),
        terms=terms(12 * M, 3 * M, "pre_money_method", NO_POOL_CHANGE),
        expected_price=3 / 2,
        expected_total=98 * M / 9,
        expected_new_shares=2 * M,
        expected_pool_increase=0,
        expected_safe_shares={"angel": 8 * M / 9},
        expected_basis={"angel": "safe_price"},
        expected_post_capitalization=80 * M / 9,
        expected_ownership={"founders": 36 / 49, "angel": 4 / 49, "series_a": 9 / 49},
    ),
    RoundFixture(
        case_id="CS-pct",
        description="S1's inputs, percentage-ownership method (S1 itself)",
        source=COOLEY,
        table=(FOUNDERS, S1_ANGEL),
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        expected_price=27 / 20,
        expected_total=100 * M / 9,
        expected_new_shares=20 * M / 9,
        expected_pool_increase=0,
        expected_safe_shares={"angel": 8 * M / 9},
        expected_basis={"angel": "safe_price"},
        expected_post_capitalization=80 * M / 9,
        expected_ownership={"founders": 0.72, "angel": 0.08, "series_a": 0.20},
    ),
    RoundFixture(
        case_id="CS-dol",
        description="S1's inputs, dollars-invested method",
        source=COOLEY,
        table=(FOUNDERS, S1_ANGEL),
        terms=terms(12 * M, 3 * M, "dollars_invested_method", NO_POOL_CHANGE),
        expected_price=117 / 80,
        expected_total=1280 * M / 117,
        expected_new_shares=80 * M / 39,
        expected_pool_increase=0,
        expected_safe_shares={"angel": 8 * M / 9},
        expected_basis={"angel": "safe_price"},
        expected_post_capitalization=80 * M / 9,
        expected_ownership={"founders": 117 / 160, "angel": 13 / 160, "series_a": 3 / 16},
    ),
    # --- Item 4: MFN, three instruments in issue order ------------------------------
    RoundFixture(
        case_id="MF-none",
        description="MFN SAFE makes no election and converts at the round price",
        source=YC_MFN,
        table=MFN_TABLE,
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        mfn=mfn_elects(None),
        expected_price=181 / 160,
        expected_total=2400 * M / 181,
        expected_new_shares=480 * M / 181,
        expected_pool_increase=0,
        expected_safe_shares={
            "mfn": 80 * M / 181,
            "cap": 192 * M / 181,
            "discount": 200 * M / 181,
        },
        expected_basis={"mfn": "round_price", "cap": "safe_price", "discount": "discount_price"},
        expected_ownership={
            "founders": 181 / 300,
            "mfn_angel": 1 / 30,
            "cap_angel": 2 / 25,
            "discount_angel": 1 / 12,
            "series_a": 1 / 5,
        },
    ),
    RoundFixture(
        case_id="MF-cap",
        description="MFN SAFE elected the later capped SAFE: $500k at a $10M post-money cap",
        source=YC_MFN,
        table=MFN_TABLE,
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        mfn=mfn_elects("cap"),
        expected_price=179 / 160,
        expected_total=2400 * M / 179,
        expected_new_shares=480 * M / 179,
        expected_pool_increase=0,
        expected_safe_shares={
            "mfn": 96 * M / 179,
            "cap": 192 * M / 179,
            "discount": 200 * M / 179,
        },
        expected_basis={"mfn": "safe_price", "cap": "safe_price", "discount": "discount_price"},
        expected_ownership={
            "founders": 179 / 300,
            "mfn_angel": 1 / 25,
            "cap_angel": 2 / 25,
            "discount_angel": 1 / 12,
            "series_a": 1 / 5,
        },
    ),
    RoundFixture(
        case_id="MF-disc",
        description="MFN SAFE elected the later discount-only SAFE: $500k at a 20% discount",
        source=YC_MFN,
        table=MFN_TABLE,
        terms=terms(12 * M, 3 * M, "percentage_ownership_method", NO_POOL_CHANGE),
        mfn=mfn_elects("discount"),
        expected_price=357 / 320,
        expected_total=1600 * M / 119,
        expected_new_shares=320 * M / 119,
        expected_pool_increase=0,
        expected_safe_shares={
            "mfn": 200 * M / 357,
            "cap": 128 * M / 119,
            "discount": 400 * M / 357,
        },
        expected_basis={
            "mfn": "discount_price",
            "cap": "safe_price",
            "discount": "discount_price",
        },
        expected_ownership={
            "founders": 119 / 200,
            "mfn_angel": 1 / 24,
            "cap_angel": 2 / 25,
            "discount_angel": 1 / 12,
            "series_a": 1 / 5,
        },
    ),
)


def by_id(case_id: str) -> RoundFixture:
    return next(f for f in ROUND_FIXTURES if f.case_id == case_id)


# --- Item 2: SAFE, then a Series A, then a Series B down round ------------------------

MR_POOL = ovf.option_pool(M, holder_id="esop", security_id="pool")
MR_SAFE = ovf.safe_post(M, 10 * M, holder_id="angel", security_id="angel")
# Event 1: the SAFE is issued. The table before the Series A.
MR_TABLE_AFTER_SAFE: tuple[ovf.Security, ...] = (FOUNDERS, MR_POOL, MR_SAFE)


def series_a_terms(safe_series: SafeSeries) -> PricedRound:
    """Event 2: $3M at $12M pre, 10% unallocated pool target, Series A at rank 1."""
    return terms(
        12 * M,
        3 * M,
        "percentage_ownership_method",
        pool_target_unallocated(0.10, security_id="pool_a", holder_id="esop"),
        safe_series=safe_series,
    )


def series_b_terms(seniority: SeniorityPlacement) -> PricedRound:
    """Event 3: a down round, $4M at $6M pre, no pool change."""
    return terms(
        6 * M,
        4 * M,
        "percentage_ownership_method",
        NO_POOL_CHANGE,
        new_series=series("series_b", seniority),
    )


MR_UNPROTECTED: dict[str, AntiDilutionProtection] = {
    "angel": UNPROTECTED,
    "series_a": UNPROTECTED,
}

# After the Series A: price $7/6, T = 90M/7.
MR_A_PRICE = 7 / 6
MR_A_TOTAL = 90 * M / 7
MR_A_SHARES = {
    "common": 8 * M,
    "pool": M,
    "angel": M,
    "series_a": 18 * M / 7,
    "pool_a": 2 * M / 7,
}
MR_A_PREFERENCE_PRICE = {"angel": 1.0, "series_a": 7 / 6}
MR_A_OWNERSHIP = {"founders": 28 / 45, "angel": 7 / 90, "series_a": 1 / 5, "esop": 1 / 10}

# After the Series B: price $7/15, T = 150M/7.
MR_B_PRICE = 7 / 15
MR_B_TOTAL = 150 * M / 7
MR_B_NEW_SHARES = 60 * M / 7
MR_B_OWNERSHIP = {
    "founders": 28 / 75,
    "angel": 7 / 150,
    "series_a": 3 / 25,
    "esop": 3 / 50,
    "series_b": 2 / 5,
}


@dataclass(frozen=True)
class ExitFixture:
    case_id: str
    description: str
    safe_series: SafeSeries
    series_b_seniority: SeniorityPlacement
    exit_valuation: float
    expected: dict[str, float]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


MR_EXITS: tuple[ExitFixture, ...] = (
    ExitFixture(
        case_id="MR-X1",
        description="$6M exit; Series B senior; SAFE holds YC Safe Preferred",
        safe_series="safe_preferred",
        series_b_seniority=SENIOR_TO_ALL,
        exit_valuation=6 * M,
        expected={
            "common": 0,
            "pool": 0,
            "angel": 0.5 * M,
            "series_a": 1.5 * M,
            "pool_a": 0,
            "series_b": 4 * M,
        },
        note="B takes $4M; $2M left against $3M + $1M, pro rata: A $1.5M, SAFE $0.5M.",
    ),
    ExitFixture(
        case_id="MR-X2",
        description="$6M exit; Series B pari passu with Series A",
        safe_series="safe_preferred",
        series_b_seniority=pari_passu_with("series_a"),
        exit_valuation=6 * M,
        expected={
            "common": 0,
            "pool": 0,
            "angel": 0.75 * M,
            "series_a": 2.25 * M,
            "pool_a": 0,
            "series_b": 3 * M,
        },
        note="One tier of $4M + $3M + $1M = $8M claims against $6M: 1/2, 3/8, 1/8.",
    ),
    ExitFixture(
        case_id="MR-X3",
        description="$6M exit; Series B senior; SAFE took Series A shares at the round price",
        safe_series="standard_preferred",
        series_b_seniority=SENIOR_TO_ALL,
        exit_valuation=6 * M,
        expected={
            "common": 0,
            "pool": 0,
            "angel": 0.56 * M,
            "series_a": 1.44 * M,
            "pool_a": 0,
            "series_b": 4 * M,
        },
        note="The SAFE claims 1M x $7/6; $2M split 7:18 gives it $0.56M instead of $0.5M.",
    ),
    ExitFixture(
        case_id="MR-X4",
        description="$141M exit; everyone converts at $7 a share",
        safe_series="safe_preferred",
        series_b_seniority=SENIOR_TO_ALL,
        exit_valuation=141 * M,
        expected={
            "common": 56 * M,
            "pool": 0,
            "angel": 7 * M,
            "series_a": 18 * M,
            "pool_a": 0,
            "series_b": 60 * M,
        },
        note="Issued shares 141M/7, so $7 each; the unallocated pool takes nothing.",
    ),
)
