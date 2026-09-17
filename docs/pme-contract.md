# open-pme · Wave 1 interface contract (coordinator-owned)

Status 2026-09-15: **design record.** This was the binding interface between the
open-pme workers and it is kept as the record of every decision taken while building the
module: each "amended" note and §11–§12 name the question, the finding that raised it and
the decision. The user-facing semantics are in `docs/pme.md`; where the two differ in
wording, `docs/pme.md` and the code describe the shipped behaviour.

Scope (from `docs/launch-plan.md` §5 and `TODO.md` §6): signed dated flows, TVPI/DPI/RVPI,
an explicit XIRR root policy, KS-PME and Direct Alpha, plus PME+ and Long–Nickels (ICM)
because both are fully determined by the same inputs. Launch gate: documented day count
and benchmark total-return convention, duplicate-date handling, no/multiple IRR roots,
incomplete NAV cases, independent reference fixtures.

**Out of scope for Wave 1** (document, do not implement): Cambridge Associates mPME
(needs an interim NAV series; algebra unpublished — Wave 2 decides after the source
check), Korteweg–Nagel GPME, Takahashi–Alexander forecasting, fund carry / GP waterfall,
subscription-line reconstruction, FX, fees reconstruction, NAV de-smoothing.

## 1. File ownership (absolute)

| Owner | Files (create only these) |
|---|---|
| Coordinator | `src/ovf/pme/__init__.py`, this file, `src/ovf/__init__.py`, `README.md`, `CHANGELOG.md`, `TODO.md`, `docs/fixtures.md`, `docs/limitations.md`, `docs/semantics.md`, `pyproject.toml`, `src/ovf/cli.py`, `src/ovf_mcp/**` |
| W1 flows | `src/ovf/pme/daycount.py`, `src/ovf/pme/flows.py`, `src/ovf/pme/irr.py`, `tests/test_pme_daycount.py`, `tests/test_pme_flows.py`, `tests/test_pme_irr.py` |
| W2 metrics | `src/ovf/pme/benchmark.py`, `src/ovf/pme/metrics.py`, `src/ovf/pme/pme.py`, `tests/test_pme_benchmark.py`, `tests/test_pme_metrics.py`, `tests/test_pme_pme.py` |
| W3 oracle | `tests/pme_oracle.py`, `tests/pme_fixtures.py`, `tests/test_pme_reference.py`, `docs/pme-fixtures.md` |
| W4 sources | `docs/pme.md`, `docs/pme-sources.md` |

Nobody else edits another owner's files. Other agent sessions may be active in this
folder: never run `git checkout`, `git switch`, `git stash`, `git reset`, `git commit` or
any formatter over the whole tree. Run `ruff check` on your own files, or on `src tests`
read-only (no `--fix` outside your files).

Import from submodules (`from ovf.pme.flows import ...`); `ovf.pme.__init__` stays empty
until integration.

## 2. Global conventions

- Style exemplar: `src/ovf/antidilution.py`. Pydantic v2 models inherit
  `ovf.core.types.FinancialBaseModel` with `model_config = ConfigDict(frozen=True)`;
  pure functions; keyword-only arguments; **no default value for any economic or
  convention choice** (day count, NAV policy, lookup policy, basis). Optional metadata
  (e.g. `flow_id`) may default to `None`.
- Every result model carries `assumptions: list[str]`, `input_hash: str` (sha256 of
  canonical JSON, `sort_keys=True`, `allow_nan=False`, dates as ISO strings) and
  `engine_version: str = ENGINE_VERSION`.
- `ENGINE_VERSION = "pme-v1"` is defined once in `ovf.pme.flows`; the other modules import it.
- Immutability (decided 2026-09-15 on R1 finding 6): models are `frozen` — no field can be
  reassigned — but, as everywhere else in `ovf` (e.g. `ConversionPriceAdjustment`), the
  `assumptions` list is not deep-frozen. Kept for consistency with the rest of the package;
  documented rather than silently claimed.
- `canonical_hash` normalises `-0.0` to `0.0` before encoding (R1 finding 7): equal inputs
  hash equally.
- Every `date` field refuses a `datetime` (including midnight and timezone-aware values)
  before coercion (R1 finding 5).
