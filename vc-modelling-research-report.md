# OVF: research synthesis and evidence map

**Updated:** 15 September 2026. **Status:** research working document.

This version revises the accuracy and novelty claims of an earlier draft. That draft's
claim of "roughly 450 sources verified against the primary text" is not repeated here: no
per-source search or reading record supporting it exists in this workspace, so this version
claims no such verification.

## 1. Central proposition and project scope

Turning venture capital contracts into computable objects with explicit assumptions, and
making financing and exit scenarios independently checkable, is a worthwhile research and
software goal. OVF's contribution should be judged by the scope it supports and by the
verification evidence behind it. "First", "only", "error-free" and "absent from the
literature" are not defended here.

The layers are unchanged:

- **L0:** contract representation, financing events, company and fund payout calculations.
- **L1:** inference, censoring and selection models for explicitly defined returns.
- **L2:** comparison of decision policies under budget and rights constraints.
- **L3:** tool interfaces, independent evaluation protocols and simulation environments.

Today's implementation is a limited subset of L0. The [README](README.md), the
[calculation semantics](docs/semantics.md), the [TODO](TODO.md) and the
[launch plan](docs/launch-plan.md) are the sources for the implemented scope.

## 2. Evidence status

| Claim / topic | Status | Action needed |
|---|---|---|
| A post-money SAFE expresses ownership before the new priced round | Checked against the YC source | Archive reference contract examples as a test suite |
| Later new money and a new pool can also dilute the SAFE investor | Represented explicitly in the corrected model | Design separate scope for existing pools and options |
| A general existence/uniqueness or monotone convergence theorem for the conversion game | Not proved | Define players and rights; look for a theorem or a counterexample |
| Agreement between the solver and an exact oracle on small games | Local test evidence | Do not present as a general theorem; widen the instance space |
| That open source contains zero waterfall/fund projects | Withdrawn | Run a current feature, maintenance and licence comparison |
| That reported tail exponents in the 1.7–2.5 range contradict each other directly | Not defensible without a shared notation and estimand check | Match the exponent and the measured quantity source by source |
| That the Whittle policy is a general optimal solution | Withdrawn | Investigate the structural conditions and finite-horizon performance |
| That a deterministic engine is by itself proof of mathematical correctness | Withdrawn | Independent computation or proof, and explicit assumptions, are required |
| That an OPM engine automatically produces a 409A/IPEV-compliant report | Withdrawn | Valuation purpose, scope and specialist review are required |
| That a JOSS submission is possible in weeks 10–14 | Inconsistent with the current conditions for a new project | Build active public history and demonstrated research use |

## 3. Financing and exit semantics

### SAFE

