# Marketability discounts: four estimators, side by side, never blended

Status 2026-09-15, engine `opm-dlom-v1`, module `ovf.opm.dlom`. Every fixed number below is
derived here and asserted in `tests/test_opm_dlom.py`. Each one was recomputed independently
at 60 significant digits with Python's `decimal` module: `_reference` in the test module
shares no code with `ovf.opm.dlom`. The Monte Carlo figures come from `simulate_payoffs` in
the same test module, which shares no code with the implementation either.

**Review status: attributions recalled, NOT verified.** No publication was available in this
checkout and none was consulted. Each formula's author, year and journal were recalled from
memory, and every `DlomEstimate.source` string says so. What can be checked without the
papers is written out in full below: the algebra each function evaluates, the payoff that
algebra prices or approximates, and a simulation of that payoff. That is the evidence here.
The citations are not.

## The finding: Finnerty and Ghaidarov bracket the payoff they both approximate

Finnerty's and Ghaidarov's formulas are closed forms for the same payoff: a put whose strike
is the arithmetic average price over the holding period, exercised against the price at its
end. Simulating that payoff directly shows that **neither formula prices it exactly**.
Finnerty is below the simulated value at every point simulated. Ghaidarov is above it once
σ√T reaches about 0.42. At σ = 60%, T = 2 years:

| | value, % of value |
|---|---:|
| Finnerty | 18.200 |
| simulated average-strike put | 19.284 (s.e. 0.020) |
| Ghaidarov | 19.927 |

The table below is the whole recorded grid. Every simulated cell carries its standard error,
and the last two columns give each formula's gap in standard errors, so a reader can check
that the gap is larger than the noise.

Seed 1995, 1,000,000 paths, 100 steps a year, r = 4%, q = 0. Values are in % of value; the
simulated column is mean (standard error).

| σ | T | σ√T | Finnerty | simulated avg-strike put | Ghaidarov | F − sim (pp) | G − sim (pp) | (F − sim)/s.e. | (G − sim)/s.e. |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.3 | 0.5 | 0.212 | 4.865 | 4.897 (0.006) | 4.892 | −0.032 | −0.005 | −5.1 | −0.7 |
| 0.45 | 0.5 | 0.318 | 7.257 | 7.334 (0.009) | 7.350 | −0.077 | +0.015 | −8.5 | +1.7 |
| 0.6 | 0.5 | 0.424 | 9.602 | 9.759 (0.011) | 9.821 | −0.157 | +0.062 | −13.7 | +5.4 |
| 0.75 | 0.5 | 0.530 | 11.883 | 12.167 (0.014) | 12.310 | −0.284 | +0.143 | −20.6 | +10.4 |
| 0.9 | 0.5 | 0.636 | 14.086 | 14.555 (0.016) | 14.821 | −0.469 | +0.266 | −29.3 | +16.7 |
| 1.2 | 0.5 | 0.849 | 18.200 | 19.258 (0.020) | 19.927 | −1.057 | +0.670 | −51.9 | +32.9 |
| 0.3 | 1.0 | 0.300 | 6.850 | 6.904 (0.009) | 6.927 | −0.055 | +0.023 | −6.4 | +2.7 |
| 0.45 | 1.0 | 0.450 | 10.162 | 10.325 (0.012) | 10.423 | −0.163 | +0.098 | −13.6 | +8.1 |
| 0.6 | 1.0 | 0.600 | 13.340 | 13.710 (0.015) | 13.957 | −0.370 | +0.246 | −24.4 | +16.2 |
| 0.75 | 1.0 | 0.750 | 16.343 | 17.051 (0.018) | 17.541 | −0.709 | +0.489 | −38.8 | +26.8 |
| 0.9 | 1.0 | 0.900 | 19.130 | 20.340 (0.021) | 21.186 | −1.210 | +0.845 | −56.5 | +39.5 |
| 1.2 | 1.0 | 1.200 | 23.928 | 26.726 (0.029) | 28.692 | −2.798 | +1.966 | −97.1 | +68.2 |
| 0.3 | 2.0 | 0.424 | 9.602 | 9.761 (0.011) | 9.821 | −0.159 | +0.060 | −13.8 | +5.2 |
| 0.45 | 2.0 | 0.636 | 14.086 | 14.568 (0.016) | 14.821 | −0.481 | +0.254 | −30.1 | +15.9 |
| 0.6 | 2.0 | 0.849 | 18.200 | 19.284 (0.020) | 19.927 | −1.084 | +0.643 | −53.2 | +31.5 |
| 0.75 | 2.0 | 1.061 | 21.838 | 23.882 (0.025) | 25.167 | −2.044 | +1.285 | −81.0 | +51.0 |
| 0.9 | 2.0 | 1.273 | 24.917 | 28.333 (0.031) | 30.560 | −3.416 | +2.227 | −110.0 | +71.7 |
| 1.2 | 2.0 | 1.697 | 29.247 | 36.721 (0.048) | 41.798 | −7.474 | +5.077 | −154.2 | +104.7 |
| 0.3 | 3.0 | 0.520 | 11.656 | 11.918 (0.014) | 12.057 | −0.262 | +0.140 | −19.3 | +10.3 |
| 0.45 | 3.0 | 0.779 | 16.908 | 17.731 (0.019) | 18.251 | −0.824 | +0.519 | −43.5 | +27.4 |
| 0.6 | 3.0 | 1.039 | 21.495 | 23.379 (0.025) | 24.631 | −1.884 | +1.252 | −76.3 | +50.7 |
| 0.75 | 3.0 | 1.299 | 25.257 | 28.816 (0.032) | 31.238 | −3.559 | +2.423 | −111.4 | +75.8 |
| 0.9 | 3.0 | 1.559 | 28.104 | 34.006 (0.042) | 38.078 | −5.902 | +4.073 | −140.0 | +96.6 |
| 1.2 | 3.0 | 2.078 | 31.234 | 43.560 (0.080) | 52.195 | −12.326 | +8.635 | −153.5 | +107.5 |

