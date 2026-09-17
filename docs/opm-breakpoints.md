# Exit breakpoints, derived from the waterfall engine

Status 2026-09-15, engine `opm-breakpoints-v1`, module `ovf.opm.breakpoints`. Every expected
number below is derived by hand here, then recomputed independently with `fractions.Fraction`
before it was written down, then asserted in `tests/test_opm_breakpoints.py` against the
fixtures in `tests/opm_breakpoint_fixtures.py`. None was copied from engine output.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty on
every fixture.

## The result: under a collective conversion the payoff steps, and a step is not in the span

The Option Pricing Method values a class whose payoff is `f(X)` as
`sum_t w_t [C(k_t) - C(k_{t+1})]`, where the `k_t` are breakpoints and `w_t` is the class's
share of each marginal dollar between `k_t` and `k_{t+1}`. At the liquidity date the call
spread `C(k_t) - C(k_{t+1})` pays `min(max(X - k_t, 0), k_{t+1} - k_t)`, a continuous
function of `X`. A finite sum of continuous functions is continuous, whatever the weights,
positive or negative. **So no choice of breakpoints and weights reproduces a payoff that
steps.** On a table whose payoff steps, the decomposition is not merely ill-conditioned or
awkward: the payoff is not in its span.

The contract for this module (`docs/opm-contract.md`) expected the failure on governed tables
to show up as negative call-spread weights. Working the README table through
`ovf.governance` shows that it is a step instead. Inside each vote outcome the table is an
ordinary table (Proposition G1 of [governance](governance.md)), and ordinary tables did not
produce a falling payoff in any instance searched (below and in [governance](governance.md)).
The fall happens only where the vote outcome flips, and there it is a jump.

**GV6 in full.** The README table (founders 8,000,000 common; Series A 2,000,000 junior
participating preferred at $2.50, total capped at 2x; Series B 1,500,000 senior
non-participating at $6.00) under a Requisite Holders mandatory conversion needing more than
1/2 of the as-converted preferred vote. Series A holds 2,000,000 of the 3,500,000 votes, 4/7,
so Series A alone decides.

- At **$57,400,000** (GV6b), without the conversion Series B takes its $9,000,000 preference
  and Series A holds at its $10,000,000 cap. Converted, Series A would get
  2/11.5 × $57.4M = 229.6/23 M = $9,982,608.70, less than $10M. Series A withholds and the vote
  fails. **Series B receives $9,000,000.**
- At **$57,600,000** (GV6a), converted, Series A gets 2/11.5 × $57.6M = 230.4/23 M =
  $10,017,391.30, more than $10M. Series A consents and the vote carries. Every position is
  common, so Series B receives 1.5/11.5 × $57.6M = **172.8/23 M = $7,513,043.48**.
- The company sells for $200,000 more and Series B receives **$1,486,956.52 less**.

Series A's gain from the conversion is `2/11.5 X - $10M`, zero at exactly **X = $57,500,000**.
There its cash is $10M either way and it is pivotal, so `ovf.governance` refuses the exit
(GV6). Just below, the vote fails; just above, it carries. Series B's cash steps from
$9,000,000 to 1.5/11.5 × $57.5M = $7,500,000, a jump of **−$1,500,000**, and the founders' cash
steps from $38,500,000 to 8/11.5 × $57.5M = $40,000,000, a jump of **+$1,500,000**.

**A second step, larger, on the same table.** Below $9M, without the conversion Series B takes
everything and Series A receives nothing. Converted, Series A would receive
2/11.5 × X > 0. So Series A consents at every exit below $9M and the vote carries: the
founders receive 8/11.5 of every dollar. Between $9M and $14M Series A is filling its own
preference, `X - $9M`. Its gain from the conversion is `2/11.5 X - (X - $9M) = $9M - 19X/23`,
which is zero at **X = 207/19 M = $10,894,736.84**. Above that exit Series A withholds, the
vote fails, and the founders are back behind $14M of preferences with nothing:

| Exit | Vote | Founders | Series A | Series B |
|---|---|---|---|---|
| $10,000,000 | carries | 160/23 M = **$6,956,521.74** | 40/23 M = $1,739,130.43 | 30/23 M = $1,304,347.83 |
| $12,000,000 | fails | **$0** | $3,000,000 | $9,000,000 |