- Dates are `datetime.date`. No `datetime`, no clock reads, no `date.today()`.
- Sums use `math.fsum`. No NaN/inf ever appears in a result: an undefined ratio is `None`,
  with an assumption line saying why.
- Refusals raise `ValueError` with an actionable message (the MCP adapter treats a
  `ValueError` raised inside `ovf` as a user-facing refusal). No silent truncation,
  interpolation, reordering-with-meaning or guessing.
- Checks: `.venv/bin/pytest tests/test_pme_*.py -q`, `.venv/bin/ruff check <your files>`,
  `.venv/bin/mypy src` (strict: `disallow_untyped_defs`). Line length 100.
- Allowed dependencies: stdlib, pydantic, numpy, scipy (e.g. `scipy.optimize.brentq`).
  Tests may use `hypothesis`.

## 3. Perspective, signs and timing

- Perspective is the **investor (LP) in the fund**. A *contribution* is cash the LP pays
  in (paid-in capital); a *distribution* is cash the LP receives; *NAV* is the LP's
  residual value in the fund at a date.
- Canonical representation is **typed**: a kind plus a strictly positive amount. A zero
  flow is refused (it is not a flow). NAV is `>= 0`.
- Signed form, used for discounting: contribution → `-amount`, distribution → `+amount`,
  residual value → `+value` dated at `as_of`.
- **Same date:** all amounts on one date are netted into one per-date signed amount before
  discounting (NPV is invariant to this). Gross sums are kept for multiples. Per-date nets
  that are exactly zero are dropped from the discounting series and listed.
- **NAV timing:** a NAV dated `d` is end of day — after every flow dated `d`.
- **Basis** is stated, never inferred: `"net_lp"` (LP-level flows, after fees and carry,
  e.g. ILPA/Burgiss style) or `"gross_fund"` (fund-level investment flows before fees and
  carry). It changes no arithmetic; it is carried into every result's assumptions.

## 4. `ovf.pme.daycount` (W1)

```python
DayCountConvention = Literal["ACT/365F", "ACT/365.25", "ACT/ACT-ISDA"]

def year_fraction(start: date, end: date, *, convention: DayCountConvention) -> float
```

Signed (negative when `end < start`) and **additive**:
`year_fraction(a, c) == year_fraction(a, b) + year_fraction(b, c)` up to float rounding.
Additivity is why an IRR does not depend on which date is `t0`. `ACT/365F` is the
convention of Excel/LibreOffice `XIRR` (days / 365, `t0` = first date). ACT/ACT-ISDA:
days falling in leap years / 366 + days in non-leap years / 365.

## 5. `ovf.pme.flows` (W1)

```python
ENGINE_VERSION = "pme-v1"
FlowKind = Literal["contribution", "distribution"]
FlowBasis = Literal["net_lp", "gross_fund"]
StaleNavPolicy = Literal["refuse", "roll_forward_cash_adjusted"]

class CashFlow(FinancialBaseModel):          # frozen
    date: date
    kind: FlowKind
    amount: float                            # Field(gt=0)
    flow_id: str | None = None               # metadata; duplicate non-None ids refused

class NavObservation(FinancialBaseModel):    # frozen
    date: date
    value: Money                             # >= 0

class DatedAmount(FinancialBaseModel):       # frozen; signed, finite
    date: date
    amount: float

class FundCashFlows(FinancialBaseModel):     # frozen
    name: str                                # min_length=1
    currency: str                            # min_length=1, e.g. "USD"
    basis: FlowBasis
    flows: tuple[CashFlow, ...]              # at least one flow
    nav: NavObservation | None               # None: no residual valuation available
    # validator: refuse duplicate non-None flow_ids; store flows in canonical order
    # (date, kind with contribution first, amount, flow_id) so input_hash is order-free.

class NavRollForward(FinancialBaseModel):    # frozen
    reported_date: date
    reported_value: float
    contributions_after: float               # dated strictly after reported_date, <= as_of
    distributions_after: float
    rolled_value: float                      # reported + contributions_after - distributions_after

class ResolvedCashFlows(FinancialBaseModel): # frozen; the ONLY input every metric consumes
    fund_name: str
    currency: str
    basis: FlowBasis
    as_of: date
    flows: tuple[CashFlow, ...]              # canonical order, all dated <= as_of
    paid_in: float                           # fsum of contributions
    distributed: float                       # fsum of distributions
    residual_value: float | None             # value at as_of; None when nav is None
    nav_source: Literal["reported_at_as_of", "rolled_forward", "none"]
    nav_roll_forward: NavRollForward | None
    net_by_date: tuple[DatedAmount, ...]     # per-date signed nets, residual added at as_of,
                                             # zero nets dropped, ascending dates
    netted_to_zero: tuple[date, ...]         # dates whose net was exactly zero
    assumptions: list[str]
    input_hash: str
    engine_version: str

def resolve(fund: FundCashFlows, *, as_of: date, stale_nav: StaleNavPolicy) -> ResolvedCashFlows
```

