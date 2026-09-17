# SAFE Dilution, Option Pools & Priced Round Conversion

This reference documents the mathematical conventions, capitalization rules, and solving mechanics for Simple Agreements for Future Equity (SAFEs) in `equilibria` / `ovf`.

---

## 1. Post-Money vs. Pre-Money SAFEs

### Post-Money SAFE (YC Standard)
In a post-money SAFE with valuation cap $C$ and investment amount $A$:
* The investor's ownership is fixed **relative to company capitalization prior to the new priced round and prior to the new option pool**:
  $$\text{Ownership}_{\text{pre-round}} = \min\left(1.0, \frac{A}{C}\right)$$
* In a subsequent priced round with new money $N$ and post-money valuation $P_{\text{post}} = P_{\text{pre}} + N$, the SAFE holder's ownership is diluted by the incoming investors and any newly expanded option pool:
  $$\text{Final Ownership} = \text{Ownership}_{\text{pre-round}} \times \left(1 - \text{Dilution}_{\text{new\_money}} - \text{Dilution}_{\text{new\_pool}}\right)$$

### Pre-Money SAFE
In a pre-money SAFE:
* The valuation cap applies to the pre-financing capitalization.
* Because the option pool expansion and multiple pre-money SAFEs dilute each other, the share price equation is circular.
* `equilibria` solves this using a **bracketed root solver (Brent's method / bisection)** to find the exact share price that balances share supply and cap commitments without numerical instability.

---

## 2. Option Pool Expansion Mechanics

When a target unallocated pool percentage $p_{\text{target}}$ is specified:
* **Founder Dilution:** Standard venture convention requires the unallocated option pool expansion to be created entirely from the pre-money capitalization, diluting founders and common holders before the new lead investor buys in.
* **Capitalization Equation:**
  $$\text{Fully Diluted Post-Round Shares} = \text{Common} + \text{Converted SAFEs} + \text{New Preferred} + \text{Unallocated Pool}$$
  where $\text{Unallocated Pool} = p_{\text{target}} \times \text{Fully Diluted Post-Round Shares}$.

---

## 3. Conversion Price Determination

For each SAFE with cap $C$, discount rate $d \in [0, 1)$, and round share price $P_{\text{round}}$:
1. **Cap Price:** $P_{\text{cap}} = \frac{C}{\text{Capitalization Basis}}$
2. **Discount Price:** $P_{\text{discount}} = P_{\text{round}} \times (1 - d)$
3. **Effective Price:**
   $$P_{\text{eff}} = \min(P_{\text{round}}, P_{\text{cap}}, P_{\text{discount}})$$
4. **Shares Issued:** $\text{Shares} = \frac{A}{P_{\text{eff}}}$

---

## 4. Round to Cap Table Snapshot Workflow

`solve_priced_round_with_safes` produces a `PricedRoundResult`. Calling `.to_cap_table()` on the result creates an explicit post-round `CapTable` ready for exit waterfall modeling:
* Converted SAFEs become Preferred stock with their effective conversion price as cost basis.
* New money becomes Preferred stock with 1x non-participating liquidation preference.
* Unallocated pool capacity is tracked separately and excluded from cash proceeds.