At 207/19 M the founders' cash steps by **−144/19 M = −$7,578,947.37** and Series B's by
**+144/19 M**. The engine reproduces both rows (`tests/test_opm_breakpoints.py`,
`test_fixture_payouts_replay_the_repository_fixtures`, case BP7). This step is not recorded
in [governance](governance.md), whose finding names only the $57.5M step.

**A smeared window is refused.** The alternative, a narrow tranche `[c − d, c + d]` whose
weights carry the jump as a steep slope (Series B's weight about `-1.5M / 2d`), would let
`payout()` replay the engine to tolerance outside the window. The weights inside it would be an
artifact of `d`, arithmetically well formed and financially meaningless. The schedule records
each step as a `Discontinuity` instead: its exact location, the signed jump of every class
(right limit minus left limit), and the reason. `BreakpointSchedule.continuous` is False
whenever one exists.

## What the schedule records

| Field | Meaning |
|---|---|
| `breakpoints` | the origin, then every exit at which some class's share of the marginal dollar changes, with `kind`, `basis` in words, and `exact` |
| `tranches` | `[lower, upper)` intervals tiling `[0, ∞)`, with measured `weights` and `weight_sum_error` |
| `discontinuities` | every step: `value`, signed `jumps`, `basis`, `exact` |
| `continuous`, `monotone` | False when a step exists; False when any class's cash falls, across a tranche or at a step, by more than `atol` |
| `max_linearity_error`, `linearity_samples` | the largest replay gap against the engine, over this many priced exits |
| `max_weight_sum_error` | the largest `abs(sum(weights) - 1)` over the tranches |
| `assumptions` | the candidate families, the probe rule, the tolerances, the `upper_probe` rule, and the engine's own assumptions |

`payout(X)` integrates the weights up to `X` and adds every step at or below `X`: it is
right-continuous. That is a convention. At the step the vote is tied and the governed payoff
is undefined, and `payout()` reports the limit from above.

## The method

```python
breakpoint_schedule(securities, *, as_of=None, upper_probe=None, atol=1e-6,
                    collective_conversion=None) -> BreakpointSchedule
```

`collective_conversion` was added to the contract signature on 2026-09-15, at the
coordinator's decision. Without it an ungoverned table is priced; with it the table is priced
under that term by `ovf.governance.resolve_collective_conversion`.

### 1. Analytic candidates, in exact arithmetic

The engine's inputs are read exactly as the engine reads them, as `Fraction`s of the stored
floats: each preferred position's `exit_terms(as_of)` (preference, total participation cap,
common-equivalent units, so cumulative and paid-in-kind dividends enter as the engine prices
them), each debt position's `exit_claim(as_of)`, and common share counts. An unallocated pool
holds no issued shares and enters nothing. The allocation rule of `evaluate_fixed_waterfall`
is restated over `Fraction`: preferences by ascending seniority, pro rata by claim within a
tier, then the residual pro rata by units among common, converted and participating positions,
with capped participants water-filled.

Write `D` for the total debt claim and `E = X − D` for the equity value. For every one of the
`2^n` conversion profiles `s` of the `n` preferred positions holding shares:

| Family | `kind` | Candidate |
|---|---|---|
| Debt repaid | `debt_repaid` | `D_t`, cumulative debt claims through debt tier `t` |
| Preference stack | `preference` | `X = D + L_r(s)`, the preferences of the positions holding in `s`, summed through seniority `r` |
| Participation cap | `participation_cap` | for a capped participant `j` with headroom `h_j = cap_j − pref_j` over `u_j` units, the residual per unit reaches `v_j = h_j / u_j` at `R_j = Σ_k min(v_j u_k, h_k)` (uncapped `h_k = ∞`); `X = D + L(s) + R_j` |
| Conversion indifference | `conversion` | every root of `g(E) = P_{s∪{i}}(E)_i − P_s(E)_i`, position `i`'s gain from converting when the others play `s` |
| Vote flip (governed only) | `forced_conversion` | every exit at which a voting holder's gain from the conversion, `Δ_h(E) = Σ_{i∈h} (W'_i(E) − W_i(E))`, changes sign or touches zero |

`P_s` is piecewise linear with knots at that profile's preference and cap candidates, so each
`g` is piecewise linear on the union of two profiles' knots and every root is found exactly by
interpolation inside one affine piece. `W` and `W'` are the unique equilibrium payoffs of the
two stage games of [governance](governance.md), computed exactly at every candidate of every
profile by enumeration; the stage game is refused if it has more than one equilibrium payoff
vector there.

