# Equilibria: installation and API quickstart

A Python research library for venture financing scenarios: preferred-stock exit
waterfalls and explicitly scoped SAFE conversion. `equilibria` is the public-facing
import alias; both imports use the same `ovf` implementation and distribution.

**Status: alpha.** Results are checked against accounting invariants and unilateral
conversion deviations within a reported tolerance. No general existence, uniqueness,
Tarski convergence, regulatory-compliance or market-first claim is made. Read
[what this does not model](limitations.md) before using a number.

## Install and verify

From this checkout, with Python 3.11 or newer:

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m mypy src
```

The distribution is named `ovf`; separate `waterfall-engine`, `safe-math` and other
launch names are proposed module identities, not published packages.

## Try it without writing code

```bash
python -m ovf waterfall --demo F5b     # a participation cap that conversion beats
python -m ovf sweep --demo F8a         # the exit range where common receives nothing
python -m ovf equilibria --demo F3     # two equilibrium profiles, one payout
python -m ovf safe --prior-common 8000000 --new-money 3000000 \
    --pre-money 12000000 --pool 0.10 --safe 1000000:10000000:angel
```

Every subcommand prints the assumptions its result depends on. `--file table.json`
accepts a cap table document instead of a built-in demo. Installation also provides an
`ovf` console script, so `ovf sweep --demo F8a` works without `python -m`.

## Exit waterfall

```python
import equilibria as eq

ct = eq.CapTable()
ct.add(eq.common(shares=8_000_000, holder_id="founders", security_id="common"))
ct.add(eq.preferred(shares=2_000_000, price=2.50, holder_id="series_a",
                    security_id="series_a"))

report = ct.waterfall_detailed(exit_valuation=35_000_000)
for payout in report.payouts:
    print(f"{payout.holder_id}: ${payout.amount:,.0f} ({payout.payout_pct:.1%} of proceeds)")
