# Anti-dilution: conversion-price adjustment

Status 2026-09-15, engine `antidilution-v1`, module `ovf.antidilution`. Pure functions
over stated numbers: nothing reads or changes a `CapTable` or a security. Every expected
number below is derived by hand here, then asserted in `tests/test_antidilution.py`
against the fixtures in `tests/antidilution_fixtures.py`.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is
empty on every fixture.

## What it computes

A preferred share converts into `Original Issue Price / Conversion Price` common shares.
The conversion price starts equal to the original issue price, so the ratio starts at 1.
A price-based anti-dilution clause lowers the conversion price when the company later
issues shares for less, so each preferred share converts into more common.

| Function | Rule |
|---|---|
| `weighted_average` | `CP2 = CP1 × (A + B) / (A + C)` |
| `full_ratchet` | `CP2 = p` |
| `conversion_ratio` | `ratio = OIP / CP2`, the value `PreferredStock.conversion_ratio` expects |
| `deemed_outstanding` | builds `A` from stated share counts under a stated definition |

- `CP1`: the protected series' conversion price immediately before the issuance.
- `CP2`: its conversion price immediately after.
- `A`: shares deemed outstanding immediately before the issuance.
- `C`: shares actually issued in the dilutive issuance.
- `p = consideration / C`: the issue price.
- `B = consideration / CP1`: the shares the same money would have bought at the old price.

**Trigger.** An adjustment applies only when `p < CP1`, strictly. Otherwise `CP2 = CP1`.
No method ever raises a conversion price, and the tests check this for every fixture
and across a grid of inputs.

**Input.** `C` is counted in common-equivalent shares. A new preferred series sold in
the down round is a Convertible Security, so `C` is the common issuable when it
converts at its initial ratio. Consideration is whatever figure the caller supplies.

## Sources

### Verified against the text

- **NVCA Model Certificate of Incorporation.** Read in two versions:
  [June 2019](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Document-Certificate-of-Incorporation.docx)
  and [October 2025](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx).
  Subsection 4.4.4 (broad-based weighted-average alternative) reads, in the 2025 text:
  - Trigger: the company issues Additional Shares of Common Stock "without
    consideration or for a consideration per share less than the Conversion Price …
    in effect immediately prior".
  - Formula: `CP2 = CP1* (A + B) / (A + C)` (the 2019 text writes `÷`). CP2 is
    "calculated to the nearest one-hundredth of a cent"; the 2019 text puts that
    increment in brackets.
  - "A" is "the number of shares of Common Stock outstanding immediately prior to such
    issuance … (treating for this purpose as outstanding all shares of Common Stock
    issuable upon exercise of Options outstanding … or upon conversion or exchange of
    Convertible Securities (including the Preferred Stock) outstanding …)".
  - "B" is "determined by dividing the aggregate consideration received by the
    Corporation in respect of such issue by CP1".
  - "C" is "the number of such Additional Shares of Common Stock issued in such
    transaction".
  - The full-ratchet alternative to 4.4.4 reduces the conversion price "to the
    consideration per share received by the Corporation". For an issuance without
    consideration it deems an aggregate of "[$0.001]" received (2019: "[$.001]").
  - 4.1.1 (2019 text) sets the conversion ratio: the number of common shares found "by
    dividing the … Original Issue Price by the … Conversion Price".
  - "Option" is defined as "rights, options or warrants to subscribe for, purchase or
    otherwise acquire Common Stock or Convertible Securities". "Convertible Securities"
    are other securities convertible into common, "but excluding Options".
- **Kaplan, S. N. & Strömberg, P. (2003).** "Financial contracting theory meets the
  real world", *Review of Economic Studies* 70(2), 281–315, Table 2 Panel E. The sample
  is 213 investments in 119 companies by 14 VC partnerships, 1987–1999. "Any
  anti-dilution protection" appears in 94.7% of these investments. Full ratchet is
  21.9% and weighted average 78.1%; the text describes the split as among the
  financings that have protection. In first VC rounds (N = 98) the figures are 91.0%,
  24.7% and 75.3%.
- **WilmerHale, *2026 Venture Capital Report*,** "Trends in Venture Capital Financing
  Terms", based on "hundreds of venture capital financing transactions we handled from
  2021 to 2025".
  - 2025, first rounds: full ratchet 0%, weighted average 100%.
  - 2025, later rounds: full ratchet 3%, weighted average 97%.
  - 2021–2025 range: full ratchet 0–2% of first rounds and 0–3% of later rounds.

  These values come from text extracted from the report PDF. They were assigned to
  years in extraction order, so check them against the rendered chart. The sample is one
  law firm's deals, not the whole market, and the report does not split broad-based
  from narrow-based.

### Not verified

