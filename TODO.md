# OVF / Equilibria · Current TODO

Canonical plans: [roadmap](docs/roadmap.md), [six-part launch plan](docs/launch-plan.md).
Scope boundaries: [limitations](docs/limitations.md), [deferred scope](docs/deferred-scope.md).
Evidence: [findings](docs/findings.md), [fixture derivations](docs/fixtures.md).
Calculation scope: [semantics](docs/semantics.md). Status reflects implementation;
public launch requires the acceptance evidence below.

## 1. Review corrections — implemented, launch validation continues

- [x] Reject duplicate security IDs; aggregate repeated SAFE holders.
- [x] Reject nonfinite inputs, zero caps, invalid pool allocations and unsupported exits.
- [x] Correct post-money SAFE dilution and cap/round/discount comparison.
- [x] Specify pre-money capitalization and replace unchecked iteration with a bracketed solve.
- [x] Provide an explicit SAFE financing → post-round cap table → exit workflow.
- [x] Exclude unallocated pool capacity from cash payouts; require settlement terms for grants.
- [x] Separate cap table snapshots and the waterfall solver.
- [x] Refresh best-response payoffs and verify unilateral deviations before returning.
- [x] Expose convergence, tolerance, conservation error, assumptions and input fingerprint.
- [x] Separate proceeds share (`payout_pct`) from equity ownership; undefined MOIC is `None`.
- [x] Add financial regressions and a separate exact oracle for small conversion games.
- [x] Correct README, research claim status, Pareto notation and knowledge-base errors.
- [x] Move planning into project-relative documents and add a CI configuration.

## 2. First launch: waterfall-engine / Equilibria

- [x] Archive source-derived contract fixtures with published derivations
      ([fixtures](docs/fixtures.md), `tests/fixtures.py`, 12 cases).
- [~] Define share-class voting and holder/position boundaries. Boundary is specified
      in [semantics](docs/semantics.md) and [limitations](docs/limitations.md), and
      `WaterfallResult.multi_position_holders` discloses where the independent-position
      assumption is weakest. **Domain-reviewer confirmation still outstanding.**
- [x] Stress larger/adversarial conversion games; add search-guard fixtures
      (`tests/test_conversion_stress.py`, [findings](docs/findings.md)). The checked-in
      fixture exercises the iteration guard. Larger historical search counts await
      reproducible generators, seeds and output artifacts; they are not launch evidence.
- [x] Publish `enumerate_equilibria` so multiplicity and payout uniqueness are
      checkable by any user on their own cap table.
- [x] Prepare a user-facing walkthrough and feedback template
      ([walkthrough](docs/walkthrough.md), `.github/ISSUE_TEMPLATE/`).
- [x] Prepare changelog and issue workflow ([CHANGELOG.md](CHANGELOG.md)).
- [x] Release only the supported scope in [launch plan](docs/launch-plan.md);
      unsupported cases raise and are listed in [limitations](docs/limitations.md).

Remaining, and **not doable without a person outside development**:

- [ ] Independent review of the fixtures: term shapes and arithmetic. `reviewed_by` is
      empty in both fixture modules until then.
- [ ] Domain-reviewer sign-off on the holder/position and class-voting boundary.
- [ ] Clean installation and usage trial by someone outside development.
- [x] Establish the public repository. `ogulcan-ozyavuz/equilibria-waterfall` exists and
      carries the work. **No alpha is tagged**, so that half of this item is still open.
- [x] Run the configured CI on the public repository. Both matrix jobs (3.11 and 3.12)
      pass on the branch and on its merge with `main`, which is the first evidence for
      this repository that does not come from one developer's machine.

Private repository preparation does not complete either public-launch item.

## 3. Second launch: safe-math

- [x] YC cap-only fixtures with hand derivations, including a down round where the
      round price beats the cap, a pool top-up and two independent SAFEs
      ([fixtures](docs/fixtures.md) S1-S5, `tests/safe_fixtures.py`).
- [x] CLI with explicit assumptions (`python -m ovf safe`, `tests/test_cli.py`).
- [x] Existing pools, promised/granted options, MFN and discount-only forms:
      specified in [deferred scope](docs/deferred-scope.md) §1-§2 with the open
      questions that must be answered before any of them is implemented.
