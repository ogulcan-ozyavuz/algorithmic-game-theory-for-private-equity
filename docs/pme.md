# Private-market performance: dated flows, IRR and public-market equivalents

Status 2026-09-15, engine `pme-v1`, module `ovf.pme`. Pure functions over stated dated
cash flows, a stated residual value and a stated benchmark index. Nothing is estimated,
forecast, interpolated or looked up from a clock.

**Review status: source-checked, not yet independently reviewed.** Every source claim on
this page links to its row in the verification ledger, [pme-sources](pme-sources.md),
which records where each claim was read and how far that reading can be trusted. Rows
marked `DERIVED` there are algebra proved in the ledger, not claims about a source.

## Purpose and audience

The module reproduces a fund's dated cash-flow metrics and its comparison with a public
index. Every convention that moves a number is a stated input. It is for fund analysts, LP
research teams and academics who need the same numbers from the same inputs on any
machine, and who need to know *why* a number is undefined rather than receive a plausible
one.

It measures; it does not value. The residual value (NAV) is an input that the caller
supplies and the module takes at face value. It is not an ILPA or GIPS compliance tool
(see [practice standards](#practice-standards)). Agreement with it is not evidence that a
manager's reported figure is correct.

| Function | Returns | What it is |
|---|---|---|
| `ovf.pme.daycount.year_fraction` | `float` | signed, additive year fraction under a stated convention |
| `ovf.pme.flows.resolve` | `ResolvedCashFlows` | the only input every metric consumes: flows, residual value and per-date nets at `as_of` |
| `ovf.pme.metrics.multiples` | `Multiples` | DPI, RVPI, TVPI |
| `ovf.pme.irr.npv` | `float` | NPV of a dated series at a stated annual rate |
| `ovf.pme.irr.xirr`, `ovf.pme.irr.fund_irr` | `IrrResult` | every real IRR root, with a proof that the list is complete, or a reason why it is not |
| `ovf.pme.benchmark.index_level` | `IndexLookupRecord` | the index level used for a date, and how far back it had to look |
| `ovf.pme.pme.ks_pme` | `KsPmeResult` | Kaplan–Schoar PME |
| `ovf.pme.pme.direct_alpha` | `DirectAlphaResult` | Direct Alpha, annual effective and continuous |
| `ovf.pme.pme.pme_plus` | `PmePlusResult` | Rouvinez PME+ scale factor and IRR |
| `ovf.pme.pme.ln_pme` | `LnPmeResult` | Long–Nickels index comparison method (ICM) |
| `ovf.pme.mpme.mpme` | `MpmeResult` | mPME, a labelled reconstruction of Cambridge Associates' method (needs a `FundNavHistory`) |
| `ovf.pme.report.pme_report` | `PmeReport` | every metric above in one call, each slot a result or a `Refusal`, with machine-readable flags, de-duplicated assumptions, `to_text()` and `to_rows()` |
| `ovf.pme.io.read_flows_csv`, `read_index_csv`, `read_nav_csv` | tuples of inputs | strict CSV loaders (ISO dates; a required sign convention; every bad row refused with its line number) |
| `FundCashFlows.through` | `(FundCashFlows, excluded)` | explicit truncation at a date, returning the flows it excluded |
| `python -m ovf pme report` | text or JSON | the report from CSV files, every convention a required flag |

Every result model carries `assumptions`, `input_hash` (sha256 of the canonical inputs) and
`engine_version`; the row records inside them (`IndexLookupRecord`, `FlowValuation`,
`IcmStep`, `MpmeStep`) do not. Models are frozen (no field can be reassigned); as
everywhere in `ovf`, the `assumptions` list itself is not deep-frozen. No result ever contains NaN or infinity: an undefined ratio or rate is
`None`, and an assumption line says why.

### Worked example

The Gredil–Griffiths–Stucke illustration (2014 draft, Exhibits 5–6; fixture PME-F12), end
to end. `examples/pme_walkthrough.py` does the same from CSV files and checks every
printed figure against the paper; `python -m ovf pme report` does it from the command line.
The index's return basis is not stated in the source; the value below is illustrative.

```python
from datetime import date

from ovf.pme import BenchmarkIndex, CashFlow, FundCashFlows, IndexLevel, NavObservation
from ovf.pme import direct_alpha, fund_irr, ks_pme, pme_report, resolve


def dec31(year: int) -> date:
    return date(year, 12, 31)


fund = FundCashFlows(
    name="GGS 2014 Exhibit 5",
    currency="USD",
    basis="net_lp",
    flows=(
        CashFlow(date=dec31(2001), kind="contribution", amount=100),
        CashFlow(date=dec31(2003), kind="contribution", amount=100),
        CashFlow(date=dec31(2003), kind="distribution", amount=25),
        CashFlow(date=dec31(2005), kind="contribution", amount=50),
        CashFlow(date=dec31(2005), kind="distribution", amount=150),
        CashFlow(date=dec31(2007), kind="distribution", amount=150),
        CashFlow(date=dec31(2009), kind="distribution", amount=100),
    ),
    nav=NavObservation(date=dec31(2010), value=75),
)
levels = (100, 78, 100, 111, 117, 135, 142, 90, 113, 131)
index = BenchmarkIndex(
    name="GGS index",
    currency="USD",
    return_basis="total_return_gross",
    levels=tuple(IndexLevel(date=dec31(2001 + i), level=v) for i, v in enumerate(levels)),
)

# Method by method: every convention is a required keyword.
resolved = resolve(fund, as_of=dec31(2010), stale_nav="refuse")
irr = fund_irr(resolved, day_count="ACT/365F")
ks = ks_pme(resolved, index, lookup="exact", max_gap_days=0)
da = direct_alpha(resolved, index, lookup="exact", max_gap_days=0, day_count="ACT/365F")
print(irr.status, round(irr.irr, 4))                       # unique 0.1752
print(round(ks.ks_pme, 4))                                 # 1.6668
print(round(da.alpha_annual_effective, 4), round(da.alpha_continuous, 4))  # 0.1256 0.1183

# Or everything at once, with flags and de-duplicated assumptions.
report = pme_report(
    fund, index, as_of=dec31(2010), stale_nav="refuse", day_count="ACT/365F",
    lookup="exact", max_gap_days=0, nav_history=None, interim_nav=None,
    max_nav_gap_days=None,
)
print(report.ln_pme.icm_irr.status)                        # multiple
print([round(r.rate, 4) for r in report.ln_pme.icm_irr.roots])  # [-0.2726, 0.0597]
print(report.to_text())
```

Each slot of the report is either the method's result or a `Refusal` naming why it could
not be computed; `report.flags` carries machine-readable warnings (`ICM_WENT_SHORT`,
`IRR_NOT_UNIQUE`, `PRICE_RETURN`, `NAV_ROLLED_FORWARD`, …).

## Perspective and sign conventions

The perspective is the **investor (LP) in the fund**.

| Input | Meaning | Signed form used for discounting |
|---|---|---|
| `CashFlow(kind="contribution")` | cash the LP pays in (paid-in capital) | `−amount` |
| `CashFlow(kind="distribution")` | cash the LP receives | `+amount` |
| `NavObservation` | the LP's residual value in the fund at a date | `+value`, dated `as_of` |

A flow is typed (a kind plus a strictly positive amount), never a bare signed number, so a
sign typo cannot silently turn a capital call into a distribution. A zero amount is
refused because it is not a flow. A NAV may be zero (a fully realised fund) but not
negative.

## Flow basis: `net_lp` or `gross_fund`

The basis is a required field of `FundCashFlows` and is never inferred:

- `"net_lp"`: the LP's own flows, after management fees and carried interest. This is
  what an LP's ledger shows and what LP-sourced datasets hold.
- `"gross_fund"`: the fund's investment-level flows, before fees and carry.

The basis changes no arithmetic. It is copied into every result's assumptions because the
same formula answers different questions on the two bases. Net figures measure the LP's
outcome; gross figures measure the manager's investment selection. The gap between them is
fees and carry, which this module does not reconstruct (see [not modelled](#not-modelled)).

- On `net_lp`, fees paid through capital calls are already inside `paid_in`. Deducting
  them again from the flows double counts them.
- A net PME compares the LP's after-fee outcome with a costless index; that is how the
  literature reports it ([S1.1](pme-sources.md#s1): "all net of fees").

## Day count

A date `d` becomes a time `t = year_fraction(t0, d, convention=...)` in years. Three
conventions are offered, and none is a default:

| Convention | Year fraction for a period of `n` actual days |
|---|---|
| `"ACT/365F"` | `n / 365`, leap years ignored ([S9.2](pme-sources.md#s9)). This is the convention of Excel's and LibreOffice's `XIRR` ([S9.4](pme-sources.md#s9)). |
| `"ACT/365.25"` | `n / 365.25` |
| `"ACT/ACT-ISDA"` | days falling in leap years / 366 + days falling in other years / 365, counting from the start date up to the day before the end date ([S9.1, S9.3](pme-sources.md#s9)) |

`year_fraction` is signed (negative when `end < start`) and **additive**:
`year_fraction(a, c) == year_fraction(a, b) + year_fraction(b, c)`. All three conventions
are additive because each is a sum of a fixed weight per calendar day.

**Why additivity makes the IRR independent of `t0`.** Moving the reference date from `t0`
to `t0'` shifts every time by the same constant `c`. The NPV becomes
`sum_i a_i (1+r)^{-(t_i + c)} = (1+r)^{-c} · sum_i a_i (1+r)^{-t_i}`. The factor
`(1+r)^{-c}` is positive, so the roots are unchanged ([D1](pme-sources.md#derivations)).

Excel measures from the first *listed* date and refuses a list whose first row is not the
earliest ([S7.5](pme-sources.md#s7)). This module measures from the earliest date (reported
as `IrrResult.t0`), which gives the same IRR. A convention that was not additive would make
the IRR depend on an arbitrary choice of `t0`, so none is offered.

The conventions do give different IRRs from one another, because they space the same dates
differently. Under `ACT/365F` a year containing 29 February is 366/365 years long. To match
a spreadsheet, use `ACT/365F`: Microsoft's published example (0.373362535) reproduces with
days/365 ([S7.6](pme-sources.md#s7)).

## Same-date netting and NAV timing

**Netting.** All amounts on one date are netted into one signed amount before discounting.
NPV is unchanged by this, because terms with the same `t` add. Netting matters for two
other reasons:

- The sign-change count that governs the root policy (below) is a property of the netted
  series. It can fall when a contribution and a distribution share a date.
- A date whose net is exactly zero contributes nothing. It is dropped from the discounting
  series and listed in `ResolvedCashFlows.netted_to_zero`. A leading zero is also what
  makes Excel's `XIRR` return an error ([S7.8](pme-sources.md#s7)).

The multiples use gross sums, not nets: `paid_in` is the sum of all contributions and
`distributed` the sum of all distributions.

**Canonical order.** Flows are stored in the order (date, contribution before
distribution, amount, `flow_id`). The same flows supplied in any order therefore hash to
the same `input_hash`, and order carries no meaning. A repeated non-`None` `flow_id` is
refused.

**NAV timing.** A NAV dated `d` is **end of day**: it already reflects every flow dated
`d`. When the NAV is dated `as_of`, the residual joins the net for `as_of`. A flow on
`as_of` is therefore both paid and already reflected in the NAV, which is what an
end-of-day valuation means.

## Incomplete NAV

`resolve(fund, as_of=..., stale_nav=...)` produces the residual value at `as_of` in one of
three ways, recorded in `nav_source`:

| Situation | `nav_source` | Residual at `as_of` |
|---|---|---|
| `fund.nav is None` | `"none"` | `None`: no valuation is available |
| NAV dated `as_of` | `"reported_at_as_of"` | the reported value |
| NAV dated before `as_of`, `stale_nav="roll_forward_cash_adjusted"` | `"rolled_forward"` | `NAV + contributions − distributions` dated in `(nav.date, as_of]` |

A fully realised fund must say so explicitly with `NavObservation(date=as_of, value=0)`.
"No NAV" and "NAV of zero" are different statements and are never conflated. With
`nav_source="none"`, only DPI is computed. RVPI and TVPI are `None`, and `fund_irr` and
every PME refuse. Treating a missing NAV as zero would write the unrealised portfolio off.

The roll-forward assumes the fund earned **exactly zero** between the NAV date and
`as_of`. `NavRollForward` records the details, and an assumption line states it. This is a
convention, not an estimate. In a PME, the index keeps compounding over that gap while the
fund is held flat. A stale NAV therefore mechanically moves the PME against the fund when
the index rose, and in its favour when the index fell.

Refused inputs (each raises `ValueError` naming the offending date):

| Refused | Why |
|---|---|
| A flow dated after `as_of` | Truncating it would silently change the fund. |
| `as_of` before the first flow | There is nothing to measure. |
| A NAV dated after `as_of` | A valuation from the future is not the value at `as_of`. |
| A NAV dated before `as_of` under `stale_nav="refuse"` | The valuation is not at `as_of`. |
| A negative rolled-forward value | Distributions after the NAV date exceed the NAV plus later contributions, so the inputs are inconsistent. |

## Benchmark index

A PME compares the fund with a hypothetical investment in an index, so the index's
definition is as much an input as the flows.

**Return basis** (`BenchmarkIndex.return_basis`, required):

| Basis | Meaning |
|---|---|
| `"total_return_gross"` | dividends reinvested, before withholding tax |
| `"total_return_net"` | dividends reinvested, after the index provider's withholding-tax treatment |
| `"price_return"` | price only; dividends omitted |

The PME literature discounts at the index **total return** ([S1.1, S1.4](pme-sources.md#s1)).
A price-return index is accepted, but it adds an assumption line. Omitting dividends lowers
the index's growth, so every PME against it **overstates** the fund's relative performance,
by roughly the dividend yield per year in Direct Alpha terms
([D9](pme-sources.md#derivations)). Kaplan and Schoar's working paper says "total return to
the S&P 500"; their journal text says only "the returns on the S&P 500 index"
([S1.3](pme-sources.md#s1)). When reproducing a published PME, check which series was used.

**Lookup** (`index_level(benchmark, on, lookup=..., max_gap_days=...)`):

- `"exact"` requires a level dated exactly `on`, with `max_gap_days == 0`.
- `"last_on_or_before"` uses the latest level dated on or before `on`, provided the gap is
  at most `max_gap_days`. A weekend or holiday flow is the usual reason to allow a gap of a
  few days.

The module never looks forward and never interpolates. Looking forward would use prices
not known on the flow date, and interpolation would invent a price. A missing level raises
`ValueError` naming the date. The as-of level is reported as an `IndexLookupRecord`
(requested date, date used, level, gap); every flow's level, the date it came from and its
gap are on its `FlowValuation`; and `max_gap_used_days` gives the stalest level used, so
the comparison can be audited.

**Currency.** The index currency must equal the fund currency. There is no FX conversion:
converting either side needs an exchange-rate series and a hedging assumption, and both
change the answer.

**Scale.** Only ratios of index levels `I_T / I_t` enter any formula, so rebasing an index
(multiplying every level by a constant) changes nothing.

## Metrics

Notation:
- `C_t` and `D_t` are the contributions and distributions dated `t`.
- `T = as_of`, and `NAV_T` is the residual value at `T`.
- `I_t` is the index level used for date `t`.
- `PI = sum C_t` (paid-in) and `D = sum D_t`.
- `FV(C) = sum_t C_t · I_T / I_t` and `FV(D) = sum_t D_t · I_T / I_t` are the flows
  carried forward to `T` at the index's growth. Each flow's valuation is reported row by
  row (`FlowValuation`).

### Multiples: DPI, RVPI, TVPI

```
DPI  = D / PI
RVPI = NAV_T / PI
TVPI = (D + NAV_T) / PI  = DPI + RVPI
```

`PI == 0` makes all three `None`. A missing residual makes RVPI and TVPI `None` and leaves
DPI. `identity_residual = TVPI − (DPI + RVPI)` is reported and is zero up to rounding.
Multiples ignore timing entirely: a 2.0x TVPI over three years and one over fifteen are the
same number.

### IRR

The IRR is a rate `r > −1` that sets the NPV of the netted series to zero:

```
sum_i a_i (1 + r)^{-t_i} = 0,    t_i = year_fraction(t0, d_i)
```

`a_i` are the per-date signed nets, including `+NAV_T` at `T`. Under `ACT/365F` this is the
equation in Microsoft's `XIRR` documentation ([S7.1](pme-sources.md#s7)). The rate is annual
effective. `IrrResult.irr` is set **only** when the root is proven unique. Otherwise it is
`None` and every root found is listed in `roots`
(see [root policy](#certified-irr-root-policy)).

An IRR is money-weighted. It depends on the size and timing of flows the manager
controlled, and on a terminal NAV that is an appraisal. A subscription line raises it by
delaying calls, without raising the multiple ([S11.2](pme-sources.md#s11)).

### KS-PME (Kaplan–Schoar)

```
KS-PME = (FV(D) + NAV_T) / FV(C)
```

This is the ratio of what the fund returned to what the same contributions would have
grown to in the index, both measured at `T`.

**Source.** Kaplan and Schoar define the PME as index-discounted distributions over
index-discounted contributions ([S1.1](pme-sources.md#s1)). They apply it to largely
liquidated funds and use no NAV ([S1.2](pme-sources.md#s1)). The residual value enters as
a terminal distribution following Harris, Jenkinson and Kaplan ([S1.4](pme-sources.md#s1)).
Multiplying numerator and denominator by `I_T / I_0` turns the discounted form into the
forward-valued form above, so the two are the same number
([D2](pme-sources.md#derivations)).

- `KS-PME > 1`: the LP ended with more than an index investor who put the same cash in on
  the same dates.
- It is a wealth ratio over the whole life, not a rate: `1.2` over four years and `1.2`
  over twelve are not comparable in annual terms. Direct Alpha converts it to a rate.
- **What it assumes about risk.** Kaplan and Schoar note that with a beta above one the PME
  overstates the risk-adjusted return ([S1.5](pme-sources.md#s1)). Sorensen and Jagannathan
  show that the PME is the valuation of an investor with log utility whose wealth earns
  the market return; under that assumption no beta needs to be estimated
  ([S2.1, S2.2](pme-sources.md#s2)). Korteweg and Nagel identify the restriction this
  imposes (the equity premium equals the variance of the market return) and relax it in
  their generalized PME ([S2.4](pme-sources.md#s2)). The limitation is the assumed investor,
  and the index should approximate that investor's wealth portfolio.

### Direct Alpha (Gredil, Griffiths & Stucke)

`a` is the IRR of the **compounded** series, netted per date:

```
{ −C_t · I_T/I_t at t,   +D_t · I_T/I_t at t,   +NAV_T at T }
alpha_annual_effective = a
alpha_continuous       = ln(1 + a)
```

The source defines `a = IRR(FV(C), FV(D), NAV_PE)` and `α = ln(1 + a)/Δ`, with `Δ` "the
time interval for which alpha is computed (typically one year)". Here `a` is already
annual because the day count is in years, so `Δ = 1` ([S3.3, S3.4](pme-sources.md#s3)).
The IRR is solved with `ovf.pme.irr.xirr`, so it has the same day count and root policy as
the fund IRR. Both alphas are `None` unless the status is `"unique"`, and the full
`IrrResult` is attached either way.

**Interpretation.** Multiply the defining equation by `I_0 / I_T`, and the discount factor
for a flow at `t` becomes `1 / [(I_t / I_0) · (1 + a)^{t}]`. Direct Alpha is the constant
annual rate that, earned on top of the index's realised path, prices the fund's flows
exactly. In continuous terms, the fund earned the index's log return plus
`alpha_continuous` per year ([D3](pme-sources.md#derivations)).

`a = 0` is a root of the compounded series exactly when KS-PME is one
([S3.6](pme-sources.md#s3)). Direct Alpha is *reported* as 0 only when that root is also
the unique one: nets `−100, +230, −130` at a constant index give KS-PME = 1, but the
compounded series has the roots 0 and 30%, so `alpha_annual_effective` is `None`. Per-date
netting of the compounded series keeps each date's sign, because `I_T / I_d > 0` multiplies
the whole net `D_d − C_d` ([D7](pme-sources.md#derivations)). The compounded series
therefore has the fund series' sign pattern and root-count bound.

### PME+ (Rouvinez)

```
s = (FV(C) − NAV_T) / FV(D)                  (None when FV(D) == 0)
PME+ IRR = IRR of { −C_t,  +s · D_t,  +NAV_T at T }
```

An index investor makes the fund's contributions and withdraws `s` times each
distribution. `s` is chosen so that the index position ends at exactly `NAV_T`: its final
value is `FV(C) − s · FV(D) = NAV_T` ([S4.3, S4.4](pme-sources.md#s4)). The PME+ IRR is the
IRR of that index strategy. The spread `IRR_fund − IRR_PME+` is reported when both IRRs are
unique. The identity residual `FV(C) − s · FV(D) − NAV_T` is reported and is zero up to
rounding.

- **No distributions:** `s` is `None`. PME+ "cannot be calculated, by definition" for a
  fund with no distributions ([S4.5](pme-sources.md#s4)).
- **Negative `s`:** flagged. It happens when `NAV_T > FV(C)`, and "turn[s] distributions
  into additional contributions" ([S4.5](pme-sources.md#s4)). The IRR is still computed, but
  its sign pattern and meaning have changed.
- **Not a strategy:** `s` uses the final NAV to rescale every earlier distribution, so PME+
  is not a strategy a real investor could have followed ([S4.5](pme-sources.md#s4)).
- **Identity:** `NAV_T = 0` gives `KS-PME = 1 / s`.

The method was the subject of US patent 7,698,196, which Google Patents lists as
"Expired - Fee Related". That is not a legal conclusion ([S4.6](pme-sources.md#s4)).

### Long–Nickels index comparison method (ICM)

An index position `V` buys index with every contribution and sells index with every
distribution, date by date in order:

```
V_d = V_prev · I_d / I_prev + C_d − D_d,     rolled to T
V_T = FV(C) − FV(D)                           (closed form)
ICM IRR = IRR of { −C_t,  +D_t,  +V_T at T }
```

Long and Nickels state the method as a numbered procedure in prose, with no equations
([S5.2, S5.4](pme-sources.md#s5)). The formulas above are the standard reconstruction
([S5.6](pme-sources.md#s5)). Both the recursive and the closed-form value are reported,
with their difference ([D4](pme-sources.md#derivations)). The spread `IRR_fund − IRR_ICM`
is reported when both IRRs are unique.

**The pathology: a short index position.** Large early distributions can sell more index
than the position holds, making `V` negative. Long and Nickels acknowledge this in their
own footnote 5: "frequent large withdrawals from the index result in a net short position
in the index comparison" ([S5.3](pme-sources.md#s5)). They read a negative final value as
outperformance "in every case" ([S5.5](pme-sources.md#s5)). The result reports
`went_short`, the first date on which `V_d` falls below the float rounding bound
`−8·n·ε·G_d` (`G_d` the gross flows grown to `d`; see
[numerical conventions](#numerical-conventions)), and the minimum position. A position of
`−7e-15` that exact arithmetic makes zero is not a short; a position of `−1` on `2e12` of
flows is.

The published Gredil–Griffiths–Stucke illustration (2014 draft, Exhibits 5–6; fixture
PME-F12) exhibits both pathologies itself: its index position goes short on 2007-12-31
(−22.87) and stays short, and its ICM series has two IRR roots, −27.26% and +5.97%. The
paper displays only the positive one (6.0%). This module reports status `"multiple"` and no
spread; that the published figure silently picks one root was found while building this
module and re-derived independently with exact arithmetic.

A negative `V_T` also changes the sign pattern of the ICM series, so its IRR can be
`"none"` or `"multiple"` even when the fund's IRR is unique. Gredil et al. report that in
about 5–10% of cases the ICM series prevents an IRR from being computed
([S5.7](pme-sources.md#s5)). The root policy reports the status rather than choosing a
root.

### mPME (a labelled reconstruction of Cambridge Associates' method)

```
X_t          = NAV_mPME,prev · I_t / I_prev + C_t        (NAV_mPME starts at 0)
w_t          = D_t / (D_t + NAV_t)                        (0 when D_t = 0)
Dist_mPME,t  = w_t · X_t
NAV_mPME,t   = NAV_t / (D_t + NAV_t) · X_t                (w_t = 1 leaves exactly 0)
mPME IRR     = IRR of { −C_t,  +Dist_mPME,t,  +NAV_mPME,T at T }
```

The index position buys with every call and, on each distribution date, sells the fraction
of itself that the fund paid out of its own value (`NAV_t` is end of day, so `D_t + NAV_t`
is the fund's value just before the distribution). Cambridge Associates describe the method
only in prose ([S6.2](pme-sources.md#s6)); no CA document with the algebra was found
([S6.1](pme-sources.md#s6)). The algebra follows Gredil et al.'s 2014 eq. (9), with their
eq. (11) read with the period index throughout — as printed it mixes the period and
terminal indices ([S6.3](pme-sources.md#s6)) — and agrees with the secondary
[S6.5](pme-sources.md#s6). It is a **reconstruction**: CA's dating conventions (which NAV,
any quarterly aggregation) are unpublished, so vendor mPME figures may differ, and no
equivalence is claimed.

- **Input.** Unlike the other methods, the mPME needs the fund's NAV on every distribution
  date: a `FundNavHistory` and a required `interim_nav` policy — `"refuse"` (an observation
  on every distribution date) or `"roll_forward_cash_adjusted"` with `max_nav_gap_days`
  (zero return from the latest earlier observation). A distribution on `as_of` uses the
  residual value from `resolve`, so there is one `NAV_T`, never two.
- **Never short.** `w_t ∈ [0, 1]` and `X_t ≥ 0` by induction, so the benchmark position
  never goes negative, in exact arithmetic and in floating point. This is the property CA
  claim for the method and the ICM pathology it removes. The proof is in the module
  docstring and is a property test.
- **Risk.** The benchmark's own distributions depend on the manager's interim marks, so
  smoothed or strategic NAVs ([S11.1](pme-sources.md#s11)) enter the benchmark itself,
  and results depend on NAV frequency and any roll-forward. Every NAV used is reported per
  step (`MpmeStep`) with its source and observation date.
- **Identity.** A fund whose interim NAVs equal the index-held value of its own flows gives
  `Dist_mPME,t = D_t`, `NAV_mPME,T = NAV_T` and an mPME IRR equal to the fund IRR.

### Identities

These hold by algebra and are tested ([D5](pme-sources.md#derivations)):

| Condition | Consequence |
|---|---|
| Constant index (`I_t` the same for every date) | KS-PME = TVPI; Direct Alpha = fund IRR |
| The fund exactly tracks the index (`NAV_T = FV(C) − FV(D)`) | KS-PME = 1, Direct Alpha = 0, `s = 1`, `V_T = NAV_T` |
| `NAV_T = 0` | KS-PME = `1 / s` |
| Exactly one sign change in the per-date nets **and** the first net negative | KS-PME > 1 ⇔ Direct Alpha > 0 |
| Index multiplied by a constant | nothing changes |
| All flows and NAV multiplied by `k > 0` | no ratio or rate changes |

The sign equivalence needs both conditions. Take nets `{+50 at year 0, −100 at year 1}`
with a constant index. KS-PME is `0.5`, but the IRR, and so Direct Alpha, is `+100%`. With
distributions before contributions the series is a loan to the LP, and a higher rate is
worse for the LP.

## Certified IRR root policy

The IRR equation can have no real root, one, or several, yet a spreadsheet function
returns one number regardless. This module **never picks a root**. It finds every real
root and proves the list complete, or says it cannot.

**Statuses** (`IrrResult.status`):

| Status | Meaning | `irr` | `complete` |
|---|---|---|---|
| `"none"` | proven: no real root | `None` | `True` |
| `"unique"` | proven: exactly one real root | the root | `True` |
| `"multiple"` | proven: two or more roots, all listed | `None` | `True` |
| `"undetermined"` | the root count is proven, but a root failed its residual verification | `None` | `True` |
| `"undetermined"` | a tangent (double) root, a near-tangent critical point in a derivative level, a failed root-bound check or degenerate arithmetic stopped the isolation | `None` | `False` |

The result also carries:
- `proof`: why the status holds, in words;
- `root_bound`: the rate interval outside which no root can exist;
- `sign_changes`: the count `V` defined below.

**The argument, in plain words.** Write `delta = ln(1 + r)`, so that `r ∈ (−1, ∞)` becomes
the whole real line and the NPV becomes an exponential sum
`f(delta) = sum_i a_i · exp(−delta · t_i)`.

1. **Descartes' rule of signs** holds for sums of exponentials with arbitrary distinct real
   exponents, not only for polynomials. The number of real roots, counted with
   multiplicity, is at most `V`, the number of sign changes in the nets taken in date order
   (Jameson 2006, Theorem 3.1; [S8.1](pme-sources.md#s8)). This is why same-date amounts
   are netted (the exponents must be distinct) and zero nets dropped.
2. **Parity.** As `delta → +∞` the earliest term dominates, so `f` takes the sign of the
   first net. As `delta → −∞` the latest term dominates, so `f` takes the sign of the last
   net. `f` crosses zero an odd number of times exactly when those two signs differ, which
   is exactly when `V` is odd. So `V` minus the root count is even (Jameson 2006,
   Proposition 3.6, which uses this argument; [S8.2](pme-sources.md#s8),
   [D6](pme-sources.md#derivations)).
3. Hence `V = 0` means no root, and `V = 1` means **exactly one** root: at most one, and an
   odd number. A conventional fund (contributions, then distributions and NAV) has `V = 1`
   and a proven unique IRR.
4. **`V ≥ 2`.** The count may be `0, 2, 4, …` or `1, 3, …`. Between two roots of `f` lies a
   root of its derivative (**Rolle**). The derivative is again an exponential sum, so the
   same method finds its roots. Between consecutive critical points `f` is monotone and
   holds at most one root. Outside a computable interval one term outweighs all the others
   combined, so no root lies there. Every candidate is refined, and its NPV is checked
   against `1e-10` times the backward-error scale `max(sum|a_i|, sum|a_i|·(1+r)^{-t_i})`;
   the ratio is reported as `IrrRoot.relative_residual` (see
   [numerical conventions](#numerical-conventions)).
5. **Tangent roots.** A critical point where `f` touches zero without changing sign is a
   tangent (double) root. Floating point cannot tell a double root from a near miss, so the
   status is `"undetermined"` and the point is listed with `kind="tangent"`.

**Two examples** ([D8](pme-sources.md#derivations)). The dates are 2021-01-01, 2022-01-01
and 2023-01-01: exactly 1 and 2 years apart under `ACT/365F`, because neither 2021 nor 2022
is a leap year.

| Nets | `V` | Roots | Status |
|---|---|---|---|
| `−100, +230, −132` | 2 | 10% and 20% (`1+r` = 1.1 and 1.2 solve `−100x² + 230x − 132 = 0`) | `"multiple"` |
| `−100, +150, −60` | 2 | none: `−100x² + 150x − 60` has a negative discriminant, so the NPV is negative at every rate | `"none"` |

**Other uniqueness rules.** Norstrom (1972) gives a sufficient condition, based on the
cumulative cash flows, for a unique *nonnegative* IRR ([S8.5](pme-sources.md#s8)). That
tests a sufficient condition; it does not count roots in general. Hazen (2003) is cited for
the view that multiple IRRs are not a defect: each is a return on a different underlying
investment stream. This project has not read that paper
([S8.6](pme-sources.md#s8), `UNVERIFIED`). Either way, the module reports `"multiple"` and
does not resolve it.

**Why Excel's `XIRR` can disagree.** Microsoft documents `XIRR` as an iteration that starts
from a guess (10% by default) and runs until the result is accurate to within 0.000001
percent, returning `#NUM!` if nothing works after 100 tries ([S7.2, S7.3](pme-sources.md#s7)).
It returns one number and says nothing about other roots. So:

- **Several roots.** A guess-driven iteration can return either root in the first example.
  Which one depends on the guess, and neither is "the" IRR.
- **No root.** `#NUM!` is the only possible outcome. But a `#NUM!` does not prove there is
  no root: the iteration can also fail from a poor guess on a series that has one.
- **One root.** `XIRR` and this module agree to within their tolerances, provided `XIRR`
  converges.

To compare with a spreadsheet, use `ACT/365F`, the same netted series and a status of
`"unique"`.

## Numerical conventions

Inputs are binary floats. The module does not pretend they are exact decimals, and it does
not let float noise pass for a property of the fund. Each rule below is stated in the
result that applied it.

| Rule | What it does | Where it shows |
|---|---|---|
| **Exact netting, generic layer** | `net_by_date`, `npv`, `npv_at_log_rate` and `xirr` on caller-supplied `DatedAmount`s net same-date amounts exactly (`math.fsum`, correctly rounded). A date whose net is exactly zero is dropped. `npv` and `xirr` therefore agree on the same amounts. | `IrrResult.assumptions` |
| **Stated legs within representation noise** | Where stated fund flows become a series (`resolve`, and the series the PME methods build from stated flows), a date with two or more legs of mixed sign whose net is within `ε·Σ|legs|` is treated as zero. Each leg's binary representation error is at most `ε/2·|leg|`, so such a net cannot be told apart from an exact decimal zero: `+300,000.30 −100,000.10 −200,000.20` nets to `−2.9e-11` in binary. A net above the bound is kept, however small (`0.001` on `1e12` legs stays). | `netted_to_zero`; `ResolvedCashFlows.stated_nets_within_noise` (`NearZeroNet`: date, raw net, gross legs, bound); an assumption line; the report flag `STATED_NET_WITHIN_REPRESENTATION_NOISE` |
| **Computed nets within rounding** | ICM, PME+ and mPME series contain computed amounts (`V_T`, `s·D_t`, mPME distributions). A computed net within `8·n·ε·G` (`n` the dated steps that produced it, `G` the gross magnitude of its terms) is dropped: exact arithmetic makes it zero, and keeping it would add a false sign change and a false root. | `dropped_computed_nets` on the PME+, ICM and mPME results (`NearZeroNet`); an assumption line; the report flag `COMPUTED_NET_DROPPED` (derived from the records, never from text) |
| **Short index position** | `went_short` needs `V_d < −8·n·ε·G_d`. `−7e-15` from cancellation is not a short; `−1` on `2e12` of flows is. | `went_short`, `first_short_date`, raw `min_position` |
| **Growth first** | Every future value is `amount · (I_T / I_t)`: the ratio is formed first, so tiny or huge index levels cannot underflow or overflow an intermediate product. Subnormal index levels are refused; a growth ratio or future value outside the float range raises `ValueError`. | refusal message |
| **IRR residual** | A root passes when `|NPV(root)|` is within `1e-10` of the backward-error scale `max(Σ|a_i|, Σ|a_i|·(1+r)^{−t_i})`. At negative rates the discounted terms exceed the undiscounted ones and cancel, so the undiscounted scale alone would fail proven roots of near-total-loss funds. | `IrrRoot.relative_residual`; `npv_residual` (currency units at `t0`, `None` when not representable) |
| **Rate representability** | A root whose `1 + r` underflows (a written-off fund, `ln(1+r)` below about −37) is reported as `rate = −1.0` with `rate_clamped = True` and its exact `log_rate`; check it with `npv_at_log_rate`, and compare such funds with `log_spread`, not `spread`. A root with `ln(1+r) > 709.78` (an annual rate above ~1.8e308) cannot be reported and raises `ValueError`; PME+ and ICM then carry `fund_irr = None` with the reason and report everything else. | `IrrRoot.rate_clamped`, `log_rate`; `log_spread` |
| **Overflow** | A sum or ratio that overflows raises `ValueError` naming the quantity. Multiples and KS-PME divide term by term when only an intermediate sum overflows, so a representable answer is still returned. | refusal message or assumption line |
| **Hashing and immutability** | `input_hash` is sha256 of canonical JSON with a `"method"` key, dates as ISO text and `−0.0` normalised to `0.0`. Models are frozen; the `assumptions` list is not deep-frozen (house convention). | `input_hash` |

**How far the IRR certificate reaches.** The Descartes/Rolle argument is exact; the signs it
relies on are float evaluations, trusted only where they exceed an a-priori rounding
estimate (not interval arithmetic). Where the estimate cannot decide a sign, the status is
`"undetermined"` — never a wrong `complete=True`. An independent reviewer's attack
(341 polynomial families with exact Sturm counts, coefficients from `1e-300` to `1e301`)
found no wrong certified count after the log-space rewrite. The cost grows with the number
of sign changes `V` (one derivative level per sign change): a conventional 10,000-date fund
solves in about 0.1 s, a 200-date alternating series is decided in about 0.2 s, and a
1,000-date alternating series is conservatively `"undetermined"` after several seconds.

## Practice standards

This section states only what the ledger records as read ([S10](pme-sources.md#s10)). The
module helps compute the figures below; it does not certify compliance with either
standard.

- **GIPS 2020.** A firm may present money-weighted returns only when it controls external
  cash flows and the fund is closed-end, fixed-life, fixed-commitment or holds illiquid
  investments as a significant part of its strategy (1.A.35). Money-weighted returns are
  since inception and use daily external cash flows from 1 January 2020 (2.A.29 and
  footnote 17). A composite's since-inception money-weighted return must be shown with and
  without a subscription line, subject to stated exemptions (5.A.2). A PME is optional; a
  firm that presents one must disclose the index (5.C.33).
- **Two meanings of "PME".** GIPS defines "public market equivalent" as the performance of
  an index "expressed in terms of a money-weighted return (MWR), using the same cash flows
  and timing". That is a **rate**, like the ICM or PME+ IRR here, not the KS-PME ratio.
  Name the method whenever a PME is reported.
- **ILPA Performance Template (January 2025).** Its methodology asks for since-inception
  measures "based on cash flows between the Fund and its investors": net IRR and TVPI with
  and without the impact of fund-level subscription facilities, with gross figures
  optional. The methodology documents read do not say "daily" and do not mention PME
  ([S10.2, S10.3](pme-sources.md#s10)). ILPA Principles 3.0 (2019) calls disclosure of net
  IRR "on both a levered and unlevered basis" best practice.
- **Subscription lines.** ILPA states that "There is no universal agreed-upon approach for
  calculating returns with and without the impact of subscription lines"
  ([S11.6](pme-sources.md#s11)). This module does not choose one (see
  [not modelled](#not-modelled)).

## Not modelled

| Not modelled | Why it matters |
|---|---|
| **Cambridge Associates' own mPME figures** | The mPME here is a labelled reconstruction (see [mPME](#mpme-a-labelled-reconstruction-of-cambridge-associates-method)). CA's dating conventions — which NAV, any quarterly aggregation of flows — are unpublished ([S6.1, S6.2](pme-sources.md#s6)), so reproducing a vendor mPME is not claimed. |
| **Korteweg–Nagel generalized PME (GPME)** | It estimates a stochastic discount factor from a cross-section of funds. It is an econometric estimator, not a function of one fund's flows ([S2.4](pme-sources.md#s2)). |
| **Takahashi–Alexander projections** | A forecast of future calls, distributions and NAV ([S12.1](pme-sources.md#s12)). Performance measurement here uses only realised flows and a stated NAV. |
| **Fund carry and the GP waterfall** | Reconstructing gross from net needs the LPA's terms. Supply `net_lp` flows for the LP's outcome. |
| **Subscription-line reconstruction** | A credit facility delays capital calls and raises the IRR, while multiples slightly decline ([S11.2](pme-sources.md#s11); a 2019 preliminary working-paper figure, [S11.3](pme-sources.md#s11)). Undoing it needs the drawdown, repayment, interest, fee and investment dates. **Net LP flows alone may not identify a unique unlevered history.** The module computes the IRR of the flows supplied and makes no claim about the unlevered one. |
| **Fee reconstruction and fee double counting** | Fees are wherever the caller's flows put them. On `net_lp` they are inside contributions; do not deduct them again. |
| **Recallable distributions** | Multiples, KS-PME and PME+ use gross legs: a distribution re-called on the same or a later date counts in both paid-in and distributed. Netting recallables is a different convention and gives a different TVPI, KS-PME and PME+ (a same-day recall of 300,000.30 moves TVPI from 1.50 to 1.38 in a reviewer's probe). IRR, Direct Alpha and the ICM are linear in per-date nets and do not change. No `recallable` flag or policy exists in `pme-v1`; each affected result says it uses gross legs. |
| **Implicit truncation** | `resolve` refuses flows dated after `as_of`. To measure at a quarter-end NAV with later flows, truncate explicitly with `FundCashFlows.through(d)`, which returns the kept fund and the excluded flows. |
| **FX** | The fund and the index must share a currency. |
| **NAV de-smoothing and NAV quality** | Reported NAVs are appraisals, and managers' valuation choices can be strategic ([S11.1](pme-sources.md#s11)). The NAV is taken as given; no de-smoothing or nowcasting model is applied ([S11.8, S11.9](pme-sources.md#s11)). A stale or biased NAV moves every metric that uses it, most of all early in a fund's life, when NAV is most of TVPI. |
| **Interim valuations beyond the mPME** | KS-PME, Direct Alpha, PME+ and the ICM use only the residual value at `as_of`; the mPME alone takes interim NAVs (`FundNavHistory`), at distribution dates. There are no time-weighted returns, quarterly return series or drawdown statistics. |
| **Vendor aggregation conventions** | Figures from databases built on quarter-aggregated flows, month-end index levels or quarter-end NAVs will not match daily-dated inputs, for every method here. Align the cash-flow dating, the index observation dates and the NAV date before comparing; nothing in a result can reveal an aggregation done before the call. |
| **Risk adjustment beyond the PME's implicit investor** | Every PME here prices the fund with the index as the only risk factor. It is exact only for the log-utility investor holding that index ([S2](pme-sources.md#s2)). |

## References

Bibliographic details and the exact passages read are in [pme-sources](pme-sources.md).

- Albertus, J. F., & Denes, M. (2019). *Distorting private equity performance: The rise of
  fund debt.* Kenan Institute working paper, SSRN 3410076. https://doi.org/10.2139/ssrn.3410076
  (Published as "Private equity fund debt: Agency costs and cash flow management", *JFQA*,
  online 2026, https://doi.org/10.1017/S0022109026102890; not read.)
- Brown, G. W., Gredil, O. R., & Kaplan, S. N. (2019). Do private equity funds manipulate
  reported returns? *Journal of Financial Economics*, 132(2), 267–297.
  https://doi.org/10.1016/j.jfineco.2018.10.011
- Brown, G., Ghysels, E., & Gredil, O. (2023). Nowcasting net asset values.
  *Review of Financial Studies*, 36(3), 945–986. https://doi.org/10.1093/rfs/hhac045
- Cambridge Associates (2025). *US Private Equity Benchmark Book*, Q2 2025, methodology.
- CFA Institute (2019). *2020 GIPS Standards for Firms.*
- Getmansky, M., Lo, A. W., & Makarov, I. (2004). An econometric model of serial correlation
  and illiquidity in hedge fund returns. *Journal of Financial Economics*, 74(3), 529–609.
  https://doi.org/10.1016/j.jfineco.2004.04.001
- Gredil, O. R., Griffiths, B., & Stucke, R. (2023). Benchmarking private equity: The direct
  alpha method. *Journal of Corporate Finance*, 81, 102360.
  https://doi.org/10.1016/j.jcorpfin.2023.102360 (equations cited from the 2014 SSRN draft,
  SSRN 2403521).
- Harris, R. S., Jenkinson, T., & Kaplan, S. N. (2014). Private equity performance: What do
  we know? *Journal of Finance*, 69(5), 1851–1882. https://doi.org/10.1111/jofi.12154
- Hazen, G. B. (2003). A new perspective on multiple internal rates of return. *The
  Engineering Economist*, 48, 31–51. https://doi.org/10.1080/00137910308965050 (not read.)
- ILPA (2017). *Subscription Lines of Credit and Alignment of Interests.* ILPA (2019).
  *Principles 3.0.* ILPA (2020). *Enhancing Transparency Around Subscription Lines of
  Credit.* ILPA (2025). *Performance Template Suggested Guidance: Granular Methodology.*
- ISDA (2006). *2006 ISDA Definitions*, §4.13 and §4.16.
- Jameson, G. J. O. (2006). Counting zeros of generalised polynomials: Descartes' rule of
  signs and Laguerre's extensions. *Mathematical Gazette*, 90(518), 223–234.
- Kaplan, S. N., & Schoar, A. (2005). Private equity performance: Returns, persistence, and
  capital flows. *Journal of Finance*, 60(4), 1791–1823.
  https://doi.org/10.1111/j.1540-6261.2005.00780.x
- Korteweg, A., & Nagel, S. (2016). Risk-adjusting the returns to venture capital.
  *Journal of Finance*, 71(3), 1437–1470. https://doi.org/10.1111/jofi.12390
- LibreOffice Help. *XIRR.* https://help.libreoffice.org/latest/en-US/text/scalc/01/04060118.html
- Long, A. M., III, & Nickels, C. J. (1996). *A private investment benchmark.* AIMR
  Conference on Venture Capital Investing, 13 February 1996. The University of Texas System.
- Microsoft Support. *XIRR function.*
  https://support.microsoft.com/en-us/office/xirr-function-de1242ec-6477-445b-b11b-a303ad9adc9d
- Norstrom, C. J. (1972). A sufficient condition for a unique nonnegative internal rate of
  return. *Journal of Financial and Quantitative Analysis*, 7(3), 1835–.
  https://doi.org/10.2307/2329806
- Pólya, G., & Szegő, G. *Problems and Theorems in Analysis II*, Part V, ch. 1 (as cited by
  Jameson 2006; not read.)
- Rouvinez, C. (2003). Private equity benchmarking with PME+. *Venture Capital Journal*,
  August, 34–38 (not read; see US Patent 7,698,196 B1).
- Sorensen, M., & Jagannathan, R. (2015). The public market equivalent and private equity
  performance. *Financial Analysts Journal*, 71(4), 43–50.
  https://doi.org/10.2469/faj.v71.n4.4 (read through secondary sources.)
- Takahashi, D., & Alexander, S. (2002). Illiquid alternative asset fund modeling.
  *Journal of Portfolio Management*, 28(2), 90–100 (not checked.)