- **Bartlett, R. P. III (2003).** "Understanding Price-Based Antidilution Protection:
  Five Principles to Apply When Negotiating a Down-Round Financing", *The Business
  Lawyer* 59(1), 23–42. **UNVERIFIED:** the text was not obtained. It is cited as the
  standard legal treatment of the subject. No number, formula or convention in this
  module depends on it; the formula comes from the NVCA text above.
- **`BROAD_BASED_WITH_RESERVED_POOL`.** No charter text was found that deems
  reserved-but-ungranted plan shares outstanding. The composition exists so a caller
  whose charter does this can say so. It is not presented as a market convention.
- **`NARROW_BASED_OUTSTANDING_STOCK`.** Its "outstanding capital stock only" reading was
  not checked against any charter.

## The definition of A is the term

Broad-based and narrow-based use the same formula. They differ only in `A`, and that
difference is the whole economic content of the term.

`CapitalizationBeforeIssue` holds five share counts. Each one is required and none has
a default:

| Component | Meaning |
|---|---|
| `common_outstanding` | issued common |
| `preferred_as_converted` | all preferred, including the protected series, at current ratios |
| `options_and_warrants_as_exercised` | NVCA "Options" outstanding: granted options and warrants |
| `other_convertibles_as_converted` | NVCA "Convertible Securities" other than preferred |
| `reserved_unissued_pool` | plan capacity not yet granted |

`DeemedOutstandingDefinition` states which of the five count toward `A`, with five
required boolean flags. There are three named compositions:

| Definition | Common | Preferred | Options, warrants | Other convertibles | Reserve |
|---|---|---|---|---|---|
| `BROAD_BASED_NVCA` | ✓ | ✓ | ✓ | ✓ | ✗ |
| `BROAD_BASED_WITH_RESERVED_POOL` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `NARROW_BASED_OUTSTANDING_STOCK` | ✓ | ✓ | ✗ | ✗ | ✗ |

**Reading of the NVCA text.** The NVCA definition counts common issuable on "Options
outstanding". Plan shares that are reserved but not granted are not yet a right to
acquire anything, so this reading excludes them from `BROAD_BASED_NVCA`. That is a
reading of the text, not a court's or practitioner's statement.

**Narrow-based is charter-dependent.** "Narrow-based" names a family of definitions,
not one definition. The named composition is one reading; a charter that narrows `A`
differently needs its own `DeemedOutstandingDefinition`.

**No default anywhere.** `weighted_average` requires `definition` as a keyword with no
default. None of the four public functions has a default argument, and a test enforces
this. Every result records `A` as counted and excluded components, so the choice
behind the number is visible.

## The algebra behind every result

Because `B = consideration / CP1 = p·C / CP1`, it follows that `CP1·B = p·C`, so

```
CP2 = CP1 (A + B) / (A + C) = (A·CP1 + C·p) / (A + C)
```

CP2 is the average of the old price and the new price, weighted by the shares behind
each. That gives four consequences, each of which is tested:

1. `CP2 − p = A (CP1 − p) / (A + C)`, so when `p < CP1`, `p ≤ CP2 ≤ CP1`. The adjusted
   price always lies between the new price and the old one, which is how Kaplan and
   Strömberg describe the weighted average.
2. A larger `A` puts more weight on `CP1`, so the adjustment is smaller. Narrow-based
   (smaller `A`) therefore always moves the price further down than broad-based on the
   same issuance.
3. As `A → 0`, `CP2 → p`: full ratchet is the weighted average with no weight on the
   existing shares.
4. If `p > CP1`, the same weighted average lies above `CP1`. The raw formula would
   ratchet the price up, which is why the trigger is enforced rather than left to the
   algebra.

## Market context

Weighted average is the common case. WilmerHale records it in 100% of its 2025 first
rounds, and Kaplan and Strömberg in 78.1% of their 1987–1999 rounds with protection.
Full ratchet is the tail: 0–3% in WilmerHale's 2021–2025 data and 21.9% in the earlier
academic sample.

An adjustment changes a number only in a down round, so how often a term is written and
how often it matters are different frequencies. No source consulted here measures how
often full ratchet appears among down rounds specifically.

## Fixture derivations

**Shared capitalization.** This continues the cap table in [fixtures](fixtures.md):

- founders hold 8,000,000 common;
- Series A holds 2,000,000 preferred at an original issue price of **$2.50**, which is
  $5,000,000 invested. Its ratio is 1, so it is 2,000,000 common-equivalent, and
  `CP1 = OIP = $2.50`;
- there are 2,000,000 granted options outstanding, no other convertibles, and a
  1,000,000-share reserve that is not yet granted.

