# Presets from the NVCA model charter

Status 2026-09-15, engine `presets-v1`, module `ovf.presets`. Every expected number below
is derived by hand here, then asserted in `tests/test_presets.py`, which holds the fixtures.
Each derivation was rechecked with exact rational arithmetic before it was written down.
None was copied from engine output.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty
on every fixture.

**Documents read.**

| Document | Version | File | SHA-256 |
|---|---|---|---|
| NVCA Model Amended and Restated Certificate of Incorporation ("the charter", "COI") | October 2025; the file's creation date is 2025-10-01 | [NVCA-Model-COI-10-1-2025.docx](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx) | `d75600769c12724990de48149d7a2bb161f3522daa54b1783672f93697d87d29` |
| NVCA Model Term Sheet, Series A Preferred Stock Financing | 2019; uploaded 2019-06 | [NVCA-Model-Term-Sheet-1.doc](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Term-Sheet-1.doc) | `6ddf9f59400272a93863790041f9f8057464fb6399aeba801ce391954b697a44` |

Both files were downloaded and read in full on 2026-09-15. The charter is the source for
the preset. The Term Sheet is a separate instrument, and it is cited only where the
charter is silent; each such place says so. When the
[model documents page](https://nvca.org/model-legal-documents/) was read, it listed the
October 2025 charter, stock purchase agreement and investors' rights agreement, but no
later venture financing term sheet. The 2019 file was still being served.

**Citation conventions.** They are the same as in [dividends](dividends.md).

- Section numbers are the document's automatic numbering, resolved through its paragraph
  styles and checked against its own cross-references ("Section 2.3.1(a)(i)",
  "Section 4.4.3(b)", "Section 5A.1").
- Footnote numbers are the numbers Word displays; each is one less than the footnote's
  XML id.
- In quotations, typographic quotes are written as straight quotes, runs of whitespace
  are collapsed, and "..." marks an elision.
- Every quoted fragment in `src/ovf/presets.py` was checked, by script, to occur in the
  text extracted from the two files.

## Finding: the model charter has no Series B

The October 2025 charter creates exactly one series of preferred stock. Article Fourth:

> "[all] of which are hereby designated as "Series A Preferred Stock"."

Part B, opening paragraph:

> "References to "Preferred Stock" mean the Series A Preferred Stock."

Its drafting footnotes say that the text must be rewritten before a second series with
different rights can exist. On liquidation ranking, fn 16:

> "For simplicity, this model charter provides for pari passu preferred stock liquidation.
> If one or more series of preferred stock has a senior or junior liquidation preference,
> this language will need to be revised."

On dividends, fn 12:

> "For simplicity, this model charter provides for pari passu dividends. If one series of
> Preferred Stock has a senior liquidation preference, this dividend language may need to
> be revised."

Parts of the text are worded for "each series" (s.2.1, s.4.4.4, fn 18), but the document
never states a second series' rank, price, preference or relation to Series A. **There is
no NVCA Series B.** A function named `nvca_series_b()` would claim that NVCA describes one,
which it does not. That would resolve the rank, and the second series' alternatives,
silently, one level above any argument.

So `ovf.presets` has one preset that maps to the document, `nvca_series_a()`. A further
series is built with `additional_series()`. The first line of its docstring says the model
is single-series and that the series, its rank and its terms are the caller's. Its result
has `series_in_model=False`, and the record for the `series` term has `within_model=False`.
The rank is required and has no default:

- `pari_passu` follows the only ranking wording the model contains (s.2.1, "on a pari
  passu basis");
- `senior` and `junior` are recorded as outside the model text, citing fn 16.

The coordinator settled this reading on 2026-09-15, including the name.

## What a preset is, when the source is a template

**The trap.** The charter is a set of bracketed alternatives. Several choices are open:
participating or not; the multiple; one of three dividend provisions; weighted average or
full ratchet; whether to include a pay-to-play section. A preset that fills them in
silently invents a canonical deal that does not exist.

**The answer taken here: every choice the document leaves open is a required argument
with no default.** In the text a choice takes one of three forms. Each becomes an argument:

1. **A bracket or blank.** Examples are "[__ times]", "[$_______] per share", "$[insert
   initial Series A purchase price]" and "[and prior to [Date]]".
2. **An alternative section**, introduced by the model's own instruction, such as
   "[Use the following Sections 2.1 and 2.2 if the term sheet calls for participating
   Preferred Stock.]"
3. **A footnoted variant of the operative text.** fn 13's compounding dividend is one.
   fn 14's "Insert the bracketed language if ..." is another.

