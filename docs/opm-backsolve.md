# Backsolve: calibrating total equity value to a transaction price

Status 2026-09-15, engine `opm-backsolve-v1`, module `ovf.opm.backsolve`. Every expected
number below is derived here by two routes that do not import `ovf` (60-digit `decimal`
arithmetic with Newton's method, and scipy's normal CDF with Brent), then asserted in
`tests/test_opm_backsolve.py`.

**Review status: source-derived, not yet independently reviewed.**

**No third-party worked example was reproduced.** B1 and B2 are derived in this document;
neither is taken from the AICPA guide or any other publication.

## What it does

```python
backsolve(
    securities, *, security_id, price_per_share, volatility, time_to_liquidity,
    risk_free_rate, dividend_yield=0.0, as_of=None, collective_conversion=None,
) -> BacksolveResult
```

It finds the total equity value `S` at which `opm_allocate` gives `security_id` a value per
share equal to `price_per_share`: the price actually paid for that class in a recent
financing. That calibrates the Option Pricing Method to an arm's-length transaction instead
of to a guessed enterprise value. Value per share is per share of the target's own class
(`ClassValue.value_per_share`), which is how a round is priced. Volatility, time to
liquidity and the risk-free rate are required; nothing is defaulted except a zero dividend
yield.

`collective_conversion` is a keyword-only passthrough to `breakpoint_schedule` and
`opm_allocate`, added with the coordinator after the contract was amended for the other two
functions: without it a caller holding a governed table would silently calibrate the
ungoverned one.

## Sources

- **The method.** AICPA, Accounting and Valuation Guide, *Valuation of Privately-Held-Company
  Equity Securities Issued as Compensation*, which describes the backsolve method of
  calibrating the Option Pricing Method to a transaction in the company's own securities.
  **No edition, page or paragraph was consulted while writing this module**, so none is
  cited. The method is implemented as described; **no conformance with the guide, or with
  409A practice, is claimed.**
- **Root finding.** Brent, R. P. (1973), *Algorithms for Minimization without Derivatives*,
  Prentice-Hall, chapter 4, as implemented by `scipy.optimize.brentq`.
- The allocation and its call values: [opm](opm.md). The breakpoints: `ovf.opm.breakpoints`.

## The round's shares must already be in the table

The price was paid for shares that exist only after the round closes, together with the
preference they carry. **`securities` must be the post-round table.** Solving with the
pre-round table is the common error, and it fails silently: every class has a price per share
at every equity value, so the solve returns a plausible number for a different company.

A Series A second closing shows it. The first close sold 2,000,000 Series A shares at $2.50;
the second sells 1,000,000 more at the same price. Calibrating to $2.50 (volatility 60%,
3 years, 4%):

| Table | Series A shares | Equity value | Common per share |
|---|---|---|---|
| Pre-round (wrong) | 2,000,000 | $16,120,936.94 | $1.39011712 |
| Post-round | 3,000,000 | $19,225,798.93 | $1.46572487 |

Both solves succeed and neither complains. A target `security_id` that is absent from the
table is refused, with a message saying the round must be in it; a table that contains the
target but is missing some other part of the round cannot be detected.

## Why the root is checked, not assumed

With a schedule the allocation accepts (all weights non-negative), each tranche value
`C(k_t) - C(k_{t+1})` has derivative `e^{-qT} [N(d1(k_t)) - N(d1(k_{t+1}))] >= 0` in `S`, so the
target's value per share is non-decreasing, and in exact arithmetic strictly increasing
whenever the class has any positive weight. In floating point it can be **flat**: when the
target class receives nothing in the tranche that holds almost all of the probability, its
value moves only through normal tail terms `N(-d)` that are below the arithmetic's resolution
or underflow to zero. Then every equity value in an interval reproduces the price, and the
transaction identifies nothing. That is a property of the table *and* the assumptions, so it
is checked for each solve:

1. **Bracket.** Start at the headline post-money, `price_per_share x as-converted shares`,
   used only as a place to start. Evaluate at half and twice that; widen by a factor of 4 on
   whichever side does not yet straddle the price, at most 40 times (`4**40` is about
   `1.2e24`). No straddle: `BacksolveError` with the range searched and the prices at its
   ends.
