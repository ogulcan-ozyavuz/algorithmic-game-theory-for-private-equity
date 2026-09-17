# Contributing

OVF / Equilibria is an alpha research library with one shared implementation.
The maintainer reviews changes to contract semantics and the public API.

Install with `python -m pip install -e '.[dev]'`. Run:

```bash
python -m pytest
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m mypy src
```

For calculation issues include a minimal input, expected amounts, the applicable
contract wording or published derivation, engine version and diagnostics. Use
synthetic or permissioned examples. Never change expected values only to make a
failing financial test pass; explain the underlying economic convention.

Changes to numerical behavior need a regression test and independent expected values.
Document new supported scope and errors in `docs/semantics.md`. Keep inference,
valuation and optional interfaces outside the deterministic core.

Support is best-effort; no service-level commitment is currently offered. Public
issues and review workflows will be enabled with the public repository launch.