The preset itself supplies **only the unbracketed wording**, the text the document states
for every deal. It supplies nothing else.

**Why not take the model's own defaults?** A preset could adopt the document's stated
default wherever it expresses one. For the economic terms, the document never does. The
nearest candidates are two places where the operative text says one thing and a footnote
offers another:

- s.2.1's "pari passu" wording, which fn 16 calls a choice made "For simplicity";
- s.1's "$[___] per share" simple accrual, which fn 13 offers to compound "If a compounding
  accrued dividend is desired".

The footnotes themselves open both. Making either one a default would give a caller a
number they never chose, and this repository is built to prevent exactly that. So both
are required arguments.

**Market prevalence is not document content.** "Most deals are 1x non-participating" is a
fact about the market. [fixtures](fixtures.md) records it with its sources. No argument
here is defaulted to it.

The test `test_public_functions_have_no_default_arguments` enforces the rule on every
public function. `test_choices_have_no_default_fields` enforces it on every choice object.

## The terms

### Terms the caller states (`origin="caller"`)

| Argument | Provision | The bracket, verbatim | What `ovf` sets |
|---|---|---|---|
| `original_issue_price` | COI s.1, definition | "$[insert initial Series A purchase price] per share" | `PreferredStock.price` |
| `shares` | Term Sheet, Offering Terms; the charter states only authorized shares | "Investor No. 1: [_______] shares ([__]%), $[_________]" | `PreferredStock.shares` |
| `liquidation_multiple` | COI s.2.1 | non-participating: "the greater of (i) [__ times] the applicable Original Issue Price ..."; participating: "an amount per share equal to [___ times] the applicable Original Issue Price" | `liquidation_multiple` |
| `participation` | COI s.2.1-2.2, two alternative pairs | "[Use the following Sections 2.1 and 2.2 if the term sheet calls for non-participating Preferred Stock.]" / "... for participating Preferred Stock.]" | `participating` |
| `maximum_participation_multiple` in `participating(...)` | COI s.2.2, fn 20 | "If a cap to the liquidation preference is specified in the term sheet, add the following language ... [$_______] per share ... (the "Maximum Participation Amount")" | `participation_cap`; `None` means no cap |
| `dividend` | COI s.1, fn 9: "This model charter provides for three bracketed alternative dividend provisions." | see below | `dividend` |
| `anti_dilution` | COI s.4.4.4, two alternatives; Term Sheet Alternative 3 | see below | `PresetPosition.anti_dilution` |

**Participation.**

- The non-participating alternative pays "the greater of (i) [__ times] the applicable
  Original Issue Price, plus any dividends declared but unpaid thereon, or (ii) such amount
  per share as would have been payable had all shares of such series of Preferred Stock ...
  been converted into Common Stock". The remainder goes to common "pro rata based on the
  number of shares of Common Stock held by each such holder" (s.2.2).
- The participating alternative pays "[___ times] the applicable Original Issue Price" in
  s.2.1. The remainder is then "distributed among the holders of the shares of Preferred
  Stock and Common Stock, pro rata based on the number of shares held by each such holder,
  treating for this purpose all such securities as if they had been converted to Common
  Stock" (s.2.2).
- These are the engine's non-participating and participating positions, with conversion
  ratio 1.

**The fn 20 cap.** fn 20 states the Maximum Participation Amount as "[$_______] per share".
The argument takes it as a multiple of the Original Issue Price, the unit `ovf` and the Term
Sheet use. The Term Sheet's Alternative 3 reads "until the holders of Series A Preferred
receive an aggregate of [_____] times the Original Purchase Price (including the amount paid
pursuant to the preceding sentence)". For the model's single series the two are one number:
dollars per share `= multiple × Original Issue Price`. The result's
`maximum_participation_amount` record states both. For example, P3's reads
`2.0x the Original Issue Price = 5.0 per share`.

**Dividends.** Each of the three s.1 alternatives is introduced by the model's own
instruction:

| Constructor | s.1 alternative | Instruction, verbatim | What `ovf` sets |
|---|---|---|---|
| `dividend_as_converted_only()` | first | "[Use the following paragraph if the Term Sheet calls for no specific dividend on the Preferred Stock, but an equal sharing if dividends are declared on the Common Stock.]" | `dividend=None`; see below |
| `dividend_non_cumulative(rate=...)` | second | "[Use the following paragraph if the Term Sheet calls for a specific dividend amount, payable only when, as and if declared by the Board, in addition to pari passu/shared dividends.]" | `NonCumulativeDividend(rate)` |
| `dividend_accruing(...)` | third | "[Use the following paragraph if the Term Sheet calls for a specified cumulative dividend, payable if and when declared by the Board, in addition to shared dividends.]" | `CumulativeDividend(..., settlement="forfeit_on_conversion")` |

