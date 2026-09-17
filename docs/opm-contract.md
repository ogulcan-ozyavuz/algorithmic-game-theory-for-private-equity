# open-opm: the contract between the parts

Status 2026-09-15. This document is written before the code and is authoritative while
`ovf.opm` is being built in parallel. If an instruction here is wrong, say so and ask;
do not quietly deviate, because someone else is coding against the same sentence.

## Checks

The module was built in its own branch, alongside `open-pme` in a separate branch. The
whole suite must be green when the work is finished, not only the module's own tests:

```bash
python -m pytest
python -m ruff check src tests examples
python -m ruff format src tests examples
python -m mypy src
```

## The thesis this module exists to state

The Option Pricing Method treats total equity value `X` as lognormal at a liquidity date
and each share class's claim as a portfolio of call spreads on it. A class whose payoff is
`f(X)` gets value `sum_t w_t * [C(k_t) - C(k_{t+1})]`, where the `k_t` are **breakpoints**
and `w_t` is the class's share of each marginal dollar between `k_t` and `k_{t+1}`.

That decomposition is arithmetic only if, for the cap table in hand, every class's payoff is

1. **continuous** in `X`,
2. **piecewise linear** in `X`,
3. **non-decreasing** in `X`, and
4. shares each marginal dollar in weights that are non-negative and **sum to one**.

Practice treats all four as facts. They are assumptions about a particular table. This
repository already has a counterexample to (3): `docs/governance.md` records 1,246 of 3,000
generated tables in which a position's cash *fell* as the exit rose, because a higher exit
flipped a Requisite Holders vote and forced a dissenting series to give up its preference.
On such a table the standard construction still produces a number, and that number is wrong
in a way no invariant inside the option maths can detect, because the call spread weights go
negative and the "allocation" stops being an allocation.

**Amended 2026-09-15 after worker A's finding, which is sharper than the paragraph above.**
The failure is not a negative slope. It is a **step**. Within each vote regime the table is
an ordinary one; what the vote does is jump between regimes. Verified against
`tests/governance_fixtures.py`: at an exit of $57.4M Series B receives $9,000,000, and at
$57.6M it receives $7,513,043.48. The company sold for $200,000 more and that series lost
$1,486,956.52. So property (1) fails, not only (3).

That matters because a call spread is continuous. **No combination of call spreads, in any
weights, positive or negative, reproduces a step.** On such a table the payoff is not merely
awkward to decompose; it is not in the span of the instruments the method decomposes into.
That is the module's central claim and it is stronger than the one this document first made.

`BreakpointSchedule` therefore carries `discontinuities: list[Discontinuity]` and a
`continuous` flag, and `payout()` applies each jump at or below the queried exit, right
continuous by convention: at the step itself the vote is tied and `ovf.governance` refuses
to call it, so the payoff there is undefined. A step is recorded as a fact and **never
smeared into a narrow steep tranche** - a smeared window replays to tolerance while making
the weights an artifact of the window width.

Both `breakpoint_schedule` and `opm_allocate` take a keyword-only
`collective_conversion: CollectiveConversion | None = None`, from `ovf.governance`. Without
the passthrough a caller holding a governed table would silently receive the ungoverned
answer, which is the exact failure the module exists to prevent.

So the module's job is not to compute OPM. It is to **derive the breakpoints from the
verified waterfall engine rather than from a hand-built table, check all four properties,
and refuse when one fails.** A refusal with a stated reason is the deliverable on those
tables. Do not add a flag that skips the check.

## Shared types: `src/ovf/opm/types.py`

Already written and owned by the coordinator. **Read it first.** It defines `Breakpoint`,
`Tranche`, `BreakpointSchedule`, `OpmInputs`, `ClassValue`, `OpmResult`, `BacksolveResult`,
`DlomEstimate`, the `Rate` and `Discount` aliases, and the error hierarchy
`OpmError` / `OpmAssumptionError` / `BreakpointError` / `BacksolveError`.

Nobody but the coordinator edits that file. If you need a field it does not have, ask; do
not add one, and do not define a parallel type of your own.

Two details in it that are deliberate and that you must not "fix":

- `Rate` is a plain float and may be negative. Real risk-free curves have been.
- `Discount` has no upper bound. Longstaff's lookback bound exceeds 100% for large
  `volatility * sqrt(time)`, and that is the honest output of that formula.

## The interfaces

Code to these exactly. The parts are being written at the same time.

