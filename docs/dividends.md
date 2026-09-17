# Preferred dividends

Status 2026-09-15, engine `waterfall-v3` with dividend accrual. The terms live on
`PreferredStock.dividend` (`ovf.contracts.securities`), and `ovf.waterfall` settles them at an
exit. This document gives the model, the source for each convention (quoted where the
wording sets a number), the hand derivation of every expected number in
`tests/dividend_fixtures.py`, a proposition that reduces dividend-bearing tables to
dividend-free ones, the search that checks it, and what is not modelled.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty
on every dividend fixture. Each derivation below was done by hand. The exact-rational
oracle in `tests/test_dividends.py` reproduces every waterfall fixture without calling the
engine's allocation.

## What is implemented

| Term | Meaning | Effect at an exit on `as_of` |
|---|---|---|
| `dividend=None` (default) | no dividend right | exactly the pre-dividend engine, byte for byte |
| `NonCumulativeDividend(annual_rate)` | payable only if declared | accrues nothing; the preference is unchanged |
| `CumulativeDividend(..., settlement="forfeit_on_conversion")` | NVCA accruing dividend | preference = multiple × invested + accrued; forfeited on conversion |
| `CumulativeDividend(..., settlement="paid_in_kind")` | accrued amount paid in shares of the series | the position holds `shares × (1 + d)` on both branches |

`CumulativeDividend` terms: `annual_rate` (on the Original Issue Price), `accrual`
(`"simple"` or `"compound"`), `compounding_frequency` (compound only), `day_count`
(`"actual/365_fixed"` or `"actual/360"`), `accrues_from` (a date), `settlement`, and
`participation_cap_basis`. Every one of these is required except the last. Constructors are
`cumulative_dividend(...)`, `non_cumulative_dividend(rate)` and `preferred(...,
dividend=...)`.

Every exit on a table holding a dividend writes one `DividendAccrual` into
`WaterfallResult.dividend_accruals` for each position that carries a dividend term. It records the days, year fraction, periods, accrued
amount per share and per position, any paid-in-kind shares, the preference claimed, the
total cap, the units, the cap basis applied and whether it was stated, and a one-line
formula.

## Sources

### Verified against the text

- **NVCA Model Certificate of Incorporation**, October 2025
  ([.docx](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx)), read
  in full for this work. The June 2019 version
  ([.docx](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Document-Certificate-of-Incorporation.docx))
  was checked for the same clauses and matches in substance.
  - **Section numbers** come from the document's automatic list numbering, resolved
    through its paragraph styles: §1 Dividends, §2.1 Preferential Payments, §4.1.1 Conversion
    Ratio, §4.3.1 Notice of Conversion, §4.3.3 Effect of Conversion, §4.3.4 No Further
    Adjustment, §5.2 Procedural Requirements.
  - **Footnote numbers** are the numbers Word displays, which is reference order. The
    document sets no per-section restart. In the file's XML each footnote's id is one
    higher than its displayed number.
