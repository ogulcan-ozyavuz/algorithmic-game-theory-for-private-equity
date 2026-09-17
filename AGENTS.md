# Agent Instructions: Equilibria · Open Venture Framework (OVF)

Universal instructions for AI coding assistants (Antigravity, OpenAI Codex, Claude Code, GitHub Copilot, Cursor).

## Project Identity & Mission
`ovf` (imported as `equilibria` or `ovf`) is a verified Python library for venture capital modeling: exit waterfalls, SAFE conversion, convertible debt, anti-dilution, and capitalization tables.

## Active Skills & Decision Runbooks
The primary project skill is located at `.agents/skills/venture-capital/SKILL.md`:
* **Exit Waterfall & Liquidation Preferences:** `.agents/skills/venture-capital/references/waterfall_mechanics.md`
* **SAFE Math & Option Pool Dilution:** `.agents/skills/venture-capital/references/safe_dilution.md`
* **Debt, Anti-Dilution & Governance:** `.agents/skills/venture-capital/references/debt_and_antidilution.md`
* **VC Terms & Standards Knowledge Base:** `.agents/skills/venture-capital/references/terms_reference.md`

## Verification & Strict Accounting Invariants
Any code generating or modifying calculations MUST satisfy:
1. **Proceeds Conservation:** $\sum \text{payouts} == \text{exit\_valuation}$ within tolerance $10^{-6}$.
2. **Share Conservation:** $\sum \text{allocated shares} + \text{unallocated pool} == \text{total shares}$.
3. **Unallocated Pool Exclusion:** Unallocated option capacity receives 0 cash proceeds at exit.
4. **Nash Conversion Stability:** All preferred positions must be checked for unilateral profitable deviation; fail explicitly if unstable or cycling.

## Development Commands
```bash
.venv/bin/pytest                     # Run all test fixtures
.venv/bin/ruff check src tests       # Enforce styling and lint rules
.venv/bin/mypy src                   # Strict static type check
```
