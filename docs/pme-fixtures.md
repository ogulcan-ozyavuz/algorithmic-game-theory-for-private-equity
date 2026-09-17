# Independent PME reference fixtures

Status: 2026-09-15. These fixtures implement the binding [PME contract](pme-contract.md),
sections 3–12. **Source-derived and hand-derived; no external review yet.** Every fixture
has `reviewed_by = ""`. Code: [fixtures](../tests/pme_fixtures.py),
[oracle](../tests/pme_oracle.py), [comparisons](../tests/test_pme_reference.py).

## Independence and numerical policy

The oracle and fixture module were completed and all **23 initial oracle-only tests
passed before any production PME file was inspected or imported by this worker**.
The first production inspection was a filename listing and public model/signature search;
`flows.py`, `irr.py` and `pme.py` had not yet been created. Subsequent integration uses
the public API. Neither oracle nor fixture code imports the production PME package.

Cash amounts, same-date netting, NAV roll-forward, day counts, index lookups, multiples,
KS-PME, PME+ scale and both Long–Nickels value computations use `Fraction` exactly.
Transcendental arithmetic uses `decimal.localcontext(prec=60)`; global precision and
flags remain unchanged. Oracle IRR scans delta = ln(1+r) from −12 to +12 at 0.01
increments and bisects every crossing to a delta interval narrower than 1e−42.
Expected decimal literals below are checked to 35 decimal places; exact expected
rationals are compared without tolerance. Production comparisons use ratio relative
tolerance 1e−9 and rate absolute tolerance 1e−9.

This is deliberately a different solver from the engine's Rolle recursion. The grid
does **not** prove absence of unobserved roots. A conclusive crossing set must exhaust
the exponential Descartes sign-change bound. A zero-sign-change series is root-free;
the negative discriminant of an equally spaced three-term series supplies a separate
elementary no-root certificate. In other cases, a missed pair, an off-grid tangent, or
a root outside the scan yields `grid_inconclusive=True`, `complete=False`,
`status="undetermined"`, `irr=None`. Differential root assertions explicitly exclude
these inconclusive cases. Tests demonstrate both missed close crossings and an
out-of-grid root. This finite scan is a reference-test tool, not a certified replacement
for the production solver.

Notation: `q=1+r>0`, C = gross paid-in, D = gross distributed, V = terminal residual,
I = index level. Contributions are negative LP cash flows. Unless specified otherwise,
the dates are 2021-01-01, 2022-01-01, 2023-01-01 (exactly t=0,1,2 under ACT/365F),
USD, net LP basis, exact index lookup with maximum gap 0. Every explicitly fully
realised fund has NAV 0 dated at the final date.

## PME-F1 — Microsoft XIRR example

