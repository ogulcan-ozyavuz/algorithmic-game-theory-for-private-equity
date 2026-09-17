# Open Cap Format (OCF) adapter

Status 2026-09-15. Module `ovf.ocf`: `from_ocf`, `import_ocf`, `load_ocf_package`,
`to_ocf`, `write_ocf_package`, and for convertible notes `OcfNoteTerms` and
`note_terms_from`.

OCF standardises cap-table **data**. It defines no computation over that data: nothing in
the format says how an exit is distributed. This adapter maps the payout-relevant part of
an OCF package into ovf securities, and back. This document states exactly which OCF
fields are honoured, which are refused and which are ignored, so that someone who works on
a cap-table system can disagree with a specific line.

## Target version and how it was checked

- **Target: OCF v1.2.0**, tag commit `9f987b48e288703ff2cd6c4534f7769bb04e724a` (tagged
  2024-08-21), <https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/tree/v1.2.0>.
  Network access was available. Every field below was read from the JSON Schema files at
  that tag, not from memory or from a secondary description.
- `main` at `095182023cd620cc55d49777b5c8f75a3376120b` (2026-07-13) was also inspected. Its
  manifest `ocf_version` constant is `1.2.1-alpha+main`. `StockClass.schema.json` differs
  from v1.2.0 only in `$id` URLs. A package declaring any `ocf_version` other than `1.2.0`
  is refused.
- **Schema validation.** During development, 40 writer-produced files (4 cap tables × 2
  participation-cap bases × 5 files each) and the 10 files of the two hand-built fixture
  packages were validated against the v1.2.0 schema with `jsonschema` 4.26 (Draft 7, with
  format checking, including RFC 3339 `date-time`). All 50 passed. As a check that the
  validator is not vacuous, OCF's own sample `Transactions.ocf.json` **fails** the same
  check (see [Findings about OCF itself](#findings-about-ocf-itself)).
- **Convertibles and warrants** were read at the same tag, on 2026-09-15:
  `objects/transactions/issuance/ConvertibleIssuance`, `WarrantIssuance`, the other five
  `Convertible*` transactions, `types/conversion_mechanisms/*`, `types/conversion_rights/*`,
  `types/conversion_triggers/*`, `types/InterestRate`, `types/Percentage`,
  `types/CapitalizationDefinition(Rules)`, the conversion primitives, and the enums
  `ConvertibleType`, `DayCountType`, `InterestPayoutType`, `AccrualPeriodType`,
  `CompoundingType`, `ConversionTimingType`, `ConversionTriggerType`. `git diff v1.2.0
  0951820` shows no change except `$id`/`$ref` URLs in `ConvertibleIssuance`,
  `NoteConversionMechanism`, `SAFEConversionMechanism`, `InterestRate`, `WarrantIssuance`,
  `DayCountType`, `CompoundingType` and `AccrualPeriodType`. Those eight are the files that
  set a note's numbers; the others were not diffed.
- The test `test_packages_validate_against_the_ocf_schema` repeats that validation for the
  three hand-built fixtures (including `two_series_with_notes`), every writable waterfall
  fixture and a writer-produced package holding notes. It passed on 2026-09-15 against the
  v1.2.0 checkout, with `jsonschema` 4.26.0 but without `rfc3339-validator`, so RFC 3339
  `date-time` format was not checked in that run. `jsonschema` and `referencing` are not ovf
  dependencies, so the test is skipped unless both are importable and `OCF_SCHEMA_DIR`
  points at the `schema/` directory of a v1.2.0 checkout:

  ```bash
  git clone https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF ocf
  git -C ocf checkout v1.2.0
  pip install jsonschema referencing rfc3339-validator
  OCF_SCHEMA_DIR=ocf/schema python -m pytest tests/test_ocf.py -k validate_against
  ```

## Licence

The OCF schema and documentation are published under the Open Cap Table Coalition
**"Schema and Documentation License v1.0.1"** (April 3, 2024). It is **not an
OSI-approved licence**. It permits copying with notices and permits derivative works "to
facilitate implementation of the technical specifications", provided they carry the
notice below. It states that "the publication of derivative works of OCF Files for use as
a technical specification is expressly prohibited". The same file licenses sample OCF
JSON and code ("Code Components") under Apache 2.0.

ovf is Apache-2.0. This adapter restates field names and constraints in order to read and
write the format. It does not copy schema files. `tests/ocf_fixtures/ocf_v1_2_0_sample/`
is a verbatim copy of Apache-2.0 sample files. Anything that depends on OCF inherits the
ambiguity of a custom, non-OSI licence over the schema text. This document does not
resolve that ambiguity and is not legal advice.

> Copyright © 2024 Open Cap Table Coalition. This software or document includes material
> copied from or derived from the Open Cap Format v1.2.0 schema,
> <https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/tree/v1.2.0/schema>.

## The four conventions that set numbers

### 1. Seniority is inverted

`schema/objects/StockClass.schema.json`, property `seniority`, at v1.2.0, verbatim:

> "Seniority of the stock - determines repayment priority. Seniority is ordered by
> increasing number so that stock classes with a higher seniority have higher repayment
> priority. The following properties hold for all stock classes for a given company:
> a) transitivity: stock classes are absolutely stackable by seniority and in increasing
> numerical order, b) non-uniqueness: multiple stock classes can have the same Seniority
> number and therefore have the same liquidation/repayment order. In practice, stock
> classes with same seniority may be created at different points in time and (for
> example, an extension of an existing preferred financing round), and also a new stock
> class can be created with seniority between two existing stock classes, in which case it
> is assigned some decimal number between the numbers representing seniority of the
> respective classes."

ovf pays the **lowest** integer first (`PreferredStock.seniority`, 0 or 1 before 2). The
two directions disagree, so:

**Mapping: an OCF class with a higher `seniority` number is repaid earlier, so the reader
sorts the distinct PREFERRED seniority values from highest to lowest and assigns ovf ranks
1, 2, 3, … in that order, where ovf rank 1 is paid first.**

