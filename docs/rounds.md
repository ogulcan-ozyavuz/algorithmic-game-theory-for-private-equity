# Rounds: a priced round over an existing cap table

Status 2026-09-15, engine `rounds-v1`, module `ovf.rounds`, with the YC Discount Only and
MFN Only forms and the MFN amendment in `ovf.contracts.safes`. One priced round goes in,
with every term-sheet and charter fact that decides it. A new `CapTable` comes out: each
existing position carried over as the same object, each SAFE replaced in place by the
preferred it converts into, the new-money series appended and any pool increase appended
as its own position. The input table is not modified.

Every expected number below is derived by hand here, then asserted in
`tests/test_rounds.py` against the fixtures in `tests/rounds_fixtures.py`. Each derivation
was rechecked with exact rational arithmetic, in a script independent of the engine, before
it was written down; none was copied from engine output. Where a fixture reproduces a
published worked example, the published figures are compared within the rounding the source
used; they are never the expected values.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty
on every fixture.

`solve_priced_round_with_safes` and its fixtures S1-S5 are unchanged. Its convention turns
out to be one of the three Cooley methods, and `tests/test_rounds.py` reproduces S1-S5
exactly through the new engine.

## What it does

```python
from ovf.financing import UNPROTECTED
from ovf.rounds import (
    SENIOR_TO_ALL, NewSeries, PricedRound, apply_priced_round, pool_target_unallocated,
)

result = apply_priced_round(
    table,
    terms=PricedRound(
        pre_money_valuation=12_000_000,
        new_money=3_000_000,
        convention="percentage_ownership_method",
        pool=pool_target_unallocated(0.10, security_id="pool_a", holder_id="esop"),
        new_series=NewSeries(security_id="series_a", holder_id="lead", seniority=SENIOR_TO_ALL,
                             liquidation_multiple=1.0, participating=False,
                             participation_cap=None),
        safe_series="safe_preferred",
    ),
    protection={"seed": UNPROTECTED},
    mfn=None,
)
result.table                           # the new snapshot
result.conversion("angel").basis       # "safe_price", "discount_price" or "round_price"
```

| Name | Purpose |
|---|---|
| `apply_priced_round(table, *, terms, protection, mfn)` | One priced round applied to a table; returns `RoundResult` |
| `PricedRound(pre_money_valuation, new_money, convention, pool, new_series, safe_series)` | The term-sheet facts. Every field required |
| `PricingConvention` | `"pre_money_method"`, `"percentage_ownership_method"`, `"dollars_invested_method"` |
| `PoolChange`, `pool_target_unallocated`, `pool_increase`, `NO_POOL_CHANGE` | The pool change |
| `NewSeries`, `SeniorityPlacement`, `SENIOR_TO_ALL`, `pari_passu_with`, `explicit_seniority` | The new series and its rank |
| `round_capitalization(table)` | Common, preferred as converted, granted options and unallocated pool before the round |
| `RoundResult`, `SafeConversion`, `ExistingPreferred` | New table, price, both SAFE capitalizations, per-SAFE trace, uniqueness margin, checks, input hash, assumptions |
| `PostMoneyDiscountSAFE`, `safe_post_discount` | YC Postmoney Safe - Discount Only (`ovf.contracts.safes`) |
| `PostMoneyMFNSAFE`, `safe_post_mfn` | YC Postmoney Safe - MFN Only (`ovf.contracts.safes`) |
| `MFNResolution`, `mfn_resolution`, `resolve_mfn`, `MFNAmendment` | Issue order, elections and the Section 3 amendment |

No public function has a default argument and no round-term model has a default field;
`test_public_functions_have_no_default_arguments` and `test_round_facts_have_no_default_fields`
enforce it. Nothing here depends on a date, so nothing takes `as_of`, and nothing reads a
clock (`test_no_clock_is_read`).

## Sources

### Read for this work, verified against the text