Rules for `resolve`:

1. A flow dated after `as_of` → `ValueError` (never truncate). `as_of` before the first
   flow → `ValueError`.
2. `nav is None` → `residual_value=None`, `nav_source="none"`. (A fully realised fund must
   say so explicitly with `NavObservation(date=as_of, value=0)`.)
3. `nav.date > as_of` → `ValueError`.
4. `nav.date == as_of` → `nav_source="reported_at_as_of"`, residual = `nav.value`.
5. `nav.date < as_of`:
   - `stale_nav="refuse"` → `ValueError` (the valuation is not at `as_of`).
   - `stale_nav="roll_forward_cash_adjusted"` → residual = NAV + contributions − distributions
     dated in `(nav.date, as_of]`; zero return assumed in between (assumption line). A
     negative rolled value → `ValueError` (distributions after the NAV date exceed it: the
     inputs are inconsistent).
6. `net_by_date` includes the residual at `as_of` when it is not `None` (a zero residual
   adds nothing).

## 6. `ovf.pme.irr` (W1) — certified XIRR root policy

```python
IrrStatus = Literal["unique", "multiple", "none", "undetermined"]

class IrrRoot(FinancialBaseModel):           # frozen
    rate: float                              # annual effective, > -1
    log_rate: float                          # delta = ln(1 + rate)
    npv_residual: float                      # NPV at the root, same currency units
    kind: Literal["crossing", "tangent"]

class IrrResult(FinancialBaseModel):         # frozen
    status: IrrStatus
    irr: float | None                        # set only when status == "unique"
    roots: tuple[IrrRoot, ...]               # every root found, ascending rate
    sign_changes: int                        # sign changes of per-date nets in date order
    complete: bool                           # True iff the root set is PROVEN complete
    proof: str                               # why the status holds, in words
    root_bound: tuple[float, float] | None   # [r_lo, r_hi] outside which no root can exist;
                                             # None when V == 0 or the rate form overflows
    log_root_bound: tuple[float, float] | None  # the same bound in delta; None only if V == 0
    day_count: DayCountConvention
    t0: date                                 # first date of the netted series
    amounts: tuple[DatedAmount, ...]         # the netted series actually solved
    tolerance: float                         # residual tolerance used (relative to sum |a_i|)
    assumptions: list[str]
    input_hash: str
    engine_version: str

def npv(amounts: Sequence[DatedAmount], *, rate: float, day_count: DayCountConvention,
        t0: date) -> float
def xirr(amounts: Sequence[DatedAmount], *, day_count: DayCountConvention) -> IrrResult
def fund_irr(resolved: ResolvedCashFlows, *, day_count: DayCountConvention) -> IrrResult
```

`fund_irr` solves `resolved.net_by_date` and refuses (`ValueError`) when
`residual_value is None`. `xirr` nets same-date inputs itself, drops zero nets, and refuses
an empty or single-date series.

**Root policy — never pick a root.** With `t_i = year_fraction(t0, d_i)` and
`delta = ln(1 + r)`, `f(delta) = sum_i a_i * exp(-delta * t_i)` is an exponential sum over
the whole real line (r ∈ (−1, ∞)). Let `V` = sign changes of `a_i` in date order.

- Descartes' rule for exponential sums: the number of real roots, counted with
  multiplicity, is at most `V` and has the parity of `V` (the limits at ±∞ carry the
  signs of the first and last amounts). Cite the source you rely on in the docstring
  (e.g. Jameson 2006, *Math. Gazette* 90:223–234; Pólya–Szegő Part V) — W4 verifies it.
