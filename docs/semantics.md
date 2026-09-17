# Calculation semantics and limits

Status: alpha, reviewed 2026-09-15. These definitions are the implemented model,
not a representation of every financing document or a regulatory valuation opinion.

## Numbers and identity

- All cash inputs share one caller-selected base currency. There is no implicit FX.
- Computation uses finite IEEE-754 floats. Money fields are nonnegative; signed fund
  cash flows will need a separate type when the fund module is implemented.
- Waterfall verification tolerance is `1e-8 + 1e-12 * net_exit` in base-currency units.
  There is no cent rounding; future settlement rounding must conserve the rounded total.
- `security_id` identifies one position and must be unique. `holder_id` can repeat;
  holder ownership is aggregated. Each preferred record is an independent player.
- Shared class voting and coordinated beneficial-owner decisions are not represented.
  A holder-level allocation model is required before claiming those semantics.
- Immutable securities must be replaced, rather than edited, for new snapshots.

## Exit event

Net proceeds are `max(0, exit_valuation - transaction_costs)`. Negative or nonfinite
inputs are rejected. Supported debt instruments are settled from net proceeds ahead of
all equity; see [debt](debt.md). Other prior claims must still be settled outside this
model and netted off.
Unconverted SAFEs and other unsupported instrument types are rejected, including at
zero exit; their contractual liquidity-event rights are not implemented.

For a fixed conversion vector:

1. Settle debt claims first, by ascending debt seniority, pro rata by claim within a
   tier. Debt requires an explicit `as_of` date; no clock is read.
2. Pay nonconverted preferred claims by ascending seniority integer (0 before 1). A
   claim includes any accrued dividend; see [dividends](dividends.md) for the accrual
   methods, the conversion-settlement choice and the participation-cap basis.
3. Within a tier, scarce proceeds are split proportional to liquidation preference.
4. Distribute residual cash to common, converted preferred and participating preferred,
   using common-equivalent shares. A nonconverted participant stops at its total cap.
5. An entirely unallocated option reserve receives no proceeds. Allocated options are
   rejected because strike, vesting and transaction settlement terms are not available.

The search starts with no conversions, scans preferred IDs in sorted order and compares
both actions at the **current** state. Strict improvements exceed the reported tolerance.
After each pass, it checks every possible unilateral deviation. Only verified states
are returned. A cycle or an exhausted iteration budget raises `WaterfallConvergenceError`.
Neither uniqueness nor monotone convergence is claimed. Exhaustive tests on small games
are evidence for those tested instances, not a general proof.

`enumerate_equilibria` evaluates all `2**n` conversion profiles and reports every
pure equilibrium, which profiles allocate the whole exit, and whether they pay the
same amounts. It is exponential in the number of preferred positions and refuses to
run above `max_positions`. Several profiles paying identical amounts is ordinary;
see [findings](findings.md) for the measured frequency and for the scope of the
payout-uniqueness evidence.

`WaterfallResult` carries input SHA-256, engine revision, assumptions, tolerance,
iterations, maximum unilateral gain, conservation error and `multi_position_holders`.
The last names holders owning several preferred positions, where the
independent-position assumption is weakest; it is a disclosure, not a coordinated-holder
model. This is basic provenance, not a signature, W3C PROV-O implementation or proof
certificate. `payout_pct` measures proceeds; `CapTable.ownership_breakdown()` measures
fully diluted equity.

## SAFE financing convention

The starting capitalization contains only `C` common shares: no existing preferred,
existing pool, promised options, warrants or notes. The result creates an entirely new
unallocated pool. Mixing pre- and post-money SAFEs is rejected.

Let `V` be negotiated pre-money, `N` new cash, `W=V+N`, `q=N/W`, `t` target post-round
pool fraction, and `I_i`, `K_i`, `d_i` each SAFE's amount, cap and discount. The priced
round includes all converting SAFE shares and the new pool within its pre-money.
This fixes new investor ownership to `q`. It is one explicit pricing convention;
`method='pre_money'` names the SAFE's capitalization basis, not the Cooley method.