print(f"Verified: {report.converged}; maximum unilateral gain: {report.max_unilateral_gain}")
```

Founders receive $28M and Series A receives $7M: the $5M preference is worth less than
a 20% as-converted share of $35M, so Series A converts. `ct.waterfall(...)` returns
just the payout list.

`payout_pct` is a share of proceeds, not equity; use `ct.ownership_breakdown()` for
fully diluted ownership. The two differ whenever an unallocated option reserve exists.
`Payout.ownership_pct` is a compatibility alias for `payout_pct`; new code should use
the explicit name.

## Whether the answer is unique

Each preferred position chooses independently between its preference and conversion,
so the exit is a simultaneous game rather than a sorted list. `solve_waterfall`
returns one verified equilibrium. To see whether others exist:

```python
survey = eq.enumerate_equilibria(ct.securities, exit_valuation=25_000_000)
print(len(survey.feasible_equilibria), survey.payoff_unique)
# 2 True
```

At $25M the preference and the as-converted value are both $5M, so both conversion
profiles are equilibria — and both pay the same amounts.

The checked-in tests investigate equilibrium multiplicity and payout agreement on
specified families. Larger historical experiment counts have no retained replay
artifacts in this repository and are not treated as verified evidence;
[docs/findings.md](findings.md) records that distinction.

## SAFE conversion, then exit

```python
result = eq.solve_priced_round_with_safes(
    prior_common_shares=8_000_000,
    new_money=3_000_000,
    pre_money_valuation=12_000_000,
    target_pool_pct=0,
    safes=[eq.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel")],
)
print(result.ownership_breakdown)
# founders: 72%, angel: 8%, new_preferred: 20%, option_pool: 0%

post_round = result.to_cap_table()
exit_result = post_round.waterfall_detailed(100_000_000)
```

Add a 10% pool to the same round and founders fall to 63%, the angel to 7%, while the
new investor still holds exactly 20%. A pool placed inside the negotiated pre-money is
paid for by everyone except the incoming round.

`to_cap_table()` explicitly creates a post-round snapshot. It assumes 1x,
non-participating, pari-passu preferred, founder common with unknown cost basis, and
an entirely unallocated new option pool. Other negotiated rights require explicit
instrument construction. Unconverted SAFEs are rejected by the exit engine.

## Supported and planned scope

| Component | Current scope |
|---|---|
| Exit waterfall | Common, preferred, integer seniority tiers, pari-passu preference sharing, participation caps, conversion ratios |
| Conversion search | Independent preferred positions, stable ID order, post-search deviation check; raises on failure |
| Equilibrium survey | Exhaustive enumeration of all `2**n` profiles, feasibility filter, payout-uniqueness report |
| SAFE math | Homogeneous capped pre- or post-money SAFEs; common-only starting capitalization; new pool; one documented round-pricing convention |
| Debt at exit | Term debt, venture debt and convertible notes; simple, stated-frequency compound and PIK accrual; paid ahead of all equity by ascending debt seniority, pro rata within a tier; an explicit `as_of` date is required and no clock is read |
| Anti-dilution | Broad-based and narrow-based weighted average and full ratchet, as pure functions. Every component of the `A` denominator is a required argument with no default. Applied to new cap-table snapshots at issuance by `ovf.financing`; see [financing](financing.md) |
| Preferred dividends | Cumulative accrual, forfeiture on conversion or paid-in-kind settlement, with explicit dates and cap conventions; see [dividends](dividends.md) |
| OCF | Read and write Open Cap Table Format v1.2.0 packages (`ovf.ocf`); 4 transaction types applied, 7 ignored, 32 refused |
| Option pool | Unallocated capacity counts in fully diluted ownership and receives no exit proceeds; granted options require explicit settlement modeling |
| Calculation trace | Input fingerprint, engine revision, assumptions, numerical diagnostics, multi-position holder disclosure |
| OPM/DLOM, fund metrics | Planned |
| Inference, decision optimization, MCP/RL benchmark | Planned |

`safe_post(..., discount_rate > 0)` models a custom capped-plus-discount instrument;
it does not implement YC's separate discount-only or MFN forms. The pre/post method
selects SAFE capitalization rules, not Cooley's three negotiated pricing conventions.

IDs must be unique within a cap table. Securities are immutable; create a replacement
object for a new snapshot. Numbers must be finite. A single base currency is assumed;
no currency conversion or settlement rounding is performed. Undefined return multiples
use `None`.

## Debt, anti-dilution and OCF

```python
from datetime import date
import equilibria as eq

table = eq.CapTable(securities=[
    eq.common(8_000_000, holder_id="founders", security_id="common"),
    eq.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"),
    eq.debt(principal=1_000_000, annual_rate=0.08, accrual="simple",
            day_count="actual/365_fixed", issue_date=date(2024, 1, 1), seniority=0,
            holder_id="lender", security_id="loan"),
])
report = table.waterfall_detailed(20_000_000, as_of=date(2026, 1, 1))
```

The loan is repaid first: `1,000,000 x (1 + 0.08 x 731/365) = $1,160,219.18`. `as_of` is
required whenever the table holds debt, and omitting it raises rather than assuming
today, because an implicit clock would make the result irreproducible.

Anti-dilution is a separate pure module. No public function has a default argument,
because whether the reserved-but-unissued pool belongs in the `A` denominator is set by
the charter and not by the formula:

```python
from ovf.antidilution import weighted_average, BROAD_BASED_NVCA
```

`ovf.ocf` reads and writes OCF v1.2.0 packages. One finding is worth stating here:
**participating-uncapped preferred is not expressible in OCF v1.2.0**, so the writer
refuses it rather than emitting a class that understates the holder or inventing a cap.
See [ocf](ocf.md).

## Documentation

- [Walkthrough](walkthrough.md) — a SAFE round through to an exit
- [What this does not model](limitations.md) — read before relying on a number
- [Calculation semantics](semantics.md) — the implemented equations
- [Debt](debt.md) — instruments, accrual and absolute priority at exit
- [Anti-dilution](antidilution.md) — weighted average, full ratchet, and the `A` denominator
- [OCF](ocf.md) — the v1.2.0 mapping, its four conventions, and what the format cannot express
- [Findings](findings.md) — evidence on the conversion game
- [Fixture provenance and derivations](fixtures.md) — where every expected number comes from
- [Deferred scope](deferred-scope.md) — what must be specified before it is built
- [Roadmap](roadmap.md), [launch plan](launch-plan.md), [TODO](../TODO.md), [changelog](../CHANGELOG.md)
- [Illustrative multi-class exit sweep](../examples/unicorn_game_showcase.py)
- [Research report](../vc-modelling-research-report.md) — working synthesis with claim-level review status

## Evidence

Tests include hand-derived fixtures with published derivations, accounting
regressions, adversarial conversion games, and a separate rational-arithmetic oracle
that enumerates all conversion strategies for small games. These establish evidence for
the documented model on the tested families; they do not prove universal equilibrium
properties. CI is configured in [.github/workflows/ci.yml](../.github/workflows/ci.yml).

Fixtures are source-derived and **not yet independently reviewed**. Independent review
of both the term shapes and the arithmetic is a launch gate.

## Contributing and citation

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [CITATION.cff](../CITATION.cff).
A calculation that disagrees with a real closing statement is the most useful report
this project can receive; the
[issue template](../.github/ISSUE_TEMPLATE/calculation-issue.md) asks for the inputs, the
expected number and the convention behind it. Apache-2.0; see [LICENSE](../LICENSE).
