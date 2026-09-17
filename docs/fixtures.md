# Fixture provenance and derivations

Status 2026-09-15. Every expected number below is derived by hand here, then asserted
against the engine in `tests/test_fixtures.py` and `tests/test_safe_fixtures.py`.
Each derivation was independently recomputed with exact rational arithmetic before
being written down.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` in
both fixture modules is empty. An external specialist confirming the term shapes and
the arithmetic is a launch gate; see [TODO](../TODO.md).

Fund-performance fixtures (open-pme, PME-F1 to PME-F19) are derived separately in
[pme-fixtures](pme-fixtures.md) and checked against both the engine and an independent
exact oracle in `tests/test_pme_reference.py`.

## Where the term shapes come from

The shapes are chosen to match documented market conventions, not to reproduce any
particular company's charter. No confidential or licensed document was used.

| Shape | Basis |
|---|---|
| 1x non-participating | Cooley's Q2 2026 venture financing report records a 1x preference in 95.8% and non-participating terms in 96.4% of reported financings. |
| Participating preferred, capped and uncapped | Kaplan & Strömberg (2003, *Review of Economic Studies* 70(2), 281–315) record participating preferred in roughly 40% of 1987–1999 rounds; Carta reports 4.1% of primary rounds in Q3 2024. Retained because the structure reappears in down rounds. |
| Stacked seniority and pari passu | The two standard conventions for ranking several preferred series. Both are modelled; neither is treated as the default. |
| Unallocated option reserve | Counts in fully diluted ownership, holds no issued shares, receives no exit cash. See [semantics](semantics.md). |
| YC post-money SAFE | [Postmoney Safe with Valuation Cap v1.2](https://www.ycombinator.com/documents/), cap-only form, `d = 0`. |
| Pre-money SAFE capitalization | Contrast case for the definitional difference; see [semantics](semantics.md) §SAFE financing convention. |

## Shared cap table

Founders hold **8,000,000** common shares.

- **Series A**: 2,000,000 shares at $2.50 = **$5,000,000** invested.
- **Series B**: 1,500,000 shares at $6.00 = **$9,000,000** invested.
- Fully diluted with Series A only: 10,000,000 shares, so Series A is **20%**.

## Waterfall derivations

**F1 — 1x non-participating, converts.** Exit $35M. Preference is $5M; as-converted is
20% × $35M = $7M. $7M > $5M so Series A converts. Founders take the remaining 80%.
→ founders **$28,000,000**, Series A **$7,000,000**.

**F2 — 1x non-participating, takes the preference.** Exit $15M. As-converted is
20% × $15M = $3M, below the $5M preference. Series A holds the preference; the $10M
residual goes to common. → founders **$10,000,000**, Series A **$5,000,000**.

**F3 — exact indifference.** Preference equals as-converted value when
0.20 × X = $5M, so X = **$25M**. At that exit both actions pay $5M, so both profiles
are equilibria and both pay the same amounts. The solver keeps the incumbent decision
on a tie, so it reports "not converted". → founders **$20,000,000**, Series A
**$5,000,000**. This is the smallest case in [findings](findings.md).

**F4 — participating, uncapped.** Exit $35M. Series A takes the $5M preference, then
participates on an as-converted basis in the $30M residual: 20% × $30M = $6M.
→ Series A **$11,000,000**, founders **$24,000,000**. Converting would pay $7M, so it
does not convert.

**F5a — participation cap binds.** Cap is 2.0x on $5M invested, so at most $10M total.
Exit $40M: preference $5M plus 20% × $35M = $7M would be $12M, above the cap, so the
payout stops at **$10,000,000**; founders take **$30,000,000**. Converting would pay
20% × $40M = $8M, less than $10M.

**F5b — the cap makes conversion better.** The cap and the as-converted value are
equal when 0.20 × X = $10M, so X = $50M. Above that, converting wins. Exit $60M:
converting pays 20% × $60M = **$12,000,000**; founders take **$48,000,000**.

**F6 — stacked seniority, proceeds below total preference.** Series B is senior
(seniority 1), Series A junior (seniority 2). Exit $10M: Series B takes its full $9M,
Series A receives the $1M remainder, common receives nothing. Checking Series A's
alternative: converting removes it from the preference queue, Series B still takes
$9M, and the $1M residual splits over 8,000,000 common and 2,000,000 converted shares,
paying Series A 20% × $1M = $0.2M, which is worse than $1M. → Series B
**$9,000,000**, Series A **$1,000,000**, founders **$0**.

**F7 — pari passu, proceeds below total preference.** Both series in one tier. Claims
are $5M and $9M, total $14M; $10M is short, so it splits in proportion:
Series A = $10M × 5/14 = **$3,571,428.57**, Series B = $10M × 9/14 =
**$6,428,571.43**, founders **$0**.

**F8a — upper edge of the dead zone.** Total preference is $5M + $9M = **$14M**. At an
exit of exactly $14M the preferences absorb everything and common receives **$0**.
Neither series converts: as-converted values are 2/11.5 × $14M = $2.43M and
1.5/11.5 × $14M = $1.83M, both below their preferences.

**F8b — first exit above the dead zone.** Exit $20M. Preferences take $14M; the $6M
residual goes entirely to common, because neither preferred converted. → founders
**$6,000,000**, Series A **$5,000,000**, Series B **$9,000,000**.

**F9 — unallocated pool.** Adds a 1,000,000-share reserve. Fully diluted is 11,000,000
shares, so Series A is **18.18% of equity**. But the reserve holds no issued shares
and receives no proceeds, so the residual is shared over 10,000,000 shares and Series
A receives **20% of proceeds**. Exit $35M: converting pays 2/10 × $35M = $7M > $5M.
→ founders **$28,000,000**, Series A **$7,000,000**, pool **$0**. The gap between
18.18% of equity and 20% of cash is the point of this fixture.

**F10 — 2x participating.** Preference is 2 × $5M = $10M. Exit $30M: $10M plus
20% × $20M = $4M gives **$14,000,000**; founders take **$16,000,000**. Converting
would pay $6M.

## SAFE derivations

Notation from [semantics](semantics.md): `C` prior common, `N` new money, `V` pre-money,
`W = V + N`, `q = N/W`, `t` post-round pool fraction, `I` and `K` the SAFE amount and
cap, `B` pre-round capitalization including converting SAFEs, `T` post-round total,
`P = W/T`.

**S1 — cap binds, no pool.** C = 8,000,000, N = $3M, V = $12M, so W = $15M, q = 0.2,
t = 0.
`a = I / min(K, W(1−q−t)) = 1M / min(10M, 12M) = 1M/10M = 0.10` — the cap binds.
`B = C/(1−a) = 8M/0.9 = 8,888,888.89`; `T = B/0.8 = 11,111,111.11`;
`P = 15M/T = $1.35`; SAFE shares `= a·B = 888,888.89`, conversion price
`= 1M/888,888.89 = $1.125`, which equals the cap price `K/B = 10M/8,888,888.89`.
→ founders **72%**, angel **8%**, new **20%**.

**S2 — down round; the round price beats the cap.** C = 8,000,000, N = $1M, V = $4M,
so W = $5M, q = 0.2, t = 0.
`a = 1M / min(10M, 5M × 0.8) = 1M/4M = 0.25` — the round price binds, not the cap.
`B = 8M/0.75 = 10,666,666.67`; `T = B/0.8 = 13,333,333.33`; `P = $0.375`;
SAFE shares `= 2,666,666.67` at **$0.375**, the round price.
→ founders **60%**, angel **20%**, new **20%**.
This is the YC document's "greater of" rule running in the holder's favour: the cap
sets a ceiling on price, never a floor, so a cheap round converts the SAFE cheaply.

**S3 — S1 plus a 10% pool.** t = 0.10, so `W(1−q−t) = 15M × 0.7 = 10.5M`, and
`a = 1M/min(10M, 10.5M) = 0.10` — the cap still binds, just.
`B = 8,888,888.89`; `T = B/0.7 = 12,698,412.70`; `P = $1.18125`.
→ founders **63%**, angel **7%**, new **20%**, pool **10%**.
Against S1 the new investor still holds exactly 20%; the pool's 10% comes out of
founders (72% → 63%) and the SAFE (8% → 7%). That is the option pool shuffle, stated
numerically: a pool placed inside the pre-money is paid for by everyone except the
incoming round.

**S4 — two capped SAFEs with a 10% pool.** C = 8,000,000, N = $4M, V = $16M, W = $20M,
q = 0.2, t = 0.10, so `W(1−q−t) = $14M`. Caps of $10M bind for both.
`a₁ = 1M/10M = 0.10`, `a₂ = 0.5M/10M = 0.05`, `Σa = 0.15`.
`B = 8M/0.85`; `T = B/0.7`; founders `= C/T = 0.85 × 0.7 = **59.5%**`;
angel 1 `= 0.10 × 0.7 = **7%**`; angel 2 `= 0.05 × 0.7 = **3.5%**`.
Each cap fixes its own fraction of pre-round capitalization independently, so
post-money SAFEs do not dilute one another. `tests/test_safe_fixtures.py` asserts this
by solving the same round with one SAFE and checking angel 1's percentage is unchanged.

**S5 — pre-money SAFE on the same cash and cap as S1.** The monotone equation is
`u + max(I/K·(u+t), I/W) = 1−q−t` with `u = P·C/W`.
`u + max(0.1u, 0.0667) = 0.8`. Taking the cap branch: `1.1u = 0.8`, `u = 0.727273`,
which satisfies `0.1u > 0.0667`. `T = C/u = 11,000,000`; `P = $1.363636`;
cap price `= K/(C+O) = 10M/8M = $1.25`; SAFE shares `= 1M/1.25 = 800,000`.
→ founders **72.7273%**, angel **7.2727%**, new **20%**.
Same cash, same cap number, **7.27% instead of 8%**. The pre- and post-money
difference is definitional — which capitalization the cap is measured against — not a
difference in negotiated price.

## Fixtures in the other modules

The same discipline applies to the modules added alongside this one. Their derivations
live with them rather than here:

- [debt](debt.md) — accrual fixtures A1-A6, exit fixtures D1-D7, note conversions C1-C2.
- [anti-dilution](antidilution.md) — AD1-AD6b plus the AD7 conversion-ratio identity.
- [dividends](dividends.md) — DV1-6, DW1-11 and FL0-3, plus Proposition 1.
- [financing](financing.md) — FA1-FA6 and FX1, including the order-independence proof.
- [rounds](rounds.md) — EP1, YC1/YC2, DO1-DO2, MF, MX1-MX2, CM/CS and MR.
- [governance](governance.md) — GV1-GV6, including the non-monotonic case.
- [presets](presets.md) — P1-P10, including the one-bracket contrasts.
- [ocf](ocf.md) — O1-O11, hand-derived and, as that document states, not yet independently reviewed.

## What a fixture does not establish

A fixture asserts that the implementation reproduces a derivation stated here. It does
not establish that the derivation matches any particular contract, that the convention
chosen is the one a given financing used, or that the modelled scope is complete. The
[limitations](limitations.md) list is the companion to this document.
