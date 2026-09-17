# Debt Instruments, Anti-Dilution & Governance Reference

This reference documents institutional venture instruments including convertible notes, venture debt, down-round anti-dilution ratchets, and shareholder voting governance.

---

## 1. Debt Instruments & Absolute Priority

### Seniority Rank 0
* In liquidation, bankruptcy, or asset sale, debt holders hold claims superior to all equity holders (**Seniority 0**).
* Proceeds must completely satisfy debt principal + accrued interest before any preference dollar flows to Series Preferred or Common.

### Accrued Interest Models
1. **Simple Interest:** $\text{Claim} = \text{Principal} \times (1 + r \times t)$
2. **Compound Interest:** $\text{Claim} = \text{Principal} \times (1 + r)^t$
3. **Payment-in-Kind (PIK):** Accrued interest capitalized into principal at stated intervals.

### Maturity & Conversion Triggers
* **Qualified Financing:** Automatic conversion into preferred shares at $\min(P_{\text{cap}}, P_{\text{round}} \times (1 - d))$.
* **Maturity Without Financing:** Noteholders may elect cash repayment or optional conversion at a negotiated baseline valuation.

---

## 2. Anti-Dilution Mechanics (Down-Rounds)

When Series $N$ shares are issued at a price $P_{\text{new}} < P_{\text{old}}$:

### Broad-Based Weighted Average (NVCA Standard)
The new conversion price $P_{\text{conv}}$ for earlier preferred series is:

$$P_{\text{conv}} = P_{\text{old}} \times \frac{A + B}{A + C}$$

Where:
* $A = \text{Fully diluted shares outstanding immediately prior to new issue}$ (including common, options, warrants, and unconverted convertible instruments).
* $B = \frac{\text{Total aggregate consideration received in new round}}{P_{\text{old}}}$ (shares that would have been purchased at old price).
* $C = \text{Actual number of new shares issued in the down round}$.

### Narrow-Based Weighted Average
Same formula as broad-based, but $A$ is restricted strictly to currently outstanding capital stock (excluding unexercised options, warrants, or unissued pool).

### Full Ratchet
The most aggressive investor protection:
$$P_{\text{conv}} = P_{\text{new}}$$
The conversion price drops directly to the lowest price paid in the down round, regardless of how few shares were issued.

### Pay-to-Play Provision
Investors who fail to participate pro-rata in a down round forfeit their anti-dilution protection and liquidation preference, automatically converting to Common Stock.

---

## 3. Governance, Class Voting & Drag-Along

* **Class Voting:** A series of Preferred stock votes as a separate class on conversion or liquidation. If the majority of Series A votes to convert, all Series A holders are legally bound to convert.
* **Drag-Along Rights:** If a specified supermajority (e.g., Board + 60% of Preferred + Founders) approves an acquisition, minority holders are compelled to vote in favor and tender their shares.
* **Protective Provisions (Negative Covenants):** Preferred shareholders retain veto power over:
  1. Creation of senior equity or debt.
  2. Alteration of rights, preferences, or privileges.
  3. Liquidation, merger, or sale of substantial assets.
