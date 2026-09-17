"""
Unit and integration tests for CapTable and Waterfall equilibrium solver.
"""

from ovf.contracts.captable import CapTable
from ovf.contracts.securities import common, preferred


def test_conservation_of_value():
    """Verify sum of all payouts exactly equals exit valuation for any exit value."""
    ct = CapTable()
    ct.add(common(shares=8_000_000, holder_id="founders"))
    ct.add(
        preferred(
            shares=2_000_000,
            price=2.50,
            seniority=1,
            liquidation_multiple=1.0,
            holder_id="series_a",
        )
    )

    for exit_val in [0.0, 1_000_000, 5_000_000, 7_500_000, 25_000_000, 100_000_000]:
        payouts = ct.waterfall(exit_valuation=exit_val)
        total_payout = sum(p.amount for p in payouts)
        assert abs(total_payout - exit_val) < 1e-5


def test_non_participating_conversion_indifference():
    """
    Test non-participating preferred conversion threshold.
    Founders: 8M shares common (80%).
    Series A: 2M shares preferred (20%), $5M invested ($2.50/sh), 1x non-participating.
    Threshold for Series A to convert:
    Series A preference = $5M.
    As common, Series A gets 20% of exit.
    Indifference point: 0.20 * X = $5M => X = $25M.
    If X < $25M => Takes $5M preference (or all if X < $5M).
    If X > $25M => Converts to common and gets 20% of X.
    """
    ct = CapTable()
    ct.add(common(shares=8_000_000, holder_id="founders"))
    ct.add(
        preferred(
            shares=2_000_000,
            price=2.50,
            seniority=1,
            liquidation_multiple=1.0,
            participating=False,
            holder_id="series_a",
        )
    )

    # Case 1: Low exit ($3M) - Preference takes all $3M, founders get $0
    p1 = ct.waterfall(exit_valuation=3_000_000)
    p_pref1 = next(p for p in p1 if p.holder_id == "series_a")
    p_fnd1 = next(p for p in p1 if p.holder_id == "founders")
    assert p_pref1.amount == 3_000_000.0
    assert p_pref1.converted is False
    assert p_fnd1.amount == 0.0

    # Case 2: Mid exit ($10M) - Preference takes $5M, founders get remaining $5M
    p2 = ct.waterfall(exit_valuation=10_000_000)
    p_pref2 = next(p for p in p2 if p.holder_id == "series_a")
    p_fnd2 = next(p for p in p2 if p.holder_id == "founders")
    assert p_pref2.amount == 5_000_000.0
    assert p_pref2.converted is False
    assert p_fnd2.amount == 5_000_000.0

    # Case 3: Exactly at indifference ($25M) - Payout is $5M either way, founders get $20M
    p3 = ct.waterfall(exit_valuation=25_000_000)
    p_pref3 = next(p for p in p3 if p.holder_id == "series_a")
    p_fnd3 = next(p for p in p3 if p.holder_id == "founders")
    assert abs(p_pref3.amount - 5_000_000.0) < 1e-4
    assert abs(p_fnd3.amount - 20_000_000.0) < 1e-4

    # Case 4: High exit ($50M) - Series A converts to common and receives 20% = $10M!
    p4 = ct.waterfall(exit_valuation=50_000_000)
    p_pref4 = next(p for p in p4 if p.holder_id == "series_a")
    p_fnd4 = next(p for p in p4 if p.holder_id == "founders")
    assert p_pref4.converted is True
    assert abs(p_pref4.amount - 10_000_000.0) < 1e-4
    assert abs(p_fnd4.amount - 40_000_000.0) < 1e-4


