# Findings: the conversion game

**Evidence status, 2026-09-15:** the large experiment counts below are historical
research notes. Their generators, seeds, retained inputs and output logs are absent
from this checkout, so the counts and claimed re-verification have **not been
independently reproduced**. They must not be cited as established repository results.
See the [mathematical review](github-launch/reviews/mathematical-review.md) for the
claim-by-claim audit. The checked-in stress tests and exact-rational oracle provide
replayable evidence for their own specified families, not for the larger counts.

The original notes state: recorded 2026-09-15 against engine `waterfall-v2`,
re-verified unchanged under `waterfall-v3`. They describe **empirical results from
exhaustive enumeration on generated cap tables**. They are not theorems. They are
reported because the literature states the corresponding property as an observation
rather than a result, and because a reader deserves to know exactly how far the
evidence reaches.

## The question

At an exit, every convertible preferred position chooses between taking its
liquidation preference and converting to common. One position's choice changes what
the others receive, so the choices are simultaneous: a fixed point, not a sort.

Gornall and Strebulaev (2020, *Journal of Financial Economics* 135(1), 120–143)
describe the same computation and report their iteration's behaviour as an
observation on their sample:

> "As the first step in the payoff calculation, we assume that all shareholders
> convert their shares… Then we iterate through each class of shares that can choose
> whether or not to convert, checking whether they would optimally choose not to
> convert. If they choose not to convert, we recalculate all of the payoffs and
> restart this step. For all of the companies we consider, this process converges to
> a Nash equilibrium."

No published existence, uniqueness, iteration-order or complexity result for this
game was located while surveying the literature for this project. That is a gap in
the record, not a claim that none exists.

Two questions matter for a calculator:

1. **Is the answer determinate?** If several equilibria pay different amounts, then
   "who gets what" is not defined by the contract terms alone, and any single number
   a tool prints is a choice it made silently.
2. **Does the search find one?** Best-response iteration can cycle in general games.

## Method

`ovf.enumerate_equilibria` evaluates all `2**n` conversion profiles and keeps every
profile in which no single position gains by switching. A profile is **feasible**
when it allocates the whole net exit; profiles that strand cash are excluded, because
`solve_waterfall` rejects them.

Two independent allocators were used. The production primitive
(`evaluate_fixed_waterfall`, iterative cap handling) and a separately written
exact-rational allocator (water-filling over `fractions.Fraction`, no floating point).
Agreement between them is part of the evidence; a shared bug would defeat it.

Search inputs were randomly generated and deliberately adversarial: zero-common cap
tables, identical classes, participation caps set exactly at a liquidation multiple,
seniority collisions, and exit values placed exactly on candidate breakpoints
(cumulative preference levels, conversion indifference points, cap-exhaustion points)
and at ±0.001 around them.

## Historical reported results — not reproduced

| Search | Instances | Multiple equilibria | Distinct equilibrium payoff vectors |
|---|---|---|---|
| Random tables, 2–4 positions, float | 400,000 | 139,094 | **0** |
| Adversarial knife-edge exits, float | 250,880 | 76,612 | 5, all explained below |
| Adversarial knife-edge exits, **exact rational** | 80,335 | 24,609 | **0** |

The five float-flagged cases did not survive inspection. Four differed by ~1e-7 on an
exact indifference point, which is floating-point noise around a tie. The fifth arose
from counting profiles that leave cash unallocated, which the solver rejects; with the
feasibility filter applied it disappears. Under exact rational arithmetic none remain.

**Solver behaviour**, over adversarially generated tables with 3–7 preferred positions:

| Property | Result |
|---|---|
| Instances with at least one feasible equilibrium | 45,462 |
| Instances where `solve_waterfall` returned a result | 45,462 |
| Payout mismatches against the exact-rational allocator | 0 |
| Best-response cycles observed (120,000 further games) | 0 |
| Iteration budget exhausted | 0 |
| Maximum sweeps required | **3** |

## Interpretation claimed by the historical notes

The following interpretation is conditional on recovering and verifying the missing
experiment artifacts; it is not a conclusion established by the checked-in tests.

- **Multiple equilibrium profiles are ordinary, not pathological.** Roughly 30% of
  generated instances have more than one. The usual cause is indifference: a position
  that receives nothing either way, or one deep enough in the money that the choice
  does not change its cash.
- **In every instance enumerated, the equilibrium payoff vector was unique.** The
  cash answer was determinate even where the strategy profile was not. This is the
  property a calculator needs; it is also the weaker and more useful claim.
- **The best-response search was reliable on these inputs** and terminated within
  three sweeps in every case, which is why `max_iterations` defaults to 20 rather
  than to a large number.

## What this does not support

- **No proof.** Nothing here establishes existence, uniqueness of payoffs, or
  convergence in general. A counterexample outside the generated families would not
  contradict any statement above.
- **Coverage is limited to the implemented scope**: common, preferred with integer
  seniority, pari-passu sharing within a tier, participation with caps and conversion
  ratios. Accrued dividends, anti-dilution adjustment at exit, management carve-outs,
  debt, class voting and coordinated holders are not modelled, and each of them can
  change the game. See [semantics](semantics.md) and [limitations](limitations.md).