- **First alternative.** Under it the preferred receives a dividend only when one is
  declared on common, as-converted. Nothing accrues. Declared dividends are not modelled
  anywhere in `ovf` ([dividends](dividends.md)), so at an exit this alternative is exactly a
  position with no dividend right. It is recorded as `dividend=as_converted_only`, so the
  choice stays visible.
- **Second alternative.** "The right to receive dividends on shares of Preferred Stock ...
  shall not be cumulative ... The "Dividend Amount" shall mean, with respect to any series
  of Preferred Stock, [8]% of the Original Issue Price". The "[8]" is a bracket, so `rate`
  is required.
- **Third alternative.** "From and after the date of the issuance of any shares of
  Preferred Stock, dividends at the rate per annum of $[___] per share shall accrue ...
  Accruing Dividends shall accrue from day to day, whether or not declared, and shall be
  cumulative". Every term of `dividend_accruing` is required:
  - `rate`: the "$[___] per share" divided by the Original Issue Price, the base
    [dividends](dividends.md) uses.
  - `accrual`: `"simple"` is the operative text. fn 13: "A cumulative dividend expressed as
    "$____ per share" will by definition be non-compounding". `"compound"` is fn 13's
    variant: "If a compounding accrued dividend is desired, it should be expressed as a
    percentage of a "base amount," ... (it should also be specified whether this
    "compounding" of the original purchase price is done on an annual, quarterly, or other
    basis)". So `compounding_frequency` must be `None` for simple accrual and stated for
    compound accrual.
  - `day_count`: the charter says only "accrue from day to day".
  - `accrues_from`: "From and after the date of the issuance". It is a caller-supplied
    date; the exit takes the usual explicit `as_of`.
  - `payable_on_liquidation`: the s.1 bracket "[or in Section 2.1 [and Section 6.1]]". fn 14:
    "Insert the bracketed language if the holders of Preferred Stock will receive the
    benefit of the accruing dividends upon a liquidation event or upon redemption." Only
    `True` is accepted. Without the bracket, accruing dividends are "payable only when, as,
    and if declared", so they are not part of the liquidation amount. `ovf` does not model
    declared dividends, so no exit claim exists to build. `False` is refused with that
    reason, rather than returning a position that looks like a cumulative dividend and
    pays like none.

**Anti-dilution.** Each alternative is introduced by the model's own instruction:

| Constructor | Source | Wording, verbatim | `PresetPosition.anti_dilution` |
|---|---|---|---|
| `anti_dilution_broad_based_weighted_average()` | COI s.4.4.4 | "[Use the following Section 4.4.4 if the terms sheet calls for a broad-based weighted average anti-dilution provision]" ("terms sheet" is in the original) | `weighted_average_protection(BROAD_BASED_NVCA)` |
| `anti_dilution_full_ratchet(end_date=None)` | COI s.4.4.4 | "[Use the following Section 4.4.4 if the term sheet calls for a full ratchet anti-dilution provision]" ... "at any time after the Original Issue Date [and prior to [Date]] issues Additional Shares of Common Stock" | `FULL_RATCHET` |
| `anti_dilution_none()` | Term Sheet, Anti-dilution Provisions | "[Alternative 3: No price-based anti-dilution protection.]" | `UNPROTECTED` |

- **The full ratchet's end date.** "[and prior to [Date]]" (and fn 57) is a bracket, so
  `end_date` must be stated. Only `None` is accepted: `ovf.financing` reads no date, so a
  ratchet that has lapsed would still be applied.
- **No protection.** The charter drafts no alternative with no protection; it would be
  written by deleting s.4.4.4. The Term Sheet offers it as Alternative 3, so it is
  available, and its record has `within_model=False`.
- **Narrow-based.** fn 56 describes a narrow-based formula without drafting one. It is not
  offered as a preset choice. `ovf.antidilution.NARROW_BASED_OUTSTANDING_STOCK` remains
  available for a position built directly.

`PreferredStock` has no anti-dilution field. The choice travels on the result and is
passed to `ovf.financing.apply_dilutive_issuance` as the position's entry in `protection`.
`anti_dilution_terms(*positions)` builds that mapping.

### Terms the model's text fixes (`origin="model_text"`)

