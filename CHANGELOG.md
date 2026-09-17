# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html); while the
major version is `0`, the public interface may change in a minor release.

Nothing has been published yet. No package, tag or release exists outside this
checkout.

## [Unreleased]

### Added - open-pme: dated fund cash flows and public-market equivalents

- **`ovf.pme`** (engine `pme-v1`; semantics in [pme](docs/pme.md)): typed dated flows with a
  stated basis, currency and stale-NAV policy (`FundCashFlows`, `resolve`); DPI/RVPI/TVPI;
  a **certified XIRR** that finds every real root and proves the list complete, or says it
  cannot — Descartes' rule of signs for exponential sums with its parity statement
  (Jameson 2006, Thm 3.1 / Prop 3.6), Rolle isolation carried out in log space, and a
  proved term-dominance root bound — and never picks a root; KS-PME, Direct Alpha, PME+,
  the Long–Nickels ICM and a **labelled mPME reconstruction** with an interim-NAV policy.
- `pme_report`: every metric in one call, each slot a result or a `Refusal`, with
  machine-readable flags, de-duplicated assumptions, `to_text()` and `to_rows()`. Strict
  CSV loaders (`ovf.pme.io`), explicit truncation (`FundCashFlows.through`), the
  `python -m ovf pme report` command and `examples/pme_walkthrough.py`, which reproduces
  the published Gredil–Griffiths–Stucke illustration and checks every printed figure.
- Every convention is a required argument: three additive day counts (ACT/365F, the
  Excel/LibreOffice `XIRR` convention; ACT/365.25; ACT/ACT-ISDA), the index return basis,
  an index lookup that never looks forward or interpolates, and the interim-NAV policy.
- Evidence: a claim-by-claim source ledger ([pme-sources](docs/pme-sources.md), 82 rows),
  hand-derived fixtures PME-F1 to PME-F19 ([pme-fixtures](docs/pme-fixtures.md)) including
  a published example, and an independent 60-digit Decimal/Fraction oracle written by a
  different model family without reading the engine. Three adversarial reviews; every
  finding is fixed or recorded as a decision in `docs/pme-contract.md` §11.

### Findings - open-pme

- **A published illustration silently picks one of two IRR roots.** Gredil, Griffiths &
  Stucke's 2014 draft (Exhibits 5–6) displays the Long–Nickels ICM rate as 6.0%. With the
  displayed inputs the ICM series has two roots, −27.26% and +5.97%, and its index position
  goes short on 2007-12-31 — the method's own documented pathology, inside its own
  illustration. Re-derived with exact arithmetic by the oracle and separately by hand.
- **Microsoft's published `XIRR` value is Excel's iterate, not the root.** The example's
  exact root is 0.37336253351883151; the displayed 0.373362535 carries Excel's stopping
  tolerance (the NPV there is −8.6e−6).
- **Attribution corrections.** Kaplan & Schoar's PME has no NAV term (largely liquidated
  funds); the residual value as a terminal distribution is Harris, Jenkinson & Kaplan
  (2014). Rouvinez's PME+ appeared in *Venture Capital Journal* (Aug 2003), not *Private
  Equity International*. The index error in Gredil et al.'s mPME eq. (11) is confirmed in
  their 2014 draft.
- **KS-PME > 1 ⇔ Direct Alpha > 0 needs a negative first net as well as one sign change**
  (+50 then −100 at a constant index: KS-PME 0.5, Direct Alpha +100%).
- **Float noise is not a property of the fund.** Reviewers found, and the module now
  handles: coefficient normalisation into subnormals that had produced a false complete
  root set (fixed by log-space isolation; 341 exact Sturm-counted families, none wrong);
  written-off funds refused because the residual overflowed (fixed: verified on a scaled
  axis, rates below float resolution reported as −1.0 with the exact log rate); decimal
  cents that do not cancel in binary adding sign changes (stated nets within
  `ε·Σ|legs|` are treated as zero and listed); computed ICM/PME+/mPME nets within their
  rounding bound adding false roots.