- **Positions, not owners.** Each preferred record is an independent player. A holder
  controlling several positions could coordinate them, which is a different game.
  `WaterfallResult.multi_position_holders` discloses when that situation exists in an
  input; it does not model it.
- **Generated tables are not real tables.** Share counts, prices and terms were drawn
  from small ranges chosen to stress the solver, not sampled from observed financings.

## Replaying the checked-in examples

```python
import ovf

securities = [
    ovf.common(8_000_000, holder_id="founders", security_id="common"),
    ovf.preferred(2_000_000, 2.50, participating=True, participation_cap=2.0,
                  holder_id="a", security_id="a"),
]
survey = ovf.enumerate_equilibria(securities, 50_000_000)
print(len(survey.feasible_equilibria), survey.payoff_unique)
```

`python -m ovf equilibria --demo F3` shows the smallest case with two profiles and one
payout. `tests/test_conversion_stress.py` and `tests/test_equilibrium_reference.py`
check their specified test families. These commands do not reproduce the large
historical searches above. The [README example](../README.md) has a separate
[reproduction script](github-launch/reproduce_example.py), including exact profile
checks and a 1,001-point comparison with hand-derived cash curves.

## Under a collective-conversion vote

`ovf.governance` adds a Requisite Holders mandatory conversion, which changes the strategy
space: holders vote, and an approved vote forces named positions to convert. The searches in
[governance](governance.md) re-ran the question over that space.

| Property | Result |
|---|---|
| Vote instances enumerated exactly | 252,039 |
| Per-series (constraint-model) instances | 218,331 |
| Second equilibrium payoff found | **0** |
| Unexplained float-engine mismatch against the exact oracle | **0** |
| Before/after snapshots byte-identical without a governance term | 12,379 |
| **Tables where some position's cash FELL as the exit rose, with the term** | **1,246 of 3,000** |
| The same, without the term | **0** |

The last row is a new property, not a regression. A higher exit can flip the vote: once
forced conversion becomes attractive to the majority, a dissenting series loses its
preference, so its cash falls even though the company sold for more. That is the Omneon and
Greenmont fact pattern, and it means **payout monotonicity in the exit value does not
survive the vote**, though it holds for the per-position game.

## Fund performance: a published illustration with two IRR roots

Recorded 2026-09-15 against engine `pme-v1`; replayable as fixture PME-F12
(`tests/pme_fixtures.py`, derivation in [pme-fixtures](pme-fixtures.md)) and by
`examples/pme_walkthrough.py`. Unlike the historical counts above, this is checked-in and
reproducible.

Gredil, Griffiths & Stucke's 2014 draft ("Benchmarking private equity: the direct alpha
method", Exhibits 5–6) is the one published worked example of KS-PME and Direct Alpha this
project could read. With its displayed inputs taken as exact, the engine and an
independent 60-digit oracle agree with every displayed figure (TVPI 2.00, KS-PME 1.67,
IRR 17.5%, Direct Alpha 12.6%). They also find two things the illustration does not show:

1. **The Long–Nickels ICM series has two IRR roots**, −27.26% and +5.97%. The paper
   displays 6.0% as the ICM rate. A guess-driven solver (Excel's `XIRR` starts at 10%)
   lands on the positive root and reports it as *the* IRR; the certified policy in
   [pme](pme.md#certified-irr-root-policy) reports status `"multiple"` and no spread.
2. **The ICM index position goes short on 2007-12-31** (−22.87) and stays short — the
   pathology Long & Nickels describe in their own footnote 5 — inside the illustration
   used to motivate the alternatives.

Neither changes the paper's Direct Alpha, which has one root here. Both show why a
performance library should report every root and every pathology rather than one number.

## Open items

- A supermodularity argument (or a counterexample) for the conversion game, which
  would replace the first result with a proof or bound its scope.
- ~~Whether payoff uniqueness survives accrued dividends~~ — **answered**, and by a
  stronger route than the search this document uses. `docs/dividends.md` proves
  Proposition 1: a dividend-bearing table is *exactly the same game* as a dividend-free
  twin (under forfeit, liquidation multiple `m + d` with `d = accrued/invested`, the cap
  clamping at `min(m+d, c)` inside or becoming `c + d` outside; under paid-in-kind, the
  same table with `shares x (1 + d)`). Uniqueness therefore does not merely survive
  testing, it follows from the existing result over a transformed parameter range. The
  accompanying exact search — 878,746 instances — found 0 twin mismatches and 0 distinct
  exact payoff vectors. 428 float flags were all tolerance epsilon-equilibria, and the
  dividend-free twin showed the identical flag every time, so none is caused by dividends.
- Whether payoff uniqueness survives exit-triggered anti-dilution. Still open, but note
  that `ovf.financing` adjusts conversion ratios *before* an exit rather than during one,
  so an adjusted table is an ordinary table to this engine.
- An owner-level game for holders with positions in several classes.