**Proposition B1 (the candidates contain every kink).** Fix a table and assume each stage
game's equilibrium payoff is unique at every exit. Between two consecutive candidates, every
fixed-profile allocation `P_s` is affine, and no position's gain from switching changes sign.
So the set of equilibrium profiles is the same at every exit in the open interval, and the
equilibrium payoff, one fixed profile's `P_s`, is affine there. Under a term, no voting
holder's gain changes sign in the interval either, so every holder votes the same way at every
exit in it, the outcome is constant, and the governed payoff is affine there too.

*Proof.* Each `P_s` is affine between its own knots, and all of them are candidates. Each gain
is a difference of two `P_s`, so it is affine between candidates and, having no root inside
the interval, keeps its sign there. An equilibrium profile is one in which every such gain is
non-positive, and feasibility depends on the stranded cash of `P_s`, which is also affine and
non-negative. So both conditions hold on the whole open interval or nowhere in it. Under a
term, each `Δ_h` is a difference of two equilibrium payoffs, affine in the interval with no
root, so each holder's vote is fixed. ∎

B1 rests on payoff uniqueness, which is an empirical property of this engine
([findings](findings.md), [governance](governance.md)), not a theorem. That is why the
candidates are verified by probing rather than trusted. It also fixes where the tail begins:
above the largest candidate the map is affine forever.

### 2. Verification by probing the engine

Every candidate becomes a knot, and so do the origin and the upper probe `U`. For every
interval `(a, b)` between consecutive knots the engine is priced at five exits:

- `a + d_a` and `b − d_b`, the probes **on both sides of every candidate**, with
  `d_x = min(10^-6 × max(x, 1), (b − a)/10)`;
- `a + t(b − a)` for `t` = 0.2113, 0.5 and 0.7887 (the two Gauss–Legendre nodes and the
  midpoint).

The interval is **affine** when the three interior probes and both end values lie within
`atol / 2` of the line through the two side probes. An end is not measured where the engine
has no value, or at a predicted vote flip. Measuring the ends is what exposes a kink or step
hidden between an end and its nearest probe, which would otherwise pass as affine and be
pinned on the knot.

A candidate is then **dropped** when the chord across it, from the value at the previous kept
knot to the value at the next knot, meets every priced exit in between within `atol / 2`. The
analytic families deliberately over-generate: a profile's preference levels are candidates
even if that profile is never played there. Probing is what discards them. In BP4 the
one-series preference levels $5M and $9M are candidates and are dropped. In BP7 the
ungoverned kinks $9M, $59M and $69M are dropped, because the vote is carrying there.

### 3. Finding what the candidates missed

An interval that is not affine hides a kink or step that no family predicted. It is split,
first where the affine pieces at its two ends meet, which locates a single missed kink in one
step. If the engine is not on both lines there, it is split at its midpoint. Each part is then
verified in turn. A knot found this way has `kind="other"` and `exact=False`, and its `basis`
says how it was located and that no candidate family predicted it.

When an interval is too narrow to split, 32 float spacings, and still not affine:

- if its two ends differ by more than its width plus `atol`, and by more than ten times the
  engine's own tie tolerance, the map steps there, and a `Discontinuity` with `exact=False` is
  recorded;
- otherwise `BreakpointError` is raised, naming the interval and the residual.

More than 400 splits also raises. The tolerance is never widened to make a failure disappear.
`test_a_missed_kink_is_found_by_bisection` deletes BP1's $5M candidate and checks that it is
found anyway. `test_an_unpredicted_step_is_recorded_as_located_numerically` and
`test_a_curved_map_cannot_be_verified` run the same machinery against substituted engines.

### 4. Measuring, not assuming

- **Weights** are measured, `(cash at the upper end − cash at the lower end) / width`, from
  the engine's own values at the ends of each tranche. At a step the one-sided limit on each
  side is used, extrapolated from that side's affine fit. They are not assigned from the
  families and not clipped to `[0, 1]`.