### Added - open-opm: the Option Pricing Method, and the boundary of where it applies

- **`ovf.opm.breakpoints`** - `breakpoint_schedule` derives the exit breakpoints from the
  verified waterfall engine instead of from a hand-built table. Candidates (debt tiers,
  preference stacks, cap exhaustion, conversion indifference over all conversion profiles,
  and vote flips under a governance term) are generated in exact rational arithmetic, then
  **verified**: the engine is probed either side of every candidate and at interior points,
  non-kinks are dropped, and any kink the candidate families failed to predict is located
  and recorded as such. Over 3,000 generated ungoverned tables this produced 10,940
  breakpoints with zero replay gaps across 80,640 probes and weights within 5.5e-15 of an
  exact-rational oracle's slopes.
- **`ovf.opm.blackscholes`** - Black-Scholes-Merton with its limits returned from closed
  forms rather than approached numerically, `math.erfc` for the normal CDF so the far tail
  keeps relative precision, and a put-call-parity branch in the money so time value is not
  the difference of two numbers near spot. Agrees with an independent scipy oracle to
  2.4e-13 relative over 20,000 draws spanning eleven orders of magnitude in spot and strike.
- **`ovf.opm.allocate`** - `opm_allocate` values each tranche as a call spread and allocates
  it by the tranche weights, checking value conservation against the call struck at zero.
- **`ovf.opm.backsolve`** - calibrates total equity value to an observed transaction price,
  verifying strict monotonicity across the bracket rather than assuming it, and refusing an
  unidentified flat stretch. Round trips recover the input to 1e-9 across 84 cases. The
  breakpoint schedule is shown not to depend on equity value and is derived once per solve.
- **`ovf.opm.dlom`** - Chaffe, Finnerty, Longstaff and Ghaidarov as four separate
  estimators, with no default, no blend, and no single "the DLOM". Each is checked against
  seeded simulation of the payoff it claims to price.

### Findings - open-opm

- **A collective-conversion vote does not merely break monotonicity, it breaks
  continuity.** The payoff *steps* at the vote flip. A call spread is continuous, so no
  combination of call spreads in any weights reproduces a step: the payoff is not in the
  span of the instruments the method decomposes into. `opm_allocate` refuses such a table
  outright. Under the model charter's majority term there is no negative tranche weight
  anywhere - only steps - so continuity, not monotonicity, is the operative check.
- **A second and much larger step on the README table**, at exactly 207,000,000/19 =
  $10,894,736.84, recorded in [governance](docs/governance.md). At $10,894,736 the vote
  carries and the common receives $7,578,946.78; one dollar higher the vote fails and the
  common receives **nothing**. It runs the opposite way from the $57.5M step: either side
  of the vote can be the loser, and the common can lose the most. A grid search would have
  had to land within a dollar of 207,000,000/19 to see it; it was found by solving for the
  root of the pivotal holder's gain.
- **Finnerty and Ghaidarov bracket the payoff they both approximate.** Simulating the
  average-strike put directly places it strictly between Finnerty (below at every one of 24
  grid cells, by 5 to 154 standard errors) and Ghaidarov (above from a volatility-time of
  about 0.42). Neither closed form is exact. Chaffe and Longstaff match simulation within
  standard error over 100 seeds, which is what establishes that the gaps belong to those
  two formulas rather than to the simulation.
- **The Longstaff bound passes 100%** at a volatility-time of about 0.94 and is left
  unclamped: it bounds the value of perfect market timing, which is not a marketability
  discount, and past that point it stops being informative about one.

### Verified against a second implementation

`tests/opm_oracle.py` is an independently written exact-rational oracle and a lognormal
quadrature allocator that imports none of the modules under test: it reasons about the
payoff as a black box and evaluates no option formula at all. Agreement between two routes
that share no code is the evidence; a shared bug would defeat it. Over 4,000 generated
tables, with and without a governance term:

- the two breakpoint derivations agree **exactly** on 36,009 breakpoints and 2,441 steps;
- call-spread allocation matches numerical integration to **6.3e-15** of equity value;
- value conservation holds to **4.9e-16**;
- the deterministic-limit error floors at **1.85e-16** of equity value, and on a breakpoint
  it tracks the predicted kink option exactly.

**How often the method actually applies.** `opm_allocate` refuses **677 of 2,000** governed
venture tables (33.9%, 95% Wilson 31.8-36.0%) and 1,127 of 2,000 adversarial ones, and
**0 of 4,000** of the same tables without the governance term. Every refusal is a step; not
one is a negative weight, which is why continuity rather than monotonicity is the operative
check.

**What the unchecked construction would have reported on those tables.** At 60% volatility
over 3 years, the largest class gap has a **median of 6.4% of equity value** ($841k), p90
16.6% ($5.4M) and a maximum of 22.7% ($34.4M) — a median of **30% of that class's own
value**. The wrong answer still conserves value exactly, so nothing inside the option
arithmetic can detect it. That is the argument for the refusal existing.

### Fixed - five defects found by the validation worker, all closed

The independent implementation found five problems that the modules' own authors and their
own test suites did not. Each is now asserted by a plain passing test.

- `call_value` raised `ZeroDivisionError` when `volatility * sqrt(time)` underflowed to zero
  from two positive factors, a case its own documentation said returned the discounted
  intrinsic. Reachable through `opm_allocate`, since `OpmInputs` admits such a volatility.
- **Three instances of one failure mode**, worth stating as a family rather than a list: a
  probe chosen for the derivation's own convenience lands on an exit where `ovf.governance`
  legitimately declines to call a tied vote, and the code treats the engine's honest refusal
  as a property of the table. The spot check at the equity value now retries beside it and
  discloses the substitution; the origin probe is floored by the interval width instead of
  an absolute 1.0, which had put it at an exit of 1e-6 on tables denominated in millions and
  refused 21 tables in 4,000 with a false reason, 7 of which price fine; and the cosmetic
  mid-tranche probe that only fills in a `basis` string can no longer refuse the table it is
  describing.
- `docs/opm.md` stated that the breakpoint module snaps tiny weights to exactly zero. It does
  not. The measurement that caught it is now in the document: 396 schedules carry a weight in
  `[-9.1e-15, 0)`, which is 110x inside the floor that absorbs them.

The validation document also records two defects in the validator itself — a probe blind
spot in its first oracle, where the module under test was right, and a replay check that
covered only `[0, 1]` for a single-tranche schedule. Both were found and fixed by the worker
that wrote them, and both are reported alongside the five above.

### Changed

- `README.md` no longer lists class governance as outside the modelled scope; `ovf.governance`
  has been present since the previous release and the sentence was simply out of date.
- `opm_allocate` takes a keyword-only `atol`, forwarded to the breakpoint construction. The
  construction tolerance is absolute, so without it no caller could price a table whose
  breakpoints run past roughly 1e10. It cannot weaken a refusal: the allocation still
  measures the resulting schedule against `linearity_tolerance(equity_value)`.

### Added - Wave 3: safe-math and global-standard completed

- **Financing rounds** (`ovf.rounds`): `apply_priced_round` prices a round over an existing
  cap table and carries existing preferred through it as the same objects. Cooley's three
  negotiated conventions are an explicit `convention` with no default; the legacy solver is
  unchanged and was identified as the percentage-ownership method. Explicit `PoolChange`
  (target post-round unallocated fraction, or a stated share increase), explicit
  `SeniorityPlacement`, and an explicit choice of whether converting SAFEs take their own
  Safe Preferred series or the new series.
- **YC Discount Only and MFN Only SAFEs** (`ovf.contracts.safes`), plus the Section 3 MFN
  amendment. The text settles all three MFN questions: it resolves **continuously** at each
  subsequent issuance, applies to the **whole instrument** (no cherry-picking), and follows
  the investor's **election** rather than a calculation.
