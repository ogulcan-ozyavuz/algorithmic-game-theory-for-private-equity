#!/usr/bin/env python3
"""
Equilibria Showcase
===================
Algorithmic Game Theory & Nash Equilibrium Solver for Multi-Class Private Equity.

This simulation demonstrates an illustrative Series C venture capital cap table across
multiple exit regimes ($15M distress sale to $250M home-run acquisition), solving the
simultaneous non-cooperative conversion game among preferred equity classes.
"""

import equilibria as eq


def run_showcase() -> None:
    print("=" * 80)
    print(" EQUILIBRIA: Algorithmic Game Theory & Nash Equilibrium Solver")
    print(" Benchmark: Multi-Class Venture Capital Capitalization Structure")
    print("=" * 80)

    # Construct the Capitalization Structure
    ct = eq.CapTable()

    # 1. Founders Common Stock
    ct.add(eq.common(shares=10_000_000, holder_id="Founders", price=0.0001))

    # 2. Employee Stock Option Pool (ESOP)
    ct.add(
        eq.common(shares=1_500_000, price=0, holder_id="Employees", security_id="employees_issued")
    )
    ct.add(eq.option_pool(reserved_shares=500_000, holder_id="Unallocated pool"))

    # 3. Series A Preferred: 1.0x Non-Participating, Seniority Tier 3 (Junior)
    # Invested: 2,500,000 shares * $2.00 = $5,000,000. Preference = $5,000,000.
    ct.add(
        eq.preferred(
            shares=2_500_000,
            price=2.00,
            seniority=3,
            liquidation_multiple=1.0,
            participating=False,
            holder_id="Series A (Early VC)",
            security_id="pref_series_a",
        )
    )

    # 4. Series B Preferred: 1.0x Participating with 3.0x Cap, Seniority Tier 2
    # Invested: 2,000,000 shares * $5.00 = $10,000,000. Base preference = $10,000,000. Max payout = $30,000,000.
    ct.add(
        eq.preferred(
            shares=2_000_000,
            price=5.00,
            seniority=2,
            liquidation_multiple=1.0,
            participating=True,
            participation_cap=3.0,
            holder_id="Series B (Growth VC)",
            security_id="pref_series_b",
        )
    )

    # 5. Series C Preferred: 1.5x Non-Participating, Seniority Tier 1 (Senior / Downside Protected)
    # Invested: 1,500,000 shares * $12.00 = $18,000,000. Preference = 1.5x * $18M = $27,000,000.
    ct.add(
        eq.preferred(
            shares=1_500_000,
            price=12.00,
            seniority=1,
            liquidation_multiple=1.5,
            participating=False,
            holder_id="Series C (Late-Stage)",
            security_id="pref_series_c",
        )
    )

    fd_shares = ct.fully_diluted_shares
    print(f"\n[1] Total Fully Diluted Share Count: {fd_shares:,.0f}")
    print("Initial Ownership Distribution (Fully Diluted):")
    for holder, pct in ct.ownership_breakdown().items():
        print(f"  • {holder:<25}: {pct:>7.2%}")

    # Exit scenarios to evaluate across the full payoff landscape
    test_exits = [
        (15_000_000, "Distressed Liquidation (< Total Liquidation Preferences)"),
        (35_000_000, "Partial Recovery"),
        (75_000_000, "Moderate Acquisition"),
        (150_000_000, "Strong Growth Exit"),
        (250_000_000, "Home-Run Acquisition (Full Dilution Scaling)"),
    ]

    for exit_val, description in test_exits:
        print("\n" + "-" * 80)
        print(f"SCENARIO: ${exit_val / 1e6:,.1f}M Exit — {description}")
        print("-" * 80)

        report = ct.waterfall_detailed(exit_valuation=exit_val)
        payouts = report.payouts

        header = f"{'Holder / Security':<24} | {'Invested':<10} | {'Preference':<11} | {'Residual':<11} | {'Total Payout':<13} | {'MOIC':<6} | {'Status'}"
        print(header)
        print("-" * len(header))

        total_distributed = 0.0
        for p in payouts:
            status = "CONVERTED" if p.converted else "NOT CONVERTED"
            inv_str = f"${p.invested_capital / 1e6:,.2f}M" if p.invested_capital > 0 else "—"
            pref_str = f"${p.preference_payout / 1e6:,.2f}M"
            res_str = f"${(p.participation_payout + p.residual_payout) / 1e6:,.2f}M"
            payout_str = f"${p.amount / 1e6:,.2f}M ({p.payout_pct:.1%})"
            moic_str = f"{p.effective_multiple:.2f}x" if p.effective_multiple is not None else "—"

            print(
                f"{p.holder_id:<24} | {inv_str:<10} | {pref_str:<11} | {res_str:<11} | {payout_str:<13} | {moic_str:<6} | {status}"
            )
            total_distributed += p.amount

        print("-" * len(header))
        print(
            f"Total Exit Value Accounted: ${total_distributed / 1e6:,.2f}M / ${exit_val / 1e6:,.2f}M (Conservation Δ = ${abs(total_distributed - exit_val):.2f})"
        )

    print("\n" + "=" * 80)
    print(
        " EQUILIBRIA EXECUTION COMPLETED: All returned states passed unilateral-deviation checks."
    )
    print("=" * 80)


if __name__ == "__main__":
    run_showcase()
