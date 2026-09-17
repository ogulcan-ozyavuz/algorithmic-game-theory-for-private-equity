# Deferred scope: specifications before implementation

Status 2026-09-15. This document is where an item outside the supported scope is specified
**before** anything is built for it. Every item that ever appears here changes a
capitalization denominator or a payout order, and guessing produces numbers that look
right and are not. An item is ready to implement when its open questions are answered from
a source and at least one source-derived fixture with a hand derivation exists. An item
whose questions cannot be answered from a source stays refused, with the reason and the
evidence written here; that is a closed item too.

## Open items

None at present. The next deferred item is specified here, in the same form as the record
below, before any code is written for it.

## Closed items

All five items first specified here were closed on 2026-09-15 by `ovf.rounds` and additions
to `ovf.contracts.safes`. The full answers, the source text quoted verbatim, the hand
derivations and the list of what remains unsupported are in [rounds](rounds.md). Each item
below records what it turned out to be.

### 1. Existing option pool and granted options at a financing: supported

- **Source.** The YC post-money Company Capitalization "Includes all (i) issued and
  outstanding Options and (ii) Promised Options" and "the Unissued Option Pool, except that
  any increase ... in connection with the Equity Financing will only be included to the
  extent that the number of Promised Options exceeds the Unissued Option Pool". An existing
  reserve counts in the SAFE denominator; the increase does not.
- **Answer.** The pool change is an explicit `PoolChange` with no default: a target
  post-round **unallocated** fraction, or an increase by a stated number of shares. The NVCA
  model term sheet uses both forms, and they differ whenever anything else moves. Granted
  options count gross, one share per option, as the YC definition counts them.
- **Fixtures.** EP1; YC1-Q2 and YC1-Q2t (the YC User Guide's Example 1 as a fixed increase
  and as its stated 10% target).
- **Remains unsupported.** Promised options beyond the reserve; the treasury method; a target
  on the whole pool; a pool placed outside the pre-money.

### 2. MFN and discount-only SAFEs: supported

- **Discount-only.** `PostMoneyDiscountSAFE`: converts at the lowest Standard Preferred price
  times YC's Discount Rate (`1 − discount`). It interacts with capitalization because it is
  one of the "other Safes" in a capped Safe's Converting Securities. Fixtures DO1, DO2, and
  Cooley's worked example (CM).
- **MFN.** The text settles all three open questions. It resolves **continuously**, at each
  issuance of a Subsequent Convertible Security, with an election "within 10 days of the
  receipt of the MFN Notice", not once at the round. It applies to the **whole instrument**,
  cap and discount together: the Safe is amended "to be identical to the instrument(s)
  evidencing the Subsequent Convertible Securities" (User Guide: no "cherry-picking").
  And the amendment follows the **Investor's determination** that the later terms are
  "preferable", which is an election, not a calculation. `MFNResolution` records the issue
  order and each holder's election, with no default; `resolve_mfn` rewrites earlier
  instruments before conversion. Fixtures MF-none, MF-cap and MF-disc: three instruments in
  issue order.
- **Remains unsupported.** The 10-day window and notice timing; electing a non-SAFE
  convertible or an already-amended instrument; MFN at a Liquidity Event.

### 3. Mixed SAFE types in one round: supported

- **Fixed point.** Parametrised by post-round fully diluted shares `T`, both SAFE
  denominators, the inverse price and the pool are affine in `T`, each SAFE's share count is
  convex, and the balance `g(T)` is concave with `g(0) < 0`.
- **Uniqueness.** If the slope of `g` for large `T` is positive, `g` is strictly increasing
  and the solution is unique; the proof is in [rounds](rounds.md). Otherwise the round is
  refused, and the margin is reported on every result.
- **Solver.** Bracketed bisection, an exact solve on the final affine piece, and the same
  share-conservation check as the legacy solver, plus a pricing-identity check.
- **Fixtures.** MX1, MX2, and the YC User Guide's Example 2 (YC2-Q2 and YC2-Q5), which mixes a
  pre-money and a post-money Safe and is reproduced within the Guide's rounding.
- **Remains unsupported.** The legacy `solve_priced_round_with_safes` still refuses mixed
  types, by design. A table with a non-positive margin is refused even where a solution may
  exist. The original pre-money form's text was not read; its capitalization comes from
  the User Guide's comparison table.

### 4. Cooley's other pricing conventions: supported

- **Answer.** `PricedRound.convention` has one value per method and no default:
  `pre_money_method`, `percentage_ownership_method`, `dollars_invested_method`. The
  difference is negotiated, not computed. The legacy solver's convention is the
  percentage-ownership method.
- **Fixtures.** CM-pre, CM-pct and CM-dol reproduce Cooley's own worked example: three
  answers to one round, each matching the article's published figures. CS-pre, CS-pct and
  CS-dol repeat them on S1's capped SAFE.
- **Remains unsupported.** Negotiated conventions other than these three.

### 5. Preserving existing preferred through a financing: supported, with one refusal

- **Answer.** An event object applied to a table, consistent with `ovf.financing`:
  `apply_priced_round(table, *, terms, protection, mfn)`. Existing positions are carried as
  the same objects with their own terms. The new series' seniority is a `SeniorityPlacement`
  with no default (senior to all, pari passu with a named series, or explicit). Whether
  converting SAFEs take their own Safe Preferred series or the new series at the round price
  is a required `safe_series` choice. The YC forms prescribe the first; the second moves
  exit payouts (MR-X3).
- **Fixture.** MR: a SAFE, then a Series A, then a Series B down round, with the table
  asserted after each event and exits at $6M (three seniority and series variants) and at
  $141M.
- **Refused.** A round that issues any share, new money or SAFE conversion, below a
  **protected** existing series' conversion price. The round's price may depend on its own
  anti-dilution shares, and the term sheet does not say whether they are in the
  "fully-diluted pre-money". A SAFE converting below that price also raises NVCA 4.4.3's
  deemed-issuance question. Neither is settled by the sources read.
  `ovf.financing.apply_dilutive_issuance` remains the tool for an adjustment at a stated
  price.
- **Remains unsupported.** Pay-to-play and shadow classes; convertible notes converting in
  the round; paid-in-kind preferred in a round table.

---

## Cross-cutting requirement

Every item added to this document must arrive with: the source text or convention it
implements, a hand derivation, an automated fixture, an entry removed from
[limitations](limitations.md), and an explicit statement of what remains unsupported. An
implementation that does not also shrink the limitations list has not finished.
