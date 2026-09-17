# Findings: the Option Pricing Method against a second implementation

**Evidence status, 2026-09-15.** Every count in this document was produced by
`tests/opm_oracle.py` from this checkout, with its command, generators and seeds stated
beside it. The large run is replayable with one command (see [Replaying](#replaying)), and it
took 471 s on 8 worker processes. Two sets of numbers **cannot be replayed from this
checkout**, and each is labelled where it appears:

- the D3 counts, which were measured before the coordinator fixed D3, and which the fix
  removes;
- one table in search 1, adversarial seed 1316, which the final run examined minutes before
  the D5 fix landed.

Smaller seeded versions of every search run in `tests/test_opm_validation.py` on every
`pytest`.

These are **empirical results on generated cap tables. None of them is a theorem.** They
say how far a second, independently written implementation agrees with `ovf.opm` on the
tables generated, and what it found where it did not.

Recorded against `ovf` 0.1.0-alpha on branch `feat/open-opm`: `opm-breakpoints-v1`
(`ovf.opm.breakpoints`), `opm-v1` (`ovf.opm.allocate`, `ovf.opm.blackscholes`),
`waterfall-v3` and `governance-v1`; Python 3.12.14, numpy 2.5.3, macOS.

## The question

`ovf.opm` makes three claims, and each can be wrong in a way its own invariants would not
see:

1. its breakpoint schedule is the cap table's payoff, derived from the engine;
2. its call-spread allocation is the expected discounted payoff under the lognormal model;
3. its refusals are the right ones: it refuses exactly the tables whose payoff the
   call-spread decomposition cannot represent, for the reason it states, and no others.

Each module tests itself against hand derivations, and worker A's breakpoints are checked
against the engine they are derived from. That is necessary and not sufficient, because a
shared misreading of the specification passes both. Only agreement with something written
independently, by a different route, survives a shared misreading.

## The second implementation

`tests/opm_oracle.py` imports nothing from `ovf.opm.breakpoints`, `ovf.opm.allocate` or
`ovf.opm.blackscholes`. It also imports nothing from the exact oracle of
`tests/test_governance.py` or from `tests/opm_breakpoint_fixtures.py`.
`test_the_oracle_shares_no_code_with_the_modules_under_test` parses the file and fails if
that changes. The search harness, which calls the modules under test, imports them inside
one function only. What the two implementations share is the specification: the waterfall
rule of [semantics](semantics.md), the two-stage sincere vote of [governance](governance.md)
and the lognormal model of [opm](opm.md).

| | `ovf.opm` | the oracle |
|---|---|---|
| Payoff at one exit | float engine, `solve_waterfall` / `resolve_collective_conversion` | its own exact game over `fractions.Fraction`: waterfall, all `2^n` profiles, unique equilibrium payoff, sincere vote |
| Breakpoints | analytic candidate families (preference levels, caps, conversion indifference, vote flips) in exact arithmetic, then probes of the float engine | no candidate family: the exact payoff is a black box. An interval that is not affine is split where the lines at its two ends meet, or at its midpoint |
| Governed payoff | vote-flip candidates from exact per-profile maps, then probes | two ungoverned black boxes (without and with the conversion). Each voting holder's gain is affine between their kinks, so its roots are found exactly; the outcome is read between roots |
| Value | Black-Scholes-Merton call spreads with an `erfc` normal CDF | 20-point Gauss-Legendre quadrature of the payoff against the lognormal density in the standard normal variable, split at every kink and step. No distribution function and no option value is evaluated |

**The oracle is checked before it is used as evidence.** It reproduces, exactly and without
tolerance, hand derivations made elsewhere and before it:

- BP1, BP3 and BP4 of [opm-breakpoints](opm-breakpoints.md): knots, weights, and the
  candidates (5M, 9M) that are not kinks.
- BP7, the README table:
  - without the term: 9M, 14M, 39M, 59M, 69M;
  - under the majority term: knots 207/19 M, 14M, 39M and 57.5M. The jumps are -144/19 M
    and +144/19 M at 207/19 M, and +1.5M and -1.5M at 57.5M. There is no negative weight.
- The isolated undefined point of `tests/test_opm_breakpoints.py`: one continuous tranche,
  weights 1/11, 8/11, 2/11.
- O1, O2 and O3 of [opm](opm.md), to the cent, by quadrature alone: Series A $5,605,633.58,
  $6,793,422.68 and $7,314,044.54. docs/opm.md derived these by hand and in 60-digit decimal
  arithmetic.

The quadrature integrates the density to within `4.4e-16` of one, and the discounted spot to
within `8.3e-15` relative, on every market in the grid. Those two errors are its own floor.

Every oracle schedule is also replayed against the float engine, which it was not derived
from. The probes are:

- 0.3, 0.5 and 0.7 of every tranche;
- 0.1 to 0.9 of the last tranche, out to twice the oracle's upper bound on the kinks;
- `1e-7` relative either side of every knot.

That third party is what settled the one disagreement described below. An earlier version
of the replay probed the last tranche only out to `2k + 1`. On a one-tranche schedule that
means only exits in [0, 1], which checks nothing. The coordinator's challenge on venture
seed 256 exposed this (see D3), and the numbers below use the widened probes.

## Generators

Both generators are in `tests/opm_oracle.py` and are seeded from the string
`"<generator>-<seed>"`. Every input is dyadic, so the engine's floats and the oracle's
fractions are the same numbers. Each table is examined twice: as generated, with its
collective-conversion term, and without the term.

**`adversarial_table(seed)`**, at small integer scale:

- 2 to 4 preferred positions of 100 to 1,000 shares at $1 to $6;
- multiples 1, 1.5 or 2;
- half participating, most of those capped at the multiple or up to 2x above it;
- conversion ratios 0.5 to 2;
- seniority 1 to 3, with collisions;
- common from none to 2,000 shares;
- one holder with two positions in 30% of tables, and an investor holding the common in 20%;
- a 6.25% simple loan ahead of everything in 20%, and an unallocated pool in 20%.

The term converts every preferred position (70%) or a random subset.

**`venture_table(seed)`**: 2 to 4 priced rounds in the usual shape, at the scale of a real
company.

- Founders hold 4 to 10 million common. There is employee common in 40% of tables and an
  unallocated pool in 60%.
- Each round sells 10% to 25% of post-money fully diluted shares.
- The first price is $0.25 to $1.00. Each later round is priced 1.5x to 4x the last, with a
  0.75x down round one round in ten.
- About four rounds in five are 1x non-participating. The rest are 1x participating (capped
  at 3x in most), 1.5x or 2x.
- Seniority is stacked (later senior) or pari passu, half each.
- In 30% of rounds an earlier lead also buys the new series.

The term converts all preferred.

**Terms, in both generators.** A Requisite Holders approval over all preferred: "more than
1/2", "at least 1/2", "at least 3/5" or "at least 2/3" (NVCA Model COI s.5.1(b);
[governance](governance.md)). In 30% of tables a series consent for one converted series is
added (NVCA fn 64).

**Market inputs.**

- The equity value is drawn per table, log-uniform between half the first breakpoint and
  twice the last (`pick_spot`).
- Search 2 uses 132 markets per table: 11 volatilities from 0.1% to 300%, 6 horizons from 1
  month to 10 years, and two rate pairs (4% with no yield; -1% with a 2% yield).
- Search 5 uses 60% volatility, 3 years and 4%.
- Search 6 uses three markets: (60%, 3 years, 4%), (30%, 1 year, 4%) and (100%, 5 years, 4%).

## Results

`python -m tests.opm_oracle --tables 2000 --workers 8`: seeds 0-1999 of each generator,
4,000 tables, each with and without its term.

| Search | Instances | What was searched | Found |
|---|---|---|---|
| 1. Two breakpoint derivations | 8,000 schedules; 7,733 derived by both, covering 36,009 breakpoints and 2,441 steps | count, position and weights of every breakpoint; position and jumps of every step; the `monotone` and `continuous` flags; the oracle replayed against the float engine at 218,744 exits | **0** count, position, weight, step or flag disagreements. Every breakpoint is equal as a float. Largest weight gap `7.1e-13`, largest jump gap `3.2e-8`, largest oracle-engine gap `2.4e-7` |
| 1a. Refusals | 267 schedules refused by `ovf.opm.breakpoints` | the refusal's stated reason against the exact vote | 266 are intervals on which the exact vote is undefined. 1 is D5 (adversarial 1316, examined before its fix; it derives correctly from this checkout) |
| 2. Call spreads against quadrature | 4,000 tables x 132 markets = 528,000 valuations; beyond the grid, 30 tables x 10 markets | every class value | Worst gap **`6.3e-15` of discounted equity value**. Worst gap relative to a class worth at least `1e-6` of equity value: `1.3e-10`. **No breakdown found** for total volatility from `2.9e-4` to `110` |
| 3. Value conservation | the same 528,000, plus 1,537 x 3 unchecked governed allocations | `abs(sum - S e^-qT) / S e^-qT` | Worst **`4.9e-16`**, measured and reported alike. The unchecked allocations of search 6 conserve value to `3.5e-16` too |
| 4. Deterministic limit | 4,000 tables x 11 volatilities (`1` to `1e-10`), off and on a breakpoint | value against the engine payout at S, with r = q = 0 | Off a breakpoint the error reaches its floor, **`1.85e-16` of S**, once S is 8 standard deviations from every breakpoint. On a breakpoint it equals the predicted kink option, ratio 1.00 for every volatility at or below `1e-3`. It is O(sigma), still `4e-11` of S at sigma = `1e-10` |
| 5. **How often the method applies** | 2,000 governed tables per generator, and the same 4,000 without the term | `opm_allocate` on its default path, against the oracle's verdict | **Venture: refused on 677 of 2,000, 33.9% (95% Wilson 31.8-36.0%).** Adversarial: 1,127 of 2,000, 56.4% (54.2-58.5%). **Without the term: 0 of 4,000.** No table was non-monotone without a step |
| 6. **The size of the error** | 677 venture and 860 adversarial stepped tables x 3 markets | what the call-spread construction reports with its checks removed, and what a vote-blind OPM reports, against quadrature of the true payoff | At (60%, 3y, 4%), venture: the largest class gap has **median 6.4% of equity value ($841k), p90 16.6% ($5.4M), max 22.7% ($34.4M)**, and median **30% of that class's value**. The vote-blind gaps are of the same order |

### Search 1 in detail: the one disagreement, and who was right

The first version of the oracle probed only the equilibrium payoff vector. On
`venture_table(5)` it reported 7 breakpoints where `ovf.opm.breakpoints` reported 9. The two
extra were at 142,341,750 and 148,082,250. Both were analytic candidates in worker A's
schedule: "the preference stack fills through seniority 4", and "series0 is indifferent
between holding and converting".

The float engine refereed. Between $140.9M and $148.1M the oracle's schedule differed from
`solve_waterfall` by **$1,129,545**, and worker A's schedule agreed with the engine. **The
oracle was wrong and worker A was right.**

The cause is a shape the oracle's probes could not see. `series0` is the most junior series,
1x non-participating, with $1,406,250 of preference behind $140,935,500 of senior
preferences. Its payoff has three phases:

- it rises with slope 1 as its preference fills, from $140.9M to $142.3M;
- it is flat at $1,406,250 while it holds;
- at $148.1M it converts onto the line `1875/9529 x (X - 140,935,500)`.

That last line is the one its converted payoff would have followed from $140.9M onwards. So
the whole payoff, every class, lies on the chord from $140.9M to the next kink at $183.8M,
except inside a bump one sixth of the interval wide. The oracle's five probes per interval
all landed outside the bump.

The oracle now tests the vector of every profile's allocation and stranded cash, not the
payoff alone (`ExactGame.extended`). A fixed-profile allocation changes regime in one
direction as the exit rises, so it cannot hide such a return. That is argued, not proven.
The payoff-only finder is kept as `blind_spot_probe`, to measure what it misses
(`--blind-spot 500 --tables 0`):

| Blind spot of probing the payoff alone (seeds 0-499 each) | adversarial | venture |
|---|---|---|
| Tables / kinks found by the full-vector finder | 500 / 2,567 | 500 / 2,495 |
| Kinks the payoff-only finder missed | **13, in 6 tables** (seeds 18, 60, 179, 272, 374, 490) | **2, in 1 table** (seed 5) |
| Knots it reported that are not kinks | 2 (seeds 18 and 490) | 0 |

Both spurious knots, 5,500 on seed 18 and 98400/11 on seed 490, have equal slopes on either
side in exact arithmetic. They are artefacts of the missed bumps.

**What this says about `ovf.opm.breakpoints`.** Worker A's verification probes the engine at
the same density, five points per interval, so verification alone would have had the same
blind spot. The analytic candidate families are what put knots at 142,341,750 and
148,082,250, so the probes never had to find them. Candidates and probes are not redundant:
each covers what the other cannot. Under *What this does not establish*,
[opm-breakpoints](opm-breakpoints.md) says that "a feature narrower than the probe spacing,
predicted by no family, could pass unseen". To a pure prober the bump is such a feature, and
on these tables it is common, not exotic. It is predicted by a family, and worker A's
schedule has it.

**Weights.** Worker A's weights are measured from float engine values, so they carry float
noise where the oracle's are exact. 397 of worker A's 7,733 compared schedules contain a
weight in `[-9.1e-15, 0)` where the exact weight is zero. The most negative weight observed
was `-9.09e-15`, on adversarial seed 55 under its term. `ovf.opm.allocate` refuses a weight
below `-1e-12`, which leaves 110x of headroom on these tables. See D4 for the documentation
that said otherwise.

### Search 2: where call spreads and quadrature part

They did not part anywhere searched. By total volatility `sigma * sqrt(T)`, over 4,000 tables:

| `sigma sqrt(T)` | cells | worst gap / discounted equity value | worst gap / class value (classes >= `1e-6` of S) |
|---|---|---|---|
| below 0.01 | 64,000 | `3.4e-15` | `1.4e-11` |
| 0.01-0.1 | 88,000 | `3.2e-15` | `1.0e-12` |
| 0.1-0.5 | 112,000 | `2.6e-15` | `4.1e-13` |
| 0.5-1 | 72,000 | `2.5e-15` | `1.8e-13` |
| 1-2 | 72,000 | `2.2e-15` | `2.2e-13` |
| 2-4 | 72,000 | `2.3e-15` | `1.2e-13` |
| 4-9.5 | 48,000 | `6.3e-15` | `1.3e-10` |

Beyond the grid (`--extreme 15 --tables 0`: 15 tables of each generator, volatilities 3 to
20, horizons 10 and 30 years), the gap grows from `2e-15` of S at total volatility 9.5 to
`5e-13` at 110. There it equals the quadrature's own error on the discounted spot
(`8.7e-13` at most) and tracks it at every total volatility, so the growth is the oracle's, not the call spread's.

The class-relative figures are largest for classes worth little: an absolute error of a few
`1e-16` of S is a large fraction of a class worth `1e-6` of S. So the practical answer is
that on every market tried the two routes agree to float rounding of the equity value. The
only breakdown found in the call routine was D1, an input outside the grid.

### Search 4: the deterministic limit, in standard deviations

With r = q = 0 and T = 1, the OPM value of a class should converge to its engine payout at
X = S as sigma falls. Off a breakpoint the error depends on `d`, the log distance from S to
the nearest breakpoint divided by sigma, and falls like a normal tail:

| `d` (standard deviations to the nearest breakpoint) | instances | worst error / S |
|---|---|---|
| below 1 | 4,911 | 0.35 |
| 1-2 | 949 | 0.13 |
| 2-4 | 1,236 | `8.7e-4` |
| 4-6 | 963 | `7.6e-7` |
| 6-8 | 459 | `2.1e-11` |
| 8-10 | 390 | `1.6e-16` |
| 10 and above | 35,092 | **`1.85e-16`** |

The floor is float rounding: `1.85e-16` of S against the exact payout, and `1.81e-16`
against the engine. The engine's own disagreement with the exact payout is below that here.

On a breakpoint the payoff bends at S, and the value exceeds the payout by the kink option
`dw x S x (2 N(sigma / 2) - 1)` of [opm](opm.md), where `dw` is the class's change of
weight. Measured against that prediction:

- the ratio is 1.00 at every volatility from `1e-3` down to `1e-10`;
- it is 1.00 in median and at most 1.03 at `1e-2`;
- it drifts at `1e-1` and above, where the other breakpoints begin to count.

Down to sigma = `1e-10` the error is O(sigma), `4.0e-11` of S, with no floor yet. A floor
would appear only where the kink option falls below one float spacing of S, near sigma =
`1e-15`. 3 adversarial tables have no breakpoint at all, and 69 of the other 3,997 on-breakpoint
equity values are the float nearest a non-dyadic breakpoint, which is not a knot of the
exact schedule; those are left out of the ratio.

### Search 5: how often the method applies

This is the module's headline number, and it is not rare.

| | Venture generator | Adversarial generator |
|---|---|---|
| Tables with the term | 2,000 | 2,000 |
| OPM applies | 1,323 (66.1%) | 873 (43.6%) |
| **Refused** | **677 (33.9%, 95% Wilson 31.8-36.0%)** | **1,127 (56.4%, 54.2-58.5%)** |
| of which: the payoff steps | 677 | 860 (861 from this checkout, see 1a) |
| of which: the vote is undefined on an interval | 0 | 266 (267 in the run, see 1a) |
| of which: a negative weight with no step | **0** | **0** |
| Steps recorded | 996 | 1,445 |
| The same tables without the term: refused | **0 of 2,000** | **0 of 2,000** |

Across the 4,000 tables without the term, refused 0 times: 95% Wilson interval 0 to 0.096%.

**The contract's expected symptom never occurred.** docs/opm-contract.md first expected the
failure to be negative call-spread weights. In all 7,734 oracle schedules (8,000 less the
266 intervals of undefined vote) the oracle found no negative weight at all: not in a stepped table, not anywhere. Every non-monotone table
was non-monotone because its payoff steps. That is worker A's BP7 finding, now observed on
every table searched rather than one.

**Which venture tables step.** The rate by structure, from the same 2,000 tables (the
columns overlap):

| Venture tables | n | steps |
|---|---|---|
| 2 series | 652 | 14.7% |
| 3 series | 674 | 38.0% |
| 4 series | 674 | 48.2% |
| Every series 1x non-participating | 1,064 | 32.6% |
| Some other term present | 936 | 35.3% |
| Stacked seniority | 1,010 | 36.7% |
| Pari passu | 990 | 30.9% |
| "more than 1/2" | 521 | 41.5% |
| "at least 1/2" | 470 | 41.9% |
| "at least 3/5" | 507 | 28.8% |
| "at least 2/3" | 502 | 23.5% |
| With a fn 64 series consent | 593 | 25.1% |
| Without one | 1,407 | 37.5% |

The rate climbs with the number of series. It falls as the threshold rises, and it falls
when a series consent is added. It is a third of the plainest tables, where every series is
1x non-participating. These are rates over one generator's choices, not estimates about real
charters.

### Search 6: the size of the error the refusal prevents

On every table where the oracle finds a step and worker A's schedule derives, three numbers
are compared.

- **The truth.** Quadrature of the true governed payoff, steps included. It is the
  defensible value inside the model: the lognormal expectation of what the vote model pays.
- **The unchecked construction.** `opm_allocate` on worker A's governed schedule, with its
  continuity and monotonicity checks removed (`checks_disabled`). This is what the module
  would print if it did not refuse.
- **The vote-blind standard.** `opm_allocate` on the same table without the term. That is a
  standard OPM from a breakpoint table that ignores the charter's mandatory-conversion vote.

The unchecked construction drops the steps and keeps the affine pieces. By construction it
therefore misses the true value by minus the digital value of every step: `-sum over steps
of jump x exp(-rT) P(X_T >= step)`. The search confirms that to within `2.3e-15` of S on every
table. **Its values still sum to the discounted equity value to `3.5e-16`**, because the
jumps sum to zero across classes. It is a well-formed allocation that no invariant inside
the option arithmetic can tell from a right one.

Largest gap over the classes of each table, against the truth:

| Venture, 677 tables | (60%, 3y) | (30%, 1y) | (100%, 5y) |
|---|---|---|---|
| Unchecked, $ (median / p90 / max) | $841k / $5.43M / $34.4M | $892k / $8.07M / $66.2M | $331k / $2.10M / $13.3M |
| Unchecked, % of equity value | 6.4 / 16.6 / 22.7 | 6.4 / 28.8 / 48.2 | 2.7 / 6.2 / 9.6 |
| Unchecked, % of that class's value (classes >= 1% of S) | 30 / 66 / 89 | 36 / 122 / 2,110 | 15 / 36 / 56 |
| Vote-blind, % of equity value | 4.2 / 29.2 / 48.6 | 3.4 / 46.6 / 86.6 | 2.1 / 12.0 / 20.4 |
| Vote-blind, % of that class's value | 18 / 122 / 379 | 21 / 165 / 745 | 11 / 69 / 157 |

| Adversarial, 860 tables | (60%, 3y) | (30%, 1y) | (100%, 5y) |
|---|---|---|---|
| Unchecked, % of equity value (median / p90 / max) | 3.5 / 11.6 / 22.5 | 3.0 / 18.5 / 42.0 | 1.7 / 4.9 / 11.7 |
| Unchecked, % of that class's value | 28 / 68 / 286 | 24 / 113 / 1,930 | 12 / 37 / 93 |
| Vote-blind, % of equity value | 3.8 / 20.6 / 54.1 | 2.2 / 32.3 / 88.1 | 2.2 / 8.8 / 31.4 |

The gap is not small. In the median stepped venture table, the number the unchecked method
would print for the most affected class is off by about 6% of the whole company, and by a
third of that class's own value. At low volatility a step near the equity value dominates,
and the gap exceeds the class's entire value in a tenth of tables. **That is the argument
for the refusal existing:** on a third of these tables the arithmetic prints a
conservation-exact number that is wrong by tens of percent. Nothing inside it would say so.

Ignoring the vote is no safer: the vote-blind standard misses by the same order. Both
numbers are "defensible" only relative to different models of the charter. This search does
not say which charter model is right. It says that the choice moves value by this much.

**A step does not make the value undefined.** A call spread is continuous, so no finite
portfolio of call spreads is a step: the contract's claim is right pointwise. But a narrow
call spread with a steep weight converges to the step's value as its width shrinks. So the
expectation of a stepped payoff is well defined and computable, here to `1e-15` by
quadrature, and it can be approximated arbitrarily well by call spreads if negative and
unbounded weights are allowed. What fails on a stepped table is therefore the allocation,
not the value. A share of the marginal dollar cannot be negative or infinite, so the
call-spread weights stop being a split of equity value. The refusal is right. Its reason is
that decomposition, not that no number exists; a caller who wants the number has one route
here, integration of the true payoff.

## Scale: where the default tolerance stops working

`breakpoint_schedule` replays the engine to an absolute `atol = 1e-6`, and `opm_allocate`
derives its schedule with that default. The limit is stated in
[opm-breakpoints](opm-breakpoints.md); above it the default path refuses. It was measured
with `--scale 150 --tables 0`: venture seeds 0-149, with every share count and principal
multiplied by a factor and prices unchanged, so every breakpoint scales exactly.

| Factor | Largest breakpoint | Default path refused |
|---|---|---|
| x1 | $2.8M-$789M | 0 / 150 |
| x3 | $8.3M-$2.4B | 0 / 150 |
| x10 | $28M-$7.9B | 1 / 150 |
| x30 | $83M-$24B | 13 / 150 |
| x100 | $278M-$79B | 36 / 150 |
| x300 | $833M-$237B | 82 / 150 |
| x1000 | $2.8B-$789B | 136 / 150 |

By the table's largest breakpoint:

- 0 of 518 refused below $1e9;
- 36 of 296 refused in [$1e9, $1e10);
- 189 of 193 refused in [$1e10, $1e11);
- 43 of 43 refused above $1e11.

The smallest largest-breakpoint refused was $4.78e9, and the largest accepted was $1.38e10.
At x1 the largest replay error was `1.19e-7`, one ninth of `atol`.

All 268 refusals come from float spacing, not from the table, and they take three forms:

- **223** read, for example, `the interval [20047096582.029808, 20047096582.029896] cannot be
  verified: it deviates from a line by 1.90735e-06 and is too narrow to split, but its ends
  differ by only 4.00543e-05, which is within the engine's own tie tolerance (0.2) or its
  width; neither a kink nor a step explains it`.
- **44** are `gave up after 400 interval splits ...` or `the schedule does not replay the
  engine ...`. On the README table the first reads, at x300, `[10912500000.0,
  10961718750.0] still deviates from a line by 9.54e-07, above the construction tolerance
  5e-07`. The second reads, at x1000, `at X = 111644345223.74275 it pays common
  77665631459.99496 where the engine pays 77665631459.99495, a gap of 1.52588e-05`.
- **1 gives a false reason.** Take `venture_table(97)` without its term, with shares x300.
  It is an ungoverned table, and the oracle finds it continuous and monotone. Worker A's
  schedule nonetheless records a `Discontinuity` at X = 5,877,900,000, an exact candidate
  where `series1` converts, with a jump of -$0.000001 to common. That is float rounding at
  5.9e9, where one float spacing is 9.5e-7, and it lies above the construction tolerance of
  5e-7. `opm_allocate` then refuses: "Payoff is not continuous ... no combination of call
  spreads ... reproduces a step". No wrong number is returned, but the stated reason is
  false.

This is an interface gap, not a defect of either module. Worker A states the `atol` limit,
and worker B's allocation could not be asked for a different one. The coordinator is adding
an `atol` passthrough to `opm_allocate`, and the limit is recorded in
[limitations](limitations.md). A tolerance relative to the exit, rather than absolute, would
remove it. None of this touches searches 1 to 6, where every generated table has its largest
breakpoint below $1e9.

## Defects found in the modules under test

All five were reported to the coordinator with the reproducing input and were not fixed
here. The coordinator reproduced each one and fixed it in the owner's file during this work.
`tests/test_opm_validation.py` asserts the correct behaviour of every one as a plain test;
none is an `xfail`. Each was found by running the modules on inputs their own authors did
not generate.

**D1 (`ovf.opm.blackscholes.call_value`).**
- *Input:* `call_value(2.0, 1.0, 1e-300, 1e-60, 0.0)`.
- *Behaviour:* it raised `ZeroDivisionError`. `sigma * sqrt(T)` underflows to `0.0`, but
  only `time == 0` and `volatility == 0` were special-cased. The limits table of [opm](opm.md)
  says this case returns the discounted intrinsic value, here 1.0.
- *Reach:* through `opm_allocate`, because `OpmInputs` accepts `volatility=1e-300`.
- *Test:* `test_call_value_when_total_volatility_underflows_is_the_discounted_intrinsic`.

**D2 (`ovf.opm.allocate`, the replay at the equity value).**
- *Input:* the table of
  `tests/test_opm_breakpoints.py::test_an_isolated_undefined_point_is_recorded_not_refused`,
  with `opm_allocate(..., equity_value=2200.0, collective_conversion=term)`.
- *Behaviour:* it raised `ovf.governance.GovernanceIndeterminateError`, which is not an
  `OpmError`. The schedule is continuous and monotone, and 2,199 and 2,201 allocate normally.
  The replay check asked the engine to price the one exit where the vote is tied.
- *Test:* `test_allocation_at_an_isolated_undefined_vote_point_matches_its_neighbours`. It
  also holds the value to the quadrature within `1e-9`.

**D3 (`ovf.opm.breakpoints`, the origin probe, with `ovf.governance`'s absolute tolerance).**
- *Input:* `venture_table(256)` under its term.
- *Behaviour:* the table was refused with `ovf.governance refuses to price an exit of 1e-06,
  where no voting holder's gain from the conversion changes sign or touches zero`.
- *What is true:* the vote carries below about $14M. Above that it is moot, because every
  series converts in the per-position game anyway, so the engine reports `approved=False`
  with `changes_payout=False`. The governed payoff is one line, and the engine sits on it at
  every exit tried, within `3.7e-9`.
- *Cause:* the origin probe was floored at `1e-6 x max(x, 1)`, an absolute `1e-6`. There
  fund0's exact gain is `3.2e-9`, inside the engine's absolute tie band of `1e-8`. The fix
  scales the probe with the interval width.
- *Counts, measured before the fix and not replayable from this checkout:*
  - 20 tables (12 of 2,000 governed venture, 8 of 1,997 adversarial) were refused this way
    although the exact vote is determined.
  - 7 of the 20 (venture 256, 315, 586, 1343, 1506 and 1804, and adversarial 437) are
    continuous and monotone, so OPM should have applied.
  - The remaining 13 step, so they were refused anyway, but for the wrong reason.
  - Adversarial 1316, reported to the coordinator alongside these, is D5, not D3.
  - After the fix: 0.
- *Test:* `test_a_governed_table_is_not_refused_for_its_origin_probe`.

**D4 (docs/opm.md, documentation only).** The sentence "Worker A snaps `|w| < 1e-12` to
exactly zero" was false. `ovf.opm.breakpoints` does not snap weights. The measured noise is
given under search 1: 397 schedules, the worst weight `-9.09e-15`, 110x inside the
allocation's `-1e-12` floor. The coordinator is correcting the sentence and says the
instruction it describes was relayed but never implemented.

**D5 (`ovf.opm.breakpoints`, a descriptive probe).**
- *Input:* `adversarial_table(1316)` under its term.
- *Behaviour:* the table was refused with `ovf.governance refuses to price an exit of
  7600.0, where no voting holder's gain from the conversion changes sign or touches zero`.
- *What is true:* in exact arithmetic h0's and h3's gains both cross zero at 7,600, so the
  vote is undefined at that one exit and fails on either side of it.
- *Cause:* worker A's candidates correctly list 7,600 as a vote-flip knot and correctly drop
  it, because the map does not bend there. Then `breakpoints.py:934`, `mid = engine(knot.x +
  width / 2)`, landed exactly on it. That probe exists only to write the `basis` text of the
  tranche [5,200, 10,000).
- *Masked outcome:* this table also steps at 15,200 and 49400/3, so the method is refused
  anyway and the outcome happens to be right. But the same probe, on a table whose only tie
  is a tranche midpoint, would refuse a continuous, priceable table with a false reason.
  **A defect masked by an unrelated correct refusal is still a defect.** It was visible only
  because the reason was checked against the exact vote, not just the verdict. That is the
  case for asserting error messages, not only exit codes.
- *Test:* `test_a_tranche_midpoint_on_an_isolated_tie_does_not_refuse_the_schedule`.

**D2, D3 and D5 are one family.** In each, a probe chosen for the derivation's own
convenience landed on a point where `ovf.governance` legitimately declines to call a tied
vote:

- the replay at the equity value (D2);
- the origin probe (D3);
- a descriptive midpoint (D5).

In each, the calling code then treated the engine's honest refusal as a property of the
table. The fix is the same in spirit each time: the probe moves or tolerates the tie, and
the table is not blamed. That is a finding about how `ovf.opm` and `ovf.governance` meet. A
governed payoff has isolated exits at which it is undefined, and any code that probes it
must expect to land on one.

**None of these fixes can move a number in searches 2 to 6.**
- D1: the smallest total volatility searched is `1e-10`, far from underflow.
- D2: an equity value drawn from a continuous distribution lands on an isolated tie with
  probability zero.
- D3 and D5 change only which governed tables derive, and the counts above are from after
  the D3 fix.
- D4 is documentation only.

## Replaying

```bash
.venv/bin/python -m pytest tests/test_opm_validation.py              # seeded subsets, ~30 s
.venv/bin/python -m tests.opm_oracle --tables 2000 --workers 8       # searches 1-6, ~8 min
.venv/bin/python -m tests.opm_oracle --tables 0 --scale 150          # scale
.venv/bin/python -m tests.opm_oracle --tables 0 --blind-spot 500     # payoff-only probing
.venv/bin/python -m tests.opm_oracle --tables 0 --extreme 15         # search 2 beyond its grid
```

Add `--json PATH` to keep every per-table record. Every crash or oracle failure is printed
with its generator and seed, and `venture_table(seed)` or `adversarial_table(seed)`
rebuilds the table. The full run prints the tables above. Replayed from this checkout, it
should differ from them in exactly one place: adversarial seed 1316, which now derives.

## What this does not establish

- **No proof.** Agreement on generated tables is evidence about those tables. It does not
  show any of the following:
  - that `ovf.opm.breakpoints` finds every kink of every table;
  - that the call-spread sum equals the lognormal expectation for every schedule;
  - that the refusals are exactly right in general.
  A counterexample outside the generated families would contradict nothing above.
- **The oracle is finite too.** It accepts an interval as affine after seven exact probes of
  a long vector. Its first version missed a bump that a pure prober cannot see, and the
  argument that the full vector cannot hide one is an argument, not a proof. Its replay
  against the engine was itself too weak on one-tranche schedules until the coordinator's
  question exposed it. What makes the agreement evidence is that it was checked against a
  third party, the float engine, and that the two derivations fail in different ways.
- **The specification is shared.** Both implementations read the same
  [semantics](semantics.md) and [governance](governance.md). A misreading that both made
  would not show up here. Examples would be pari-passu sharing by preference rather than by
  shares, sincere voting by holder rather than by position, or right-continuity at a step.
  The vote model itself, its sincere voting and its one term per exit are assumptions of
  [governance](governance.md), not facts about holders. Searches 5 and 6 inherit all of
  them.
- **Coverage is the generators'.** At most 4 preferred positions. At most one loan, with a
  single dyadic rate. No dividends, no anti-dilution adjustments, no SAFEs or notes, no
  allocated options, and no several-term votes. Tables whose largest breakpoint is above
  $1e9 appear only in the scale search.
- **Generated tables are not real tables.** `venture_table` has the shape of a financing
  history, but its parameters were chosen, not sampled from observed financings. The 33.9%
  of search 5 is a frequency over this generator. It is not an estimate of how often real
  charters make a payoff step; that would need real cap tables and real terms.
- **Nothing here says the lognormal model, a volatility or a horizon is appropriate.** The
  searches check the arithmetic of the model, not the model.
- **The defensible value in search 6 is defensible only inside the model.** It is the
  lognormal expectation of the payoff the vote model produces. It is not a fair value, a 409A
  value, or an assertion that holders would vote as modelled.