Reading across it:

- **Finnerty is below the simulated payoff in all 24 cells**, by more than five standard
  errors in each. The gap is 0.03 percentage points at σ√T = 0.21, 0.37 at 0.60, about 1.1
  at 0.85, 3.4 at 1.27 and 12.3 at 2.08.
- **Ghaidarov is above it from σ√T = 0.42 up**, by more than five standard errors in every
  cell from there on. At 0.21, 0.30 and 0.32 it is within three standard errors (−0.7, +2.7
  and +1.7). The gap is 0.06 points at 0.42, 0.25 at 0.60, 0.65 at 0.85, 2.2 at 1.27 and
  8.6 at 2.08.
- **Equal σ√T, equal value.** σ = 0.6 at T = 0.5 and σ = 0.3 at T = 2 both have σ√T = 0.424,
  and the simulation gives 9.759 and 9.761. With no dividend yield the payoff depends on σ and
  T only through σ²T. The simulation reproduces that without being told it.
- **The time step does not explain the gap.** Five runs at σ = 0.6, T = 2 with 25, 50, 100,
  200 and 400 steps over the two years give 19.247, 19.258, 19.218, 19.284 and 19.242, each
  with s.e. 0.020. Each step count consumes the random stream differently, so the five are
  independent draws. They scatter as independent draws should and show no trend, so the
  trapezoid average's discretisation bias is below what the simulation can resolve. Pooled,
  they give 19.250 (s.e. about 0.009).

**Where σ√T = 0.5 sits.** For illustration, this document treats volatility of 45–75% and a
holding period of one to three years as ordinary for a venture-backed private company. That
band is a working choice made here, not a survey. Across it σ√T runs from 0.45 (45%, one year)
to 1.30 (75%, three years), so nearly all of it lies past 0.5. Over the band Finnerty is 0.16
to 3.6 points below the simulated payoff and Ghaidarov 0.10 to 2.4 points above. At the
centre, 60% over two years, the gaps are −1.08 and +0.64. The finding applies across the
inputs people actually use.

**Why this is about the formulas, not the simulation.** The same harness, on the same paths,
reproduces the two closed forms that are exact. In every one of the 24 cells (see the harness
table below):

- Chaffe's put agrees with its simulation to within 2.5 standard errors.
- Longstaff's lookback agrees to within 1.9.
- The simulated discounted price is a martingale to within 2.1.
- The Asian put-call symmetry that connects Ghaidarov's construction to this payoff holds to
  within 2.3.

The gaps above are 5 to 154 standard errors for Finnerty, and 5 to 108 for Ghaidarov from
σ√T = 0.42. That is one to two orders of magnitude outside anything the checks allow. A
harness that got the average, the discounting, the carry or the random numbers wrong would
fail those checks, and it does not. So the Finnerty and Ghaidarov gaps belong to those two
formulas.

This document does not say which of the two is "correct". Both approximate one payoff, and
the simulation measures how far each is from it. It does not establish that this payoff is
the right model of a marketability discount. It does not describe the published critique
Ghaidarov's formula is attributed to, because that critique was not read.

## What is implemented

```python
from ovf.opm.dlom import dlom_comparison

for estimate in dlom_comparison(volatility=0.6, time=2.0, risk_free_rate=0.04):
    print(estimate.method, round(estimate.discount, 4))
# chaffe 0.2789 / finnerty 0.182 / longstaff 0.8772 / ghaidarov 0.1993
```

- **Four functions, one per method.** `chaffe_dlom`, `finnerty_dlom`, `longstaff_dlom` and
  `ghaidarov_dlom` each return a `DlomEstimate`. It carries the discount, the inputs, the
  formula evaluated, the attributed source with its verification status, the assumptions and
  the caveats.
- **`dlom_comparison`** returns all four, in the fixed order `DLOM_METHODS`: chaffe,
  finnerty, longstaff, ghaidarov. That is an order, not a ranking.
- **No default method, no average, no single "the DLOM".** The module exports nothing else,
  and a test asserts that.
- **No house inputs.** `volatility`, `time` and `risk_free_rate` are required keyword
  arguments everywhere. `dividend_yield` defaults to zero.
- **Refusals** raise `OpmError` and name the method and the field. They cover non-positive or
  non-finite volatility or holding period, non-finite rates, a `volatility**2 * time` that
  underflows, and a result that is non-finite or, through lost precision, negative.
  `longstaff_dlom` refuses a nonzero dividend yield, and `dlom_comparison` then refuses the
  whole set rather than return three of the four.
- **Not clamped.** Longstaff above 100% is returned as computed. `Discount` in `types.py` has
  no upper bound, for exactly this reason.

## Notation and the four payoffs

Value is 1 at the valuation date. Under the pricing measure dS = (r − q) S dt + σ S dW. Write
s = σ²T, N for the standard normal distribution function, φ for its density, and

    Ŝ_t = S_t e^{−(r−q)t} = exp(σ W_t − σ² t / 2),        Â = (1/T) ∫₀ᵀ Ŝ_t dt.

Ŝ is a driftless geometric Brownian motion, a martingale with Ŝ₀ = 1, and Â is its continuous
arithmetic average. Every moment used below follows from E[Ŝ_u Ŝ_t] = e^{σ² min(u, t)}:

    E[Â]      = 1
    E[Â²]     = (2/T²) ∫₀ᵀ ∫₀ᵗ e^{σ² u} du dt = 2 (eˢ − s − 1) / s²
    E[Â Ŝ_T]  = (1/T) ∫₀ᵀ e^{σ² t} dt       = (eˢ − 1) / s
    E[Ŝ_T²]   = eˢ

| Method | Payoff simulated | Closed form's relation to it |
|---|---|---|
| Chaffe | e^{−rT} (1 − S_T)⁺ | exact |
| Finnerty | e^{−rT} (A_T − S_T)⁺ | approximation |
| Ghaidarov | e^{−rT} (A_T − S_T)⁺ | approximation |
| Longstaff | e^{−rT} (max_t S_t e^{r(T−t)} − S_T) | exact |