2. **Grid.** Evaluate on a geometric grid across the bracket, adjacent points at most 2%
   apart. A step that moves the price by no more than `1e-9 x price` is flat (that is the
   allocation's own conservation tolerance); one that lowers it by more is falling. A flat
   run whose level contains the price: `BacksolveError`, not identified, with the interval.
   A falling step: `BacksolveError`.
3. **Brent** on the stretch of the grid around the crossing on which every step rises. That
   stretch is reported as `bracket_low` and `bracket_high`, so `monotone_verified` describes
   the bracket actually used. Flat stretches elsewhere are excluded and listed in the
   assumptions. `monotone_verified` is therefore true on every returned result: a result is
   returned only when its bracket was verified, and the field lets it carry that evidence.
4. **At the root**, the price must still rise across `root x (1 +/- 1e-4)`; the elasticity of
   equity value to price there is reported ("a 1% error in the observed price moves the
   equity value by about ...%"). The residual must be within `1e-9` of the price.

**Strictly increasing is verified at grid resolution.** Between grid points,
non-decrease follows from the allocation's non-negative weights, not from the grid. A flat
stretch narrower than one 2% step, away from the price, would not be seen and does no harm; at
the root the local check sees it.

## The schedule is derived once, and why that is safe

Each allocation needs a breakpoint schedule, and deriving one probes the waterfall engine
dozens of times. The question was whether the schedule moves with the assumed equity value.
It does not:

- **By construction.** `breakpoint_schedule(securities, *, as_of, upper_probe, atol,
  collective_conversion)` takes no equity value. Its default `upper_probe` is twice the
  largest analytic candidate, which is a property of the table. `as_of` and the term are
  fixed for the whole solve.
- **By test.** For F1, F5a, F6 and F7, the schedule `opm_allocate` derives at equity values of
  $100,000, $20M and $5bn is equal to the one derived with no equity value at all.
- **Measured.** Deriving a schedule for the fixture tables takes 1.7 to 7.4 ms; an allocation
  on a cached schedule takes 0.06 to 0.15 ms. B1 makes 79 allocations, so reuse is 20 to 70
  times cheaper per evaluation.

No table in scope makes the schedule depend on equity value, so it is always cached. A test
counts the derivations: exactly one per backsolve. Each allocation still replays the engine
at its own equity value (`opm_allocate`'s spot check), so every point the search visits is
also a check of the schedule there, including above the schedule's highest probe.

## Refusals

| Refusal | Raised as | Triggered in the tests by |
|---|---|---|
| Invalid input (price not positive, non-finite value, volatility or time not positive) | `BacksolveError` | direct inputs |
| Target not in the table ("the round's shares must already be in the cap table") | `BacksolveError` | Series B on the F1 table |
| Target holds no issued shares | `BacksolveError` | the F9 option reserve |
| **No bracket** | `BacksolveError` | F1, Series A at $2.50, dividend yield 1,000% over 10 years: `e^{-100}` of value leaks out before liquidity, and at `4**40` times the starting scale the price is `1.1e-18` |
| **Not identified** (flat run containing the price) | `BacksolveError` | F1, Series A at $2.50, volatility 1%, 1 year, r = 0: flat from at least $5,314,056.76 to $23,684,018.91 |
| Falling price | `BacksolveError` | no table reaches it, since the allocation refuses a negative weight first; exercised by replacing the price function |
| Brent fails, residual too large, or flat at the root | `BacksolveError` | defensive; not reached by any fixture |
| Governed or non-monotone table | `OpmAssumptionError`, propagated unchanged | the README table with its mandatory-conversion term |

**The flat case is real.** In the 1x non-participating table Series A takes the first $5M and
nothing more until it converts at $25M. At 1% volatility and a zero rate its value is exactly
$5M, $2.50 a share, for equity values across most of that tranche, so a round at $2.50 fixes
no equity value in it. At 5% volatility the flat stretch still runs from about $6.6M to $19.1M.
With a 4% rate the level falls to `2.5 e^{-0.04} = 2.40`, the price $2.50 lies above it, and
the solve succeeds at $24,809,431.94. The equity value is then set entirely by the conversion
option near $25M, and the flat stretch from $12.5M to $18.47M is excluded from the bracket.

**No bracket needs extreme inputs here.** Every share-holding position the engine supports has
a value per share that tends to zero as equity value falls and grows without bound as it rises,
because every preferred position can convert. So a finite price is always straddled unless
something like a huge dividend yield pushes the crossing beyond `4**40` of the starting scale.

**The governed table.** Series B at $6.00 on the README table (tests/governance_fixtures.py)
backsolves to about $40.3M without its term. With the mandatory-conversion term the payoff
steps (the largest step is at $10,894,736.84, where common's cash jumps by -$7,578,947.37), and
the allocation refuses on continuity before any search. A test asserts both halves.

## Fixture derivations

Market inputs for B1, B2 and the sensitivity table: volatility **60%**, **3 years**, risk-free
rate **4%** continuously compounded, **no dividend yield**, unless stated. The table is the
[fixture](fixtures.md) one: common 8,000,000 shares; Series A 2,000,000 at $2.50, **the
round's shares included**. Breakpoints are derived in [opm](opm.md).

### B1: 1x non-participating, Series A priced at $2.50

The target is a Series A value of `2,000,000 x 2.50 = $5,000,000`. From the tranche weights
(`[0, 5M)` Series A 1, `[5M, 25M)` 0, `[25M, ∞)` 1/5),

```
A(S)  = [C(0) - C(5M)] + (1/5) C(25M) = S - C(5M) + C(25M)/5          (q = 0, so C(0) = S)
A'(S) = 1 - N(d1(5M)) + N(d1(25M))/5                                   (dC/dS = N(d1))
```

Newton's method from the headline post-money `2.50 x 10,000,000 = $25,000,000`:

| Iteration | S | A(S) | A(S) - 5,000,000 | A'(S) |
|---|---|---|---|---|
| 0 | 25,000,000.000000 | 6,402,459.437052 | 1,402,459.437052 | 0.161952384313 |
| 1 | 16,340,297.686862 | 5,034,196.277499 | 34,196.277499 | 0.155855533940 |
| 2 | 16,120,887.591921 | 4,999,992.305486 | -7.694514 | 0.155929524342 |
| 3 | 16,120,936.938021 | 5,000,000.000000 | -0.000000 | 0.155929505075 |
| 4 | 16,120,936.938024 | 5,000,000.000000 | -0.000000 | 0.155929505075 |

Check at the root `S* = 16,120,936.938024`, with `sigma sqrt(T) = 1.0392304845`:

| K | d1 | d2 | N(d1) | C(K) |
|---|---|---|---|---|
| 5,000,000 | 1.7615735613 | 0.7223430768 | 0.96092931290440 | 12,098,795.495292 |
| 25,000,000 | 0.2128912080 | -0.8263392766 | 0.58429408989581 | 4,889,292.786340 |

`A = 16,120,936.938024 - 12,098,795.495292 + 4,889,292.786340 / 5 = 4,022,141.442732 +
977,858.557268 = 5,000,000.000000`.

→ **Total equity value $16,120,936.94.** With `q = 0` the values sum to `S`, so common is worth
`S* - 5,000,000 = $11,120,936.94`, **$1.39011712 a share**. The Decimal root and the scipy
root differ by `2.2e-8` dollars. `backsolve` searches `[12.5M, 50M]` with no widening, and a 1%
error in the $2.50 price moves the answer by about 2%.

The headline post-money is $25M. The backsolved value is 36% below it, because a Series A share
is worth more than a common share: the round price overstates common, which here is worth 56%
of the preferred price.

### B2: participating with a 2x cap, Series A priced at $2.50

Weights `[0, 5M)` 1, `[5M, 30M)` 1/5, `[30M, 50M)` 0, `[50M, ∞)` 1/5, so

```
A(S) = C(0) - C(5M) + (1/5)[C(5M) - C(30M)] + (1/5) C(50M)
     = S - (4/5) C(5M) - (1/5) C(30M) + (1/5) C(50M)
```

Newton from $25M:

| Iteration | S | A(S) | A(S) - 5,000,000 |
|---|---|---|---|
| 0 | 25,000,000.000000 | 7,676,509.366577 | 2,676,509.366577 |
| 1 | 9,584,472.723993 | 4,655,098.241707 | -344,901.758293 |
| 2 | 10,950,242.067605 | 4,985,977.329993 | -14,022.670007 |
| 3 | 11,010,434.469244 | 4,999,977.761103 | -22.238897 |
| 4 | 11,010,530.232961 | 4,999,999.999944 | -0.000056 |
| 5 | 11,010,530.233202 | 5,000,000.000000 | -0.000000 |

→ **Total equity value $11,010,530.23**; common `(S* - 5M) / 8M` = **$0.75131628 a share**.
The two routes differ by `1.0e-9` dollars. The same $2.50 price on participating terms implies
an equity value a third lower and a common price 46% lower than B1: the terms of the round
decide what its price says about the company.

## Sensitivity: how much is the assumption

B1 re-solved across volatility and time to liquidity, everything else unchanged. Each cell was
computed by the scipy route and is asserted to within 50 cents.

**Total equity value**

| Volatility \ years | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 30% | 19,669,279 | 19,173,554 | 19,062,388 | 19,118,027 | 19,258,079 |
| 45% | 16,502,125 | 16,186,904 | 16,506,179 | 16,943,130 | 17,393,421 |
| 60% | 14,695,529 | 15,342,549 | **16,120,937** | 16,842,547 | 17,497,702 |
| 75% | 14,306,692 | 15,512,506 | 16,567,725 | 17,478,780 | 18,274,327 |
| 90% | 14,467,557 | 16,042,467 | 17,315,358 | 18,374,599 | 19,271,067 |

**Common value per share**, `(S* - 5,000,000) / 8,000,000`

| Volatility \ years | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 30% | 1.8337 | 1.7717 | 1.7578 | 1.7648 | 1.7823 |
| 45% | 1.4378 | 1.3984 | 1.4383 | 1.4929 | 1.5492 |
| 60% | 1.2119 | 1.2928 | **1.3901** | 1.4803 | 1.5622 |
| 75% | 1.1633 | 1.3141 | 1.4460 | 1.5598 | 1.6593 |
| 90% | 1.1834 | 1.3803 | 1.5394 | 1.6718 | 1.7839 |

The transaction is the same in every cell: 2,000,000 Series A shares at $2.50. Across ranges a
valuer could defend, the calibrated equity value runs from **$14.3M to $19.7M** (-11% to +22%
around the central $16.1M), and **common from $1.16 to $1.83 a share**, a factor of 1.58. The
transaction fixes one number, Series A's value; how that number translates into an equity value
and a common price is mostly the volatility and the time to liquidity. Those are assumptions,
not observations.

The value is not monotone in either input. Using parity, the Series A value is
`A = 5M e^{-rT} - P(5M) + C(25M)/5`: the preference as a discounted bond, less the put the
holder is short, plus a fifth of a call struck at conversion. Longer time discounts the bond
more and widens both options, and higher volatility widens both, so at 30% the equity value
falls from 1 to 3 years and then rises, and at 1 year it is lowest at 75% volatility.

## Evidence

| Test | What it establishes |
|---|---|
| Round trip | 6 tables x every class x 3 (volatility, time) pairs x 2 equity values: S recovered to `1e-9` relative, residual within `1e-9` of the price, root inside a verified bracket |
| Schedule invariance | Derived schedule equal at $100k, $20M and $5bn for four tables |
| Derived once | Exactly one call to `breakpoint_schedule` per backsolve |
| Refusals | Each row of the refusal table, with the table named there |
| Governed table | A number without the term, `OpmAssumptionError` with it |
| Pre-round table | Silently different answer, more than $3M apart |
| B1, B2 | To the cent, with common per share to `5e-10` |
| Sensitivity | All 25 cells to 50 cents |

## Decisions, recorded

- `collective_conversion` added to `backsolve`, forwarded to both functions, with the
  continuity refusal propagated as `OpmAssumptionError` (agreed with the coordinator
  2026-09-15; the contract is being updated).
- Starting scale: the headline post-money. It is only a starting point; the bracket widens
  from it.
- Flat band `1e-9` of the price: the allocation's conservation tolerance. A change below it is
  not distinguishable from the arithmetic.
- `scipy.optimize.brentq` is imported with `# type: ignore[import-untyped]`: scipy is a runtime
  dependency but ships no type stubs, and this is its first use in `src`.

## What this does not establish

- **No third-party worked example was reproduced**, and the AICPA guide was not consulted. No
  conformance with it, or with 409A practice, is claimed. Nothing here is a valuation opinion.
- **The price is taken at face value.** It is treated as an arm's-length price for exactly the
  rights the engine models. Real rounds pay for things it does not model: redemption rights,
  pro rata and information rights, protective provisions, a strategic premium, a secondary
  component, a discount for an insider-led round. Calibrating to a price that pays for them
  attributes their value to the equity.
- **The table must be the post-round table**, and that cannot be verified beyond the target's
  presence.
- **One class, one transaction.** No calibration to several prices at once, no weighting of
  rounds, and no reconciliation with an income or market approach.
- **The assumptions dominate.** The sensitivity table is the evidence. The module requires
  volatility and time as inputs and estimates neither.
- **Strict increase is verified at grid resolution**, 2% of equity value, plus a local check at
  the root. Between grid points non-decrease follows from the allocation's non-negative weights.
- **No discount for lack of marketability** is applied to the calibrated values, including the
  common price read off the result.
- **A governed table is refused, not calibrated.** No alternative method is offered.
- **The Brent step is scipy's.** The tests cross-check the whole solve on B1 and B2 against an
  independent Decimal Newton solve, not the root finder in isolation.

## What a fixture does not establish

A fixture shows that the implementation reproduces a derivation stated here. It does not
establish that the inputs are realistic for any company, that a real round was priced on these
terms, or that the list above is complete. The [limitations](limitations.md) list is the
companion to this document.