- **Filed charters that follow the model**, read on SEC EDGAR:
  - [Sage Therapeutics, S-1/A 2014, Ex. 3.1](https://www.sec.gov/Archives/edgar/data/1597553/000119312514262688/d697091dex31.htm)
  - [Global Blood Therapeutics, S-1/A 2015, Ex. 3.6](https://www.sec.gov/Archives/edgar/data/1629137/000119312515271753/d885656dex36.htm)
  - [Virtual Piggy, 8-K 2014, Ex. 3.1](https://www.sec.gov/Archives/edgar/data/1437283/000121465914007299/ex3_1.htm)
- **Filed charters that deviate:**
  - [Spark Therapeutics, S-1 2014, Ex. 3.1](https://www.sec.gov/Archives/edgar/data/1609351/000119312514457223/d776249dex31.htm)
    pays accruing dividends in kind.
  - [Mirna Therapeutics, S-1 2015, Ex. 3.1](https://www.sec.gov/Archives/edgar/data/1527599/000104746915006962/a2225772zex-3_1.htm)
    pays them in common at the IPO price, and only at an IPO.

Five charters are a sample of drafting, not a market survey. No frequency is claimed for
any convention below.

### Not verified

- **Sub-annual compounding split.** NVCA fn 13 says to specify "whether this 'compounding'
  of the original purchase price is done on an annual, quarterly, or other basis". It does
  not say whether a quarterly period accrues `r/4`. **UNVERIFIED:** the engine uses `r/m` per
  period, the nominal-rate convention already used in [debt](debt.md) (Hull, ch. 4). Annual
  compounding, the fn 13 example and the one used in the fixtures, does not depend on this.
- **Paid in kind with a multiple above 1x.** Spark's series are 1x. Spark's text gives the
  paid-in-kind shares "the same consideration" as the other shares of the series, so they
  take `multiple × Original Issue Price` each. **UNVERIFIED** for a multiple other than 1: no
  such charter was read.
- **Day count.** The charter says only that Accruing Dividends "accrue from day to day". The
  year basis is therefore a required term. The names Actual/365 Fixed and Actual/360 come
  from the same secondary source for ISDA 2006 §4.16 as in [debt](debt.md).

## The four questions, answered from the text

### 1. Does conversion forfeit accrued dividends?

**Under the model charter, yes.** NVCA §4.3.3 (Effect of Conversion), verbatim:

> "All shares of Preferred Stock which shall have been surrendered for conversion as
> herein provided shall no longer be deemed to be outstanding and all rights with respect
> to such shares shall immediately cease and terminate at the Conversion Time, except only
> the right of the holders thereof to receive shares of Common Stock in exchange therefor
> and to receive payment of any dividends declared but unpaid thereon."

NVCA fn 46, on the §4.1.1 conversion ratio (Original Issue Price divided by Conversion
Price): "The effect of using the Original Issue Price is that accruing dividends are not
taken into account in a conversion." §4.3.1(ii) and §5.2(b) pay only "declared but unpaid
dividends" on conversion. The operative text has **no bracketed alternative**. The
only alternative is fn 50:

> "Some investors will insist that, upon conversion, all declared but unpaid dividends
> (and, if the Preferred Stock is entitled to accruing dividends, all accrued dividends,
> whether or not declared) be paid in additional shares of Common Stock rather than in
> cash."

It states no price for those shares, so it is not implemented (see Not modelled).

**Filed charters.** Sage (§4.3.3), Global Blood (§4.3.3) and Virtual Piggy (§6.3.3) use the
model's forfeiting wording. Spark §4.3.3 keeps "any undeclared Series B Accruing Dividends".
Its §1.1 says how they are paid, at a liquidation and at a conversion:

> "Any Series B Accruing Dividends due and payable pursuant to Subsection 2.1, and
> Sections 4 and 5 as described above shall be paid by the issuance of shares of Series B
> Preferred Stock determined by dividing the aggregate amount of the Series B Accruing
> Dividends by the Series B Original Issue Price (with the value of any fractional share
> paid in cash)".

Its §2.1 then gives those shares "the same consideration ... as holders of shares of
Series B Preferred Stock otherwise issued and outstanding".

**Decision.** Both structures are sourced and the charter decides between them, so
`settlement` is required and has no default. The coordinator confirmed this reading on
2026-09-15. A cash payment of accrued dividends on conversion was not found in any document
read, so no such value exists, and `settlement="retain_as_cash"` is rejected.

**`paid_in_kind` is a different position, not a conversion flag.** Let `d = accrued /
invested`. The accrued amount becomes `accrued / OIP = shares × d` new shares of the same
series, so the position holds `shares × (1 + d)` shares. Everything the engine reads scales
with that one number:

- the preference, `shares(1 + d) × OIP × m`;
- the units that participate or convert, `shares(1 + d) × ratio`;
- a per-share participation cap, `shares(1 + d) × OIP × c`.

The engine computes this once, as `PreferredStock._paid_in_kind_position`, and then uses
the ordinary no-dividend terms of the enlarged position. The added units dilute common and
every other residual holder exactly as issued shares would.

### 2. Simple or compounding, and on what base?

The operative text (§1, third alternative) is simple:

> "dividends at the rate per annum of $[___] per share shall accrue on such shares of
> Preferred Stock ... Accruing Dividends shall accrue from day to day, whether or not
> declared, and shall be cumulative".

Fn 13: "A cumulative dividend expressed as '$____ per share' will by definition be
non-compounding." Its compounding example:

> "dividends at the rate per annum of [8]% of the Original Issue Price (as defined below)
> of such share, plus the amount of previously accrued dividends, compounded annually,
> shall accrue on each share then outstanding".

So the base is the Original Issue Price, and `annual_rate` is stated on it ($[___] per share
= `annual_rate × OIP`). `accrual` is required, as it is for debt:

- simple: `accrued = invested × r × days / D`;
- compound: `n = m × days / D` whole periods, `accrued = invested × ((1 + r/m)ⁿ − 1)`.

A partial compounding period is refused, as for debt. Spark accrues "8% of the sum of (i)
the Series B Original Issue Price ... and (ii) the accrued and unpaid dividends" from day to
day, with no stated frequency. That is expressible here only by stating one.

### 3. Does the accrued amount count inside the participation cap?

**Inside, under the model charter.** NVCA fn 20 adds the cap to the participating §2.1 or
§2.2:

> "if the aggregate amount which the holders of Preferred Stock are entitled to receive
> under Sections 2.1 and 2.2 shall exceed [$_______] per share ... (the 'Maximum
> Participation Amount'), each holder of Preferred Stock shall be entitled to receive ...
> the greater of (i) the Maximum Participation Amount and (ii) the amount such holder would
> have received if all shares of Preferred Stock had been converted into Common Stock".

With accruing dividends, the §2.1 amount is "the Original Issue Price, plus any Accruing
Dividends accrued but unpaid thereon, whether or not declared, together with any other
dividends declared but unpaid thereon" (fn 17 for non-participating and fn 19 for
participating preferred). The cap therefore bounds preference, dividends and participation
together. Sage, Global Blood and Spark are drafted this way, each with a fixed dollar cap per
share.

**Outside, in one filed charter.** Virtual Piggy §4.2 sets the cap at "two-and-a-half times
(2.5x) the Series B Original Issue Price, plus any Accruing Dividends accrued but unpaid
thereon, whether or not declared". The accrued amount sits on top of the multiple.

**A drafting note.** The model states the cap as "[$___] per share", a fixed amount, not as
"X times the Original Issue Price". ovf's `participation_cap` is a multiple of invested
capital. The two are the same number when the dollar amount is `c × OIP`.

**Implemented.** `participation_cap_basis` is consulted only when a participating position
has a cap and a `forfeit_on_conversion` dividend. Everywhere else it is refused if set.

- `None` applies the NVCA reading, `"includes_dividends"`. The total cap is `c × invested`,
  and the preference claim is `min(m × invested + accrued, c × invested)`. The clamp follows
  fn 20: once the §2.1 amount exceeds the cap, the holder receives the greater of the cap and
  its as-converted amount. Conversion is the engine's other branch, so the non-converting
  claim stops at the cap.
- `"excludes_dividends"` gives a total cap of `c × invested + accrued`.

Whenever the basis is consulted, `WaterfallResult.assumptions` names the value used and
whether it was stated or the default. For example: `series_a: the participation cap includes
accrued dividends (default; NVCA Model COI fn 20).` Under `paid_in_kind` the basis does not
apply, because each new share carries the per-share cap like any other share.

### 4. Declared-but-unpaid, accrued-but-undeclared, and non-cumulative dividends

- **Accrued but undeclared** is what `CumulativeDividend` models. It is in the preference
  under both settlements. Under `forfeit_on_conversion` it is lost on conversion; under
  `paid_in_kind` it is kept, as shares.
- **Declared but unpaid** is not modelled. The model charter adds it to the §2.1 amount
  and also preserves it through conversion (§4.3.3; §4.3.1(ii) "pay all declared but unpaid
  dividends on the shares of Preferred Stock converted"). It is therefore owed on both
  branches, and behaves like a liability rather than part of the conversion choice. Every
  result carrying a dividend says so in its assumptions. See Not modelled for what that
  omits.
- **Non-cumulative dividends are accepted and ignored explicitly.** §1, second alternative:
  "The right to receive dividends on shares of Preferred Stock ... shall not be cumulative,
  and no right to dividends shall accrue to holders of Preferred Stock by reason of the fact
  that dividends on such shares are not declared or paid." A `NonCumulativeDividend` accrues
  zero on every date. It needs no `as_of`, never reads one, and is named in the result's
  assumptions. It is never treated as cumulative, because it is a different class with no
  accrual fields.

## The time basis

- The same `as_of` that `solve_waterfall` and `enumerate_equilibria` take for debt is the
  accrual date. There is no second date concept.
- A table holding a cumulative dividend and no `as_of` raises, even at a zero exit:
  `Cumulative preferred dividends accrue with time, so an exit holding them needs an explicit
  as_of date (series_a). No implicit clock is used`.
- `as_of` must be a `datetime.date`, not a `datetime`, and not before `accrues_from`. There
  is no upper bound: an accruing dividend has no maturity.
- No code path reads a clock. `test_no_clock_is_read` scans `securities.py` and
  `waterfall.py`.
- With a cumulative dividend present, `as_of` goes into the input fingerprint, the
  assumptions and `WaterfallResult.as_of`. With no cumulative dividend it is not read, and
  the result is unchanged by passing one.

## How a position enters the allocation

The engine reads three numbers from each preferred position:

- `P`, the preference claimed when not converting. `P` is also the pro-rata weight in a
  short tier.
- `K`, the total cap while participating, or none.
- `u`, the common-equivalent units used when converting or participating.

These come from `PreferredStock.exit_terms(as_of)`. Let `I = shares × OIP` be invested
capital, `A` the accrued amount, `m` the multiple, `c` the cap multiple and `r` the ratio.

| Term | P | K | u |
|---|---|---|---|
| none or non-cumulative | `I m` | `I c` | `shares × r` |
| forfeit, no cap | `I m + A` | none | `shares × r` |
| forfeit, cap includes dividends | `min(I m + A, I c)` | `I c` | `shares × r` |
| forfeit, cap excludes dividends | `I m + A` | `I c + A` | `shares × r` |
| paid in kind | `I(1 + d) m` | `I(1 + d) c` | `shares(1 + d) × r` |

Under forfeit, `u` carries no dividend. The conversion branch pays the as-converted value
alone, which is §4.3.3.

## Proposition 1: a dividend-bearing table is a dividend-free table

**Statement.** Fix `as_of`. For each preferred position with a cumulative dividend, let
`A ≥ 0` be its accrued amount and `d = A / I` (with `I > 0`, which the model enforces).
Build a twin position with no dividend:

| Settlement and cap | Twin |
|---|---|
| forfeit, no cap | multiple `m + d` |
| forfeit, cap includes dividends | multiple `min(m + d, c)`, cap `c` |
| forfeit, cap excludes dividends | multiple `m + d`, cap `c + d` |
| paid in kind | shares `shares × (1 + d)` |

Keep every other position and every other term. Then in **every** conversion profile, every
position, including common, receives the same amount in the dividend table as in the twin
table. The two tables are the same game: they have the same equilibria, the same feasible
profiles and the same equilibrium payoff vectors.

**Proof.** The allocation for a fixed profile depends on each preferred position only
through `(P, K, u)`, its seniority, its participation flag, whether it holds shares and
whether it has a cap. The twin keeps the last four. It remains to show that `(P, K, u)` agree:

- **forfeit, no cap:** `P = I m + A = I(m + d) = P'`. `u = shares × r = u'`.
- **cap includes dividends:** `P = min(I m + A, I c) = I min(m + d, c) = P'` because `I > 0`.
  `K = I c = K'`. `u` as above.
- **cap excludes dividends:** `P = I(m + d) = P'`. `K = I c + A = I(c + d) = K'`. `u` as above.
- **paid in kind:** with `s' = shares + A/OIP = shares(1 + d)`: `P = s' OIP m`, `K = s' OIP c`
  and `u = s' r`. These are the no-dividend terms of a position holding `s'` shares.

Every twin is a legal no-dividend position. The model requires `cap ≥ multiple`, and it
holds: `min(m + d, c) ≤ c`, and `c + d ≥ m + d` because `c ≥ m`. Payoffs agree profile by
profile, so the equilibrium sets agree. ∎

**Both branches.** The coordinator asked for the conversion branch to be checked, because
that is where the reduction could fail.

- **Forfeit.** A converting position holds `shares × r` units and no preference, in both
  tables. The twin's higher multiple is read only when it does not convert. So the preference
  branch pays `I(m + d)` and the conversion branch pays as-converted value with no dividend
  component, in both tables. The whole game is identical, not just the payouts at one
  profile.
- **Paid in kind.** The residual denominator is the sum of active units. In both tables it
  includes `shares(1 + d) × r` for this position whenever it converts or participates, and
  the unallocated pool contributes nothing. This is the denominator intended: the
  paid-in-kind shares are issued shares. One reporting difference is outside the game.
  `CapTable.fully_diluted_shares` has no date, so it does not count paid-in-kind shares on
  the dividend table but does on the twin. Payouts are unaffected.

**Tests.**

- `test_reduction_holds_on_every_profile_on_both_branches` builds the twin from the table
  above for 150 generated tables. At each of several exits it compares every position's
  payout in all `2**n` profiles, then compares the two equilibrium surveys.
- `test_exact_reduction_and_payoff_uniqueness_sweep` repeats the comparison in exact rational
  arithmetic, where it is equality rather than tolerance. It also compares the engine with the
  independent oracle in every profile.
- The adversarial search below checked the same equality exactly on every instance.

**What it implies.** Payoff uniqueness with dividends is not a new question. A
dividend-bearing counterexample would be a dividend-free counterexample: a table with
multiple `m + d`, a cap equal to its multiple (the clamp), a cap of `c + d`, or a fractional
share count. All of those lie inside the scope that [findings](findings.md) already
examines. What changes is the parameter range: `d` grows without bound with time and rate,
so the twins reach multiples far above the small ranges the earlier search drew from.

**What it does not imply.** It is a proof about this model at one `as_of`, not about a
charter. It does not make payoff uniqueness a theorem. The earlier result is empirical, so
the dividend result inherits exactly that status, over the transformed range. It says
nothing about declared dividends, fn 50's payment in common, a retain-as-cash variant or
anything else not modelled.

## Payoff uniqueness with dividends: the search

Proposition 1 is the primary evidence. The search checks it, and extends the empirical
record into the parameter range the reduction produces. If the search had disagreed with the
proposition, the proposition would have been wrong.

**Method.** Recorded 2026-09-15. Tables were generated at random and made adversarial:

- 2–4 preferred positions for the exact search, 3–7 for the solver search;
- zero-common tables and identical classes, seniority collisions, and an unallocated pool;
- multiples 0.5–5 and caps equal to the multiple, so the clamp binds;
- rates 4–100%, elapsed time from 0 to 40 years, and both day counts;
- simple accrual, and compound accrual at 1, 2, 4 or 12 periods a year;
- both settlements and both cap bases.

Exits were placed exactly on candidate breakpoints for every conversion profile, and
$0.001 either side. The breakpoints were cumulative preference levels, conversion
indifference points and cap-exhaustion points, all computed in exact arithmetic.

Each instance was solved twice in exact rational arithmetic, by the oracle in
`tests/test_dividends.py`: once from the charter terms and once from the Proposition 1 twin.
Every instance was then run through the production float engine: `enumerate_equilibria` and
`solve_waterfall`.

| Search | Instances | Multiple equilibrium profiles | Distinct equilibrium payoff vectors |
|---|---|---|---|
| Exact rational, 2–4 positions, 37,040 tables | 878,746 | 217,685 | **0** |
| Charter terms vs Proposition 1 twin, exact, every profile | 878,746 | — | **0 mismatches** |
| Same instances, production float engine | 878,746 | — | 343 flagged, all explained below |
| Float solver search, 3–7 positions | 342,580 | — | 6 flagged, all explained below |

In both searches, every instance had at least one feasible equilibrium, and
`solve_waterfall` returned on all 878,746 and 342,580 instances. It needed at most
**3** sweeps, and there were no cycles and no exhausted budgets. The generated positions
included 94,785 carrying a dividend, 8,146 of them clamped at the cap.

**The float flags are the tolerance, not the dividends.** The flagged cases were classified
against the exact oracle:

- 388 found by regenerating the exact-search instance stream, a superset of the original
  343;
- the 33 float-vs-exact payoff mismatches and the 1 solver-vs-exact mismatch;
- the 6 from the solver search.

All 428 have the same explanation. The float engine accepts a profile that exact arithmetic
rejects. That profile strands no cash, and its best unilateral deviation gains a strictly
positive amount no larger than the reported tolerance (`1e-8 + 1e-12 × net_exit`). It is an
ε-equilibrium admitted by the tolerance. Its payoffs differ from the unique exact vector by at
most **2.93 times the tolerance**.

**In all 428 cases the dividend-free twin table shows the identical flag.** This is a
property of the engine's tolerance-based equilibrium test that already existed without
dividends, not something dividends introduce. [findings](findings.md) records five such float
cases, found near ties. They are more frequent here because exits were placed deliberately at
breakpoints ± $0.001, including tables whose whole exit is $0.001, where the tolerance is
comparable to the amounts at stake.

**What this supports.** Every instance with a feasible equilibrium had one equilibrium payoff
vector in exact arithmetic. This held into the ranges the twins reach: multiples far above 3,
caps equal to the multiple, fractional share counts. Proposition 1 held exactly on every
profile of every instance. Neither result is a proof of payoff uniqueness. The claim is the
same kind as in [findings](findings.md), over a wider range. The float engine can report a
second payoff vector that differs by no more than about three tolerances. That tolerance
caveat already applied without dividends.

## Fixture derivations

**Shared time basis.** Dividends accrue from **2025-01-01**. The measurement date is
**2027-01-01**: 365 + 365 = **730 days**, and 730/365 = **2.0 years** under Actual/365 Fixed.
The long horizon runs to **2039-12-29**. 2025-01-01 to 2040-01-01 is 15 × 365 + 3 = 5,478
days, because 2028, 2032 and 2036 each contain 29 February. Three days earlier gives
**5,475 = 15 × 365 days**, so 5,475/365 = 15.0 years.

**Shared equity**, as in [fixtures](fixtures.md):

- Founders hold 8,000,000 common.
- Series A holds 2,000,000 preferred at an Original Issue Price of **$2.50**: $5,000,000
  invested, 1x, converting 1:1. That is 20% as converted.
- Series B, where used, holds 1,500,000 at $6.00 ($9,000,000), 1x, with no dividend, in the
  same tier as Series A.

The dividend is **8% of the Original Issue Price**: $0.20 per share, or **$400,000 a year**
for Series A.

### Accrual

**DV1: simple, two years.** $0.20 × 730/365 = **$0.40 a share**. × 2,000,000 =
**$800,000**. The preference is $5,000,000 + $800,000 = **$5,800,000**.

**DV2: compounded annually, same term.** n = 1 × 730/365 = 2 periods. 1.08² = 1.1664, so
the accrual is 5,000,000 × 0.1664 = **$832,000** ($2.50 × 0.1664 = **$0.416 a share**). The
preference is **$5,832,000**. Compounding exceeds simple by $32,000, which is 8% of the first
year's $400,000.

**DV3: simple, Actual/360, same dates.** $400,000 × 730/360 = 292,000,000/360 =
**$811,111.11…** ($0.20 × 730/360 = $0.405556 a share). The day count alone adds $11,111.11.

**DV4: non-cumulative.** Nothing accrues. The preference stays **$5,000,000**.

**DV5: simple, fifteen years.** $0.20 × 15 = **$3.00 a share**, **$6,000,000** accrued, and
a preference of **$11,000,000**.

**DV6: paid in kind, two years.** The DV1 accrual of $800,000 becomes 800,000 / 2.50 =
**320,000 shares**, so Series A holds 2,320,000 = 2,000,000 × 1.16 shares (d = 0.16). The
preference is 2,320,000 × $2.50 = **$5,800,000**, the same as DV1. Conversion units are
**2,320,000**, not 2,000,000.

### Exit waterfalls (as of 2027-01-01 unless stated)

**DW1: accrued dividends change who converts.** Exit $27M.

- With the DV1 dividend: converting pays 20% × $27M = $5.4M, below the **$5.8M**
  preference, so Series A holds. Founders take $27M − $5.8M = **$21.2M**.
- **DW1-none**, no dividend: $5.4M beats $5M, so Series A converts (**$5.4M**) and founders
  take **$21.6M**.

The dividend reverses the decision.

**DW2: cap includes the dividend (default).** Participating, 2x cap, DV1 dividend, exit
$40M. The preference is $5.8M, and participation adds 20% × ($40M − $5.8M) = $6.84M. The
uncapped total, $12.64M, exceeds the cap of 2 × $5M = $10M. Series A receives **$10M** and
founders **$30M**. Converting would pay 20% × $40M = $8M.

**DW3: cap excludes the dividend.** The same position with `"excludes_dividends"`: the cap
is $10M + $0.8M = $10.8M. $12.64M exceeds it, so Series A receives **$10.8M** and founders
**$29.2M**. Converting pays $8M.

**DW4: paid in kind with a per-share cap.** DV6 shares, participating, 2x cap, exit $40M.
- The preference is $5.8M.
- The residual of $34.2M is shared over 8,000,000 + 2,320,000 = 10,320,000 units, so Series
  A's share is 2.32/10.32 = 29/129. Participation is $34.2M × 29/129 = $7,688,372.09, and the
  uncapped total is $13,488,372.09.
- The cap is 2 × 2,320,000 × $2.50 = $11.6M, so Series A receives **$11.6M** and founders
  **$28.4M**.
- Converting would pay $40M × 29/129 = $8,992,248.06.

At one exit and one table, the three readings pay **$10M, $10.8M and $11.6M**.

**DW5: the clamp (inside).** Participating, 2x cap, DV5's fifteen-year accrual, exit $40M.
The $11M preference exceeds the $10M cap, so the claim is **$10M** with no headroom left.
Converting pays $8M, so Series A receives **$10M** and founders **$30M**. This is F5a
exactly: $6M of accrued dividends adds nothing once the preference reaches the cap.

**DW6: the same case outside.** The cap is $10M + $6M = $16M. $11M + 20% × ($40M − $11M) =
$11M + $5.8M = $16.8M exceeds it. Series A receives **$16M** and founders **$24M**.
Converting pays $8M.

**DW7: short of preference plus dividends, one tier.** Series A (DV1 dividend) and Series B
share a tier. The claims are $5.8M and $9M, $14.8M in total. The exit of $7.4M is exactly
half, so Series A receives **$2.9M**, Series B **$4.5M** and founders **$0**. Checking
conversions:

- A converts: B takes all $7.4M (claim $9M), and A receives $0.
- B converts: A takes $5.8M, and B receives 1.5/9.5 × $1.6M = $252,631.58.

Both are worse, and no other profile is stable.

**DW7-none**, no dividend: the claims split 5:9, giving A $7.4M × 5/14 = **$2,642,857.14**
and B $7.4M × 9/14 = **$4,757,142.86**. The dividend moves $257,142.86 from B to A.

**DW8: non-cumulative.** Exit $15M, no `as_of`. This is F2: Series A holds its **$5M**
preference (20% × $15M = $3M), and founders take **$10M**.

**DW9: paid in kind, participating, uncapped.** Exit $31.6M.
- The preference is $5.8M. The $25.8M residual over 10,320,000 units is **$2.50 a unit**.
  Series A receives $5.8M + 2,320,000 × $2.50 = **$11.6M**, and founders 8,000,000 × $2.50 =
  **$20M**.
- Converting would pay $31.6M × 29/129 = $7,103,875.97.
- **DW9-forfeit**, the same exit with the dividend in the preference: $5.8M + 20% × $25.8M =
  **$10.96M**, and founders **$20.64M**. Converting would pay $6.32M.

**DW10: paid in kind, converting.** Exit $30.96M. As converted, $30.96M / 10,320,000 units =
**$3.00 a unit**. Series A receives 2,320,000 × $3 = **$6.96M**, above its $5.8M preference,
and founders receive **$24M**. The added shares dilute founders: with forfeit, converting at
this exit would leave them $24.768M.

**DW11: debt and a dividend on one `as_of`.** Exit $28.16M. The loan
($1,000,000 at 8% simple, [debt](debt.md) A1) takes **$1.16M**. The $27M residual is DW1:
Series A **$5.8M**, founders **$21.2M**.

### The conversion flip point

At the flip, Series A's preference equals its as-converted value, and both profiles are
equilibria paying the same. $10 either side, the decision flips. The minimum difference is
$2 at 20% (FL0–FL2) and $2.25 at 29/129 (FL3), far above the tolerance of about $3 × 10⁻⁵.

| Case | Dividend | Flip condition | Flip exit | At the flip |
|---|---|---|---|---|
| FL0 (F3) | none | 0.2 X = $5M | **$25,000,000** | A $5M, founders $20M |
| FL1 | simple, forfeit | 0.2 X = $5.8M | **$29,000,000** | A $5.8M, founders $23.2M |
| FL2 | compound, forfeit | 0.2 X = $5.832M | **$29,160,000** | A $5.832M, founders $23.328M |
| FL3 | simple, paid in kind | (29/129) X = $5.8M | **$25,800,000** | A $5.8M, founders $20M |

- The forfeit dividend moves the flip up by $0.8M / 0.2 = **$4M**.
- Paid in kind moves it only $0.8M. The flip is where each residual unit is worth the
  Original Issue Price, X = $2.50 × 10,320,000. Adding shares raises both the preference and
  the share of the residual.

## Regression evidence

A position with `dividend=None` takes the same computation as before this change.

- **Snapshot comparison.** Before either engine file was edited, 5,940 results were
  captured and compared afterwards as JSON. They covered:
  - every F-fixture at 15 exits, with and without an unused `as_of`, with transaction costs
    and through `CapTable`, plus every conversion profile of `evaluate_fixed_waterfall` at
    a $33M exit;
  - every equilibrium survey, the OCF export of each fixture and every debt fixture at four
    exits;
  - the slow game at 58 exits;
  - 400 random tables at 6 exits each, with surveys;
  - the `model_dump` of every fixture security, and 12 recorded error messages.

  Every pre-existing field was **byte-identical**, including `input_hash`, `assumptions`,
  `iterations`, `max_unilateral_gain` and `conservation_error`. The one new result field,
  `dividend_accruals`, was `[]` in all of them.
- **`model_dump`.** `PreferredStock` leaves `dividend` out of its dump when it is `None`, so
  the dump, and the fingerprint built from it, are the pre-dividend ones.
  `test_no_dividend_results_are_unchanged` recomputes each F-fixture's hash from the
  pre-dividend payload definition and checks the field set and assumptions.
- **Unchanged tests.** The existing F-fixture, debt, stress and reference tests were not
  edited.

## Not modelled

Each item below would change a real number.

| Not modelled | Why it matters |
|---|---|
| **Declared-but-unpaid dividends** | The model charter adds them to the §2.1 amount and preserves them through conversion. In a solvent exit they behave like a liability. In a shortfall they compete within the preference tier on one branch and are a separate claim on the other. Settle them outside and net them off. |
| **Dividends already paid** | The claim assumes nothing paid since `accrues_from`. A simple dividend can be restated with a later `accrues_from`; a compounding one cannot be restated that way exactly. |
| **Payment in common on conversion (NVCA fn 50)** | Its share price is not stated. Mirna prices such shares at the IPO price, and only at an IPO. A price basis would change the conversion branch. |
| **Accrued dividends kept as cash on conversion** | No document read does this. It would make conversion strictly more attractive, and it is the one variant not reducible by Proposition 1. |
| **Fractional paid-in-kind shares** | Spark pays "the value of any fractional share ... in cash". Here fractions are shares, which moves less than one share's value per holder. |
| **Sub-annual compounding split and stub periods** | `r/m` per period is UNVERIFIED for dividends. Partial periods are refused. |
| **Dividend priority between series** | NVCA fn 12, on the second dividend alternative: "For simplicity, this model charter provides for pari passu dividends. If one series of Preferred Stock has a senior liquidation preference, this dividend language may need to be revised." Here the accrued amount ranks with its own position's preference tier and has no separate dividend priority. |
| **Accrual caps and end dates** | Some charters stop accrual after a period or a date (Mirna's "Accrual End Date"). Here accrual runs to `as_of`. |
| **Redemption** (§6) | NVCA fn 77, on the §6.1 redemption price, gives the wording with accruing dividends: "the Original Issue Price per share, plus any Accruing Dividends accrued but unpaid thereon". No redemption is modelled. |
| **Recapitalisation adjustments** | The rate and Original Issue Price adjust for splits and stock dividends. Restate them in a new snapshot. |
| **Dividends shared with common** (§1 first alternative, and the second sentence of each alternative) | These matter only when a dividend is declared. |
| **Tax** | NVCA fn 50 flags IRC §305 treatment of dividends paid in stock. All amounts are pre-tax. |
| **Ownership reporting of paid-in-kind shares** | `CapTable.fully_diluted_shares` and `ownership_breakdown()` take no date, so they exclude paid-in-kind shares. Exit payouts include them. |
| **OCF** | OCF v1.2.0 has no dividend fields ([ocf](ocf.md), finding 6). On 2026-09-15 `ovf.ocf.to_ocf` wrote a dividend-bearing class **without its dividend**, and reading it back gave `dividend=None`. That module is outside this change. Until the writer refuses such a class, do not export one. |
| **CLI** | `python -m ovf waterfall --file` accepts a `dividend` object but has no `--as-of`, so a cumulative dividend raises the `as_of` error. |
| **Exit-triggered anti-dilution, coordinated holders, class votes** | Inherited from the engine; see [limitations](limitations.md). |

## What a fixture does not establish

A fixture shows that the implementation reproduces a derivation stated here. It does not
establish that a given charter uses these terms, or that its rate, base, day count,
compounding, settlement or cap basis matches the one chosen. It also does not establish
that the list above is complete. Proposition 1 is exact within the model. It is not
evidence about any charter's wording.