def test_participating_preferred_double_dip():
    """
    Participating preferred takes preference first, then shares remaining residual with common.
    Founders: 8M shares (80%)
    Series A: 2M shares (20%), $5M invested, 1x participating (no cap)
    Exit: $15M
    Series A takes $5M preference first. Remaining = $10M.
    Series A gets 20% of $10M = $2M. Total Series A = $5M + $2M = $7M.
    Founders get 80% of $10M = $8M. Total = $15M.
    """
    ct = CapTable()
    ct.add(common(shares=8_000_000, holder_id="founders"))
    ct.add(
        preferred(
            shares=2_000_000,
            price=2.50,
            seniority=1,
            liquidation_multiple=1.0,
            participating=True,
            holder_id="series_a",
        )
    )

    payouts = ct.waterfall(exit_valuation=15_000_000)
    p_pref = next(p for p in payouts if p.holder_id == "series_a")
    p_fnd = next(p for p in payouts if p.holder_id == "founders")

    assert abs(p_pref.amount - 7_000_000.0) < 1e-4
    assert p_pref.preference_payout == 5_000_000.0
    assert abs(p_pref.participation_payout - 2_000_000.0) < 1e-4
    assert abs(p_fnd.amount - 8_000_000.0) < 1e-4


def test_participating_preferred_with_cap():
    """
    Participating preferred with 2.0x cap on $5M investment = $10M max payout.
    Exit: $40M
    Preference = $5M. Residual before cap = $35M.
    20% of $35M = $7M. Preference + participation would be $5M + $7M = $12M > $10M cap.
    Therefore, cap binds at $10M total payout.
    Remaining $30M goes to founders.
    Wait: If exit is $60M, 20% as common is $12M > $10M cap, so it converts to common!
    """
    ct = CapTable()
    ct.add(common(shares=8_000_000, holder_id="founders"))
    ct.add(
        preferred(
            shares=2_000_000,
            price=2.50,
            seniority=1,
            liquidation_multiple=1.0,
            participating=True,
            participation_cap=2.0,  # 2x cap = $10M max
            holder_id="series_a",
        )
    )

    # At $40M exit: Cap binds at $10M, converted common is 20% of $40M = $8M (which is less than $10M cap)
    payouts_40m = ct.waterfall(exit_valuation=40_000_000)
    p_pref_40 = next(p for p in payouts_40m if p.holder_id == "series_a")
    p_fnd_40 = next(p for p in payouts_40m if p.holder_id == "founders")

    assert abs(p_pref_40.amount - 10_000_000.0) < 1e-4
    assert abs(p_fnd_40.amount - 30_000_000.0) < 1e-4
    assert p_pref_40.converted is False

    # At $60M exit: 20% as common is $12M > $10M cap! Preferred flips to converted common!
    payouts_60m = ct.waterfall(exit_valuation=60_000_000)
    p_pref_60 = next(p for p in payouts_60m if p.holder_id == "series_a")
    p_fnd_60 = next(p for p in payouts_60m if p.holder_id == "founders")

    assert p_pref_60.converted is True
    assert abs(p_pref_60.amount - 12_000_000.0) < 1e-4
    assert abs(p_fnd_60.amount - 48_000_000.0) < 1e-4


def test_multi_tier_seniority():
    """
    Series B (Seniority 1): $5M preference
    Series A (Seniority 2): $5M preference
    Common (Subordinated): 0 preference
    Exit: $7M
    Series B gets full $5M.
    Series A gets remaining $2M (out of its $5M).
    Common gets $0.
    """
    ct = CapTable()
    ct.add(common(shares=10_000_000, holder_id="founders"))
    ct.add(
        preferred(
            shares=2_000_000,
            price=2.50,
            seniority=2,
            liquidation_multiple=1.0,
            holder_id="series_a",
        )
    )
    ct.add(
        preferred(
            shares=1_000_000,
            price=5.00,
            seniority=1,
            liquidation_multiple=1.0,
            holder_id="series_b",
        )
    )

    payouts = ct.waterfall(exit_valuation=7_000_000)
    p_b = next(p for p in payouts if p.holder_id == "series_b")
    p_a = next(p for p in payouts if p.holder_id == "series_a")
    p_c = next(p for p in payouts if p.holder_id == "founders")

    assert p_b.amount == 5_000_000.0
    assert p_a.amount == 2_000_000.0
    assert p_c.amount == 0.0
