# Governance and collective action

Status 2026-09-15, engine `governance-v1`, module `ovf.governance`, with a
`forced_conversions` input added to `ovf.waterfall`. Every expected number below is derived
by hand here, then asserted in `tests/test_governance.py` against the fixtures in
`tests/governance_fixtures.py`. None was copied from engine output. One derivation (GV5) was
wrong in its first draft; the failing test caught it, and it was corrected by redoing the
arithmetic by hand.

**Review status: source-derived, not yet independently reviewed.** `reviewed_by` is empty on
every fixture.

## The result: two of the three mechanisms do not move cash

The roadmap names three governance mechanisms: class voting, drag-along and protective
provisions. Read against the NVCA model documents, they are not the same kind of thing.

| Mechanism | Operative text | Effect on who gets what | Treatment here |
|---|---|---|---|
| Drag-along (Voting Agreement s.3) | enforceable only if proceeds follow the charter waterfall | none | not an input |
| Protective provision over a sale (COI s.3.3.1) | a veto; bracketed text makes an unapproved sale void | none | not an input |
| Mandatory conversion by vote (COI s.5.1(b)) | converts all preferred on the Requisite Holders' vote | **moves cash** | modelled |

**Drag-along.** In the October 2025 NVCA Model Voting Agreement, a stockholder need not
comply with the drag "unless", among other conditions (s.3.2(f)):

> "(ii) each holder of a series of Preferred Stock will receive the same amount of
> consideration per share of such series of Preferred Stock as is received by other holders
> in respect of their shares of such same series, (iii) each holder of Common Stock will
> receive the same amount of consideration per share of Common Stock as is received by other
> holders in respect of their shares of Common Stock, and (iv) unless waived pursuant to the
> terms of the Restated Certificate or as may be required by law, the aggregate consideration
> receivable by all holders of the Preferred Stock and Common Stock shall be allocated among
> the holders of Preferred Stock and Common Stock on the basis of the relative liquidation
> preferences to which the holders of each respective series of Preferred Stock and the
> holders of Common Stock are entitled in a Deemed Liquidation Event (assuming for this
> purpose that the Proposed Sale is a Deemed Liquidation Event) in accordance with the
> Company's Restated Certificate in effect immediately prior to the Proposed Sale".

The June 2019 model has the same condition as s.3.3(f). A drag-along therefore forces a
minority to sell only on the terms the charter already fixes. It decides whether the sale
happens, not how its proceeds are split. The engine starts from the premise that a sale
happened and allocates it by the charter, so there is nothing for a drag term to change.

s.3.3 (2025; s.3.4 in 2019) closes the one route around this, a sale of stock to which the
company is not a party:

> "No Stockholder shall be a party to any Stock Sale unless (a) all holders of Preferred Stock
> are allowed to participate in such transaction(s) and (b) the consideration received
> pursuant to such transaction is allocated among the parties thereto in the manner specified
> in the Company's Restated Certificate in effect immediately prior to the Stock Sale (as if
> such transaction(s) were a Deemed Liquidation Event)".

**Protective provisions.** NVCA Model COI (October 2025) s.3.3 says the corporation "shall not
... effect any of the following acts or transactions without ... the written consent or
affirmative vote of the Requisite Holders[, and any such act or transaction that has not been
approved by such consent or vote prior to such act or transaction being effected shall be null
and void ab initio, and of no force or effect]". The first listed act, s.3.3.1, is to
"liquidate, dissolve or wind-up the business and affairs of the Corporation or effect any
Deemed Liquidation Event". fn 38 explains the bracketed "null and void" language by reference
to *Fletcher Int'l v. ION Geophysical* (Del. Ch. 2010). A veto has two outcomes: the sale
happens on the charter's terms, or it does not happen. The charter gives no formula that
pays a vetoing holder differently.

The charter also prevents a sale from escaping the waterfall. s.2.3.2(a): "The Corporation
shall not have the power to effect a Deemed Liquidation Event referred to in Section
2.3.1(a)(i) unless the agreement or plan with respect to such transaction ... provide that the
consideration payable to the stockholders of the Corporation in such Deemed Liquidation Event
shall be allocated to the holders of capital stock of the Corporation in accordance with
Sections 2.1 and 2.2."

**Consequence for the engine.** Modelling either mechanism as a payout modifier would invent
economics. Neither is an input to `ovf.governance`. A caller who wants to know whether a sale
can be forced or blocked needs the approval thresholds and a counterfactual value for not
selling. The charter supplies the first. Nothing in a cap table supplies the second.

## Renegotiation produces a different cap table

Vetoes are used as bargaining leverage, and that bargaining does move cash. Broughman and
Fried (2010, *Journal of Financial Economics* 95(3), 384–399) hand-collected 50 sales of
Silicon Valley VC-backed firms in 2003 and 2004. Their summary, posted by the authors on the
Harvard Law School Forum on Corporate Governance (2008):

> "In 11 of the sales, however, VCs carve out part of their cash flow rights to common
> shareholders ... the average deviation between the VCs' cash flow rights and their actual
> payout is $3.7 million, approximately 11% of the VCs' cash flow rights. Across all 50 firms,
> the average deviation was 2.3%"

and "the expected deviation is about $1.5 million larger if VCs lack a board majority and
roughly $1.6 million larger if the firm is incorporated in California (rather than Delaware)".