Here A_T = (1/T) ∫₀ᵀ S_t e^{(r−q)(T−t)} dt is the average of prices, each carried forward to T
at r − q. With q = 0 that is what a holder receives by selling evenly over the period and
reinvesting the proceeds at r. Because S_t e^{(r−q)(T−t)} = e^{(r−q)T} Ŝ_t, the average-strike
payoff is worth e^{−rT} e^{(r−q)T} E[(Â − Ŝ_T)⁺] = e^{−qT} E[(Â − Ŝ_T)⁺]. **So r drops out, and
q enters as e^{−qT}.** Under that convention the Finnerty and Ghaidarov closed forms price
the stated payoff. The simulation checks it at r = 5%, q = 2%. Whether either publication
states its dividend term in exactly this form has not been checked.

### Chaffe: a European put struck at the initial value

    D_C = e^{−rT} N(−d₂) − e^{−qT} N(−d₁),    d₁ = ((r − q) T + s/2) / √s,    d₂ = d₁ − √s

This is the Black–Scholes–Merton put with spot and strike both equal to 1, and it prices
e^{−rT} E[(1 − S_T)⁺] exactly. The strike is the initial value, not the forward. Two
properties follow from the formula:

- **It is bounded above by e^{−rT}**, the value of the strike paid at T. The bound exceeds 1
  only when the rate is negative (DL4).
- **With r > 0 and q ≥ 0 it tends to zero as T grows without bound**, because e^{−rT}
  vanishes, so it is not monotone in the holding period. Every row of the grid below is still
  rising at five years; the test checks the limit at T = 200.

### Longstaff: the value of selling at the maximum with hindsight

    D_L = (2 + s/2) N(√s / 2) + √(s / (2π)) e^{−s/8} − 1

With q = 0, e^{−rT}(max_t S_t e^{r(T−t)} − S_T) is worth E[max_t Ŝ_t] − E[Ŝ_T] = E[e^M] − 1.
Here M is the running maximum over [0, T] of X_t = ln Ŝ_t, a Brownian motion with drift −σ²/2.

**Derivation.** The reflection principle gives, for m ≥ 0,
P(M > m) = N(−(m + s/2)/√s) + e^{−m} N((s/2 − m)/√s). With a = √s/2:

    E[e^M] − 1 = ∫₀^∞ eᵐ P(M > m) dm = I₁ + I₂
    I₂ = ∫₀^∞ N((s/2 − m)/√s) dm = √s ∫_{−∞}^{a} N(y) dy = √s (a N(a) + φ(a))
    I₁ = ∫₀^∞ eᵐ N(−(m + s/2)/√s) dm
       = −N(−a) + ∫₀^∞ φ((m − s/2)/√s) / √s dm = N(a) − N(−a)

I₁ is integrated by parts, using eᵐ φ((m + s/2)/√s) = φ((m − s/2)/√s). So
E[e^M] − 1 = 2N(a) − 1 + (s/2) N(a) + √s φ(a), which is D_L. The tests check the same
identity against direct numerical quadrature of the running-maximum law at s = 0.01, 0.72, 2
and 9, to a relative 10⁻⁹. They also check it against the simulation, which samples the
maximum exactly between time steps.

**It exceeds 100%, and it is not clamped.** D_L reaches 1 at s* = 0.886066, where
σ√T = 0.941311 (DL6), and it grows like s/2 without bound. In the grid below it passes 100% at
45% volatility over five years, 60% over three and 75% over two. **It is an upper bound on the
value of perfect market timing.** It measures what a holder who knew the best price of the
period in advance, and could sell there, gives up by being unable to sell. That is not a
marketability discount. A discount above 100% would make the restricted interest worth less
than nothing, and every discount at or below 100% satisfies a bound above 100% trivially. Past
s*, the bound tells you nothing about the discount. A clamped value would be a number no
source supports, so the estimate reports the bound as computed and says in its caveats what
that means.

Pathwise, the lookback payoff is at least the Chaffe put's payoff when r ≥ 0: max_t S_t
e^{r(T−t)} ≥ S_T and ≥ e^{rT} ≥ 1. It also dominates the average-strike put, since the maximum
is at least the average. So Longstaff is never below Chaffe (r ≥ 0, q = 0), and never below
the average-strike payoff's value. In the grid below it is also the largest of the four in
every cell.

### Finnerty: an exchange option after bivariate-lognormal moment matching

    D_F = e^{−qT} [N(v/2) − N(−v/2)],    v² = s + ln(2 (eˢ − s − 1)) − 2 ln(eˢ − 1)

**Which version.** This is the formula attributed to Finnerty (2012), *The Journal of
Derivatives* 19(4), 53–69. The attribution was recalled and has not been checked against the
article. **How the 2002 working paper differs is not established here.** A reader with both
documents should check it, and it is on the reviewer list below. The formula stands on its
own algebra, as follows.

Replace (ln Â, ln Ŝ_T) by a bivariate normal (X, Y) with E[eˣ] = E[eʸ] = 1 and the same three
second moments:

    Var X     = ln E[Â²]     = ln(2 (eˢ − s − 1)) − 2 ln s
    Var Y     = ln E[Ŝ_T²]   = s
    Cov(X, Y) = ln E[Â Ŝ_T]  = ln(eˢ − 1) − ln s

Then

    Var(X − Y) = Var X + Var Y − 2 Cov(X, Y) = s + ln(2 (eˢ − s − 1)) − 2 ln(eˢ − 1) = v².

For unit-mean jointly lognormal variables, taking eʸ as numeraire gives
E[(eˣ − eʸ)⁺] = Ẽ[(e^{X−Y} − 1)⁺], where e^{X−Y} is unit-mean lognormal with log-variance v².
That is the at-the-money call N(v/2) − N(−v/2). This is Margrabe's exchange-option formula
at zero rates; the attribution to Margrabe (1978), *Journal of Finance* 33(1), is recalled.
**So D_F is e^{−qT} E[(Â − Ŝ_T)⁺] computed as if the average and the terminal price were
jointly lognormal.** They are not, and the simulation above measures the cost of treating
them as if they were.

