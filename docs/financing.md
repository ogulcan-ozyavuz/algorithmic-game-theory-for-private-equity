# Financing: applying an anti-dilution adjustment to a cap table

Status 2026-09-15, engine `financing-v1`, module `ovf.financing`. One issuance goes in
with the charter facts that decide its effect. A new `CapTable` comes out, holding the
issued securities and a replacement `PreferredStock` for every protected position whose
conversion price fell. The input table and its securities are not modified.

The conversion price is computed by [`ovf.antidilution`](antidilution.md). This module
decides which positions it is computed for, against which denominator, and turns each new
price into a `conversion_ratio`. Every expected number below is derived by hand here, then
asserted in `tests/test_financing.py` against the fixtures in `tests/financing_fixtures.py`.
Each derivation was rechecked with exact rational arithmetic before it was written down;
none was copied from engine output.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty
on every fixture.

## What it does

```python
from ovf.antidilution import BROAD_BASED_NVCA
from ovf.financing import (
    UNPROTECTED, ExemptionDetermination, NewIssue,
    apply_dilutive_issuance, weighted_average_protection,
)

result = apply_dilutive_issuance(
    table,
    issue=NewIssue(securities=(series_b,), aggregate_consideration=5_000_000),
    protection={"seed": UNPROTECTED,
                "series_a": weighted_average_protection(BROAD_BASED_NVCA)},
    exemption=ExemptionDetermination(exempted=False, basis="cash sale of Series B"),
)
result.table                           # the new snapshot
result.position("series_a").outcome    # "adjusted"
```

| Name | Purpose |
|---|---|
| `apply_dilutive_issuance(table, *, issue, protection, exemption)` | One issuance applied to a table; returns `FinancingResult` |
| `adjust_position(position, *, protection, capitalization, issuance, exemption)` | The same step for one preferred position |
| `capitalization_before_issue(table)` | The five components of `A`, counted from a table |
| `AntiDilutionProtection`, `weighted_average_protection(definition)`, `FULL_RATCHET`, `UNPROTECTED` | One position's charter term |
| `ExemptionDetermination(exempted, basis)` | The caller's Exempted Securities decision |
| `NewIssue(securities, aggregate_consideration)` | What was issued and what the company received |
| `FinancingResult`, `PositionAdjustment` | New table, pre-issuance capitalization, per-position trace, input hash, assumptions |

Each `PositionAdjustment` records the Original Issue Price, the conversion price, ratio
and as-converted shares before and after, the `ovf.antidilution` result, and an outcome:
`adjusted`, `not_triggered`, `exempted` or `unprotected`.

## The architecture question: is there a fixed point?

Adjusting one series raises its as-converted share count. That count is part of the `A`
denominator used for every other protected series. If `A` had to include the other
series' adjusted counts, the adjustments would form a simultaneous system, possibly a
fixed point like the conversion equilibrium in [findings](findings.md).

**The charter text says `A` is taken before the issuance and before anything it
triggers, so there is no system to solve.** The text read is the
[NVCA Model Certificate of Incorporation, October 2025](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx),
Article Fourth, Section 4.4, downloaded and read for this work. Four passages decide it.

1. **`CP1` and `A` are both fixed immediately prior to the issue.** From the definitions
   under 4.4.4 (broad-based weighted-average alternative), verbatim:

   > "CP1" shall mean the Conversion Price of such series of Preferred Stock in effect
   > immediately prior to such issuance or deemed issuance of Additional Shares of Common
   > Stock;
   >
   > "A" shall mean the number of shares of Common Stock outstanding immediately prior to
   > such issuance or deemed issuance of Additional Shares of Common Stock (treating for
   > this purpose as outstanding all shares of Common Stock issuable upon exercise of
   > Options outstanding immediately prior to such issuance or deemed issuance or upon
   > conversion or exchange of Convertible Securities (including the Preferred Stock)
   > outstanding (assuming exercise of any outstanding Options therefor) immediately prior
   > to such issue);

   The preferred enters `A` as the common "issuable upon conversion" immediately prior
   to the issue, which is the count at the conversion prices then in effect.