That is an empirical finding about negotiated outcomes. It is not a contractual formula,
and the size of a carve-out comes out of bargaining, not out of any term. A deterministic
engine should not guess it.

The model charter says how an agreed deviation is put into effect. fn 23, on waiving
Deemed Liquidation Event treatment:

> "If the Preferred Stock is willing to forgo some but not all of its preference in such
> Deemed Liquidation Event, the Certificate of Incorporation should be amended prior to the
> effective time of the Deemed Liquidation Event to fix the agreed upon preference in
> connection with such Deemed Liquidation Event."

**A renegotiated split is therefore a different cap table.** It has amended preferences or
an added payment, and the engine prices that table exactly as it prices any other: build
the new snapshot and run it. This acknowledges that bargaining is real and common, 11 of
50 sales in that sample, without the engine pretending to model it or taking an invented
input. A carve-out paid to management off the top is still not modelled; see
[limitations](limitations.md).

## What "class voting" actually is in the model charter

The roadmap, and the brief for this work, say "class-majority conversion", which suggests a
class converting itself on a majority of that class. The NVCA mechanism is different in four
ways. Each one changes a number.

NVCA Model COI (October 2025) s.5.1, "Trigger Events":

> "All outstanding shares of Preferred Stock shall automatically be converted into shares of
> Common Stock, at the then effective conversion rate ..., upon the earliest to occur of ...:
> [(i)] immediately prior to the closing of the sale of shares of Common Stock to the public
> ... (a "Qualified IPO"); [(ii) ... a "Qualified Direct Listing"]; and (b) the date and
> time, or upon the occurrence of an event, specified by vote or written consent of the
> Requisite Holders."

The Requisite Holders are defined in s.2.3.1: "the holders of at least [specify percentage] of
the outstanding shares of Preferred Stock, voting together as a single class on an
as-converted to Common Stock basis".

1. **The group is all preferred, not one class.** Every series votes together, weighted by
   as-converted shares, and every series converts.
2. **It converts only.** Optional conversion under s.4.1.1 is "at the option of the holder
   thereof, at any time". A vote can force a position to convert. Nothing can force a
   position not to.
3. **The IPO triggers never fire at an M&A exit.** A Qualified IPO or Qualified Direct Listing
   is not the event this engine prices. The election trigger (b) can fire at any time,
   including immediately before a merger.
4. **It is used against a dissenting series.** fn 64:

   > "As with the vote required to waive a Deemed Liquidation Event, see footnote 22, where
   > there are multiple series of Preferred Stock, investors should give consideration to
   > the vote required to trigger a mandatory conversion. See Greenmont Cap. Partners I, LP
   > v. Mary's Gone Crackers, Inc., 2012 WL 4479999 (Del. Ch. Sept. 28, 2012) in which
   > plaintiff, whose series of preferred stock did not have a blocking vote on mandatory
   > conversion, unsuccessfully argued that its consent right on actions that would 'alter
   > or change' its series rights prevented the majority of preferred holders from converting
   > all preferred stock to common stock. See also Alta Berkeley VI C.V. v. Omneon, Inc., 41
   > A.3d 381 (Del. 2012) in which plaintiff, who did not have a blocking vote on mandatory
   > conversion, unsuccessfully argued that it was entitled to its liquidation preference
   > (rather than its Common Stock payout) where its preferred stock was converted to common
   > stock prior to a liquidation event."

In *Omneon*, as summarised by Potter Anderson (counsel to Omneon), the Series C-1 shares
"were automatically and involuntarily converted into Omneon common stock by a majority vote
of Omneon's preferred stockholders ... As a condition of and immediately prior to a merger",
and the Delaware Supreme Court held that the holders were "not entitled to a liquidation
preference payment". Those cases are the evidence that the difference is real money: a
preference the individual conversion game would have paid disappears.

**A per-series route also exists.** The Waiver section of the model charter (the section
after "Redeemed or Otherwise Acquired Shares") lets the rights of a series "be waived on
behalf of all holders of such series of Preferred Stock by the affirmative written consent or
vote of the holders of such series that would otherwise be required to amend" them. A series
that waives its preference on a series vote is expressible here as a term whose voters and
converted positions are that series.

## Who the player is

Two models were considered.

- **(a) Constraint model.** The positions in a class move together, and the strategy space
  shrinks from `2^positions` to `2^classes`.
- **(b) Vote model.** The engine looks at who holds what and works out whether the holders
  who gain control the required vote.

**This module implements (b), with holders as voters.** The coordinator confirmed this choice
on 2026-09-15. The NVCA text fixes it three ways:

- the vote is cast by holders ("the holders of at least [x]%");
- it only converts, whereas (a) also forces positions not to convert;
- its group spans classes, where (a) moves one class.

(a) is not an input. It is examined below as a question about the per-position game, because
it is what the NVCA §2.1 formula for non-participating preferred computes.

### The solution concept: two stages, sincere voting

1. **Vote.** Each holder that owns a voting position compares its total cash, summed over every
   position it holds in the table, with and without the conversion. It consents if and only if
   the cash with the conversion is higher by more than the waterfall tolerance
   `ε = 1e-8 + 1e-12 × net exit`.
2. **Play.** The per-position conversion game is played over the positions the vote did not
   convert. This is `ovf.waterfall` with `forced_conversions`.

Voting sincerely is weakly dominant for a single yes-or-no proposal under a quota rule, and
that is why this is a coherent choice. It is still an **assumption, and a solution concept,
not a fact about holders**. It excludes:

- a holder voting against its immediate interest to affect a later stage;
- coalitions forming;
- side payments between holders;
- any other strategic voting.

A holder votes once, on its total. In stage 2, each of its positions still decides alone,
as the engine has always assumed (`WaterfallResult.multi_position_holders` discloses where
that is weakest).

### The voting layer rests on payoff uniqueness

A holder's vote compares "the equilibrium payoff with the conversion" and "without". Those
phrases name one number each only if the equilibrium payoff of each stage is unique. That
is exactly the property [findings](findings.md) reports empirically, and Proposition 1 in
[dividends](dividends.md) extends to dividend-bearing tables. **If payoff uniqueness failed,
this model would be ill-posed, not merely inaccurate.** So `resolve_collective_conversion`
enumerates every profile of both stages on every call. It raises
`GovernanceIndeterminateError` when either stage has more than one equilibrium payoff
vector, and it is limited by `max_positions`. That dependency is why the uniqueness search
below was rerun under the new strategy spaces.

### Refusals

- **Pivotal indifference.** Some holders may gain or lose no more than `ε`, with the outcome
  depending on whether they consent, and the two outcomes pay differently. The call then
  raises `GovernanceIndeterminateError`. The error names the holders and gives the tolerance
  in base-currency units. The charter does not say how a holder with nothing at stake votes.
  GV6 below is such a case.
- **One term per exit.** Several independent votes interact: one vote's outcome changes
  what every other voter gains. Resolving that needs a voting-game solution concept that is
  not implemented. One term may carry several approvals, all of which must be given
  (conjunctive). That covers a series consent added under fn 64.
- A term naming anything other than a preferred position in the table, a vote whose voters
  hold no shares, a float threshold, and a table where no profile allocates the whole exit.

## The model

| Name | Purpose |
|---|---|
| `VoteRequirement(name, voters, threshold, comparison, source)` | one approval: preferred positions voting, the fraction needed, and whether it is `"at_least"` or `"more_than"` |
| `CollectiveConversion(name, converts, approvals, source)` | the charter term: positions converted when every approval is given |
| `resolve_collective_conversion(securities, exit, ..., term=...)` | the vote, both stage-2 outcomes, and the one that applies |
| `CollectiveConversionResult` | `approved`, `changes_payout`, per-holder decisions, per-approval tallies, both surveys, both `WaterfallResult`s, `result`, input hash, assumptions |
| `GovernanceIndeterminateError` | the terms and the model do not determine one outcome |
| `solve_waterfall(..., forced_conversions=...)`, `enumerate_equilibria(..., forced_conversions=...)` | stage 2: listed positions are held converted and are not players |

No field of either charter term has a default. The threshold is a bracketed blank in the
NVCA text, and whether a vote landing exactly on it passes depends on the wording: "at least
[x]%" is `"at_least"`, "a majority" is `"more_than"` one half.

The threshold must be exact, a `Fraction` or a string such as `"3/5"`. A float is refused,
because `0.6` is stored slightly below 3/5. Vote weights are the stated as-converted share
counts, and the comparison is done in exact rational arithmetic on those values.

**The vote.** Let `W` be stage-2 cash without the conversion and `W'` with it, both unique by
enumeration. For holder `h` with positions `P(h)`, `Δ_h = Σ_{i∈P(h)} (W'_i − W_i)`. `h` consents
if `Δ_h > ε`, withholds if `Δ_h < −ε`, and is indifferent otherwise. For an approval with
voters `V`, `h`'s weight is `Σ_{i∈V∩P(h)} shares_i × ratio_i`. The approval is given if the
consenting weight is at least (or more than) `threshold × total weight`.

## Proposition G1: a forced conversion is common stock

**Statement.** Fix an exit and a set `F` of preferred positions. Replace each `i ∈ F` with a
common position holding `u_i` shares, where `u_i` is the position's common-equivalent units
(`shares × ratio`; `shares(1 + d) × ratio` under paid-in-kind dividends). Then, in every
profile of the remaining players, every position receives the same cash in the table with `F`
forced as in the replaced table.

**Proof.** In `evaluate_fixed_waterfall` a converted preferred position:

- is excluded from every preference tier;
- has no participation cap;
- is in the residual with weight `exit_terms(as_of).units`.

A common position with `u_i` shares is excluded from the tiers, is uncapped, and is in the
residual with weight `u_i`. Nothing else reads the position. So the tier payments, the
residual set, the weights and the caps are identical, and so is every payment. ∎

**What it implies.** Stage 2 with forced conversions is an ordinary table, so its payoff
uniqueness is the existing empirical question on a table with more common stock. The
governed outcome is a deterministic function of two unique payoff vectors and the vote. So
the vote model adds exactly one new source of indeterminacy: pivotal indifference, which is
refused.

**Tests.** `test_proposition_g1_on_the_engine` compares `evaluate_fixed_waterfall` on both
tables in every profile. The vote search checks the same equality exactly on every profile of
every instance.

## The constraint model, and what NVCA §2.1 computes

The NVCA non-participating §2.1 does not ask holders to convert. It pays each series "the
greater of (i) [__ times] the applicable Original Issue Price ... or (ii) such amount per
share as would have been payable had all shares of such series of Preferred Stock (and all
shares of all other series of Preferred Stock that would receive a larger distribution per
share if such series of Preferred Stock were converted into Common Stock) been converted".
That is a per-series computation, the constraint model (a), with each series as the unit.
fn 18 describes the circularity and names the alternative this engine implements:

> "Some versions of Preferred Stock terms simply state that the liquidation payment to be made
> to a particular series of Preferred Stock is equal to the original purchase price ... rather
> than the higher of such amount and the as-converted payment. That alternative formulation is
> not intended to result in a substantive difference from the approach taken in this form;
> rather, in that alternative formulation, it is assumed that the holders of a particular
> series of Preferred Stock would simply convert ... That is, each holder of Preferred Stock
> must decide whether it will receive a higher payment if it converts into Common Stock; and
> such determination would require each holder of Preferred Stock to make an assumption as to
> whether the other holders of Preferred Stock (both of the same series and of different
> series) will convert into Common Stock."

The engine's per-position game is that alternative formulation. The Voting Agreement's
equal-per-share condition (s.3.2(f)(ii)) and the §2.1 per-series wording both require every
share of a series to receive the same amount. The question is whether the per-position game
ever breaks that, or pays differently from the per-series computation. fn 18 says it is "not
intended to result in a substantive difference", an intention rather than a result.

**Proposition G2.** Give the positions of one series identical per-share terms: price,
multiple, participation, cap multiple, ratio, seniority and dividend. Let them move together.
Then in every profile, the series receives exactly what one position holding all its shares
would receive, and each position receives its pro-rata share of that.

**Proof.** The series' preference claims are `shares_i × price × m` in one tier, so the tier
pays them pro rata to shares and in total what the merged claim gets. The residual weights
`shares_i × ratio` add. For a capped participant, headroom over weight is
`(c × price − paid_per_share) / ratio`, the same for every position of the series. So all of
them cap at the same cash-per-unit level, as the merged position does. ∎

So the constraint model on a homogeneous series is the ordinary game on the merged table, and
its payoff uniqueness is again the existing question. What G2 does not settle is whether the
per-position game on the split table and the constrained game agree. The series search below
tests that directly.

## Re-verifying payoff uniqueness under the new strategy spaces

**Method.** Recorded 2026-09-15. Both searches use an exact-rational oracle
(`exact_allocation` in `tests/test_governance.py`), written without reference to
`ovf.waterfall`. It does its own tiering and water-filling over `fractions.Fraction`. It was
first checked against the hand-derived README and GV1/GV6 numbers
(`test_oracle_reproduces_hand_derived_fixtures`). Generators and seeds are checked in. The
full run is replayed with `python -m tests.test_governance 3000 3000 6` (tables for each
search, then worker processes), and a six-table subset of each search runs in pytest.

Tables are generated at random, with deliberately adversarial structure:

- 2–4 preferred positions;
- common from zero to 2,000 shares;
- multiples 1, 1.5 or 2;
- participation with caps equal to the multiple or up to 2x above it;
- conversion ratios 0.5, 1, 1.5 or 2;
- seniority collisions;
- identical classes;
- one holder owning two positions;
- an investor also holding the common.

Every input is exactly representable in binary floating point.

Exits are placed exactly on breakpoints, then 1/1000 either side, plus four random exits per
table. The breakpoints, all computed in exact arithmetic, are:

- the cumulative preference levels of every profile;
- every exit at which a position is indifferent to its own conversion in some profile;
- for the vote search, every exit at which a voting holder's `Δ_h` is zero.

The last are the vote knife edges. At most 40 exact breakpoints are kept per table.

**Search A, the vote model.** The terms convert all preferred (60%) or a random subset. The
Requisite Holders threshold is drawn from more than 1/2, at least 1/2, at least 3/5 and at
least 2/3. In 30% of terms a series consent is added. Each instance is solved exactly, and
the float engine is run at the float nearest the exit, compared with the oracle at that same
float.

| Search A, vote model, exact rational (seed 20260915) | Count |
|---|---|
| Tables / instances (table × exit) | 3,000 / 252,039 |
| Instances where a stage (without or with the conversion) has more than one equilibrium payoff vector | **0** |
| Instances where no profile allocates the whole exit | 0 |
| Proposition G1 mismatches, every profile of every instance | **0** |
| Determinate outcomes | 238,151 |
| of which the conversion is approved | 62,680 |
| Refused: an exactly indifferent holder decides the vote and the outcomes pay differently | 13,888 |
| Float engine matches the oracle (approval, then every payout within 8 tolerances) | 238,141 |
| Float engine refuses where the oracle finds the tie | 13,888 |
| Float engine differs, at a float exit where a voting holder's exact gain is within 4 tolerances of zero | 10 |
| Float engine differs, unexplained | **0** |
| Tables in which some position's cash falls between consecutive exits, **with** the term | **1,246** |
| The same, **without** the term (the per-position equilibrium) | **0** |

The full run of both searches took 2 min 45 s on six processes.

Approval always moves cash: consent needs a strict gain. Every approved instance therefore
pays differently from the unique per-position equilibrium. The refusal rate, 5.5%, is high by
construction: exits were placed on the roots of every voting holder's gain, which are the
vote's knife edges.

**Search B, the constraint model.** 1–3 series with identical per-share terms, each split into
1–3 positions, with at most five positions in all. Each instance compares three things
exactly: the per-position game on the split table, the constrained game (series as players,
each maximising its total), and the merged table of Proposition G2.