The [Microsoft XIRR function page](https://support.microsoft.com/en-us/excel/functions/xirr-function)
was read on 2026-09-15. It supplies these five dated amounts:

| Date | Signed cash | Days from first flow |
|---|---:|---:|
| 2008-01-01 | −10000 | 0 |
| 2008-03-01 | 2750 | 60 |
| 2008-10-30 | 4250 | 303 |
| 2009-02-15 | 3250 | 411 |
| 2009-04-01 | 2750 | 456 |

ACT/365F gives the scalar equation

`−10000 + 2750*q^(−60/365) + 4250*q^(−303/365)
 + 3250*q^(−411/365) + 2750*q^(−456/365) = 0`.

There is exactly one coefficient sign change. The high-precision root is
**0.3733625335188315103084554119145548241713**. The source prints **0.373362535**
and 37.34%; the former differs from the high-precision equation by approximately
1.48117e−9. We preserve it as `published_irr`, not as a 12-digit mathematical truth.
The reference assertion uses the independently refined root, with unchanged engine
rate tolerance. Status **unique**, complete **true**, IRR is the number above.

## PME-F2a/b/c — two-flow closed form and a leap day

C=100 on 2019-07-01; D=121 on 2020-07-01; final NAV 0. There are 366 elapsed days,
including February 29. From `−100+121*q^(−t)=0`, `r=(121/100)^(1/t)−1`.

| Fixture | Day count | Exact t | Expected r |
|---|---|---|---|
| F2a | ACT/365F | 366/365 | 0.2093699710881278525772505269803884236053 |
| F2b | ACT/365.25 | 366/(1461/4) = 488/487 | 0.2095274475550495656185518306727665038204 |
| F2c | ACT/ACT-ISDA | 184/365 + 182/366 = 66887/66795 | 0.2096827922187858707054071472140171420283 |

All three are **unique**, complete **true**, and return the stated IRR. Separate tests
split the interval at February 29 and verify signed additivity exactly.

## PME-F3 — two roots

Signed cash: −100, +230, −132. Multiply NPV by positive `q²`:
`−100*q²+230*q−132 = −100*(q−11/10)*(q−6/5)`.
Roots are exactly **r=1/10 and 1/5**, each crossing. Status **multiple**, complete
**true**, **irr=None**. The engine must not choose a root from a guess.

## PME-F4 — proven no root

Signed cash: −100, +100, −100. The scaled polynomial is
`−100*(q²−q+1) = −100*((q−1/2)²+3/4)`, strictly negative for all q>0.
The discriminant is `100²−4*100²=−30000`.
Roots **empty**, status **none**, complete **true**, **irr=None**.

## PME-F5 — double tangent root

Signed cash: −100, +200, −100. The scaled polynomial is `−100*(q−1)²`.
Its only distinct root is **r=0**, of multiplicity two. The contract deliberately
requires **status=undetermined**, **complete=false**, **irr=None**, with a root of
kind **tangent**. Knowing the exact rational polynomial does not authorize the
production floating-point solver to present an unambiguous selected IRR.

## PME-F6 — constant-index identities

C0=100; D1=30; NAV2=90; I0=I1=I2=100. All growth factors are 1:

- DPI=3/10, RVPI=9/10, **TVPI=KS-PME=6/5**.
- Fund IRR and Direct Alpha solve `100*q²−30*q−90=0`, so
  `r=(3+sqrt(369))/20−1` = **0.1104686356149273029732326511932719896781**.
- **s=(100−90)/30=1/3**. PME+ cash is −100,+10,+90, hence PME+ IRR=0.
- ICM path: 100,70,70; **V2=100−30=70**. Its cash is −100,+30,+70,
  hence ICM IRR=0. Both spreads equal the fund IRR.

All these conventional IRRs are unique and complete.

## PME-F7 — exact index replication

C0=100; D1=55; NAV2=121/2; index 100,110,121.
`FV(C)=121`, `FV(D)=55*121/110=121/2`.

- **KS=(121/2+121/2)/121=1**.
- Compounded cash: −121,121/2,121/2. Its sum is 0 with one sign change,
  hence **Direct Alpha=0** (unique, complete).
- **s=(121−121/2)/(121/2)=1**.
- ICM path: 100; `110−55=55`; `55*121/110=121/2`.
  Thus **V2=NAV2=121/2**.
- `−100+55/1.1+(121/2)/1.1²=0`, so both fund and ICM IRR are exactly **1/10**.

## PME-F8 — fully realised reciprocal scale

C0=100; D1=60; D2=72; NAV2=0; index 100,110,121.
`FV(C)=121`, `FV(D)=60*(121/110)+72=66+72=138`.
Thus **KS=138/121**, **s=121/138**, and **KS=1/s exactly**.
The ICM path is 100,50,−17; terminal closed form is `121−138=−17`.
The fund root is **1/5**; compounded cash is −121,+66,+72, whose root is **1/11**.
Both are unique and complete. The negative ICM terminal amount is retained.

## PME-F9 — Long–Nickels short position

C0=100; D1=150; NAV2=10; index 100,110,121.
Positions after same-date cash: **100**, `100*(110/100)−150=−40`,
`−40*(121/110)=−44`. Thus **went_short=true**, first short date **2022-01-01**,
minimum position **−44**, terminal **−44**. The separate closed form gives
`FV(C)−FV(D)=121−150*(121/110)=121−165=−44` exactly.

ICM cash is −100,+150,−44. Its scaled NPV is
`−100*q²+150*q−44 = −100*(q−2/5)*(q−11/10)`.
ICM roots **−3/5 and 1/10**; **status=multiple**, **complete=true**, **irr=None**;
the fund-minus-ICM spread is therefore **None**. The fund itself has a unique root
`(15+sqrt(265))/20−1` = **0.5639410298049853193676507954991916577004**.
**KS=(165+10)/121=175/121**; **s=(121−10)/165=37/55**.

## PME-F10a/b — end-of-day NAV and refused inconsistency

Calls: 100 on 2021-01-01 and 20 on 2022-06-01. Distributions: 10 on 2022-01-01
and 15 on 2023-01-01. Reported end-of-day NAV on 2022-01-01 is 80.
Resolve at 2023-01-01 with `roll_forward_cash_adjusted`:
**80+20−15=85**. The distribution 10 on the NAV date is **excluded** from the
roll-forward, since it is already reflected in the end-of-day NAV.
Gross C=120, D=25: **DPI=5/24**, **RVPI=17/24**, **TVPI=11/12**.
Netted final cash includes `15+85=100`.

F10b changes only the last distribution to 115: `80+20−115=−15`.
Both implementations must **raise ValueError**; no metric or IRR result is valid.
The separate stale-policy test also verifies that F10a with `stale_nav="refuse"`
raises instead of implicitly rolling forward.

## PME-F11 — preserve gross cash through netting

Date 0 has a call 100 and distribution 20; date 1 has call 10 and distribution 10;
date 2 has distribution 88 and explicit NAV 0. Net cash is **−80,+88**, with date 1
recorded in **netted_to_zero**. From `q²=88/80=11/10`, the unique complete IRR is
**sqrt(11/10)−1 = 0.0488088481701515469914535136799375984753**.
Gross C=110 and D=118, so **TVPI=KS=118/110=59/55** under the constant index
and the gross convention used here (netting recallables would give 88/80).
**s=55/59**; **ICM terminal=−8**.

## PME-F12 — readable published PME and Direct Alpha example

Source: Gredil, Griffiths and Stucke, *Benchmarking Private Equity: The Direct Alpha
Method*, February 28, 2014 draft, **Exhibit 5, printed page 25; Exhibit 6, printed
page 26** ([readable PDF](https://allocatortraining.com/wp-content/uploads/2023/06/Benchmarking-PE-Direct-Alpha-Method.pdf)).
Tables and outputs were read directly on 2026-09-15. Each row is December 31:

| Year | C | D | Index | Terminal NAV |
|---|---:|---:|---:|---:|
| 2001 | 100 | 0 | 100 | |
| 2002 | 0 | 0 | 78 | |
| 2003 | 100 | 25 | 100 | |
| 2004 | 0 | 0 | 111 | |
| 2005 | 50 | 150 | 117 | |
| 2006 | 0 | 0 | 135 | |
| 2007 | 0 | 150 | 142 | |
| 2008 | 0 | 0 | 90 | |
| 2009 | 0 | 100 | 113 | |
| 2010 | 0 | 0 | 131 | 75 |

Published **TVPI=2.00**, **KS-PME=1.67**, fund **IRR=17.5%**, and arithmetic
**Direct Alpha=12.6%**. These are display-precision checks only. In particular,
the source prints the FV of the 2003 contribution as 130 even though its displayed
indices imply `100*131/100=131`, indicating undisplayed input precision. We make
the reproducible choice of treating the **displayed integer indices as exact** and
using explicit ACT/365F. We do not claim access to unrounded source data.

Hand algebra for the exact-input fixture:

`A=FV(C)=131+131+50*131/117=37204/117`.

`B=FV(D)=25*131/100+150*131/117+150*131/142+100*131/113`.

Then **TVPI=(425+75)/250=2**, **KS=(B+75)/A=1990055721/1193950768**,
**s=(A−75)/B=912343468/1708448421**, and
**V_ICM=A−B=−514497653/3754764**.

The nonzero time numerators in days from 2001-12-31 are 0,730,1461,2191,2922,3287.
Let `z_d=q^(−d/365)`. The fund equation is
`−100−75*z_730+100*z_1461+150*z_2191+100*z_2922+75*z_3287=0`.
Its unique root is **0.1752012983239102762880181532804552349698**.
The compounded equation is
`−131−(75*131/100)*z_730+(100*131/117)*z_1461
 +(150*131/142)*z_2191+(100*131/113)*z_2922+75*z_3287=0`.
Its unique root is **0.1256031689842718129140562878513095672908**.
These agree with the published rates at the precision actually displayed.

There is a further useful root-policy distinction. Replace the fund equation's
terminal 75 by the ICM terminal `−514497653/3754764`. The resulting coefficient
sign pattern has two changes. It has **two** crossings:
**−0.2725508866987863647654264584613866681767** and
**0.0596701431386367255176898473485018680819**. The positive root rounds to the
6.0% ICM figure in Exhibit 2 (printed page 24), but the OVF contract requires
**status=multiple**, **complete=true**, **irr=None**, and **spread=None**.
This is a root-selection difference from the published illustration, not an engine
disagreement or a claim that the authors published these higher-precision roots.
The position first goes short on **2007-12-31**, to `−5351/234`, stays negative,
and reaches its minimum `−514497653/3754764` at the terminal date. Thus the published
illustration itself exhibits Long–Nickels' short-position pathology; F12 explicitly
asserts `went_short=True` and that first-short date.

Source search also found the 2023 journal version (DOI 10.1016/j.jcorpfin.2023.102360),
its ResearchGate/SSRN records, and a Bolivia central-bank PDF mirror; that mirror
timed out. F12 uses the readable 2014 primary-author draft, not search snippets or a
secondary worked example. No fabricated or unread-source numbers are included.

## Independent mPME extension (Wave 3)

W7 implements section 12 from the contract and the [S6 source ledger](pme-sources.md#s6).
This is a **labelled reconstruction**, not a claim to reproduce Cambridge Associates'
figures. S6 records CA's verbal description and Gredil et al.'s consistent distribution
equation (9); equation (11) as printed has inconsistent period indices. No new source
verification or external specialist review is claimed here.

The extension has no production imports. Its exact `Fraction` calculations use
`X = previous_position * (I / previous_I) + C`, `w = D / (D + NAV)`, sale `w * X`,
and retained position `NAV / (D + NAV) * X`. Gross same-date calls enter before the sale;
the NAV mark already reflects both calls and distributions on that date. With no
distribution, w=0 and no interim NAV is needed. At each step, sale + retained = X
exactly, and both amounts are nonnegative. Exact zero nets need no float rounding rule.
IRRs use the existing independent Decimal grid and bisection, including its explicitly
inconclusive root-count policy.

The original extension and F13–F17 were complete, and all **45 oracle self-tests**
(including **21 mPME tests**) passed before mPME engine comparisons began. Subsequent
F18 preserves a randomized engine finding; F19a/b implement the coordinator's later
terminal-NAV clarification. Oracle-only checks of those additions passed before
their engine comparisons. Every fixture keeps `reviewed_by = ""`.

### PME-F13 — three distributions with round numbers

Dates are January 1 of 2021–2024, exactly t=0,1,2,3 under ACT/365F. Interim fund NAVs
are end-of-day marks. The final fund NAV is 60.

| Year | I | C | D | Fund NAV used | X before sale | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 100 | 100 | 0 | none needed | 100 | 0 | 0 | 100 |
| 2022 | 120 | 40 | 80 | 80 | 100×120/100+40 = 160 | 80/(80+80) = 1/2 | 80 | 80 |
| 2023 | 150 | 0 | 50 | 150 | 80×150/120 = 100 | 50/(50+150) = 1/4 | 25 | 75 |
| 2024 | 180 | 0 | 120 | 60 | 75×180/150 = 90 | 120/(120+60) = 2/3 | 60 | 30 |

Thus the mPME series is **−100,+40,+25,+90**, where the last 90 is distribution 60
plus terminal public position 30. Its unique root solves
`−100*q³ + 40*q² + 25*q + 90 = 0` and is
**0.2151953740642772566525964996136581841420**. The fund series is
−100,+40,+50,+180, with unique root
**0.5146759923822105766006955715018281837973**. These decimal literals were separately
obtained by 60-digit bisection of the displayed cubics before engine integration.
The same-day call 40 must be invested before applying w=1/2; subtracting the call
from the distribution first would change both the sale and the retained position.

### PME-F14 — tracking-fund identity

Use the same annual dates, with a 10% annual index path: 100,110,121,1331/10.

| Year | C | D | Fund NAV after | X before sale | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 100 | 0 | not needed | 100 | 0 | 0 | 100 |
| 2022 | 10 | 60 | 60 | 100×11/10+10 = 120 | 1/2 | 60 | 60 |
| 2023 | 0 | 22 | 44 | 60×11/10 = 66 | 1/3 | 22 | 44 |
| 2024 | 0 | 121/5 | 121/5 | 44×11/10 = 242/5 | 1/2 | 121/5 | 121/5 |

At each sale X=D+NAV, so sale = D and retained position = NAV. Both series are exactly
**−100,+50,+22,+242/5**, and substitution of q=11/10 gives NPV=0. They have one
coefficient sign change: both IRRs are uniquely **1/10**, with **spread=log_spread=0**.
More generally, induction preserves equality of the fund's index-held value and the
public position whenever every required interim mark and the terminal mark track it.

### PME-F15 — zero interim NAV

C0=100, D1=150, NAV1=0, terminal NAV2=0; indices 100,110,121. The path is:

| Date | X | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|
| 2021-01-01 | 100 | 0 | 0 | 100 |
| 2022-01-01 | 110 | 150/(150+0) = 1 | 110 | **0 exactly** |
| 2023-01-01 | 0 | 0 | 0 | **0 exactly** |

The zero terminal row disappears from the IRR series. mPME cash **−100,+110** has
IRR **1/10**, fund cash −100,+150 has IRR **1/2**, and the spread is **2/5**.
This checks the direct retained fraction, including exact zero after subsequent growth.

### PME-F16a/b/c/d — interim NAV roll-forward and refusals

The index is constant at 100. On January 1, 2021, C=100 and D=10; its reported
end-of-day NAV is 90. January 6 has C=20, January 11 has D=30, and the terminal
date January 1, 2022 has reported NAV 80 and no cash flow.

For the January 11 distribution, the latest earlier mark is January 1. Roll-forward
includes cash strictly after that mark: **90+20−30=80**. It excludes the January 1
distribution 10, already reflected in the mark. The gap is exactly **10 calendar days**.

| Date | C | D | NAV used | X | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021-01-01 | 100 | 10 | 90 reported | 100 | 1/10 | 10 | 90 |
| 2021-01-06 | 20 | 0 | none | 110 | 0 | 0 | 110 |
| 2021-01-11 | 0 | 30 | 80 rolled | 110 | 3/11 | 30 | 80 |
| 2022-01-01 | 0 | 0 | none needed | 80 | 0 | 0 | 80 |

- **F16a:** roll-forward permitted with maximum gap 10; succeeds at the inclusive limit.
  Both series are **−90 on Jan 1, −20 on Jan 6, +30 on Jan 11, +80 at T**. Sum=0 and
  one sign change imply both IRRs uniquely **0**, with zero spreads. Maximum used gap=10.
- **F16b:** same data, maximum gap **9**; refuse January 11 because the mark is 10 days old.
- **F16c:** same data, policy **refuse**, maximum gap 0; refuse missing January 11 mark.
- **F16d:** change only the January 1 mark to **1**; roll-forward gives
  **1+20−30=−9**; refuse January 11 for a negative rolled value. The zero-return
  assumption cannot support those inputs.

Separate self-tests add a newer mark on January 10 (a date with **no benchmark level**),
and an exact January 11 mark. The newer mark 110 rolls to 80 with gap 1; the exact mark
110 overrides that roll and gives **w=3/14**, **sale=165/7**, **position=605/7**, gap 0.
Additional refusals cover empty/duplicate histories, future/negative marks, terminal
inconsistency, no earlier mark, invalid policy/gap, absent terminal NAV and zero paid-in.

### PME-F17 — Long–Nickels short while mPME stays nonnegative

This uses exactly F9's flows, terminal NAV and benchmark: C0=100, D1=150, terminal
NAV2=10, I=100,110,121. Add the required interim fund NAV1=10.

| Date | X | w | mPME distribution | mPME NAV after | ICM after |
|---|---:|---:|---:|---:|---:|
| 2021-01-01 | 100 | 0 | 0 | 100 | 100 |
| 2022-01-01 | 110 | 150/160 = 15/16 | 825/8 | 55/8 | −40 |
| 2023-01-01 | (55/8)×11/10 = 121/16 | 0 | 0 | 121/16 | −44 |

mPME series **−100,+825/8,+121/16** has NPV=0 at q=11/10 and one sign change, hence
unique IRR **1/10**. ICM goes short on January 1, 2022 and reaches **−44**, while
mPME ends at **121/16 = 7.5625** and never goes short. Fund IRR remains F9's
**0.5639410298049853193676507954991916577004**. The methods receive the same inputs;
the difference comes from a proportional sale instead of a fixed distribution amount.

### PME-F18 — a second sale after full public liquidation

Annual dates 2021–2024; constant index 100. C0=20, D1=1, D2=1, interim NAV1=NAV2=0,
terminal NAV3=0. The exact path is:

| Year | X | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|
| 2021 | 20 | 0 | 0 | 20 |
| 2022 | 20 | 1 | 20 | 0 |
| 2023 | 0 | 1 | **0** | **0** |
| 2024 | 0 | 0 | 0 | 0 |

After the first full sale, the second sale is **1×0=0**, an exact result. mPME series
**−20,+20** has unique IRR **0**. Fund series −20,+1,+1 has positive q root 1/4
from `20*q²−q−1=0`, so fund IRR and spread are **−3/4**.

This fixture preserves a randomized finding: the engine initially refused the second
sale as floating-point underflow. The actual fault was the shared multiplication
helper rejecting a nonzero first factor times an exact-zero second factor. The
coordinator confirmed the engine was wrong; W6 added an exact-zero guard in mPME, and
the coordinator routed the shared helper correction to its owner as well. W7 changed
no production file and kept the exact-zero requirement and every tolerance.

### PME-F19a/b — a terminal distribution uses resolved NAV

C0=100, D1=30, as_of=2022-01-01, I0=100, I1=110. NAV history contains only the
2021-01-01 mark 100. In **F19a**, the fund reports terminal NAV=70. In **F19b**, the
fund reports NAV0=100 and `resolve(stale_nav="roll_forward_cash_adjusted")` produces
the same terminal NAV=100−30=70. Both use **interim_nav="refuse", max_nav_gap_days=0**.

| Date | X | w | mPME distribution | mPME NAV after |
|---|---:|---:|---:|---:|
| 2021-01-01 | 100 | 0 | 0 | 100 |
| 2022-01-01 | 110 | 30/(30+70) = 3/10 | 33 | 77 |

Both give mPME series **−100,+110**, unique IRR **1/10**; fund series −100,+100,
unique IRR **0**; spread **−1/10**. F19a's terminal source is **reported**, observation
date 2022-01-01. F19b's is **rolled_forward**, observation date 2021-01-01. The latter
365-day terminal roll belongs to `resolve`, so **max_nav_gap_used_days=0** for both.
The interim policy does not replace, re-roll or refuse the already resolved terminal NAV.

## Coverage and limits

The comparison suite checks every fixture against the oracle and the public engine,
then generates conventional funds with random positive index paths, all three day
counts and explicit NAVs. It also compares multi-sign-change root sets when the
oracle's count is conclusive, preserves gross totals through same-date netting, and
checks index/flow rescaling invariance. Missing NAV, stale refusal, look-back index
gaps, zero paid-in and zero distributions receive separate tests.

These fixtures establish agreement with the stated equations and provenance. They
do not establish that a NAV is accurate, a benchmark is suitable, or the cash flows
have the desired fee/carry basis. There is no claim of independent human review.

## Wave 1 validation and findings

Completed 2026-09-15 against the concurrently delivered public engine API:

- `.venv/bin/pytest tests/test_pme_reference.py -q -W error` — **passed**.
- `.venv/bin/ruff check tests/pme_oracle.py tests/pme_fixtures.py
  tests/test_pme_reference.py` — **passed**.
- Randomized comparison budgets: 60 conventional funds, 25 rescaling cases (each
  compares original, scaled index and scaled cash), and 60 constructed multi-root
  series across the three day counts. Root-set comparisons require the oracle's
  independent completeness check.
- **No engine disagreements found.** No numerical tolerances were loosened and no
  production files were changed by this worker.
- Source limitations: Microsoft's displayed XIRR differs slightly from its exact-input
  mathematical root; F12's unrounded index data were not available. Both sources are
  readable and cited above, with published numbers kept distinct from recomputed
  values. The published ICM illustration selects the positive member of a two-root
  set; the engine correctly preserves both roots and declines to select one.
- The coordinator separately recomputed F12 with rational/Decimal code and confirmed
  its exact KS, scale, terminal value, fund rate, Direct Alpha, both ICM roots and
  first-short date. This machine cross-check does not populate `reviewed_by`.

## Wave 3 validation and findings

Completed 2026-09-15 after the engine's exact-zero correction:

- `.venv/bin/pytest tests/test_pme_reference.py -q -W error` — **91 passed**, including
  the complete inherited reference suite and all new mPME comparisons.
- `.venv/bin/ruff check tests/pme_oracle.py tests/pme_fixtures.py
  tests/test_pme_reference.py` — **passed**.
- F13–F19 comprise **11 mPME fixtures** (eight successful reconstructions and three
  refusals), all with literal expected values and `reviewed_by = ""`. The new tests
  compare every path field, sources, observation dates, weights, gross cash, exact
  zero positions, terminal values, dated series, IRRs and spreads. F17 compares ICM
  and mPME on identical inputs; F18 preserves the exact-zero engine regression.
- Randomized mPME coverage: **60** funds with independent random interim NAV histories,
  calls, distributions, index paths and all three day counts; **25** additional funds
  compare original inputs, scaled indices and jointly scaled cash/NAVs. Histories may
  be unsorted, use exact observations or cash-adjusted earlier marks, include zero NAV,
  or omit terminal marks. Reducing the allowed gap below the maximum used age must
  produce a refusal naming the first offending distribution date in both implementations.
  Gross-leg splitting and input ordering receive a separate comparison.
- **Inherited oracle disagreement, oracle was wrong:** under §11.4 a negative PME+
  scale suppresses both spreads. With a constant index, C=20, D=20+20 and terminal
  NAV=21, `s=(20−21)/40=−1/40`. The engine correctly returned `None`; the inherited
  oracle still subtracted the rates. The coordinator approved updating the oracle's
  spread eligibility, and the suite explicitly asserts both spreads are `None` while
  still comparing the PME+ IRR. PME+/ICM log spreads and the new index-gap and IRR
  residual fields are now checked as well.
- **Engine disagreement, engine was wrong:** after complete public liquidation a
  subsequent distribution has X=0 and sale=w×0=0; the former engine refused this as
  underflow. F18 retains the hand derivation. W6's exact-zero guard resolves it; the
  full random comparisons now pass. No remaining engine/oracle disagreement was found.
- **§11.3 representation-noise scope:** exact stated cents `300000.30−100000.10−200000.20`
  net to zero in the rational oracle; their binary-float inputs net to **−1/2³⁵**.
  This is within `eps × gross stated legs`, so `resolve` drops that date and lists it
  in `netted_to_zero`, with a dated assumption. Raw `xirr(DatedAmount)` retains the
  dust, and is separately compared against exact `Fraction(float)` inputs. A stated
  difference of 1e−6 above the bound stays in the series. These are explicit convention
  checks, not broader numerical tolerances.
- **No tolerances were loosened.** The coordinator's ICM `position_close` comparison
  (absolute tolerance `1e−12 × gross grown magnitude`, relative tolerance `1e−9`)
  remains unchanged. mPME comparisons use the existing ratio/rate tolerance helpers.
  W7 edited only the four assigned oracle, fixture, comparison and documentation files.