**The 32.28% ceiling (DL5).** As s → ∞, ln(2 (eˢ − s − 1)) = ln 2 + s + ln(1 − (s + 1) e^{−s})
and 2 ln(eˢ − 1) = 2s + 2 ln(1 − e^{−s}). So v² → s + ln 2 + s − 2s = ln 2, and

    D_F → e^{−qT} [N(√ln 2 / 2) − N(−√ln 2 / 2)] = e^{−qT} erf(√ln 2 / (2√2))
        = 0.322792902826673 e^{−qT}.

**The payoff has no such ceiling.** By the symmetry derived under Ghaidarov below,
e^{−qT} E[(Â − Ŝ_T)⁺] = e^{−qT} E[(1 − Â)⁺]. Substituting u = σ²t gives
Â ≤ (1/s) ∫₀^∞ exp(B_u − u/2) du for a standard Brownian motion B. That integral has the same
law for every σ, and it is finite almost surely because B_u/u → 0. So Â → 0 in probability
as s → ∞, and by bounded convergence the payoff's value tends to e^{−qT}. The simulation is
already well past the ceiling inside the grid: 36.72% at σ√T = 1.70 and 43.56% at 2.08,
against Finnerty's 29.25% and 31.23%. **The ceiling belongs to the moment match, not to the
payoff.**

### Ghaidarov: a lognormal moment match of the average alone

    D_G = e^{−qT} [N(v/2) − N(−v/2)],    v² = ln(2 (eˢ − s − 1)) − 2 ln s

This formula is attributed to Ghaidarov (2009), a working paper, as a critique of the
Finnerty derivation. The attribution was recalled, not verified. The content of that
critique is neither reproduced nor assessed here. The algebra is as follows.

v² = ln E[Â²] − 2 ln E[Â], and the second term is zero. That is the log-variance of a
lognormal L carrying the average's first two moments, and D_G = e^{−qT} E[(1 − L)⁺], the
at-the-money put on L at zero rates. It approximates the average-strike payoff because of a
**put-call symmetry for Asian options**: at zero net carry,

    E[(Â − Ŝ_T)⁺] = E[(1 − Â)⁺].

**Derivation.** Take Ŝ_T as numeraire. Under dP̃ = Ŝ_T dP, W̃_t = W_t − σt is a Brownian
motion, and

    Â / Ŝ_T = (1/T) ∫₀ᵀ exp(−σ (W̃_T − W̃_t) − σ² (T − t) / 2) dt.

Reverse time: with u = T − t, B_u = W̃_T − W̃_{T−u} is a Brownian motion, so Â / Ŝ_T has the
law of (1/T) ∫₀ᵀ exp(−σ B_u − σ² u / 2) du. That is the law of Â, since −B is also a Brownian
motion. Hence E[(Â − Ŝ_T)⁺] = Ẽ[(Â/Ŝ_T − 1)⁺] = E[(Â − 1)⁺] = E[(1 − Â)⁺]. The last step is
put-call parity with E[Â] = 1. The general result is attributed, again from recall, to
Henderson and Wojakowski (2002), *Journal of Applied Probability* 39(2). The trapezoid
weights are symmetric in time, so the argument also holds for the discretised average. The
simulation prices both sides on the same paths; the harness table below reports their
paired difference.

So both formulas approximate the same quantity, e^{−qT} E[(1 − Â)⁺]. Ghaidarov matches the
average's distribution, and Finnerty matches the joint distribution of the average and the
terminal price. They agree to first order and differ at the second:

    Finnerty:   v² = s/3 − s²/18 + O(s³)
    Ghaidarov:  v² = s/3 + s²/36 + O(s³)

These expansions were checked at 50 digits at s = 10⁻² and 10⁻³. The sign of that difference
is consistent with the sign of the gaps the simulation measures. As s → ∞, Ghaidarov's v² →
∞ and D_G → e^{−qT}, which is the payoff's own limit. So it has no artificial ceiling, but it
overshoots the payoff on the way there.

## Small-σ√T behaviour

As σ√T → 0 with r = q = 0, all four become proportional to σ√T:

- Chaffe = erf(√s / (2√2)) ≈ √s / √(2π);
- Longstaff = erf(√s / (2√2)) + (s/2) N(√s/2) + √s φ(√s/2) ≈ 2 √s / √(2π);
- Finnerty and Ghaidarov = erf(v / (2√2)) ≈ v / √(2π), with v ≈ √(s/3).

So Longstaff : Chaffe : Finnerty : Ghaidarov → 2 : 1 : 1/√3 : 1/√3. Three variances start at
s/3: Finnerty's, Ghaidarov's and the payoff's own. For a Brownian motion W,
Var((1/T) ∫₀ᵀ W_t dt − W_T) = T/3 + T − 2 · T/2 = T/3. The test asserts these ratios at
σ√T = 10⁻⁴.

## Hand-derived fixtures DL1–DL6

The tests assert 15-digit values from the 60-digit recomputation, to a relative 10⁻¹². The
intermediate values below are rounded to 15 digits; each final value is the exact
combination, not the rounded one.

**DL1: σ = 0.6, T = 2, r = 0.04, q = 0.** s = 0.72, √s = 0.848528137423857.

- Chaffe: d₁ = (0.08 + 0.36) / 0.848528137423857 = 0.518544972870135, d₂ = −0.329983164553722.
  e^{−0.08} N(0.329983164553722) = 0.923116346386636 × 0.629293658479992 = 0.580911262820330,
  and N(−0.518544972870135) = 0.302039045303621. **D_C = 0.278872217516708.**
- Finnerty: eˢ = 2.054433210643888. 2 (eˢ − s − 1) = 0.668866421287775, whose log is
  −0.402170908016508. 2 ln(eˢ − 1) = 0.106006762932966. So
  v² = 0.72 − 0.402170908016508 − 0.106006762932966 = 0.211822329050526, v/2 =
  0.230120799282967, and **D_F = N(v/2) − N(−v/2) = 0.182002096928826.**