| Source | Where | What it decides |
|---|---|---|
| YC Postmoney Safe - Valuation Cap Only | ycombinator.com/documents, `.docx` SHA-256 `185d24f5…49c4`, and the v1.2 PDF | Company Capitalization; the "greater of" conversion; Safe Preferred Stock |
| YC Postmoney Safe - Discount Only | same page, `.docx` SHA-256 `93d606fc…b5a5` | Discount Price, Discount Rate |
| YC Postmoney Safe - MFN Only | same page, `.docx` SHA-256 `d3ad9946…e727` | Section 3 amendment; Subsequent Convertible Securities |
| YC Post-Money Safe User Guide | same page, PDF SHA-256 `415e4d60…58ca` | Original-safe capitalization table; Appendix I (MFN, cap-and-discount); Appendix II worked rounds |
| Cooley, "Calculating Share Price With Outstanding Convertible Notes or Safes" | [cooleygo.com](https://www.cooleygo.com/calculating-share-price-outstanding-convertible-notes-or-safes/), Derek Colla, last reviewed 24 January 2022 | The three pricing methods and their worked example |
| NVCA Model Term Sheet | [nvca.org, 2019 `.doc`](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Term-Sheet-1.doc) | Pool inside the fully-diluted pre-money; both pool forms |

The October 2025 NVCA term sheet was not read: the URL tried returned a 548-byte HTML page,
not the document. Everything quoted from the term sheet is from the 2019 file.

### Not read

- **The original (pre-money) YC safe.** It is no longer on YC's documents page, and an
  archived copy could not be retrieved. Its capitalization is taken from the User Guide's
  comparison table, quoted under item 5. **UNVERIFIED** beyond that table: in particular,
  whether the original form converted into its own Safe Preferred series is not confirmed
  from its text.
- **The YC post-money "Valuation Cap and Discount" form.** The User Guide's Appendix I
  describes it ("Either the Post-Money Valuation Cap or the Discount Rate applies ...
  depending on which calculation is most advantageous to the investor"), but it is not on the
  current documents page. `PostMoneySAFE` with a nonzero `discount_rate` applies that
  best-of rule, as it always has; the form's own text was not read.
- **No court decision or practitioner commentary** on any reading below was consulted.

---

## Item 1: an existing option pool and granted options

**The text.** Company Capitalization, verbatim from the Valuation Cap Only form, Section 2:

> "Company Capitalization" is calculated as of immediately prior to the Equity Financing and
> (without double-counting, in each case calculated on an as-converted to Common Stock
> basis):
> - Includes all shares of Capital Stock issued and outstanding;
> - Includes all Converting Securities;
> - Includes all (i) issued and outstanding Options and (ii) Promised Options; and
> - Includes the Unissued Option Pool, except that any increase to the Unissued Option Pool
>   in connection with the Equity Financing will only be included to the extent that the
>   number of Promised Options exceeds the Unissued Option Pool prior to such increase.

and "'Unissued Option Pool' means all shares of Capital Stock that are reserved, available
for future grant and not subject to any outstanding Options or Promised Options". So an
existing unallocated reserve and granted options count in the denominator, and the increase
made with the round does not.

**Decision 1: what the pool target means.** The legacy `target_pool_pct` is "the new pool
is this fraction of post-round shares", which has no meaning once a pool already exists. Two
readings occur, and the sources show both:

- A **target post-round unallocated fraction**, of which part already exists. The User
  Guide's worked rounds state "Target available option pool: 10%" and describe the pre-money
  as including "an ungranted and unallocated employee option pool representing 10% of the
  fully-diluted post-closing capitalization". The NVCA term sheet (2019) prices the round on
  "a fully-diluted pre-money valuation of $[_____] and a fully-diluted post-money valuation
  of $[______] (including an employee pool representing [__]% of the fully-diluted
  post-money capitalization)".
- An **absolute share increase**. The NVCA term sheet also has the bracketed alternative
  "[Immediately prior to the Series A Preferred Stock investment, [______] shares will be
  added to the option pool creating an unallocated option pool of [_______] shares.]", and
  the User Guide computes its examples with a fixed "Option pool increase: 1,695,000 shares".

They give different answers whenever anything else in the round moves (asserted in
`test_target_pool_is_hit_exactly_and_an_absolute_increase_is_not_recomputed`: raise the new
money and the target recomputes the increase; the absolute increase leaves the unallocated
pool below target). So both are supported and neither is a default: `pool_target_unallocated`
and `pool_increase`, plus `NO_POOL_CHANGE`. The target is the **unallocated** pool, the
User Guide's "available" pool and the term sheet's "unallocated option pool"; a target
measured on the whole pool including grants is not modelled. Either increase sits inside
the pre-money share count, which is the term-sheet placement. A target below the existing
reserve is refused rather than treated as a cancellation.

**Decision 2: granted options count gross.** Company Capitalization counts "issued and
outstanding Options" on "an as-converted to Common Stock basis": the shares the options are
for, not net of strike proceeds. The User Guide's worked tables count 300,000 outstanding
options as 300,000 fully diluted shares. The treasury method is not modelled.
`StockOptionPool.allocated_shares` is read as granted options.

**Promised options** are not represented. Promised options that fit inside the existing
reserve give the same Company Capitalization as grants, because both are included and both
reduce the Unissued Option Pool, so they may be entered as `allocated_shares`; the YC
fixtures do exactly that. Promised options beyond the reserve would pull part of the
increase into the denominator under the exception quoted above; that is not modelled.

### EP1: an existing pool with grants, a 10% target and one post-money SAFE

Table: 8,000,000 common; a pool of 1,000,000 reserved, of which 500,000 are granted; a $1M
post-money SAFE at a $10M cap. Round: $3M at $12M pre, so `W = 15M` and `q = 0.2`; target
10% unallocated; percentage-ownership method.

Outstanding `F = 8M + 0.5M = 8.5M`; existing unallocated `E = 0.5M`. Under this method the
new money buys `qT`, so `P = W/T`. The unallocated pool after the round is `0.1T`, the
increase `0.1T − 0.5M`. What the share count leaves for the SAFE is
`A(T) = T − F − 0.1T − 0.2T = 0.7T − 8.5M`, and Company Capitalization is
`B = F + E + A(T) = 0.7T + 0.5M`.

The SAFE takes the greater of `I/P = T/15` and `I·B/K = 0.1B = 0.07T + 50,000`; the cap
branch is larger for every positive `T`. Balance: `0.7T − 8.5M = 0.07T + 50,000`, so
`0.63T = 8.55M` and **T = 95M/7 = 13,571,428.57**.

- `B = 0.7 × 95M/7 + 0.5M =` **10,000,000**: 8M common + 0.5M granted + 0.5M unallocated +
  1M SAFE. The 6M/7 increase and the new money are not in it.
- SAFE shares **1,000,000** at a Safe Price of $10M / 10M = **$1.00**.
- `P = 15M/T =` **$21/19** ($1.105263). The round option `T/15 = 904,761.90` is smaller.
- Increase `= 9.5M/7 − 0.5M =` **6M/7** (857,142.86); unallocated after `9.5M/7`, exactly 10%.
- New money shares `0.2T =` **19M/7** (2,714,285.71).
- Check: `8M + 0.5M + 0.5M + 6M/7 + 1M + 19M/7 = 10M + 25M/7 = 95M/7`.
- Ownership: founders `56/95` (58.95%), SAFE `7/95` (7.37%), esop (granted, existing reserve
  and increase) `13/95` (13.68%), Series A `19/95` (20%). The pre-money SAFE capitalization,
  reported but unused here, is `F + 9.5M/7 = 69M/7`.

### YC1-Q2: the User Guide's Example 1, Question 2

Table, from the Guide: 9,250,000 founder common; 300,000 options outstanding and 350,000
promised options (entered as 650,000 allocated of a 750,000 reserve); 100,000 available.
Investor A: $200,000 at a $4M post-money cap. Investor B: $800,000 at an $8M post-money cap.
Round: $5M at $15M pre, so `q = 0.25`; the Guide's pool increase of 1,695,000 shares, entered
as `pool_increase(1_695_000)`.

- Company Capitalization: `B = 10,000,000 + 0.05B + 0.10B`, so
  `B = 10,000,000 / 0.85 =` **200M/17** (11,764,705.88).
- A `= 0.05B =` **10M/17** (588,235.29); B `= 0.10B =` **20M/17** (1,176,470.59). Their
  round options, `200,000/P ≈ 179,463` and `800,000/P ≈ 717,851`, are smaller.
- Pre-money share count `B + 1,695,000 = 228,815,000/17`; price
  `15M × 17 / 228,815,000 =` **$51,000/45,763** ($1.114437).
- New money shares `= 5M/P = 228,815,000/51` (4,486,568.63), one third of the pre-money count.
  `T = 915,260,000/51` (**17,946,274.51**).

The Guide prints 11,764,705; 588,235; 1,176,470; $1.1144; 4,486,719 and 17,946,424. The
Guide rounds the price to $1.1144 before dividing ($5M / $1.1144 = 4,486,719), which accounts
for the new-money difference. Every printed figure is within 1e-4 of the exact value
(`test_fixture_agrees_with_the_published_source`).

### YC1-Q2t: the same round with the Guide's stated 10% target

`A(T) = T − 9.9M − 0.1T − 0.25T = 0.65T − 9.9M`; `B = 0.65T + 0.1M`; both caps bind, so the
SAFEs take `0.15B`. Balance: `0.65T − 9.9M = 0.15(0.65T + 0.1M)`, so `0.5525T = 9,915,000`
and **T = 3,966,000,000/221** (17,945,701.36). `B` is again 200M/17: a binding post-money cap
does not see the pool. Increase `0.1T − 100,000 =` **374,500,000/221** (1,694,570.14); price
`20M/T =` **$2,210/1,983** ($1.114473); new money `T/4 = 991,500,000/221`.

The Guide's 1,695,000 is 429.86 shares more than its own 10% target requires. It is
consistent with the target rounded to the nearest thousand shares; that is an inference,
not something the Guide says. Entered as a target, the round gives exactly 10%; entered as
the Guide's share count, 10.0021%.

---

## Item 2: preserving existing preferred through a round

**Function or event object?** An event object applied to a table, as in `ovf.financing`:
`apply_priced_round(table, *, terms, protection, mfn)`. It reads the prior table, requires
every charter fact the round turns on, and returns a new table and a trace. `protection` is
the same mapping `ovf.financing.apply_dilutive_issuance` takes, with the same rule: it must
name every preferred position, `UNPROTECTED` included, so nothing is left alone by omission.

**Existing preferred is carried as the same objects**, with every term (seniority, multiple,
participation, conversion ratio, dividend) unchanged, and counts in every denominator at
its conversion ratio in effect ("calculated on an as-converted to Common Stock basis").
Non-convertible debt is carried and counts nothing.

**Seniority of the new series is a parameter with no default.** `SENIOR_TO_ALL` ranks it one
step ahead of the most senior existing preferred; `pari_passu_with(security_id)` gives it
that position's rank; `explicit_seniority(n)` uses `n`. A table records no issue dates, so
"pari passu with the most recent series" is expressed by naming that series. `SENIOR_TO_ALL`
is refused when there is no existing preferred (use an explicit rank for a first round) and
when the most senior rank is already 0, the top of the scale; the table is not renumbered
behind the caller's back.

**Converting SAFEs: their own series or the new one.** The YC post-money forms decide it for
their own instruments. Safe Preferred Stock means "the shares of the series of Preferred
Stock issued to the Investor in an Equity Financing, having the identical rights, privileges,
preferences, seniority, liquidation multiple and restrictions as the shares of Standard
Preferred Stock, except that any price-based preferences (such as the per share liquidation
amount, initial conversion price and per share dividend amount) will be based on the Safe
Price" (Discount Price in the Discount Only form). The User Guide: "The only differences
between the Series A-1 Preferred and the Series A-2 Preferred would be the name, share
price, per share liquidation amount (but not the liquidation preference or multiple)", and
"the liquidation amount for safe holders does not exceed the original purchase amount".

The other practice, converting everything into the new series at the round price, gives a
SAFE that converted below the round price a preference above its Purchase Amount. It
changes exit payouts (fixture MR-X3), so it is a required parameter:

- `safe_series="safe_preferred"`: a SAFE converting at its Safe Price or Discount Price gets
  its own position whose per-share preference is that price; one converting at the round
  price gets new-series shares at the round price. The YC forms.
- `safe_series="standard_preferred"`: every SAFE gets new-series shares with the round price
  as per-share preference. No source form was read that prescribes this; it is offered
  because it occurs and because it moves money, and it departs from the YC text.

Either way the SAFE takes the new series' rank, multiple and participation terms, and a
conversion ratio of 1.

### Anti-dilution inside a round

A protected existing position is carried unchanged when no share in the round is issued
below its conversion price in effect (`price / conversion_ratio`), counting the new-money
price and every SAFE's conversion price. **When one is, the round is refused.** Two things
would have to be settled first, and the sources read do not settle either:

1. **The price is circular.** The term sheet prices the round on "a fully-diluted pre-money
   valuation". Whether that count includes the shares the round's own anti-dilution
   adjustment creates is not stated. If it does, the price depends on the adjustment and the
   adjustment on the price.
2. **SAFE conversions below the conversion price.** A SAFE is a Convertible Security whose
   conversion count NVCA 4.4.3 deems "not calculable" until the round (see
   [financing](financing.md)); how its conversion shares, issued at a Safe Price below a
   protected series' price, enter that series' adjustment is a deemed-issuance question this
   project has not read far enough to answer.

`ovf.financing.apply_dilutive_issuance` remains the tool for an adjustment. It prices
nothing and takes the issue price as stated, so the pricing-basis question stays with the
caller. Refused: `test_a_triggered_protected_position_refuses_the_round`,
`test_a_safe_converting_below_a_protected_price_refuses_the_round`. Carried:
`test_a_protected_position_not_triggered_is_carried_unchanged`.

### MR: a SAFE, then a Series A, then a Series B down round

**Event 1, the SAFE.** Founders 8,000,000 common; a pool of 1,000,000, all unallocated; a
$1M post-money SAFE at a $10M cap. `round_capitalization`: common 8M, preferred 0, granted 0,
unallocated 1M.

**Event 2, Series A.** $3M at $12M pre (`q = 0.2`), 10% unallocated target, Series A at
`explicit_seniority(1)`, percentage-ownership method. `F = 8M`, `E = 1M`.
`A(T) = T − 8M − 0.1T − 0.2T = 0.7T − 8M`; `B = F + E + A = 0.7T + 1M`; the SAFE takes
`0.1B = 0.07T + 100,000` (above `T/15`). Balance `0.63T = 8.1M`: **T = 90M/7**
(12,857,142.86). `B = 10M`, so the SAFE takes **1,000,000** shares at **$1.00**. Price
`15M/T =` **$7/6**. Increase `0.1T − 1M =` **2M/7**; new money `0.2T =` **18M/7**.

| Position | Shares | Per-share preference | Seniority | Ownership |
|---|---|---|---|---|
| `common` (founders) | 8,000,000 | — | — | 28/45 (62.22%) |
| `pool` | 1,000,000 | — | — | } 1/10 together |
| `pool_a` | 2M/7 = 285,714.29 | — | — | } |
| `angel` (Safe Preferred) | 1,000,000 | $1.00 | 1 | 7/90 (7.78%) |
| `series_a` | 18M/7 = 2,571,428.57 | $7/6 | 1 | 1/5 |
| **Fully diluted** | **90M/7** | | | |