- Equal OCF values receive the same ovf rank and are paid pari passu. A shortfall inside
  a rank splits in proportion to preference, as in the NVCA model charter §2.1 ("shall
  share ratably … in proportion to the respective amounts which would otherwise be
  payable").
- Seniority is an OCF `Numeric`, so decimals such as `2.5` are accepted and ranked.
- Every COMMON class must carry one shared seniority value, strictly below every PREFERRED
  class's value. Anything else is refused, because ovf pays all common from one residual.
- The writer inverts the other way. With `k` distinct ovf preferred seniorities, the most
  senior becomes OCF `k + 1`, the most junior becomes `2`, and the common class `1`.
- Pinned by `test_seniority_direction_follows_the_schema_text`, whose docstring quotes the
  sentence above. Its two-series fixture (case O1) pays differently under the two
  readings, so an inverted mapping fails that test.

OCF's own sample agrees with this reading: its Common Stock has seniority `"1"` and its
Series Seed Preferred `"2"`.

### 2. Preference = multiple × class price

The preference per share is `liquidation_preference_multiple × StockClass.price_per_share`.
This follows the NVCA model certificate of incorporation (October 2025, §2.1), which sets
the preference as "[__ times] the applicable Original Issue Price". Its "Original Issue
Price" is defined per series, not per holder.

- A PREFERRED class without `price_per_share` is refused. The reader does not fall back to
  `conversion_price` or to issuance prices.
- A PREFERRED class without `liquidation_preference_multiple` is refused. 1x is not
  assumed.
- An issuance whose `share_price` differs numerically from its class's `price_per_share`
  (or is in another currency) is refused, because the reader would have to choose which
  price bases the preference. The comparison is on decimal values, so `2.5` equals `2.50`.
- The schema's description reads "The liquidation preference per share for this stock
  class", but the field is named `_multiple`. It is read as a multiple, following the name.

### 3. Participation

OCF v1.2.0 has **no participating flag**. The only participation field is
`participation_cap_multiple`, described as "The participation cap multiple per share for
this stock class". The schema, the documentation and the repository's issues do not say
what an absent value means, or whether the cap includes the preference. The coordinator
decided the reading on 2026-09-15:

- **Absent `participation_cap_multiple` means non-participating.** If absence meant
  uncapped participation, OCF could not express non-participating preferred at all, and
  that is the dominant market term (Cooley's Q2 2026 venture financing report: 96.4%
  non-participating).
- **A present cap means participating, capped on the total** (preference plus
  participation) by default, `participation_cap_basis="total"`. This is the NVCA reading:
  the drafting footnote to §2.2 (participating alternative) of the October 2025 model
  charter says, verbatim, "if the aggregate amount which the holders of Preferred Stock are
  entitled to receive under Sections 2.1 and 2.2 shall exceed [$_______] per share … (the
  “Maximum Participation Amount”), each holder of Preferred Stock shall be entitled to
  receive … the greater of (i) the Maximum Participation Amount and (ii) the amount such
  holder would have received if all shares of Preferred Stock had been converted into
  Common Stock". That is also what `PreferredStock.participation_cap` already means,
  which is why ovf requires `participation_cap >= liquidation_multiple`.
- **`participation_cap_basis="participation_only"`** reads the cap as a bound on
  participation received on top of the preference, so the ovf total cap is
  `liquidation_preference_multiple + participation_cap_multiple`. Use it when the system
  of record means that. Case O6 shows the two bases give different payouts from the same
  file.
- A default is allowed here because a named drafting standard backs it. Contrast the
  anti-dilution denominator in the parallel anti-dilution work, which gets no default,
  because no standard settles it.
- Under the total basis, a cap below the preference multiple is refused, because such a
  cap could never be met.
- OCF's sample sets `participation_cap_multiple` equal to `liquidation_preference_multiple`
  on both classes. Under the total basis that term pays exactly what non-participating
  pays. It is treated as placeholder data, not as evidence for either reading.

### 4. Conversion ratio

A PREFERRED class must have exactly one conversion right: a `RATIO_CONVERSION` (the only
mechanism v1.2.0 allows for a stock class), converting into an existing COMMON class,
with `converts_to_future_round` not true. The ovf `conversion_ratio` is
`ratio.numerator / ratio.denominator` ("One share of this stock class converts into this
many target stock class shares"). It is evaluated exactly with `Fraction`, then converted
to float once.

`TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT` replaces the ratio as of its date, and the
latest date wins. OCF says the new ratio "is calculated outside of OCF"; ovf applies the
stated ratio and computes nothing.

## Finding: participating-uncapped preferred is not expressible in OCF v1.2.0

An absent cap reads as non-participating, and there is no flag. So a preferred class that
participates **without** a cap has no encoding in OCF v1.2.0. `to_ocf` refuses such a
position with `OcfUnsupportedError`. It does not emit it as non-participating, which would
understate the investor, and it does not write a large cap, which would invent a term that
is not in the charter. Fixtures F4 and F10 (docs/fixtures.md) are refused on export for
this reason. The standard carries the data. It cannot carry this piece of the meaning.

## Finding: an OCF v1.2.0 package cannot round-trip a convertible note's economics

ovf's `ConvertibleNote` needs, to accrue interest at all, a principal, an annual rate, an
accrual method, a day count and an issue date; to be a note it also needs a maturity date
and a qualified-financing threshold. An OCF v1.2.0 `TX_CONVERTIBLE_ISSUANCE` carries some
of these, carries others only as free text, and has no field at all for the rest:

| ovf `ConvertibleNote` field | OCF v1.2.0 source | Readable? |
|---|---|---|
| `principal` | `investment_amount`: "Amount invested and outstanding on date of issuance of this convertible" | Yes |
| `issue_date` | `date`. Each `InterestRate` also has its own `accrual_start_date` | Yes, when the two agree |
| `annual_rate` | `interest_rates[].rate`, inside a `NoteConversionMechanism`, inside one conversion trigger | Only with one note mechanism and exactly one rate. `interest_rates` may be empty ("if applicable"), and the `Percentage` pattern admits `""` |
| `accrual` | `compounding_type`: `COMPOUNDING` or `SIMPLE` | `SIMPLE` only |
| `compounding_frequency` | **No field** | No |
| `day_count` | `day_count_convention`: `ACTUAL_365` or `30_360` | No. What `ACTUAL_365` means is an open OCF issue (§6), no 30/360 variant is named, and Actual/360 has no value |
| `maturity_date` | **No field** | No |
| `qualified_financing_threshold` | Free text in `trigger_condition`: "Legal language describing what conditions must be satisfied" | No |
| `valuation_cap` | `conversion_valuation_cap` | Yes |
| `discount_rate` | `conversion_discount` | Yes |
| `exit_treatment` | **No field**. Every trigger is a *conversion* trigger; none says the note is repaid | No |
| `exit_principal_multiple` | `exit_multiple`: "For cash proceeds calculation during a liquidity event." | No. The text does not say what it multiplies |
| `seniority` | `seniority`: "1 being highest seniority" | Yes, in the opposite direction to `StockClass.seniority` (§5) |

Three structural facts make this worse than a list of missing fields:

- **Interest terms belong to a conversion mechanism, not to the instrument.** The rate,
  day count and compounding type sit inside `conversion_triggers[i].conversion_right.
  conversion_mechanism`. A note with three triggers can state three different sets of
  interest terms. A note whose only mechanism is `CUSTOM_CONVERSION`, or whose only
  trigger is `UNSPECIFIED`, states no interest terms at all.
- **Nothing ties `convertible_type` to the mechanism.** OCF's own sample
  `test-convertible-issuance-all-fields` has `convertible_type: "SAFE"` and a
  `CONVERTIBLE_NOTE_CONVERSION` mechanism with a three-rate interest schedule
  (`test_official_sample_convertibles_validate_and_are_refused_for_what_they_carry`).
- **The one dated trigger converts rather than repays.** `AUTOMATIC_ON_DATE` has a
  `trigger_date` "on which trigger occurs automatically". The official sample uses it
  as "Converts on Maturity". ovf's note is *repaid* at maturity (docs/debt.md), and no OCF
  trigger means "repayable".

The gap was raised in the format's own tracker. OCF issue #262 (closed 2022-11-15) notes
"a lack of a end date / maturity date in the existing mechanisms". At v1.2.0 the only end
date is `InterestRate.accrual_end_date`, which ends accrual at one rate; it is not a
maturity.

**Consequence.** The reader builds a note only from the OCF record *plus* caller-supplied
`OcfNoteTerms(maturity_date, qualified_financing_threshold, day_count)`, none of which has
a default. The writer puts those three values into comments and trigger text, which no
reader parses. A package that `to_ocf` writes is therefore refused by `from_ocf` until the
caller supplies them again. `test_a_note_does_not_round_trip_through_ocf_without_its_terms`
makes this a passing assertion: the export is refused on read; the maturity date appears in
no structured field; the threshold appears only in comments and in `trigger_condition`; and
with `note_terms_from(table)` resupplied, every field comes back exactly.

**Trust boundary.** The reader requires the qualified-financing trigger to exist and takes
its number from the caller. It never reads the trigger's text, which could state a
different threshold. The caller asserts that the two agree. `OcfImport.
qualified_financing_conditions` returns the text next to each note so the caller can check
it. Parsing legal prose would be guessing, and refusing every such note would refuse the
format's only way of stating the condition.

## Convertible notes: the conventions that set numbers

### 5. Convertible seniority runs the other way

`schema/objects/transactions/issuance/ConvertibleIssuance.schema.json`, property
`seniority`, at v1.2.0, verbatim (including its typo):

> "If different convertible instruments have seniorty over one another, use this value to
> build a seniority stack, with 1 being highest seniority and equal seniority values
> assumed to be equal priority"

That is the opposite of `StockClass.seniority` (§1), where a higher number is repaid
first. The two are read by separate code with separate comparators:

- **Notes:** the distinct `ConvertibleIssuance.seniority` values, **lowest first**, become
  ovf debt seniority ranks 1, 2, 3, …, where 1 is paid first. Equal values share a rank and
  are paid pari passu, pro rata by claim (docs/debt.md, DGCL §281(a)). The writer emits the
  dense rank unchanged: the most senior note is OCF `1`.
- **Stock classes:** unchanged. Highest first, as in §1.
- **The two scales are never compared.** OCF says the convertible stack applies where
  "different convertible instruments have seniorty over one another"; it says nothing
  about convertibles against stock classes. ovf pays every debt position, notes included,
  ahead of all equity (docs/debt.md, "Priority at exit").
- Pinned by `test_convertible_seniority_runs_opposite_to_stock_class_seniority`. In the
  notes fixture, Series B (class 3) is senior to Series A (class 2) *and* note CN-2
  (convertible 1) is senior to CN-1 (convertible 2). Case O7 pays differently under a
  shared comparator, so unifying the two fails that test.

### 6. Day count: OCF's value is a check, never the source

`enums/DayCountType` at v1.2.0: "Enumeration of how the number of days are determined per
period", with values `ACTUAL_365` and `30_360`. Nothing more.

- **`ACTUAL_365` is an open question in OCF itself.** OCF issue
  [#423](https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/issues/423),
  "What does our DayCountType ACTUAL_365 value actually mean?", has been open since
  **2023-05-10**. Its opening post sets out two interpretations of leap-year accrual and
  says "I'm starting to think that we may need multiple versions of 'Actual/365' in the
  schema". The comments report that implementers differ. One (2023-05-16) "doesn't
  (currently) implement either of the interpretations". One system's options are "365.25
  or 366" (2023-06-13). In another (2023-06-20), "for leap years, interest accrues over 366
  days". The last comment is dated 2023-06-20. A secondary source
  ([Wikipedia, "Day count convention"](https://en.wikipedia.org/wiki/Day_count_convention))
  lists "Actual/365" as another name for Actual/Actual ISDA, and "Act/365 Fixed" for
  Actual/365 Fixed. The ISDA text itself was not consulted.
- **What the choice is worth.** $1,000,000 at 8% simple from 2027-01-01 to 2029-01-01 is
  731 days, because 2028 has 29 February. Actual/365 Fixed:
  80,000 × 731/365 = **$160,219.18** (debt fixture A6). Actual/Actual ISDA:
  365/365 + 366/366 = 2.0 years, so **$160,000.00**. A 365.25-day year:
  58,480,000/365.25 = **$160,109.51**. The same OCF value gives three amounts.
- **Rule.** The caller states `OcfNoteTerms.day_count`. `ACTUAL_365` with `actual/365_fixed`
  proceeds. `ACTUAL_365` with `actual/360` is refused as a contradiction, and neither value
  is preferred. `30_360` is always refused: OCF does not say which 30/360 variant (30/360
  US, Bond Basis, 30E/360, 30E/360 ISDA, per the same secondary source) it means, and ovf
  implements none. A field that cannot determine the number can still catch a mistake.
- ovf's Actual/360 has no OCF value, so the writer refuses Actual/360 notes.

### 7. Interest: simple, daily, deferred, one rate

- **Compounding is not expressible.** OCF has a compounding *type* (`COMPOUNDING`,
  `SIMPLE`) and an accrual *period* (`DAILY` … `ANNUAL`, "What is the period over which
  interest is calculated?"), but **no compounding frequency**. #423's own worked example
  is "daily accrual + annual compounding", so the accrual period is not the compounding
  period. ovf requires an explicit frequency (docs/debt.md), so `COMPOUNDING` is refused
  on read. ovf compound and PIK notes are refused on write.
- **`SIMPLE` is read only with `interest_accrual_period: DAILY`.** ovf's simple interest is
  principal × rate × days / 365, which is daily accrual. OCF does not define how simple
  interest accrues over a monthly or annual period.
- **Exactly one `InterestRate`**, whose `accrual_start_date` equals the issuance `date` and
  which has no `accrual_end_date`. ovf's note has one rate from its issue date until
  maturity. None is not read as 0%, and a schedule of rates is refused.
- **`interest_payout: DEFERRED`** only. `CASH` means interest is paid out along the way,
  and ovf's claim assumes none has been paid since issue.
- `conversion_discount` absent means no discount, because OCF's text is "if applicable".
  A discount of 1 (100%) is refused, and so is the empty string.
- Notes are read **unresolved**: `exit_treatment` is `None`. OCF records no repayment
  outcome, so the caller states one with `ConvertibleNote.resolved()` before an exit, and
  the waterfall refuses an unresolved note (docs/debt.md).

## Field by field

"Honoured" means the value feeds the cap table. "Refused" means the package is rejected
with an error naming the field. "Ignored" means the value is validated for shape by the
strict models in `ovf/ocf/schema.py` and then not used. Unknown properties are always
refused, as the schema's `additionalProperties: false` requires.

### Manifest and files

| Field | Treatment | Why |
|---|---|---|
| `ocf_version` | Honoured; anything but `1.2.0` refused | Only v1.2.0 was verified. |
| `as_of` | Honoured; applied transactions dated later are refused | The package must describe the state it claims. |
| `issuer` | `legal_name` reported in the import trace; nothing else read | No issuer field changes a payout. |
| `generated_at`, `comments` | Ignored | Metadata. |
| `stock_classes_files`, `stakeholders_files`, `stock_plans_files`, `transactions_files` | Honoured: opened, MD5-checked, validated | These carry the payout-relevant state. |
| `stock_legend_templates_files`, `vesting_terms_files`, `valuations_files`, `financings_files`, `documents_files` | Not opened; listed in `OcfImport.unread_files` | See [Not modelled](#not-modelled). |
| `md5` | Verified by default; `verify_md5=False` skips it | A mismatch means a file changed after the manifest was written. |
| `filepath` | Resolved relative to the manifest; paths escaping the package directory are refused | Containment. |

ZIP containers are not read. Give the reader a directory or a manifest path.

### Stakeholder

| Field | Treatment | Why |
|---|---|---|
| `id` | Honoured as ovf `holder_id` | Identity. |
| Everything else (`name`, `stakeholder_type`, contacts, addresses, tax ids, `current_relationship`, `issuer_assigned_id`) | Ignored | ovf has no holder attributes besides the id. |

### StockClass

| Field | Treatment | Why |
|---|---|---|
| `id`, `class_type` | Honoured | Identity and COMMON/PREFERRED mapping. |
| `seniority` | Honoured, inverted; see §1 | Payout order. |
| `price_per_share` | Honoured for PREFERRED (required); ignored for COMMON | Preference basis. Common positions use their issuance price. |
| `liquidation_preference_multiple` | Honoured for PREFERRED (required). On COMMON: refused, or ignored with `ignore_common_preference_fields=True` | ovf cannot represent a preference on common. |
| `participation_cap_multiple` | Honoured for PREFERRED; see §3. On COMMON: as above | Participation. |
| `conversion_rights[0].conversion_mechanism.ratio` | Honoured (PREFERRED) | Conversion ratio. |
| `conversion_rights` count ≠ 1 on PREFERRED | Refused | None: ovf would let the class convert. Several: the reader would have to choose. |
| `conversion_rights` on COMMON | Refused | Conversion between common classes is not modelled. |
| `converts_to_future_round: true`, target not COMMON, target missing | Refused | Cannot be valued. |
| `conversion_price` | Ignored | The ratio sets the share count; an inconsistent price is not detected. |
| `rounding_type` | Ignored | ovf converts to fractional shares. |
| `votes_per_share` | Ignored | Voting is not modelled. |
| `par_value` | Ignored | Does not enter the distribution. |
| `initial_shares_authorized`, approval dates, `name`, `default_id_prefix`, `comments` | Ignored | Not payout-relevant. |

### StockPlan

| Field | Treatment | Why |
|---|---|---|
| `id` | Honoured as the pool's `security_id` and `holder_id` | An OCF plan has no holder. |
| `initial_shares_reserved` | Honoured, then overridden by `TX_STOCK_PLAN_POOL_ADJUSTMENT` (latest date wins) | Pool size counts in fully diluted ownership. |
| `stock_class_ids` / deprecated `stock_class_id` | Checked: must reference COMMON classes | ovf's pool is common-equivalent capacity. |
| `default_cancellation_behavior`, `plan_name`, dates | Ignored | The OCF text itself says "do not rely on this field"; grants are refused anyway. |

The pool is always read as entirely unallocated (`allocated_shares = 0`), because every
grant transaction is refused. An unallocated pool receives nothing at exit
(docs/semantics.md).

### StockIssuance (`TX_STOCK_ISSUANCE`)

| Field | Treatment | Why |
|---|---|---|
| `security_id` | Honoured as ovf `security_id` (must be unique) | One OCF security is one independent ovf position. |
| `stakeholder_id` | Honoured as `holder_id`; must exist | Holder. |
| `stock_class_id` | Honoured; must exist | Terms. |
| `quantity` | Honoured as `shares`; negative refused | Shares. |
| `share_price` | COMMON: honoured as `price`. PREFERRED: must equal class `price_per_share` | See §2. |
| `stock_plan_id` | Refused | Stock issued from a plan consumes pool capacity; netting is not implemented. |
| `date` | Checked against `as_of` | See Manifest. |
| `vesting_terms_id`, `vestings`, `issuance_type` | Ignored | Issued stock is treated as outstanding and entitled whether vested or not. |
| `cost_basis` | Ignored | ovf uses `share_price`. |
| `custom_id`, `share_numbers_issued`, `stock_legend_ids`, approval dates, `consideration_text`, `security_law_exemptions`, `comments` | Ignored | Not payout-relevant. |

### ConvertibleIssuance (`TX_CONVERTIBLE_ISSUANCE`)

| Field | Treatment | Why |
|---|---|---|
| `convertible_type` | `NOTE` honoured. `SAFE` and `CONVERTIBLE_SECURITY` refused | See [Not modelled](#not-modelled). |
| `security_id`, `stakeholder_id` | Honoured as `security_id`, `holder_id`; stakeholder must exist | Identity. |
| `investment_amount` | Honoured as `principal`; must be positive; its currency joins the one-currency check | Principal. |
| `date` | Honoured as `issue_date`; checked against `as_of` | Accrual start. |
| `seniority` | Honoured, **not** inverted; see §5 | Debt payout order. |
| `conversion_triggers` | Exactly one, `AUTOMATIC_ON_CONDITION`; every other type refused | See the triggers table. |
| `pro_rata` | Ignored; listed in `ignored_fields` | Pro-rata purchase rights do not change an exit payout. |
| `custom_id`, approval dates, `consideration_text`, `security_law_exemptions`, `comments` | Ignored | Not payout-relevant. |

| Trigger `type` | Treatment | Why |
|---|---|---|
| `AUTOMATIC_ON_CONDITION` | Honoured as the qualified financing. `trigger_condition` is returned in the trace, not parsed | Trust boundary; see the finding above. |
| `AUTOMATIC_ON_DATE` | Refused | Converts on a date. ovf's note is repaid at maturity; conversion at maturity is not implemented (docs/debt.md). |
| `ELECTIVE_AT_WILL`, `ELECTIVE_IN_RANGE`, `ELECTIVE_ON_CONDITION` | Refused | A holder option to convert. ovf does not model optional conversion. |
| `UNSPECIFIED` | Refused | OCF: the system of record "cannot represent this data in a structured form". |
| Two or more `AUTOMATIC_ON_CONDITION` | Refused | ovf would have to choose which one is the qualified financing. |
| `conversion_right.type` other than `CONVERTIBLE_CONVERSION_RIGHT` (or absent) | Refused | Not a convertible's right. |
| `conversion_right.converts_to_future_round`, `converts_to_stock_class_id` | Ignored | ovf's conversion returns a share count and price; the caller builds the resulting security. |

| `NoteConversionMechanism` field | Treatment | Why |
|---|---|---|
| mechanism `type` other than `CONVERTIBLE_NOTE_CONVERSION` | Refused | The only mechanism that carries interest terms. |
| `interest_rates` | Exactly one entry; see §7 | One rate from issue date. |
| `day_count_convention` | Consistency check only; see §6 | #423. |
| `interest_payout` | `DEFERRED` only | See §7. |
| `compounding_type`, `interest_accrual_period` | `SIMPLE` + `DAILY` only | See §7. |
| `conversion_valuation_cap` | Honoured as `valuation_cap`; must be positive | Cap price = cap / caller's `capitalization_shares`. |
| `conversion_discount` | Honoured as `discount_rate`; absent is 0; `1` and `""` refused | Discounted price. |
| `exit_multiple` | Refused | Basis unstated. |
| `conversion_mfn: true` | Refused | MFN terms not modelled. |
| `capitalization_definition`, `capitalization_definition_rules` | Ignored; listed in `ignored_fields` | ovf's `convert_at_financing` takes `capitalization_shares` from the caller and never infers it. |

| `OcfNoteTerms` (caller) | Becomes | Why it is not read from OCF |
|---|---|---|
| `maturity_date` | `maturity_date` | No OCF field. |
| `qualified_financing_threshold` | `qualified_financing_threshold` | Free text only. |
| `day_count` | `day_count` | `ACTUAL_365` is not defined (§6); checked against it. |

A `note_terms` entry for a security_id that is not a convertible issuance in the package
is refused (`ValueError`), as is a NOTE without one.

### Adjustments applied

| Transaction | Field honoured | Rule |
|---|---|---|
| `TX_STOCK_PLAN_POOL_ADJUSTMENT` | `shares_reserved` ("as of the effective date") | Absolute. The latest date wins. Same-date entries that disagree are refused, because OCF gives no order within a day. |
| `TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT` | `new_ratio_conversion_mechanism.ratio` | Same rule. A COMMON target is refused. |

## Transactions: all 43 v1.2.0 types

`APPLIED_TRANSACTIONS`, `IGNORED_TRANSACTIONS` and `REFUSED_TRANSACTIONS` in
`ovf/ocf/reader.py` partition the `TX_*` values of `enums/ObjectType`. A test asserts the
partition is exact.

| Class | Types | Reason |
|---|---|---|
| **Applied (4)** | `TX_STOCK_ISSUANCE`, `TX_STOCK_PLAN_POOL_ADJUSTMENT`, `TX_STOCK_CLASS_CONVERSION_RATIO_ADJUSTMENT` | See above. |
| | `TX_CONVERTIBLE_ISSUANCE` | `NOTE` only, with `note_terms`; see the finding and §5–§7. |
| Ignored (7) | `TX_STOCK_ACCEPTANCE`, `TX_CONVERTIBLE_ACCEPTANCE` | Holder acceptance; amount, terms and holder unchanged. |
| | `TX_ISSUER_AUTHORIZED_SHARES_ADJUSTMENT`, `TX_STOCK_CLASS_AUTHORIZED_SHARES_ADJUSTMENT` | Authorized, not issued, shares. |
| | `TX_VESTING_START`, `TX_VESTING_EVENT`, `TX_VESTING_ACCELERATION` | Vesting is not modelled; see Not modelled. |
| Refused (32) | `TX_STOCK_CANCELLATION`, `_REPURCHASE`, `_RETRACTION`, `_TRANSFER`, `_CONVERSION`, `_REISSUANCE` | Change outstanding shares or holders; not applied. |
| | `TX_STOCK_CLASS_SPLIT` | Changes share counts and, under NVCA, the Original Issue Price. |
| | `TX_STOCK_PLAN_RETURN_TO_POOL` | Plan securities not supported. |
| | `TX_EQUITY_COMPENSATION_*` (7), `TX_PLAN_SECURITY_*` (7) | Grants need strike, vesting and settlement terms (docs/limitations.md). |
| | `TX_WARRANT_*` (6) | No ovf warrant model; see [What a warrant model would have to carry](#what-a-warrant-model-would-have-to-carry). |
| | `TX_CONVERTIBLE_CANCELLATION`, `_RETRACTION`, `_TRANSFER`, `_CONVERSION` | Change a convertible's amount or holder, or retire it into other securities; not applied. |

A refused type fails the whole import: a partial cap table missing a cancellation or a
transfer would be silently wrong. Each refused type is under-claimed rather than guessed.
Applying cancellations, transfers and repurchases is the next step if the adapter is
extended.

## What the writer emits

`to_ocf(table, issuer=..., currency=..., as_of=...)` needs the issuer, the ISO 4217
currency and the as-of date because OCF requires them and ovf does not hold them.

- One COMMON class `ovf-common` (seniority `1`). Each ovf common position becomes one
  issuance at its own price.
- One PREFERRED class per distinct combination of price, seniority, multiple,
  participation, cap and ratio (`ovf-preferred-1`, `-2`, … in order of first appearance).
  Each position becomes one issuance.
- Each unallocated pool becomes one StockPlan with the pool's `security_id` as its id.
- Numbers are written as exact fixed-point text from the float's shortest round-trip
  representation. A value that needs more than OCF's 10 decimal places is refused rather
  than rounded. This affects, for example, non-terminating prices produced by
  `SafeConversionResult.to_cap_table()`, which does not round to issuable prices.
- The ratio is written as the integer fraction of the float's shortest decimal
  representation, so `1/3` round-trips.
- **Placeholders**, each stated in a `comments` entry on the object that carries it:
  `votes_per_share` `"1"`; `initial_shares_authorized` = shares issued in the class;
  stakeholder `name` = holder id and `stakeholder_type` `INSTITUTION` (unless
  `stakeholders=` supplies records); issuance `date` = `as_of`, `custom_id` = security
  id; `rounding_type` `NORMAL`; `conversion_price` = price ÷ ratio rounded to 10 decimals.
  A common `share_price` of 0 is labelled as ovf's "cost basis unknown", not a recorded
  price.
- **Convertible notes.** One `TX_CONVERTIBLE_ISSUANCE` per `ConvertibleNote`. It has
  `convertible_type: NOTE`, `date` equal to the issue date, and seniority equal to the dense
  debt rank (not inverted, §5). It has one `AUTOMATIC_ON_CONDITION` trigger whose
  `trigger_condition` states the threshold in words. The mechanism is
  `CONVERTIBLE_NOTE_CONVERSION` with one rate from the issue date, `ACTUAL_365`,
  `DEFERRED`, `DAILY` and `SIMPLE`, the cap and discount when present, and
  `converts_to_future_round: true`. The maturity date, the threshold and the day count are
  written into `comments`, which is the only place OCF allows. `note_terms_from(table)`
  returns them for the read back. Note holders become stakeholders.
- Refused: participating-uncapped preferred; **term debt and venture debt** (OCF v1.2.0
  has no non-convertible debt object; finding 11); notes that are compound or PIK, use
  Actual/360, have a stated `exit_treatment`, or are issued after `as_of`; SAFEs and any
  other instrument; pools with allocated options; OCF object id collisions.
- `write_ocf_package` writes into a new or empty directory only, with real MD5s. It
  refuses a package that was loaded with unread files, because writing it would drop them.

## Round trip

**Definition.** `from_ocf(to_ocf(t))` reproduces, exactly as floats, every field of every
security in `t`: kind, `security_id`, `holder_id`, `shares`, `price`,
`liquidation_multiple`, `participating`, `participation_cap`, `conversion_ratio`, and the
pool's reserved and allocated shares. Two exceptions, both things OCF does not carry:

1. Preferred seniority is reproduced as its **dense rank**. OCF keeps the order and
   equalities, and the waterfall uses nothing else (`ovf/waterfall.py` sorts the distinct
   levels).
2. A pool's `holder_id` becomes the plan id, because an OCF stock plan has no holder.

Security order in the list may change (plans are read last). Payouts do not depend on
list order.

**Convertible notes** round-trip only with their terms resupplied:
`from_ocf(to_ocf(t), note_terms=note_terms_from(t))` reproduces every `ConvertibleNote`
field exactly. Debt seniority, like preferred seniority, comes back as its dense rank.
Without `note_terms` the read is refused; that refusal is the finding above, asserted by
`test_a_note_does_not_round_trip_through_ocf_without_its_terms`. The Hypothesis property
test draws zero to two simple Actual/365 Fixed notes per table (rates 0–20% in basis
points, optional caps, discounts 0–25%, seniorities 0–3) alongside the equity.
`test_notes_round_trip_through_disk` does the same through files.

**Evidence.** `test_round_trip_over_waterfall_fixtures` covers every writable F-fixture
under both cap bases, and asserts the hand-derived payouts of docs/fixtures.md after the
round trip. `test_round_trip_through_disk` goes OCF → ovf → OCF files → ovf for both
hand-built packages. `test_round_trip_property` (Hypothesis, 150 generated tables per
run) covers zero to four preferred positions with random prices in cents, seniorities 0–5,
multiples 0.5–3x, caps, ratios including 1/3, and optional pools. Tables containing
participating-uncapped preferred are excluded, because they cannot be written.

## Findings about OCF itself

1. **OCF's own sample package cannot be read under a strict reading, even with the
   opt-in flag.** In order: (a) its manifest MD5s are placeholders (its own `comments` say
   so), so `verify_md5=False` is needed. (b) Its Common Stock class sets
   `liquidation_preference_multiple: "1"` and `participation_cap_multiple: "1"`, which
   needs `ignore_common_preference_fields=True`. (c) Its Series Seed Preferred class has
   no `price_per_share`, so the preference basis is missing and the class is refused.
   (d) With a price supplied, its transactions still include option grants, warrants,
   convertibles, stock cancellations, transfers and more, all refused.
   `test_official_sample_is_refused_by_a_strict_reading_in_this_order` pins that sequence.
2. **The sample transactions file fails its own file schema.** At v1.2.0, and still at
   `main` `0951820`, `files/TransactionsFile.schema.json` does not list
   `IssuerAuthorizedSharesAdjustment` in its `oneOf`. The object schema exists and
   `ObjectType` lists `TX_ISSUER_AUTHORIZED_SHARES_ADJUSTMENT`. The sample's two
   such items therefore fail validation. `ovf.ocf` classifies transactions by
   `object_type` and ignores this type, so it is more permissive here than the file schema.
3. **Two seniority fields run in opposite directions.** `StockClass.seniority`: higher
   number, higher priority (§1). `ConvertibleIssuance.seniority` at the same tag,
   verbatim: "use this value to build a seniority stack, with 1 being highest seniority".
   ovf now reads both, with separate comparators (§5). Case O7 fails if they are unified.
4. **No participating flag, and no cap basis.** See §3 and the finding above.
5. **`liquidation_preference_multiple` is described as a per-share amount** ("The
   liquidation preference per share") but named as a multiple.
6. **No dividend fields on StockClass.** Accrued and cumulative dividends change payouts
   (docs/limitations.md) and cannot arrive through OCF v1.2.0 at all.
7. **A convertible has no maturity date.** See the round-trip finding. The only dated
   trigger converts rather than repays.
8. **`ACTUAL_365` is undefined, by the format's own account.** Issue #423 has been open
   since 2023-05-10 (§6).
9. **No compounding frequency.** There is a type and an accrual period; #423's example
   shows they differ (§7).
10. **The `Percentage` pattern admits the empty string.** `types/Percentage`:
    `^0?(\.[0-9]{1,10})?$|^1(\.0{1,10})?$`. Every part of the first alternative is
    optional, so `"rate": ""` validates. `test_ocf_percentage_pattern_admits_the_empty_string`
    pins the pattern, and the optional schema test checks that ovf restates it exactly.
    The reader refuses an empty rate or discount.
11. **No object for non-convertible debt.** A term loan or a venture debt facility ranks
    ahead of all equity at exit (docs/debt.md), yet OCF v1.2.0 has nowhere to record one.
    Its only debt-like issuance is `TX_CONVERTIBLE_ISSUANCE`. A cap table exchanged as OCF
    silently loses every non-convertible creditor, so `to_ocf` refuses `DebtInstrument` and
    `VentureDebt` rather than dropping them.
12. **`exit_multiple` does not state its basis.** "For cash proceeds calculation during a
    liquidity event." It could be a multiple of principal, of principal plus interest, or a
    replacement for interest. docs/debt.md shows the public note forms use
    `m × principal + interest`, but OCF does not say which it means.
13. **The official sample's warrants and convertibles are internally inconsistent.**
    `test-warrant-issuance-minimal` is "exercisable for" `quantity` 1,000 shares while its
    `FIXED_AMOUNT_CONVERSION` converts into 10,000.00.
    `test-pps-based-warrant-issuance-full-fields` states neither a quantity nor an exercise
    price. `test-convertible-issuance-all-fields` is a `SAFE` carrying note interest terms,
    with a GBP investment and a `consideration_text` of "3.50 USD". Its conversion trigger
    is dated 2022-01-01, while its issuance date is 1978-05-27.

## Derivations

Cap tables are the two packages in `tests/ocf_fixtures/`. Every number below was computed
by hand from the package contents; the tests assert them against the engine.

**Two-series package.** Founders hold 8,000,000 common. Series A holds 2,000,000 at $2.50
with a 1x preference of $5,000,000 and OCF seniority 2. Series B holds 1,500,000 at $6.00
with a 1x preference of $9,000,000 and OCF seniority 3. Neither participates. Both convert
1:1.

**O1: seniority direction, exit $10M.** OCF repays the higher seniority first, so Series B
(3) is senior to Series A (2). B takes its full $9M, and A receives the $1M remainder.
Common receives nothing. Conversion checks: if A converts, B still takes $9M and the $1M
residual is shared by 8,000,000 common and 2,000,000 converted A shares, so A gets
2/10 × $1M = $0.2M < $1M. If B converts, A takes $5M and the $5M residual is shared by
8,000,000 and 1,500,000 shares, so B gets 1.5/9.5 × $5M ≈ $0.79M < $9M. Neither converts.
→ **Series B $9,000,000, Series A $1,000,000, common $0.** Under the opposite reading A
would be senior: A takes $5M and B the remaining $5M (conversion would pay A $0.2M and B
≈ $0.79M, both worse). → A $5,000,000, B $5,000,000. The two readings disagree by $4M on
each series.

**O2: exit $20M.** Both preferences are paid in full ($14M), and the $6M residual goes to
common. Converting would pay A 2/10 × $11M = $2.2M or B 1.5/9.5 × $15M ≈ $2.37M, both
below their preferences. → **common $6,000,000, A $5,000,000, B $9,000,000.**

**O3: equal seniority, exit $10M.** With both classes at OCF seniority 3, they share one
tier. Claims of $5M and $9M against $10M split 5:9: **A $3,571,428.57, B
$6,428,571.43**, common $0. Converting alone would pay A $0.2M or B ≈ $0.79M, as in O1.

**Participating package.** Founders hold 8,000,000 common. Series A holds 2,000,000 at
$2.50, with `liquidation_preference_multiple` 1, so the preference is $5,000,000, and
`participation_cap_multiple` 2. A conversion-ratio adjustment dated 2023-03-01 sets the
ratio to 5/4 = 1.25 (conversion price $2.00 = $2.50 / 1.25). Plan `plan-2020` starts at
500,000 reserved shares, is adjusted to 800,000 on 2021-01-01 and to 1,000,000 on
2022-06-30, and so has 1,000,000. A stock acceptance and a class authorized-shares
adjustment are ignored.

**O4: ownership.** As converted, Series A holds 2,000,000 × 1.25 = 2,500,000 shares.
Fully diluted is 8,000,000 + 2,500,000 + 1,000,000 = 11,500,000. → **founders 8/11.5 =
69.57%, Series A 2.5/11.5 = 21.74%, pool 1/11.5 = 8.70%.**

**O5: total cap.** The cap is 2 × $5M = $10M in total. The residual is shared over
8,000,000 + 2,500,000 = 10,500,000 units, because the pool is unallocated and takes
nothing.
- Exit $40M: without conversion, $5M preference plus 2.5/10.5 × $35M ≈ $8.33M would be
  $13.33M. The cap stops A at $10M, and common takes the other $30M. Converting would pay
  2.5/10.5 × $40M ≈ $9.52M < $10M. → **Series A $10,000,000, common $30,000,000, pool
  $0.**
- Exit $63M: capped participation pays $10M. Converting pays 2.5/10.5 × $63M = $15M, so A
  converts, and common takes 8/10.5 × $63M = $48M. → **Series A $15,000,000, common
  $48,000,000.** With the unadjusted 1:1 ratio, conversion would pay 2/10 × $63M =
  $12.6M, so this exit also checks that the ratio adjustment was applied.

**O6: participation-only basis, exit $40M.** Read as a 2x cap on participation alone,
the total cap is (1 + 2) × $5M = $15M. The uncapped amount of $5M + $35M × 2.5/10.5 =
$40M/3 ≈ $13.33M is below it, so the cap does not bind. Conversion (≈ $9.52M) is worse.
→ **Series A $13,333,333.33 ($40M/3), common $26,666,666.67 ($80M/3).** The same file
pays Series A $10M under the default basis (O5): the choice of basis moves $3.33M.

**Notes package** (`tests/ocf_fixtures/two_series_with_notes/`). The stock classes and
stock plans are byte-for-byte the two-series package's, and so are the three stock
issuances. Two convertible notes and a convertible acceptance are added. The two-series
package itself is unchanged, because adding notes to it would move O1–O3: notes are paid
ahead of all equity.

- **CN-1**, held by `angel`: $500,000, issued 2026-01-01, 6% simple, `ACTUAL_365`, daily,
  deferred, $8,000,000 cap, 20% discount, **convertible seniority 2**.
- **CN-2**, held by `bridge-fund`: $1,000,000, issued 2025-01-01, 8% simple, no cap, no
  discount, **convertible seniority 1**.
- Supplied `note_terms`: both mature 2028-01-01 and use Actual/365 Fixed. CN-1's
  qualified-financing threshold is $1,000,000 and CN-2's is $2,000,000. Those are the
  amounts each `trigger_condition` states in words.
- All accruals run to **2027-01-01**. That is 365 days after CN-1's issue and 730 after
  CN-2's (365 + 365, because neither 2025 nor 2026 is a leap year). Notes are resolved
  `repay` for the exit cases, because OCF states no exit treatment.

**O10: accrual.** CN-1: 500,000 × 0.06 × 365/365 = **$30,000**, so the claim is
**$530,000**. At maturity (730 days) the interest is $60,000 and **$560,000** falls due.
CN-2: 1,000,000 × 0.08 × 730/365 = **$160,000**, so the claim is **$1,160,000**. These are
the debt fixtures' note and A1 amounts, now read from OCF.

**O7: convertible seniority direction, exit $1,500,000.** OCF convertible seniority 1 is
highest, so CN-2 is senior. CN-2 takes its full **$1,160,000**. CN-1 receives the
**$340,000** left and is $190,000 short. Equity receives **$0**; both series are
indifferent at zero and keep "not converted". Under the StockClass reading (higher number
first), CN-1 would be senior: it would take its $530,000 in full, and CN-2 the $970,000 left.
The two readings disagree by $190,000 on each note.

**O8: notes and preferred together, exit $11,690,000.** Debt claims total 1,160,000 +
530,000 = $1,690,000 and are paid in full. That leaves exactly $10,000,000, which is O1:
Series B (class 3) is senior and takes **$9,000,000**, Series A gets **$1,000,000**, and
common gets **$0**. The O1 conversion checks apply unchanged, because the equity game
sees the same $10M. Each scale is read in its own direction in the same package.

**O9: equal convertible seniority, exit $845,000.** With both notes at convertible
seniority 1 they share one tier. Claims of $1,160,000 and $530,000 total $1,690,000, and
$845,000 is exactly half of it. So CN-2 receives **$580,000** and CN-1 **$265,000**
(OCF: "equal seniority values assumed to be equal priority").

**O11: conversion of notes read from OCF, financing on 2027-01-01.** CN-1 converts
$530,000 (O10). With $3,000,000 of new money, above its $1,000,000 threshold, and the caller's
capitalization of 8,000,000 shares, the cap price is 8,000,000 / 8,000,000 = $1.00.
- Round price $1.50: discount price 1.50 × 0.8 = $1.20. The cap binds at $1.00, giving
  **530,000 shares** (debt fixture C1).
- Round price $1.10: discount price 1.10 × 0.8 = $0.88, below $1.00. The discount binds,
  giving 530,000 / 0.88 = **602,272.73 shares** (C2).
- CN-2 has a $2,000,000 threshold, so $1,500,000 of new money does **not** qualify. With
  $2,000,000 at $1.60 and neither cap nor discount, CN-2 converts its $1,160,000 at the round
  price into 1,160,000 / 1.60 = **725,000 shares**. This checks that the threshold came
  from the supplement and not from CN-1.

## What a warrant model would have to carry

ovf has no warrant model, and none is invented here. Every `TX_WARRANT_*` transaction is
refused. Before that refusal could be lifted, a warrant model would need each item below.
Each changes an exit payout. The right-hand column is what OCF v1.2.0 supplies.

| A warrant model needs | Why it changes a number | OCF v1.2.0 `WarrantIssuance` |
|---|---|---|
| The number of shares | Sets the warrant's share of the residual | `quantity` is **optional**, and `quantity_source` may be `HUMAN_ESTIMATED` or `UNSPECIFIED`. The conversion mechanism may state a different count (sample: 1,000 vs 10,000.00) |
| The exercise price | The holder takes value net of the strike, and a cash exercise adds the strike to proceeds | `exercise_price` is **optional**. Only `exercise_triggers` and `purchase_price` are required beyond the common issuance fields |
| The underlying security | A warrant on preferred carries a preference; one on common does not | `converts_to_stock_class_id`, or `converts_to_future_round`. A future-round warrant cannot be valued until the round exists |
| Settlement at a liquidity event: cash exercise, net (cashless) exercise, cash-out of the spread, assumption, or termination if unexercised | Each gives different share counts and cash | **No field** |
| An exercise decision inside the conversion game | An in-the-money warrant is another player whose choice changes every other payout. The payoff-uniqueness evidence in docs/findings.md does not cover it | Not a data question; ovf would need a new game |
| Whether it is still exercisable on the exit date | An expired warrant takes nothing | `warrant_expiration_date` is optional, with the `$comment` "This may not be necessary as it can be expressed with the exercise_triggers" |
| Vesting | Unvested warrants may be forfeited | `vesting_terms_id` and `vestings`, which ovf does not read (see Vesting below) |
| Price and quantity adjustments (anti-dilution, splits) | They change the strike and the count | **No field** on `WarrantIssuance` |

A reader could lift the refusal only for a narrow subset. It would need an
instrument-fixed quantity (`quantity_source: INSTRUMENT_FIXED`) consistent with a
`FIXED_AMOUNT_CONVERSION`, a stated `exercise_price`, an existing target class, and an
exercise window covering the exit date. It would also need a settlement method that the
caller states, with no default, because OCF does not record one. The exercise decision
would have to join the conversion search, and the findings evidence would have to be
re-run.

## Not modelled

Each item changes a real number, or would if it were present in a package.

- **Vesting** (`VestingTerms`, issuance `vestings`, vesting transactions): unvested stock
  may be forfeited or repurchased at exit, and acceleration changes who holds entitled
  shares. ovf treats all issued stock as outstanding and entitled.
- **Option grants, RSUs and other plan awards, with their exercise and settlement:**
  in-the-money options take proceeds net of strike. Refused rather than read as
  allocated capacity with no strike.
- **Stock issued from a plan** (`stock_plan_id`): the pool reserve must be netted, or
  fully diluted ownership double-counts. Refused.
- **Warrants:** they take proceeds or exercise into shares. Refused; see
  [What a warrant model would have to carry](#what-a-warrant-model-would-have-to-carry).
- **SAFEs** (`convertible_type: SAFE`): they convert or cash out at a liquidity event,
  changing every payout. Refused. ovf's exit engine rejects an unconverted SAFE. OCF's
  `conversion_valuation_cap` is optional where ovf's SAFE requires one. OCF's
  `capitalization_definition_rules` may contradict the capitalization that ovf's SAFE
  solver fixes (docs/semantics.md). The YC liquidity-event cash-out is not implemented.
- **`CONVERTIBLE_SECURITY`:** OCF defines no economics for it. Refused.
- **Notes outside the read subset:** compound interest (no frequency in OCF), non-daily
  simple accrual, rate schedules, an accrual start other than the issue date, an accrual
  end date, cash-paid interest, `30_360`, conversion on a date, holder-elective
  conversion, unspecified triggers, more than one qualified-financing trigger,
  `exit_multiple`, MFN, non-note mechanisms on a NOTE. Each is refused with its field
  named, and each would change the note's claim or its conversion shares.
- **A note's exit treatment:** OCF records none. Notes are read unresolved, and the caller
  states repayment or a multiple.
- **The qualified-financing condition text:** not parsed; the caller's threshold is
  trusted (see the finding).
- **Capitalization definition for note conversion:** OCF's `capitalization_definition`
  and `_rules` are not read. The caller supplies `capitalization_shares`, and a different
  count changes the conversion shares.
- **Pro-rata rights** (`pro_rata`): not modelled. They matter for the next round, not for
  an exit.
- **Convertible cancellations, retractions, transfers and conversions:** refused. They
  change which notes are outstanding.
- **Term debt and venture debt on write:** OCF v1.2.0 has no object for them (finding 11).
- **Cancellations, repurchases, retractions, transfers, stock conversions, reissuances:**
  they change outstanding shares or holders. Refused.
- **Splits:** change share counts and the Original Issue Price. Refused.
- **Valuations:** no effect on an ovf waterfall; they would matter for option strikes,
  which are refused.
- **Financings, documents, stock legends:** no effect on an ovf payout. Not opened.
- **Authorized-share limits:** not enforced, so an over-issued class is not detected.
- **Voting and par value:** class votes drive drag-along and vetoes (not modelled), and par
  value affects legal surplus under Delaware law, not the distribution.
- **`rounding_type`:** ovf converts to fractional shares. Rounding per holder would move
  at most one share each.
- **`conversion_price`:** ignored in favour of the ratio. A package whose conversion price
  disagrees with price ÷ ratio is not detected.
- **`cost_basis`:** unused. A common holder's `effective_multiple` uses `share_price`.
- **Unequal economics between COMMON classes:** OCF v1.2.0 has no field for them. All
  common is treated as one residual.
- **Dividends:** OCF v1.2.0 StockClass has no dividend fields (finding 6).
- **Holder-level coordination:** each OCF security is an independent ovf position
  (`WaterfallResult.multi_position_holders` discloses shared holders).
- **Several currencies:** refused. ovf has one base currency and no FX.
- **ZIP containers:** not read.
- **OCF versions other than 1.2.0:** refused.

## Public API

| Name | Purpose |
|---|---|
| `from_ocf(source, *, participation_cap_basis="total", ignore_common_preference_fields=False, verify_md5=True, note_terms=None)` | Package directory, manifest path or `OcfPackage` → `CapTable`. `note_terms` maps each note's security_id to its `OcfNoteTerms`; a NOTE without one is refused. |
| `import_ocf(...)` | Same, returning `OcfImport`: the table plus preferred and debt seniority ranks, the qualified-financing condition texts, applied and ignored transactions, ignored fields, unread files, currency and assumptions. |
| `OcfNoteTerms(maturity_date, qualified_financing_threshold, day_count)` | The three note terms OCF v1.2.0 does not carry. No defaults. |
| `note_terms_from(table)` | The `OcfNoteTerms` of every `ConvertibleNote` in a table, to keep beside an exported package and pass back on read. |
| `load_ocf_package(path, *, verify_md5=True)` | Files → validated in-memory `OcfPackage`. |
| `to_ocf(table, *, issuer, currency, as_of, generated_at=None, stakeholders=None, participation_cap_basis="total")` | `CapTable` → `OcfPackage`. |
| `write_ocf_package(package, directory)` | `OcfPackage` → files plus manifest with MD5s. |
| `OcfSchemaError`, `OcfUnsupportedError`, `OcfIntegrityError` | All subclass `OcfError`, a `ValueError`. |