- Ghaidarov: 2 ln 0.72 = −0.657008133944072, so
  v² = −0.402170908016508 + 0.657008133944072 = 0.254837225927564 and v/2 = 0.252407025421027.
  **D_G = 0.199273529588148.**
- Longstaff: a = √s/2 = 0.424264068711929, N(a) = 0.664313379729564, and
  (2 + 0.36) N(a) = 1.567779576161770. √(s/2π) e^{−s/8} = 0.338513750128654 ×
  0.913931185271228 = 0.309378272885689. **D_L = 1.567779576161770 + 0.309378272885689 − 1 =
  0.877157849047459.**

**DL2: DL1 with q = 0.03.** e^{−qT} = e^{−0.06} = 0.941764533584249.

- Finnerty: 0.182002096928826 × 0.941764533584249 = **0.171403119925531**.
- Ghaidarov: 0.199273529588148 × 0.941764533584249 = **0.187668742648269**.
- Chaffe: d₁ = (0.02 + 0.36) / 0.848528137423857 = 0.447834294751480 and
  d₂ = −0.400693842672377. e^{−0.08} N(0.400693842672377) = 0.605266366818475 and
  e^{−0.06} N(−0.447834294751480) = 0.308085454836370, so **D_C = 0.297180911982105.** The yield
  raises Chaffe, because the underlying's forward falls, and lowers the two average-strike
  formulas.
- Longstaff: refused.

**DL3: Longstaff above 100%.** σ = 1, T = 2, so s = 2 and a = 0.707106781186548, with
N(a) = 0.760249938906523. (2 + 1) N(a) = 2.280749816719570 and √(2/2π) e^{−1/4} =
0.439391289467722. **D_L = 1.720141106187292**, returned unclamped.

**DL4: a negative rate.** σ = 0.6, T = 2, r = −0.005, q = 0. d₁ = (−0.01 + 0.36) /
0.848528137423857 = 0.412478955692153 and d₂ = −0.436049181731704. e^{0.01}
N(0.436049181731704) = 1.010050167084168 × 0.668599476675209 = 0.675319013128182, and
N(−0.412478955692153) = 0.339994201117147. **D_C = 0.335324812011035.** The rate is taken as
given, since `Rate` in `types.py` may be negative, and the bound e^{−rT} = 1.01005 now
exceeds 1.

**DL5: Finnerty's ceiling.** √ln 2 = 0.832554611157698, and erf(0.832554611157698 / (2√2)) =
erf(0.294352505628869) = **0.322792902826673**. The test evaluates D_F at s = 10⁴ and gets
this value to 10⁻¹³. It also checks that the ceiling is approached from below, and that it
scales with e^{−qT}.

**DL6: Longstaff's 100% crossing.** Bisection on the 60-digit form gives **s* = 0.886065843793**,
where **σ√T = 0.941310705237**. The test checks D_L < 1 at s*(1 − 10⁻⁹) and D_L > 1 at
s*(1 + 10⁻⁹).

## Numerics

- **The two log-moment ratios.** Finnerty and Ghaidarov are computed from ln(2 (eˢ − s − 1) / s²)
  and ln((eˢ − 1) / s). Below s = 0.5 these come from their Taylor series, because eˢ − s − 1
  loses digits to cancellation there. Above it they are written with e^{−s}, so nothing
  overflows.
- **No near-equal subtractions.** N(v/2) − N(−v/2) is evaluated as erf(v / (2√2)), and
  Longstaff's (2 + s/2) N(a) − 1 as erf(a/√2) + (s/2) N(a).
- **Tested against the reference.** A test sweeps s from 10⁻¹⁰ to 50, across both branches,
  against the 60-digit reference to a relative 10⁻¹⁰. It also checks both sides of the
  s = 0.5 boundary to 10⁻¹³.

## Monte Carlo verification

**Design.** `simulate_payoffs` in `tests/test_opm_dlom.py` simulates ln S exactly on a uniform
grid under the pricing measure, with numpy's `default_rng(seed)` (PCG64). On the same paths
it prices five things:

- **the European put**, from the terminal price, which carries no discretisation error;
- **the average-strike put**, with the trapezoid average of the carried prices over the
  steps + 1 dates;
- **the at-the-money average-price put** (e^{(r−q)T} − A_T)⁺, for the symmetry check;
- **the lookback.** Its maximum is sampled exactly inside each step from the Brownian-bridge
  law, M = (x₀ + x₁ + √((x₁ − x₀)² − 2σ²Δt ln U)) / 2 with U uniform on (0, 1], so it carries
  no discretisation bias;
- **e^{−rT} S_T**, whose true value is e^{−qT}.

Each standard error is the sample standard deviation divided by √paths.

**Recorded run.** Seed 1995, 1,000,000 paths, 100 steps a year, r = 4%, q = 0. The grid is
σ ∈ {30, 45, 60, 75, 90, 120}% and T ∈ {0.5, 1, 2, 3}. Replay it with
`python -m tests.test_opm_dlom`, which took 120 seconds on the machine that produced it. All 24 cells use the
same seed and the same time step, so they share their Brownian paths. Their errors are
therefore strongly correlated from cell to cell. When a sign repeats down a column, that is
one draw of the noise, not 24.

The harness: each exact closed form against its simulation, the martingale check on
e^{−rT} S_T, and the paired symmetry gap between the average-strike put and the at-the-money
average-price put. The z columns are the gap over the simulation's standard error.