| Term | Provision | Wording, verbatim | What `ovf` sets |
|---|---|---|---|
| Series | Article Fourth; Part B | "[all] of which are hereby designated as "Series A Preferred Stock"" | `series` |
| Ranking ahead of common | s.2.1 | "before any payment shall be made to the holders of Common Stock by reason of their ownership thereof" | any preferred seniority ranks ahead of common in the engine |
| Ranking among preferred | s.2.1, fn 16 | "on a pari passu basis based on their respective Liquidation Amounts" | one series, so no effect; seniority `1` |
| Shortfall | s.2.1 | "the holders of shares of Preferred Stock shall share ratably ... in proportion to the respective amounts which would otherwise be payable" | pro rata by claim within a tier |
| Conversion ratio | s.4.1.1 | "dividing the applicable Original Issue Price by the applicable Conversion Price ... The "Conversion Price" ... as of the Original Issue Date shall be equal to $_______ [insert original purchase price of Series A Preferred Stock] per share" | `conversion_ratio = 1.0` |
| Conversion election | s.2.1(ii), fn 18 | "That alternative formulation is not intended to result in a substantive difference from the approach taken in this form" | each position chooses; the waterfall solves the equilibrium |
| Definition of `A` | s.4.4.4 | ""A" shall mean the number of shares of Common Stock outstanding immediately prior to such issuance ... (treating for this purpose as outstanding all shares of Common Stock issuable upon exercise of Options outstanding ... or upon conversion or exchange of Convertible Securities (including the Preferred Stock) outstanding ...)" | `BROAD_BASED_NVCA` (broad-based choice only) |
| Accruing dividends on conversion | s.4.3.3, fn 46 | "all rights with respect to such shares shall immediately cease and terminate at the Conversion Time, except only the right ... to receive shares of Common Stock ... and to receive payment of any dividends declared but unpaid thereon" | `settlement="forfeit_on_conversion"` (accruing choice only) |
| Cap basis | fn 20, with fn 17/19 | "if the aggregate amount which the holders of Preferred Stock are entitled to receive under Sections 2.1 and 2.2 shall exceed [$_______] per share" | a total cap; `participation_cap_basis="includes_dividends"` when an accruing dividend is present |

Notes on the fixed terms:

- **The conversion election.** fn 18 explains that charters paying "the original purchase
  price ... rather than the higher of such amount and the as-converted payment" assume that
  "the holders ... would simply convert into Common Stock if the as-converted payment is
  greater". That per-position choice is the game the waterfall solves. For several series
  the model's greater-of wording assumes the conversion of "all shares of all other series
  of Preferred Stock that would receive a larger distribution per share if such series of
  Preferred Stock were converted", a circular calculation fn 18 describes at length. No
  proof is offered here that the charter's calculation and the engine's equilibrium
  coincide in every multi-series table. The preset relies on fn 18's statement that the
  two formulations are not meant to differ in substance, and the P10 cases were checked by
  enumerating every conversion profile.
- **Forfeiture on conversion is the model's rule, not every charter's.** s.4.3.3 has no
  bracket on this point, so the preset fixes it. fn 50 records the other practice: "Some
  investors will insist that, upon conversion, all declared but unpaid dividends (and, if
  the Preferred Stock is entitled to accruing dividends, all accrued dividends, whether or
  not declared) be paid in additional shares of Common Stock rather than in cash."
  **`ovf` does not implement fn 50.** It states no price for those shares
  ([dividends](dividends.md), Not modelled). `ovf`'s `settlement="paid_in_kind"` is a
  different drafting: shares of the same series, at liquidation and at conversion, as in
  the Spark Therapeutics charter. A charter drafted either way is not this preset. It can
  be built with `ovf.preferred(..., dividend=cumulative_dividend(..., settlement=...))`.
- **The cap basis is one convention, not two.** fn 20 caps "the aggregate amount ... under
  Sections 2.1 and 2.2". With accruing dividends, the s.2.1 amount is "the Original Issue
  Price, plus any Accruing Dividends accrued but unpaid thereon, whether or not declared"
  (fn 17 and fn 19). So the cap bounds the preference, the accrued dividends and the
  participation together. `ovf.contracts.securities.CumulativeDividend` takes this same
  reading, from the same footnote, when `participation_cap_basis=None`. The preset passes
  `"includes_dividends"` explicitly, so the waterfall reports it as stated:
  `series_a: the participation cap includes accrued dividends (stated; NVCA Model COI fn 20).`
  The two modules agree because they read one footnote.

### Where the charter is silent and the Term Sheet is used

