# PME source ledger

Status 2026-09-15, for engine `pme-v1`. This is the claim-by-claim verification record
behind [pme](pme.md) and `docs/pme-contract.md`. A row records where a claim was read, how,
and how far that reading can be trusted. A claim that is not in this ledger is not
sourced.

## How to read this ledger

| Status | Meaning |
|---|---|
| `VERIFIED-primary` | Read in the primary document, or in the author's own version of it. The version is named, and page numbers refer to that version. |
| `VERIFIED-secondary` | The primary could not be read. A named secondary source that restates it was read instead. |
| `UNVERIFIED` | Paywalled, blocked or not found. The row says what was tried. |
| `CONTRADICTED` | A source read here says something different from the claim as it was previously stated (in the contract, the task brief or the archived research report). |
| `DERIVED` | Not a source claim: algebra proved in [Derivations](#derivations), checkable by the reader. |

Reading rules applied:

- Quotes are verbatim from the fetched page, from text extracted from the PDF, or, for
  equations, from the rendered page image.
- A quote marked † came through a summarizing web fetch, and its exact wording is
  approximate.
- "PDF p." is the page count of the file read; "printed p." is the number on the page.
- A working-paper page is never presented as a journal page.
- No page, equation or footnote number appears here unless it was seen.
- Sources were fetched 2026-09-15.

### Summary

| Status | Rows |
|---|---|
| `VERIFIED-primary` | 50 |
| `VERIFIED-secondary` | 7 |
| `UNVERIFIED` | 11 |
| `CONTRADICTED` | 2 (both resolved: see [Consequences](#consequences)) |
| `DERIVED` | 12 (D1–D9, plus S1.6, S3.7 and S11.7, which rest on them) |

**No source contradicts any formula, sign or compounding convention in the contract, or
the parity claim.** One attribution was contradicted: Kaplan and Schoar's PME has no NAV
term. The contract was amended on 2026-09-15.

<a id="s1"></a>
## S1 · KS-PME: Kaplan & Schoar (2005); Harris, Jenkinson & Kaplan (2014)

Kaplan, S. N., & Schoar, A. (2005). Private equity performance: Returns, persistence, and
capital flows. *Journal of Finance*, 60(4), 1791–1823.
https://doi.org/10.1111/j.1540-6261.2005.00780.x
- Read: NBER WP 9807 (2003), https://www.nber.org/system/files/working_papers/w9807/w9807.pdf
  ("WP").
- Read: the journal text hosted by the author at https://web.mit.edu/aschoar/www/KaplanSchoar2005.pdf
  ("JF copy"). No page numbers are cited from it.

Harris, R. S., Jenkinson, T., & Kaplan, S. N. (2014). Private equity performance: What do
we know? *Journal of Finance*, 69(5), 1851–1882. https://doi.org/10.1111/jofi.12154
- Read: NBER WP 17874 (2012).

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S1.1 | KS-PME is the ratio of index-discounted distributions to index-discounted contributions; above 1 means the fund beat the index. | Kaplan & Schoar, WP | §3.1 "Private Equity Performance", printed p. 8 | `VERIFIED-primary` | "The PME measures the discounted value of the cash outflows of the fund relative to the discounted value of the cash inflows (all net of fees), where discounting is undertaken using the total return to the S&P 500. [...] A fund with a PME greater than one outperformed the S&P 500 (net of all fees)." "Outflows of the fund" are distributions to LPs; the direction is fixed by "greater than one outperformed". |
| S1.2 | *As previously stated in the contract:* Kaplan & Schoar define KS-PME as `(FV(D) + NAV_T) / FV(C)`, NAV included. | Kaplan & Schoar, WP and JF copy | WP Table 5 note; WP §2 sample criteria | `CONTRADICTED` → contract amended | "We base our IRR calculations only on the actual csh flows of funds, not reported net asset value. Therefore we concentrate on funds that have already realized most of their investments." (WP Table 5 note; same wording in the JF copy). The sample criteria include funds "[...] whose returns are unchanged for at least the final six quarters we observe; and (3) whose reported unrealized value is less than 10% [of committed capital]". KS use largely liquidated funds and no NAV; the NAV term is S1.4's. |
| S1.3 | The KS index is the S&P 500 total return. | Kaplan & Schoar, WP and JF copy | WP printed p. 8; JF copy, PME paragraph | `VERIFIED-primary` (WP) | The WP says "total return to the S&P 500". The JF copy says only "The benchmark we use here to discount funds are the returns on the S&P 500 index." Treat "total return" as the WP's wording. |
| S1.4 | The residual value enters the PME as a terminal distribution, and both sides are discounted at the index total return. | Harris, Jenkinson & Kaplan, NBER WP 17874 | performance-measures paragraph, PDF p. 12 | `VERIFIED-primary` (WP) | "The PME calculation discounts (or invests) all cash distributions and residual value to the fund at the public market total return and divides the resulting value by the value of all cash contributions discounted (or invested) at the public market total return. A PME greater than one indicates the fund outperformed the public market net of fees." The published wording was not read. |
| S1.5 | KS-PME ignores beta; with a beta above one it overstates the risk-adjusted return. | Kaplan & Schoar, WP | printed p. 8 | `VERIFIED-primary` (WP) | "If private equity returns have a beta greater than one, PME will [overstate the true risk-adjusted returns to private equity]." The bracketed part is the continuation as reported by the research pass; the first clause was re-checked in the extracted text. |
| S1.6 | The forward-valued form `(FV(D)+NAV_T)/FV(C)` equals the discounted form. | — | [D2](#derivations) | `DERIVED` | Multiply numerator and denominator by `I_T/I_0`. |

<a id="s2"></a>
## S2 · Economic interpretation: Sorensen & Jagannathan (2015); Korteweg & Nagel (2016)

Sorensen, M., & Jagannathan, R. (2015). The public market equivalent and private equity
performance. *Financial Analysts Journal*, 71(4), 43–50. https://doi.org/10.2469/faj.v71.n4.4
- Unreadable: SSRN returned 403, Taylor & Francis a bot check, ResearchGate failed.

Korteweg, A., & Nagel, S. (2016). Risk-adjusting the returns to venture capital.
*Journal of Finance*, 71(3), 1437–1470. https://doi.org/10.1111/jofi.12390
- Read: NBER WP 19347, https://www.nber.org/system/files/working_papers/w19347/w19347.pdf

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S2.1 | KS-PME is a valid performance measure for an LP with log utility whose total wealth earns the market return, i.e. an SDF valuation. | Secondary: Hüther, Schmid & Steri, "Credit Market Equivalents…", working paper, Nov 2022, https://www.runi.ac.il/media/apifj5zs/credit-marker.pdf ; Wikipedia, "Public Market Equivalent" | Hüther et al. p. 8; Wikipedia § on the KS-PME | `VERIFIED-secondary` | Hüther et al.: "Sorensen and Jagannathan (2015) and Korteweg and Nagel (2016) point out that the public market equivalent (PME) is an application of a stochastic discount factor (SDF) valuation in the special case of log-utility (a = 0 and b = 1), which is equivalent to the SDF of an investor who is fully invested in the public stock market." Wikipedia quotes S&J: "The [Kaplan Schoar] PME provides a valid economic performance measure when the investor ("LP") has log-utility preferences and the return on the LP's total wealth equals the market return." |
| S2.2 | S&J's stated consequences: no PE beta needs to be computed, and the index should approximate the investor's wealth portfolio. | Secondary: CBS research-portal abstract, https://research.cbs.dk/en/publications/the-public-market-equivalent-and-private-equity-performance/ | abstract | `VERIFIED-secondary` † | † "(1) one need not compute betas of PE investments, and any changes in PE cash flow betas… are automatically taken into account; (2) the public market index used in evaluations should be the one that best approximates the wealth portfolio of the investor". S&J do **not** say KS-PME "assumes beta one"; that caveat is Kaplan & Schoar's own (S1.5). |
| S2.3 | S&J full text: exact wording, page numbers, stated limits. | S&J (2015) | — | `UNVERIFIED` (paywalled/blocked) | Cite S&J only through S2.1–S2.2 until the article is read. |
| S2.4 | Korteweg & Nagel's GPME generalizes the PME; the PME implicitly fixes the equity premium to the variance of the market return. | Korteweg & Nagel, NBER WP 19347 | abstract; PDF pp. 3–4 | `VERIFIED-primary` (WP) | Abstract: "Our approach generalizes the Public Market Equivalent (PME) measure commonly used in the private-equity literature." PDF p. 4: "It implicitly assumes that the equity premium… is equal to the variance of the market return. Our approach, which we label Generalized Public Market Equivalent (GPME), avoids this restriction by relaxing the assumption that a = 0 and b = 1." PDF p. 3: "One special case is the log-utility Capital Asset Pricing Model (CAPM) with a = 0, b = 1". |

<a id="s3"></a>
## S3 · Direct Alpha: Gredil, Griffiths & Stucke

Gredil, O. R., Griffiths, B., & Stucke, R. (2023). Benchmarking private equity: The direct
alpha method. *Journal of Corporate Finance*, 81, 102360.
https://doi.org/10.1016/j.jcorpfin.2023.102360
- Working papers: SSRN 2403521 (2014), and a later version as SSRN 4174563.
- Read: the 2014 SSRN first draft, headed "First draft - comments welcome" and dated
  "February 28, 2014", at https://allocatortraining.com/wp-content/uploads/2023/06/Benchmarking-PE-Direct-Alpha-Method.pdf
  ("2014 draft"). Printed page and equation numbers are that draft's; the 2023 numbering
  may differ.

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S3.1 | Published citation: JCF 81 (2023), article 102360. | Crossref metadata for the DOI | — | `VERIFIED-primary` | August 2023. |
| S3.2 | The published 2023 text matches the 2014 draft on everything below. | JCF 2023 | — | `UNVERIFIED` (paywalled) | SSRN, ScienceDirect and ResearchGate all returned 403. |
| S3.3 | `a` is the IRR of the future-valued (index-compounded) contributions and distributions plus the NAV. | 2014 draft | eq. (17), printed p. 11; Appendix A | `VERIFIED-primary` (2014 draft) | Eq. (17): `a = IRR(FV(C), FV(D), NAV_PE)`. Appendix A: "Consequently, a is just the IRR of the future values of the cash flows and α is its equivalent log rate." |
| S3.4 | Continuous alpha is `ln(1+a)/Δ`, with `Δ` the period for which alpha is computed. | 2014 draft | eq. (16), printed p. 11; eq. (25), Appendix A | `VERIFIED-primary` (2014 draft) | Eq. (16): `α = ln(1 + a)/Δ`, "where a is the discrete-time analog of α" and "Δ is the time interval for which alpha is computed (typically one year)". Eq. (25): `1 + a = exp(αΔ)`. With an annual XIRR, `Δ = 1`, so the contract's `alpha_continuous = ln(1+a)` agrees. |
| S3.5 | KS-PME in this notation is `(ΣFV(D) + NAV_PE) / ΣFV(C)`. | 2014 draft | eq. (14) | `VERIFIED-primary` (2014 draft) | Agrees with the contract. |
| S3.6 | Direct Alpha and KS-PME agree in sign. | 2014 draft | §III.C, printed p. 13; eq. (18); footnote 11 | `VERIFIED-primary` for the zero point; sign equivalence `DERIVED` (D5) | "Note that, by construction, Direct Alpha is zero whenever KS-PME equals one." Eq. (18) defines Direct Alpha Duration `= ln(KS-PME)/ln(1 + Direct Alpha)`, and footnote 11 says: "It is defined and positive whenever KS-PME is not exactly equal to one." A positive ratio implies equal signs. But footnote 11, read literally, fails for a series whose first net is positive: in D5's counterexample the duration is `ln 0.5 / ln 2 = −1`. The contract states the precondition. |
| S3.7 | Netting the compounded series per date preserves each date's sign. | — | [D7](#derivations) | `DERIVED` | — |

The research pass also noted that the draft's eq. (27) appears to swap the distribution and
contribution sums relative to the IRR identity. That was not re-checked here, and nothing
depends on it.

<a id="s4"></a>
## S4 · PME+: Rouvinez (2003)

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S4.1 | *As given in the task brief:* Rouvinez (2003) appeared in *Private Equity International*. | Gredil et al. 2014 draft, reference list | references | `CONTRADICTED` (venue) | The reference list reads "Rouvinez, Christophe, 2003, Private Equity Benchmarking with PME+, Venture Capital Journal, August, 34-38." A VCJ page dated 1 August 2003 exists at https://www.venturecapitaljournal.com/private-equity-benchmarking-with-pme/ (registration-walled). Cite it as *Venture Capital Journal*. |
| S4.2 | Rouvinez's own text. | Rouvinez (2003), VCJ | — | `UNVERIFIED` (registration wall) | — |
| S4.3 | Scale factor `s = (FV(C) − NAV_T) / FV(D)`, chosen so that the index position ends at the fund's NAV. | US Patent 7,698,196 B1 (Rouvinez & Kubr, Capital Dynamics), https://patents.google.com/patent/US7698196B1/en ; Gredil et al. 2014 draft | patent description; draft eqs. (5)–(6), printed p. 7 | `VERIFIED-primary` (the method's author, via the patent) | Patent: "the scaling factor can be selected so that the end balance in the benchmark portfolio valuation matches the end value of the private equity asset, as measured, e.g., by its NAV." The draft (read from the rendered page) gives eq. (5) `NAV_PE = Σ FV(C) − s·Σ FV(D)` and eq. (6) `s = (Σ FV(C) − NAV_PE) / Σ FV(D)`. Both agree with the contract. |
| S4.4 | PME+ IRR `= IRR(C, sD, NAV_PE)`; spread `= IRR_PE − IRR_PME+`. | Gredil et al. 2014 draft | eqs. (7)–(8), printed p. 7 | `VERIFIED-secondary` (Gredil et al., for Rouvinez) | Read from the rendered page. Agrees with the contract. |
| S4.5 | `s` can be negative; PME+ is undefined without distributions; it is not an investable strategy. | Gredil et al. 2014 draft | printed pp. 7–8 | `VERIFIED-primary` (2014 draft) | "PME+ cannot be calculated, by definition, for younger PE portfolios, if no distributions have yet taken place; and in cases in which only a few distributions have occurred, the scaling factor s may actually be negative and turn distributions into additional contributions." "[...] PME+ is a non-causal process that cannot be followed by a real investor." Agrees with the contract's `FV(D) == 0 → s = None` and its `s < 0` flag. |
| S4.6 | PME+ was patented; the patent is no longer in force. | Gredil et al. 2014 draft, footnote 6; Google Patents | printed p. 7; legal-status field | `VERIFIED-secondary` (Google Patents) | Footnote 6: "Note that Capital Dynamics has been granted a U.S. patent for PME+ in 2010 (#7,698,196)." Google Patents shows "Expired - Fee Related" with its own disclaimer: "The legal status is an assumption and is not a legal conclusion." This is not a legal opinion; confirm with the USPTO if it matters. |

<a id="s5"></a>
## S5 · Long–Nickels index comparison method (1996)

Long, A. M., III, & Nickels, C. J. (1996, February 13). *A private investment benchmark.*
AIMR Conference on Venture Capital Investing. The University of Texas System.
- Read: http://alignmentcapital.com/pdfs/research/icm_aimr_benchmark_1996.pdf (17 pages;
  every footer reads "CONFIDENTIAL · Page n of 17").
- The document names "The University of Texas System". It does not name UTIMCO.

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S5.1 | The document, authors, venue and date. | Long & Nickels (1996) | title block | `VERIFIED-primary` | — |
| S5.2 | The procedure: invest each contribution in the index, grow it by the linked index, treat each distribution as a withdrawal, and take the final value as the terminal flow of an IRR. | Long & Nickels | numbered procedure, steps 1–5, Page 8 of 17 | `VERIFIED-primary` | "1. Treat the first (negative) cash flow as having been invested in the relevant index. 2. Using an end-of-period assumption, grow that cash flow over the time between the first and second cash flow at the rates indicated by the linked index. 3. At the point of the next cash flow, grow the new net amount [...] Note that the next cash flow could be a distribution from the private investment, which would be treated as a withdrawal from the index investment. [...] 5. Compute the IRR of the investment using the portfolio value at the current report date [...] as the final cash flow". This matches the contract's recursion, in dollars rather than units. |
| S5.3 | Footnote 5: the terminal value can be negative, a net short position. | Long & Nickels | footnote 5, Page 8 of 17 | `VERIFIED-primary` | "If a private investment greatly outperforms the index because it makes frequent large distributions it is possible for the final value determined by the index comparison to be negative. In effect, frequent large withdrawals from the index result in a net short position in the index comparison. See the numerical example in APPENDIX B on page 14." |
| S5.4 | The original states the method in prose, with no equations. | Long & Nickels | whole text layer | `VERIFIED-primary` | Confirmed for the text layer. The appendix tables and graphs did not extract as text and were not viewed. Every formula in circulation (including the contract's) is a reconstruction; see S5.6. |
| S5.5 | Long & Nickels read a negative final value as outperformance. | Long & Nickels | Page 12 of 17; Appendix B, Page 15 of 17 | `VERIFIED-primary` | "[...] be considered overperformance in every case (see APPENDIX B on page 14)". Appendix: "[...] the result is, in effect, a short position on the S&P." |
| S5.6 | Closed form `NAV_ICM = ΣFV(C) − ΣFV(D)`; `IRR_ICM = IRR(C, D, NAV_ICM)`. | Gredil et al. 2014 draft | eqs. (2)–(3), printed p. 6 | `VERIFIED-primary` (2014 draft); see also [D4](#derivations) | Agrees with the contract. |
| S5.7 | In about 5–10% of cases the ICM series prevents computing an IRR. | Gredil et al. 2014 draft | printed pp. 6–7 | `VERIFIED-primary` (2014 draft) | "In about 5-10% of all cases the resulting stream of cash flows effectively prevents the calculation of the IRRICM and, hence, the ΔIRR." |

<a id="s6"></a>
## S6 · Cambridge Associates mPME

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S6.1 | Cambridge Associates has published the mPME algebra in a primary source. | CA website, CA benchmark books, CA "A Framework for Benchmarking Private Investments" (2014); the CA 2013 note Gredil et al. cite ("Private Equity and Venture Capital Benchmarks - An Introduction for Readers of Quarterly Commentaries") | — | `UNVERIFIED` (not found) | No CA document with equations was found. The 2013 note could not be located, and the 2013 press release could not be fetched. Absence cannot be proved by search, so the archived report's "never published" stays unverified. |
| S6.2 | CA's own description: index shares are bought and sold on the fund's schedule, distributions are taken in the same proportion as the fund's, and negative NAV is avoided. | Cambridge Associates, *US Private Equity Benchmark Book*, Q2 2025, methodology, https://www.cambridgeassociates.com/wp-content/uploads/2025/10/WEB-2025-Q2-USPE-Benchmark-Book.pdf | methodology page | `VERIFIED-primary` (verbal only) | "The public index's shares are purchased and sold according to the private fund cash flow schedule, with distributions calculated in the same proportion as the private fund, and the mPME NAV (the value of the shares held by the public equivalent) is a function of mPME cash flows and public index returns." It also says mPME works "while avoiding the "negative NAV" issue inherent in some PME methodologies". |
| S6.3 | *Archived report:* Gredil et al.'s eq. 11 mixes the period index `i` and the terminal index `n` in one recursion. | Gredil et al. 2014 draft | eqs. (9)–(11), printed p. 8, read from the rendered page | `VERIFIED-primary` (2014 draft): the error is present | Eq. (9): `D_mPME,i = (D_i / (D_i + NAV_PE,i)) · (NAV_mPME,i−1 · m_i/m_{i−1} + C_i)`, which is consistent. Eq. (11): `NAV_mPME,n = (1 − D_i / (D_i + NAV_PE,n)) · (NAV_mPME,n−1 · m_n/m_{n−1} + C_i)`, which mixes `D_i` and `C_i` with `NAV_PE,n`, `NAV_mPME,n−1` and `m_n/m_{n−1}`. Read consistently, `i` throughout, it is the NAV recursion that goes with eq. (9). |
| S6.4 | The published 2023 version has the same eq. 11. | JCF 2023 | — | `UNVERIFIED` (paywalled) | Do not cite the 2023 equation numbers for mPME until they are read. |
| S6.5 | Consistent reconstruction: weight `w_t = D_t / (D_t + NAV_t)`; `NAV_mPME,t = (1 − w_t)(NAV_mPME,t−1 · I_t/I_{t−1} + Call_t)`; `Dist_mPME,t = w_t (···)`; `IRR_mPME = IRR(Call, Dist_mPME, NAV_mPME,T)`. | Wikipedia, "Public Market Equivalent" (raw wikitext) | mPME section | `VERIFIED-secondary` (Wikipedia) | Agrees with Gredil eq. (9), with a consistently indexed eq. (11), and with CA's prose in S6.2. Wikipedia describes it as "we compute the weight of the distribution in the private investment, and remove the same weight from the public one." |
| S6.6 | mPME dates from 2013. | Wikipedia (citing a CA press release, "released [...] in October 2013"); Gredil et al. 2014 draft ("developed by Cambridge Associates in the later 2000s") | — | `UNVERIFIED` | The two secondary sources differ, and the CA press release was not read. The contract's "(2013)" is the publication date of the method as cited, not its development date. |

<a id="s7"></a>
## S7 · Spreadsheet XIRR

Microsoft Support, "XIRR function",
https://support.microsoft.com/en-us/office/xirr-function-de1242ec-6477-445b-b11b-a303ad9adc9d
- Read in raw HTML. The formula is an image, and was read from that image.

LibreOffice Help, "XIRR", https://help.libreoffice.org/latest/en-US/text/scalc/01/04060118.html
- Read in raw HTML.

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S7.1 | `0 = Σ_{i=1}^{N} P_i / (1+rate)^((d_i − d_1)/365)` | Microsoft | formula image and variable list | `VERIFIED-primary` | "di = the ith, or last, payment date." "d1 = the 0th payment date." "Pi = the ith, or last, payment." |
| S7.2 | Iteration from a guess; 0.000001 percent accuracy; `#NUM!` after 100 tries. | Microsoft | Remarks | `VERIFIED-primary` | "Excel uses an iterative technique for calculating XIRR. Using a changing rate (starting with guess), XIRR cycles through the calculation until the result is accurate within 0.000001 percent. If XIRR can't find a result that works after 100 tries, the #NUM! error value is returned." |
| S7.3 | The default guess is 10%. | Microsoft | Syntax | `VERIFIED-primary` | "If omitted, guess is assumed to be 0.1 (10 percent)." |
| S7.4 | At least one positive and one negative value are required. | Microsoft | Syntax and Remarks | `VERIFIED-primary` | "XIRR expects at least one positive cash flow and one negative cash flow; otherwise, XIRR returns the #NUM! error value." |
| S7.5 | Date handling. | Microsoft | Remarks | `VERIFIED-primary` | "Numbers in dates are truncated to integers." "If any number in dates precedes the starting date, XIRR returns the #NUM! error value." "Dates may occur in any order." So `d_1` is the first **listed** date, and it must be the earliest. The module uses the earliest date as `t0`; by D1 this gives the same IRR. |
| S7.6 | Published example: 0.373362535 (37.34%). | Microsoft | Example | `VERIFIED-primary` | Values −10,000 / 2,750 / 4,250 / 3,250 / 2,750 on 1-Jan-08 / 1-Mar-08 / 30-Oct-08 / 15-Feb-09 / 1-Apr-09, "=XIRR(A3:A7, B3:B7, 0.1)", described as "The internal rate of return (0.373362535 or 37.34%)". Recomputed here with days/365 and a bracketing solver: 0.3733625335. |
| S7.7 | LibreOffice uses a 365-day year ignoring leap years, a first date as the start, and a 10% default guess. | LibreOffice | XIRR entry | `VERIFIED-primary` | "The calculation is based on a 365 days per year basis, ignoring leap years." "The first pair of dates defines the start of the payment plan. All other date values must be later, but need not be in any order." "The default is 10%." Example: "XIRR(B1:B5; A1:A5; 0.1) returns 0.1828 or 18.28%." The page states no formula and no iteration limit. |
| S7.8 | Practitioners hit XIRR's zero-first-value error. | ILPA, Performance Template Suggested Guidance, Granular Methodology (Jan 2025), https://ilpa.org/wp-content/uploads/2025/01/ILPA-Performance-Template-Suggested-Guidance-Granular-Methodology.pdf | "Miscellaneous" section | `VERIFIED-primary` | "Excel's XIRR function will return an error value if the first value in the column is a zero." This is one reason the contract drops zero per-date nets. |

<a id="s8"></a>
## S8 · Root counting: Descartes' rule for exponential sums; IRR uniqueness

Jameson, G. J. O. (2006). Counting zeros of generalised polynomials: Descartes' rule of
signs and Laguerre's extensions. *Mathematical Gazette*, 90(518), 223–234.
- Read: the author's copy, https://www.maths.lancs.ac.uk/~jameson/zeros.pdf, whose header
  reads "Math. Gazette 90, no. 518 (2006), 223–234".
- Theorem and proposition numbers are the author's copy's. No page numbers are cited from it.

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S8.1 | For `F(x) = Σ a_j e^{p_j x}` on all of ℝ (and `f(t) = Σ a_j t^{p_j}` on t > 0) with distinct real exponents, the zeros counted with multiplicity are at most the sign changes of the coefficients. | Jameson (2006) | Theorem 3.1, with definitions (1)–(2) | `VERIFIED-primary` | "Theorem 3.1. Let F be defined by (2), and f by (1), with p1 > · · · > pn. Then Z(F) and Z(f) are not greater than S[(aj)]." Definition (2): "F(x) = Σ aj e^(pj x) (x ∈ R)"; zeros are "counted with their orders". |
| S8.2 | Parity: the sign-change count minus the zero count is even. | Jameson (2006) | Proposition 3.6 and its proof | `VERIFIED-primary` | "Proposition 3.6. Let F be defined by (2). Then S[(aj)] − Z(F) is an even integer." The proof is the end-sign argument: "For sufficiently large x, F(x) is dominated by the term a1e^(p1x), so has the same sign as a1. For sufficiently large −x, it has the same sign as an." **This confirms the contract's parity claim.** |
| S8.3 | Zero orders are preserved between the exponential and power forms. | Jameson (2006) | Lemma 2.4 | `VERIFIED-primary` | "If F has a zero of order k at x0, then f has a zero of order k at e^x0. Hence Z(f) = Z(F)." Under `1 + r = e^δ` the same holds in `r` (D6). |
| S8.4 | Pólya & Szegő, *Problems and Theorems in Analysis II*, Part V, contains these results. | Jameson (2006), citing [P-Sz] | Jameson's historical remarks | `VERIFIED-secondary` (Jameson) | Jameson: "These results of Laguerre were reproduced in the form of exercises, and partly with new methods, in [P-Sz], Part V, chapter 1", naming "(Part V, exercises 80, 83)" and citing the German edition. The book itself was not readable (archive.org lending only). Cite Jameson in docstrings; do not cite a Pólya–Szegő problem number not seen here. |
| S8.5 | Norstrom (1972) gives a sufficient condition for a unique nonnegative IRR. | Norstrom, C. J. (1972). A sufficient condition for a unique nonnegative internal rate of return. *JFQA*, 7(3), 1835–. https://doi.org/10.2307/2329806 (Crossref: first page 1835, June 1972). Secondary: Bernhard (1979), https://doi.org/10.2307/2330506 | first-page extract of Bernhard | `VERIFIED-secondary` (Bernhard 1979) | Bernhard says Norström presented "a very simple sufficient condition for detecting whether a given pattern of cash flows over time has a unique nonnegative internal rate of return." The exact criterion (cumulative sums changing sign once) and the end page were not read. The related mathematics is Jameson's Theorem 4.7 (S8.7). |
| S8.6 | Hazen (2003): multiple IRRs are meaningful, each a return on a different investment stream. | Hazen, G. B. (2003). A new perspective on multiple internal rates of return. *The Engineering Economist*, 48, 31–51. https://doi.org/10.1080/00137910308965050 | — | `UNVERIFIED` (paywalled) | The citation is confirmed by Semantic Scholar. The abstract was not read; only search snippets were seen. [pme](pme.md) flags it. |
| S8.7 | A cumulative-sum bound on positive-rate roots. | Jameson (2006) | Theorem 4.7 | `VERIFIED-primary` | With `Aj = a1 + … + aj`: "Then (without the condition An = 0), Z[F, (0, ∞)] and Z[f, (1, ∞)] are not greater than S[(Aj)]." Mapping this to Norstrom's criterion is not done here. |

<a id="s9"></a>
## S9 · Day count

ISDA, *2006 ISDA Definitions*, §4.16 and §4.13.
- Read: ISDA's blackline of the 2000 against the 2006 Definitions,
  https://www.isda.org/a/smMDE/Blackline-2000-v-2006-ISDA-Definitions.pdf. The 2006 text
  was read through the marked deletions.

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S9.1 | ACT/ACT (ISDA): days in leap years / 366 + days in other years / 365. | ISDA 2006 | §4.16(b) | `VERIFIED-primary` | "[...] divided by 365 (or, if any portion of that Calculation Period or Compounding Period falls in a leap year, the sum of (i) the actual number of days in that portion of the Calculation Period or Compounding Period falling in a leap year divided by 366 and (ii) the actual number of days in that portion of the Calculation Period or Compounding Period falling in a non-leap year divided by 365)". |
| S9.2 | Actual/365 (Fixed): actual days / 365. | ISDA 2006 | §4.16(d) (the 2000 text's (c); the 2006 edition inserts a new (c)) | `VERIFIED-primary` | "[...] the actual number of days in the Calculation Period or Compounding Period in respect of which payment is being made divided by 365". |
| S9.3 | A period includes its first day and excludes its last. | ISDA 2006 | §4.13 | `VERIFIED-primary` | "each period from, and including, one Period End Date [...] to, but excluding, the next following applicable Period End Date". So the days "falling in a leap year" run from the start date to the day before the end date. |
| S9.4 | Excel and LibreOffice XIRR use ACT/365F. | Microsoft; LibreOffice | S7.1, S7.7 | `VERIFIED-primary` | Microsoft: "All succeeding payments are discounted based on a 365-day year", with `/365` in the formula. LibreOffice: "ignoring leap years". "ACT/365F" is this project's label; neither vendor uses the ISDA name. The published example (S7.6) reproduces with days/365. |

<a id="s10"></a>
## S10 · Practice standards

- ILPA, *Performance Template Suggested Guidance, Granular Methodology*, released January 2025 (URL in S7.8).
- ILPA, *Principles 3.0* (2019), https://ilpa.org/wp-content/uploads/2019/06/ILPA-Principles-3.0_2019.pdf
- CFA Institute, *2020 GIPS Standards for Firms* (© 2019), https://www.gipsstandards.org/wp-content/uploads/2021/03/2020_gips_standards_firms.pdf

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S10.1 | The ILPA Performance Template asks for since-inception performance on fund–investor cash flows: net IRR and TVPI with and without subscription facilities, gross optional. | ILPA Granular Methodology (2025) | Fund Performance table section | `VERIFIED-primary` | "The Fund Performance table aims to provide investors with the following since-inception performance measures, which are based on cash flows between the Fund and its investors". "The net IRR and TVPI both with and without the impact of fund-level subscription facilities". "The gross IRR and MOIC both with and without the impact of fund-level subscription facilities (Optional metric)". |
| S10.2 | ILPA requires the IRR on **daily**-dated flows. | ILPA Granular Methodology (2025) | — | `UNVERIFIED` (not stated) | The word "daily" does not appear. XIRR is mentioned only in S7.8's practical note. |
| S10.3 | ILPA recommends PME. | ILPA Granular Methodology (2025); Principles 3.0 (2019) | — | `UNVERIFIED` (not found) | No "PME", "public market" or benchmark recommendation in either. The 2016 ILPA Reporting Template was not checked. |
| S10.4 | ILPA best practice: disclose net IRR levered and unlevered. | ILPA Principles 3.0 | printed p. 34 | `VERIFIED-primary` | "Best practice is to disclose the net IRR on both a levered and unlevered basis, taking into account any impact from capital call credit facilities." |
| S10.5 | GIPS allows money-weighted returns only under stated conditions. | GIPS 2020 | 1.A.35 | `VERIFIED-primary` | "The firm may present money-weighted returns only if the firm has control over the external cash flows into the portfolios in the composite or pooled fund and the portfolios in the composite have or the pooled fund has at least one of the following characteristics: a. Closed-end b. Fixed life c. Fixed commitment d. Illiquid investments as a significant part of the investment strategy." |
| S10.6 | GIPS: since-inception MWR on daily external cash flows from 1 January 2020. | GIPS 2020 | 2.A.29 and footnote 17 | `VERIFIED-primary` | "a. Calculate annualized since-inception money-weighted returns. b. Calculate money-weighted returns using daily external cash flows." Footnote 17: "Daily external cash flows are required beginning 1 January 2020. [...]" |
| S10.7 | GIPS: composite since-inception MWR with and without a subscription line. | GIPS 2020 | 5.A.2 (and the pooled-fund counterpart) | `VERIFIED-primary` | "[...] the firm must present the composite since-inception money-weighted return both with and without the subscription line of credit", unless, among other conditions, "The principal was repaid within 120 days using committed capital drawn down [...]". |
| S10.8 | GIPS defines PME as an index MWR on the fund's cash flows, and requires disclosure of the index if a PME is shown. | GIPS 2020 | Glossary, "public market equivalent (pme)"; 5.C.33 | `VERIFIED-primary` | Glossary: "The performance of a public market index expressed in terms of a money-weighted return (MWR), using the same cash flows and timing as those of the composite or pooled fund over the same period." 5.C.33: "If the firm presents the public market equivalent of the composite as a benchmark, the firm must also disclose the index used to calculate the public market equivalent." GIPS's "PME" is a **rate**, like the ICM or PME+ IRR, not the KS ratio. |

<a id="s11"></a>
## S11 · Limitation evidence

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S11.1 | Reported NAVs can be strategic: some underperformers boost them during fundraising, and top performers understate them. | Brown, G. W., Gredil, O. R., & Kaplan, S. N. (2019). Do private equity funds manipulate reported returns? *JFE*, 132(2), 267–297. https://doi.org/10.1016/j.jfineco.2018.10.011 (citation via Crossref). Read: NBER WP 22493 (2016). | WP abstract | `VERIFIED-primary` (WP abstract) | "We find evidence that some under-performing managers boost reported returns during times when fundraising takes place. However, those managers are unlikely to raise a next fund, suggesting that investors see through much of the manipulation. In contrast, we find that top-performing funds likely understate their valuations." This is evidence of strategic valuation, not of smoothing as such. The published abstract was not read. |
| S11.2 | Subscription lines raise IRR by 6.1 percentage points (25.0% of the sample mean), while multiples slightly decline. | Albertus, J. F., & Denes, M. (2019, June 25). *Distorting private equity performance: The rise of fund debt.* Kenan Institute / SSRN 3410076, https://doi.org/10.2139/ssrn.3410076. Read: https://www.kenaninstitute.unc.edu/wp-content/uploads/2019/07/DistortingPrivateEquityPerformance_07192019.pdf | abstract; body | `VERIFIED-primary` (2019 working paper only) | Abstract: "[...] the use of SLCs increases IRR-based performance by 6.1 percentage points, while multiples-based performance slightly declines." Body: "[...] representing a 25.0% increase relative to the sample mean of a fund's IRR based on its observed cash flows." Caveat, same PDF: "This paper is based on a preliminary sample of data [...]". |
| S11.3 | The published version carries the 6.1 pp figure. | Albertus & Denes, "Private Equity Fund Debt: Agency Costs and Cash Flow Management", *JFQA*, accepted manuscript online 7 May 2026, https://doi.org/10.1017/S0022109026102890 | — | `UNVERIFIED` | No abstract is shown and no volume or issue has been assigned. The archived report's `UNVERIFIED` flag stands. Cite 6.1 pp as the 2019 preliminary working paper's figure only. |
| S11.4 | Delaying the first call raises IRR by a median 206 bps by year 3, falling to 35–45 bps by fund end (Cobalt, 498 funds). | ILPA (2017, June). *Subscription Lines of Credit and Alignment of Interests*, https://ilpa.org/wp-content/uploads/2017/06/ILPA-Subscription-Lines-of-Credit-and-Alignment-of-Interests-June-2017.pdf | footnote 2 | `VERIFIED-primary` (ILPA reporting Cobalt's analysis) | "A Cobalt analysis of 498 funds found that delaying the first cash flow by up to one year yielded higher IRRs provided TVPI was [...] 206bps by year 3, falling to 35-45 bps by the end of the fund life for the funds studied. Source: CobaltGP.com." This is a third-party analysis reported by ILPA; Cobalt's own study was not read. |
| S11.5 | ILPA defines the unlevered IRR as if capital had been called immediately. | ILPA (2017) | body | `VERIFIED-primary` | "[...] unlevered IRR, i.e., the IRR had the fund not utilized its credit facility to temporarily finance the transaction and instead called capital immediately from its LPs." |
| S11.6 | There is no agreed method for returns with and without subscription lines. | ILPA (2020, June). *Enhancing Transparency Around Subscription Lines of Credit*, https://ilpa.org/wp-content/uploads/2020/06/ILPA-Guidance-on-Disclosures-Related-to-Subscription-Lines-of-Credit_2020_FINAL.pdf | printed pp. 2–3 | `VERIFIED-primary` | "There is no universal agreed-upon approach for calculating returns with and without the impact of subscription lines". "ILPA understands there is not an agreed upon methodology for calculating performance with and without the use of subscription lines." The archived report's rendering "universally" is a paraphrase. |
| S11.7 | A price-return index overstates every PME. | — | [D9](#derivations) | `DERIVED` | S1.3 and S1.4 show that the PME literature discounts at total return. |
| S11.8 | Getmansky, Lo & Makarov (2004), the smoothing model behind NAV de-smoothing. | *JFE*, 74(3), 529–609, https://doi.org/10.1016/j.jfineco.2004.04.001 | metadata | `VERIFIED-primary` (citation only) | The content was not read; it is cited only as the de-smoothing reference in "not modelled". |
| S11.9 | Brown, Ghysels & Gredil (2023), NAV nowcasting. | *Review of Financial Studies*, 36(3), 945–986, https://doi.org/10.1093/rfs/hhac045 | metadata | `VERIFIED-primary` (citation only) | Content not read. |

<a id="s12"></a>
## S12 · Other citations used on the semantics page

| ID | Claim | Source | Location | Status | Note |
|---|---|---|---|---|---|
| S12.1 | Takahashi & Alexander (2002): a fund cash-flow projection model. | Takahashi, D., & Alexander, S. (2002). Illiquid alternative asset fund modeling. *Journal of Portfolio Management*, 28(2), 90–100. | — | `UNVERIFIED` (not checked in this pass) | Citation carried from the research report's bibliography; used only to name an unmodelled method. |

<a id="derivations"></a>
## Derivations

Rows marked `DERIVED` rest on the algebra below, not on a source. Notation as in
[pme](pme.md): per-date nets `a_i` at distinct times `t_i`; `f(δ) = Σ a_i e^{−δ t_i}` with
`δ = ln(1+r)`.

| ID | Statement | Proof |
|---|---|---|
| D1 | The IRR does not depend on `t0` under an additive day count. | Additivity gives `t_i' = t_i + c` for all `i`, so `f'(δ) = e^{−δc} f(δ)`. Since `e^{−δc} > 0`, the roots and their multiplicities are unchanged. |
| D2 | The forward form of KS-PME equals the discounted form. | `(Σ D_t/I_t + NAV_T/I_T) / Σ C_t/I_t`, multiplied above and below by `I_T`, is `(FV(D) + NAV_T)/FV(C)`. Rebasing the index cancels in the same way. |
| D3 | Direct Alpha is a constant excess rate on top of the index path. | Multiply `Σ x_t (I_T/I_t)(1+a)^{−t} = 0` by `I_0/I_T`: `Σ x_t / [(I_t/I_0)(1+a)^{t}] = 0`. In logs, the discount rate is the index's log return plus `ln(1+a)` per year, i.e. S3.4 with `Δ = 1`. |
| D4 | The Long–Nickels recursion equals `FV(C) − FV(D)` at `T`. | Induction: if `V_prev = Σ_{s≤prev} (C_s − D_s) I_prev/I_s`, then `V_d = V_prev · I_d/I_prev + C_d − D_d = Σ_{s≤d} (C_s − D_s) I_d/I_s`. Rolling to `T` multiplies by `I_T/I_d`. |
| D5 | The identities table in [pme](pme.md#identities), including the sign equivalence under "exactly one sign change **and** first net negative". | Constant index: `I_T/I_t = 1`, so every FV equals the raw amount. Tracking fund: `NAV_T = FV(C) − FV(D)` gives KS-PME `= 1`, `s = 1`, `V_T = NAV_T`, and a compounded NPV of 0 at `a = 0`. `NAV_T = 0`: `KS = FV(D)/FV(C) = 1/s`. Sign equivalence: the compounded series has the fund's sign pattern (D7). With one sign change at `t*` and a negative first net, `g(a) = Σ b_i (1+a)^{t*−t_i}` is strictly decreasing, because each negative `b_i` has `t_i < t*` and each positive one `t_i > t*`. So the unique root is positive iff `g(0) = FV(D) + NAV_T − FV(C) > 0`, iff KS-PME `> 1`. Counterexample without the precondition: nets `{+50 at year 0, −100 at year 1}`, constant index, give KS-PME `0.5` and IRR `+100%`. Flow and index rescaling: every ratio is homogeneous of degree 0, and a common positive factor leaves roots unchanged. |
| D6 | The contract's root-count statement follows from S8. | Put `p_j = −t_j` (distinct after netting; zero nets dropped). Theorem 3.1 gives `Z ≤ V` in `δ` over ℝ and Proposition 3.6 gives `Z ≡ V (mod 2)`. `r = e^δ − 1` is a smooth bijection ℝ → (−1, ∞) with non-zero derivative, so zero orders carry over (as in Lemma 2.4). Then `V = 0 ⇒ Z = 0` and `V = 1 ⇒ Z = 1`. |
| D7 | Netting the compounded series keeps each date's sign. | The net at `d` is `(D_d − C_d) · I_T/I_d` (plus `NAV_T` at `T`, where `I_T/I_T = 1`), and `I_T/I_d > 0`. |
| D8 | The worked examples in [pme](pme.md#certified-irr-root-policy). | Dates 2021-01-01, 2022-01-01, 2023-01-01 give `t = 0, 1, 2` under ACT/365F (365 and 730 days). With `x = 1+r`, `−100x² + 230x − 132 = 0` has roots `x = (230 ± 10)/200 = 1.1, 1.2`. `−100x² + 150x − 60` has discriminant `22500 − 24000 < 0`. Both were checked numerically. |
| D9 | A price-return index overstates every PME. | The price index grows by the total return less dividends, so for `t < T`, `I_T/I_t` is smaller under price return. That lowers `FV(C)` more than `FV(D)` whenever contributions precede distributions on average, and it raises KS-PME. With a constant dividend yield `y` the price-return growth factor is lower by about `e^{−y(T−t)}`, so Direct Alpha rises by about `y`. This is approximate; no source quantifies it here. |

<a id="consequences"></a>
## Consequences for the contract and the code

Resolved by the coordinator on 2026-09-15:

1. **KS-PME attribution** (S1.2, S1.4): the contract now credits Kaplan & Schoar (2005)
   for the ratio (largely liquidated funds, no NAV) and Harris, Jenkinson & Kaplan (2014)
   for the residual value as a terminal distribution. The arithmetic is unchanged.
2. **Sign-equivalence identity** (D5): the precondition is now "exactly one sign change
   in the per-date nets **and** a negative first net", and the counterexample is recorded.

Recommended, not yet applied:

3. `ovf.pme.irr` docstring: cite Jameson (2006) Theorem 3.1 (bound), Proposition 3.6
   (parity) and Lemma 2.4. Cite Pólya–Szegő only "as cited by Jameson (Part V, ch. 1)",
   with no problem number (S8.4).
4. Cite Rouvinez (2003) as *Venture Capital Journal*, August, 34–38 (S4.1), not
   *Private Equity International*.
5. Cite the Direct Alpha equations as the 2014 SSRN draft's (S3.3–S3.4). The 2023 journal
   text is unread (S3.2).
6. Never cite Gredil et al.'s eq. 11 as the mPME recursion (S6.3).
7. Cite Albertus & Denes's 6.1 pp only as the 2019 preliminary working paper's figure
   (S11.2–S11.3).
8. Document that GIPS's "PME" is an index money-weighted return (S10.8), so a user does
   not mistake KS-PME for it.