- `V == 0` → `"none"`, `complete=True`.
- `V == 1` → exactly one root; bracket and refine; `"unique"`, `complete=True`.
- `V >= 2` → isolate every real root by Rolle recursion: the critical points of `f` are
  the roots of `f'` (again an exponential sum), `f` is monotone between consecutive
  critical points, so each such interval holds at most one simple root. Bound the search
  rigorously: beyond a computable `delta_hi` the earliest term dominates the sum of all
  others, and below `delta_lo` the latest term does — no root outside `[delta_lo,
  delta_hi]`; report it as `root_bound` in rates.
- Every root is refined (e.g. `brentq`) and its residual verified against the
  backward-error scale: `|NPV(root)| <= tolerance * max(sum|a_i|, sum|a_i| * (1+r)^(-t_i))`,
  `tolerance = 1e-10` (amended 2026-09-15 on W1's question: for `r < 0` the discounted
  gross magnitude exceeds `sum|a_i|`, and float cancellation alone would fail a proven root
  of a near-total-loss series; for `r >= 0` the check is unchanged). The same scale sets the
  level-0 tangent threshold. A failed verification → `"undetermined"`.
- A critical point where `|f| <= tolerance * sum|a_i|` without a sign change is a
  **tangent** root: list it with `kind="tangent"`, status `"undetermined"`,
  `complete=False` (floating point cannot distinguish a double root from a near miss).
- Otherwise the status follows from the proven root count: 0 → `"none"`, 1 → `"unique"`,
  ≥ 2 → `"multiple"` (all listed, `irr=None`).
- Evaluate `f` in a scaled form (factor out the dominant exponential) so extreme `delta`
  never overflows.