- **Mixed pre- and post-money SAFEs** are solved as one concave scalar fixed point, with a
  uniqueness proof, and **refused when the proof's condition fails** rather than guessed.
- **Governance** (`ovf.governance`): a Requisite Holders mandatory conversion as a
  holder-level sincere vote with no defaults, refusing non-unique stage payoffs and pivotal
  indifference within tolerance.
- **NVCA presets** (`ovf.presets`): `nvca_series_a()` with every bracketed choice a required
  argument, and `additional_series()` for a further series.

### Findings - Wave 3

- **Drag-along and protective provisions do not move cash.** Both gate whether a sale
  happens (Voting Agreement s.3.2(f), COI s.3.3.1), and a renegotiated carve-out is
  implemented by amending the charter before closing (COI fn 23), which is a different cap
  table the engine already prices. Neither becomes an engine input.
- **Payout monotonicity does not survive the vote.** In 1,246 of 3,000 generated tables a
  position's cash FELL as the exit rose under a collective-conversion term; without the
  term, none did at the same exits. A higher exit can flip the vote, and forced conversion
  then strips a dissenting series' preference. Exact searches over 252,039 vote and 218,331
  per-series instances found no second equilibrium payoff.
- **The NVCA model charter has no Series B.** It designates exactly one series and its own
  footnotes say the text must be revised for a second. A preset named `nvca_series_b` would
  assert something the document does not say, so the second-series constructor is not
  NVCA-attributed.
- **The roadmap's phrase "class-majority conversion" does not match the charter.** The
  operative vote is ALL preferred voting together, as-converted, and it is one-directional.

### Fixed

- `CapTable.fully_diluted_shares` silently counted the new discount-only and MFN SAFE forms
  as **zero shares**, reporting their holder at 0% and everyone else too high with no error.
  The guard was a list of two SAFE classes and failed the moment two more were added in a
  module it does not own. It is now structural and fails safe: any security that can still
  convert but holds no shares is refused, while a resolved instrument (a note settled to
  repay, a term loan) is allowed and contributes what it actually holds.

### Added - global-standard Wave 2a

- **Dividends** (`ovf.contracts.securities`, `ovf.waterfall.accrue_dividends`): cumulative
  and non-cumulative preferred dividends accruing to the same `as_of` as debt. Required
  with no default: the rate on the Original Issue Price, simple or compound accrual, day
  count, accrual start, and the conversion settlement - `forfeit_on_conversion`
  (NVCA Model COI s.4.3.3 and fn 46; Sage, Global Blood, Virtual Piggy) or
  `paid_in_kind` (Spark Therapeutics s.1.1, where the position becomes
  `shares x (1 + d)` on **both** branches, so it is a different position rather than a
  flag on conversion). `participation_cap_basis` defaults to NVCA fn 20 with
  `excludes_dividends` citing Virtual Piggy s.4.2; it is consulted only when a cap and a
  forfeit dividend coexist, and is always named in `WaterfallResult.assumptions`.
- **Financing events** (`ovf.financing`): `apply_dilutive_issuance` applies an
  anti-dilution adjustment to a cap table and returns a new one, with a per-position
  trace. No argument has a default; every position must be named protected or
  `UNPROTECTED`, and the exempted-securities decision comes from the caller.
- **OCF convertible notes** (`ovf.ocf`): `TX_CONVERTIBLE_ISSUANCE` of type NOTE is read
  into an unresolved `ConvertibleNote`, given caller-supplied `OcfNoteTerms`. Convertible
  seniority is read with its own comparator, because it runs opposite to
  `StockClass.seniority`. Transaction partition is now 4 applied / 7 ignored / 32 refused.
- CLI `--as-of`, required whenever a table holds debt or an accruing dividend.

### Findings - Wave 2a