- [x] Mixed SAFE types and Cooley's other conventions: specified in
      [deferred scope](docs/deferred-scope.md) §3-§4. Both remain rejected at runtime
      rather than guessed.
- [x] Financing events that preserve existing preferred and negotiated rights:
      specified in [deferred scope](docs/deferred-scope.md) §5.

Remaining, and **not doable without a person outside development**:

- [x] All five deferred-scope items closed (Wave 3, `ovf.rounds`). Existing pools and
      granted options, discount-only and MFN SAFEs, mixed pre/post types, Cooley's three
      conventions, and preserving existing preferred through a financing. See
      [rounds](docs/rounds.md); [deferred-scope](docs/deferred-scope.md) is now a
      closed-item record and the place the next deferred item gets specified first.
- [ ] Independent review of the S1-S5 derivations against the YC document.

## 4. Third launch: global-standard (debt, anti-dilution, governance, OCF)

Wave 1 landed 2026-09-15 (three parallel workers, strict file ownership, coordinator
integration). Wave 2 is everything that needs the new waterfall and was deliberately
held back to avoid three workers editing one core file.

- [x] `DebtInstrument` & `ConvertibleNote`: seniority-ordered settlement ahead of all
      equity, simple / stated-frequency compound / PIK accrual, maturity triggers.
      Explicit `as_of`; no clock is read. See [debt](docs/debt.md).
- [x] Venture Debt / term loan: exit fee supported. **Warrant attachments excluded** and
      documented, because warrant coverage materially changes the lender's return.
- [x] Anti-dilution engine: broad-based and narrow-based weighted average and full
      ratchet, as pure functions with no default arguments. See [anti-dilution](docs/antidilution.md).
      **Pay-to-play excluded**: it is a governance action, not a price formula.
- [x] OCF adapter: v1.2.0 read/write, round-trip tests, 43 transaction types partitioned
      4 applied / 7 ignored / 32 refused. See [ocf](docs/ocf.md).
- [x] Anti-dilution applied at issuance to a new CapTable snapshot, using pre-issuance
      capitalization and explicit charter facts. See [financing](docs/financing.md).
      Independent domain review remains outstanding.
- [x] Cumulative dividends: accrued preference additions, forfeiture on conversion
      and paid-in-kind settlement with explicit cap conventions. See
      [dividends](docs/dividends.md). Independent domain review remains outstanding.
- [x] Governance & collective action (Wave 3). Established from the charter that
      drag-along and protective provisions only GATE a sale and do not move cash, and that
      a renegotiated carve-out is a different cap table. The one mechanism that moves cash,
      a Requisite Holders mandatory conversion, is modelled as a holder-level sincere vote.
      See [governance](docs/governance.md). Note the roadmap's phrase "class-majority
      conversion" does not match the charter: the vote is ALL preferred together.
- [x] NVCA model term sheet presets (Wave 3). `presets.nvca_series_a()` with every
      bracketed choice required, plus `additional_series()`, because the model charter
      designates exactly one series and says so in its own footnotes.
- [ ] Carta/Pulley round-trip: no real export has been obtained, so this is untested
      against anything except fixtures written here and OCF's own sample.

Findings from Wave 1 worth carrying forward:

- OCF v1.2.0 **cannot express participating-uncapped preferred**; the writer refuses it.
- OCF's own v1.2.0 sample package is not readable, and its `Transactions` file fails
  OCF's own file schema (`IssuerAuthorizedSharesAdjustment` missing from the
  `TransactionsFile` `oneOf`, at both v1.2.0 and main).
- `StockClass.seniority` and `ConvertibleIssuance.seniority` run in opposite directions
  within the same OCF version. Any system reading both must not share one comparator.
- `engine_version` moved to `waterfall-v3`. A cap table without debt produces
  byte-identical payouts, hash and diagnostics; the bump marks that a new claim class now
  ranks ahead of all equity.

## 5. Fourth launch: ovf-mcp (AI Agent Adapter)

