# The Option Pricing Method: call values and allocation

Status 2026-09-15, engine `opm-v1`, modules `ovf.opm.blackscholes` and `ovf.opm.allocate`.
Every expected number below is derived by hand here, then asserted in
`tests/test_opm_blackscholes.py` and `tests/test_opm_allocate.py`. Each call value was
recomputed three independent ways before being written down (see
[Independent recomputation](#independent-recomputation)), and every breakpoint and weight with
`fractions.Fraction`.

**Review status: source-derived, not yet independently reviewed.**

**No third-party worked example was reproduced.** The fixtures O1-O3 are derived in this
document. None is taken from the AICPA guide or from any other publication, and none is
claimed to match one.

## What is implemented

| Part | Function | What it does |
|---|---|---|
| Call value | `call_value(spot, strike, volatility, time, risk_free_rate, dividend_yield=0.0)` | Black-Scholes-Merton value of a European call, limits taken exactly |
| Normal CDF | `normal_cdf(x)` | `erfc(-x / sqrt(2)) / 2` |
| Allocation | `opm_allocate(securities, *, inputs, as_of=None, schedule=None, collective_conversion=None)` | Checks the breakpoint schedule, then values each position as weighted call spreads, or refuses |

`opm_allocate` takes its breakpoints from `ovf.opm.breakpoints.breakpoint_schedule` (worker A)
unless a schedule is passed. A passed schedule gets the same checks as a derived one.

## Sources

- **The method.** AICPA, Accounting and Valuation Guide, *Valuation of Privately-Held-Company
  Equity Securities Issued as Compensation*. The guide describes the Option Pricing Method:
  total equity value treated as the underlying of a set of call options, struck at the
  breakpoints of the cap table. **No edition, page or paragraph of the guide was consulted
  while writing this module,** so none is cited, and no year is given for it. The formula
  below is the construction the guide names, implemented as published: nothing is calibrated,
  adjusted or added to it. **No conformance with the guide, or with 409A practice, is
  claimed.**
- **The call value.** Black, F. and Scholes, M. (1973), "The Pricing of Options and Corporate
  Liabilities", *Journal of Political Economy* 81(3), 637-654. Merton, R. C. (1973), "Theory of
  Rational Option Pricing", *Bell Journal of Economics and Management Science* 4(1), 141-183,
  for the continuous proportional yield `q`.

## The call value

With spot `S`, strike `K`, volatility `sigma`, time `T`, risk-free rate `r` and yield `q`,
all continuously compounded,

```
C = S e^{-qT} N(d1) - K e^{-rT} N(d2)
d1 = (ln(S/K) + (r - q + sigma^2/2) T) / (sigma sqrt(T)),    d2 = d1 - sigma sqrt(T)
```

**The normal CDF uses `math.erfc`.** `N(x) = erfc(-x/sqrt(2)) / 2`. For negative `x` this
evaluates a small tail probability directly and keeps its relative precision; `1 - N(-x)`
cancels to zero long before the tail is zero (`1 - N(30)` is exactly `0.0` in floating
point, while `N(-30)` by erfc is `4.9e-198`). The upper tranches of a cap table sit in that
tail. The test suite cross-checks against `scipy.stats.norm.cdf` as an independent oracle,
not as the implementation.

**Limits are closed forms, not approached numerically.**

| Case | Returned | Why |
|---|---|---|
| `strike == 0` | `S e^{-qT}` exactly | A call struck at zero is the prepaid forward |
| `spot == 0` | `0.0` | Nothing to pay |
| `time == 0` or `volatility == 0` (or `sigma sqrt(T)` underflows) | `max(S e^{-qT} - K e^{-rT}, 0)` | The payoff is known with certainty |

**In the money, the put is computed and parity added.** When `ln(S e^{-qT} / K e^{-rT}) >= 0`
the value is `S e^{-qT} - K e^{-rT} + P`, with `P = K e^{-rT} N(-d2) - S e^{-qT} N(-d1)`
floored at zero. The time value is then not the difference of two numbers near `S`. Out of
the money the direct formula is used and floored at zero. Both floors are true bounds, so
they move a correct value by rounding at most.

**Refusals.** A non-finite input, or a negative `spot`, `strike`, `volatility` or `time`,
raises `OpmError` naming the argument. A discount factor that overflows a float
(`e^{-qT}` with a large negative `qT`, say) raises rather than returning infinity. Negative
rates and yields are accepted, because real curves have been negative.

**A very large strike returns `0.0`.** For strikes from `1e100` up to `sys.float_info.max`,
at volatilities 0.3 and 2.0, the value is exactly zero. A sweep of strikes `10^0 ... 10^308`
and `float_info.max` stays finite, non-negative and non-increasing. `ln(S) - ln(K)` is taken
from logs, so an extreme ratio cannot overflow.

### What the tests assert for the call value

| Property | How | Bound |
|---|---|---|
| Agreement with the scipy oracle | 1,080-case grid over S, K/S, sigma, T, r (negative included), q | `1e-13 x max(S, K)` |
| Tail precision | Deep out-of-the-money values from `2e-8` down to `3e-110` | `1e-9` relative |
| `N(x)` against `scipy.stats.norm.cdf` | `x` from -37 to 8 | `1e-12` relative |
| Non-increasing and convex in strike | Hypothesis, 300 examples each | `1e-13 x max(S, K)` per value |
| Non-decreasing in volatility | Hypothesis | same |
| Non-decreasing in time | Hypothesis, **with `q = 0` and `r >= 0` only**: with a yield or a negative rate a European call can lose value with time, so it is not asserted there | same |
| No-arbitrage bounds | `max(S e^{-qT} - K e^{-rT}, 0) <= C <= S e^{-qT}` | same |
| Put-call parity | Against the scipy put, and through put-call symmetry `P(S,K,r,q) = C(K,S,q,r)` using `call_value` alone, which crosses the two branches | `4e-13 x max(S, K)` |
| Volatility to zero | Away from the forward the time value vanishes; at `K = F` the value is `S e^{-qT}(2N(sigma sqrt(T)/2) - 1)`, linear in `sigma` with slope `S e^{-qT} sqrt(T/(2 pi))` | `1e-6` relative |
| Time to zero | Converges to the discounted intrinsic at each `T`, which reaches `max(S - K, 0)` at rate `K(1 - e^{-rT})` | `1e-9 x S` |
| Exact limits | `C(K=0)`, `T = 0`, `sigma = 0`, `S = 0` compared with `==` | exact |

## The allocation

Tranche `t` spans `[k_t, k_{t+1})` with `k_0 = 0`. It is worth
`V_t = C(k_t) - C(k_{t+1})`, with `C` of the unbounded upper end equal to zero. A position
taking share `w_t` of each marginal dollar in tranche `t` is worth `sum_t w_t V_t`. Because
`C(0) = S e^{-qT}` and the `V_t` telescope, the tranches exhaust the discounted equity value
exactly when every tranche's weights sum to one.

### Why the checks, and why they come first

The call-spread decomposition is an allocation only if every position's payoff is
continuous, piecewise linear and non-decreasing in total equity value, and each tranche's
weights are non-negative and sum to one. `docs/opm-contract.md` records that this repository
already has tables where the payoff **steps**: under a collective-conversion vote Series B
receives $9,000,000 at an exit of $57.4M and $7,513,043.48 at $57.6M
([governance](governance.md), GV6). A call spread is continuous, so no combination of call
spreads, in any weights, reproduces a step. On such a table the arithmetic still returns a
number, and nothing inside the option maths can tell it is wrong.

So `opm_allocate` checks, in this order, and refuses with a message saying what failed, where,
and by how much. The order was set by the coordinator so that the caller gets the most
informative error rather than the first one that happens to trip.

| # | Check | Refuses when | Error |
|---|---|---|---|
| 1 | Continuity | `schedule.continuous` is False; names the largest step, its exit value, the position and the jump | `OpmAssumptionError` |
| 2 | Monotonicity | Any weight `< -1e-12` (names the most negative weight, its position and tranche, and how many others), or `monotone=False` with no such weight | `OpmAssumptionError` |
| 3 | Weight sums | `abs(fsum(weights) - 1) > 1e-9` in any tranche, measured here; or the schedule's own `max_weight_sum_error` / `weight_sum_error` above `1e-9` | `OpmAssumptionError` |
| 4a | Linearity measured at all | `linearity_samples == 0`: a zero error that was never measured is not evidence | `BreakpointError` |
| 4b | Linearity | `max_linearity_error > max(1e-6, 1e-9 x equity_value)` | `OpmAssumptionError` |
| 5a | Correspondence | The schedule's positions differ from the table's, a tranche weights an unlisted position, or both carry an `as_of` and they differ | `BreakpointError` |
| 5b | Replay at the equity value | `schedule.payout(equity_value)` differs from the engine's cash by more than the 4b tolerance | `BreakpointError` |

There is no parameter that skips them; a test asserts the signature.

**The negative-weight floor.** A weight produced by a vote is of order 0.1 to 1. The floor of
`1e-12` keeps float noise from a numerically located kink from causing a refusal, and still
separates the real case from noise by about eleven orders of magnitude. A weight inside
`[-1e-12, 0)` is used as given; the negative product it makes is set to zero, so that
`ClassValue.tranche_values` stays non-negative money, and its size is added into
`conservation_error`.

**Corrected 2026-09-15.** This paragraph previously said that `ovf.opm.breakpoints` snaps
`|w| < 1e-12` to exactly zero, so that this path does not run in practice. **That was
false.** The snapping was discussed while the two modules were being written in parallel
and never implemented, and it was written up here as though it had been. The validation
worker measured the truth: `breakpoints.py` does not snap, and **396 schedules carry a
weight in `[-9.1e-15, 0)`**. So this floor is not a second line of defence, it is the only
one, and this path does run. The measurement is also the reassuring part: the largest
residual observed is 110 times inside the floor, so no correct table has been refused by
it. A stated tolerance is worth much less than a stated tolerance with its measured worst
case beside it, which is why the number is here.

**The linearity tolerance.** If a schedule is within `eps` of the engine at every probed exit,
each position's value moves by at most `e^{-rT} eps` over that range. `max(1e-6, 1e-9 x equity
value)` therefore holds the valuation error to one part in 10^9 of equity value (a cent at
$10M) and never asks for less than the `1e-6` at which worker A replays by default.

**The replay at the equity value** is what connects a supplied schedule to the table in hand.
A schedule for the 1x non-participating table, fully verified for that table, passes every
property check when handed the participating table with the same position names; only the
replay sees that the participating table pays common $24M at $35M, not $28M. Under a
collective-conversion term the engine for this check is
`ovf.governance.resolve_collective_conversion(...).result`, not `solve_waterfall`, because
the governed payoff is a different function. A test asserts that the switch happens.

**Negative tranche values.** `C` is non-increasing in strike, so `C(k_t) - C(k_{t+1}) < 0`
can only be float noise. A value within `1e-12 x equity_value` below zero is set to zero and
its size added to `conservation_error`; anything larger raises `OpmError`, because it would
mean the call routine is wrong, not the table. The coordinator's instruction gave the band
as `[-1e-12, 0)`; it is scaled by equity value here because a call value of order `S` rounds
at about `2e-16 x S`, so a band of `1e-12` dollars would be narrower than one ulp for any real
equity value.

**Conservation.** `conservation_error = abs(sum of values - S e^{-qT}) + any snapped noise`.
It is measured, never normalised away, and a value above `1e-9 x S e^{-qT}` raises `OpmError`.
With every weight sum within `1e-9` the first term is bounded by `1e-9 x S e^{-qT}` plus
rounding, so this guard catches numerical failure rather than a property of the table.

**Result fields.** `class_values` lists every position in table order. `value_per_share` is
per share of the position's own class, a preferred share rather than its as-converted common
shares. An unallocated option reserve holds no issued shares, so its `shares` is its
allocated options (zero; the engine refuses allocated options) and `value_per_share` is
`None`. `pct_of_equity` is a share of the total allocated, `S e^{-qT}`.

## The deterministic limit

With `r = q = 0`, as `sigma -> 0`, `C(k) -> max(S - k, 0)`. Tranche `t` then tends to the
length of `[k_t, k_{t+1}) ∩ [0, S]`, and a position's value to
`sum_t w_t |[k_t, k_{t+1}) ∩ [0, S]|`, which is the schedule's replay at `S`. If the schedule
replays the engine, that is the engine's payout at `X = S`. The option maths therefore has to
reproduce the waterfall engine in this limit, and this is the strongest check in the module:
a failure means the allocation is wrong, not the tolerance.

**Off a breakpoint.** At `sigma = 1%`, `T = 1`, the residual option value is
`O(N(-d))` with `d` the log distance to the nearest breakpoint in standard deviations:

| Fixture | X | Nearest breakpoint | Distance in s.d. at sigma = 1% |
|---|---|---|---|
| F1, F9 | $35M | $25M | 33.6 |
| F2 | $15M | $25M | 51.1 |
| F4 | $35M | $5M | 194.6 |
| F5a | $40M | $50M | 22.3 |
| F5b | $60M | $50M | 18.2 |
| F6 | $10M | $9M | 10.5 |
| F7 | $10M | $14M | 33.6 |
| F8b | $20M | $14M | 35.7 |
| F10 | $30M | $10M | 109.9 |

`N(-10.5)` is about `4e-26`, so every position's value equals its engine payout to well
within the `1e-6` dollars the test asserts, for all ten fixtures. The same test runs through
worker A's derived schedule, within `max(1e-6, 1e-9 X) + 1e-6`.

**On a breakpoint** (F3 at $25M, F8a at $14M), the payoff bends at `S` itself. Near `S` it is
a linear function plus `dw (X - S)^+`, with `dw` the change in the position's weight at `S`.
With `r = q = 0`, `E[X_T] = S`, so the linear part is worth its value at `S`, and
`E[(X_T - S)^+] = C(S, S) = S (2 N(sigma sqrt(T)/2) - 1)`. Hence, exactly up to the
exponentially small contribution of the other breakpoints,

```
value = payout(S) + dw * S * (2 N(sigma sqrt(T)/2) - 1)
```

which is `O(sigma)` and vanishes. F3: `dw = +1/5` for Series A and `-1/5` for common. F8a:
`dw = -1` for Series A (its preference is full at $14M), `+1` for common (which starts
there), `0` for Series B.

| sigma | `2N(sigma/2) - 1` | F3: Series A above payout | F8a: common above payout |
|---|---|---|---|
| 1e-2 | 3.989406181e-03 | 19,947.03 | 55,851.69 |
| 1e-3 | 3.989422638e-04 | 1,994.71 | 5,585.19 |
| 1e-4 | 3.989422802e-05 | 199.47 | 558.52 |
| 1e-6 | 3.989422804e-07 | 1.99 | 5.59 |

The test evaluates the prediction with `scipy.stats.norm`, not with `call_value`, and holds
each position to it within `1e-6` dollars. Common at F8a is a clean illustration of what the
method says: the engine pays common nothing at exactly $14M, while its option value is the
value of the right to everything above.

## Breakpoints used in the tests

The tests build their schedules by hand, so they do not depend on worker A's derivation, then
replay each against `solve_waterfall` at every breakpoint, half a dollar either side, each
midpoint, and three exits beyond the last breakpoint, and store the measured gap as
`max_linearity_error`. A guard test requires every one to be within `1e-6`. All share counts
are the [fixture](fixtures.md) table: common 8,000,000; Series A 2,000,000 at $2.50; Series B
1,500,000 at $6.00.

**1x non-participating (F1-F3, F9).** Preference `2,000,000 x 5/2 = 5,000,000`. Series A
converts when `(1/5) X = 5,000,000`, at `X = 25,000,000`, where `1/5 = 2M/(8M + 2M)`.
Weights: `[0, 5M)` Series A 1; `[5M, 25M)` common 1; `[25M, inf)` common 4/5, Series A 1/5.
The pool in F9 has weight 0 throughout.

**Participating, uncapped (F4).** `[0, 5M)` Series A 1; `[5M, inf)` common 4/5, Series A 1/5.
It never converts: `X/5 < 5M + (X - 5M)/5`.

**Participating, 2x cap (F5a, F5b).** The cap is `2 x 5M = 10M`, reached when
`5M + (X - 5M)/5 = 10M`, at `X = 30M`. Conversion beats the cap when `X/5 = 10M`, at `X = 50M`.
Weights: `[0, 5M)` A 1; `[5M, 30M)` 4/5, 1/5; `[30M, 50M)` common 1; `[50M, inf)` 4/5, 1/5.

**2x participating (F10).** `[0, 10M)` A 1; `[10M, inf)` 4/5, 1/5. Never converts.

**Stacked, Series B senior (F6, F8a, F8b).** B's 9M, then A's 5M to 14M, then common alone.
A converts when `(X - 9M)/5 = 5M`, at 34M, after which B still holds its 9M and the residual
splits 4/5, 1/5. B converts when `(3/23) X = 9M`, at 69M, where `1.5/11.5 = 3/23`; above it
everything is common-equivalent: common `8/11.5 = 16/23`, A `4/23`, B `3/23`. At 69M A stays
converted: `(4/23) 69M = 12M > 5M`.

**Pari passu (F7).** `[0, 14M)` A 5/14, B 9/14 (claims 5M and 9M). Above 14M as stacked: A
converts at 34M (B, alone in the tier, keeps 9M), B at 69M. Holding, B would need
`(3/19)(X - 5M) >= 9M`, `X >= 62M`, while A has not converted; A converts first, so B's
threshold is the all-converted 69M.

**The README table (governance tests).** Series A junior, participating, 2x cap; Series B
senior, non-participating. B 9M; A 5M to 14M; A participates at 1/5 until
`5M + (X - 14M)/5 = 10M`, at 39M; common alone to A's conversion at `(X - 9M)/5 = 10M`, 59M;
4/5, 1/5 to B's conversion at 69M; then 16/23, 4/23, 3/23.

## Fixture derivations

Inputs for O1-O3: equity value **S = $20,000,000**, volatility **60%**, **3 years** to
liquidity, risk-free rate **4%** continuously compounded, **no dividend yield**. So
`sigma sqrt(T) = 0.6 sqrt(3) = 1.0392304845` and `e^{-rT} = e^{-0.12} = 0.8869204367`.

### The four calls

`C(0) = S = 20,000,000.00` exactly (strike zero, `q = 0`).

| K | d1 | d2 | N(d1) | N(d2) | S N(d1) | K e^{-rT} N(d2) | C(K) |
|---|---|---|---|---|---|---|---|
| 5,000,000 | 1.9690476671 | 0.9298171825 | 0.97552619121860 | 0.82376712584095 | 19,510,523.824372 | 3,653,079.495020 | **15,857,444.33** |
| 25,000,000 | 0.4203653137 | -0.6188651708 | 0.66289069838690 | 0.26800259241105 | 13,257,813.967738 | 5,942,424.407564 | **7,315,389.56** |
| 30,000,000 | 0.2449263139 | -0.7943041706 | 0.59674325672445 | 0.21350918832853 | 11,934,865.134489 | 5,680,969.876664 | **6,253,895.26** |
| 50,000,000 | -0.2466158717 | -1.2858463563 | 0.40260276001003 | 0.09924834415812 | 8,052,055.200201 | 4,401,269.237209 | **3,650,785.96** |

For example at K = 5M: `d1 = (ln 4 + (0.04 + 0.18) x 3) / 1.0392304845 = (1.3862943611 +
0.66) / 1.0392304845 = 1.9690476671`; `d2 = d1 - 1.0392304845 = 0.9298171825`;
`K e^{-rT} = 4,434,602.183586`; `C = 19,510,523.824372 - 3,653,079.495020 = 15,857,444.329352`.

### O1: 1x non-participating (breakpoints 5M and 25M)

| Tranche | Value `C(k_t) - C(k_{t+1})` | Series A | Common |
|---|---|---|---|
| [0, 5M) | 20,000,000.000000 - 15,857,444.329352 = **4,142,555.67** | 1 → 4,142,555.670648 | 0 |
| [5M, 25M) | 15,857,444.329352 - 7,315,389.560174 = **8,542,054.77** | 0 | 1 → 8,542,054.769177 |
| [25M, ∞) | 7,315,389.560174 - 0 = **7,315,389.56** | 1/5 → 1,463,077.912035 | 4/5 → 5,852,311.648139 |

Series A **$5,605,633.58** (28.028%; **$2.80281679** per share); common **$14,394,366.42**
(71.972%; **$1.79929580** per share). Sum $20,000,000.00. A Series A share is worth
$1.0035 more than a common share at this value, `2.80281679 - 1.79929580 = 1.00352099`.

### O2: participating with a 2x cap (breakpoints 5M, 30M, 50M)

| Tranche | Value | Series A | Common |
|---|---|---|---|
| [0, 5M) | **4,142,555.67** | 1 → 4,142,555.670648 | 0 |
| [5M, 30M) | 15,857,444.329352 - 6,253,895.257825 = **9,603,549.07** | 1/5 → 1,920,709.814305 | 4/5 → 7,682,839.257222 |
| [30M, 50M) | 6,253,895.257825 - 3,650,785.962992 = **2,603,109.29** | 0 | 1 → 2,603,109.294833 |
| [50M, ∞) | **3,650,785.96** | 1/5 → 730,157.192598 | 4/5 → 2,920,628.770394 |

Series A **$6,793,422.68** (33.967%; **$3.39671134** per share); common **$13,206,577.32**
(66.033%; **$1.65082217** per share). Sum $20,000,000.00.

### O3: participating, uncapped (breakpoint 5M)

Tranches `[0, 5M)` **4,142,555.67** to Series A, and `[5M, ∞)` **15,857,444.33**, of which
Series A takes 1/5 = 3,171,488.865870. Series A **$7,314,044.54**; common
**$12,685,955.46**. Against O2, the 2x cap costs Series A $520,621.86 at this value.

Each class value is rounded to the cent from six decimals; in all three cases the rounded
values sum to exactly $20,000,000.00. The tests assert tranche and class values within half a
cent and value per share within `5e-9`.

### Independent recomputation

Every call value above was computed three ways that share no code:

1. `ovf.opm.blackscholes.call_value` (`math.erfc`);
2. the same formula with `scipy.stats.norm.cdf`;
3. 60-digit `decimal` arithmetic, with `erf` from its Taylor series and `pi` from Machin's
   formula.

Routes 1 and 2 agree with route 3 to within `5e-9` dollars at every strike (largest gaps
`4.75e-9` and `2.47e-9`). Breakpoints and weights were derived with `fractions.Fraction`:
`5M = 2M x 5/2`, `25M = 5M / (1/5)`, `30M = 5M + (10M - 5M)/(1/5)`, `50M = 10M / (1/5)`.

## Decisions, recorded

Agreed with the coordinator on 2026-09-15, before the code was final: refuse at a weight below
`-1e-12`, not at zero; a weight-sum tolerance of `1e-9`, measured here and cross-checked
against the schedule's own figure; a linearity tolerance of `max(1e-6, 1e-9 x equity_value)`;
refuse an unmeasured schedule; replay a supplied schedule at the equity value, against the
governance engine under a collective-conversion term; and the check order in the table above.
The one interpretation made here, scaling the negative-tranche-value band by equity value, is
explained under [Negative tranche values](#the-allocation).

## What this does not establish

- **No third-party worked example was reproduced.** Agreement with the AICPA guide's own
  examples, or with any valuation firm's, is untested. The guide was not consulted.
- **No conformance claim.** Nothing here is a 409A valuation, a fair-value opinion or evidence
  of compliance with any standard. The formula is implemented as published; whether it is the
  right method for a given company is a judgement this library does not make.
- **The lognormal assumption is the method's, not a fact.** Constant volatility, one
  liquidity date, a flat continuously compounded rate, a continuous yield, no jumps. Volatility
  is a required input; nothing here estimates it, and no house default exists.
- **No discount for lack of marketability is applied**, and no PWERM, hybrid method or scenario
  weighting is offered.
- **Exercise-price breakpoints are out of reach.** The engine refuses allocated options and
  unexercised warrants, so no schedule here contains the option strike breakpoints that are a
  large part of practice. Unconverted SAFEs and notes are likewise refused by the engine.
- **A governed table is refused, not valued.** Where a collective-conversion vote makes a payoff
  step, the module says why and stops. It offers no alternative number.
- **The replay check is one point.** A supplied schedule that matches the engine at the equity
  value but not elsewhere is caught only by its own `max_linearity_error`, which is only as
  good as the probes that produced it. Beyond the highest probe the last tranche's weights are
  assumed to hold.
- **Transaction costs** are not modelled in the allocation; the engine is replayed at the
  equity value with none.
- **Test coverage of the derived path is narrow.** Only the deterministic limit on the
  off-breakpoint F-fixtures runs through `breakpoint_schedule`. Every other allocation test uses
  hand-built schedules, deliberately, so that it does not depend on worker A's code.
- **Fixture review.** O1-O3 and the breakpoint shapes are derived here and not yet reviewed by
  an independent specialist.

## What a fixture does not establish

A fixture shows that the implementation reproduces a derivation stated here. It does not
establish that the inputs chosen are realistic for any company, that the breakpoints match any
particular charter, or that the list above is complete. The [limitations](limitations.md) list
is the companion to this document.