**Event 3, Series B down round.** $4M at $6M pre (`q = 0.4`), no pool change, Series B
`SENIOR_TO_ALL`, both existing positions stated `UNPROTECTED`. No SAFEs, so the price is
`6M / (90M/7) =` **$7/15** ($0.466667), below both $7/6 and $1.00. New money `4M ÷ 7/15 =`
**60M/7**; `T = 150M/7`. Series B ranks 0. Ownership: founders `28/75`, `angel` `7/150`,
`series_a` `3/25`, esop `3/50`, `series_b` `2/5`. Every existing position is the same object
as in the Series A table.

**Exits.** Issued shares sharing a residual: `8M + 1M + 18M/7 + 60M/7 = 141M/7`; the
unallocated pool takes nothing.

- **MR-X1, $6M, Series B senior.** Series B takes its $4M. The remaining $2M meets rank 1
  claims of $3M (Series A) and $1M (the SAFE's Safe Preferred), pro rata: Series A
  **$1.5M**, SAFE **$0.5M**, common $0. Deviations: Series B converting gets
  `$2M × (60/7)/(8 + 60/7) = $1.034M`; Series A converting gets
  `$1M × (18/7)/(8 + 18/7) = $0.243M`; the SAFE converting gets $0. None improves.
- **MR-X2, $6M, Series B pari passu with Series A.** One tier of $4M + $3M + $1M = $8M
  against $6M: Series B **$3M**, Series A **$2.25M**, SAFE **$0.75M**. Deviations likewise pay
  $1.034M, $0.243M and $0.
- **MR-X3, $6M, Series B senior, `safe_series="standard_preferred"` at Series A.** The SAFE
  holds the same 1,000,000 shares but claims `1M × $7/6`. The $2M splits 7 : 18: SAFE
  **$0.56M**, Series A **$1.44M**. Only the preference basis moved, and it moved $60,000.
- **MR-X4, $141M.** `$141M ÷ 141M/7 = $7` a share, everyone converts: common **$56M**, SAFE
  **$7M**, Series A **$18M**, Series B **$60M**.

The test also enumerates every conversion profile at each exit and finds one payoff vector.

---

## Item 3: discount-only SAFEs

**The text.** Discount Only form, Section 1(a): the Safe converts "into the number of shares
of Safe Preferred Stock equal to the Purchase Amount divided by the Discount Price"; Section
2: "'Discount Price' means the lowest price per share of the Standard Preferred Stock sold in
the Equity Financing multiplied by the Discount Rate"; the cover: "The 'Discount Rate' is
[100 minus the discount]%". `PostMoneyDiscountSAFE.discount` is the discount itself, so YC's
Discount Rate is `1 − discount`.

**The interaction.** The Discount Only form has no Company Capitalization of its own. But
the capped form's Converting Securities "includes this Safe and other convertible securities
issued by the Company, including but not limited to: (i) other Safes", so a discount SAFE's
conversion shares sit in a capped SAFE's denominator.

### DO1: one discount-only SAFE

$1M at a 20% discount; 8,000,000 common; $3M at $12M pre; no pool; percentage-ownership.
`P = 15M/T`; the SAFE takes `1M / (0.8P) = T/12`; `A(T) = 0.8T − 8M`. Balance
`0.8T − 8M = T/12`, so `T × 43/60 = 8M` and **T = 480M/43** (11,162,790.70). Price
**$43/32** ($1.34375); Discount Price $1.075; SAFE **40M/43** shares (930,232.56); new money
`0.2T = 96M/43`. Ownership: founders **43/60** (71.67%), SAFE **1/12**, new **1/5**.

### DO2: a discount-only SAFE beside a capped SAFE

Add a $1M post-money SAFE at a $10M cap. `B = F + A(T) = 0.8T`, which counts the discount
SAFE. The capped SAFE takes `max(T/15, 0.08T) = 0.08T`; the discount SAFE `T/12`. Balance
`0.8T − 8M = 0.08T + T/12`, so `T × 191/300 = 8M` and **T = 2400M/191** (12,565,445.03).
Price **$191/160** ($1.19375). `B = 1920M/191` (10,052,356.02); capped SAFE **192M/191**
(1,005,235.60) at a Safe Price of $0.994792; discount SAFE **200M/191** (1,047,120.42) at
$0.955. Ownership: founders **191/300**, capped SAFE **2/25** (8%), discount SAFE **1/12**,
new **1/5**.

The capped SAFE still holds exactly 10% of its Company Capitalization; the discount SAFE is
paid for by the founders. Had the discount SAFE been left out of that denominator, the capped
SAFE would take `0.1 × (8M + K)`, that is 888,888.89 shares instead of 1,005,235.60.

---

## Item 4: MFN SAFEs

**The text.** MFN Only form, Section 3, verbatim:

> "MFN" Amendment Provision. If the Company issues any Subsequent Convertible Securities
> with terms more favorable than those of this Safe (including, without limitation, a
> valuation cap and/or discount) prior to termination of this Safe, the Company will
> promptly provide the Investor with written notice thereof, together with a copy of such
> Subsequent Convertible Securities (the "MFN Notice") and, upon written request of the
> Investor, any additional information related to such Subsequent Convertible Securities as
> may be reasonably requested by the Investor. In the event the Investor determines that the
> terms of the Subsequent Convertible Securities are preferable to the terms of this
> instrument, the Investor will notify the Company in writing within 10 days of the receipt
> of the MFN Notice. Promptly after receipt of such written notice from the Investor, the
> Company agrees to amend and restate this instrument to be identical to the instrument(s)
> evidencing the Subsequent Convertible Securities.

"Subsequent Convertible Securities" are "convertible securities that the Company may issue
after the issuance of this instrument with the principal purpose of raising capital,
including but not limited to, other Safes, convertible debt instruments and other
convertible securities", excluding plan options, lender and supplier convertibles, strategic
issuances and side letters. Unamended, Section 1(a) converts the Safe "into the number of
shares of Standard Preferred Stock equal to the Purchase Amount divided by the lowest price
per share of the Standard Preferred Stock". User Guide, Appendix I: "the MFN of the safe is
amended away once the safe holder decides the MFN is triggered ... the MFN Provision
typically provides only one opportunity to amend the safe", and "the MFN Provision does not
permit the 'cherry-picking' of terms ... the amended safe will be identical to the later
safe (other than the Purchase Amount)".

**What the text settles.**

- **Continuously, not once at the round.** The trigger is each issuance of a Subsequent
  Convertible Security; notice is "prompt", the election window is "within 10 days of the
  receipt of the MFN Notice". Nothing waits for the Equity Financing.
- **The whole instrument, not the cap or the discount.** The amended Safe is "identical to"
  the later instrument: its cap and its discount together, from one instrument, keeping its
  own Purchase Amount. The User Guide says so in terms ("does not permit the
  'cherry-picking' of terms").
- **One opportunity.** Once amended to a Safe without an MFN clause, there is no MFN left.
- **The holder decides.** The amendment happens only when "the Investor determines that the
  terms ... are preferable". The model cannot make that determination. Fixtures MF-cap and
  MF-disc show why: at a $12M pre-money the later discount SAFE would have given the holder
  1/24 of the company against 1/25 for the capped SAFE; at $48M pre with $12M new
  (`test_which_election_is_better_depends_on_the_round`) the capped SAFE gives `1/25` and the
  discount `1/96`. Which is "preferable" depends on a round that has not happened.

**The model.** `MFNResolution(issue_order, elections)`: the order in which every Safe in the
round was issued, and for every MFN Only Safe the id of the later Safe its holder elected, or
`None`. Neither has a default. `resolve_mfn` rewrites each electing Safe into a copy of the
elected instrument with its own Purchase Amount, holder and id, before anything converts, and
refuses: an elected Safe issued at or before the MFN Safe; an elected MFN Only Safe (no cap
and no discount is not "more favorable"); an id that is not a Safe in the round; an issue
order that does not list every Safe exactly once; elections that do not name exactly the MFN
Only Safes. Because each election refers to an instrument as issued, the order in which
elections are applied cannot matter. `apply_priced_round` requires `mfn` exactly when the
table holds an MFN Only Safe.

### MF: three instruments in issue order

An MFN Only Safe of $500,000 (`mfn`), then a $1M capped post-money Safe at $10M (`cap`), then
a $1M discount-only Safe at 20% (`discount`). 8,000,000 common; $3M at $12M pre; no pool;
percentage-ownership. For every election, `A(T) = 0.8T − 8M`, `B = 0.8T`, `cap` takes
`max(T/15, 0.08T) = 0.08T` and `discount` takes `T/12`.

- **MF-none**: `mfn` converts at the round price, `0.5M × T/15M = T/30`. Balance
  `T × (0.72 − 1/12 − 1/30) = T × 181/300 = 8M`: **T = 2400M/181**, price **$181/160**.
  Shares: `mfn` 80M/181, `cap` 192M/181, `discount` 200M/181. Ownership: founders
  **181/300**, `mfn` **1/30**, `cap` 2/25, `discount` 1/12, new 1/5.
- **MF-cap**: `mfn` becomes $500,000 at a $10M cap, `max(T/30, 0.05 × 0.8T) = 0.04T`.
  `T × 179/300 = 8M`: **T = 2400M/179**, price **$179/160**; `mfn` **1/25**, at a Safe Price
  of `10M/(0.8T) = $179/192`.
- **MF-disc**: `mfn` becomes $500,000 at a 20% discount, `T/24`.
  `T × (0.72 − 1/12 − 1/24) = 0.595T = 8M`: **T = 1600M/119**, price **$357/320**; `mfn`
  **1/24**.

---

## Item 5: mixed pre- and post-money SAFEs, and Cooley's conventions

### The two capitalizations

User Guide, "In an Equity Financing, how does the calculation ... differ", comparison table
(original safe / post-money safe): outstanding shares of Capital Stock included / included;
outstanding Options included / included; Promised Options included* / included; Unissued
Option Pool included / included; **Option Pool Increase included / excluded**; **Safes,
convertible notes and other similar convertibles excluded / included**. So in one round the
two forms measure their caps against different share counts:

- post-money: `B_post = F + E + ΣS` (everything outstanding, the existing reserve, every
  converting SAFE including the pre-money ones; not the increase, not the new money);
- pre-money: `B_pre = F + E + Δ` (the reserve including the increase; no SAFEs).

The User Guide's Example 2 is a worked round with one of each; it is reproduced below.

### The round as one fixed point

Notation: `F` outstanding common, preferred as converted and granted options; `E` the
existing unallocated reserve; `Δ` the increase; `V` pre-money; `N` new money; `W = V + N`;
`P` price; `S_k` SAFE shares, with purchase amount `I_k`, cap `K_k`, discount `d_k` and
`f_k = 1/(1 − d_k)`; `T` post-round fully diluted shares.

The round is the system:

1. share count: `T = F + E + Δ + ΣS_k + N/P`;
2. pricing, one equation per convention: `P·(F + E + Δ) = V` (pre-money method),
   `P·(F + E + Δ + ΣS_k) = V` (percentage ownership),
   `P·(F + E + Δ + ΣS_k) = V + ΣI_k` (dollars invested);
3. each SAFE: `S_k = I_k·max(f_k/P, B_k/K_k)` with `B_k = B_post` or `B_pre`; a discount-only
   Safe `S_k = I_k f_k/P`; an unamended MFN Safe `S_k = I_k/P`;
4. pool: `E + Δ = tT` (target) or `Δ = Δ₀` (increase by shares).

**Reduction to one unknown.** Fix `T`. By (4), the pool after the round `p(T)` is `tT` or
`E + Δ₀`. By (1) and (2), `1/P` is determined: `T/W` (percentage ownership, because
`P(T − N/P) = V`), `T/(W + ΣI)` (dollars invested), or `(F + p(T))/V` (pre-money method). What
(1) leaves for the SAFEs is `A(T) = T − F − p(T) − N/P(T)`, and then `B_post(T) = F + E + A(T)`
and `B_pre(T) = F + p(T)`. Every one of these is **affine in `T`**. So each
`S_k(T) = I_k·max(f_k·(1/P)(T), B_k(T)/K_k)` is a maximum of affine functions: convex and
piecewise affine. The whole system reduces to

    g(T) = A(T) − Σ_k S_k(T) = 0.

**Proposition.** Let `s∞ = A′ − Σ_k max(I_k f_k (1/P)′, I_k B_k′/K_k)`, the slope of `g`
beyond its last kink. If `s∞ > 0`, the round has exactly one solution.

*Proof.* `g` is an affine function minus a sum of convex functions, so it is concave and
piecewise affine, and its slope is non-increasing in `T`. Beyond the last kink the slope is
`s∞`, so every slope of `g` is at least `s∞ > 0`: `g` is strictly increasing, and
`g(T) ≥ g(0) + s∞T → ∞`. At `T = 0`, `A(0)` is `−F` (target pool under percentage ownership or
dollars invested), `−F − E − Δ₀` (increase by shares) or `−F − N(F + p(0))/V` (pre-money method),
all negative because `F > 0`; and every `S_k(0) ≥ 0` because its price option
`I_k f_k (1/P)(0)` is nonnegative. So `g(0) < 0`, and `g` has exactly one root `T* > 0`. Every
quantity of the round (price, pool, new shares, each `S_k`) is a function of `T`, so the
solution is unique. ∎

**When `s∞ ≤ 0` the round is refused.** Then `g` is concave and bounded above for large `T`,
so it has no root, a tangent root or two roots, and none of these is reported. For a round
of post-money capped SAFEs alone and no existing pool, `s∞ ≤ 0` is exactly the legacy
solver's refusal `Σ fractions ≥ 1`. For pre-money SAFEs alone, `g(T) = −T·h(C/T)` with `h` the
legacy solver's increasing balance, so `s∞ ≤ 0` means no solution at all. Whether a general
mixed table can have two solutions was not settled: no example was constructed and none was
excluded. The refusal rests on the sufficient condition, and the margin `s∞` is reported on
every result as `uniqueness_margin`.

**The solver.** Bracket the root on `[0, U]`, with `U` from `g(U) ≥ g(0) + s∞U`; bisect until
the bracket is `1e-14 U` wide; then solve the affine piece of `g` in force exactly. Checks
after the solve: share conservation within `max(1e-8, 1e-10 T)`, the legacy solver's
tolerance; the pricing identity of the stated convention within `1e-9` of the effective
pre-money; a target that would need a negative increase is refused.

### YC1-Q5: the User Guide's Example 1, Question 5

The same table as YC1-Q2. $2.2M at $8.8M pre (`q = 0.2`); pool increase 1,573,000. Investor
B converts at the round price, A at its cap, so the price and B's shares are simultaneous
even with a fixed pool.

`S_B = 800,000/P`; `B_c = 10M + S_A + S_B` with `S_A = 0.05 B_c`, so `B_c = (10M + S_B)/0.95`.
Pricing: `P × (B_c + 1,573,000) = 8.8M`. Multiplying through by 0.95:
`P × (10M + 1,494,350) = 8,360,000 − 800,000`, so **P = 7,560,000/11,494,350 = $2,400/3,649**
($0.657714).

- `S_B = 800,000 × 3,649/2,400 =` **3,649,000/3** (1,216,333.33); its cap option
  `0.1 B_c = 1,180,666.67` is smaller, so the round price does bind.
- `B_c = 35,420,000/3` (11,806,666.67); `S_A =` **1,771,000/3** (590,333.33); its round option
  `200,000/P ≈ 304,083` is smaller.
- New money `2.2M/P =` **10,034,750/3**; **T = 50,173,750/3** (16,724,583.33).

The Guide prints $0.6577, 590,334, 1,216,360, 3,344,990 and 16,724,684, each within 1e-4.

### YC2-Q2: the User Guide's Example 2, Question 2, mixed, caps bind

The same table with Investor A holding a **pre-money** $200,000 Safe at a $3.8M cap. $5M at
$15M pre; pool increase 1,700,000.

- Pre-money capitalization (the Guide: "Pre-Financing Fully Diluted Shares + Option Pool
  Increase") `10,000,000 + 1,700,000 = 11,700,000`; A `= 200,000 × 11.7M/3.8M =`
  **11,700,000/19** (615,789.47), a Safe Price of $0.324786.
- Post-money Company Capitalization, which counts A: `B_c = (10M + 11.7M/19)/0.9 =`
  **2,017,000,000/171** (11,795,321.64); B `=` **201,700,000/171** (1,179,532.16).
- Pre-money share count `B_c + 1,700,000 = 2,307,700,000/171`; price **$25,650/23,077**
  ($1.111496). Round options (about 179,937 and 719,748 shares) are smaller.
- New money `= 2,307,700,000/513` (4,498,440.55); **T = 9,230,800,000/513** (17,993,762.18).

The Guide prints $0.3248, 615,763, 11,795,292, 1,179,529, $1.1115, 4,498,426 and 17,993,718,
each within 1e-4. **The Guide contains a typo here:** it states the new-money shares as
"$5,000,000 divided by the Series A-1 price per share of $1.1144", but 4,498,426 is
$5M / $1.1115; $5M / $1.1144 would be 4,486,719, Example 1's figure.

With a fixed increase and both caps binding, this system happens to be triangular: A first,
B second, the price last, which is how the Guide computes it. The engine does not know in
advance which option binds, and solves the whole system.

### YC2-Q5: Example 2, Question 5, mixed, B at the round price

$2.2M at $8.8M pre; increase 1,575,000. A `= 200,000 × 11,575,000/3.8M =` **11,575,000/19**
(609,210.53). B takes `800,000/P`, so pricing gives
`P × (11,575,000 + 11,575,000/19) + 800,000 = 8.8M`, that is `P × 11,575,000 × 20/19 = 8M`, and
**P = $304/463** ($0.656587). B `=` **23,150,000/19** (1,218,421.05), above its cap option
`0.1 × 224,725,000/19 = 1,182,763.16`. New money **63,662,500/19**;
**T = 318,312,500/19** (16,753,289.47). The Guide prints $0.6566, 609,198, 1,218,397,
3,350,594 and 16,753,189, each within 1e-4.

### MX1: both denominators, no pool

8,000,000 common; a $1M post-money SAFE at $10M (`post`) and a $1M pre-money SAFE at $8M
(`pre`); $3M at $12M pre. `A(T) = 0.8T − 8M`, `B_post = 0.8T`, `B_pre = 8M`, `1/P = T/15M`.
`post` takes `max(T/15, 0.08T) = 0.08T`; `pre` takes `max(T/15, 1M × 8M/8M)`. On the cap
branch for `pre`: `0.72T = 9M`, **T = 12.5M**, and `T/15 = 833,333 < 1M` confirms the branch.
Price **$1.20**; both SAFEs **1,000,000** shares at **$1.00**; new money 2.5M.
`B_post =` **10M** includes `pre`'s shares; `B_pre =` **8M** includes neither. Ownership 64%,
8%, 8%, 20%. `s∞ = 0.8 − 0.08 − 1/15 = 49/75`.

### MX2: both denominators move with T

$1M post-money at $10M and $500,000 pre-money at $5M; $4M at $16M pre (`q = 0.2`); 10% target.
`A(T) = 0.7T − 8M`; `B_post = 0.7T`; `B_pre = 8M + 0.1T`. `post` takes
`max(T/20, 0.07T) = 0.07T`; `pre` takes `max(0.025T, 0.1(8M + 0.1T))`. On the cap branch:
`0.7T − 8M = 0.07T + 800,000 + 0.01T`, `0.62T = 8.8M`, **T = 440M/31** (14,193,548.39), and
`800,000 + 0.01T = 941,935.48 > 0.025T` confirms it. Price **$31/22**; `post` **30.8M/31** at
$310/308; `pre` **29.2M/31** at $155/292; new **88M/31**; increase **44M/31**. Ownership:
founders **31/55**, `post` **7%**, `pre` **73/1100**, new 20%, pool 10%.

### Cooley's three conventions

Cooley, verbatim: "In the pre-money method, the pre-money valuation of the company is fixed
and the conversion price for the notes or Safes is determined based on that"; "In the
percentage-ownership method, the percentage ownership of the company that the investor is
purchasing is fixed and the other variables are computed based on that"; "In the
dollars-invested method, the post-money valuation of the company is fixed to equal the
agreed upon pre-money valuation plus the dollars invested by the new investors plus the
principal and accrued interest on the notes that are converting". And: "The pre-money method
causes both the Founders and the Series A Investors to be diluted by the shares issued upon
conversion of the notes or Safes in proportion to their ownership percentage"; "The
percentage-ownership method causes all of the dilution that results from the shares issued
upon conversion of the notes or Safes to be borne by the Founders". The User Guide's
footnote 1 describes the pre-money method as a negotiated exception to its own examples: "a
negotiated agreement ... that the pre-money valuation will not actually include safes or
notes converting in the round".

These are negotiated allocations of the same dilution, not three computations of which two
are wrong. `PricedRound.convention` has one value per method and no default.

**The legacy convention is the percentage-ownership method.** `solve_priced_round_with_safes`
places converting SAFEs inside the pre-money, which fixes new money at `N/W`: Cooley's
percentage-ownership method (`test_legacy_solver_is_the_percentage_ownership_method`, and
S1-S5 reproduced through the new engine).

**CM: Cooley's own example.** Assumptions from the article: pre-money $8M; new money $2M;
$1M of Safes at a 30% discount, no cap; 1,000,000 shares outstanding; no pool.

- **Pre-money method.** `P = $8M / 1M =` **$8.00**; conversion price $5.60; SAFE
  `1M/5.6 = 1.25M/7` (178,571.43); new `2M/8 = 250,000`; **T = 10M/7** (1,428,571.43).
  Founders 70%, SAFE 12.5%, new 17.5%. `P × T = $80M/7`, Cooley's "$11.43 million".
- **Percentage ownership.** `P × (1M + 1M/(0.7P)) = 8M` gives `P = 8 − 10/7 =` **$46/7**
  ($6.571429); conversion price $4.60; SAFE `5M/23` (217,391.30); new `7M/23` (304,347.83);
  **T = 35M/23** (1,521,739.13). Founders 23/35 (65.71%), SAFE 1/7, new exactly 20%.
- **Dollars invested.** `P × (1M + 1M/(0.7P)) = 9M` gives `P = 9 − 10/7 =` **$53/7**
  ($7.571429); conversion price $5.30; SAFE `10M/53` (188,679.25); new `14M/53`
  (264,150.94); **T = 77M/53** (1,452,830.19). Founders 53/77 (68.83%), SAFE 10/77, new 2/11.
  `P × T = $11M`, the fixed post-money.

Cooley prints $8.00 / $6.57 / $7.57; $5.60 / $4.60 / $5.30; 178,571 / 217,391 / 188,679;
250,000 / 304,348 / 264,151; and totals 1,428,571 / 1,521,739 / 1,452,830. All agree within
Cooley's rounding.

**CS: the same three methods on S1's capped SAFE.** 8,000,000 common; $1M post-money at
$10M; $3M at $12M pre. The cap binds in all three, so `B = 8M/0.9 = 80M/9` and the SAFE
takes **8M/9** shares regardless of the price.

- Pre-money: `P = 12M/8M =` **$1.50**; new 2M; **T = 98M/9**; founders 36/49 (73.47%), SAFE
  4/49 (8.16%), new 9/49 (18.37%).
- Percentage ownership: S1, `P =` **$1.35**, **T = 100M/9**, 72% / 8% / 20%.
- Dollars invested: `P = 13M / (80M/9) =` **$117/80** ($1.4625); new 80M/39; **T = 1280M/117**;
  founders 117/160 (73.125%), SAFE 13/160 (8.125%), new 3/16 (18.75%).

**The three answers to one round:**

| Convention | Price | Founders | SAFE | New money | Implied post-money |
|---|---|---|---|---|---|
| Cooley's example, pre-money | $8.00 | 70.00% | 12.50% | 17.50% | $11.43M |
| Cooley's example, percentage ownership | $6.57 | 65.71% | 14.29% | 20.00% | $10.00M |
| Cooley's example, dollars invested | $7.57 | 68.83% | 12.99% | 18.18% | $11.00M |
| S1 inputs, pre-money | $1.50 | 73.47% | 8.16% | 18.37% | $16.33M |
| S1 inputs, percentage ownership | $1.35 | 72.00% | 8.00% | 20.00% | $15.00M |
| S1 inputs, dollars invested | $1.4625 | 73.125% | 8.125% | 18.75% | $16.00M |

With a binding post-money cap the SAFE-to-founder ratio is the same 1 : 9 under all three
conventions (`test_a_cap_bound_safe_keeps_its_ratio_to_founders_under_every_convention`): the
convention moves value between the existing holders and the new money, not between the
founders and the capped SAFE. With a discount SAFE, it moves value between all three.

---

## Refused input

- A table holding a convertible note, preferred with a paid-in-kind cumulative dividend, or
  an instrument with no place in a round; a table with no outstanding shares.
- A `protection` mapping that misses a preferred position, names anything else, or holds
  anything but an `AntiDilutionProtection`; a protected position issued below its conversion
  price in the round; a protected position with a zero price.
- `mfn` given without an MFN Only Safe in the table, or missing with one; every
  `resolve_mfn` refusal listed under item 4.
- A round with no unique solution (`uniqueness_margin ≤ 1e-12`).
- A pool target below the existing unallocated reserve; a malformed `PoolChange`,
  `SeniorityPlacement` or `NewSeries`; non-positive pre-money or new money; an unknown
  convention.
- `SENIOR_TO_ALL` with no existing preferred or with a rank-0 series; `pari_passu_with` a
  position that is not preferred stock in the table.
- A new series or pool id that collides with the table or with each other.

## Not modelled

| Not modelled | Why it would change a real number |
|---|---|
| **Anti-dilution triggered by the round** | Refused (see above). A protected series issued below its price would gain conversion shares, which moves every percentage and may move the price. |
| **Promised options beyond the reserve** | The Company Capitalization exception pulls part of the pool increase into the SAFE denominator, lowering the Safe Price. |
| **Options at the treasury method** | Counting options net of strike proceeds shrinks every denominator, raising the SAFE's and founders' percentages. |
| **A pool target on the whole pool, or a pool outside the pre-money** | A target including grants needs a smaller increase; a post-money pool dilutes the new investor too, so it would not buy exactly `N/W`. |
| **Several purchasers in the new series; pro rata side letters** | Totals are unchanged at one price, but the User Guide's pro rata purchases change which holder owns what. |
| **Convertible notes converting in the round** | Refused. Their conversion needs accrued interest to a date and their own qualified-financing terms. |
| **MFN timing and scope** | The 10-day window, the notice, elections of non-SAFE Subsequent Convertible Securities, elections of an already-amended instrument, and MFN at a Liquidity Event are not modelled. A late election, or a note elected, changes what converts. |
| **The pre-money SAFE's own form** | Its text was not read; only its capitalization, from the User Guide. If it converts into a different series or at a different price, its shares and preference change. |
| **Post-money "Valuation Cap and Discount" form text** | Applied as the best-of rule the User Guide describes; its text was not read. |
| **Rounding** | The User Guide rounds the price to four decimals and share counts to whole shares; real closings round shares down and pay cash for fractions. Differences here are below 1e-4. |
| **Pay-to-play, shadow series, recapitalizations, class votes** | A round that converts or strips a non-participating holder's rights moves value between classes. |
| **Multiple closings** | A later closing at the same price adds shares; at a different price it is a different round. |
| **Dividends on the new series; dividend-bearing existing preferred converting** | The new series takes no dividend term. Existing forfeit-on-conversion and non-cumulative preferred is carried unchanged; paid-in-kind preferred is refused. |
| **A general mixed table whose balance has two roots** | Refused whenever `s∞ ≤ 0`; no such table was constructed, and none was proved impossible. |
| **Unconverted SAFEs at an exit** | The exit engine still refuses them; SAFE liquidity rights (Liquidity Capitalization) are not implemented. |

## What a fixture does not establish

A fixture asserts that the implementation reproduces a derivation written here, and, where
stated, that a published example agrees with it within that example's rounding. It does not
establish that a given financing used the convention stated, that a charter gives a series
the rank or protection the caller states, that an MFN holder made the election recorded, or
that the YC forms read are the versions a given company signed. The list above is the
companion to this document.