| Search B, constraint model, exact rational (seed 20260916) | Count |
|---|---|
| Tables / instances | 3,000 / 218,331 |
| Proposition G2 mismatches, every series profile of every instance | **0** |
| Unequal cash per share inside a series moving together | 0 |
| Per-position game: instances with several equilibrium profiles | 63,119 |
| Per-position game: instances with more than one equilibrium payoff vector | **0** |
| Constrained game: instances with several equilibrium profiles | 69,690 |
| Constrained game: instances with more than one equilibrium payoff vector | **0** |
| Instances where the per-position and constrained equilibrium payoffs differ | **0** |
| Per-position equilibrium profiles in which one series' positions elect differently | 224,428 |
| of which pay unequal cash per share within that series | **0** |
| Float engine on the merged table agrees with the exact merged game | 218,331 |

### What the two searches support

- **Payoff uniqueness survived both new strategy spaces in every instance searched.** Search
  A played two stage games in each of 252,039 instances, and Search B two games in each of
  218,331. None had a second equilibrium payoff vector in exact arithmetic. A counterexample
  was looked for, with exits placed on every breakpoint and every vote knife edge, and none
  was found.
- **The vote model adds exactly one new source of indeterminacy:** a holder who gains nothing
  deciding the vote. Proposition G1 predicts this, and the search found no other. The engine
  refuses those cases, and refused every one the oracle found.
- **On homogeneous series the constraint model changes no number.** The per-position game
  and the per-series game gave the same equilibrium payoffs in every instance. fn 18's
  intention of "no substantive difference" held throughout. The per-position game often
  reports a profile that splits a series, but only where the split positions are
  indifferent, and such a split always paid equal cash per share. The engine's payouts
  therefore respected the Voting Agreement's equal-per-share condition in every instance.
  `Payout.converted` can still differ between two positions of one series.
- **A new property appears under the vote.** In 1,246 of 3,000 tables some position's cash
  fell as the exit rose. Without the term, none did at the same exits.

### What they do not support

- **No proof.** Neither search establishes payoff uniqueness. Propositions G1 and G2 reduce
  both games to ordinary tables, so both inherit exactly the empirical status of
  [findings](findings.md).
- **Limited coverage.**
  - Search A covers 2–4 preferred positions; Search B covers at most five positions and
    only series with identical per-share terms.
  - Terms were drawn from the ranges above. Debt and dividends were not generated: debt is a
    constant deduction, and dividends reduce to dividend-free tables by Proposition 1 in
    [dividends](dividends.md).
  - Series whose positions differ per share are not examined. That is the case in which the
    NVCA per-series formula and the per-position game could come apart.
- **Generated tables are not real tables.**

## A finding: under a collective conversion, cash can fall as the exit rises

On the README table with a majority Requisite Holders term:

- at **$57.4M** Series B keeps its $9M preference (GV6b);
- at **$57.6M** it is converted and receives **$7,513,043.48** (GV6a).

A $200,000 higher price costs Series B **$1,486,956.52**, which is 34.2/23 M. At **$57.5M**
Series A is exactly indifferent and holds the majority, so the outcome is refused (GV6).
Without the term, Series B receives $9M at all three exits. The README's payoff curves are
continuous and never fall. Under a mandatory-conversion vote they can jump down, at the exit
where the controlling holder's gain from the conversion crosses zero.
`test_governance_makes_series_b_cash_fall_as_the_exit_rises` asserts it. In the vote search,
some position's cash fell between consecutive exits in 1,246 of 3,000 generated tables with
the term. Without it, the same happened in none of them.

### A second, much larger step on the same table, found while building `ovf.opm`

Added 2026-09-15. Deriving the exit breakpoints of this table analytically, rather than
sampling it, turned up a step this section had missed. It sits at

    X = 207,000,000 / 19 = $10,894,736.84

and it is far bigger than the $57.5M one, because the class that moves is the common:

| exit | vote | common | Series A | Series B |
|---:|---|---:|---:|---:|
| $10,894,736 | approved | **$7,578,946.78** | $1,894,736.70 | $1,421,052.52 |
| $10,894,737 | fails | **$0.00** | $1,895,000.00 | $9,000,000.00 |

One dollar more on the sale price, and the founders receive nothing instead of
$7,578,946.78. The fall is 144,000,000/19 = **$7,578,947.37**.

It runs the other way from the $57.5M case, and that is the point of recording it. There the
vote switched *on* as the exit rose and stripped a dissenting preferred series. Here it
switches *off*: below the step Series A still gains by converting and carries the majority,
so everyone converts and the common shares in the proceeds; above it Series A prefers its
preference, the vote fails, and the preference stack of $19M absorbs the whole $10.9M exit
with nothing left for the common. So "a higher exit can only hurt the preferred" is not the
lesson. Either side of the vote can be the loser, and the common can lose the most.

This was not found by searching over exits. It was found because the vote flip is the root of
a holder's gain function, which is an analytic candidate; `ovf.opm.breakpoints` solves for it
in exact rational arithmetic and then checks the engine either side. A grid would have had to
land within a dollar of 207,000,000/19 to see it at all.

## Fixture derivations

**Shared table** (`tests/governance_fixtures.py`, `TABLE`), the README example:

| Position | Shares | Price | Invested | Terms | Votes (as-converted) |
|---|---|---|---|---|---|
| `common` (founders) | 8,000,000 | — | — | residual | — |
| `series_a` | 2,000,000 | $2.50 | $5,000,000 | junior (2), 1x participating, total capped at 2x = $10M | 2,000,000 = **4/7** |
| `series_b` | 1,500,000 | $6.00 | $9,000,000 | senior (1), 1x non-participating | 1,500,000 = **3/7** |