- **`weight_sum_error`** is `abs(fsum(weights) − 1)` as computed, and `max_weight_sum_error`
  the largest of them.
- **Replay.** The finished schedule is replayed against the engine at every exit priced during
  construction, and at fresh exits at fractions 0.382 and 0.618 of every final tranche and at
  `2U`. The largest gap is `max_linearity_error`. Above `atol` it raises `BreakpointError`
  ("the schedule does not replay the engine"). Exits at a step, and inside a numerically
  located step's bracket, are skipped: the payoff there is undefined.
  `test_a_replay_gap_above_atol_is_refused` hides a bump that only a fresh probe hits.
- **`monotone`** is False when some class's cash falls by more than `atol`, across a tranche
  (weight × width) or at a step. The falls are listed in `assumptions`.

**Tolerances.** `atol` is absolute, per class, per priced exit; the construction tests use
`atol / 2`, so that a schedule built to pass them also passes the replay check at `atol`.
`solve_waterfall` keeps an incumbent decision unless switching gains more than its own
tolerance, `1e-8 + 1e-12 × X`. Near an indifference point that band has width
`(1e-8 + 1e-12 X) / |Δslope|`, about 10^-4 dollars at X = $10^8. The side probes sit
`10^-6 × X` from every candidate, far outside it.

**`upper_probe`.** By B1 the map is affine above the largest candidate. The default `U` is
twice the largest analytic candidate, whether or not it was kept, or $1,000,000 when there is
none (a table of common stock alone). The tail is verified up to `U` by the same five-probe
test, and replayed once more at `2U`. A caller-supplied `upper_probe` at or below the largest
candidate is refused, because the candidates above it would go unverified.

## Diagnostic, not a refusal

`breakpoint_schedule` returns a schedule for a non-monotone or discontinuous table, with the
negative weights or the steps exactly as measured. Refusing to price such a table is
`opm_allocate`'s job, and it refuses on `continuous=False` with the reason above. The schedule
raises `BreakpointError` only when it cannot be derived or verified:

- the engine refuses an exit (for example a table with nobody to take the residual);
- a governed exit that is not a predicted vote flip cannot be priced, because a pivotal
  holder is indifferent over a whole interval (see the governed evidence below);
- an interval cannot be made affine, or the finished schedule misses the engine by more than
  `atol`;
- more than 12 preferred positions hold shares (8 under a term), since the candidates
  enumerate every profile;
- debt without `as_of`, a SAFE or unresolved note, allocated options, a bad `atol` or
  `upper_probe`, or a `collective_conversion` that is not one.

## Fixture derivations

Shared table ([fixtures](fixtures.md)): founders **8,000,000** common; Series A 2,000,000 at
$2.50 = **$5,000,000**; Series B 1,500,000 at $6.00 = **$9,000,000**. With both series
converted there are 11,500,000 units, so every unit receives `X / 11.5M` and the weights are
Series A 2/11.5 = **4/23**, Series B 1.5/11.5 = **3/23** and founders 8/11.5 = **16/23**.
Weights are listed per tranche; a class not listed has weight 0.

**BP1: 1x non-participating over common, the textbook table.** Series A junior.

- Below $5M the preference absorbs every dollar: **{A: 1}**.
- Series A converts when 2,000,000 / 10,000,000 × X = $5M, so X = **$25,000,000**.
- Between $5M and $25M Series A holds at $5M and common takes every dollar: **{common: 1}**.
- Above $25M Series A holds 1/5 of the residual: **{A: 1/5, common: 4/5}**.

Breakpoints **5,000,000** (preference) and **25,000,000** (conversion). F1 ($35M → 28M / 7M),
F2 ($15M → 10M / 5M) and F3 ($25M → 20M / 5M) are replayed from the schedule. This is the table
every OPM tutorial draws. The point here is that it was produced by probing the engine, not
drawn.

**BP2: participating, total cap 2x ($10M)** (F5a/F5b).

- Below **$5M**: **{A: 1}**.
- From $5M Series A also takes 1/5 of the residual: **{A: 1/5, common: 4/5}**.
- The cap binds when 5M + 1/5 (X − 5M) = 10M, so X = **$30,000,000**.
  From there: **{common: 1}**.
- Converting beats the cap when 1/5 X = 10M, so X = **$50,000,000**.
  Above: **{A: 1/5, common: 4/5}**.

