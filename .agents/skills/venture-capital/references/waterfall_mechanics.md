# Exit Waterfall Mechanics & Conversion Game

This reference documents the mathematical rules, game-theoretic conversion search, and accounting invariants governing exit waterfalls in `equilibria` / `ovf`.

---

## 1. Payout Priority and Seniority

Proceeds from an exit valuation $V$ are distributed through an integer seniority hierarchy ($s = 1, 2, \dots, K$, where lower numbers denote higher priority):

1. **Seniority Tiers:** Tier $s=1$ receives preference payouts before tier $s=2$.
2. **Pari-Passu Preference Sharing:** If proceeds are insufficient to satisfy all claims within tier $s$, available proceeds are apportioned pro-rata based on dollar preference:
   $$\text{payout}_i = \text{RemainingProceeds} \times \frac{\text{preference}_i}{\sum_{j \in \text{Tier}(s)} \text{preference}_j}$$
3. **Common Residual:** Any proceeds remaining after all preference obligations are satisfied flow to common stock (and converted preferred shares) pro-rata by share count.

---

## 2. Preferred Conversion Dynamics (The Conversion Game)

Each preferred position $i$ with preference multiple $M_i$, investment $I_i$, conversion ratio $r_i$, and share count $S_i$ evaluates whether to:
* **Exercise Preference:** Collect liquidation preference $P_i = M_i \times I_i$ (subject to participation caps if participating).
* **Convert to Common:** Convert $S_i$ preferred shares into $r_i \times S_i$ common shares to participate in residual equity value.

### Game-Theoretic Equilibrium (Nash Stability)
* The engine evaluates best-response payoffs across all preferred holders.
* A conversion profile $c \in \{0, 1\}^N$ is stable if and only if no single preferred holder $i$ can unilaterally deviate ($c_i \to 1 - c_i$) and strictly increase their dollar payout:
  $$\Delta_i = \text{Payout}(c_i \oplus 1, c_{-i}) - \text{Payout}(c_i, c_{-i}) \le \text{tolerance}$$
* The solver returns `report.converged = True` and `report.max_unilateral_gain <= tolerance`. If cycling or instability occurs, it raises a convergence failure error.

---

## 3. Preferred Stock Flavors

* **Non-Participating Preferred:** Receives the **maximum** of (Preference Payout, Converted Common Share of Proceeds).
* **Fully Participating Preferred:** Receives Preference Payout **plus** pro-rata share of remaining common proceeds.
* **Capped Participating Preferred:** Receives Preference Payout plus common proceeds, up to an aggregate cap $C_i = \text{CapMultiple} \times I_i$. Once the cap binds, converting fully to common may yield a higher un-capped payout.

---

## 4. Invariants and Constraints

* **Strict Non-Negative Payouts:** $\forall i, \text{amount}_i \ge 0$.
* **Proceeds Reconciliation:** $|\sum_i \text{amount}_i - V| \le 10^{-6}$.
* **Unallocated Option Capacity:** Unallocated pool shares receive 0 exit proceeds.
* **Undefined MOIC:** When investment basis is 0 or unknown, multiple on invested capital is represented as `None`, never $\infty$ or zero.
