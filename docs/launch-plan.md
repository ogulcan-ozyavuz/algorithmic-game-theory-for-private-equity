# Six-part launch plan · revised proposal

Updated 2026-09-15. Status: local planning draft; no launches, submissions or outreach
have been performed. Owner: Ogulcan. All names are working identities; package/domain
availability has not been checked.

## Assessment

Splitting the work into user problems creates clearer demos and earlier feedback.
The launch sequence should expose one dependable shared core. The suggested 6–20 hour
budgets omit contract validation, edge cases, documentation, external review and support.
“First”, “error-free”, “zero hallucination”, “thousands of stars” and guaranteed publication
are not supported promises. Retire the “80% complete” claim until acceptance criteria
have been measured.

Start with one repository, one `ovf` distribution and the existing `equilibria` import.
Give each module its own documentation page, example and announcement. Split packaging
only when stable interfaces and separate demand justify the maintenance overhead.

## Recommended order

**waterfall-engine → safe-math → global-standard → thin ovf-mcp → open-pme → open-opm → vc-powerlaw**.

Data feasibility for power-law research starts early even though its launch is later.
PME and OPM can be reprioritized if a qualified pilot and data are available. The thin
MCP adapter is placed right after global-standard so agents can evaluate full-spectrum
venture contracts without scope bottlenecks.

### 1. waterfall-engine / Equilibria

- **User outcome:** explain who receives cash at an exit and why.
- **Initial scope:** common/preferred, integer seniority, pari-passu sharing, caps,
  conversion ratios and independent-position conversion checks.
- **Limits:** no fund carry, debt, unconverted SAFE liquidity events, granted-option
  settlement, class voting or coordinated holder decisions. “Carried interest” is a
  fund-level topic and is not this module's feature.
- **Launch gate:** independent small-game oracle, sourced contract fixtures, explicit
  convergence failures, net-proceeds reconciliation, clean installation and external review.
- **Demo:** an exit-value sweep with payout components, assumptions and verification status.
- **Audience:** founders, startup finance developers and transaction specialists.
- **Draft headline:** “Show HN: Equilibria — an open-source startup exit waterfall calculator with conversion checks.”
- **Success evidence:** proposed pilot target of three independent completed runs and
  at least one substantive calculation review. These are targets, not achieved metrics.

### 2. safe-math

- **User outcome:** understand financing dilution and reproduce the share-price calculation.
- **Initial scope:** one documented financing convention, homogeneous capped SAFEs,
  common-only starting capitalization, cap/discount/round-price comparison and a new pool.
- **Limits:** existing pools/options, mixed SAFE types, MFN, discount-only YC forms and
  the other Cooley conventions require additional specifications. A custom capped-plus-
  discount contract must be labeled as such.
- **Launch gate:** independently checked cap-only, down-round and pool scenarios; share
  conservation; clear unsupported-case errors; explicit round-to-exit example.
- **Demo:** before/after ownership plus the capitalization definition and conversion price.
- **Audience:** pre-seed founders and startup finance specialists.
- **Draft headline:** “Show HN: SAFE dilution scenarios with explicit cap, round and option-pool assumptions.”
- **Success evidence:** five proposed pilot scenarios reproduced, including at least one
  external cross-check. Compare calculator outputs only after aligning conventions.