F5a ($40M → A $10M) and F5b ($60M → A $12M) are replayed.

**BP3: stacked seniority, B senior** (F6, F8a, F8b).

- Below **$9M** Series B fills its preference: **{B: 1}**.
- Up to **$14M** Series A fills its preference: **{A: 1}**.
- From $14M common takes everything: **{common: 1}**.
- Series A, with B holding, converts when 2/10 (X − 9M) = 5M, so X = **$34,000,000**.
  From there: **{A: 1/5, common: 4/5}**.
- Series B, with A converted, converts when 1.5/11.5 X = 9M, so X = **$69,000,000**.
  Above: **{A: 4/23, B: 3/23, common: 16/23}**.

Series B converting while A still holds would need 1.5/9.5 (X − 5M) = 9M, X = $62M. That is a
candidate, but A has already converted at $34M, so the engine shows no kink there and it is
dropped. F6 ($10M → B 9M, A 1M), F8a ($14M) and F8b ($20M → common 6M) are replayed.

**BP4: pari passu** (F7).

- Both claims share one tier, $5M + $9M = **$14M**. Below it they split 5:9:
  **{A: 5/14, B: 9/14}**.
- Above $14M it is BP3: $34M and $69M, with the same weights.

The candidates include $5M and $9M, the one-series preference levels of the profiles in which
the other series has converted. Neither profile is played below $14M, so both are dropped.
F7 ($10M → A 50/14 M = $3,571,428.57, B 90/14 M = $6,428,571.43) is replayed.

**BP5: debt at seniority 0.** The GV8 loan: $1,000,000 at 8% simple, Actual/365 Fixed, issued
2025-01-01, as of 2027-01-01, 730 days. The claim is 1,000,000 × (1 + 0.08 × 730/365) =
**$1,160,000**.

- Below it: **{loan: 1}**, and the first breakpoint is **1,160,000** (`debt_repaid`).
- Above it: BP1 shifted right by $1.16M, with breakpoints **6,160,000** and **26,160,000**.

At $36.16M the schedule pays loan $1.16M, founders $28M and Series A $7M: F1 behind the loan.
Without `as_of` the schedule refuses, as the engine does.

**BP6: an unallocated pool** (F9). BP1 plus a 1,000,000-share reserve, which holds no issued
shares and takes no cash.

- Breakpoints **5,000,000** and **25,000,000**, as in BP1.
- The pool's weight is **0 in every tranche**.
- It still dilutes: Series A holds 2/11 = 18.18% of fully diluted equity (`ownership_breakdown`)
  and the pool 1/11.
- Series A's weight above $25M is **1/5**, not 2/11.

A table built on fully diluted shares would put the conversion at $5M / (2/11) = **$27.5M**,
which is wrong by $2.5M. F9 ($35M → 28M / 7M / 0) is replayed.

**BP7: the README table under a majority Requisite Holders conversion.** This fixture is the
module's reason to exist.

*Without the term* (the README equilibrium; `test_bp7_without_the_term_…`):

| Exit | What changes | Weights above it |
|---|---|---|
| 0 | B fills its $9M preference | {B: 1} |
| $9M | A fills its $5M preference | {A: 1} |
| $14M | A participates in the residual | {A: 1/5, common: 4/5} |
| $39M | A's total reaches its $10M cap: 5M + 1/5 (X − 14M) = 10M | {common: 1} |
| $59M | A converts, B holding: 1/5 (X − 9M) = 10M | {A: 1/5, common: 4/5} |
| $69M | B converts: 3/23 X = 9M | {A: 4/23, B: 3/23, common: 16/23} |

Monotone and continuous.

*With the term.* All preferred converts when Series A consents (4/7 > 1/2); Series B's gain is
negative below $69M and zero above it, so B never decides. Series A's cash with the conversion
is `4X/23`. Its gain `Δ_A(X) = 4X/23 − A_without(X)` is, piece by piece:

| Piece | `A_without` | `Δ_A` | Sign |
|---|---|---|---|
| (0, 9M) | 0 | 4X/23 | + |
| (9M, 14M) | X − 9M | 9M − 19X/23 | + below 207/19 M, − above |
| (14M, 39M) | 2.2M + X/5 | −3X/115 − 2.2M | − |
| (39M, 59M) | 10M | 4X/23 − 10M | − below 57.5M, + above |
| (59M, 69M) | X/5 − 1.8M | 1.8M − 3X/115 | + (zero at 69M) |
| (69M, ∞) | 4X/23 | 0 | none |