- [ ] Typed waterfall, SAFE, debt, and cap table tools exposing calculation traces and explicit assumptions.
- [ ] Input parameter validation and structured domain error handling for LLM agents.
- [ ] Preserved trace diagnostics (assumptions, conversion deviation checks, residual errors).
- [ ] End-to-end replayable demos on Claude Desktop and Cursor.
- [ ] Distribution packaging (uvx / Smithery.ai ready config).

## 6. Subsequent research work, gated by evidence

- [x] open-pme (2026-09-15, `ovf.pme`, engine `pme-v1`): dated signed flows, TVPI/DPI/RVPI,
      a certified XIRR root policy, KS-PME, Direct Alpha, PME+, the Long–Nickels ICM, a
      labelled mPME reconstruction, a one-call report, CSV loaders and a CLI. See
      [pme](docs/pme.md), the [source ledger](docs/pme-sources.md), the
      [fixtures](docs/pme-fixtures.md) and the decision record `docs/pme-contract.md`.
      Launch gate items met: documented day count and total-return convention, duplicate-date
      handling, no/multiple IRR roots, incomplete-NAV cases, independent reference fixtures.
      Remaining, **not doable without a person outside development**:
  - [ ] Independent review of PME-F1–F19 and of the source ledger's `UNVERIFIED` rows
        (S&J 2015 full text, the published 2023 Direct Alpha text, Rouvinez 2003).
  - [ ] Two research workflows reproduced by someone else, with their inputs documented.
  - [ ] Recallable-distribution policy (gross legs only in `pme-v1`) and an exact-decimal
        input path, if users need them.
- [ ] Subscription-line adjustment only with observed borrowing, repayment, fees and calls.
- [ ] Separate Takahashi–Alexander cash-flow simulator from performance metrics.
- [x] open-opm: analytical breakpoints, OPM and Backsolve; evaluate DLOM variants separately.
      Landed as `ovf.opm`. Breakpoints are derived in exact rational arithmetic and then
      verified against the engine either side of every candidate, rather than assumed from
      the cap table. The allocation refuses a table whose payoff the method cannot
      represent, which under a Requisite Holders vote means a **step**, not merely a
      negative weight. The four marketability discounts are separate, unblended, and each
      checked against simulation of the payoff it claims to price.
      Verified against an independently written exact-rational oracle and quadrature
      allocator that imports none of the modules under test: exact agreement on 36,009
      breakpoints and 2,441 steps, allocation matching integration to 6.3e-15 of equity
      value, and five defects found and fixed. The method is refused on 33.9% of generated
      governed venture tables and on none of 4,000 without the term; where it refuses, the
      unchecked construction would be off by a median 30% of a class's value while still
      conserving value exactly. See [findings](docs/opm-findings.md).
      Still open on this row, and each needs a person:
      - [ ] Independent review of the OPM fixtures and of the DLOM attributions. Every
            citation in `docs/dlom.md` is recalled and unverified against the publication;
            the Finnerty 2002-versus-2012 difference is explicitly not established.
      - [ ] Reproduce a third-party worked example of the method. None was reproduced,
            because no edition of the AICPA guide was consulted.
      - [ ] Decide whether the 8-in-60 governed tables that `ovf.governance` refuses over a
            whole interval should be representable at all, or stay refused.
- [ ] vc-powerlaw: common tail notation, estimand/data feasibility, CSN baseline, simulation recovery.
- [ ] Selection models, competing risks and decision policies: research work after data feasibility.
- [ ] Formal equilibrium existence/uniqueness OR counterexamples; no promised theorem
      outcome. Empirical status recorded in [findings](docs/findings.md): payout
      uniqueness held across every enumerated instance; no proof and no
      counterexample yet.
- [ ] Independent benchmark evaluator, dataset documentation and baseline results before a paper claim.

## 7. Publication and sustainability

- [ ] JOSS: eligibility review after more than six months of active public development and demonstrated research use.
- [ ] CFR: choose a specific reproducible result and confirm necessary data before committing.
- [ ] NeurIPS: distinct benchmark contribution and track requirements assessed for the actual submission year.
- [ ] Versioning, DOI archival and explicit documentation/data licensing policy.
- [ ] Funding eligibility and maintenance capacity review; no precommitted grant outcome.

A task is complete when its supported scope, source/derivation, automated checks and
limitations are documented. Launch is a separate milestone requiring external use.