With every position converted there are 11,500,000 units, so each unit receives `X / 11.5M`.
Series A then gets `2/11.5 X` and Series B `1.5/11.5 X`. Without a vote, the README
equilibrium applies:

- Series A is capped at $10M from $39M;
- Series A converts above $59M;
- Series B converts above $69M.

**GV1: the Omneon mechanism, $60M, "more than 1/2".**

- *Without:* the README. Series B takes $9M. Series A converts and gets 20% of $51M =
  **$10.2M**, and founders get **$40.8M**.
- *With:* $60M / 11.5M units = 120/23 per unit. Series A gets 240/23 M = **$10,434,782.61**,
  Series B 180/23 M = **$7,826,086.96** and founders 960/23 M = **$41,739,130.43**. The sum
  is 1380/23 M = $60M.
- *Changes:* Series A +5.4/23 M (**+$234,782.61**), Series B −27/23 M (**−$1,173,913.04**),
  founders +21.6/23 M.
- *Vote:* Series A consents with 4/7 > 1/2, so the conversion is **approved**.

Series B's preference is stripped: 27/23 M leaves it, 5.4/23 M to Series A and 21.6/23 M to
founders. The converted profile is not an equilibrium of the individual game, because B would
un-convert, and the test asserts that too.

**GV2: "at least 3/5".** The same changes, but 4/7 = 57.1% < 60%, so the vote is **not
approved**. The payout is the README's: $10.2M, $9M and $40.8M.

**GV3: a Series B consent added under fn 64.** The Requisite Holders approve (4/7 > 1/2). Series
B, voting alone, withholds, so the conversion is **not approved** and the README payout stands.

**GV4: $100M, nothing to decide.** Without a vote both series already convert:

- Series B converting gets 1.5/11.5 × $100M = $13.04M, above $9M;
- Series A converting gets 2/11.5 × $100M = $17.39M, above its $10M cap.

Both branches pay 400/23 M (**$17,391,304.35**) to Series A, 300/23 M (**$13,043,478.26**) to
Series B and 1600/23 M (**$69,565,217.39**) to founders. Every change is 0, so both holders
are indifferent. The vote is not approved and `changes_payout` is False.

**GV5: $20M, a conversion no one wants.**

- *Without:* Series B takes $9M. Series A holds: its $5M preference plus 20% of the $6M
  residual gives **$6.2M**, below the cap. Converting would pay 20% × $11M = $2.2M, and Series
  B converting would pay 1.5/11.5 × $15M = $1.96M. Founders get **$4.8M**.
- *With:* Series A gets 80/23 M = $3,478,260.87, a change of −62.6/23 M
  (**−$2,721,739.13**). Series B gets 60/23 M = $2,608,695.65, a change of −147/23 M
  (**−$6,391,304.35**).

Both withhold, so the conversion is not approved. (The first draft of this fixture used
40/23 and 30/23, the values for 1,000,000 shares; the test failed, and the arithmetic was
redone as shown.)

**GV6: the knife edge at $57.5M, refused.** $57.5M / 11.5M = exactly **$5 a unit**.

- *Without:* Series B takes $9M, and Series A holds at its cap. Its preference of $5M plus
  2/10 of $43.5M would be $13.7M, so it gets **$10M**. Converting would pay 20% × $48.5M =
  $9.7M, so Series A holds. Founders get $38.5M.
- *With:* Series A gets 2M × $5 = **$10M**, Series B 1.5M × $5 = $7.5M and founders $40M.

Series A's change is exactly zero, and it holds the majority. Counted as consenting, it
converts Series B and moves $1.5M from Series B to founders; counted as withholding, it does
not. The call raises `GovernanceIndeterminateError`, naming Series A and the tolerance
(5.75e-05).

**GV6a: $57.6M.** $57.6M / 11.5M = 5.00869565 a unit.

- *Without:* Series B takes $9M. Series A holds at $10M, since converting would pay 20% ×
  $48.6M = $9.72M. Founders get $38.6M.
- *With:* Series A gets 230.4/23 M = **$10,017,391.30**, Series B 172.8/23 M =
  **$7,513,043.48** and founders 921.6/23 M = **$40,069,565.22**.
- *Changes:* Series A +0.4/23 M = +$17,391.30, Series B −34.2/23 M. Series A consents, so the
  conversion is **approved**.

**GV6b: $57.4M.**

- *Without:* Series A gets $10M, since converting would pay 20% × $48.4M = $9.68M. Series B
  gets $9M and founders $38.4M.
- *With:* Series A would get 229.6/23 M = $9,982,608.70, a change of −0.4/23 M, and Series B
  172.2/23 M, a change of −34.8/23 M.

Both withhold, so the conversion is **not approved**.

**GV7: holder-level voting.** Series A is split between two funds. `series_a1` (1,500,000
shares) belongs to `fund_a`. `series_a2` (500,000 shares) belongs to `fund_b`, which also holds
all of Series B. The terms are those of Series A.