| σ | T | σ√T | Chaffe | sim put | (C − sim)/s.e. | Longstaff | sim max | (L − sim)/s.e. | (sim e^{−rT}S_T − 1)/s.e. | sim symmetry gap | gap/s.e. |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.3 | 0.5 | 0.212 | 7.410 | 7.429 (0.010) | −1.8 | 18.082 | 18.102 (0.012) | −1.7 | −2.1 | 0.011 (0.007) | +1.5 |
| 0.45 | 0.5 | 0.318 | 11.550 | 11.577 (0.015) | −1.8 | 28.027 | 28.052 (0.017) | −1.5 | −2.1 | 0.015 (0.011) | +1.4 |
| 0.6 | 0.5 | 0.424 | 15.661 | 15.695 (0.019) | −1.8 | 38.605 | 38.633 (0.022) | −1.3 | −2.1 | 0.019 (0.014) | +1.3 |
| 0.75 | 0.5 | 0.530 | 19.729 | 19.769 (0.022) | −1.8 | 49.840 | 49.867 (0.028) | −1.0 | −2.0 | 0.021 (0.018) | +1.2 |
| 0.9 | 0.5 | 0.636 | 23.741 | 23.788 (0.025) | −1.9 | 61.755 | 61.778 (0.034) | −0.7 | −2.0 | 0.022 (0.021) | +1.0 |
| 1.2 | 0.5 | 0.849 | 31.556 | 31.614 (0.030) | −2.0 | 87.716 | 87.718 (0.053) | −0.0 | −1.9 | 0.022 (0.029) | +0.8 |
| 0.3 | 1.0 | 0.300 | 9.832 | 9.865 (0.013) | −2.5 | 26.276 | 26.301 (0.016) | −1.6 | −1.2 | −0.010 (0.010) | −1.0 |
| 0.45 | 1.0 | 0.450 | 15.560 | 15.605 (0.019) | −2.4 | 41.269 | 41.299 (0.023) | −1.3 | −1.1 | −0.017 (0.015) | −1.1 |
| 0.6 | 1.0 | 0.600 | 21.209 | 21.262 (0.023) | −2.3 | 57.588 | 57.618 (0.032) | −0.9 | −0.9 | −0.025 (0.020) | −1.2 |
| 0.75 | 1.0 | 0.750 | 26.739 | 26.797 (0.027) | −2.1 | 75.297 | 75.323 (0.043) | −0.6 | −0.7 | −0.034 (0.025) | −1.3 |
| 0.9 | 1.0 | 0.900 | 32.119 | 32.179 (0.030) | −2.0 | 94.459 | 94.480 (0.060) | −0.4 | −0.6 | −0.042 (0.030) | −1.4 |
| 1.2 | 1.0 | 1.200 | 42.325 | 42.381 (0.034) | −1.6 | 137.390 | 137.420 (0.117) | −0.3 | −0.4 | −0.056 (0.041) | −1.4 |
| 0.3 | 2.0 | 0.424 | 12.591 | 12.603 (0.017) | −0.7 | 38.605 | 38.645 (0.022) | −1.8 | −0.6 | 0.029 (0.014) | +2.0 |
| 0.45 | 2.0 | 0.636 | 20.346 | 20.365 (0.023) | −0.8 | 61.755 | 61.814 (0.034) | −1.7 | −0.5 | 0.047 (0.021) | +2.2 |
| 0.6 | 2.0 | 0.849 | 27.887 | 27.912 (0.028) | −0.9 | 87.716 | 87.790 (0.053) | −1.4 | −0.4 | 0.066 (0.029) | +2.3 |
| 0.75 | 2.0 | 1.061 | 35.114 | 35.140 (0.031) | −0.8 | 116.666 | 116.751 (0.085) | −1.0 | −0.1 | 0.083 (0.036) | +2.3 |
| 0.9 | 2.0 | 1.273 | 41.955 | 41.982 (0.033) | −0.8 | 148.774 | 148.866 (0.136) | −0.7 | +0.2 | 0.092 (0.045) | +2.1 |
| 1.2 | 2.0 | 1.697 | 54.271 | 54.298 (0.035) | −0.8 | 223.098 | 223.254 (0.351) | −0.4 | +0.8 | 0.093 (0.065) | +1.4 |
| 0.3 | 3.0 | 0.520 | 14.187 | 14.205 (0.018) | −1.0 | 48.674 | 48.725 (0.027) | −1.9 | −0.1 | 0.026 (0.018) | +1.5 |
| 0.45 | 3.0 | 0.779 | 23.278 | 23.307 (0.025) | −1.2 | 78.939 | 79.012 (0.046) | −1.6 | +0.3 | 0.032 (0.026) | +1.2 |
| 0.6 | 3.0 | 1.039 | 31.997 | 32.034 (0.029) | −1.2 | 113.601 | 113.700 (0.081) | −1.2 | +0.8 | 0.033 (0.035) | +0.9 |
| 0.75 | 3.0 | 1.299 | 40.178 | 40.213 (0.032) | −1.1 | 152.974 | 153.120 (0.145) | −1.0 | +1.2 | 0.028 (0.046) | +0.6 |
| 0.9 | 3.0 | 1.559 | 47.711 | 47.740 (0.033) | −0.9 | 197.355 | 197.617 (0.257) | −1.0 | +1.5 | 0.021 (0.058) | +0.4 |
| 1.2 | 3.0 | 2.078 | 60.587 | 60.601 (0.033) | −0.4 | 302.192 | 303.204 (0.807) | −1.3 | +1.6 | 0.016 (0.096) | +0.2 |

**Reading the harness table.** Every cell is inside 2.5 standard errors, but the signs repeat
down the columns. Chaffe's simulation comes out above its closed form in all 24 cells, and
so does Longstaff's. That is what shared paths do: it is one draw of the noise, seen 24
times, not 24 draws. Two further runs at σ = 0.6, T = 2 tell noise from bias.

- **Five independent seeds**, printed at the end of the replay. Chaffe's z-scores are −0.9,
  −1.0, −0.6, −2.3 and −0.5; Longstaff's −1.4, −1.8, +0.5, −0.5 and +0.6; the martingale's
  −0.4, +0.9, −0.1, +0.1 and +0.6. Chaffe's five average −1.06, which is 2.4 standard errors
  from zero. Chance produces that about once in 60 runs, so it was followed up.
