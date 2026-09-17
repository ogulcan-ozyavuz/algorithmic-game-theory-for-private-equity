# GitHub Copilot & Codex Instructions for OVF / Equilibria

This repository develops `equilibria` (`ovf`), a verified Python library for venture capital modeling.

## Domain Guidelines
- Consult the specialized skill definitions in `.agents/skills/venture-capital/SKILL.md`.
- Exit Waterfalls: Use `ct.waterfall_detailed(exit_valuation)` to capture convergence diagnostics and unilateral deviation bounds.
- SAFEs: In a post-money SAFE, ownership is locked before the new money and option pool. In a pre-money SAFE, solve circularity via the bracketed solver.
- Never allocate exit cash to unallocated option pool capacity.
- Development commands: `.venv/bin/pytest`, `.venv/bin/ruff check src tests`, `.venv/bin/mypy src`.