- *Without,* at $60M: Series B takes $9M. Each Series A position converting gets its units ×
  $51M / 10M:
  - `series_a1`: 1.5M × 5.1 = **$7.65M**. Holding would reach its cap of 1.5M × $2.50 × 2 =
    $7.5M, which is less.
  - `series_a2`: 0.5M × 5.1 = **$2.55M**. Its cap is $2.5M.
  - Series B converting gets 1.5/11.5 × $60M = $7.83M, less than $9M.

  Founders get $40.8M.
- *With:* each unit gets 120/23. `series_a1` gets 180/23 M (+4.05/23 M), `series_a2` 60/23 M
  (+1.35/23 M) and Series B 180/23 M (−27/23 M).
- *By holder:* `fund_a` gains +4.05/23 M (**+$176,086.96**) and consents with 1.5M votes.
  `fund_b` changes by 1.35/23 − 27/23 = −25.65/23 M (**−$1,115,217.39**) and withholds with
  0.5M + 1.5M = 2.0M votes. 1.5/3.5 = 3/7 < 1/2, so the conversion is **not approved**.

*The choice matters:* counted by position, `series_a2` would consent too, giving 2.0/3.5 =
4/7 > 1/2, and the conversion would pass.

**GV8: GV1 behind a loan.** A $1,000,000 loan at 8% simple, Actual/365 Fixed, issued
2025-01-01. As of 2027-01-01 it has accrued 730 days: $1,000,000 × 0.08 × 730/365 = $160,000.
The loan takes **$1,160,000** of the $61.16M, and the remaining $60M is GV1 exactly. The vote is
approved, and the payouts and changes are GV1's.

**GV9: a dividend forfeited by the conversion.** Series B carries an 8% simple cumulative
dividend from 2025-01-01, forfeited on conversion ([dividends](dividends.md)). As of
2027-01-01 it has accrued $9,000,000 × 0.08 × 2 = **$1,440,000**, so B's preference is
$10.44M. At $60M:

- *Without:* Series B takes $10.44M.
  - Series A holding gets its $5M preference plus 2/10 of $44.56M, which would be $13.912M,
    so it is capped at **$10M**. Converting would pay 20% × $49.56M = $9.912M, so Series A
    holds.
  - Series B converting, with A holding, would get $7.89M, less than $10.44M.
  - Founders get **$39.56M**.
- *With:* GV1's split, since the dividend is forfeited: 240/23 M, 180/23 M and 960/23 M.
- *Changes:* Series A 240/23 − 10 = +10/23 M (+$434,782.61). Series B 180/23 − 10.44 =
  −60.12/23 M (**−$2,613,913.04**), which includes the whole $1.44M accrued dividend. Series
  A consents with 4/7 of the votes, so the conversion is **approved**. NVCA s.5.2 pays only
  "any declared but unpaid dividends" on a mandatory conversion.

**At exactly the threshold.** With a threshold of 4/7, Series A's 2,000,000 of 3,500,000
votes is exactly the threshold. The comparison is exact: "at least 4/7" is approved
(the GV1 payout) and "more than 4/7" is not (the README payout).

## Regression evidence

`waterfall.py` is the file the whole repository depends on. Before it was edited, 12,379
results were captured as JSON:

- every fixture of `tests/fixtures.py`, `debt_fixtures.py`, `dividend_fixtures.py` and
  `financing_fixtures.py`, at 19 exits, with and without `as_of`, with and without
  transaction costs;
- `solve_waterfall` and `enumerate_equilibria` on each, `CapTable.waterfall_detailed`,
  `settle_debt`, `accrue_dividends`, `multi_position_holders`, and every profile of
  `evaluate_fixed_waterfall`;
- the slow game at 58 exits;
- 400 seeded random tables at 6 exits with surveys;
- 10 recorded error messages.

After the edit, all 12,379 were **byte-identical**. That covers payouts, conversion
profiles, `input_hash`, assumptions, iterations, `max_unilateral_gain`,
`conservation_error`, debt settlements, dividend accruals and equilibrium surveys.

- `EquilibriumSurvey.forced_conversions` is omitted from dumps when empty, as
  `PreferredStock.dividend` is when `None`, so a survey's JSON is unchanged.
- `forced_conversions` enters the fingerprint and the assumptions only when non-empty.
- `test_no_forced_conversion_is_byte_identical` recomputes each F-fixture's hash from the
  pre-governance payload and checks the assumptions and dumps.
- No existing test was edited.

## Sources

### Verified against the text

