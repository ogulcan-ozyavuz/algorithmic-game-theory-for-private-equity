"""
Unit tests for SAFE conversion and priced round solver.
"""

import pytest

from ovf.contracts.safes import solve_priced_round_with_safes
from ovf.contracts.securities import safe_post, safe_pre


def test_post_money_yc_priced_round_dilution():
    """
    Test standard YC post-money SAFE conversion with pool expansion.
    Founders: 8,000,000 shares
    SAFE 1: $1M on $10M cap (10%)
    SAFE 2: $500k on $10M cap (5%)
    Series A: $3M new money at $12M pre-money ($15M post-money) -> 20%
    Target Option Pool: 10%
    New money and pool dilute the pre-pool SAFE base to 70% of post shares.
    SAFE holdings are 7% and 3.5%; founders retain 85% * 70% = 59.5%.
    These are hand-derived expectations under the documented pricing convention.
    """
    s1 = safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel_1")
    s2 = safe_post(amount=500_000, cap=10_000_000, holder_id="angel_2")

    res = solve_priced_round_with_safes(
        prior_common_shares=8_000_000,
        new_money=3_000_000,
        pre_money_valuation=12_000_000,
        target_pool_pct=0.10,
        safes=[s1, s2],
        method="post_money_yc",
    )

    assert abs(res.ownership_breakdown["founders"] - 0.595) < 1e-5
    assert abs(res.ownership_breakdown["angel_1"] - 0.07) < 1e-5
    assert abs(res.ownership_breakdown["angel_2"] - 0.035) < 1e-5
    assert abs(res.ownership_breakdown["new_preferred"] - 0.20) < 1e-5
    assert abs(res.ownership_breakdown["option_pool"] - 0.10) < 1e-5

    # Total post money check
    assert res.post_money_valuation == 15_000_000.0
    assert abs(res.total_post_shares * res.share_price - 15_000_000.0) < 1e-2


def test_excessive_dilution_raises_error():
    """Reject a cap-implied SAFE base that leaves no founder ownership."""
    # Four SAFEs each implying 30% of the pre-new-money/pool base.
    safes = [safe_post(amount=3_000_000, cap=10_000_000, holder_id=f"safe_{i}") for i in range(4)]
    # Cap ownership alone already exceeds the available pre-financing base.
    with pytest.raises(ValueError, match="Dilution exceeds"):
        solve_priced_round_with_safes(
            prior_common_shares=10_000_000,
            new_money=2_000_000,
            pre_money_valuation=8_000_000,  # 2M / 10M = 20%
            target_pool_pct=0.10,
            safes=safes,
            method="post_money_yc",
        )


def test_pre_money_safe_conversion():
    """Verify pre-money SAFE conversion converges properly."""
    s1 = safe_pre(amount=1_000_000, cap=8_000_000, holder_id="pre_angel")

    res = solve_priced_round_with_safes(
        prior_common_shares=10_000_000,
        new_money=2_000_000,
        pre_money_valuation=10_000_000,
        target_pool_pct=0.10,
        safes=[s1],
        method="pre_money",
    )

    assert res.share_price > 0
    assert res.total_post_shares > 10_000_000
    assert sum(res.ownership_breakdown.values()) == pytest.approx(1.0, abs=1e-4)
