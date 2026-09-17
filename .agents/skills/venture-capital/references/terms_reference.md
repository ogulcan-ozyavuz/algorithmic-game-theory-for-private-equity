# Venture Capital Terms & Standards Knowledge Base

This reference indexes the venture capital domain knowledge base, industry standards (NVCA, OCF, BVCA), and accounting invariants across the OVF codebase.

---

## 1. Key Terminology Index

| Term | Domain | Definition & Core Formula |
| :--- | :--- | :--- |
| **Liquidation Preference** | Exit Waterfall | Priority dollar return ($M \times I$) guaranteed to preferred holders before common distributions. |
| **Pari-Passu** | Exit Waterfall | Equal priority sharing among instruments within the same seniority tier when proceeds are insufficient. |
| **Valuation Cap** | SAFE / Note | Maximum company valuation at which convertible capital converts into equity. |
| **Post-Money SAFE** | Dilution | Instrument locking ownership percentage pre-round: $\text{Shares} = \frac{\text{Amount}}{\text{Cap}} \times \text{Company Capitalization}$. |
| **Pre-Money SAFE** | Dilution | Instrument where cap applies to pre-money cap table; circular dependency solved via bracketed root solver. |
| **Broad-Based WA** | Anti-Dilution | Down-round price adjustment factor: $\frac{A + B}{A + C}$ factoring all fully diluted equity. |
| **Full Ratchet** | Anti-Dilution | Immediate reset of conversion price to the exact lowest price of the down round: $P_{\text{conv}} = P_{\text{new}}$. |
| **Pay-to-Play** | Governance | Down-round clause forcing non-participating preferred shares into common shares. |
| **Drag-Along** | Governance | Legal mechanism compelling minority shareholders to accept a transaction approved by the specified majority. |
| **OCF** | Standards | Open Cap Table Standard (JSON format) maintained by the Open Cap Table Coalition. |

---

## 2. Standards & External References

1. **NVCA Model Documents:** Standard certificate of incorporation, investors' rights agreement, and term sheet templates used as reference fixtures for preferred stock classes.
2. **Open Cap Table Standard (OCF):** Canonical schemas for securities, stakeholders, vesting, and transactions (`ocf-core`).
3. **Knowledge Base Files:**
   * `docs/semantics.md` (numerical tolerances and semantic boundaries).
