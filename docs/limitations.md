# What this does not model

Status 2026-09-15, engine `waterfall-v3` / `safe-round-v2`.

This list exists so a reader finds the gaps here rather than in their own numbers.
Anything on it will change a real payout. Absence from this list is not a claim of
completeness; if something is missing, that is a documentation bug and worth an issue.

## Exit waterfall

| Not modelled | Why it matters |
|---|---|
| **Management carve-out plans** | Frequently paid off the top, ahead of the preference stack. A carve-out changes every number below it, and it is the most common reason a hand-built waterfall disagrees with a real closing statement. |
| **Dividend forms beyond the supported two** | Cumulative and non-cumulative dividends ARE now modelled; see [dividends](dividends.md). Declared-but-unpaid dividends, sub-annual rate conventions, PIK at a multiple other than 1x and fractional-PIK cash are not. |
| **Debt beyond the supported instruments** | Term debt, venture debt and convertible notes ARE now modelled and paid ahead of all equity; see [debt](debt.md) for the supported accrual methods and the list of what it excludes (warrants, prepayment charges, amortisation, post-maturity accrual, stub-period compounding, conversion at maturity). Trade payables and anything else must still be settled outside and netted off. |
| **Anti-dilution beyond a conversion-price adjustment** | The adjustment IS now applied to a cap table by `ovf.financing.apply_dilutive_issuance`; see [financing](financing.md). Only the conversion ratio changes. CP2 rounding, waiver, multiple closings, series-specific exemptions, a par floor and every other down-round term are absent. |
| **Pay-to-play and shadow classes** | A failure to participate can convert a class or strip its rights. Not represented. |
| **Drag-along and protective provisions** | Established NOT to move cash: both gate whether a sale happens, and a renegotiated carve-out is a different cap table. See [governance](governance.md). They are documented, not inputs. |
| **Governance beyond one collective conversion** | A Requisite Holders mandatory conversion IS modelled (`ovf.governance`). Several independent votes, strategic or coalition voting, and a vote whose stage payoff is non-unique are refused. |
| **Coordinated holders** | One holder across several positions may optimise jointly. `WaterfallResult.multi_position_holders` discloses when this is possible; it does not model it. |
| **Granted options and warrants** | Rejected rather than guessed, because strike, vesting, acceleration on change of control and net-exercise settlement are all required and none is available. Unallocated reserve capacity is supported and receives nothing. |
| **Escrow, holdbacks, earnouts, indemnity** | Deferred and contingent consideration is out of scope. Pass the amount actually distributed. |
| **Transaction expenses beyond one lump sum** | `transaction_costs` is a single deduction from gross proceeds. |
| **Multiple closes at different prices inside one series** | Model them as separate positions with their own prices. |
| **Side letters** | Not represented in any form. |
| **Tax** | All amounts are pre-tax. |
| **Non-cash and mixed consideration** | Stock-for-stock, escrowed stock and contingent value rights are out of scope. |
| **Foreign structures and multi-currency** | One base currency, no conversion, no settlement rounding. |
| **Unconverted SAFEs at a liquidity event** | Rejected by the exit engine. SAFE liquidity rights are not implemented; resolve the financing first. |

## Financing rounds

`ovf.rounds.apply_priced_round` prices a round over an existing cap table under any of
Cooley's three conventions and carries existing preferred through it; see
[rounds](rounds.md). `solve_priced_round_with_safes` is unchanged and remains the
common-only entry point. What is still absent:

| Not modelled | Why it matters |
|---|---|
| **A round that triggers a protected series' anti-dilution** | Refused. The round's price may depend on its own anti-dilution shares, and the term sheet does not say whether those are inside the "fully-diluted pre-money"; NVCA s.4.4.3's deemed-issuance question is also unsettled. Use `ovf.financing.apply_dilutive_issuance` at a stated price instead. |
| **Convertible notes converting in a round** | A note is an exit claim (see [debt](debt.md)); it does not convert through `apply_priced_round`. |
| **Paid-in-kind preferred in a round table** | Not carried through a financing. |
| **Promised options beyond the reserve, the treasury method, a pool outside the pre-money** | Each changes the capitalization denominator; see [rounds](rounds.md). |
| **MFN timing and notice** | The 10-day election window, electing a non-SAFE convertible or an already-amended instrument, and MFN at a liquidity event. |
| **Negotiated conventions beyond Cooley's three** | Only the three are implemented, each explicit and with no default. |
| **Convertible notes in a SAFE round** | The SAFE solver does not price notes alongside SAFEs. Notes as an exit claim are modelled separately in [debt](debt.md); mixing them into `solve_priced_round_with_safes` is not supported. |

## Open Cap Table Format (OCF)

`ovf.ocf` reads and writes OCF v1.2.0 packages. See [ocf](ocf.md) for the full mapping,
the four conventions that set numbers, and the transaction partition (4 applied,
7 ignored, 32 refused).

| Not modelled | Why it matters |
|---|---|
| **Participating-uncapped preferred on write** | OCF v1.2.0 has no `participating` flag, only `participation_cap_multiple`, so this term is **not expressible**. The writer refuses it rather than emitting a class that understates the holder or inventing a cap. |
| **OCF's own v1.2.0 sample package** | Not readable, even with `ignore_common_preference_fields`: placeholder md5s, preference fields on its common class, a Series Seed with no `price_per_share`, and refused transaction types. Its `Transactions` file also fails OCF's own file schema. |
| **Preferred carrying a dividend, on write** | OCF v1.2.0 `StockClass` has no dividend fields at all. The writer refuses such a class rather than emitting it without the term, which would silently drop an accruing claim. |
| **A convertible note's economics, on round trip** | OCF has no maturity field, carries the qualified-financing threshold only as free text, and has no compounding frequency. Notes are readable only when the caller supplies those terms; see [ocf](ocf.md). |
| **Non-convertible debt** | OCF v1.2.0 has no object for a term loan or a venture debt facility, so a claim ranking ahead of all equity cannot be written at all. |
| **Vesting, grants, exercise, warrants, transfers, splits** | Refused rather than approximated; each refusal and its cost is listed in [ocf](ocf.md). |
| **ZIP containers and other OCF versions** | Only an unpacked v1.2.0 package is read. |

## Option Pricing Method (`ovf.opm`)

- **The method is refused more often than it is applied, by design.** The call-spread
  decomposition needs the payoff to be continuous, piecewise linear, non-decreasing and to
  share each marginal dollar in weights summing to one. `opm_allocate` checks all four and
  raises `OpmAssumptionError` rather than returning a number when one fails. There is no
  flag to skip the check, and there will not be one.
- **A collective-conversion vote makes the method inapplicable, not merely inaccurate.**
  The payoff steps at the vote flip, and no combination of call spreads reproduces a step,
  so the payoff is not in the span of the instruments the method decomposes into. See
  [breakpoints](opm-breakpoints.md) and [governance](governance.md).
- **Some governed tables cannot be scheduled at all.** `ovf.governance` refuses over a whole
  interval where a pivotal holder's gain is identically zero, and `breakpoint_schedule`
  propagates that refusal. This is a real property of those tables, not a probe artefact:
  three separate probe artefacts that looked like it were found and fixed, and are recorded
  in [findings](opm-findings.md).
- **The method does not apply to roughly a third of governed tables.** `opm_allocate`
  refused 677 of 2,000 generated governed venture tables (33.9%) and 0 of 4,000 of the same
  tables without the term. That is the measured refusal rate on generated tables, not a
  claim about real cap tables.
- **Lognormal total equity value, one liquidity date, one volatility.** The model has no
  term structure, no jump, no stochastic volatility, and no distribution other than
  lognormal. Volatility, time to liquidity and the risk-free rate are required arguments
  with no defaults, because there is no defensible house value for any of them.