| Point | Why the charter does not settle it | Term Sheet wording, verbatim |
|---|---|---|
| A multiple other than 1 together with accruing dividends | fn 17/19 replace the s.2.1 amount with "the Original Issue Price, plus any Accruing Dividends ...", a text with no multiple. Read literally, the charter gives the accruing-dividend amount at 1x only. | "First pay [one] times the Original Purchase Price [plus accrued dividends] [plus declared and unpaid dividends] on each share of Series A Preferred" |
| No price-based anti-dilution | The charter drafts no such alternative | "[Alternative 3: No price-based anti-dilution protection.]" |
| Shares sold | The charter states authorized shares only | "Investor No. 1: [_______] shares ([__]%), $[_________]" |

The first row decides a number. With a multiple `m` and accrued amount `A`, the claim is
`m × invested + A`, which is what `ovf` computes. The composition comes from the Term
Sheet, and the record `accruing_dividends_in_liquidation_amount` says so. The Term Sheet
footnote to its Dividends term also records the practice fixed above: "Most typically,
however, dividends are not paid if the preferred is converted."

## Out of scope this wave: governance and other bracketed sections

Governance terms are being built separately and are **not carried** by a preset position:
voting (s.3.1), board election (s.3.2), protective provisions (s.3.3), and the Voting
Agreement's drag-along. The other bracketed charter sections with economic effect are also
not carried: s.2.3 Deemed Liquidation Events and their "[specify percentage]" waiver,
s.2.3.4 escrow, s.5 Mandatory Conversion, s.5A pay-to-play and s.6 Redemption. The position
does not claim either branch of these brackets. `PresetPosition.not_represented` lists each
of them with its section, and the table below says what each would change.

## Fixture derivations

**Shared equity**, as in [fixtures](fixtures.md):

- Founders hold 8,000,000 common.
- Series A is `nvca_series_a(shares=2_000_000, original_issue_price=2.50, ...)`, which is
  $5,000,000 invested, converting 1:1. As converted it holds 2,000,000 / 10,000,000 = 20%.

**P1 choices:** 1x (`liquidation_multiple=1.0`), `non_participating()`,
`dividend_as_converted_only()` and `anti_dilution_broad_based_weighted_average()`. Every
other case changes exactly one of these. The fixtures in the test file build them through a
helper, and the helper's defaults exist only to make that one change visible. The preset
itself has no defaults.

**Accruing dividends** (P4, P5, P7):

- The rate is 8% of the Original Issue Price: $0.20 a share, or $400,000 a year for the
  position.
- Accrual runs from 2025-01-01 to `as_of` 2027-01-01. That is 730 days, or 2.0 years under
  Actual/365 Fixed, the time basis of [dividends](dividends.md).

### The position each preset builds

| Case | `liquidation_multiple` | `participating` | `participation_cap` | `dividend` | `anti_dilution` |
|---|---|---|---|---|---|
| P1 | 1.0 | False | None | None | weighted average, `broad_based_nvca` |
| P2 | 1.0 | True | None | None | as P1 |
| P3 | 1.0 | True | 2.0 | None | as P1 |
| P4 | 1.0 | False | None | cumulative 8%, simple, Actual/365 Fixed, from 2025-01-01, forfeit on conversion | as P1 |
| P5 | 1.0 | False | None | as P4, compound, 1 period a year | as P1 |
| P6 | 1.0 | False | None | non-cumulative 8% | as P1 |
| P7 | 1.0 | True | 2.0 | as P4, `participation_cap_basis="includes_dividends"` | as P1 |
| P8 | 2.0 | False | None | None | as P1 |

Every case has 2,000,000 shares at $2.50, seniority 1 and `conversion_ratio = 1.0`.

### Exits through the existing waterfall

**P1: 1x non-participating.** The preference is 1 × $2.50 × 2,000,000 = $5,000,000. Series
A takes the greater of that and 20% of the exit.

- **P1a, $15M:** 20% is $3M < $5M, so Series A holds **$5,000,000**. Founders take
  **$10,000,000**. This is F2.
- **P1b, $35M:** 20% is $7M > $5M, so Series A converts: **$7,000,000**, and founders
  **$28,000,000**. This is F1.
- **P1c, $27M:** 20% is $5.4M > $5M, so Series A converts: **$5,400,000**, and founders
  **$21,600,000**.
- **P1d, $30M:** 20% is $6M > $5M, so Series A converts: **$6,000,000**, and founders
  **$24,000,000**.

**P2: participating, no cap.** The $5M preference is paid, then 20% of the rest.

- **P2a, $15M:** $5M + 20% × $10M = **$7,000,000**, and founders **$8,000,000**. Converting
  would pay $3M.