```python
# src/ovf/opm/breakpoints.py
def breakpoint_schedule(
    securities: Sequence[Security],
    *,
    as_of: date | None = None,
    upper_probe: float | None = None,
    atol: float = 1e-6,
    collective_conversion: CollectiveConversion | None = None,
) -> BreakpointSchedule: ...

# src/ovf/opm/blackscholes.py
def call_value(
    spot: float, strike: float, volatility: float, time: float,
    risk_free_rate: float, dividend_yield: float = 0.0,
) -> float: ...

# src/ovf/opm/allocate.py
def opm_allocate(
    securities: Sequence[Security],
    *,
    inputs: OpmInputs,
    as_of: date | None = None,
    schedule: BreakpointSchedule | None = None,
    collective_conversion: CollectiveConversion | None = None,
) -> OpmResult: ...

# src/ovf/opm/backsolve.py
def backsolve(
    securities: Sequence[Security],
    *,
    security_id: str,
    price_per_share: float,
    volatility: float,
    time_to_liquidity: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    as_of: date | None = None,
    collective_conversion: CollectiveConversion | None = None,
) -> BacksolveResult: ...

# src/ovf/opm/dlom.py
def chaffe_dlom(*, volatility, time, risk_free_rate, dividend_yield=0.0) -> DlomEstimate: ...
def finnerty_dlom(...) -> DlomEstimate: ...
def longstaff_dlom(...) -> DlomEstimate: ...
def ghaidarov_dlom(...) -> DlomEstimate: ...
def dlom_comparison(...) -> list[DlomEstimate]: ...
```

## Invariants every part asserts

- **Value conservation.** `sum(class values) == equity_value * exp(-dividend_yield * time)`
  to a relative `1e-9`. A call struck at zero is the whole discounted spot, so the tranches
  must exhaust it. Report the measured error in `conservation_error`; never normalise it away.
- **Schedule replay.** `BreakpointSchedule.payout(X)` must agree with `solve_waterfall` at
  every breakpoint, at both sides of every breakpoint, and at interior probes, within `atol`.
  The largest observed gap goes in `max_linearity_error`.
- **Weights.** Non-negative, summing to one in every tranche, with the measured error kept.
- **Deterministic limit.** As `volatility -> 0` with `risk_free_rate = dividend_yield = 0`,
  each class's OPM value must converge to its `solve_waterfall` payout at `X = equity_value`.
  This is the strongest single check in the module: it ties the option maths back to the
  engine. Assert it numerically at small volatility.
- **No silent defaults.** Volatility, time to liquidity and the risk-free rate are required
  arguments everywhere. There is no house volatility.

## House rules, taken from the three waves already merged

- Refuse rather than guess. A wrong number is worse than an error. Every refusal message
  says what failed, where, and by how much.
- Every fixture is derived by hand in a docs file before it is asserted in a test, with the
  source named. Independently recompute each derivation, with `fractions.Fraction` where the
  quantity is rational, before writing it down.
- Cite the source for every formula: author, year, publication. For the method itself the
  reference is the AICPA Accounting and Valuation Guide, *Valuation of Privately-Held-Company
  Equity Securities Issued as Compensation*. Do not claim conformance with it; claim that a
  formula is implemented as published.
- State what remains unsupported at the end of your docs file. An implementation that does
  not also say what it cannot do has not finished.
- Type annotations everywhere, `mypy` strict clean, `ruff` clean, line length 100.
- No network access is needed. Do not fetch anything.

## File ownership, absolute

You may create and edit **only** the files on your row. Everything else in the repository,
including every other worker's row and every shared file, is read-only to you. There is no
version control safety net between workers inside a single branch, so an edit outside your
row destroys someone's work.

| Worker | Owns |
|---|---|
| A — breakpoints | `src/ovf/opm/breakpoints.py`, `tests/test_opm_breakpoints.py`, `tests/opm_breakpoint_fixtures.py`, `docs/opm-breakpoints.md` |
| B — option maths | `src/ovf/opm/blackscholes.py`, `src/ovf/opm/allocate.py`, `tests/test_opm_blackscholes.py`, `tests/test_opm_allocate.py`, `docs/opm.md` |
| C — backsolve | `src/ovf/opm/backsolve.py`, `tests/test_opm_backsolve.py`, `docs/opm-backsolve.md` |
| D — marketability | `src/ovf/opm/dlom.py`, `tests/test_opm_dlom.py`, `docs/dlom.md` |
| E — validation | `tests/opm_oracle.py`, `tests/test_opm_validation.py`, `docs/opm-findings.md` |
| Coordinator | `src/ovf/opm/types.py`, `src/ovf/opm/__init__.py`, `src/ovf/__init__.py`, `src/equilibria/__init__.py`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `TODO.md`, `docs/limitations.md`, `docs/fixtures.md`, `docs/opm-contract.md` |

Out of scope for this module, without exception: `src/ovf/pme/`, `src/ovf_mcp/`, and any
file on another row.

## Reporting

Ask when a decision is genuinely ambiguous rather than picking one and moving on: a wrong
assumption propagates into three other files. Report at the end with what changed, what was
found, and what was left undone. A real obstacle is worth more than success that cannot be
evidenced.