2. **The adjustment happens with the issue, not before it.** 4.4.4: "the Conversion
   Price for such series of Preferred Stock shall be reduced, concurrently with such
   issue". An adjustment that is concurrent with the issue is not "immediately prior"
   to it, so it cannot be inside another series' `A`.

3. **One series' adjustment is not a new issuance that re-triggers another.** Preferred
   Stock is a Convertible Security. 4.4.3 treats a change in the number of common shares
   issuable on a Convertible Security as a deemed issuance only when it comes from "an
   amendment to such terms or any other adjustment pursuant to the provisions of such
   Option or Convertible Security (but excluding automatic adjustments to such terms
   pursuant to anti-dilution or similar provisions of such Option or Convertible
   Security)". The anti-dilution increase in Series A's conversion shares is exactly
   such an excluded automatic adjustment. Separately, the Exempted Securities list in
   4.4.1 includes "shares of Common Stock actually issued upon the conversion or exchange
   of Convertible Securities, in each case provided such issuance is pursuant to the
   terms of such Option or Convertible Security", so conversion shares never trigger.

4. **Each series is tested and adjusted on its own.** 4.4.4 applies when shares are
   issued "for a consideration per share less than the Conversion Price of a series of
   Preferred Stock in effect immediately prior to such issuance", and then reduces "the
   Conversion Price for such series". The 2025 model is written for several series. The
   [June 2019 model](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Document-Certificate-of-Incorporation.docx)
   is written for Series A alone ("the Series A Conversion Price in effect immediately
   prior to such issuance"). Its `A` uses the same "immediately prior" wording, but it
   does not address several series, so the multi-series conclusion rests on the 2025
   text.

**Consequence.** For each protected series `i`, with `A₀` the pre-issuance `A`:

```
CP2_i = CP1_i × (A₀ + B_i) / (A₀ + C),   B_i = consideration / CP1_i
```

`CP2_i` depends on its own `CP1_i`, on `A₀`, on `C` and on the consideration. Nothing
about any other series' adjustment appears. The adjustments are independent, the order
of application is irrelevant, and there is no fixed point. Full ratchet (`CP2_i = p`)
does not use `A` at all.

The code follows this structure. `apply_dilutive_issuance` computes
`capitalization_before_issue(table)` once, from the input table, and hands the same
object to `adjust_position` for every position. `adjust_position` reads no other
position.

**The order-independence test.** `test_fa3_order_independence` adjusts Seed then Series
A, then Series A then Seed, each time passing the pre-issuance capitalization to the
second step, and compares both with the simultaneous result. All three give exactly
Seed 27/26 and Series A 9/8 (derived under FA3). The test also asserts that the
intermediate table's as-converted count did rise after the first step. The first step
does change the table; under the charter reading, it does not change `A`.
`test_fa3_result_does_not_depend_on_table_or_mapping_order` permutes the input table and
the protection mapping and gets identical adjustments.

**What a different reading would give.** If `A` were recomputed after each series is
adjusted, the answer would depend on the order (derived under FA3, and asserted in
`test_naive_reading_would_be_order_dependent`). A reading in which every series' `A`
includes every other series' adjusted count would be a fixed point. Neither reading is
supported by the text above, and neither is implemented.

**Limit of this conclusion.** It is a reading of the NVCA model text. No court decision
or practitioner commentary on this point was consulted. A charter whose `A` is worded
differently, for example "after giving effect to" adjustments of other series, is not
covered and is not detected.

## Inputs with no default

Each of these is a charter fact or a determination about the transaction. None has a
default, and `test_public_functions_have_no_default_arguments` and
`test_charter_facts_have_no_default_fields` enforce that.

| Input | Why it has no default |
|---|---|
| `protection`, one entry per preferred position | Protection is set per series by the charter. The mapping must name **every** preferred position in the table, each with `weighted_average_protection(definition)`, `FULL_RATCHET` or `UNPROTECTED`. A missing key is refused, so no position is adjusted, or left alone, by omission. A key that is not a preferred position in the table is refused. |
| `definition` inside each weighted-average protection | Broad- and narrow-based differ only in `A`, and the charter decides which. This is the `ovf.antidilution` rule surfaced per position; two positions may use different definitions. |
| `exemption` | Charters list issuances that never trigger an adjustment. The lists are negotiated and bracketed in the NVCA form, so they cannot be enumerated here. The caller states `exempted` and a `basis`, both required, and the basis is written into the result's assumptions. |
| `aggregate_consideration` | NVCA 4.4.5 sets it at the cash received, "excluding amounts paid or payable for accrued interest", or at the board's good-faith fair value of property. It need not equal `shares × price` of the issued securities, so it is not inferred from them. |

The NVCA Exempted Securities categories, from 4.4.1 of the 2025 text, include: dividends
or distributions on preferred; stock splits and distributions covered by 4.5–4.8;
[bracketed] securities issued to banks, equipment lessors or real property lessors in a
debt financing or lease; plan grants to employees, directors, consultants or advisors;
common issued on exercise or conversion of Options or Convertible Securities;
[bracketed] issuances to suppliers or service providers; [bracketed] acquisition
consideration; an underwritten public offering; and [bracketed] strategic-partnership
issuances. Brackets mark negotiated terms, several with share-count ceilings. An issuance
that is only partly exempt must be split into two calls.

## How `A` is counted from the table

`capitalization_before_issue(table)` builds the five `CapitalizationBeforeIssue`
components from the table as it stands before the issuance:

| Component | Counted from |
|---|---|
| `common_outstanding` | every `CommonStock` position's shares |
| `preferred_as_converted` | every `PreferredStock`, `shares × conversion_ratio`, at current ratios |
| `options_and_warrants_as_exercised` | `StockOptionPool.allocated_shares` (granted options) |
| `other_convertibles_as_converted` | zero: the convertibles that could fill it are refused |
| `reserved_unissued_pool` | `StockOptionPool` capacity not yet granted |

Which components enter `A` is each weighted-average protection's stated definition.
Non-convertible debt holds no shares and adds nothing. A table holding a SAFE or a
convertible note is refused. The common issuable on its conversion is not fixed before
the priced round that converts it. The final paragraph of 4.4.3 treats a security with
"a cap on the valuation of the Corporation at which such conversion will be effected" as
"deemed not calculable" until its conversion terms are determined.

A table with granted options can be financed, but `solve_waterfall` refuses granted
options at exit ([limitations](limitations.md)). The exit fixtures below therefore use a
pool with no grants.

## What changes in the new table

Only `conversion_ratio`, and only for a position whose outcome is `adjusted`.

- **Conversion price and ratio.** NVCA 4.1.1 (Conversion Ratio): each preferred share
  converts into the number of common shares "determined by dividing the applicable
  Original Issue Price by the applicable Conversion Price". The Original Issue Price is
  `PreferredStock.price`, the figure the waterfall already uses as the preference basis.
  So `CP1 = price / conversion_ratio` and the new ratio is `price / CP2`.
- **The preference does not move.** NVCA 2.1 pays "[__ times] the applicable Original
  Issue Price, plus any dividends declared but unpaid thereon". The Conversion Price is
  not in that amount. `test_fixture_changes_only_conversion_ratios` checks that every
  field other than `conversion_ratio`, and every liquidation preference, is unchanged.
- **Unchanged positions are the same objects.** A position that is `not_triggered`,
  `exempted` or `unprotected` is carried into the new table as the input object itself.
  Common and pool positions are carried the same way.
- **Order.** The input positions keep their order, and the issued securities follow.

## Refused input

- A table holding a SAFE, a convertible note or an unrecognised instrument.
- A `protection` mapping that misses a preferred position, names a non-preferred or
  unknown id, or holds anything other than an `AntiDilutionProtection`.
- A weighted-average protection without a definition of `A`, or a full-ratchet or
  unprotected term with one.
- An issuance that is empty, issues no shares, repeats an id, collides with an id in the
  table, or contains anything other than common or preferred stock. A pool is refused
  with its own message: a reserve is not an issuance of shares.
- A full ratchet on an issuance without consideration (`ovf.antidilution` refuses it;
  the error names the position).
- A protected preferred position with a zero price: its conversion price is undefined.
- Arguments of the wrong type, including a bare `False` for the exemption.

## Sources

### Verified against the text

- **NVCA Model Certificate of Incorporation, October 2025** (URL above), read from the
  published `.docx` for this work: 2.1 (preference amount), 4.1.1 (conversion ratio),
  4.4.1 (Additional Shares of Common Stock, Exempted Securities, Option, Convertible
  Securities), 4.4.2 (no adjustment on written notice), 4.4.3 (deemed issuance; the
  anti-dilution exclusion and the not-calculable rule), 4.4.4 (both alternatives and the
  definitions of `CP1`, `CP2`, `A`, `B`, `C`), 4.4.5 (consideration) and 4.4.6
  (multiple closing dates). Quotations above are verbatim. Subsection numbers
  4.4.1–4.4.6 follow the document's automatic numbering, which does not survive text
  extraction. They were inferred from its cross-references ("Section 4.4.3",
  "Section 4.4.4", "Section 4.4.5") and their order, and match the numbering in
  [anti-dilution](antidilution.md).
- **NVCA Model Certificate of Incorporation, June 2019** (URL above): the Series A-only
  wording of the same definitions.

### Not verified

- **Full ratchet on one series alongside weighted average on another (FA4).** The NVCA
  model offers the two as alternatives for one 4.4.4, so one charter uses one of them.
  **UNVERIFIED:** no charter combining them was examined. FA4 assumes each series' own
  provision uses the NVCA definitions, including "immediately prior". The result
  follows from that assumption, not from a document.
- **Granted options as "Options outstanding".** Reading `allocated_shares` as granted,
  outstanding options follows the pool model in [semantics](semantics.md). Warrants
  outside the table are not seen.
- **No practitioner or judicial source** on the multi-series reading was consulted; see
  "Limit of this conclusion" above.

## Fixture derivations

**Shared table** (`tests/financing_fixtures.py`, `TABLE`):

| Position | Shares | Original Issue Price | Invested | Ratio | As converted |
|---|---|---|---|---|---|
| `common` (founders) | 8,000,000 | — | — | — | 8,000,000 |
| `seed` | 2,000,000 | $1.50 | $3,000,000 | 1 | 2,000,000 |
| `series_a` | 2,000,000 | $2.50 | $5,000,000 | 1 | 2,000,000 |
| `pool` | 3,000,000 reserved, 2,000,000 granted | — | — | — | 3,000,000 |
| **Fully diluted** | | | | | **15,000,000** |

Both ratios are 1, so `CP1` is $1.50 for Seed and $2.50 for Series A. Founders and Series
A are the shared cap table of [fixtures](fixtures.md). The pre-issuance components of `A`
are common 8,000,000, preferred as converted 4,000,000, granted options 2,000,000, other
convertibles 0 and reserve 1,000,000. So:

- `A` under `BROAD_BASED_NVCA` = 8M + 4M + 2M + 0 = **14,000,000** (reserve excluded);
- `A` under `NARROW_BASED_OUTSTANDING_STOCK` = 8M + 4M = **12,000,000**.

**Down round.** 4,000,000 Series B preferred at $1.25, ratio 1, for $5,000,000. So
`C = 4,000,000 × 1 = 4,000,000` and `p = 5,000,000 / 4,000,000 = $1.25`, below both
`CP1`s. Series B is new, so it is in no series' `A`.

**FA1: one protected series, broad-based.** Seed is stated `UNPROTECTED`; Series A is
broad-based.
- Series A: `B = 5,000,000 / 2.50 = 2,000,000`.
  `CP2 = 2.50 × (14M + 2M) / (14M + 4M) = 2.50 × 16/18 = 2.50 × 8/9 =` **$20/9**
  ($2.222222).
- Weighted-form check: `(14M × 2.50 + 4M × 1.25) / 18M = (35M + 5M) / 18M = 40/18 = 20/9`.
- Ratio `= 2.50 / (20/9) = 22.5 / 20 =` **9/8** (1.125). Series A converts into
  `2,000,000 × 9/8 =` **2,250,000** common. Identity check: `$5,000,000 / (20/9) =
  2,250,000`.
- Seed: not adjusted, although $1.25 < $1.50, because the caller did not protect it.

After FA1:

| Position | Shares | Conversion price | Ratio | As converted | Preference |
|---|---|---|---|---|---|
| `common` | 8,000,000 | — | — | 8,000,000 | — |
| `seed` | 2,000,000 | $1.50 | 1 | 2,000,000 | $3,000,000 |
| `series_a` | 2,000,000 | **$20/9** | **9/8** | **2,250,000** | $5,000,000 (unchanged) |
| `pool` | 3,000,000 | — | — | 3,000,000 | — |
| `series_b` | 4,000,000 | $1.25 | 1 | 4,000,000 | $5,000,000 |
| **Fully diluted** | | | | **19,250,000** | |

Founders hold `8 / 19.25 = 32/77` (41.56%) and Series A `2.25 / 19.25 = 9/77` (11.69%).

**FA1n: narrow-based.** `A = 12M`. `CP2 = 2.50 × (12M + 2M) / (12M + 4M) = 2.50 × 14/16 =`
**$2.1875**, ratio **8/7**, and Series A converts into `16,000,000/7 = 2,285,714.29`.
Fully diluted `= 8M + 2M + 16M/7 + 3M + 4M = 135M/7 = 19,285,714.29`. Leaving the
2,000,000 granted options out of `A` lowers the price by `20/9 − 35/16 = 5/144 =
$0.034722`. The price equals [anti-dilution](antidilution.md) AD1 because that fixture's
`A` is also 12,000,000, composed differently.

**FA2: the same issuance, nothing protected.** Both series are `UNPROTECTED`. No
adjustment is computed. The new table is `TABLE` followed by Series B, with the same
objects. Fully diluted `= 15M + 4M =` **19,000,000**. Against FA1, Series A holds
`2/19` (10.53%) instead of `9/77` (11.69%).

**FA3: two protected series, both broad-based.** Both use `A = 14M`.
- Seed: `B = 5,000,000 / 1.50 = 10,000,000/3`.
  `CP2 = 1.50 × (14M + 10M/3) / 18M = 1.50 × (52/3) / 18 = 1.50 × 52/54 =` **$13/9**
  ($1.444444). Weighted-form check: `(14M × 1.50 + 4M × 1.25) / 18M = 26M / 18M = 13/9`.
- Ratio `= 1.50 / (13/9) = 13.5 / 13 =` **27/26** (1.038462). Seed converts into
  `2,000,000 × 27/26 = 27,000,000/13 = 2,076,923.08`. Identity check:
  `$3,000,000 / (13/9) = 27,000,000/13`.
- Series A: exactly FA1, **$20/9** and **9/8**.
- Fully diluted `= 8M + 27M/13 + 2.25M + 3M + 4M = 251,250,000/13 = 19,326,923.08`.

*Order.* Both results use the same `A₀ = 14M`, so either order and the simultaneous
application give 27/26 and 9/8.

*The naive reading, for contrast.* Recompute `A` after each adjustment:
- Series A first: Series A's count rises from 2M to 2.25M, so `A' = 14.25M`. Then Seed:
  `CP2 = (14.25M × 1.50 + 5M) / (14.25M + 4M) = 26.375 / 18.25 =` **$211/146**
  ($1.445205).
- Seed first: `A' = 14M − 2M + 27M/13 = 183M/13` (14,076,923.08). Then Series A:
  `CP2 = (183/13 × 2.50 + 5) / (183/13 + 4) = (522.5/13) / (235/13) = 522.5/235 =`
  **$209/94** ($2.223404).

Each order gives the second series a higher price than the charter reading (13/9 ≈
1.444444 and 20/9 ≈ 2.222222), because it sees a larger `A`. The two orders disagree,
so this reading is not even defined without choosing an order.

**FA4: full ratchet on Seed, broad-based on Series A.**
- Seed: `CP2 = p =` **$1.25**, ratio `1.50 / 1.25 =` **6/5**, and Seed converts into
  **2,400,000**.
- Series A: its `A` counts Seed at the pre-issuance 2,000,000, not at 2,400,000, so
  `A = 14M` and `CP2 =` **$20/9**, ratio **9/8**, identical to FA1 and FA3.
- Fully diluted `= 8M + 2.4M + 2.25M + 3M + 4M =` **19,650,000**.

The ratchet on Seed is the largest adjustment in the file and has no effect on Series A.

**FA5: issue above both prices.** 1,000,000 Series B at $3.00 for $3,000,000, so
`p = $3.00`. Seed on full ratchet and Series A on broad-based. $3.00 is not below $1.50
or $2.50, so neither triggers: prices stay **$1.50** and **$2.50**, ratios stay **1**,
and no position is replaced. The new table is `TABLE` followed by Series B, with
fully diluted **16,000,000**. Series A's raw formula would have raised its price:
`B = 3M / 2.50 = 1.2M > C = 1M`, giving `2.50 × 15.2/15 = $2.533333`. The trigger stops
that; see [anti-dilution](antidilution.md) AD5.

**FA5b: issue between the two prices.** 1,000,000 Series B at $2.00 for $2,000,000.
- Seed (full ratchet): $2.00 > $1.50, **not triggered**.
- Series A (broad-based): `B = 2M / 2.50 = 800,000`, `C = 1M`.
  `CP2 = 2.50 × (14M + 0.8M) / (14M + 1M) = 2.50 × 14.8/15 =` **$37/15** ($2.466667).
  Weighted-form check: `(14M × 2.50 + 1M × 2.00) / 15M = 37/15`. Ratio
  `= 2.50 × 15/37 =` **75/74** (1.013514), so Series A converts into
  `75,000,000/37 = 2,027,027.03`.
- Fully diluted `= 8M + 2M + 75M/37 + 3M + 1M = 593,000,000/37 = 16,027,027.03`.

The trigger is tested per series, against each series' own `CP1`.

**FA6: an exempted issuance.** 4,000,000 common issued as acquisition consideration,
valued by the board at $5,000,000. `C = 4,000,000` and `p = $1.25`, the same as the down
round, and both series are broad-based as in FA3. The caller determines the issuance
exempt, citing the charter's acquisition carve-out. Additional Shares of Common Stock
exclude Exempted Securities, so neither series adjusts: prices **$1.50** and **$2.50**,
ratios **1**, fully diluted `15M + 4M =` **19,000,000**. The test reruns the same issuance
with the exemption set to `False` and obtains FA3's **$13/9** and **$20/9**. The
determination is the only difference.

### An adjusted table carried into an exit

**Exit table.** Founders hold 8,000,000 common. Series A holds 2,000,000 at $2.50
(seniority 2). The pool has 1,000,000 reserved and nothing granted. The down round issues
4,000,000 Series B at $1.25 for $5,000,000 (seniority 1). Both series are 1x
non-participating.

**Adjustment.** Under `BROAD_BASED_NVCA`, `A = 8M + 2M = 10M`; the unallocated reserve is
excluded and there are no options. `B = 2M`, `C = 4M`. `CP2 = 2.50 × 12/14 = $15/7`
($2.142857). The ratio is **7/6**, so Series A converts into `7,000,000/3 = 2,333,333.33`.

**Exit at $301,000,000.** The unallocated pool takes nothing, so residual cash is shared
over common, Series A as converted and Series B as converted. $301M is `7 × $43M`, chosen
so that both cases divide exactly.

**FX1a: Series A protected.** Shares sharing the residual: `8M + 7M/3 + 4M = 43M/3`.
If everyone converts:
- common `= 8 × 3/43 × $301M = 24/43 × $301M =` **$168,000,000**;
- Series A `= (7/3) × 3/43 × $301M = 7/43 × $301M =` **$49,000,000**;
- Series B `= 4 × 3/43 × $301M = 12/43 × $301M =` **$84,000,000**.

The sum is $301M. Deviations: holding the $5M preference instead would pay Series A $5M
< $49M and Series B $5M < $84M, so all-convert is an equilibrium. The test also
enumerates every conversion profile and finds one payoff vector.

**FX1b: Series A unprotected.** Shares sharing the residual: `8M + 2M + 4M = 14M`.
- common `= 8/14 × $301M =` **$172,000,000**;
- Series A `= 2/14 × $301M =` **$43,000,000**;
- Series B `= 4/14 × $301M =` **$86,000,000**.

The preferences ($5M each) are again worse than converting.

**The difference.** The adjustment moves **$6,000,000** to Series A, **$4,000,000** of it
from common and **$2,000,000** from Series B. The liquidation preferences are identical
in both tables. Only the conversion ratio changed.

## What the adjusted table does not carry

This is a conversion-ratio adjustment and nothing else. A real down round often changes
more at the same closing. None of the following is applied, and a table produced here is
wrong wherever the financing did any of them:

- **Pay-to-play.** The 2025 model's special mandatory conversion converts a holder that
  does not buy its Pro Rata Amount in a Qualified Financing "into shares of Common Stock
  at the applicable Conversion Price in effect immediately prior to the consummation of
  such Qualified Financing". [Limitations](limitations.md) also lists shadow classes.
  A converted holder loses its preference and its anti-dilution protection, which this
  module still gives it. Governance work owns this.
- **Board composition, voting and new protective provisions.** Not represented anywhere
  in the model.
- **Changes to the terms of existing series**, including repricing, recapitalization,
  new preferences, seniority reordering or accruing dividends negotiated at the down
  round. Every term except the ratio is carried over unchanged.
- **Pool changes made with the round.** A pool increase is refused as part of an
  issuance. Whether it sits before the round (so it can enter a definition of `A` that
  counts the reserve) or after it is a financing-document question, and is modelled by
  building that snapshot separately.
- **Conversions of SAFEs or notes in the round.** Refused: the table cannot contain them
  and the issuance cannot issue them.

## Not modelled

| Not modelled | Why it would change a real number |
|---|---|
| **Rounding of CP2** | NVCA rounds CP2 "to the nearest one-hundredth of a cent". Unrounded here, so a ratio can differ from a closing statement by up to $0.00005 of price. |
| **Waiver** (4.4.2) | Written notice from the Requisite Holders, or a series majority, cancels the adjustment. A waived series still adjusts here unless the caller states it unprotected, which records the wrong reason. |
| **Multiple closing dates** (4.4.6) | Related issuances within the bracketed [180] days readjust "as if they occurred on the date of the first such issuance". One call per closing compounds instead and gives a different CP2. |
| **Deemed issuance of Options and Convertible Securities** (4.4.3) | Issuing options, warrants or convertibles is refused. Their maximum share count and minimum total consideration set C and B. |
| **Readjustment on amendment, expiry or termination** (4.4.3) | A later change to an option or convertible that caused an adjustment readjusts the price. Nothing here remembers why a ratio is what it is. |
| **Non-cash and bundled consideration** (4.4.5) | Board fair value and allocation are taken as the stated amount, not computed. |
| **Series-specific or partial exemptions** | One determination covers the whole issuance and every series. A charter with per-series carve-outs, or an issuance that is partly exempt, must be split by the caller. |
| **Series identity** | The model has positions, not series. Two positions of one series must be given the same term. This is not checked, because two series can share a price. |
| **Full-ratchet end date** | The NVCA ratchet allows "[and prior to [Date]]". No date is read; the caller decides whether the ratchet is still in force. Nothing else in this module depends on time, so it takes no `as_of`. |
| **Par-value floor** | NVCA 4.3 (Reservation of Shares) requires corporate action before an adjustment "reducing the Conversion Price for any series of Preferred Stock below the then par value". Not checked. |
| **Proportional adjustments** (splits, combinations, dividends, reorganizations; 4.5–4.8) | Separate subsections that move the conversion price independently of this formula. |
| **Anti-dilution on warrants or common** | Warrants are not modelled, so their own price protection is not applied. |
| **Charter wording other than the NVCA "immediately prior" definitions** | A charter that measures `A` after adjustments would need a different calculation. It is not detected. |
| **Fractional shares at conversion** | Cash in lieu of fractions changes delivered shares by less than one per holder. |
| **Payoff uniqueness over adjusted tables** | The [findings](findings.md) enumeration ran on unadjusted ratios. FX1a and FX1b are checked for a unique payoff; no wider search over adjusted tables was run. |

## What a fixture does not establish

A fixture asserts that the implementation reproduces a derivation written here. It does
not establish that a given charter uses the NVCA definitions, that a series is protected
by the term the caller states, that an issuance is or is not exempt, or that the
consideration is the figure the board would determine. The list above is the companion
to this document.
