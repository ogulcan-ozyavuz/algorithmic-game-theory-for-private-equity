# Mathematical publication review

Reviewed 2026-09-15 against the live source tree. Scope: README mathematics,
reproducibility, and an executable equity example. Only this review was edited.
The supplied directory has no Git metadata, so this audits files present locally,
not their tracked status or an immutable release commit.

## Recommendation

Lead with **a venture exit calculator that verifies every preferred position's
unilateral conversion incentive**. The implemented, auditable claim is a feasible
approximate pure Nash equilibrium under stated position-level assumptions.
The source does not establish universal existence, payoff uniqueness, convergence,
or a three-sweep bound. Remove the large survey counts from the launch README until
their generators, seeds, results, and validation scripts accompany them.

Suggested README wording:

> Equilibria calculates who receives the proceeds of a venture exit under explicit
> preference, participation, seniority, and conversion terms. Before returning a
> result, it checks that no preferred position can improve its payout by more than
> the reported tolerance through a unilateral conversion switch, and reconciles
> payouts to net proceeds. For small tables, exhaustive enumeration reports every
> feasible stable conversion profile and compares their payouts.

Evidence: [solver and final verification](../../../src/ovf/waterfall.py#L211),
[enumeration](../../../src/ovf/waterfall.py#L403).

## 1. Exact game and allocation definition

**Players:** the `n` preferred *positions*, identified by `security_id`. Each chooses
`a_i = 0` (retain preferred rights) or `a_i = 1` (convert completely to common).
The strategy space is the full cube `{0,1}^n`; utility is that position's cash payout.
Common holders and an unallocated pool have no conversion action. A fund holding
several positions is not a single optimizing player; the report discloses repeated
preferred holders but does not optimize their combined wealth. This is a simultaneous
normal-form game, searched by sequential unilateral improvements.
[Source](../../../src/ovf/waterfall.py#L266),
[holder disclosure](../../../src/ovf/waterfall.py#L374).

Let gross exit be `V`, transaction costs `T`, and distributable net proceeds
`N = max(0, V - T)`. Current lower-level code first settles supported debt by claim,
in ascending debt seniority; let `D` be total debt cash paid and `E = N - D` the
equity budget. The example below has no debt. Debt payments do not vary with the
preferred conversion profile, and note repayment/conversion elections are not
optimized by this game. [Source](../../../src/ovf/waterfall.py#L161).

For preferred position `i`, define investment `I_i = shares_i × issue_price_i`,
preference claim `L_i = liquidation_multiple_i × I_i`, and common-equivalent units
`w_i = shares_i × conversion_ratio_i`.
[Contract definitions](../../../src/ovf/contracts/securities.py#L38).

**Preference stage.** Start with `R_0 = E`. For each ascending seniority tier `k`,
let `H_k(a)` contain its nonconverted positions and set

$$
Q_k=\sum_{i\in H_k(a)}L_i,\qquad
B_k=\min(R_{k-1},Q_k),\qquad
p_i=B_k\frac{L_i}{Q_k},\qquad R_k=R_{k-1}-B_k.
$$

Use `p_i = 0` when `Q_k = 0`; converted preferred and common have zero preference
cash. Shortfalls within a tier share by **dollar claim**, not shares. Rank zero is
allowed and precedes rank one. [Allocator](../../../src/ovf/waterfall.py#L104),
[rank validation](../../../src/ovf/core/types.py#L42).

**Residual stage.** Let `J(a)` contain positive-share common, converted preferred,
and nonconverted participating preferred. Common uses issued shares as its weight;
preferred uses `w_i`. A capped nonconverted participant has residual headroom
`h_i = max(0, cap_multiple_i × I_i - p_i)`; every other member has unlimited
headroom. With remaining cash `R`, the allocation is capped pro-rata water filling:

$$
x_i=\min(h_i,\lambda w_i),\qquad
\sum_{i\in J(a)}x_i=\min\!\left(R,\sum_{i\in J(a)}h_i\right),\qquad
u_i(a)=p_i+x_i.
$$

Choose a nonnegative `λ` satisfying the cash equation; the empty sum is zero.
Positions outside `J(a)` receive no residual. The cap includes the preference;
converting removes both the preference and the cap. Cash beyond finite aggregate
headroom is unallocated `U(a)`, so equity cash plus `U(a)` equals `E`.
Unallocated option capacity receives zero cash and supplies no residual weight.
[Cap handling](../../../src/ovf/waterfall.py#L119).

**Verification.** With the default dollar tolerance

$$
\varepsilon=10^{-8}+10^{-12}N,\qquad
g(a)=\max\left(0,\max_i[u_i(1-a_i,a_{-i})-u_i(a)]\right),
$$

the returned state satisfies `g(a) ≤ ε`, `U(a) ≤ ε`, and
`|sum(all cash payouts) - N| ≤ ε`. With no preferred positions use `g = 0`.
Call this an **ε-pure Nash equilibrium verified on floating-point payoffs**.
It is not an exact-arithmetic proof certificate. All binary switches are evaluated,
including switches into profiles that strand cash; feasibility is a separate final
filter, not a restriction on the deviation set.
[Tolerance and search](../../../src/ovf/waterfall.py#L262),
[reconciliation](../../../src/ovf/waterfall.py#L308).

The solver starts all positions unconverted, visits sorted security IDs, changes
an action only for an improvement exceeding `ε`, and checks every unilateral
deviation after each sweep. It retains the current action on a tie. Repeated sweep
states or budget exhaustion raise `WaterfallConvergenceError`; an unallocatable
terminal state raises `ValueError`. Finding a feasible equilibrium by enumeration
does not by itself guarantee this bounded search returns one.

## 2. Strategy uniqueness, payoff uniqueness, and cost

- **Strategy uniqueness:** exactly one feasible ε-equilibrium profile exists.
- **Payoff uniqueness:** feasible equilibria exist and their per-security cash
  vectors agree to the declared comparison tolerance. This can hold with several
  strategy profiles. State the result for the supplied table and exit.
- `payoff_unique` alone is insufficient: the implementation returns `True` even
  when `feasible_equilibria` is empty (`distinct_payoff_vectors == 0`). Check
  nonemptiness first. Its distinct-vector count uses greedy comparison against
  representative vectors; tolerance proximity is not transitive, so this is not an
  exact equivalence-class count or a guarantee that every pair differs by at most
  `ε`. [Implementation](../../../src/ovf/waterfall.py#L469).

For README purposes: **enumeration evaluates all `2**n` profiles and defaults to a
12-preferred-position limit**; solver iterations are a configurable search budget,
not a complexity theorem.

Implementation detail for technical documentation: let `m` be the number of equity
records and `A(m,n)` the cost of one fixed allocation. The current repeated tier
and cap scans admit a conservative `A = O(m(n+1))` bound. A completed solver sweep
uses `3n+1` fixed allocations; at most `s = max_iterations` sweeps cost
`O(s(3n+1)A)`, excluding one-time debt settlement. Enumeration stores
`O(2^n(m+n))` state data. Its allocation/deviation work is
`O(2^n(A+n^2))` because each neighbor tuple is rebuilt; comparing `K` feasible
payoffs with `d` representatives adds `O(mKd)`, potentially `O(m4^n)` in the worst
case. Do not present the entire implementation as exactly `O(n2^n)` or claim a
measured speed bound. [Loops](../../../src/ovf/waterfall.py#L447).

## 3. Recommended executable README example

Illustrative negotiated terms, not a historical company: founders hold 8M common;
Series A invested $5M for 2M shares, with a junior 1x participating preference capped
at 2x; Series B invested $9M for 1.5M shares, with senior 1x nonparticipating
preference. An optional 1M-share unallocated reserve illustrates ownership versus
cash entitlement. Both conversion ratios are one.

```python
import math
import equilibria as eq

ct = eq.CapTable()
ct.add(eq.common(8_000_000, holder_id="founders", security_id="common"))
ct.add(eq.preferred(
    2_000_000, 2.50, seniority=2, participating=True,
    participation_cap=2.0, holder_id="series_a", security_id="a",
))
ct.add(eq.preferred(
    1_500_000, 6.00, seniority=1, holder_id="series_b", security_id="b",
))
ct.add(eq.option_pool(1_000_000, holder_id="reserve", security_id="pool"))

report = ct.waterfall_detailed(60_000_000)
survey = eq.enumerate_equilibria(ct.securities, 60_000_000)
cash = {p.security_id: p.amount for p in report.payouts}
state = {p.security_id: p.converted for p in report.payouts
         if p.security_id in survey.positions}

assert cash == {"common": 40_800_000, "a": 10_200_000, "b": 9_000_000, "pool": 0}
assert ct.total_shares == ct.fully_diluted_shares == 12_500_000
assert report.converged and report.max_unilateral_gain <= report.tolerance
assert abs(math.fsum(cash.values()) - report.net_exit) <= 1e-6
assert survey.feasible_equilibria and state in survey.feasible_equilibria
assert len(survey.feasible_equilibria) == 1 and survey.payoff_unique
print(cash)

# At the conversion boundary, two strategies produce the same cash.
tie = eq.enumerate_equilibria(ct.securities, 59_000_000)
assert len(tie.feasible_equilibria) == 2
assert tie.distinct_payoff_vectors == 1
```

**At $60M:** B retains its $9M preference. A converts and receives
`2/10 × ($60M - $9M) = $10.2M`, beating its $10M cap. Founders receive $40.8M.
A reverting to preferred would lose $0.2M; B converting while A remains converted
would receive `1.5/11.5 × $60M ≈ $7.8261M`, below $9M. The reserve receives zero.
A owns 16% fully diluted but receives 17% of cash. The returned gain and conservation
error were both zero; the reported tolerance was `0.00006001` dollars.

Full fixed-profile matrix at $60M, entries **(A cash, B cash), $M**:

| A action / B action | B retains preferred | B converts |
|---|---:|---:|
| A retains preferred | (10, 9) | (10, 7.894737) |
| A converts | **(10.2, 9)** | (10.434783, 7.826087) |

All four profiles conserve cash; only the bold cell passes both unilateral checks.
The matrix was independently derived and executed through the fixed allocator.
At $59M the two feasible profiles pay founders $40M, A $10M, and B $9M.

For a plot of this same stack, verified breakpoints are **$9M, $14M, $39M, $59M,
$69M**: B's preference fills, A's preference fills, A reaches its participation
cap, A becomes indifferent to conversion, and B becomes indifferent to conversion.
For example A's cap binds at `5 + 0.2(V - 14) = 10`, hence `V = 39` in $M;
its conversion threshold is `0.2(V - 9) = 10`, hence `V = 59`.
Above $69M all issued equity shares in proceeds pro rata. The reserve affects none
of these cash thresholds. This example combines the mechanisms of
[F5a/F5b](../../../tests/fixtures.py#L137),
[F6/F7](../../../tests/fixtures.py#L160), and [F9](../../../tests/fixtures.py#L204).

## 4. What the available evidence actually reproduces

| Claim or artifact | Audit result and permitted wording |
|---|---|
| 400,000 float games / 139,094 multiple equilibria | Not reproducible from the supplied tree: no corresponding generator, seed, retained inputs, or result dataset found. |
| 250,880 adversarial float games / 76,612 multiple / five flagged cases | Same gap; the five alleged false positives and their explanations cannot be replayed. |
| 80,335 exact-rational games / 24,609 multiple | Same gap. The checked-in rational oracle is much smaller and narrower. |
| 45,462 solver successes, zero rational mismatches; 120,000 further games without cycles | No matching harness, logs, or datasets found. Not supported by the current stress tests. |
| README “roughly 730,000”, about 30%, unique payouts in every instance | The three reported counts sum to **731,215**, but overlap, rejected cases, and counting rules are unavailable. Do not relabel their sum as independently reproduced or distinct games. |
| Slow case found among 200,000 random tables; maximum three sweeps | The discovery count is only a comment. The saved four-position case reproducibly takes three sweeps; `max_iterations=1` fails. It establishes one case, not a maximum. |
| Small deterministic grid | Reproduced **128** table/exit combinations (`4 × 4 × 8`), all feasible, **50** with multiple profiles, all with one tolerance-grouped payoff vector. These are counts for this grid only. |
| Slow-case exit sweep and larger games | Reproduced **58** exits (`range(0,400,7)`) on one four-position table; all feasible and payoff-unique. The larger-game test covers three fixed tables with 5, 6, and 7 preferred positions at five exits each. |
| Rational oracle | Configured for **100 deterministic Hypothesis examples**, 1–3 preferred positions, positive common, integer terms, ratio 1, and cap `liquidation_multiple+1` when capped. It enumerates exact strategies and checks the solver's chosen state/cash; it does **not** compare the complete production enumeration set, assert exact payoff uniqueness, or cover zero-common knife edges and arbitrary ratios. |
| Named waterfall fixtures | **12** stored fixtures, with expected cash and conversion states and production enumeration checks. F3 reproducibly has two profiles with the same payoff. Review fields are empty; do not call them independently specialist-reviewed. |

Sources: [research counts](../../findings.md#results),
[README headline](../../../README.md#L81),
[saved slow case](../../../tests/test_conversion_stress.py#L17),
[grid](../../../tests/test_conversion_stress.py#L190),
[exact oracle](../../../tests/test_equilibrium_reference.py#L18),
[oracle assertions](../../../tests/test_equilibrium_reference.py#L65),
[fixture assertions](../../../tests/test_fixtures.py#L11),
[review status](../../fixtures.md#L8).

The independent rational allocator is valuable evidence, but production enumeration
and the main solver share `evaluate_fixed_waterfall`; agreement between those two
is not independent validation of allocation arithmetic. The claim that no prior
existence/uniqueness result was located is an unverified literature-search statement
in this review, not a basis for a novelty or market-first claim.

To restore the large counts: retain one documented command, fixed seeds and dependency
versions, generators and exact oracle, input/output hashes, explicit feasibility and
tolerance rules, denominators and exclusion counts, and the five flagged cases with
exact rechecks. Pin the source revision; generated games are not observed financings.

## 5. Corrections to resolve before publication

1. **Accounting promise differs from implementation.** [AGENTS.md](../../../AGENTS.md)
   requires absolute `1e-6` proceeds conservation. The engine uses
   `1e-8 + 1e-12 × net_exit`, which exceeds `1e-6` above $990,000; it reconciles to
   **net**, not gross, proceeds when transaction costs apply. This does not show an
   observed misallocation; it shows the advertised acceptance guarantee is stronger
   than the code. Fixture assertions using `pytest.approx(..., abs=1e-6)` also retain
   pytest's relative default unless `rel=0` is specified. Align the promise, check,
   and tests before saying every exit conserves within an absolute micro-dollar.

2. **Enumeration is not a general input validator.** It omits the solver's unsupported
   instrument and granted-option guards. Reproduced: common plus an unresolved SAFE
   yields a feasible, payoff-unique survey with zero SAFE cash, while `solve_waterfall`
   rejects the same input. Reproduced: `enumerate_equilibria([], 100)` gives no feasible
   profiles but `payoff_unique=True`. Use supported equity in the README and require
   nonempty feasible profiles; align the APIs before implying identical validation.
   [Solver guards](../../../src/ovf/waterfall.py#L253),
   [enumerator validation](../../../src/ovf/waterfall.py#L422).

3. **Scope documentation is behind current source.** Debt settlement and note accrual
   exist in [debt.py](../../../src/ovf/instruments/debt.py) and the lower-level waterfall
   API. The reviewed `CapTable.waterfall_detailed` wrapper does not expose `as_of`;
   neither the small rational oracle nor the large-count evidence verifies the expanded
   debt scope. Treat that integration as provisional for this review, not absent.
   [Anti-dilution](../../../src/ovf/antidilution.py) has an implemented, tested separate
   issuance adjustment; the caller constructs a new conversion-ratio snapshot.
   This does not constitute endogenous exit-triggered anti-dilution optimization.
   Blanket statements in [limitations](../../limitations.md) and
   [semantics](../../semantics.md) need refreshing against the final release tree.

4. **One fixture derivation uses the wrong counterfactual.** F8a's payout is correct,
   but its [explanation](../../fixtures.md#L77) compares both series with an
   all-converted gross-exit share. At $14M, A alone converting receives
   `2/10 × (14-9) = $1M`; B alone converting receives
   `1.5/9.5 × (14-5) ≈ $1.421053M`. Those are the unilateral deviations needed for
   the equilibrium argument. Use the worked matrix above to make this distinction clear.

## Verification performed

- Full available suite at the verification snapshot: **200 passed**. Command:
  `PYTHONDONTWRITEBYTECODE=1 HYPOTHESIS_STORAGE_DIRECTORY=/tmp/ovf-mathematical-review-hypothesis .venv/bin/pytest -p no:cacheprovider`.
- `ruff check --no-cache src tests`: passed. `mypy --cache-dir /tmp/ovf-mathematical-review-mypy src`:
  passed for 15 source files, with only an unused test-override configuration note.
- Executed the example at $59M/$60M, its four-profile payoff matrix, all five
  analytical breakpoints, the 128-instance grid, the 58-exit sweep, and the two API
  edge cases described above. No code or test files were edited.
- Other workers added files while this review ran, including debt tests; the 200-test
  result records that snapshot and is not a test count for a later frozen release.
