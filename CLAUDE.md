# Claude Instructions for Equilibria / Open Venture Framework (OVF)

## Overview
This repository contains `equilibria` / `ovf`, a verified Python research library and simulation engine for venture capital financing mechanics, exit waterfalls, SAFE dilution, and institutional governance.

## Commands
- Run test suite: `.venv/bin/pytest`
- Run linter & formatter: `.venv/bin/ruff check src tests examples`
- Run type checker: `.venv/bin/mypy src`
- Build wheel: `python -m build`

## Project Skills
This project includes a specialized **Venture Capital Modeling Skill** located in `.claude/skills/venture-capital/SKILL.md` (or `.agents/skills/venture-capital/SKILL.md`).
- When asked about exit waterfalls, liquidation preference stacks, or conversion games, consult `.claude/skills/venture-capital/references/waterfall_mechanics.md`.
- When asked about pre/post-money SAFEs, option pool dilution, or priced round conversion, consult `.claude/skills/venture-capital/references/safe_dilution.md`.
- When asked about convertible debt, anti-dilution (broad/narrow weighted average, full ratchet), or governance, consult `.claude/skills/venture-capital/references/debt_and_antidilution.md`.

## Architectural Guidelines
1. **Accounting Invariants:** Never violate proceeds conservation ($\sum \text{payouts} == \text{exit\_valuation}$), share conservation, or non-negativity.
2. **Immutable Securities:** Security objects are immutable; construct new snapshot objects for subsequent rounds.
3. **No Halve-Measure Calculations:** Always check for convergence and game-theoretic unilateral deviation stability.
4. **Explicit Assumptions:** Always return explicit calculation traces and assumptions.