**Down round.** The company issues 4,000,000 shares for $5,000,000. So
`p = 5,000,000 / 4,000,000 = $1.25`, `B = 5,000,000 / 2.50 = 2,000,000` and
`C = 4,000,000`.

**AD1: broad-based, NVCA definition.**
`A = 8,000,000 + 2,000,000 + 2,000,000 + 0 = 12,000,000`; the reserve is excluded.
`A + B = 14,000,000` and `A + C = 16,000,000`, so the factor is `14/16 = 0.875`.
`CP2 = 2.50 × 0.875 =` **$2.1875**.
Weighted-form check: `(12M × 2.50 + 4M × 1.25) / 16M = 35M / 16M = 2.1875`.
Ratio `2.50 / 2.1875 =` **8/7** (1.142857). Series A converts into
`2,000,000 × 8/7 = 2,285,714.29` common.

**AD2: narrow-based, same issuance.**
`A = 8,000,000 + 2,000,000 = 10,000,000`; options and the reserve are excluded.
The factor is `12M / 14M = 6/7`, so `CP2 = 2.50 × 6/7 = 15/7 =` **$2.142857**.
Weighted-form check: `(10M × 2.50 + 5M) / 14M = 30/14`.
Ratio `= 7/6` (1.166667), so Series A converts into 2,333,333.33 common.
That is a larger downward adjustment than AD1:
- the price is lower by `35/16 − 15/7 = 5/112 = $0.044643`;
- Series A converts into `7,000,000/3 − 16,000,000/7 = 1,000,000/21 = 47,619.05` more
  shares.

**AD3: full ratchet, same issuance.** `CP2 = p =` **$1.25**, ratio **2**, and Series A
converts into 4,000,000 common. This is the largest adjustment of the three. It ignores
`A` and would be the same for 4 shares or 400,000,000 shares at $1.25.

**AD4: broad-based with the reserve deemed outstanding.** `A = 13,000,000`. The factor
is `15/17`, so `CP2 = 2.50 × 15/17 = 75/34 =` **$2.205882**. Ratio `= 17/15`
(1.133333), so Series A converts into 2,266,666.67 common.
Compared with AD1, 1,000,000 shares that have not been granted:
- raise CP2 by `75/34 − 35/16 = 5/272 = $0.018382`;
- cost Series A `16,000,000/7 − 34,000,000/15 = 2,000,000/105 = 19,047.62` shares.

Whether the reserve counts is set by the charter's wording, not by the formula.

| Case | A | CP2 | Ratio | Series A common-equivalent |
|---|---|---|---|---|
| none | — | $2.50 | 1 | 2,000,000 |
| AD4 broad + reserve | 13,000,000 | $2.205882 | 17/15 | 2,266,666.67 |
| AD1 broad (NVCA) | 12,000,000 | $2.1875 | 8/7 | 2,285,714.29 |
| AD2 narrow | 10,000,000 | $2.142857 | 7/6 | 2,333,333.33 |
| AD3 full ratchet | — | $1.25 | 2 | 4,000,000 |

**AD5: issue above the conversion price.** The company issues 1,000,000 shares for
$3,000,000, so `p = $3.00 > $2.50`. There is no adjustment under any method: `CP2 =`
**$2.50**, ratio **1**.

This case is why the trigger matters. `B = 3,000,000 / 2.50 = 1,200,000 > C`, so the
raw formula would raise the price:
- broad-based: `2.50 × 13.2/13 = 33/13 = $2.538462`;
- narrow-based: `2.50 × 11.2/11 = 28/11 = $2.545455`;
- a ratchet to the issue price: $3.00.

The test computes each raw value from the returned `A`, `B` and `C` and checks that the
engine did not use it. An issue at exactly $2.50 does not trigger either: the NVCA
trigger is "less than", and in that case `B = C`, so the formula would return `CP1`
anyway.

**AD6: issuance without consideration.** The company issues 4,000,000 shares for $0, so
`p = 0` and `B = 0`. With `A` and `C` fixed this is the lowest price the weighted
average can give, `CP2 = A × CP1 / (A + C)`. It stays above zero because the existing
shares keep their weight.
- **AD6a, broad:** `2.50 × 12/16 =` **$1.875**, ratio **4/3**, so Series A converts
  into 2,666,666.67 common.
- **AD6b, narrow:** `2.50 × 10/14 = 25/14 =` **$1.785714**, ratio **7/5**, so Series A
  converts into 2,800,000 common.
- **Full ratchet:** rejected. At `p = 0` the ratchet would set the price to zero and the
  ratio to infinity. The NVCA form instead deems a bracketed aggregate of $0.001
  received, which the caller passes explicitly. With that amount,
  `CP2 = 0.001 / 4,000,000 = $2.5 × 10⁻¹⁰` and the ratio is `2.50 / 2.5 × 10⁻¹⁰ = 10¹⁰`.