The vote carries on (0, 207/19 M) and on (57.5M, 69M). Above $69M the two branches pay the
same, so the outcome no longer matters. The governed map is therefore:

| Tranche | Regime | Weights |
|---|---|---|
| [0, 207/19 M) | all converted | {A: 4/23, B: 3/23, common: 16/23} |
| [207/19 M, 14M) | README: A fills its preference | {A: 1} |
| [14M, 39M) | README: A participates | {A: 1/5, common: 4/5} |
| [39M, 57.5M) | README: A capped | {common: 1} |
| [57.5M, ∞) | all converted | {A: 4/23, B: 3/23, common: 16/23} |

Breakpoints **207/19 M** (`forced_conversion`), **14,000,000** (`preference`),
**39,000,000** (`participation_cap`) and **57,500,000** (`forced_conversion`). Two steps:

- **At 207/19 M = $10,894,736.84**, from all-converted to the README.
  - Series A: 4/23 × 207/19 M = 36/19 M on both sides, so no jump.
  - Series B: from 3/23 × 207/19 M = 27/19 M to $9M, a jump of **+144/19 M**.
  - Founders: from 16/23 × 207/19 M = 144/19 M to $0, a jump of **−144/19 M = −$7,578,947.37**.
- **At $57,500,000**, from the README to all-converted.
  - Series A: $10M on both sides, so no jump.
  - Series B: from $9M to $7.5M, **−$1,500,000**.
  - Founders: from $38.5M to $40M, **+$1,500,000**.

So `monotone` is False and `continuous` is False. The class whose cash falls is the founders'
at 207/19 M and Series B's at $57.5M.

**No tranche weight is negative.** Every weight in the table above is non-negative, and the
test asserts it. The contract's expected symptom, a negative weight, does not occur on this
table. The failure is entirely in the steps.

The ungoverned kinks at $9M, $59M and $69M are candidates and are dropped: the vote is
carrying there, so the governed map does not bend. A hand-built table of the governed payoff
would have to know that.

GV1 ($60M), GV4 ($100M), GV5 ($20M), GV6a ($57.6M) and GV6b ($57.4M) are replayed from the
schedule, and so are the $10M and $12M rows above. At each step `ovf.governance` refuses the
exit itself. `payout()` there returns the limit from above; the test checks it against the
engine at `value × (1 + 10^-9)`.

*Recomputation.* All seven fixtures were recomputed from the formulas above with `Fraction`
alone, without importing `ovf.opm`: every breakpoint, weight and jump matched. For BP7 the
roots of `Δ_A` came out as exactly 207000000/19 and 57500000, the jumps as ±144000000/19 and
∓1500000, and `ovf.governance` refused at `float(207/19 M)` with Series A pivotal.

## Evidence from generated tables

**Ungoverned** (`generated_table(seed)` in `tests/opm_breakpoint_fixtures.py`). Each table has:

- 1–3 preferred positions, multiples 1, 1.5 or 2;
- participation with caps equal to the multiple or up to 2x above it;
- conversion ratios 0.5–2 and seniority collisions;
- common from none to 2,000 shares;
- in a quarter of tables a loan ahead of everything, and in a quarter an unallocated pool.

Every input is exact in binary floating point. For each table:

- **replay:** the schedule was compared with `solve_waterfall` at every breakpoint, 10^-3
  either side of it, and three random exits in every tranche;
- **weights:** each tranche's weights were compared with the slope of the exact-rational
  oracle of `tests/test_governance.py`, written without reference to `ovf.waterfall`, at the
  tranche's midpoint.

| Ungoverned, seeds 0–2,999 | Count |
|---|---|
| Tables / breakpoints | 3,000 / 10,940 |
| Refused | 0 |
| Breakpoints located numerically (`other`) | 0 |
| Tables not monotone / not continuous | 0 / 0 |
| Replay gaps above `atol` | 0 of 80,640 priced exits |
| Largest gap between a weight and the oracle's slope | 5.5 × 10^-15 |

