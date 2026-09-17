"""
Unit tests for ovf.contracts.securities.
"""

from ovf.contracts.securities import (
    CommonStock,
    PostMoneySAFE,
    PreferredStock,
    StockOptionPool,
    common,
    option_pool,
    preferred,
    safe_post,
)


def test_common_stock_creation():
    c = common(shares=10_000_000, holder_id="founders")
    assert isinstance(c, CommonStock)
    assert c.shares == 10_000_000
    assert c.holder_id == "founders"
    assert c.is_convertible() is False
    assert c.base_liquidation_preference() == 0.0


def test_preferred_stock_properties():
    p = preferred(
        shares=2_000_000,
        price=2.50,
        seniority=1,
        liquidation_multiple=1.5,
        participating=True,
        participation_cap=3.0,
        holder_id="series_a_lead",
    )
    assert isinstance(p, PreferredStock)
    assert p.invested_capital == 5_000_000.0  # 2M * 2.50
    # 1.5x on 5M = 7.5M
    assert p.base_liquidation_preference() == 7_500_000.0
    assert p.is_convertible() is True
    assert p.converted_shares == 2_000_000.0


def test_post_money_safe():
    s = safe_post(amount=500_000, cap=5_000_000, holder_id="angel")
    assert isinstance(s, PostMoneySAFE)
    assert s.investment_amount == 500_000.0
    assert s.valuation_cap == 5_000_000.0
    assert s.target_ownership == 0.10  # 500k / 5M = 10%
    assert s.base_liquidation_preference() == 500_000.0


def test_stock_option_pool():
    pool = option_pool(reserved_shares=1_000_000, allocated_shares=400_000)
    assert isinstance(pool, StockOptionPool)
    assert pool.shares == 1_000_000.0
    assert pool.allocated_shares == 400_000.0
    assert pool.unallocated_shares == 600_000.0
    assert pool.base_liquidation_preference() == 0.0
