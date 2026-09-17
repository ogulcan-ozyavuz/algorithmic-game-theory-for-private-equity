# Debt at exit

Status 2026-09-15, engine `waterfall-v3` with debt settlement. This document states the
debt model, the source for each convention, the hand derivation of every expected
number in `tests/debt_fixtures.py`, and what is not modelled.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is
empty on every debt fixture. Each derivation below was checked by hand; exact figures
(1.02⁸, 1.04⁴) were expanded as integer powers, not taken from the engine.

## What is implemented

| Instrument | Terms | Exit claim |
|---|---|---|
| `DebtInstrument` (`ovf.instruments.debt`) | principal, annual rate, accrual method, compounding frequency, day count, issue date, optional maturity, debt seniority | outstanding principal + accrued interest |
| `VentureDebt` | the above plus a stated `exit_fee` amount | outstanding principal + accrued interest + exit fee |
| `ConvertibleNote` | the above plus valuation cap, discount, qualified-financing threshold, required maturity, caller-stated exit treatment | `repay`: outstanding principal + interest; `multiple`: m × original principal + interest |

Debt holds zero shares. `CapTable.fully_diluted_shares` and `ownership_breakdown()`
count it as zero (a lender appears with 0%) until it converts. Conversion returns a
share count and price; the caller builds the resulting equity security and places it
in a new snapshot, as for any other immutable security.

## The time basis

Interest depends on elapsed time, so every claim is a function of an explicit date.

- Each instrument carries its `issue_date` and a required `day_count`. Neither has a
  default.
- `solve_waterfall(..., as_of=date)` and `enumerate_equilibria(..., as_of=date)` take the
  exit date. If the table holds any debt and `as_of` is missing, the call raises. This
  happens even at a zero exit.
- No code path reads a clock. `tests/test_debt.py` scans both modules for clock calls.
- `as_of` must be a `datetime.date`. A `datetime` is refused because time of day is not
  modelled. An `as_of` before `issue_date` or after `maturity_date` is also refused.
- `as_of` is written into the result (`WaterfallResult.as_of`), into its assumptions and
  into the input fingerprint. The same inputs and the same `as_of` give the same hash.
  A different `as_of` gives a different one.
- For a table with no debt, `as_of` is not read. The result, including its fingerprint,
  is exactly what it was before debt existed.