The run took 40 s on one process. pytest runs seeds 0–299. Both evidence tables in this section are replayed from the repository root with `PYTHONPATH=src python -m tests.test_opm_breakpoints 3000 60`, which runs the same `check_generated` and `check_governed` that pytest runs.

**Governed** (tables and terms from the vote search of [governance](governance.md),
`random_vote_instance`, seeds 0–59). Each returned schedule was replayed against the exact
governed payoff (`exact_vote`) at three interior exits of every tranche. Each step's jumps were
compared with the exact payoff 10^-12 either side of it.

| Governed, seeds 0–59 | Count |
|---|---|
| Schedules returned / refused | 52 / 8 |
| Steps recorded / tables with a step | 39 / 22 |
| Tables not monotone | 22 |
| Jumps or interior payouts differing from the exact vote | 0 |
| Breakpoints located numerically | 0 |

Every refusal was at an exit where the exact vote is itself undetermined on an interval. A
voting holder whose gain from the conversion is identically zero there is pivotal, so
`ovf.governance` refuses every exit in the interval, and no schedule can be verified on it.
Where such a holder's gain only touches zero at one exit, the map is continuous. There the
schedule records the point in `assumptions` and reports the common limit. pytest runs seeds
0–39 and asserts each refusal against `exact_vote`.

## Sources

- **AICPA Accounting and Valuation Guide**, *Valuation of Privately-Held-Company Equity
  Securities Issued as Compensation* (2013). It describes the option pricing method and its
  breakpoints. This module implements breakpoints as described there; it does not claim
  conformance with the guide, which was not re-read for this work.
- The call-spread payoff `min(max(X − k_t, 0), k_{t+1} − k_t)` and the continuity argument are
  elementary; no source is needed.
- Engine semantics, the vote model and the fixtures it reuses:
  - [fixtures](fixtures.md) (F1–F10);
  - [governance](governance.md) (GV1–GV9, Proposition G1);
  - [debt](debt.md);
  - [dividends](dividends.md);
  - [findings](findings.md) (payoff uniqueness).

## What this does not establish

- **No proof of completeness.** Proposition B1 shows the candidates contain every kink *if*
  each stage game's equilibrium payoff is unique. That is an empirical property of generated
  tables ([findings](findings.md)), not a theorem. Where it failed, the engine's chosen
  equilibrium could jump. Probing would see such a jump only where a probe or an end value
  catches it.
- **Finite probes.** Affinity is tested at five exits per interval plus the ends, and replay at
  two fresh exits per tranche. A feature narrower than the probe spacing, predicted by no
  family, could pass unseen. The fresh probes catch some such features, not all
  (`test_a_replay_gap_above_atol_is_refused`).
- **The tail beyond `2U`.** Affinity above the largest candidate is B1's conclusion. It is
  verified by probes only up to `U`, and at `2U`.
- **Float resolution.** `atol` is absolute. At exits near $10^10 float spacing approaches
  $10^-6, and the replay check can fail from rounding alone. A caller pricing such a table
  must pass a larger `atol` explicitly; the module does not scale it.
- **The engine's tie band.** The engine's own tolerance is `1e-8 + 1e-12 X`. Within it, it
  keeps an incumbent decision. Probes avoid it, but a breakpoint located numerically inside
  such a band could be offset by the band's width.
- **Size.** Candidates enumerate all `2^n` conversion profiles: at most 12 preferred positions,
  8 under a term. Larger tables are refused, not approximated.
- **Governed tables inherit the vote model's limits.** These include sincere voting, one term
  per exit, and no coalitions or side payments ([governance](governance.md) §Not modelled).
  - An interval on which the governed payoff is undefined is refused.
  - The value at a step is undefined, and `payout()`'s right-continuity is a convention.
  - A numerically located step is placed within 32 float spacings, and its jumps are
    extrapolated.
- **Transaction costs.** `X` is the exit with no transaction costs. A caller pricing net
  proceeds must shift the schedule itself.
- **Not the Option Pricing Method.** A verified schedule says what the engine pays as a function
  of `X`. It says nothing about whether a lognormal `X`, a single liquidity date or any
  volatility is appropriate, and it does not value anything.
- **Instruments.** SAFEs, unresolved convertible notes and allocated options are refused, as the
  engine refuses them.
- **Generated tables are not real tables.** Neither is any table here a real company's charter.