- **Float representability** (decided 2026-09-15 on W1's question): a root with
  `delta > ln(float max) ≈ 709.78` cannot be reported as an annual rate → `ValueError`
  naming `delta`. A root whose `1 + r` underflows (`delta` below about −37) is reported as
  `rate = -1.0` exactly, with the exact `log_rate` and an assumption line (so in float
  `rate >= -1`, mathematically `> -1`). Downstream code that needs a log rate uses
  `log_rate`, never `ln(1 + rate)`. Excel's `XIRR` (Newton from a guess, first root found) is the
  counter-model: document the difference.

## 7. `ovf.pme.benchmark` (W2)

```python
ReturnBasis = Literal["total_return_gross", "total_return_net", "price_return"]
IndexLookup = Literal["exact", "last_on_or_before"]

class IndexLevel(FinancialBaseModel):        # frozen
    date: date
    level: float                             # Field(gt=0)

class BenchmarkIndex(FinancialBaseModel):    # frozen
    name: str                                # min_length=1
    currency: str                            # must equal the fund currency (no FX)
    return_basis: ReturnBasis
    levels: tuple[IndexLevel, ...]           # >= 1; duplicate dates refused; stored ascending

class IndexLookupRecord(FinancialBaseModel): # frozen
    requested: date
    used: date
    level: float
    gap_days: int

def index_level(benchmark: BenchmarkIndex, on: date, *, lookup: IndexLookup,
                max_gap_days: int) -> IndexLookupRecord
```

`"exact"` requires a level dated `on` (and `max_gap_days == 0`). `"last_on_or_before"`
uses the latest level dated `<= on` with `(on - used).days <= max_gap_days`. Never look
forward, never interpolate; failure → `ValueError` naming the date. A `price_return`
basis is allowed but adds an assumption line: it omits dividends, so every PME against it
overstates relative performance.

## 8. `ovf.pme.metrics` (W2)

```python
class Multiples(FinancialBaseModel):         # frozen
    as_of: date
    paid_in: float
    distributed: float
    residual_value: float | None
    nav_source: str
    dpi: float | None                        # distributed / paid_in
    rvpi: float | None                       # residual / paid_in
    tvpi: float | None                       # (distributed + residual) / paid_in
    identity_residual: float | None          # tvpi - (dpi + rvpi), must be ~0
    assumptions: list[str]
    input_hash: str
    engine_version: str

def multiples(resolved: ResolvedCashFlows) -> Multiples
```

`paid_in == 0` → all three `None`. `residual_value is None` → `rvpi` and `tvpi` `None`,
`dpi` still reported.

## 9. `ovf.pme.pme` (W2)

Every function takes `(resolved, benchmark, *, lookup, max_gap_days)`, plus
`day_count` where an IRR is solved. All require `residual_value is not None` and
`paid_in > 0` (else `ValueError`), matching currencies, and an index level at every flow
date and at `as_of`. `T = as_of`, `I_t` = index level used for date `t`.

```python
class FlowValuation(FinancialBaseModel):     # frozen; one row per flow, canonical order
    date: date
    kind: FlowKind
    amount: float
    index_date: date
    index_level: float
    growth_to_as_of: float                   # I_T / I_t
    future_value: float                      # amount * I_T / I_t

def ks_pme(...) -> KsPmeResult
def direct_alpha(..., day_count) -> DirectAlphaResult
def pme_plus(..., day_count) -> PmePlusResult
def ln_pme(..., day_count) -> LnPmeResult
```

Formulas (the oracle implements these independently from this text):

- `FV(C) = sum_t C_t * I_T / I_t`, `FV(D) = sum_t D_t * I_T / I_t`, `NAV_T = residual_value`.
- **KS-PME** (Kaplan & Schoar 2005, who used largely liquidated funds and no NAV; the
  residual value enters as a terminal distribution following Harris, Jenkinson & Kaplan
  2014, JF 69(5)): `(FV(D) + NAV_T) / FV(C)`. *[Amended 2026-09-15 after W4 source check.]*
- **Direct Alpha** (Gredil, Griffiths & Stucke): `a` = IRR of the compounded series
  `{-C_t * I_T/I_t at t, +D_t * I_T/I_t at t, +NAV_T at T}` (netted per date) solved with
  `ovf.pme.irr.xirr`; report `alpha_annual_effective = a` and
  `alpha_continuous = ln(1 + a)`; both `None` unless the IRR status is `"unique"`, and the
  full `IrrResult` is attached either way.
- **PME+** (Rouvinez 2003, *Venture Capital Journal*, Aug 2003, pp. 34–38 — not PEI;
  corrected after W4): scale `s = (FV(C) - NAV_T) / FV(D)`; `FV(D) == 0` → `s = None`
  (nothing to scale). PME+ IRR solves `{-C_t, +s * D_t, +NAV_T at T}`; report the fund IRR
  and the spread (fund − PME+) when both are unique; flag `s < 0`; report the identity
  residual `FV(C) - s * FV(D) - NAV_T`.
- **Long–Nickels ICM**: index position `V` updated per date in order:
  `V_d = V_prev * I_d / I_prev + C_d - D_d`, rolled to `T`; must equal the closed form
  `FV(C) - FV(D)` (report both and their difference). ICM IRR solves
  `{-C_t, +D_t, +V_T at T}`; report the spread `IRR_fund - IRR_ICM` when both are unique;
  report `went_short` (any `V_d < 0`), the first such date and the minimum position,
  because a short index position is the method's documented pathology (Long & Nickels
  1996, fn. 5).

