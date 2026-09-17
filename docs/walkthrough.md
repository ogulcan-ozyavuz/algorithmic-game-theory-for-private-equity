# Walkthrough

A single company, from a SAFE round to an exit, with the numbers checked at each step.
Everything below runs against the installed package; nothing is pseudocode.

Before starting, read [what this does not model](limitations.md). Several of the
entries there — carve-outs, accrued dividends, debt — change real payouts.

## Install

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

## 1. The question a waterfall answers

A company sells for $35M. Founders hold 8,000,000 common shares. Series A bought
2,000,000 shares at $2.50, so $5,000,000 invested, with a standard 1x
non-participating preference.

```python
import equilibria as eq

table = eq.CapTable()
table.add(eq.common(8_000_000, holder_id="founders", security_id="common"))
table.add(eq.preferred(2_000_000, 2.50, holder_id="series_a", security_id="series_a"))

report = table.waterfall_detailed(exit_valuation=35_000_000)
for payout in report.payouts:
    print(f"{payout.security_id:<10} ${payout.amount:>12,.0f}  converted={payout.converted}")
```

```
common     $  28,000,000  converted=False
series_a   $   7,000,000  converted=True
```

Series A converted. Its preference is worth $5M; its 20% as-converted share of $35M is
worth $7M, so it gives up the preference. That choice is the whole problem: it depends
on the exit value, and with several series it depends on what the others choose.

## 2. Where the choice flips

```bash
python -m ovf sweep --demo F8a --to 30000000 --steps 8
```

```
             exit            common          series_a          series_b   common share
$            0.00                 0                 0                 0     0.0%
$    4,285,714.29                 0                 0         4,285,714     0.0%
$    8,571,428.57                 0                 0         8,571,429     0.0%
$   12,857,142.86                 0         3,857,143         9,000,000     0.0%
$   17,142,857.14         3,142,857         5,000,000         9,000,000    18.3% ####
$   21,428,571.43         7,428,571         5,000,000         9,000,000    34.7% #######
$   25,714,285.71        11,714,286         5,000,000         9,000,000    45.6% #########
$   30,000,000.00        16,000,000         5,000,000         9,000,000    53.3% ###########
```

This table has Series A ($5M, junior) and Series B ($9M, senior). Common receives
nothing at all until the $14M of preferences is covered. That range is the part people
are usually surprised by, so the sweep names it explicitly:

```
Common holders received nothing at every sampled exit up to $12,857,142.86.
```

The grid can step over a kink; raise `--steps` when you need the exact boundary.

## 3. Reading the verification block

Every result carries its own diagnostics:

```
Verified equilibrium: True  (max unilateral gain 0.00e+00, tolerance 6.00e-05, sweeps 1)
Conservation error:   0.00e+00
Input fingerprint:    7599ec189619f251  engine waterfall-v3
```

- **max unilateral gain** — after solving, every position was re-checked against its
  alternative. Zero means no position could improve by switching. If this exceeded the
  tolerance the call would have raised instead of returning.
- **conservation error** — payouts minus net proceeds. Cash is neither created nor lost.
- **input fingerprint** — SHA-256 of the inputs, so a reported number can be tied to
  the table that produced it. It is provenance, not a signature.

## 4. When the answer has more than one story

At an exit of exactly $25M the Series A preference and its as-converted value are both
$5M. Two conversion profiles are equilibria:

```bash
python -m ovf equilibria --demo F3
```

```
Pure equilibria     2
Fully allocating    2
Distinct payouts    1
Payout unique       True

  [series_a=preference]  ->  common=20,000,000, series_a=5,000,000
  [series_a=convert]     ->  common=20,000,000, series_a=5,000,000
```

Two profiles, one payout. That pattern held in every instance enumerated for
[findings](findings.md) — roughly 30% of generated tables have several equilibrium
profiles, and none produced different cash. It is an empirical result on the
implemented scope, not a theorem, and the reasoning is written out there.

## 5. A financing round first

The same company, before the exit. $3M of new money at a $12M pre-money, with a
$1M SAFE on a $10M post-money cap and a new 10% option pool.

```bash
python -m ovf safe --prior-common 8000000 --new-money 3000000 \
    --pre-money 12000000 --pool 0.10 --safe 1000000:10000000:angel
```

```
Round share price   $1.18125
holder         ownership
founders       63.0000%
new_preferred  20.0000%
option_pool    10.0000%
angel           7.0000%

SAFE conversion
  safe_post_angel: 888,888.8889 shares at $1.125
```

Run it again with `--pool 0` and founders hold 72%, the angel 8%, the new investor
still exactly 20%. The pool's ten points come out of the founders and the SAFE, never
out of the incoming round, because the pool sits inside the negotiated pre-money.
That is the option pool shuffle, and it is arithmetic rather than opinion.

## 6. Carrying the round into an exit

```python
import equilibria as eq

result = eq.solve_priced_round_with_safes(
    prior_common_shares=8_000_000,
    new_money=3_000_000,
    pre_money_valuation=12_000_000,
    target_pool_pct=0.10,
    safes=[eq.safe_post(amount=1_000_000, cap=10_000_000, holder_id="angel")],
)
post_round = result.to_cap_table()
exit_report = post_round.waterfall_detailed(100_000_000)
```

`to_cap_table()` builds an explicit snapshot and states what it assumed: 1x
non-participating pari-passu preferred, founder common with unknown cost basis, and an
entirely unallocated pool. Negotiated rights that the round did not model — participation,
seniority, dividends — need `PreferredStock` objects constructed directly.

## 7. Reporting a problem

Numbers that disagree with a real closing statement are the most useful report this
project can receive. Open an issue with the cap table, the exit value, the number you
expected, and the contract convention or derivation behind it. The
[calculation issue template](../.github/ISSUE_TEMPLATE/calculation-issue.md) asks for
exactly those fields.

If the disagreement is caused by something in [limitations](limitations.md), saying so
is still useful: it tells us which gap to close first.
