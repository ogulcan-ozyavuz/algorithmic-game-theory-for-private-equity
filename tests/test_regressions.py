"""Regression scenarios from the financial review; expected values derived independently."""

import math

import pytest
from pydantic import ValidationError

import ovf


def test_yc_new_money_dilutes_safe_and_round_reaches_exit():
    s = ovf.safe_post(1_000_000, 10_000_000, holder_id="angel")
    result = ovf.solve_priced_round_with_safes(8_000_000, 3_000_000, 12_000_000, 0, [s])
    assert result.ownership_breakdown == pytest.approx(
        {"founders": 0.72, "angel": 0.08, "new_preferred": 0.20, "option_pool": 0}
    )
    table = result.to_cap_table()
    assert table.ownership_breakdown() == pytest.approx(
        {"founders": 0.72, "angel": 0.08, "new_preferred": 0.20}
    )
    payouts = {p.holder_id: p for p in table.waterfall(100_000_000)}
    assert payouts["angel"].amount == pytest.approx(8_000_000)
    assert payouts["angel"].invested_capital == pytest.approx(1_000_000)
    assert sum(p.amount for p in payouts.values()) == pytest.approx(100_000_000)


def test_post_safe_chooses_round_price_below_cap():
    result = ovf.solve_priced_round_with_safes(
        1_000_000, 1_000_000, 4_000_000, 0, [ovf.safe_post(1_000_000, 10_000_000)]
    )
    assert result.share_price == pytest.approx(3)
    assert result.ownership_breakdown["safe_investor"] == pytest.approx(0.2)
    assert result.safe_conversion_prices["safe_post_safe_investor"] == pytest.approx(3)


def test_custom_post_cap_plus_discount():
    result = ovf.solve_priced_round_with_safes(
        1_000_000,
        1_000_000,
        4_000_000,
        0,
        [ovf.safe_post(1_000_000, 10_000_000, discount_rate=0.2)],
    )
    assert result.share_price == pytest.approx(2.75)
    assert result.safe_conversion_prices["safe_post_safe_investor"] == pytest.approx(2.2)
    assert result.ownership_breakdown["safe_investor"] == pytest.approx(0.25)


def test_pre_money_pool_in_cap_denominator():
    # C=10M, pre=10M, new=2M, pool=10%, I=1M, cap=8M.
    # Cap binds: 10 = 10P + 1.2 + (10P+1.2)/8 => P=173/225.
    result = ovf.solve_priced_round_with_safes(
        10_000_000, 2_000_000, 10_000_000, 0.1, [ovf.safe_pre(1_000_000, 8_000_000)], "pre_money"
    )
    assert result.share_price == pytest.approx(173 / 225, rel=1e-11)
    cap_price = 8_000_000 / (10_000_000 + result.new_option_pool_shares)
    assert result.safe_conversion_prices["safe_pre_safe_investor"] == pytest.approx(cap_price)
    assert sum(result.ownership_breakdown.values()) == pytest.approx(1)


def test_same_safe_holder_is_aggregated():
    safes = [
        ovf.safe_post(500_000, 10_000_000, holder_id="angel", security_id=f"s{i}") for i in range(2)
    ]
    result = ovf.solve_priced_round_with_safes(8_000_000, 3_000_000, 12_000_000, 0, safes)
    assert result.ownership_breakdown["angel"] == pytest.approx(0.08)
    assert sum(result.ownership_breakdown.values()) == pytest.approx(1)


def test_ids_rejected_at_all_entry_points():
    security = ovf.common(100)
    with pytest.raises(ValueError, match="Duplicate"):
        ovf.CapTable(securities=[security, security])
    table = ovf.CapTable().add(security)
    with pytest.raises(ValueError, match="Duplicate"):
        table.add(ovf.common(100))
    table.securities.append(security)  # Direct list mutation must not bypass calculation checks.
    with pytest.raises(ValueError, match="Duplicate"):
        table.waterfall(100)
    with pytest.raises(ValueError, match="Duplicate"):
        table.ownership_breakdown()
    safe = ovf.safe_post(100, 1000)
    with pytest.raises(ValueError, match="Duplicate"):
        ovf.solve_priced_round_with_safes(100, 100, 1000, 0, [safe, safe])


def test_pool_has_no_payment_entitlement():
    table = ovf.CapTable().add(ovf.common(8_000_000)).add(ovf.option_pool(2_000_000))
    assert table.ownership_breakdown()["esop"] == 0.2
    payouts = table.waterfall(10_000_000)
    assert [p.amount for p in payouts] == [10_000_000, 0]
    assert payouts[0].payout_pct == 1
    assert payouts[0].ownership_pct == payouts[0].payout_pct  # Deprecated compatibility alias.
    assert payouts[1].effective_multiple is None


