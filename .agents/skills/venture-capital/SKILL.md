---
name: venture-capital-modeling
description: >-
  Expert venture capital modeling and startup financing skill. Use when analyzing,
  calculating, or implementing exit waterfalls (liquidation preferences, conversion games),
  SAFE dilution (pre/post-money, valuation caps, discounts, option pools), convertible debt,
  anti-dilution ratchet mechanics, class governance, or Cap Table engineering in the OVF/Equilibria codebase.
---

# Venture Capital Modeling Expert

Specialized skill for venture financing mechanics, capitalization tables, exit waterfalls, and quantitative VC contract modeling using the Equilibria / Open Venture Framework (`ovf`).

## Core Responsibilities & Capabilities

1. **Exit Waterfall Calculations:** Common vs. preferred stock, seniority tiers, pari-passu preference sharing, participation caps, and game-theoretic conversion optimization.
2. **Financing & SAFE Dilution:** Homogeneous/heterogeneous SAFEs, pre/post-money capitalization, option pool expansions, and priced round conversions.
3. **Debt & Anti-Dilution:** Convertible notes with accrued interest, seniority-0 priority, broad/narrow-based weighted average anti-dilution, and full ratchet mechanics.
4. **Governance & Standards:** Share-class voting, drag-along rights, and Open Cap Table Standard (OCF) schema compatibility.

---

## Workflow Decision Tree

```text
User Request
 ├── Exit Payout / Proceeds Distribution?
 │    └── Load: references/waterfall_mechanics.md
 │         └─ Construct CapTable → add common/preferred → run waterfall_detailed()
 │
 ├── SAFE Dilution / Priced Round / Cap Table Snapshot?
 │    └── Load: references/safe_dilution.md
 │         └─ solve_priced_round_with_safes() → inspect ownership → to_cap_table()
 │
 ├── Convertible Debt / Down-Round Anti-Dilution / Class Voting?
 │    └── Load: references/debt_and_antidilution.md
 │         └─ Model Seniority 0 debt, weighted average price adjust, or voting mandates
 │
 └── Terminology / Legal Standards / Verification Invariants?
      └── Load: references/terms_reference.md
           └─ Check accounting invariants, NVCA/OCF conventions & knowledge base
```

---

## Operational Guidelines

### 1. Enforce Accounting Invariants
Every calculation must verify the four core invariants:
* **Proceeds Conservation:** $\sum \text{payouts} == \text{exit\_valuation}$ (within float tolerance $\le 10^{-6}$).
* **Share Conservation:** $\sum \text{allocated shares} + \text{unallocated pool} == \text{total fully diluted shares}$.
* **Monotonicity & Non-Negativity:** Payout amounts $\ge 0$; common payout is non-decreasing with respect to exit valuation above preference hurdle.
* **Unallocated Capacity Exclusion:** Unallocated option pool capacity never receives cash proceeds at exit.

### 2. Standard Code Patterns

```python
import equilibria as eq

# 1. Cap Table & Exit Waterfall
ct = eq.CapTable()
ct.add(eq.common(shares=8_000_000, price=0, holder_id="founders"))
ct.add(eq.preferred(shares=2_000_000, price=2.50, holder_id="series_a", seniority=1))
report = ct.waterfall_detailed(exit_valuation=35_000_000)

# 2. SAFE Priced Round
result = eq.solve_priced_round_with_safes(
    prior_common_shares=8_000_000,
    new_money=3_000_000,
    pre_money_valuation=12_000_000,
    target_pool_pct=0.10,
    safes=[eq.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel")],
)
post_round_ct = result.to_cap_table()
```

### 3. Verification & Testing Commands
Always verify changes with the project test and lint suite:
```bash
.venv/bin/pytest                     # Run 35+ verification tests
.venv/bin/ruff check src tests       # Enforce linting standards
.venv/bin/mypy src                   # Verify type safety
```