**AD7: the conversion-ratio identity.** For `n` preferred shares bought at the original
issue price,

```
n × ratio = n × OIP / CP2 = invested capital / CP2
```

So the adjusted ratio turns the original investment into common at the adjusted price.
- **AD1:** `5,000,000 / 2.1875 = 5,000,000 × 16/35 = 16,000,000/7 = 2,285,714.29`,
  which equals `2,000,000 × 8/7`.
- **AD3:** `5,000,000 / 1.25 = 4,000,000 = 2,000,000 × 2`.

The test builds `ovf.preferred(2_000_000, 2.50, conversion_ratio=ratio)` and checks that
`converted_shares` equals both expressions.

## Using the result

```python
from ovf.antidilution import (
    BROAD_BASED_NVCA, CapitalizationBeforeIssue, DilutiveIssuance,
    conversion_ratio, weighted_average,
)

result = weighted_average(
    conversion_price=2.50,
    capitalization=CapitalizationBeforeIssue(
        common_outstanding=8_000_000, preferred_as_converted=2_000_000,
        options_and_warrants_as_exercised=2_000_000, other_convertibles_as_converted=0,
        reserved_unissued_pool=1_000_000,
    ),
    definition=BROAD_BASED_NVCA,
    issuance=DilutiveIssuance(shares_issued=4_000_000, aggregate_consideration=5_000_000),
)
ratio = conversion_ratio(original_issue_price=2.50,
                         conversion_price=result.conversion_price_after)
# result.conversion_price_after == 2.1875; ratio == 8/7
```

- **Securities are immutable.** Apply the ratio by building a new `PreferredStock` with
  `conversion_ratio=ratio` in a new snapshot.
- **Several series.** Adjust each protected series with a separate call against its own
  `CP1`. `B` differs between series because it divides by that series' `CP1`.
- **Later issuances.** Pass the adjusted price as the next `CP1`, and restate `A`
  (including the new shares and any changed as-converted counts).

## Not modelled

| Not modelled | Why it would change a real number |
|---|---|
| **Rounding of CP2** | The NVCA form rounds CP2 to the nearest one-hundredth of a cent. Results here are unrounded, so CP2 can differ by up to $0.00005 and the ratio moves with it. |
| **Exempted Securities (carve-outs)** | Plan grants, conversions, acquisitions, equipment leases, strategic deals and similar issuances are excluded by charter-specific lists. They decide whether an issuance triggers at all; the caller must exclude them. |
| **Deemed issuance of Options and Convertible Securities** (NVCA 4.4.3, 4.4.5) | Consideration becomes the amount received plus the minimum exercise or conversion consideration, divided by the maximum shares issuable. Later amendment or expiry readjusts it. This changes B, C and the trigger. |
| **Non-cash and bundled consideration** | Property is valued at the board's good-faith fair value, and bundled sales are allocated by the board. Either changes B. |
| **Multiple closings** | The NVCA form readjusts as if all closings in a related series of issuances happened at the first. Calling the engine once per closing compounds and gives a different CP2. |
| **Waiver** | Written notice from the Requisite Holders, or a series majority, cancels the adjustment. A waived issuance changes nothing. |
| **Splits, combinations, stock dividends, reorganizations** | These are proportional adjustments under separate subsections, not price-based ones. They move CP independently of this formula. |
| **Full-ratchet end date** | The NVCA ratchet allows a negotiated "[and prior to [Date]]". After that date the ratchet does not apply. |
| **Pay-to-play** | This is a governance action, not a price formula. Non-participating holders can lose the protection, or convert to common or a shadow series. It belongs with the governance work. |
| **Conversion of SAFEs or notes as the dilutive issuance** | WilmerHale notes that SAFE conversion can trigger existing preferred's anti-dilution. The effective consideration of a converting SAFE is not computed here; the caller must state it. |
| **Cross-series feedback** | Adjusting one series changes its as-converted count, which feeds `A` for other series and for later issuances. The engine uses the counts it is given. |
| **Narrow-based variants other than the named one** | These are charter-specific. Express them as a `DeemedOutstandingDefinition`. |
| **Applying the result to a live CapTable or an exit** | Wiring is deferred to integration. The payoff-uniqueness evidence in [findings](findings.md) does not cover adjusted ratios. |
| **Fractional shares at conversion** | Cash in lieu of fractions changes the delivered share count by less than one share per holder. |

## What a fixture does not establish

A fixture asserts that the implementation reproduces a derivation written here. It does
not establish that a given charter uses the named definition of `A`, that an issuance
is not exempted, or that the consideration figure is the one the charter would compute.
The list above is the companion to this document.