- **Proposition 1** (`docs/dividends.md`, proved): a dividend-bearing table is *exactly
  the same game* as a dividend-free twin - under forfeit, liquidation multiple `m + d`
  with `d = accrued/invested`, the cap clamping at `min(m+d, c)` inside or becoming
  `c + d` outside; under paid-in-kind, the same table with `shares x (1 + d)`. Payoff
  uniqueness under dividends therefore *follows from* the existing result rather than
  merely surviving a search. The accompanying exact search over 878,746 instances found
  0 twin mismatches and 0 distinct exact payoff vectors; all 428 float flags were
  tolerance epsilon-equilibria whose dividend-free twin showed the identical flag.
- **Anti-dilution has no fixed point.** The NVCA charter fixes `CP1` and `A` "immediately
  prior to such issuance" and s.4.4.3 excludes anti-dilution adjustments from deemed
  issuances, so every protected series adjusts from one pre-issuance denominator. A test
  proves order-independence and shows the naive recompute-`A` reading disagrees with
  itself across orders ($211/146 vs $209/94).
- **An OCF v1.2.0 package cannot round-trip a convertible note's economics.** There is no
  maturity field, the qualified-financing threshold exists only as free text, and there is
  no compounding frequency. `ACTUAL_365` is undefined by OCF's own
  [issue #423](https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/issues/423),
  open since 2023-05-10 - a difference worth $219.18 on $1M at 8% over a period spanning
  2028. A named test asserts the round trip fails without caller-supplied terms.
- **OCF has no object for non-convertible debt**, so a term loan or venture debt facility
  cannot be written even though both rank ahead of all equity.

### Fixed

- `ovf.ocf.to_ocf` **silently dropped a dividend term**, so a round trip returned a
  position whose accruing claim had vanished: on a $20M exit that understated Series A by
  $801,095.89. `StockClass` has no dividend fields, so the writer now refuses such a class
  by name. Found only at integration, because the module that added dividends and the
  module that writes OCF were built in parallel by different workers; regression in
  `tests/test_integration_wave2.py`.

### Added — global-standard Wave 1

- **Debt at exit** (`ovf.instruments`): `DebtInstrument`, `VentureDebt` (exit fee) and
  `ConvertibleNote` (cap, discount, qualified-financing conversion, repayment at
  maturity, caller-stated exit treatment). Simple, stated-frequency compound and PIK
  accrual over ACT/365F or ACT/360. Settled by `waterfall.settle_debt` from net proceeds
  ahead of all equity, by ascending debt seniority, pro rata by claim within a tier.
  `WaterfallResult` gains `as_of` and `debt_settlements`; `CapTable.waterfall` and
  `waterfall_detailed` take `as_of`. Debt holds no shares, so ownership is unaffected.
  **No clock is read anywhere**: a table holding debt raises rather than assuming today,
  and an unresolved note is refused even at a zero exit.
- **Anti-dilution** (`ovf.antidilution`): broad-based and narrow-based weighted average,
  full ratchet, and the conversion-ratio identity, as pure functions. Neither adjusts
  unless the issue price is strictly below the current conversion price, and a price
  never moves up. Every component of the `A` denominator is a required argument: no
  public function has a default, and a test enforces that. Named compositions
  `BROAD_BASED_NVCA`, `BROAD_BASED_WITH_RESERVED_POOL`, `NARROW_BASED_OUTSTANDING_STOCK`.
- **Open Cap Table Format** (`ovf.ocf`): `from_ocf`, `import_ocf`, `load_ocf_package`,
  `to_ocf`, `write_ocf_package` against OCF v1.2.0 (tag commit `9f987b4`). Seniority is
  inverted per the verbatim schema text; the preference basis, participation-cap basis
  and common-class handling are each explicit conventions documented in `docs/ocf.md`.
  43 transaction types are partitioned 4 applied / 7 ignored / 32 refused.
- Documentation: `docs/debt.md`, `docs/antidilution.md`, `docs/ocf.md`, each with
  hand-derived fixtures and its own "Not modelled" list.

### Changed

- `engine_version` is now `waterfall-v3`. A cap table without debt produces
  byte-identical payouts, input hash, assumptions and equilibrium surveys — a 141-case
  before/after snapshot was checked — so the bump marks a semantic extension rather than
  a calculation change: a new claim class now ranks ahead of all equity.
- `jsonschema` and `referencing` added to the `dev` extra. They are used only by the
  optional OCF schema-validation test, which skips unless `OCF_SCHEMA_DIR` points at the
  `schema/` directory of an OCF **v1.2.0** checkout. Schema `$id` values are
  version-pinned, so a checkout on `main` will not match; the test now says so.

### Findings

- **Participating-uncapped preferred is not expressible in OCF v1.2.0.** `StockClass` has
  no `participating` flag, only `participation_cap_multiple`. The writer refuses such a
  class rather than emitting one that understates the holder or inventing a cap.
- OCF's own v1.2.0 sample package cannot be read even with `ignore_common_preference_fields`,
  and its `Transactions` file fails OCF's own file schema:
  `IssuerAuthorizedSharesAdjustment` is missing from the `TransactionsFile` `oneOf` at
  both v1.2.0 and `main`.
- `StockClass.seniority` (higher number, higher priority) and `ConvertibleIssuance.seniority`
  ("1 being highest seniority") run in opposite directions inside the same OCF version.

### Added

- `enumerate_equilibria` and `EquilibriumSurvey`: exhaustive enumeration of every pure
  conversion equilibrium for one exit, reporting whether the payout is unique across
  them. Exponential in the number of preferred positions and refused above
  `max_positions` (default 12).
- `multi_position_holders`, also reported on `WaterfallResult`: discloses holders
  owning several preferred positions, where the independent-position assumption is
  weakest. A disclosure, not a coordinated-holder model.
- Command-line demo, `python -m ovf` and an `ovf` console script, with `waterfall`,
  `sweep`, `equilibria` and `safe` subcommands. Every subcommand prints the assumptions behind its result. The
  `sweep` output names the exit range over which common receives nothing.
- Named fixture suites with hand derivations: twelve exit-waterfall cases covering
  conversion thresholds, ties, capped and uncapped participation, stacked and
  pari-passu seniority, the common dead zone and the unallocated pool; five SAFE cases
  covering a binding cap, a down round, a pool top-up, two independent SAFEs and the
  pre-money contrast. Derivations in `docs/fixtures.md`.
- Adversarial conversion tests: larger games, knife-edge exits, identical classes,
  zero-common tables, search-budget enforcement and agreement between the solver and
  exhaustive enumeration.
- `docs/findings.md` — empirical results on the conversion game, including that
  multiple equilibrium profiles are common while the equilibrium payout was unique in
  every enumerated instance. Stated as evidence, not as a theorem.
- `docs/limitations.md` — what the model does not represent, and why each omission
  changes a real payout.
- `docs/deferred-scope.md` — specifications that must be settled before existing
  pools, MFN and discount-only SAFEs, mixed SAFE types, the other Cooley conventions
  and multi-round financings are implemented.
- `docs/walkthrough.md` — a worked path from a SAFE round to an exit.
- Issue templates for calculation disagreements and usage feedback.

### Changed

- `common()` now defaults to `price=0.0` rather than a nominal `0.0001`. A founder cost
  basis is normally unknown, and a nominal par value produced a meaningless
  `effective_multiple` of tens of thousands of times. With a zero basis the multiple is
  reported as undefined (`None`). Allocation is unaffected. Pass the real purchase
  price when a multiple is wanted.

### Notes

- No existence, uniqueness or convergence theorem is claimed for the conversion game.
  See `docs/findings.md` for what the evidence does and does not reach.
- Fixtures are source-derived and **not yet independently reviewed**; `reviewed_by` is
  empty in both fixture modules.