- **Backsolve needs the round's shares already in the table.** Calibrating against the
  pre-round table returns a plausible and wrong number; the tests pin the size of that
  error. A flat stretch in the target's price leaves the equity value unidentified, and
  that is refused rather than resolved by picking an endpoint.
- **The breakpoint search is bounded.** Up to 12 preferred positions, 8 under a governance
  term. `atol` is absolute, so exits near 1e10 need a larger tolerance than the default.
- **No third-party worked example has been reproduced.** No edition of the AICPA guide was
  consulted; the method is implemented as published in the general literature, and nothing
  here claims conformance with it or with 409A.

## Marketability discounts (`ovf.opm.dlom`)

- **Every attribution is recalled and unverified.** The formulas were derived and are shown
  as algebra a reader can check, and each is validated against simulation of the payoff it
  prices. What is NOT established is that each matches the formula printed in the cited
  paper. The difference between Finnerty's 2002 working paper and the 2012 version is
  explicitly not established here.
- **Two of the four are demonstrably not exact.** Simulation places the true average-strike
  put strictly between Finnerty below and Ghaidarov above, by up to 154 standard errors.
  Neither is reported as correct.
- **There is no default and no blend.** The discounts disagree by more than the inputs move
  any one of them once Longstaff is included; among the three put-based methods the spread
  is smaller than that claim implies, and the document says so.
- **Longstaff exceeds 100%** past a volatility-time of about 0.94 and is left unclamped,
  because it bounds the value of perfect market timing rather than a marketability discount.
- **An option price is not a marketability discount.** The analogy is an argument, not an
  identity, and the choice of discount is a judgment this library does not make.

## Fund performance (open-pme)

The full list is in [pme](pme.md#not-modelled); these are the items most likely to make a
number differ from a vendor's.

| Not modelled | Why it matters |
|---|---|
| **Cambridge Associates' own mPME** | `ovf.pme.mpme` is a labelled reconstruction; CA's dating conventions are unpublished. |
| **Korteweg–Nagel GPME, Takahashi–Alexander, fund carry, subscription-line reconstruction** | Estimators, forecasts or LPA/facility data this module does not take. Net LP flows alone may not identify a unique unlevered history. |
| **Recallable distributions** | Gross legs only: a recalled distribution counts in both paid-in and distributed, which moves TVPI, KS-PME and PME+. |
| **Quarter-aggregated flows, month-end index levels** | Vendor series built that way will not match daily-dated inputs, and nothing in a result can reveal an aggregation done before the call. |
| **NAV quality** | The residual value (and, for the mPME, every interim NAV) is taken as stated; no de-smoothing. |
| **FX** | Fund and index must share a currency. |

## Numerical and structural

- Floating point throughout, with a reported tolerance of `1e-8 + 1e-12 × net_exit`.
  There is no cent rounding, so a settlement layer must conserve the rounded total.
- `solve_waterfall` returns **one** verified equilibrium. Where several profiles exist
  it does not report that fact; `enumerate_equilibria` does, and is exponential in the
  number of preferred positions.
- The payoff-uniqueness result in [findings](findings.md) is empirical, over generated
  tables, within the implemented scope. It is not a theorem and does not extend to the
  unmodelled features above.
- Debt AND dividend accrual both require the same explicit `as_of` date.
- Under a collective-conversion term a position's cash can FALL as the exit rises; the
  monotonicity that holds for the per-position game does not survive the vote. See
  [governance](governance.md).
- `fully_diluted_shares` refuses any security that can still convert but holds no shares. There is no implicit clock: a table
  holding debt raises rather than assuming today, because an implicit date would make the
  result irreproducible.
- `security_id` identifies a position and must be unique. `holder_id` may repeat and is
  aggregated for ownership only.
- Securities are immutable; a new snapshot requires new objects.

## Not a compliance or advice surface

This library performs the calculations documented in [semantics](semantics.md). It is
not a 409A valuation, an IPEV or ASC 820 fair-value opinion, a regulatory filing tool,
or financial, legal or tax advice. It does not certify a cap table, and agreement with
it is not evidence that a distribution is contractually correct.