- **NVCA Model Certificate of Incorporation, October 2025**
  ([.docx](https://nvca.org/wp-content/uploads/2025/10/NVCA-Model-COI-10-1-2025.docx)), read
  from the published file for this work. Read in full:
  - §§2.1 (both alternatives), 2.2, 2.3.1, 2.3.2(a) and 2.3.4;
  - §3.1 and §3.3 (preamble and 3.3.1);
  - §4.1.1, 5.1, 5.2 and 5A.1;
  - the Waiver section;
  - fns 16, 18, 20, 22, 23, 38, 63, 64 and 65.

  **Numbering.** A footnote number here is the displayed number, which is the XML id minus
  one. The text confirms this: the footnote on the mandatory-conversion vote (id 65) says
  "see footnote 22" and means the Deemed Liquidation Event vote footnote (id 23). Section
  numbers follow the document's cross-references ("Section 2.3.1(a)(i)", "Section 3.3.9(f)",
  "Section 5.1") and heading order. The item letter in "s.5.1(b)" is inferred from the
  heading style, because the automatic numbering does not survive text extraction.
- **NVCA Model Voting Agreement, October 2025**
  ([.docx](https://nvca.org/wp-content/uploads/2024/10/NVCA-Model-VA-10-1-2025.docx), linked
  from nvca.org's "Updated Oct 2025" page). Read: §3.1 (Actions to be Taken), §3.2
  (Conditions) and §3.3 (Restrictions on Sales of Control), with footnotes. The June 2019
  model ([.docx](https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Document-Voting-Agreement.docx))
  has the same allocation condition as s.3.3(f).
- **Broughman & Fried (2010)**, JFE 95(3), 384–399, for the citation and the finding. The
  quoted figures are from the authors' own summary on the Harvard Law School Forum on
  Corporate Governance (16 November 2008). The journal text was not obtained; see below.

### Not verified

- **The *Omneon* and *Greenmont* opinions themselves.** Both court texts returned HTTP 403
  from the repositories tried. Their holdings are quoted from NVCA fn 64 and from the
  summaries of Potter Anderson (*Omneon*) and Delaware Counsel Group (*Greenmont*).
  **UNVERIFIED** at the primary source: the vote thresholds and the series percentages in
  those companies' charters. Nothing in this module depends on a number from either case.
- **Broughman & Fried journal text.** **UNVERIFIED** beyond the authors' summary. Nothing
  computed here depends on it.
- **Whole-share vote counting.** COI §3.1 gives each holder votes "equal to the number of
  whole shares of Common Stock into which the shares of Preferred Stock held by such holder
  are convertible". Weights here are unrounded as-converted shares; see Not modelled.

## Not modelled

| Not modelled | Why it would change a real number |
|---|---|
| **Bargaining over a sale (Broughman & Fried)** | Carve-outs negotiated with a veto holder moved 11% of VC cash-flow rights in 11 of 50 sales. Price the amended table instead; the engine does not guess the bargain. |
| **Drag-along and protective provisions as inputs** | They decide whether a sale happens, not its split. A caller asking "can this be blocked" needs a no-sale value, which a cap table does not contain. |
| **Several independent votes at one exit** | Each outcome changes every other voter's gain, so they need a voting-game solution. One term with conjunctive approvals is supported. |
| **Strategic voting, coalitions, side payments** | Sincere voting is the stated solution concept. A holder that trades its vote changes the outcome. |
| **Whole-share vote rounding** (COI §3.1) | Fractions of a vote are counted here. At a threshold, a fraction can decide the vote. |
| **Waiver of Deemed Liquidation Event treatment** (s.2.3.1, fn 22) | Waiving it "means that the Preferred Stock has waived its right to be treated in a manner superior to the Common Stock". The split that replaces the charter's is then set by the transaction, not by a formula here. |
| **The NVCA per-series "greater of" computation** (§2.1, fn 18) | The engine plays fn 18's per-position "alternative formulation". The search below compares the two on homogeneous series. Series with non-identical per-share terms are not covered. |
| **The capped-participation counterfactual of fn 20** | fn 20 pays "the greater of (i) the Maximum Participation Amount and (ii) the amount such holder would have received if all shares of Preferred Stock had been converted", a counterfactual in which **all** preferred convert. The engine compares with the position's own conversion. The two can differ when other series would not convert. |
| **Special mandatory conversion (pay-to-play, §5A)** | Triggered by failing to buy a Pro Rata Amount in a financing, at a possibly punitive rate (fn 65). It belongs to a financing event, not to an exit. |
| **Mandatory conversion at an IPO or direct listing** | Not an exit this engine prices. |
| **Suspension of optional conversion** (§4.1.1 bracket) | During a pending special mandatory conversion, optional conversion is suspended. Not relevant at an exit, and not read. |
| **Vote record dates, written-consent mechanics, notice periods** | Procedure, not payout. |
| **Coordinated holders in stage 2** | A holder votes once on its total, but its positions still elect independently in the conversion game. |

## For integration (coordinator)

- **Exports.** From `ovf.governance`: `CollectiveConversion`, `VoteRequirement`,
  `VoteComparison`, `resolve_collective_conversion`, `CollectiveConversionResult`,
  `HolderDecision`, `ApprovalTally` and `GovernanceIndeterminateError`. From `ovf.waterfall`:
  `forced_conversion_ids`, if wanted. The new keyword `forced_conversions` on
  `solve_waterfall` and `enumerate_equilibria` is already reachable.
- **[limitations](limitations.md).** "Class voting, drag-along, protective vetoes" should
  become: mandatory conversion by a Requisite Holders vote is modelled (link here);
  drag-along and protective provisions gate a sale and move no cash; several votes at one
  exit, strategic voting and bargaining are not modelled.
- **[semantics](semantics.md).** "Shared class voting ... not represented" is superseded for
  the one mechanism above.
- **[findings](findings.md).** The open item on coordinated owners is unchanged. Add the two
  searches here as an evidence item.
- **Roadmap and TODO language.** "Class-majority conversion" should read "mandatory
  conversion of all preferred on a Requisite Holders vote", for the reasons above.
- **README.** The payoff curves there assume no collective conversion. Under one they can
  fall as the exit rises (the GV6 finding).

## What a fixture does not establish

A fixture shows that the implementation reproduces a derivation stated here. It does not
show:

- that a given charter uses the NVCA mandatory-conversion wording, its threshold or its
  voting group;
- that holders vote sincerely;
- that a real sale would not be renegotiated.

The list above is the companion to this document.