- **P2b, $35M:** $5M + 20% × $30M = **$11,000,000**, and founders **$24,000,000**. This is F4.

**P3: participating with the fn 20 cap at 2x.** The cap is $10,000,000 in total, $5.00 a
share.

- **P3a, $40M:** $5M + 20% × $35M = $12M exceeds the cap, so the total stops at
  **$10,000,000**. Converting would pay $8M, so Series A holds. Founders take
  **$30,000,000**. This is F5a.
- **P3b, $60M:** the capped amount is $10M. Converting pays 20% × $60M = **$12,000,000**,
  which is more, so Series A converts. Founders take **$48,000,000**. This is F5b, and it
  is fn 20's "greater of (i) the Maximum Participation Amount and (ii) the amount such
  holder would have received if all shares of Preferred Stock had been converted".
- **P3c, $20M:** $5M + 20% × $15M = **$8,000,000**, below the cap. Converting would pay $4M.
  Founders take **$12,000,000**.

**P4: accruing, simple.** $0.20 × 730/365 = $0.40 a share, or **$800,000**. The preference
is $5,800,000.

- At **$27M**, converting pays 20% × $27M = $5.4M < $5.8M, so Series A holds
  **$5,800,000**. Founders take **$21,200,000**. This is [dividends](dividends.md) DW1.

**P5: accruing, compounded annually (fn 13).** There are 2 periods, and 1.08² − 1 = 0.1664.
$5,000,000 × 0.1664 = **$832,000**, so the preference is $5,832,000.

- At **$27M**, converting pays $5.4M, so Series A holds **$5,832,000**. Founders take
  **$21,168,000**.

**P6: non-cumulative 8%.** Nothing accrues, and no `as_of` is read.

- At **$15M** the payout is P1a: Series A **$5,000,000**, founders **$10,000,000**. The
  result's assumptions say that non-cumulative dividends accrue nothing unless declared.

**P7: participating, fn 20 cap at 2x, accruing simple.** The claim is
min($5M + $0.8M, $10M) = $5.8M. The cap is the $10M total, dividends included.

- **P7a, $40M:** $5.8M + 20% × $34.2M = $12.64M exceeds the cap, so the total is
  **$10,000,000**. Converting would pay $8M. Founders take **$30,000,000**. This is
  [dividends](dividends.md) DW2.
- **P7b, $20M:** $5.8M + 20% × $14.2M = $5.8M + $2.84M = **$8,640,000**, below the cap.
  Converting would pay $4M. Founders take **$11,360,000**.

**P8: 2x non-participating.** The preference is 2 × $5M = $10,000,000.

- At **$30M**, converting pays $6M < $10M, so Series A holds **$10,000,000**. Founders take
  **$20,000,000**.

Every fixture has exactly one preferred position, so the equilibrium is Series A's better
action. The test also enumerates both profiles and checks that one payoff vector exists.

### One bracket apart: the same exit, different payouts

This is the argument for making each choice explicit. Each row changes exactly one required
argument:

| Exit | The one choice that differs | Left: Series A | Right: Series A | Difference |
|---|---|---|---|---|
| $15M | s.2.1-2.2: non-participating (P1a) vs participating (P2a) | $5,000,000 | $7,000,000 | **$2,000,000** |
| $27M | s.1: alternative 1 (P1c, converts) vs alternative 3, accruing (P4, holds) | $5,400,000 | $5,800,000 | **$400,000** |
| $27M | s.1 operative text vs fn 13: simple (P4) vs compound (P5) | $5,800,000 | $5,832,000 | **$32,000** |
| $30M | s.2.1 "[__ times]": 1x (P1d) vs 2x (P8) | $6,000,000 | $10,000,000 | **$4,000,000** |
| $20M | s.1 with a fn 20 cap: alternative 1 (P3c) vs accruing (P7b) | $8,000,000 | $8,640,000 | **$640,000** |

Two further contrasts, below, change the anti-dilution alternative (P9) and the rank of a
further series (P10).

### P9: the anti-dilution choice, applied by a down round, then an exit

- **Table:** founders 8,000,000 common, and a P1-shaped Series A with each of the three
  anti-dilution choices.
- **Down round:** the company sells 4,000,000 common to a new investor for $5,000,000, and
  it is not an Exempted Security. So `p = 5,000,000 / 4,000,000 = $1.25`, below `CP1 =
  $2.50`, and `C = 4,000,000`. There are no options and no pool.

**Adjustments** (`ovf.financing`, from the pre-issuance table):