- **One hundred independent seeds**, each with 200,000 paths and 200 steps. Replay with
  `python -m tests.test_opm_dlom --seeds`.

  | | mean z | pooled z | s.d. of z | outside ±2 |
  |---|---:|---:|---:|---:|
  | Chaffe | +0.009 | +0.09 | 0.95 | 3 of 100 |
  | Longstaff | +0.003 | +0.03 | 1.01 | 5 of 100 |
  | martingale | −0.141 | −1.41 | 1.01 | 6 of 100 |

  Those are the numbers an unbiased estimator produces: a mean near zero, a standard deviation
  near one, and about 5 in 100 outside ±2. Neither exact form, and neither set of paths, shows
  a detectable bias. The five-seed run was chance.
- **A direct check that bypasses the oracle** agrees. It was a one-off script, not kept in the
  repository: it drew terminal prices directly and used none of the oracle's code. Chaffe
  over 20 seeds of 2,000,000 draws gave a mean z of −0.08. The martingale over 100 seeds of
  200,000 summed-normal paths gave a pooled z of −0.82.

**The pytest version.** The default test run uses seed 20260915, 100,000 paths and 50 steps a
year. Every tolerance is `Z_TOLERANCE` = 4 standard errors of that run; under normality a
correct closed form fails one comparison with two-sided probability 6.3 × 10⁻⁵. It checks:

- Chaffe at four points, one with a negative rate and a dividend yield;
- Longstaff at three points;
- the martingale at three (r, q) pairs;
- the symmetry at two points;
- **the finding itself**: at σ = 0.6, T = 2, Finnerty below the simulation minus four
  standard errors and Ghaidarov above it plus four, both at q = 0 and at r = 5%, q = 2%.

At σ√T = 0.2 it checks for gross error only, because Finnerty's real gap there (about 0.03
points) is narrower than the test's four-standard-error band. The whole DLOM test file runs
in about five seconds.

## The disagreement across inputs

All four at r = 4%, q = 0, in % of value. Each cell reads Chaffe / Finnerty / Ghaidarov /
Longstaff, and Longstaff is bold where it reaches 100% or more. Replay with
`python -m tests.test_opm_dlom --grid`.

| σ | T = 0.25 | T = 0.5 | T = 1 | T = 2 | T = 3 | T = 5 |
|---:|---|---|---|---|---|---|
| 0.3 | 5.5 / 3.4 / 3.5 / 12.5 | 7.4 / 4.9 / 4.9 / 18.1 | 9.8 / 6.8 / 6.9 / 26.3 | 12.6 / 9.6 / 9.8 / 38.6 | 14.2 / 11.7 / 12.1 / 48.7 | 15.8 / 14.8 / 15.6 / 65.8 |
| 0.45 | 8.4 / 5.2 / 5.2 / 19.3 | 11.6 / 7.3 / 7.3 / 28.0 | 15.6 / 10.2 / 10.4 / 41.3 | 20.3 / 14.1 / 14.8 / 61.8 | 23.3 / 16.9 / 18.3 / 78.9 | 26.6 / 21.0 / 23.8 / **108.9** |
| 0.6 | 11.4 / 6.8 / 6.9 / 26.3 | 15.7 / 9.6 / 9.8 / 38.6 | 21.2 / 13.3 / 14.0 / 57.6 | 27.9 / 18.2 / 19.9 / 87.7 | 32.0 / 21.5 / 24.6 / **113.6** | 36.6 / 25.8 / 32.3 / **159.9** |
| 0.75 | 14.3 / 8.5 / 8.7 / 33.6 | 19.7 / 11.9 / 12.3 / 49.8 | 26.7 / 16.3 / 17.5 / 75.3 | 35.1 / 21.8 / 25.2 / **116.7** | 40.2 / 25.3 / 31.2 / **153.0** | 45.6 / 29.1 / 41.3 / **219.3** |
| 0.9 | 17.2 / 10.2 / 10.4 / 41.3 | 23.7 / 14.1 / 14.8 / 61.8 | 32.1 / 19.1 / 21.2 / 94.5 | 42.0 / 24.9 / 30.6 / **148.8** | 47.7 / 28.1 / 38.1 / **197.4** | 53.5 / 31.0 / 50.4 / **287.6** |
| 1.2 | 23.0 / 13.3 / 14.0 / 57.6 | 31.6 / 18.2 / 19.9 / 87.7 | 42.3 / 23.9 / 28.7 / **137.4** | 54.3 / 29.2 / 41.8 / **223.1** | 60.6 / 31.2 / 52.2 / **302.2** | 65.6 / 32.2 / 67.9 / **453.2** |

The spread between methods, in percentage points. Each cell gives max − min over the three
put-based estimators (Chaffe, Finnerty, Ghaidarov), then max − min with Longstaff included.

| σ | T = 0.25 | T = 0.5 | T = 1 | T = 2 | T = 3 | T = 5 |
|---:|---|---|---|---|---|---|
| 0.3 | 2.0 / 9.1 | 2.5 / 13.2 | 3.0 / 19.4 | 3.0 / 29.0 | 2.5 / 37.0 | 1.1 / 51.0 |
| 0.45 | 3.3 / 14.1 | 4.3 / 20.8 | 5.4 / 31.1 | 6.3 / 47.7 | 6.4 / 62.0 | 5.6 / 88.0 |
| 0.6 | 4.5 / 19.4 | 6.1 / 29.0 | 7.9 / 44.2 | 9.7 / 69.5 | 10.5 / 92.1 | 10.8 / 134.1 |
| 0.75 | 5.8 / 25.1 | 7.8 / 38.0 | 10.4 / 59.0 | 13.3 / 94.8 | 14.9 / 127.7 | 16.5 / 190.2 |
| 0.9 | 7.1 / 31.1 | 9.7 / 47.7 | 13.0 / 75.3 | 17.0 / 123.9 | 19.6 / 169.3 | 22.5 / 256.6 |
| 1.2 | 9.6 / 44.2 | 13.4 / 69.5 | 18.4 / 113.5 | 25.0 / 193.9 | 29.4 / 271.0 | 35.7 / 421.0 |