**Year fraction.** `days = (as_of − issue_date).days` in actual calendar days.
Actual/365 Fixed divides by 365, and Actual/360 divides by 360. These names and formulas
are the ones given for ISDA 2006 Definitions §4.16(d) and (e) in a secondary source
([Wikipedia, "Day count convention"](https://en.wikipedia.org/wiki/Day_count_convention)).
The ISDA text itself was not consulted. Published note forms state their basis: the
[Fenwick seed-stage note](https://assets.fenwick.com/legacy/FenwickDocuments/Convertible-Note-Seed-Stage-Startup.pdf)
computes interest "based on the actual number of days elapsed and on a year of three
hundred sixty-five (365) days". This is why the day count is a required parameter
rather than a default.

**Accrual.** Let `P` be principal, `r` the nominal annual rate, `m` the periods per year
and `D` the day-count denominator.

- Simple: `interest = P × r × days / D`. The
  [D3 note template](https://www.third-derivative.org/hubfs/D3%20Convertible%20Note%20Template.pdf)
  says "a simple rate of 8% per annum".
- Compound: `n = m × days / D` whole periods, `interest = P × ((1 + r/m)ⁿ − 1)`, and
  principal is unchanged. This follows the textbook definition of a rate compounded
  `m` times per year: Hull, *Options, Futures, and Other Derivatives*, ch. 4, gives
  `A(1 + R/m)^(mn)`. The edition and page were not re-checked in this session.
- PIK: the same growth, but interest is capitalised into principal at each period end.
  Accrued cash interest is therefore zero at a period end, and the claim is the grown
  principal. Barings BDC's
  [10-K for FY2021](https://www.sec.gov/Archives/edgar/data/1379785/000137978522000008/a202110-k.htm)
  describes PIK interest as "periodically added to the principal balance of the loan,
  rather than being paid to the Company in cash".
- **Partial periods are refused.** When `m × days` is not a multiple of `D`, compound
  and PIK accrual raise an error. Interest over a stub period can be simple on the
  compounded balance, a fractional exponent, or calendar-anniversary compounding.
  These give different numbers, and the choice is contract-specific. Under Actual/365
  Fixed, integer days and `m ∈ {1, 2, 4, 12}` make this whole 365-day years only. Under
  Actual/360 the unit is `360/m` days (30 days monthly, 90 quarterly).

## Priority at exit

Order of payment:

1. `transaction_costs` come off gross proceeds. This is the existing engine's
   definition of net proceeds, and the task scope pays debt from net proceeds.
2. Debt is paid by ascending **debt** seniority (0 before 1). A tier paid in full takes
   exactly its claims. A tier that proceeds do not cover shares them pro rata by claim,
   and every later tier and all equity receive nothing.
3. The remainder goes through the existing preferred and common waterfall and
   conversion search, unchanged.

Debt seniority integers rank debt against debt only. A loan with seniority 7 is still
paid before preferred stock with seniority 0.

Sources for the ordering:

- The [NVCA Model Certificate of Incorporation (Oct 2025)](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx),
  Article Fourth B §2.1, pays preferred "out of the assets of the Corporation available
  for distribution to its stockholders". Creditors are therefore ahead of the
  preference stack.
- [DGCL §281(a)](https://delcode.delaware.gov/title8/c001/sc10/index.html), on
  dissolution: "If there are insufficient assets, such claims and obligations shall be
  paid or provided for according to their priority, and, among claims of equal
  priority, ratably to the extent of assets legally available therefor. Any remaining
  assets shall be distributed to the stockholders".

This document does not invoke the bankruptcy absolute priority rule. The ordering here
is the contractual and corporate-law ordering above.

The debt settlement never depends on any preferred conversion decision. The conversion
game is therefore the same game the engine already solved, played over a smaller
residual. The equity rows of D1 equal those of F1 to the last bit
(`test_debt_is_a_pure_prefix_of_the_equity_waterfall`).

Each debt position's trace is in `WaterfallResult.debt_settlements`. It holds the
accrual (days, year fraction, periods, outstanding principal, accrued interest), any exit
fee, the claim, a basis sentence, the amount paid and the shortfall. A debt `Payout` has
`amount` set and zero preference, participation and residual components.

## Convertible notes

**Exit treatment is stated, never inferred.** At a liquidity event a note may be
repaid, paid a premium, or converted. Its terms and the holder's election decide which.
The Fenwick form §6.2(b), for example, lets the holder elect between the balance and
the as-converted amount. A note without `exit_treatment` is rejected at exit, including
at zero proceeds. `note.resolved("repay")` and
`note.resolved("multiple", exit_principal_multiple=m)` return new snapshots. A note that
converts at the event must be replaced by the equity it converts into.

The one multiple form implemented is `m × original principal + accrued interest`. Both
public forms located use it:

- D3 template §4.3: "the sum of (x) all accrued and unpaid interest due on this Note and
  (y) two times (2x) the outstanding principal balance".
- Fenwick form §2.3: the principal balance and accrued interest "plus (b) an amount equal
  to [one (1)] times the original Principal Balance". This is the same amount with
  `m = 2`.

`m` must be at least 1. The multiple is refused on PIK notes, because "principal" could
mean the original or the capitalised balance.

**Qualified financing.** A financing raising at least `qualified_financing_threshold`
converts principal plus interest accrued to the financing date. The conversion price is
`min(valuation_cap / capitalization_shares, round_price × (1 − discount_rate))`. Fenwick
defines a Next Financing by aggregate gross proceeds "of no less than [One Million
Dollars ($1,000,000)]", with a Conversion Price of "the lower of" the discounted price
and the cap divided by a stated share count. Notes define that share count differently,
so the caller supplies `capitalization_shares` and it is never inferred. A non-qualified
financing is refused, because conversion there is at the holder's option. On an exact
price tie the cap is reported as binding; the share count is the same either way.

**Maturity.** Principal and accrued interest fall due at `maturity_date`
(`repayment_at_maturity()`). Fenwick §2.1: "the Balance shall be due and payable in full
upon the written demand of the Majority Holders at any time on or after the Maturity
Date". Accrual stops at maturity, and a later `as_of` is refused.

## Venture debt

`exit_fee` is a stated amount, due in full when the loan is repaid at the event.
TriplePoint Venture Growth's
[10-K for FY2023](https://www.sec.gov/Archives/edgar/data/1580345/000158034524000005/tpvg-20231231.htm)
describes end-of-term payments as "due at the maturity date of the loan, including upon
prepayment, and are generally a fixed percentage of the original principal balance of
the loan". A [sample term sheet](https://kruzeconsulting.com/venture-debt/venture-debt-term-sheet/)
sets a final payment of "6.00% of the Advanced Amount, due upon the earlier of Maturity
or termination". A
[filed loan amendment](https://www.sec.gov/Archives/edgar/data/1341235/000115752322001788/a53133738ex10_2.htm)
states its end-of-term charges as fixed dollar amounts. Because agreements use both
forms, the fee is taken as an amount and no fee base is assumed.

## Fixture derivations

Shared time basis: issued **2025-01-01**, measured **2027-01-01**. 2025 and 2026 are not
leap years, so the span is 365 + 365 = **730 days**, and 730/365 = **2.0 years** under
Actual/365 Fixed. Notes are issued **2026-01-01**, which is **365 days** before the
measurement date (1.0 year), and mature **2028-01-01**, which is **730 days** after issue.

Shared equity: founders hold 8,000,000 common shares. Series A holds 2,000,000 shares at
$2.50: $5,000,000 invested, 1x non-participating, 20% as converted. This is the same
equity as `docs/fixtures.md`, so residuals of $35M and $15M reproduce F1 and F2.

### Accrual

**A1 — simple, Actual/365 Fixed.** $1,000,000 at 8% for 730 days.
Interest = 1,000,000 × 0.08 × 730/365 = 80,000 × 2 = **$160,000**. Claim **$1,160,000**.

**A2 — compound annually.** n = 1 × 730/365 = 2 periods at 8%.
1.08² = 1.1664, so the claim is **$1,166,400** and interest is **$166,400**. That is
$6,400 more than A1, which is 8% interest on the first year's $80,000 of interest.

**A3 — compound quarterly.** n = 4 × 730/365 = 8 periods at 0.08/4 = 2%.
1.02⁸ = 102⁸ / 10¹⁶. Squaring step by step:

- 102² = 10,404
- 102⁴ = 10,404² = 108,243,216
- 102⁸ = 108,243,216² = 11,716,593,810,022,656

So 1.02⁸ = 1.1716593810022656. The claim is **$1,171,659.3810022656** and interest is
$171,659.38. That is above annual compounding (A2) and above simple interest (A1).

**A4 — PIK, semiannual.** n = 2 × 730/365 = 4 periods at 4%. Principal grows each half
year:

- 1,000,000 × 1.04 = 1,040,000
- 1,040,000 × 1.04 = **1,081,600** (after one year)
- 1,081,600 × 1.04 = 1,124,864
- 1,124,864 × 1.04 = **1,169,858.56**

Check: 1.04⁴ = 1.16985856. Accrued cash interest is **$0**, and the exit claim equals the
grown principal, **$1,169,858.56**. Compound accrual at the same frequency gives the
same total, but it leaves principal at $1,000,000 and reports $169,858.56 as interest.

**A5 — simple, Actual/360, same dates as A1.** Interest = 80,000 × 730/360 =
58,400,000/360 = **$162,222.22…**. The day count alone adds $2,222.22.

**A6 — across a leap day.** From 2027-01-01 to 2029-01-01 is 365 + 366 = **731 days**,
because 2028 contains 29 February. Interest = 80,000 × 731/365 = 58,480,000/365 =
**$160,219.18…**.

**Venture debt.** $2,000,000 at 10% simple for 730 days. Interest is 2,000,000 × 0.10 × 2
= $400,000, and the exit fee is 3% × $2,000,000 = $60,000. Claim
**$2,460,000**.

**Note, repaid.** $500,000 at 6% simple for 365 days. Interest is **$30,000**, and the
claim is **$530,000**. At maturity (730 days) interest is $60,000 and **$560,000** falls
due.

**Note, 2x multiple.** 2 × $500,000 + $30,000 = **$1,030,000**.

### Exit waterfalls (as of 2027-01-01)

**D1 — debt covered.** Exit $36,160,000. The loan takes its **$1,160,000** claim
(A1), which leaves $35,000,000. That is F1: 20% × $35M = $7M beats the $5M preference,
so Series A converts. Result: founders **$28,000,000**, Series A **$7,000,000**, loan
$1,160,000. Sum $36,160,000.

**D2 — debt not covered.** Exit $1,000,000 against a $1,160,000 claim. The loan takes
**$1,000,000** and is $160,000 short. Nothing is left, so founders and Series A each
receive exactly **$0**. Series A is indifferent at zero and keeps "not converted".

**D3 — two debt tiers.** The senior loan (debt seniority 0) has a $1,160,000 claim. The
junior note (seniority 1, repaid) has a $530,000 claim. Exit $1,500,000. The senior loan
is paid **$1,160,000** in full. The note receives the $340,000 remainder, **$190,000**
short. Equity receives **$0**.

**D4 — one pari-passu tier.** Loan A has a $1,160,000 claim. Loan B ($500,000 at 8%
simple, same dates) has 500,000 × 0.08 × 2 = $80,000 of interest and a **$580,000** claim.
Both are seniority 0, and the total claim is $1,740,000. Exit $870,000 = 1,740,000 / 2,
so each loan is paid half its claim: loan A **$580,000**, loan B **$290,000**. Equity
receives **$0**.

**D5 — venture debt exit fee.** Exit $37,460,000. Venture debt takes **$2,460,000**,
which includes the $60,000 fee. The $35,000,000 residual is F1: founders **$28,000,000**,
Series A **$7,000,000** (converted). The lender's multiple on principal is
2,460,000 / 2,000,000 = 1.23.

**D6 — PIK debt at exit.** Exit $16,169,858.56. The PIK loan's claim is its grown
principal, **$1,169,858.56** (A4). The $15,000,000 residual is F2: as converted, Series A
would get 20% × $15M = $3M, below its $5M preference, so it holds the preference.
Result: Series A **$5,000,000**, founders **$10,000,000**.

**D7 — note paid a multiple.** Exit $16,030,000. The note takes **$1,030,000**. The
$15,000,000 residual is F2: Series A **$5,000,000**, founders **$10,000,000**.

A cost check reuses D1: gross $36,660,000 less $500,000 of transaction costs gives
$36,160,000 net, and the D1 payouts follow.

### Note conversion in a qualified financing (2027-01-01)

Both cases use the $500,000 note: 6% simple, $8,000,000 cap, 20% discount and a
$1,000,000 threshold. New money is $3,000,000, which qualifies. The amount converted is
$500,000 + $30,000 = **$530,000**. The caller states the cap capitalization as 8,000,000
shares.

**C1 — cap binds.** Round price $1.50. Cap price 8,000,000 / 8,000,000 = **$1.00**, and
discount price 1.50 × 0.8 = **$1.20**. The lower is $1.00, so the note converts into
530,000 / 1.00 = **530,000 shares**.

**C2 — discount binds.** Round price $1.10. Discount price 1.10 × 0.8 = **$0.88**, which
is below the $1.00 cap price. The note converts into 530,000 / 0.88 = **602,272.73
shares**.

With $900,000 of new money, below the threshold, conversion is refused. Replacing the
note by 530,000 preferred shares (C1) raises fully diluted shares from 10,000,000 to
10,530,000. While the note is still debt it contributes zero shares.

## Regression evidence

A table with no debt takes the same computation as before this change.

- `test_existing_fixtures_are_unchanged_without_debt` re-asserts every F-fixture's
  hand-derived payouts through the new engine. It also checks that passing an unused
  `as_of` changes no payout field and no fingerprint, and that the assumptions list is
  the pre-debt list.
- `test_no_debt_fingerprint_format_is_unchanged` recomputes F1's input hash from the
  pre-debt payload definition.
- During development, 141 no-debt cases were captured before the change and compared
  after it. They covered every F-fixture at six exit values, their equilibrium surveys,
  and the slow conversion game. Payout JSON, every pre-existing result field (including
  `input_hash` and `assumptions`) and every survey were byte-identical. The two new
  result fields, `as_of` and `debt_settlements`, are `None` and `[]` for these tables.

## Not modelled

Each item below would change a real number.

| Not modelled | Why it matters |
|---|---|
| **Lender warrants** | Warrant coverage is a material part of a venture lender's return (TriplePoint 10-K FY2023 calls warrants equity "kickers" that "enhance our overall returns"). A debt claim here is not the lender's total return, and warrant shares would dilute every equity payout. |
| **Prepayment charges** | A filed loan amendment requires the "Prepayment Charge upon the occurrence of a Change in Control". Omitting it understates the lender's claim at exit. The result's assumptions say so whenever debt is present. |
| **Amortisation and scheduled payments** | A partly repaid loan owes less than its original principal. Represent it with a new snapshot at its outstanding balance. The exit fee is a stated amount so this does not distort it. |
| **Default interest and post-maturity accrual** | Past maturity a note is due on demand, and default rates often apply. `as_of` after maturity is refused rather than accrued at the contract rate. |
| **Stub-period compounding** | Compound and PIK accrual over a partial period follows one of several conventions. It is refused, not approximated. |
| **Other day counts** (30/360 variants, Actual/Actual) | These give different year fractions for the same dates. Only Actual/365 Fixed and Actual/360 are accepted. |
| **Conversion at maturity** | No public form reviewed contained a conversion-at-maturity price clause, so it is not implemented. The note's maturity treatment is repayment only. |
| **Holder elections** (repay vs convert at a change of control, optional conversion in a non-qualified financing) | These are a further strategic choice that could enter the conversion game. The caller states the outcome. |
| **Other change-of-control multiple bases** (m × (principal + interest), multiple with interest forgone, multiples on PIK notes) | These are different amounts from the implemented `m × principal + interest`, and no public form using them was located. |
| **Note conversion into a shadow series or with a preference different from the conversion amount** | This changes the converted security's preference. The caller builds the converted security explicitly. |
| **Order of transaction costs versus debt when proceeds cannot cover both** | Set by payoff letters and the purchase agreement. Here costs come off first. |
| **Security interests, collateral, subordination agreements, intercreditor terms** | These can reorder debt beyond a single seniority integer. |
| **Interest paid in cash before exit** | The claim assumes no interest has been paid since `issue_date`. Represent payments with a new snapshot and a later `issue_date`. |
| **Taxes, withholding, currency** | Inherited from the engine: pre-tax, one base currency, no rounding. |

## What a fixture does not establish

A fixture shows that the implementation reproduces a derivation stated here. It does
not establish that a given loan or note uses these terms, that its day count, fee or
multiple matches the one chosen, or that the list above is complete.