@pytest.mark.parametrize("exit_value", [0, 35_000_000])
def test_unconverted_safe_is_never_silently_ignored(exit_value):
    table = ovf.CapTable().add(ovf.common(8_000_000)).add(ovf.safe_post(1_000_000, 10_000_000))
    with pytest.raises(ValueError, match="Unsupported exit instrument"):
        table.waterfall(exit_value)
    with pytest.raises(ValueError, match="Resolve SAFEs"):
        table.ownership_breakdown()


def test_granted_options_need_explicit_settlement():
    table = ovf.CapTable().add(ovf.common(100)).add(ovf.option_pool(100, allocated_shares=50))
    with pytest.raises(ValueError, match="settlement"):
        table.waterfall(100)
    with pytest.raises(ValidationError):
        ovf.option_pool(100, allocated_shares=101)


@pytest.mark.parametrize("bad", [-1, math.nan, math.inf, -math.inf])
def test_invalid_financial_inputs(bad):
    with pytest.raises(ValidationError):
        ovf.safe_post(100, bad)
    with pytest.raises(ValidationError):
        ovf.common(bad)
    with pytest.raises(ValueError):
        ovf.CapTable().add(ovf.common(100)).waterfall(100, transaction_costs=bad)
    with pytest.raises(ValueError):
        ovf.solve_priced_round_with_safes(100, bad, 1000)


def test_zero_cap_full_discount_and_mixed_types_are_rejected():
    with pytest.raises(ValidationError):
        ovf.safe_post(100, 0)
    with pytest.raises(ValidationError):
        ovf.safe_pre(100, 1000, discount_rate=1)
    with pytest.raises(ValueError, match="Mixed"):
        ovf.solve_priced_round_with_safes(100, 100, 1000, safes=[ovf.safe_pre(100, 1000)])
    with pytest.raises(ValueError):
        ovf.solve_priced_round_with_safes(0, 100, 1000)
    with pytest.raises(ValueError):
        ovf.solve_priced_round_with_safes(100, 100, 1000, target_pool_pct=1)


def test_instruments_are_immutable_and_caps_consistent():
    security = ovf.common(100)
    with pytest.raises(ValidationError):
        security.shares = 200
    with pytest.raises(ValidationError):
        ovf.preferred(100, 1, participating=True, liquidation_multiple=2, participation_cap=1)
    with pytest.raises(ValidationError):
        ovf.preferred(100, 1, participation_cap=2)


def test_diagnostics_costs_and_empty_cap_table():
    table = ovf.CapTable().add(ovf.common(100, price=0))
    report = table.waterfall_detailed(100, transaction_costs=10)
    assert report.net_exit == 90
    assert report.converged and report.max_unilateral_gain <= report.tolerance
    assert report.conservation_error == 0
    assert report.input_hash == table.waterfall_detailed(100, 10).input_hash
    assert report.input_hash != table.waterfall_detailed(101, 10).input_hash
    assert report.payouts[0].effective_multiple is None
    with pytest.raises(ValueError, match="allocated"):
        ovf.CapTable().waterfall(100)
    assert ovf.CapTable().waterfall(0) == []
    with pytest.raises(ValueError, match="positive integer"):
        table.waterfall(100, max_iterations=0)


def test_iteration_budget_cannot_return_an_unverified_state():
    table = ovf.CapTable().add(ovf.common(1))
    # This profile requires a second pass; the first pass leaves a profitable deviation.
    for i, (shares, price, rank, multiple, ratio) in enumerate(
        [
            (6, 2, 1, 3, 1),
            (6, 2, 1, 3, 2),
            (6, 10, 1, 3, 0.5),
            (2, 5, 2, 2, 0.5),
            (9, 8, 3, 3, 2),
        ]
    ):
        table.add(
            ovf.preferred(
                shares,
                price,
                seniority=rank,
                liquidation_multiple=multiple,
                conversion_ratio=ratio,
                holder_id=f"p{i}",
            )
        )
    with pytest.raises(ovf.WaterfallConvergenceError, match="after 1 iterations"):
        table.waterfall(835, max_iterations=1)
    report = table.waterfall_detailed(835)
    assert report.iterations == 2
    assert report.max_unilateral_gain <= report.tolerance
    assert sum(p.amount for p in report.payouts) == pytest.approx(835)
