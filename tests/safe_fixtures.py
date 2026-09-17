"""Named SAFE financing fixtures with documented derivations.

Every expected number is derived by hand in `docs/fixtures.md` from the equations
in `docs/semantics.md`, then asserted here against the solver. Ownership is a
post-round fully diluted fraction. `reviewed_by` stays empty until an external
specialist confirms the convention and the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import ovf


@dataclass(frozen=True)
class SafeFixture:
    case_id: str
    description: str
    prior_common_shares: float
    new_money: float
    pre_money_valuation: float
    target_pool_pct: float
    safes: tuple[ovf.PostMoneySAFE | ovf.PreMoneySAFE, ...]
    method: Literal["post_money_yc", "pre_money"]
    expected_share_price: float
    expected_total_shares: float
    expected_ownership: dict[str, float]
    expected_safe_shares: dict[str, float]
    expected_conversion_prices: dict[str, float]
    note: str = ""
    reviewed_by: tuple[str, ...] = field(default=())


YC_CAP_ONLY = (
    "Y Combinator Postmoney Safe with Valuation Cap v1.2. The holder receives the "
    "greater of Purchase Amount / lowest Standard Preferred price and Purchase "
    "Amount / Safe Price, where Safe Price = Post-Money Valuation Cap / Company "
    "Capitalization. Company Capitalization excludes the pool increase made in "
    "connection with the financing. Source: https://www.ycombinator.com/documents/"
)
PRE_MONEY_FORM = (
    "Pre-money SAFE capitalization. The cap denominator includes the new option "
    "pool and excludes other converting SAFEs, which is the definitional difference "
    "from the post-money form."
)


SAFE_FIXTURES: tuple[SafeFixture, ...] = (
    SafeFixture(
        case_id="S1",
        description="cap binds, no option pool",
        prior_common_shares=8_000_000,
        new_money=3_000_000,
        pre_money_valuation=12_000_000,
        target_pool_pct=0.0,
        safes=(ovf.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel"),),
        method="post_money_yc",
        expected_share_price=1.35,
        expected_total_shares=11_111_111.111111112,
        expected_ownership={
            "founders": 0.72,
            "angel": 0.08,
            "new_preferred": 0.20,
            "option_pool": 0.0,
        },
        expected_safe_shares={"safe_post_angel": 888_888.8888888889},
        expected_conversion_prices={"safe_post_angel": 1.125},
        note=(
            "The $10M cap is below the $12M implied value of prior capitalization, so "
            "the cap sets the conversion price at $1.125 against a $1.35 round price."
        ),
    ),
    SafeFixture(
        case_id="S2",
        description="down round; the round price beats the cap",
        prior_common_shares=8_000_000,
        new_money=1_000_000,
        pre_money_valuation=4_000_000,
        target_pool_pct=0.0,
        safes=(ovf.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel"),),
        method="post_money_yc",
        expected_share_price=0.375,
        expected_total_shares=13_333_333.333333334,
        expected_ownership={
            "founders": 0.60,
            "angel": 0.20,
            "new_preferred": 0.20,
            "option_pool": 0.0,
        },
        expected_safe_shares={"safe_post_angel": 2_666_666.6666666665},
        expected_conversion_prices={"safe_post_angel": 0.375},
        note=(
            "The cap never binds below it. The holder converts at the $0.375 round "
            "price and takes 20% rather than the 8% the cap would have implied, which "
            "is the 'greater of' rule working in the holder's favour."
        ),
    ),
    SafeFixture(
        case_id="S3",
        description="S1 plus a 10% new option pool",
        prior_common_shares=8_000_000,
        new_money=3_000_000,
        pre_money_valuation=12_000_000,
        target_pool_pct=0.10,
        safes=(ovf.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel"),),
        method="post_money_yc",
        expected_share_price=1.18125,
        expected_total_shares=12_698_412.698412698,
        expected_ownership={
            "founders": 0.63,
            "angel": 0.07,
            "new_preferred": 0.20,
            "option_pool": 0.10,
        },
        expected_safe_shares={"safe_post_angel": 888_888.8888888889},
        expected_conversion_prices={"safe_post_angel": 1.125},
        note=(
            "Against S1 the new investor still holds exactly 20%. The pool's 10% comes "
            "out of founders (72% to 63%) and the SAFE (8% to 7%). This is the option "
            "pool shuffle: a pool placed inside the pre-money is paid for by everyone "
            "except the incoming round."
        ),
    ),
    SafeFixture(
        case_id="S4",
        description="two capped SAFEs with a 10% pool",
        prior_common_shares=8_000_000,
        new_money=4_000_000,
        pre_money_valuation=16_000_000,
        target_pool_pct=0.10,
        safes=(
            ovf.safe_post(amount=1_000_000, cap=10_000_000, holder_id="a1"),
            ovf.safe_post(amount=500_000, cap=10_000_000, holder_id="a2"),
        ),
        method="post_money_yc",
        expected_share_price=1.4875,
        expected_total_shares=13_445_378.151260504,
        expected_ownership={
            "founders": 0.595,
            "a1": 0.07,
            "a2": 0.035,
            "new_preferred": 0.20,
            "option_pool": 0.10,
        },
        expected_safe_shares={
            "safe_post_a1": 941_176.4705882353,
            "safe_post_a2": 470_588.2352941176,
        },
        expected_conversion_prices={
            "safe_post_a1": 1.0625,
            "safe_post_a2": 1.0625,
        },
        note=(
            "Post-money SAFEs do not dilute one another: the two caps fix 10% and 5% of "
            "pre-round capitalization, which become 7% and 3.5% after the 20% round and "
            "the 10% pool."
        ),
    ),
    SafeFixture(
        case_id="S5",
        description="pre-money SAFE on the same cash and cap as S1",
        prior_common_shares=8_000_000,
        new_money=3_000_000,
        pre_money_valuation=12_000_000,
        target_pool_pct=0.0,
        safes=(ovf.safe_pre(amount=1_000_000, cap=10_000_000, holder_id="angel"),),
        method="pre_money",
        expected_share_price=1.3636363636363635,
        expected_total_shares=11_000_000.0,
        expected_ownership={
            "founders": 0.7272727272727273,
            "angel": 0.07272727272727272,
            "new_preferred": 0.20,
            "option_pool": 0.0,
        },
        expected_safe_shares={"safe_pre_angel": 800_000.0},
        expected_conversion_prices={"safe_pre_angel": 1.25},
        note=(
            "Identical cash and identical cap, different capitalization definition: "
            "the holder receives 7.27% instead of the 8% of S1. The pre- and post-money "
            "difference is definitional, not a difference in negotiated price."
        ),
    ),
)


def solve(fixture: SafeFixture) -> ovf.SafeConversionResult:
    return ovf.solve_priced_round_with_safes(
        prior_common_shares=fixture.prior_common_shares,
        new_money=fixture.new_money,
        pre_money_valuation=fixture.pre_money_valuation,
        target_pool_pct=fixture.target_pool_pct,
        safes=list(fixture.safes),
        method=fixture.method,
    )