**At ordinary private-company inputs**, meaning the illustrative band of 45–75% volatility over
one to three years:

- **The three put-based estimators are 5.4 to 14.9 points apart.** At the centre, 60% over two
  years, they are 27.9 (Chaffe), 18.2 (Finnerty) and 19.9 (Ghaidarov), a spread of 9.7
  points. Across the band Chaffe is 1.44 to 1.64 times Finnerty.
- **With Longstaff the spread is 31 to 128 points.** Longstaff runs from 41.3% to 153.0% in
  the band and reaches 100% in three of its nine cells.
- **Method choice against input choice.** At the centre, moving volatility from 50% to 70%
  moves Chaffe by 9.9 points, Finnerty by 5.2 and Ghaidarov by 6.9. Moving the holding period
  from 1.5 to 2.5 years moves them by 5.2, 3.9 and 5.2. **So the choice among the three
  put-based methods (9.7 points) is about as large as a plausible disagreement about
  volatility, and larger than one about the holding period.** A wider move, from 45% to 75%,
  shifts Chaffe by 14.8 points, which exceeds the method spread.
- **Where the "disagree by more than any single input" claim holds.** With Longstaff
  included it holds: the four-way spread at the centre is 69.5 points, more than any
  single-input move above, including Longstaff's own (54.9 for 45%→75% and 56.0 for one year
  to three). Among the three put-based methods it does not always hold. There, the method is
  one of the two or three largest decisions in the number, but not always the largest.
- **Only Chaffe depends on the rate.** The other three record the rate and do not use it.

## Caveats that travel with every estimate

- **An analogy, not an identity.** Each formula prices restricted marketability through one
  option analogy. A marketability discount is not an option price, and the analogy is an
  argument, not an identity. Chaffe prices insurance against a fall in value, which a
  marketable holder does not hold either. The average-strike put prices one particular
  selling schedule. Longstaff prices clairvoyance.
- **A judgment applied after the allocation.** The AICPA Accounting and Valuation Guide,
  *Valuation of Privately-Held-Company Equity Securities Issued as Compensation*, treats a
  discount for lack of marketability as a separate judgment applied after the allocation,
  not as an output of it. Nothing in `ovf.opm` applies a discount to an allocation, and
  nothing here should be read as doing so.
- **No conformance claim.** Not with IRC section 409A, the AICPA Guide or the IPEV Valuation
  Guidelines. The formulas are implemented as stated in this document.
- **One of four.** Read each estimate beside the other three, and do not average them.

## For integration (coordinator)

- **Exports.** From `ovf.opm.dlom`: `chaffe_dlom`, `finnerty_dlom`, `longstaff_dlom`,
  `ghaidarov_dlom`, `dlom_comparison` and `DLOM_METHODS`. `DlomEstimate` is already exported
  from `ovf.opm`. There is no averaging helper to export, and there should not be one.
- **[limitations](limitations.md).** A row could record that DLOM estimators are evaluated
  separately, never blended and never applied to an allocation. It could add that
  Longstaff refuses a dividend yield, and that the four attributions are unverified.
- **TODO.** "Evaluate DLOM variants separately" can be ticked for the four closed forms.
  The reviewer items below stay open.
- **`types.py`.** No change was needed. `Discount`'s missing upper bound and `Rate`'s
  sign freedom are both exercised, by DL3 and DL4.
- **The full-suite gate:** `python -m pytest`, `ruff check`, `ruff format --check` on these
  files, and `mypy src` were run before this was reported.

## What a human reviewer must confirm

1. **Each formula against its publication**: Chaffe (1993), Finnerty (2012), Ghaidarov
   (2009) and Longstaff (1995). That includes the dividend terms in Finnerty and Ghaidarov,
   and the absence of the rate from Longstaff.
2. **How Finnerty's 2002 working paper differs from the 2012 article.** Not established
   here. A reader with both documents should state the difference, and confirm whether
   `finnerty_dlom` is the 2012 formula.
3. **The bibliographic details** in every `source` string, and in the Margrabe and
   Henderson–Wojakowski attributions above.
4. **What Ghaidarov's critique of the Finnerty derivation argues.** It was not read, and
   nothing here depends on it.
5. **The illustrative band.** Whether "45–75% volatility, one to three years" is a
   reasonable picture of ordinary private-company inputs, or whether a better band exists.

## What this does not establish

- **That any of the four is a marketability discount.** Each is the value of an option
  payoff. How that payoff relates to the price concession a restricted holder actually
  suffers is an argument made in the literature, and it is not checked here.
- **That the attributions are right.** Author, year and journal were recalled, not checked.
  The algebra is verified; the citations are not.
- **How Finnerty's 2002 and 2012 versions differ**, or whether the formula here is the one
  printed in 2012.
- **Which of Finnerty and Ghaidarov is preferable.** The simulation measures each one's
  distance from the average-strike payoff, and nothing more. A closer match to that payoff
  is not a closer match to a marketability discount.
- **Any empirical calibration.** Nothing here is compared with restricted-stock or pre-IPO
  studies, and nothing claims that any of the four reproduces an observed discount.
- **Richer dynamics.** Uncertain holding periods, stochastic volatility, jumps and a
  liquidity date that depends on the state are all out of scope. Every formula assumes
  geometric Brownian motion over a fixed, known period.
- **Discrete sale windows.** The closed forms assume continuous averaging and a continuously
  monitored maximum. A contractual schedule of sale windows would change both payoffs.
- **A dividend yield in Longstaff**, which is refused rather than extended. The dividend
  convention used for Finnerty and Ghaidarov is the one under which their closed forms price
  the stated payoff. It is not a verified reading of either paper.
- **How a discount is applied.** Whether and where a discount enters a valuation (per
  class, after allocation, to common only) is the valuer's judgment. The AICPA Guide places
  it after the allocation. This module computes estimators and does not apply them.
- **Conformance** with 409A, the AICPA Guide or IPEV. None is claimed.