- **P9a, broad-based:** `A = 8,000,000 + 2,000,000 = 10,000,000`, and
  `B = 5,000,000 / 2.50 = 2,000,000`. `CP2 = 2.50 × (10M + 2M) / (10M + 4M) = 2.50 × 12/14 =
  15/7` ($2.142857). The ratio is `2.50 / (15/7) =` **7/6**, so Series A converts into
  7,000,000/3 = 2,333,333.33 common. This is the adjustment of [financing](financing.md) FX1.
- **P9b, full ratchet:** `CP2 = $1.25`, and the ratio is **2**, so 4,000,000 common.
- **P9c, none:** the ratio stays **1**, so 2,000,000 common.

**Exit at $43,000,000.** Series A is the only preferred position. Its preference is $5M,
and in each case converting pays more (shown below), so it converts. Residual cash is
shared over the founders' 8M, the new investor's 4M and Series A as converted.

| Case | Units | Cash per unit | Founders | Series A | New investor |
|---|---|---|---|---|---|
| P9a broad | 8M + 4M + 7M/3 = 43M/3 | $3.00 | **$24,000,000** | **$7,000,000** | **$12,000,000** |
| P9b ratchet | 8M + 4M + 4M = 16M | $2.6875 | **$21,500,000** | **$10,750,000** | **$10,750,000** |
| P9c none | 8M + 4M + 2M = 14M | $43/14 | **$172,000,000/7** ($24,571,428.57) | **$43,000,000/7** ($6,142,857.14) | **$86,000,000/7** ($12,285,714.29) |

The exit $43M was chosen so that the broad-based case divides exactly. Each row sums to
$43M. The choice between the two drafted alternatives of s.4.4.4 moves $3,750,000 to Series
A at this exit.

### P10: a further series, where rank is the one choice that differs

- **Table:** founders 8,000,000 common, and Series A as P1 (seniority 1).
- **Further series:** `additional_series(series="Series B Preferred Stock", ...)` with
  1,500,000 shares at $6.00. That is $9,000,000 invested, 1x non-participating,
  `dividend_as_converted_only()` and broad-based. Only `rank` changes, relative to Series
  A.
- **Exit:** $10,000,000, below the $14M of preferences, so founders receive nothing in
  every case.

| Case | `rank` | Series B seniority | Series A | Series B |
|---|---|---|---|---|
| P10a | `pari_passu` | 1 | $10M × 5/14 = **$25,000,000/7** ($3,571,428.57) | $10M × 9/14 = **$45,000,000/7** ($6,428,571.43) |
| P10b | `senior` | 0 | the $1M remainder: **$1,000,000** | **$9,000,000** |
| P10c | `junior` | 2 | **$5,000,000** | the $5M remainder: **$5,000,000** |

**Checking each position's alternative.** Converting pays, in every case:

- **Series A:** the other series takes its claim first, so Series B receives
  min($10M, $9M) = $9M. The $1M left is shared over 8M + 2M, and Series A receives
  **$200,000**.
- **Series B:** Series A takes $5M. The $5M left is shared over 8M + 1.5M, and Series B
  receives 1.5/9.5 × $5M = **$15,000,000/19** ($789,473.68).

Both are below every held amount in the table, so no position converts. P10a is
[fixtures](fixtures.md) F7 and P10b is F6.

**The contrast.** Pari passu against senior moves 25/7 − 1 = **$18,000,000/7**
($2,571,428.57) away from Series A at the same exit. The model drafts only the first
ranking. So the rank is required, and a non-pari-passu rank is recorded as outside the
model text.

## Using the result

```python
import datetime
import ovf
from ovf import presets as p

series_a = p.nvca_series_a(
    shares=2_000_000,
    original_issue_price=2.50,
    liquidation_multiple=1.0,
    participation=p.participating(maximum_participation_multiple=2.0),
    dividend=p.dividend_accruing(
        rate=0.08, accrual="simple", compounding_frequency=None,
        day_count="actual/365_fixed", accrues_from=datetime.date(2025, 1, 1),
        payable_on_liquidation=True,
    ),
    anti_dilution=p.anti_dilution_broad_based_weighted_average(),
    holder_id="series_a",
    security_id="series_a",
)
table = ovf.CapTable(securities=[
    ovf.common(8_000_000, holder_id="founders", security_id="common"),
    series_a.security,
])
table.waterfall_detailed(20_000_000, as_of=datetime.date(2027, 1, 1))  # P7b
series_a.term("maximum_participation_amount")   # origin, provision, wording
p.anti_dilution_terms(series_a)                 # protection mapping for ovf.financing
```

`PresetPosition` has these fields:

| Field | Contents |
|---|---|
| `security` | the `PreferredStock` |
| `anti_dilution` | the `AntiDilutionProtection` for `ovf.financing` |
| `series`, `series_in_model` | the series name, and whether the model creates it |
| `document` | the charter's URL, version and SHA-256 |
| `terms` | a `TermRecord` per term: name, value, origin, `within_model`, source and verbatim wording |
| `not_represented` | the bracketed sections the position does not carry |
| `assumptions` | the stated conventions |
| `input_hash` | a fingerprint of the inputs |

**Refused input.** Each of the following is refused with a message naming the provision:

- a missing choice;
- a choice passed as anything other than its constructor's object, for example a string,
  a boolean, `None` or an `ovf.antidilution` definition;
- a cap below the multiple;
- simple accrual with a frequency, or compound accrual without one;
- `payable_on_liquidation=False`;
- a full-ratchet end date;
- a `datetime` in place of a date;
- a non-positive, non-finite or boolean number;
- an unknown rank;
- a senior rank above seniority 0;
- a further series reusing the `security_id` of `relative_to`.

## Not modelled

| Not modelled | Why it would change a real number |
|---|---|
| **A second NVCA series** | The model has none (finding above). `additional_series` records the caller's terms; no NVCA text stands behind its rank or its relation to Series A. |
| **Pay-to-play, s.5A** (bracketed section) | A holder that does not buy its Pro Rata Amount in a Qualified Financing is converted to common "at the applicable Conversion Price in effect immediately prior". It loses its preference, and every later exit changes. |
| **Redemption, s.6** (bracketed: not redeemable, or s.6.1-6.5) | A redemption at "[the greater of (A)][the applicable Original Issue Price, plus all declared but unpaid dividends thereon]" is a claim before any exit. |
| **Deemed Liquidation Events, s.2.3** | Which transactions count, and the "[specify percentage]" waiver, decide whether the preference applies at all. The exit passed in is assumed to be one. |
| **Escrow and contingent consideration, s.2.3.4** "[Initial Consideration] [Additional Consideration]" | fn 31's example: $135 received with $15 escrow forfeited pays preferred $90 or $100 depending on the bracket. |
| **Declared but unpaid dividends** (s.2.1 "plus any dividends declared but unpaid thereon") | They are owed on both branches. Settle them outside and net them off, as in [dividends](dividends.md). |
| **Accruing dividends outside the liquidation amount** (fn 14 bracket omitted) | Refused. They would be payable only if declared, and declared dividends are not modelled. |
| **Payment of accrued dividends in common on conversion** (fn 50) | It adds shares on the conversion branch at a price the model does not state. |
| **A lapsing full ratchet** ("[and prior to [Date]]", fn 57) | Refused. After the date, fn 57 contemplates that "broad-based weighted average antidilution applies", a different CP2. |
| **Narrow-based and reserve-inclusive weighted average** (fn 56) | They are described, not drafted. Each gives a different `A`, and therefore a different CP2 ([anti-dilution](antidilution.md)). |
| **Punitive pay-to-play conversion rates** (fn 65) | "It is not uncommon for the conversion rate to be punitive", which means fewer common shares per preferred share. |
| **Whole-share rounding, s.4.2, and CP2 rounding** ("to the nearest one-hundredth of a cent") | Each is less than one share per holder, or $0.00005 of price. |
| **A dollar Maximum Participation Amount shared across series** | fn 20 states one "[$_______] per share" amount for all preferred. For one series this is `multiple × OIP`. With several series at different prices one dollar figure is several multiples, which `additional_series` does not reproduce. |
| **Governance** (s.3 voting, board, protective provisions; Voting Agreement drag-along) | Collective action can block or force an exit, or a conversion (s.5.1(b), the Requisite Holders' vote). This is out of scope for this module. |
| **Exempted Securities, waiver and multiple closings** (s.4.4.1, s.4.4.2, s.4.4.6) | Stated per issuance to `ovf.financing`, not held on the position. See [financing](financing.md). |
| **Charters that depart from the model** | For example, paid-in-kind dividends, dividend priority between series, or a per-series cap in dollars. Build these with `ovf.preferred` directly; they are not this preset. |

## What a fixture does not establish

A fixture shows that the preset reproduces a derivation written here. It does not establish
that a given company's charter follows the NVCA model, or that its brackets were filled the
way the caller states. It also does not establish that the Term Sheet's composition of a
multiple with accruing dividends matches that charter's drafting, or that the list above is
complete. The market frequency of each choice is recorded separately in
[fixtures](fixtures.md), and none of it enters a preset.