YC defines post-money SAFE ownership as measured after the SAFE financing but before the
priced round that converts it. For example, in a cap-binding round with no pool, a 10%
SAFE stake falls to 8% once the new investor takes 20%.
[YC documents](https://www.ycombinator.com/documents/), [SAFE explanation](https://www.ycombinator.com/safe).

The comparison of cap, discount and round price, the definition of capitalization, and
which denominator includes the pool must all be explicit. Cooley's three methods describe
negotiated economic conventions; they are not algebra mistakes that disappear once a single
correct method is found.
[Cooley explanation](https://www.cooleygo.com/calculating-share-price-outstanding-convertible-notes-or-safes/).

The current engine solves homogeneous pre- or post-money capped SAFEs under one pricing
convention. The pre-money solution is a normalized, bracketed root search. No claim is made
that this is a matrix solution of the three conventions or of a general mixed-instrument
system. The detailed equations are in the [semantics document](docs/semantics.md).

### The conversion game

The definition of the player comes first: a security position, a share class and a
coordinated beneficial owner are not the same thing. The current model counts each
preferred position as a separate player. Vetoes, class voting and coordination under joint
ownership are out of scope.

For a fixed strategy profile, seniority, participation and caps are computed. The search
result is returned only after checking that no player can gain more than the tolerance by
changing its own decision alone. Exceeding the iteration limit, or cycling, raises an
error. Neither Tarski's applicability nor uniqueness follows from this behaviour.
Generating analytic breakpoints is separate work.

Research questions: under which rights constraints does an equilibrium exist, when is it
multiple, which algorithms give checkable results, and at what cost? Negative results and
counterexamples are valid outputs too.

### Valuation

OPM/Backsolve values a contractual payoff model under particular distribution, timing and
calibration assumptions. Without verifying the model assumptions and the breakpoints, no
409A report or automatic regulatory compliance should be promised. The IRS framework rests
on the reasonable application of a reasonable valuation method; it does not mandate the OPM
alone. [IRS statement](https://www.irs.gov/irb/2007-19_IRB).

"Post-money value is 48% above fair value" does not mean "fair value is 48% lower". If a
single example compares 100 with 148, the shortfall is 48/148 ≈ 32.4%. The reciprocal of a
sample mean ratio is also not the mean of the reciprocal ratios. The Gornall–Strebulaev
results should be re-checked together with their sample and model assumptions.

## 4. Tail econometrics: notation and estimand first

| Definition | Parameter relation | Finite mean | Finite variance |
|---|---|---|---|
| Density `p(x) ∝ x^(-alpha)` | alpha = beta + 1 | alpha > 2 | alpha > 3 |
| Tail `Pr(X>x) ∝ x^(-beta)` | beta = alpha - 1 | beta > 1 | beta > 2 |
| EVT index xi | xi = 1/beta, for a positive Pareto tail | xi < 1 | xi < 1/2 |

For an unbounded Pareto density, `E[X^k]` is finite only when `k < alpha-1`. An earlier
glossary stated that condition correctly but gave the variance threshold as 2 by mistake;
this is corrected. [CSN definitions, Section 2](https://arxiv.org/pdf/0706.1062).

The values reported by Othman, by de Treville and by the Malenko group are not comparable
merely because they carry the same symbol. For each source, record the density/tail
definition, the measured quantity (IPO value or investment multiple), the time horizon and
the sample selection. Even after the notation is corrected, different estimands can produce
different distributions.

The CSN workflow: threshold and exponent estimation, goodness of fit by simulation, and
comparison with alternative distributions. A high p-value does not prove a power law.
Instead of a universal "1,000 observations" rule, run power and parameter-recovery
simulations at the sample size and tail fraction actually available.

A NumPyro selection model is research work separate from that basic workflow. Estimating
right-censoring, left-truncation, measurement error and selection together can create an
identifiability problem. "Zombie" companies should not be treated automatically as terminal
events; states that can be refinanced need multi-state models or an explicit
end-of-observation definition.

## 5. Fund performance and decision research

- For TVPI/DPI/RVPI, dated IRR, KS-PME and Direct Alpha, fix the cash-flow signs, the
  calendar, the index total-return definition, the terminal NAV and the multiple-root policy.
- Removing the effect of a subscription line requires historical borrowing and fee data; a
  unique "true IRR" should not be assumed recoverable from net LP flows alone.
- Takahashi–Alexander is a cash-flow projection. Performance measurement, the fund carry
  ledger and the pacing decision are separate interfaces. If fees are inside the calls, they
  must not be deducted from the cash flow a second time.
- If distributions suffice to complete the catch-up and the terms allow it, the GP reaches
  its target rate; it cannot be said to earn full carry at every exit size.
- Whittle and BwK are candidate policies. A finite horizon, common shocks, budgets and the
  learning structure can break their standard assumptions. Compare them against exact DP and
  explicit heuristics on small problems.
  [Even indexability is not always sufficient](https://arxiv.org/abs/2211.00112).
- A policy performance difference in simulation is not a causal measure of real investors'
  psychological sunk-cost bias. An empirical claim needs its own identification strategy.

## 6. Data, novelty and source-verification plan

Open or accessible data does not mean the required economic fields are observed. For every
research question, record: the estimand, the required fields, the identity matching, the
data dates, failure and exit observations, censoring, access and redistribution terms,
preprocessing, and the effect of what is missing. Form D, Companies House or patent records
should not be assumed to supply fund cash flows and preferred rights on their own.

Keep a per-source record of claim → URL/DOI → page/equation → sample → verification status.
Unchecked rows are not labelled as verified. Current examples such as
[CarryFlow](https://github.com/bhupendra05/carryflow) show that the "zero repositories"
inference cannot be sustained. A licence, quality and coverage review is a separate task;
no quality endorsement of that example is given here.

## 7. Launch and publication strategy

The order: a verified waterfall, SAFE scenarios, a thin MCP interface; then PME, OPM and
tail research, as data and specialist availability allow. Separate product narratives share
one package at the start. [Roadmap](docs/roadmap.md),
[six-part plan](docs/launch-plan.md).

JOSS expects more than six months of active public development history and demonstrated
research use. CFR requires a specific replication target and data; a benchmark publication
requires independent answer verification, a task distribution and comparative results.
[Official JOSS requirements](https://joss.readthedocs.io/en/latest/submitting.html).

An MCP server calling a deterministic tool does not eliminate wrong inputs or an agent's
misinterpretation. "Ground truth as theorem" can only be used where the scope really is
proved and independently verified. The current goal is calculations with explicit
assumptions and reproducible evaluation examples.

## 8. Preserved bibliography — re-verification queue

The list below is carried over from the earlier draft. Its presence here does not mean that
the bibliographic details, the full text, or any claim attributed to an entry were verified
in this revision. Recent publications, working-paper versions and direct quotations in
particular must be verified source by source before use.

### Return distributions and econometrics
- Clauset, A., Shalizi, C. R., & Newman, M. E. J. (2009). Power-law distributions in empirical data. *SIAM Review, 51*(4), 661–703. https://doi.org/10.1137/070710111
- Cochrane, J. H. (2005). The risk and return of venture capital. *Journal of Financial Economics, 75*(1), 3–52.
- de Treville, S., Petty, J. S., & Wager, S. (2014). Economies of extremes: Lessons from venture-capital decision making. *Journal of Operations Management*. https://doi.org/10.1016/j.jom.2014.07.002
- Ewens, M., Jones, C. M., & Rhodes-Kropf, M. (2013). The price of diversifiable risk in venture capital and private equity. *Review of Financial Studies, 26*(8), 1854–1889.
- Kisseleva, K., Mjøs, A., & Robinson, D. T. (2026). Evaluating selection bias in early-stage investment returns. *Journal of Financial and Quantitative Analysis, 61*(2), 841–871. https://doi.org/10.1017/S0022109025101701
- Korteweg, A., & Nagel, S. (2016). Risk-adjusting the returns to venture capital. *Journal of Finance, 71*(3), 1437–1470.
- Korteweg, A., & Sorensen, M. (2010). Risk and return characteristics of venture capital-backed entrepreneurial companies. *Review of Financial Studies, 23*(10), 3738–3772.
- Korteweg, A., & Sorensen, M. (2017). Skill and luck in private equity performance. *Journal of Financial Economics, 124*(3), 535–562.
- Lahr, H. (2023). Fat tails in private equity fund returns: The smooth double Pareto distribution. *International Review of Financial Analysis, 86*, 102471. https://doi.org/10.1016/j.irfa.2022.102471
- Malenko, A., Nanda, R., Rhodes-Kropf, M., & Sundaresan, S. (2023). *HBS Working Paper 21-131.*
- Othman, A. (2019). *Startup growth and venture returns.* AngelList. https://angel.co/pdf/growth.pdf **[not peer-reviewed]**

### Fund economics and performance measurement
- Ang, A., Chen, B., Goetzmann, W. N., & Phalippou, L. (2018). Estimating private equity returns from limited partner cash flows. *Journal of Finance, 73*(4), 1751–1783. https://doi.org/10.1111/jofi.12688
- Brown, G., Ghysels, E., & Gredil, O. (2023). Nowcasting net asset values. *Review of Financial Studies, 36*(3), 945–986. https://doi.org/10.1093/rfs/hhac045 · Code: https://github.com/orgredil/Nowcasting-PE-NAVs
- Choi, W. W., Metrick, A., & Yasuda, A. (2012). A model of private equity fund compensation. In *The Global Macro Economy and Finance* (pp. 271–286). https://doi.org/10.1057/9781137034250_15
- de Zwart, G., Frieser, B., & van Dijk, D. (2012). Private equity recommitment strategies for institutional investors. *Financial Analysts Journal, 68*(3), 81–99.
- Getmansky, M., Lo, A. W., & Makarov, I. (2004). An econometric model of serial correlation and illiquidity in hedge fund returns. *Journal of Financial Economics, 74*(3), 529–609.
- Gourier, E., Phalippou, L., & Westerfield, M. (2024). Capital commitment. *Journal of Finance, 79*(5), 3407–3457. https://doi.org/10.1111/jofi.13382
- Gredil, O., Griffiths, B., & Stucke, R. (2023). Benchmarking private equity: The Direct Alpha method. *Journal of Corporate Finance, 81*, 102360.
- Harris, R. S., Jenkinson, T., Kaplan, S. N., & Stucke, R. (2023). Has persistence persisted in private equity? *Journal of Corporate Finance, 81*, 102361.
- Hüther, N., Robinson, D. T., Sievers, S., & Hartmann-Wendels, T. (2020). Paying for performance in private equity: Evidence from venture capital partnerships. *Management Science, 66*(4), 1756–1782.
- Kaplan, S. N., & Lerner, J. (2017). Venture capital data: Opportunities and challenges. NBER WP 22500.
- Kaplan, S. N., & Schoar, A. (2005). Private equity performance. *Journal of Finance, 60*(4), 1791–1823.
- Litvak, K. (2009). Venture capital limited partnership agreements. *University of Chicago Law Review, 76*(1), 161–218.
- Metrick, A., & Yasuda, A. (2010). The economics of private equity funds. *Review of Financial Studies, 23*(6), 2303–2341.
- Nevins, D., Conner, A., & McIntire, G. (2004). A portfolio management approach to determining private equity commitments. *Journal of Alternative Investments, 6*(4), 32–46.
- Takahashi, D., & Alexander, S. (2002). Illiquid alternative asset fund modeling. *Journal of Portfolio Management, 28*(2), 90–100.

### Company level and contracts
- Bartlett, R. P., III (2003). Understanding price-based antidilution protection. *The Business Lawyer, 59*, 23–42.
- Ewens, M., Gorbenko, A., & Korteweg, A. (2022). Venture capital contracts. *Journal of Financial Economics, 143*(1), 131–158.
- Gornall, W., & Strebulaev, I. A. (2020). Squaring venture capital valuations with reality. *Journal of Financial Economics, 135*(1), 120–143.
- Kaboth, J., Lodowicks, A., Schreiter, M., & Schwetzler, B. (2023). Same same but different. *Review of Quantitative Finance and Accounting, 60*(3), 877–914.
- Kaplan, S. N., & Strömberg, P. (2003). Financial contracting theory meets the real world. *Review of Economic Studies, 70*(2), 281–315.
- Y Combinator. (2023). *Postmoney safe with valuation cap*, v1.2. CC BY-ND 4.0.

### Decision theory and staged financing
- Badanidiyuru, A., Kleinberg, R., & Slivkins, A. (2018). Bandits with knapsacks. *Journal of the ACM, 65*(3), 1–55.
- Bergemann, D., & Hege, U. (1998). Venture capital financing, moral hazard, and learning. *Journal of Banking & Finance, 22*(6–8), 703–735.
- Bergemann, D., & Hege, U. (2005). The financing of innovation. *RAND Journal of Economics, 36*(4), 719–752. *(no DOI assigned; JSTOR 4135254)*
- Chen, T., Embrechts, P., & Wang, R. (2025). An unexpected stochastic dominance. *Operations Research, 73*(3), 1336–1344.
- Ewens, M., Nanda, R., & Rhodes-Kropf, M. (2018). Cost of experimentation and the evolution of venture capital. *Journal of Financial Economics, 128*(3), 422–442.
- Gompers, P., Gornall, W., Kaplan, S. N., & Strebulaev, I. A. (2020). How do venture capitalists make decisions? *Journal of Financial Economics, 135*(1), 169–190.
- Guler, I. (2007). Throwing good money after bad? *Administrative Science Quarterly, 52*(2), 248–285.
- Kerr, W. R., Nanda, R., & Rhodes-Kropf, M. (2014). Entrepreneurship as experimentation. *Journal of Economic Perspectives, 28*(3), 25–48.
- Post, T. (2003). Empirical tests for stochastic dominance efficiency. *Journal of Finance, 58*(5), 1905–1931.
- Sorensen, M. (2007). How smart is smart money? *Journal of Finance, 62*(6), 2725–2762.
- Whittle, P. (1988). Restless bandits. *Journal of Applied Probability, 25A*, 287–298.

### ML, agents and reproducibility
- Chen, A. Y., & Zimmermann, T. (2022). Open source cross-sectional asset pricing. *Critical Finance Review, 11*(2), 207–264.
- Chen, M., Ternasky, J., Alican, F., & Ihlamur, Y. (2025). *VCBench.* arXiv:2509.14448
- Kapoor, S., & Narayanan, A. (2023). Leakage and the reproducibility crisis in ML-based science. *Patterns, 4*(9), 100804.
- Kapoor, S., et al. (2024). REFORMS. *Science Advances, 10*(18), eadk3452.
- Khamphukun, W., & Narkbunnum, W. (2026). A leakage-controlled, calibration-first evaluation. *Information, 17*(7), 702. · Code: https://doi.org/10.5281/zenodo.21330297
- Lyu, S., et al. (2021). *Graph neural network based VC investment success prediction.* arXiv:2105.11537
- Peyton Jones, S., & Eber, J.-M. (2000). Composing contracts. *ICFP 2000.* https://doi.org/10.1145/351240.351267
- Retterath, A., & Braun, R. (2020). *Benchmarking venture capital databases.* SSRN 3706108
- Vismara, S., et al. (2026). Can large language models help venture capitalists? *International Review of Financial Analysis, 109*, 104748.
- Yao, S., Shinn, N., Razavi, P., & Narasimhan, K. (2024). *τ-bench.* arXiv:2406.12045
- Żbikowski, K., & Antosiuk, P. (2021). A machine learning, bias-free approach. *Information Processing & Management, 58*(4), 102555.

### Standards and infrastructure
- AICPA. *Valuation of portfolio company investments of venture capital and private equity funds.* https://doi.org/10.1002/9781119663188
- ILPA. (2019). *Private Equity Principles 3.0.*
- IPEV. (2025, December). *International Private Equity and Venture Capital Valuation Guidelines.*
- Open Cap Table Coalition. *Open Cap Format (OCF).* https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF

## 9. Limitations and use of AI

This work is not a systematic review or a complete bibliographic audit. The code and
mathematics checks produce local evidence for the model whose scope is documented.
Applying this to financial or legal contracts still requires independent domain review and
conformance with the original documents.

Earlier research notes were prepared with AI assistance. In this revision, AI assisted with
code review, implementation, testing and editing. Before public publication, human
responsibility, source verification and the disclosure requirements of the chosen venue
must be satisfied.
