---
name: Calculation issue
about: A number disagrees with a contract, a closing statement or your own derivation
title: "[calc] "
labels: calculation
---

**This is the most useful report the project can receive.** Please include enough to
reproduce the disagreement; a screenshot of a total is not enough to act on.

### Inputs

Cap table, exit value and any transaction costs. Code, JSON or a table is all fine.

```python
# e.g.
import equilibria as eq
table = eq.CapTable()
table.add(eq.common(8_000_000, holder_id="founders", security_id="common"))
table.add(eq.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"))
report = table.waterfall_detailed(35_000_000)
```

### What the library returned

Paste the payouts and the verification block (`converged`, `max_unilateral_gain`,
`conservation_error`, `input_hash`, `engine_version`).

### What you expected

The number, and where it comes from: a closing statement, a charter provision, a
spreadsheet, or your own derivation. Please show the arithmetic if it is yours.

### Convention

Which convention or document the expected number follows — for example 1x
non-participating, stacked or pari passu seniority, a specific SAFE form, or one of
the Cooley financing conventions. Differences here are usually the cause, and they are
not bugs; they tell us which option to add.

### Checked against limitations?

- [ ] I read [docs/limitations.md](../../docs/limitations.md) and the difference is not
      explained by something listed there.

If it *is* explained by something on that list, please still open the issue and say
which item. That tells us which gap to close first.

### Environment

Package version, Python version, operating system.