### Post-money capitalization

Let `B=C+sum(S_i)` exclude the new pool and new cash. Then:

```
a_i = I_i / min(K_i, W*(1-q-t)*(1-d_i))
B = C / (1-sum(a_i))
T = B / (1-q-t)
P = W / T
S_i = a_i * B
```

The conversion price is the better of the cap price `K_i/B` and discounted round
price `P*(1-d_i)`. `sum(a_i) < 1` and `1-q-t > 0` are required. This includes down-round
cases where the round price beats the cap. Nonzero `d_i` is an explicit custom
cap-plus-discount extension; YC's cap-only form uses `d_i=0`.

For $1M at a $10M cap, $12M pre + $3M new and no pool, the SAFE has 10% before the
new money, then 8% after it; founders have 72%. With two cap-binding SAFEs selling
10% and 5% before a 20% new investment and 10% new pool, their post-round percentages
are 7% and 3.5%; founders retain 59.5%.

### Pre-money capitalization

The cap denominator is `C+O`, where `O=t*T`; converting SAFEs are excluded. With
`u=P*C/W`, the monotone scalar equation is:

```
u + sum(max(I_i/K_i*(u+t), I_i/W/(1-d_i))) = 1-q-t
T = C/u; P = W/T; O=t*T
S_i = I_i / min(K_i/(C+O), P*(1-d_i))
```

A bracketed bisection solves the normalized equation, with an explicit iteration limit
and post-solution share-conservation check. This is not a matrix solver. Existing
pools and alternative capitalization definitions require an additional model.

### Round-to-exit transition

`SafeConversionResult.to_cap_table()` explicitly produces a new snapshot with founders,
converted SAFE preferred, new investor preferred and unallocated pool. Preferred is
1x nonparticipating and pari-passu; SAFE preference is based on its own conversion
price (purchase amount per converted share). The starting founder cost basis is unknown
and set to zero, so its effective multiple is `None`. This helper does not mutate an
existing arbitrary cap table or preserve unmodeled rights.

## References and evidence

- [YC SAFE documents](https://www.ycombinator.com/documents/) and [current SAFE explanation](https://www.ycombinator.com/safe): ownership timing, capitalization and conversion choices.
- [Cooley: share pricing with convertibles](https://www.cooleygo.com/calculating-share-price-outstanding-convertible-notes-or-safes/): negotiated financing conventions can allocate dilution differently.
- `tests/test_regressions.py`: hand-derived cap, discount, down-round, pool and duplicate-ID cases.
- `tests/test_equilibrium_reference.py`: exact rational allocation and exhaustive conversion profiles on small generated games.
- `tests/test_fixtures.py`, `tests/test_safe_fixtures.py`: named market-convention cases; derivations in [fixtures](fixtures.md).
- `tests/test_conversion_stress.py`: adversarial games, knife-edge exits, search-guard behaviour.
- [findings](findings.md): what the enumeration evidence supports and what it does not.
- [debt](debt.md): debt instruments, accrual methods and absolute priority at exit.
- [anti-dilution](antidilution.md): weighted-average and full-ratchet conversion-price adjustment.
- [dividends](dividends.md): cumulative and non-cumulative dividends, and Proposition 1.
- [financing](financing.md): applying an anti-dilution adjustment to a cap table.
- [rounds](rounds.md): priced rounds over an existing table, Cooley's three conventions, MFN.
- [governance](governance.md): what moves cash and what only gates the sale.
- [presets](presets.md): NVCA model term-sheet presets, and why there is no Series B.
- [ocf](ocf.md): Open Cap Table Format v1.2.0 mapping, conventions and refusals.
- [limitations](limitations.md): features that are absent and would change a payout.

Source examples and independent specialist review remain launch gates. No 409A/IPEV
compliance, universal contractual coverage or certified financial advice is asserted.