Cooley describes negotiated economic conventions, not three errors that one solver can
make disappear. [Cooley explanation](https://www.cooleygo.com/calculating-share-price-outstanding-convertible-notes-or-safes/)

### 3. global-standard

- **User outcome:** model real-world institutional VC deals including debt, anti-dilution, class governance and OCF data.
- **Initial scope:**
  - `DebtInstrument` & `ConvertibleNote` with accrued interest, maturity triggers and seniority-0 payout.
  - Anti-dilution engines: broad-based & narrow-based weighted average, full ratchet, and pay-to-play rules.
  - Class governance & collective action: class-majority conversion, drag-along and protective veto constraints.
  - OCF (Open Cap Table Standard) JSON parser/serializer and NVCA model term sheet defaults.
- **Limits:** multi-jurisdictional tax structuring, bankruptcy reorganization outside absolute priority rule.
- **Launch gate:** NVCA reference fixture reconciliation, OCF round-trip validation, mixed-integer solver stability, domain legal counsel review.
- **Demo:** an end-to-end multi-round company lifecycle: Convertible Note → Series A → Series B down-round with anti-dilution → exit.
- **Audience:** startup CFOs, transaction lawyers, venture investors and cap-table engineers.
- **Draft headline:** “Show HN: Open venture framework with institutional debt, anti-dilution and Open Cap Table (OCF) support.”
- **Success evidence:** three complex real-world cap tables reproduced from OCF files with identical payouts.

### 4. ovf-mcp — thin adapter over complete contracts

- **User outcome:** invoke verified calculations from an AI agent (Claude, ChatGPT, etc.) across the full contract suite.
- **Initial scope:** typed waterfall, SAFE, debt, anti-dilution and cap table calls, structured errors, parameter validation and calculation traces.
- **Limits:** MCP does not guarantee correct interpretation, correct tool inputs or zero
  hallucination. Authentication, storage or write operations are separate scope if introduced.
- **Launch gate:** schema/argument tests, invalid-input scenarios, preserved model assumptions
  and a repeatable end-to-end demo against the supported client versions.
- **Draft headline:** “Show HN: Let AI agents run reproducible, zero-hallucination startup waterfall and SAFE calculations.”
- **Success evidence:** replayable runs in two proposed client integrations, with published
  success/failure definitions and tool/model versions.
- **Research follow-up:** a separate benchmark needs independently checked answers, tasks,
  evaluation protocol and baselines. An MCP wrapper alone is not a NeurIPS paper claim.

### 5. open-pme

- **User outcome:** reproduce a fund's dated cash-flow metrics and public-market comparison.
- **Initial scope:** signed dated flows, TVPI/DPI/RVPI, XIRR root policy, KS-PME and Direct Alpha.
- **Separate extensions:** Takahashi–Alexander forecasting, fund carry and subscription-line
  reconstruction. A borrowing adjustment needs drawdowns, repayments, interest, fees and
  capital-call dates; net cash flows alone may not identify a unique unlevered history.
- **Launch gate:** documented day count and benchmark total-return convention, duplicate-date
  handling, no/multiple IRR roots, incomplete NAV cases and independent reference fixtures.
- **Draft headline:** “Open-source private-market performance metrics with reproducible cash-flow conventions.”
- **Audience:** fund analysts, LP research teams and academics.
- **Success evidence:** two proposed research workflows reproduced and their inputs documented.
- **Publication:** assess JOSS after eligibility and use evidence exist. Do not characterize
  every subscription line as fraud or promise general ILPA compliance.

### 6. open-opm (working name replacing open-409a)

- **User outcome:** inspect how a specified payout structure affects option-based allocation.
- **Initial scope:** verified analytical breakpoints, OPM call-spread valuation and Backsolve.
- **Separate extensions:** one reviewed DLOM method at a time; PWERM and report generation.
- **Launch gate:** independent valuation fixtures, sum-of-class-value reconciliation, limiting
  volatility/time tests, calibration diagnostics and explicit valuation assumptions.
- **Draft headline:** “An open-source OPM and Backsolve engine for private-company equity research.”
- **Audience:** valuation engineers, researchers and qualified valuation practitioners.
- **Success evidence:** a specialist reproduces an example and reviews the assumptions.
- **Positioning:** a calculation library is not automatically a complete 409A valuation service.
  Retire unsupported price comparisons and 409A/IPEV compliance guarantees.

### 7. vc-powerlaw

- **User outcome:** assess which tail models the available observations can support.
- **Initial scope:** a sourced CSN workflow using existing statistical libraries, explicit
  density/tail notation, cutoff estimation, goodness-of-fit/model comparisons and simulation tests.
- **Research extensions:** Hill/GPD sensitivity, dependence/censoring adjustments and NumPyro
  selection models after identifiability and parameter-recovery studies.
- **Launch gate:** distinguish density exponent alpha from tail exponent beta=alpha-1;
  define the measured return/value, observation window and sampling mechanism; document data
  access, sample limitations and the possibility of inconclusive results.
- **Draft headline:** “A reproducible workflow for testing venture-return tails, with selection and data limitations made explicit.”
- **Audience:** financial econometricians and research engineers.
- **Success evidence:** reproduce a prespecified result or report why available data cannot
  identify it. No predetermined rejection of a “VC myth” is required.
- **Publication:** CFR is a candidate venue after a concrete replication contribution exists.

## Launch operations for each module

1. Freeze supported scope and publish the assumptions page.
2. Complete fixtures, independent review and installation checks.
3. Prepare one short runnable demo, expected outputs and a feedback template.
4. Tag an alpha and document compatibility changes; publish only after gates are met.
5. Share the problem-specific demo in relevant communities, following their posting rules.
6. Triage feedback and issue a correction release before starting another launch.

Proposed channel hypotheses: a runnable developer demo for Show HN; founder-oriented
SAFE scenarios for startup communities; traceable valuation/metric examples for specialist
networks. Reach and virality are unmeasured. No messages or posts have been sent.

Track completed external runs, repeat use, independently confirmed discrepancies and
response time to calculation bugs. GitHub stars are a secondary discovery metric.
If an announced calculation defect is confirmed, flag the affected version/examples,
ship a fix with a regression and document the corrected assumptions/results.

## Evidence and claims policy

- A current [CarryFlow repository](https://github.com/bhupendra05/carryflow) describes related
  PE/VC calculations. Its existence defeats an unqualified zero-repository claim; quality,
  coverage and licensing still need a comparative review.
- [YC SAFE definitions](https://www.ycombinator.com/safe) establish dilution timing.
- [JOSS requirements](https://joss.readthedocs.io/en/latest/submitting.html) govern submission
  eligibility; development speed does not waive public history or research-use requirements.
- All headlines above are drafts. No package publication, conference submission or
  promotional outreach is part of this edit.