**Computed nets within rounding of zero** (decided 2026-09-15 on W2's question). The ICM
and PME+ series contain computed amounts (`V_T`, `s * D_t`). A computed per-date net with
`|net| <= TOLERANCE * G`, where `G` is the gross magnitude of the terms that produced it
(ICM terminal: the gross flows grown to `T`; PME+: `C_t + |s| D_t (+ NAV_T)`) and
`TOLERANCE = ovf.pme.irr.TOLERANCE = 1e-10`, is dropped from that series as "within rounding
of zero": the raw value is still reported, and an assumption line names the date, the raw
value and the scale. **Re-amended 2026-09-15 after R1:** `TOLERANCE * G` is far above the
actual float noise and hid a genuine short position (`V = -1` with `G = 2e12`). The threshold
for both the dropped computed nets and `went_short` is a float **rounding bound**
`8 * n * eps * G` (`eps` = machine epsilon, `n` = the number of dated steps/terms that
produced the value), which covers cancellation noise (observed ≈ 1.6·eps·G) and nothing
larger. FV products are computed as `amount * (I_T / I_t)`; subnormal index levels are refused. Otherwise float cancellation noise (e.g. `V_T = -7.1e-15` where exact
arithmetic gives 0) adds a false sign change and a false root, and index rescaling — which
must change nothing — would change the IRR status. Stated fund nets and the Direct Alpha
series keep the exact-zero rule of §3.

Identities that must hold and be tested: constant index ⇒ KS-PME = TVPI and Direct Alpha
= fund IRR; a fund whose distributions exactly replicate the index ⇒ KS-PME = 1,
Direct Alpha = 0, s = 1, V_T = NAV_T; `NAV_T = 0` ⇒ KS-PME = 1/s; for a conventional
series — exactly one sign change in the per-date nets **and the first net amount
negative** — KS-PME > 1 ⇔ Direct Alpha > 0 (without the second condition it fails: nets
+50 then −100 under a constant index give KS-PME = 0.5 but Direct Alpha = +100%; amended
2026-09-15 after W4); rescaling the index by a constant changes nothing; rescaling all flows and NAV by k > 0 changes no ratio or rate.

## 10. Cross-worker protocol

- W1 publishes `daycount.py` and `flows.py` first (models + `resolve`), then `irr.py`;
  send a `status` message to the Run when each is importable so the coordinator can relay.
- W2 codes against §5–§6 immediately; until W1's modules exist, stub nothing inside
  W1's files — use them once importable.
- W3 writes the oracle and fixtures **from §3–§9 and primary sources only**; it must not
  open `src/ovf/pme/*.py` until `tests/pme_oracle.py` and `tests/pme_fixtures.py` are
  complete. Only then does it wire `tests/test_pme_reference.py` to the public API.
- W4's source check can change a formula or a convention. It reports that to the
  coordinator immediately with the source and page; the coordinator decides and relays.

## 11. Amendments from the Wave 2 reviews (R1, R2), decided 2026-09-15

1. **Never refuse a representable root (R2-1).** A root's residual is verified on the
   scaled axis. `IrrRoot` gains `relative_residual: float` (`|NPV(root)|` divided by the
   §6 backward-error scale; always finite; the verification is `relative_residual <=
   TOLERANCE`) and `rate_clamped: bool` (`True` when `1 + r` underflowed and `rate` reads
   `-1.0`). `npv_residual` becomes `float | None`: `None` when the NPV at the root is not
   representable in currency units at `t0`. The only representability refusal left is a
   root with `delta > ln(float max)` (§6). `ovf.pme.irr.npv_at_log_rate(amounts, *,
   log_rate, day_count, t0)` evaluates the NPV at any `delta`, including clamped roots.
2. **A fund-IRR refusal does not abort PME+ or ICM (R2-1).** `PmePlusResult.fund_irr` and
   `LnPmeResult.fund_irr` become `IrrResult | None`; a `ValueError` from the fund IRR is
   carried as `None` with the reason in `assumptions`, and every figure that does not need
   the fund IRR (`s`, `V_T`, the path, `went_short`, the method's own IRR) is still reported.
3. **Stated nets within decimal-representation noise (R2-3).** Cents stated as binary
   floats rarely cancel exactly (`300000.30 - 100000.10 - 200000.20 = -2.9e-11`). A per-date
   net of `n >= 2` stated legs of mixed sign with `|net| <= eps * sum|legs|` (each leg's
   binary representation error is at most `eps/2 * |leg|`) is treated as zero: dropped,
   listed in `netted_to_zero`, and its raw value named in an assumption line. A net above
   that bound is kept, however small. Computed nets keep the §9 bound `8 * n * eps * G`.
   *Scope (decided on F4's question):* the rule applies where **stated fund flows** become
   a series — `resolve` and the series `ovf.pme.pme` / `ovf.pme.mpme` build from stated
   flows. The generic numeric layer (`net_by_date`, `npv`, `npv_at_log_rate`, `xirr` on
   caller-supplied `DatedAmount`s) nets **exactly**: its caller controls the inputs, and
   `npv` and `xirr` must agree with each other on the same amounts.
4. **PME+ spread at `s < 0` (R2-5).** `spread` is `None` when `s < 0`; the PME+ IRR stays
   attached and an assumption line gives the reason (Gredil et al.: distributions turn into
   contributions, so the spread is not a performance difference).
5. **Traceability (R2-4, 10, 13, 14, 16, 17).** PME results gain `max_gap_used_days: int`
   and, when `nav_source == "rolled_forward"`, `index_growth_over_nav_gap = I_T / I_navdate`
   with an assumption line saying the PME moves against the fund when it exceeds 1 (else
   `None`). `FlowValuation` gains `index_gap_days`. PME+ and ICM gain `log_spread`
   (difference of the two roots' `log_rate`, when both unique). `Multiples.nav_source` uses
   the `NavSource` literal. Every `input_hash` payload carries a `"method"` key. The as-of
   net of the Direct Alpha series is not multiplied by `I_T / I_T`.
6. **Gross legs (R2-2).** KS-PME, PME+ and the multiples use gross legs; each such result
   states it ("a distribution re-called on the same or a later date counts in both paid-in
   and distributed; netting recallables gives different TVPI/KS-PME/PME+"). A recallable
   policy is not modelled in `pme-v1` and is listed in the limitations.
7. **Not changed:** `ln_pme` keeps its name (the literature's "LN-PME"; the docstring spells
   out Long–Nickels). `assumptions` stays `list[str]` (§2).

## 12. Wave 3: mPME reconstruction (`ovf.pme.mpme`), decided 2026-09-15

Adopted from R2's specification (`out/pme-review-r2.md` Q7) and W4's ledger (S6). It is a
**labelled reconstruction**: Cambridge Associates describe the method only in prose
(S6.2); the algebra follows Gredil, Griffiths & Stucke's 2014 eq. (9) with eq. (11) read
consistently in the period index (S6.3; never cite eq. (11) as printed) and the secondary
S6.5. Never claim to reproduce Cambridge Associates' figures.

```python
class FundNavHistory(FinancialBaseModel):    # frozen
    observations: tuple[NavObservation, ...] # >= 1; duplicate dates refused; stored ascending
InterimNavPolicy = Literal["refuse", "roll_forward_cash_adjusted"]

def mpme(resolved, nav_history, benchmark, *, lookup, max_gap_days, day_count,
         interim_nav: InterimNavPolicy, max_nav_gap_days: int) -> MpmeResult
```

- **Validation:** every observation dated `<= as_of`; an observation dated `as_of` must
  equal `resolved.residual_value` exactly (else `ValueError`); `residual_value` not `None`;
  `paid_in > 0`; same currency; index levels at every flow date and `as_of` (NAV dates need
  none). `interim_nav="refuse"` requires `max_nav_gap_days == 0`.
- **Fund NAV at a distribution date `t`** (end of day, after every flow on `t`, §3):
  an observation dated `t`; else under `"roll_forward_cash_adjusted"` the latest
  observation `s < t` with `(t - s).days <= max_nav_gap_days`, rolled as
  `NAV_s + C_(s,t] - D_(s,t]` (the distribution on `t` itself included, zero return
  assumed); a negative rolled value, no earlier observation, or a gap beyond the limit →
  `ValueError` naming the date. Under `"refuse"` a missing observation → `ValueError`.
  Dates without a distribution need no NAV. *A distribution dated `as_of`* (decided on W6's
  question): when `nav_history` has no observation dated `as_of`, `NAV_T =
  resolved.residual_value` — one `NAV_T`, never two. Its step source is `"reported"` when
  `resolved.nav_source == "reported_at_as_of"`, else `"rolled_forward"` with the
  observation date from `resolved.nav_roll_forward`; that roll is governed by `resolve`'s
  `stale_nav` policy, not by `interim_nav` / `max_nav_gap_days` (assumption line), and
  `max_nav_gap_used_days` counts only interim NAVs rolled by `mpme`. The path has one
  `MpmeStep` per flow date plus `as_of`; `fund_nav` is set only on distribution dates.
- **Recursion per date in order** (grow, invest the call, then sell the fund's fraction):
  `X_t = NAV_mPME,prev * (I_t / I_prev) + C_t`; `w_t = D_t / (D_t + NAV_t)` when
  `D_t > 0`, else 0; `Dist_mPME,t = w_t * X_t`; `NAV_mPME,t = (NAV_t / (D_t + NAV_t)) * X_t`
  (so `w_t = 1` gives exactly 0). Gross `C_t`, `D_t` (a same-day recall is not netted; say so).
- **Series and IRRs:** `{-C_t, +Dist_mPME,t, +NAV_mPME,T at T}` netted per date; nets
  containing `Dist_mPME` or `NAV_mPME,T` are computed nets (§9 rounding bound, `G = C_t +
  Dist_mPME,t (+ NAV_mPME,T)`). mPME IRR via `xirr`; `fund_irr: IrrResult | None` (§11.2);
  `spread` and `log_spread` (fund − mPME) only when both are unique.
- **Result `MpmeResult(PmeResultBase)`:** the common PME fields plus `path:
  tuple[MpmeStep, ...]` with `MpmeStep(date, index_level, contribution, distribution,
  fund_nav: float | None, fund_nav_source: Literal["reported", "rolled_forward", "none"],
  fund_nav_observation_date: date | None, weight, position_before_sale,
  mpme_distribution, position_after)`, `terminal_value`, `mpme_series`, `mpme_irr`,
  `fund_irr`, `spread`, `log_spread`, `max_nav_gap_used_days`, assumptions (reconstruction
  label, weight and ordering conventions, gross legs, NAV sources, the interim-NAV policy,
  and the risk that interim marks enter the benchmark itself).
- **Never short (prove in the docstring, test it):** `NAV_mPME` starts at 0, `I > 0`,
  `C_t >= 0` ⇒ `X_t >= 0`; `D_t > 0` ⇒ `D_t + NAV_t > 0` and `w_t ∈ [0, 1]` ⇒
  `NAV_mPME,t >= 0` and `Dist_mPME,t >= 0`.
- **Identities to test:** a fund whose interim NAVs equal the index-held value of its own
  flows at every distribution date and `T` ⇒ `Dist_mPME,t = D_t`, `NAV_mPME,T = NAV_T`,
  mPME IRR = fund IRR, spread 0; index rescaling changes nothing; scaling flows and every
  NAV by `k > 0` changes nothing; `NAV_t = 0` at a distribution date ⇒ `w_t = 1` and a
  position of exactly 0 after it.
- **Ownership (Wave 3):** W6 owns `src/ovf/pme/mpme.py` and `tests/test_pme_mpme.py`. W7 owns
  `tests/pme_oracle.py`, `tests/pme_fixtures.py`, `tests/test_pme_reference.py` and
  `docs/pme-fixtures.md` (inherited from W3) and extends them to the mPME independently.

## 13. Decisions on the final review (R3, `out/pme-review-r3.md`), 2026-09-15

1. **CSV input never guesses (R3-1, 2, 3).** Duplicate header names are refused (header line
   1); parsing is strict (`csv.Error` → `ValueError` with the physical line); a missing
   file, an undecodable file, a field over the parser limit, an empty or header-only file,
   a missing column and a non-text value are all `ValueError`s naming the file and line;
   a UTF-8 BOM is handled the same for paths and text streams. The CLI never exits 1 with a
   traceback for bad input (exit 2 with the message).
2. **Flags come from structured data, never from assumption text (R3-5).**
   `ResolvedCashFlows.stated_nets_within_noise: tuple[NearZeroNet, ...]` and
   `dropped_computed_nets: tuple[NearZeroNet, ...]` on the PME+, ICM and mPME results
   (`NearZeroNet(date, raw_net, gross, bound)`) carry what was dropped; the report derives
   `STATED_NET_WITHIN_REPRESENTATION_NOISE` and `COMPUTED_NET_DROPPED` from them.
3. **Every index lookup used counts (R3-6).** The NAV-date lookup behind
   `index_growth_over_nav_gap` is reported and included in `max_gap_used_days` and in
   `INDEX_STALE`; it adds no ICM/mPME path step.
4. **mPME throughput (R3-4):** 10,000 flows, 100,000 index levels and 1,000 NAV observations
   with long permitted gaps in under 2 s, without replacing exact window sums by
   differences of large prefix totals.
5. **Report rendering and rows (R3-7, 8, 9).** `to_text()` is magnitude-aware (scientific
   notation outside the fixed range; a tiny non-zero value never prints as zero; a clamped
   root shows its log rate); `to_rows()` separates a metric's availability and reason from
   an underlying IRR's status and keeps `rate_clamped` / `log_rate`; the report validates
   `interim_nav="refuse"` ⇒ `max_nav_gap_days == 0` before running any method.
6. **`datetime` refused on every date field of every `ovf.pme` model (R3-11)**, records and
   results included, as §2 says.
