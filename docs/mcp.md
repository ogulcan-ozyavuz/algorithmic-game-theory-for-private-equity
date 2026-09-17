# ovf-mcp: the Model Context Protocol server

Status 2026-09-15, server `0.1.0a0` over library `0.1.0-alpha`, package `ovf_mcp`, console
script `ovf-mcp`, MCP server name `equilibria`. Developed against the MCP Python SDK 2.2.0.

`ovf-mcp` exposes the calculations documented in [semantics](semantics.md) to MCP clients
such as Claude Code, Claude Desktop and Cursor. Each tool builds library objects from typed
arguments, calls one public `ovf` function, and returns the engine's own record together
with an adapter `provenance` block and, for the allocation tools, an adapter `verification`
block. The server adds no modelling of its own.

## What it is and what it is not

It is:

- a local, single-user adapter. By default it speaks MCP over stdio to one client that
  launched it as a subprocess;
- a typed interface to the exit waterfall, the conversion-equilibrium survey, the SAFE
  priced round, debt accrual and note conversion, anti-dilution, dilutive issuances and
  the OCF v1.2.0 reader and writer;
- a server that refuses input the library refuses, with a structured error the calling
  model can act on, instead of returning an approximate number.

It is not:

- a new model. Every limitation in [limitations](limitations.md) applies unchanged, and the
  adapter closes none of them;
- a hosted service. It has no authentication and is not published on PyPI or Smithery;
- a check that the terms a model passed in are the terms in a charter. It validates their
  shape, and the library refuses terms outside its scope. Whether a Series A is really
  capped at 2x is something only the documents can settle;
- a 409A valuation, a fair-value opinion, or financial, legal or tax advice.

## Install

From a checkout, with Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[mcp]'
```

This installs the `ovf-mcp` console script. `python -m ovf_mcp` starts the same server.
Started by hand, the server writes nothing and waits for MCP messages on stdin. That is
expected: it is meant to be started by a client. Stop it with Ctrl-C.

```bash
ovf-mcp                     # stdio (default)
python -m ovf_mcp           # the same
ovf-mcp --version           # ovf-mcp 0.1.0a0
ovf-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

The second transport serves MCP over Streamable HTTP at `http://127.0.0.1:8765/mcp`. The
host and port shown are the defaults, and `/mcp` is the SDK's default endpoint path. Read
[Security](#security) before using it. The only transports are `stdio` and
`streamable-http`.

**Not yet published.** Once `ovf` is on PyPI, the intended no-checkout form is
`uvx --from 'ovf[mcp]' ovf-mcp`. It does not work today.

## Client setup

Every client below starts the server as a subprocess. Clients do not activate a virtual
environment, so give them the **absolute** path of the script inside `.venv`
(`.venv/bin/ovf-mcp`, or `.venv\Scripts\ovf-mcp.exe` on Windows). A bare `ovf-mcp` works
only if that script is on the client's `PATH`. Ready-made files are in
[`examples/mcp/`](../examples/mcp/README.md).

### Claude Code

```bash
claude mcp add equilibria -- /ABSOLUTE/PATH/TO/personal/.venv/bin/ovf-mcp

# The same, with the OCF tools confined to one directory:
claude mcp add equilibria -e OVF_MCP_ALLOWED_ROOTS=/ABSOLUTE/PATH/TO/cap-tables \
    -- /ABSOLUTE/PATH/TO/personal/.venv/bin/ovf-mcp
```

The default scope is `local`: this project, this user. `--scope user` registers the server
for every project. `claude mcp list` shows whether it connects, and so does `/mcp` inside
a session.

The repository also carries a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "equilibria": {
      "type": "stdio",
      "command": ".venv/bin/python",
      "args": ["-m", "ovf_mcp"],
      "env": {}
    }
  }
}
```

It uses a relative interpreter path and `python -m ovf_mcp`, so it works in any checkout
whose `.venv` has the package installed, provided Claude Code runs from the repository
root. Claude Code asks for approval before it starts a project-scoped server for the
first time.

### Claude Desktop

Add the `equilibria` entry from
[`examples/mcp/claude_desktop_config.json`](../examples/mcp/claude_desktop_config.json) to
`claude_desktop_config.json`. On macOS that is
`~/Library/Application Support/Claude/claude_desktop_config.json`, and on Windows
`%APPDATA%\Claude\claude_desktop_config.json`. Replace both placeholders, then restart the
app.

```json
{
  "mcpServers": {
    "equilibria": {
      "command": "/ABSOLUTE/PATH/TO/personal/.venv/bin/ovf-mcp",
      "args": [],
      "env": {
        "OVF_MCP_ALLOWED_ROOTS": "/ABSOLUTE/PATH/TO/cap-tables"
      }
    }
  }
}
```

Until the placeholder root is replaced with a real directory, `ocf_import` and `ocf_export`
refuse every path. Delete the `env` entry to lift the restriction.

### Cursor

Put the same `mcpServers` object in `.cursor/mcp.json` in a project, or in
`~/.cursor/mcp.json` for every project. See
[`examples/mcp/cursor_mcp.json`](../examples/mcp/cursor_mcp.json).

### Smithery and other clients

[`smithery.yaml`](../smithery.yaml) declares a stdio `startCommand` whose `commandFunction`
returns `{command: 'ovf-mcp', args: [], env: {}}`. Its one optional setting, `allowedRoots`,
becomes `OVF_MCP_ALLOWED_ROOTS`. The file assumes `ovf-mcp` is already on `PATH`. The
repository has no Dockerfile, and the server is not listed on Smithery.

Any other stdio MCP client needs only the command, with no arguments. A client that speaks
Streamable HTTP can connect to the URL above, for example
`claude mcp add --transport http equilibria http://127.0.0.1:8765/mcp` against a server
that is already running.

## Tools

"Read-only" is the tool's `readOnlyHint` annotation. Every tool also declares
`destructiveHint: false` and `openWorldHint: false`. Annotations are hints to the client,
not enforcement. An argument with no default in the table is required.

| Tool | Purpose | Arguments (default) | Read-only |
|---|---|---|---|
| `exit_waterfall` | Allocate one exit, solve the conversion game and verify the allocation | `securities`, `exit_valuation`; `transaction_costs` (0), `as_of` (null), `max_iterations` (20, range 1–1000) | yes |
| `exit_sweep` | Allocate an evenly spaced range of exits; bracket conversion switches between samples | `securities`, `exit_to`; `exit_from` (0), `steps` (21, range 2–401), `transaction_costs` (0), `as_of` (null) | yes |
| `conversion_equilibria` | Evaluate all `2**n` conversion profiles at one exit, and report every pure equilibrium, payout uniqueness and the profile `exit_waterfall` selects | `securities`, `exit_valuation`; `transaction_costs` (0), `as_of` (null), `max_positions` (12, range 1–14) | yes |
| `cap_table_summary` | Validate a table without an exit: fully diluted ownership, preference stack by seniority, debt ranks, multi-position holders, normalized securities | `securities` | yes |
| `safe_priced_round` | Solve a priced round with converting SAFEs from a common-only start; return the post-round table | `prior_common_shares`, `new_money`, `pre_money_valuation`, `target_pool_pct` (**required**, 0 ≤ t < 1), `method` (**required**: `post_money_yc` or `pre_money`); `safes` (none) | yes |
| `anti_dilution_adjustment` | One conversion-price adjustment (NVCA Model COI 4.4.4) | `method` (`weighted_average` or `full_ratchet`), `conversion_price`, `shares_issued`, `aggregate_consideration`; `capitalization`, `definition`, `original_issue_price` (all null) | yes |
| `dilutive_issuance` | Apply one issuance to a table and each preferred position's protection | `securities`, `new_securities`, `aggregate_consideration`, `protection`, `exemption` | yes |
| `debt_claim` | Accrue one debt instrument and state its exit claim | `instrument`, `as_of` | yes |
| `convert_note` | Convert a convertible note in a qualified financing | `note`, `financing_date`, `new_money`, `round_price`; `capitalization_shares` (null) | yes |
| `ocf_import` | Read an OCF v1.2.0 package into `securities` with its import trace | `path`, `participation_cap_basis` (**required**: `total` or `participation_only`); `ignore_common_preference_fields` (false), `verify_md5` (true), `note_terms` (null) | yes (reads files) |
| `ocf_export` | Express a table as an OCF v1.2.0 package; optionally write it to disk | `securities`, `issuer`, `currency`, `as_of`, `participation_cap_basis` (**required**); `directory` (null) | **no** |
| `example_cap_tables` | The CLI demo tables F1, F2, F3, F5a, F5b and F8a, and `readme_60m`, each with a suggested exit | none | yes |

Notes on individual tools:

- **`as_of`** is required whenever the table holds debt or an accruing cumulative dividend,
  even at a zero exit. It is never defaulted to today.
- **`exit_waterfall`** returns **one** verified equilibrium. Where several profiles exist it
  does not say so; `conversion_equilibria` does. Its result adds a `summary` with `net_exit`,
  `by_holder`, `converted` and `debt_paid` to the engine's `WaterfallResult`.
- **`exit_sweep`** solves each sampled exit independently. `conversion_switches` places each
  change of election only between two neighbouring samples, and the grid can step over a
  breakpoint. `common_receives_nothing_up_to` is the largest sampled exit at which common
  is paid nothing, or null. It is a sample, not a solved threshold.
- **`conversion_equilibria`** is exponential in the number of preferred positions. The
  server refuses more than 14 positions (16,384 profiles).
- **`safe_priced_round`** has no default for `target_pool_pct`, unlike the CLI's `--pool`, so
  the pool is always a stated term. Nor does `method`: post- and pre-money SAFEs use
  different cap denominators and convert to different share counts. All SAFEs take the one
  form `method` names. Each entry
  in `safes` is `{amount, cap, discount_rate (0), holder_id (required), security_id}`.
  `post_round_securities` can be passed unchanged to `exit_waterfall`.
- **`anti_dilution_adjustment`**: `weighted_average` requires both `capitalization` (five
  share counts, each required) and `definition`. Without either it returns
  `missing_charter_terms`, because broad- and narrow-based differ only in `A`. `definition`
  is `broad_based_nvca`, `broad_based_with_reserved_pool`, `narrow_based_outstanding_stock`,
  or a custom object `{name, source, include_common, include_preferred_as_converted,
  include_options_and_warrants, include_other_convertibles, include_reserved_pool}`.
  `full_ratchet` with either argument returns `unused_terms`. `original_issue_price` adds
  `conversion_ratio_before` and `conversion_ratio_after`. CP2 is unrounded. See
  [anti-dilution](antidilution.md).
- **`dilutive_issuance`**: `protection` maps **every** preferred `security_id` in
  `securities` to `{method: weighted_average | full_ratchet | none, definition}`. `exemption`
  is `{exempted, basis}`, both required. `aggregate_consideration` is never inferred from
  the new securities' prices. The result carries each position's before-and-after price,
  ratio and as-converted shares, and `securities_after`. See [financing](financing.md).
- **`convert_note`**: principal plus interest accrued to `financing_date` converts at
  `min(valuation_cap / capitalization_shares, round_price × (1 − discount_rate))`.
  `capitalization_shares` is required when the note has a cap, and is never inferred. A
  financing below the qualified threshold is refused. See [debt](debt.md).
- **`ocf_import`**: `path` is a package directory or its manifest file. `note_terms` maps each
  convertible note's `security_id` to `{maturity_date, qualified_financing_threshold,
  day_count}`, which OCF v1.2.0 does not carry. See [ocf](ocf.md).
- **`ocf_export`**: `issuer` is `{id, legal_name, formation_date, country_of_formation}`, and
  `currency` is an ISO 4217 code. With `directory` null it returns the package as JSON and
  writes nothing. With a `directory`, it writes files into a new or empty directory and
  never overwrites. Terms OCF v1.2.0 cannot express are refused, not written lossily.

### The `securities` argument

A list of objects, each discriminated by `type`. The field names are the same as the `ovf`
factories and the CLI's `--file` JSON, so a table written for
`python -m ovf waterfall --file` is a valid argument. Unknown keys and non-finite numbers
are rejected. The full JSON Schema is the resource `ovf://schema/securities`.

| `type` | Fields (default) |
|---|---|
| `common` | `shares`; `holder_id` (`founders`), `security_id`, `price` (0, meaning cost basis unknown) |
| `preferred` | `shares`, `price`; `seniority` (1), `liquidation_multiple` (1.0), `participating` (false), `participation_cap` (null), `conversion_ratio` (1.0), `holder_id` (`investor`), `security_id`, `dividend` (null) |
| `pool` or `option_pool` | `reserved_shares`; `allocated_shares` (0), `holder_id` (`esop`), `security_id` |
| `safe_post` or `safe_pre` | `amount`, `cap`; `discount_rate` (0), `holder_id` (`safe_investor`), `security_id` |
| `debt` | `principal`, `annual_rate`, `accrual` (`simple`, `compound` or `pik`), `day_count` (`actual/365_fixed` or `actual/360`), `issue_date`, `seniority`; `compounding_frequency` (null), `maturity_date` (null), `holder_id` (`lender`), `security_id` |
| `venture_debt` | as `debt`, plus `exit_fee`; `holder_id` (`venture_lender`) |
| `convertible_note` | as `debt`, plus `maturity_date` (required), `qualified_financing_threshold`; `valuation_cap` (null), `discount_rate` (0), `exit_treatment` (`repay`, `multiple` or null), `exit_principal_multiple` (null), `holder_id` (`noteholder`) |

`dividend` is `{kind: "cumulative", annual_rate, accrual, compounding_frequency, day_count,
accrues_from, settlement, participation_cap_basis}` or
`{kind: "non_cumulative", annual_rate}`. `settlement` is `forfeit_on_conversion` or
`paid_in_kind`; see [dividends](dividends.md).

**Omitted terms are reported, not hidden.** An omitted `seniority`, `liquidation_multiple`,
`participating`, `participation_cap` (when participating), `conversion_ratio` or `dividend`
takes the factory default above. So do a pool's `allocated_shares`, a SAFE's
`discount_rate`, a debt or venture debt's `maturity_date`, and a note's `valuation_cap` and
`discount_rate`. Every tool that takes positions returns `defaults_applied`, mapping each
`security_id` to its omitted terms and the values used, and adds a sentence to
`adapter_notes` (to `notes` in `cap_table_summary`) whenever one applies. The server's
instructions tell the calling model to ask the user rather than assume. `normalized_securities`
from `cap_table_summary` shows every term as modelled. Unconverted SAFEs are
accepted by `cap_table_summary` and refused by every exit tool.

Every result that contains a cap table (`post_round_securities`, `securities_after`,
`normalized_securities`, the `securities` from `ocf_import` and `example_cap_tables`)
returns it in this same form, ready for the next tool.

## What every result carries

**The engine's own record.** Whatever the library returns, serialized unchanged: for
example `payouts`, `assumptions`, `tolerance`, `input_hash`, `engine_version`, `iterations`,
`max_unilateral_gain`, `conservation_error`, `debt_settlements`, `dividend_accruals` and
`multi_position_holders` for `exit_waterfall`. The `assumptions` list is the one the
numbers depend on.

**`provenance`**, on every result: `tool`, `server` (`equilibria`), `server_version`,
`library_version`, `engine_version` and `input_hash`. The last two are null where the
library returns no engine record: `conversion_equilibria`, `cap_table_summary`,
`debt_claim`, `convert_note`, `ocf_import`, `ocf_export` and `example_cap_tables`.
`exit_sweep` reports the engine version, and each sampled point carries its own
`input_hash`. Like the library's fingerprint, this is basic provenance, not a signature or
a proof certificate.

**`defaults_applied`**, on every tool that takes positions (and `safe_priced_round`,
`debt_claim`, `convert_note`): see [the `securities` argument](#the-securities-argument).

**`verification`**, on the three tools that allocate value. The adapter re-checks the
engine's result before returning it. If any check fails, the call returns
`invariant_violation` with the failed checks in `details`, and no numbers.

| Tool | Checks |
|---|---|
| `exit_waterfall` | `proceeds_conservation`: the payouts, summed with `math.fsum`, equal net proceeds recomputed from the tool's own `exit_valuation` and `transaction_costs`, within `1e-8 + 1e-12 × net_exit`. `non_negative_payouts`. `payout_components_sum_to_amount`: the preference, participation and residual parts add up to each equity payout. `debt_paid_first_in_seniority_order`: no debt is paid above its claim, no junior debt is paid while a senior tier is short, and no equity is paid while any debt is short. `preferences_paid_in_seniority_order`: no retained preference is paid above its claim (accrued dividends included), no junior preference is paid while a senior one is short, and no residual or participation is paid while any preference is short. `no_profitable_unilateral_deviation`, below. `unallocated_pool_paid_nothing`. `every_position_reported_once`. |
| `exit_sweep` | The same eight checks at every sampled exit. The block reports `points_checked` and `deviation_check_method`. |
| `safe_priced_round` | Re-derived from `post_round_securities` and the tool's own arguments, at relative tolerance `1e-9`. `share_conservation`: the post-round positions' shares add up to `total_post_shares`. `new_money_buys_new_shares`: new preferred shares × share price equal `new_money`. `new_investor_ownership_is_new_money_over_post_money`: new preferred shares ÷ post-round shares equal `N/(V+N)`. `pool_is_target_fraction`. `safe_price_is_best_of_cap_and_discount`: each SAFE's price is min(cap ÷ denominator, round price × (1 − discount)). The denominator is prior common plus converted SAFE shares for `post_money_yc`, and prior common plus the new pool for `pre_money`. `ownership_sums_to_one`. |

**The deviation check.** With at most 10 preferred positions, the adapter evaluates every
conversion profile through `enumerate_equilibria`. It then requires the solver's selected
profile to be one of the fully allocating equilibria, paying the same amounts. The check
reports `method: "exhaustive enumeration of every conversion profile"` and
`independent_of_search: true`. It is independent of the best-response search, but it uses
the engine's own fixed-profile allocator. Above 10 positions, or in an `exit_sweep` whose
`steps × 2**n` exceeds 4,096, it falls back to the engine's reported `max_unilateral_gain`
and says so with `independent_of_search: false`. `every_position_reported_once` holds by
construction today and guards against regressions. The other tools return no
`verification` block. Their refusals are the library's own.

## Errors

A refusal is an MCP tool result with `isError: true`, whose text is one JSON object:

```json
{"error": {"code": "refused_by_model",
           "message": "Unsupported exit instrument safe_post_angel; resolve conversion first",
           "tool": "exit_waterfall",
           "hint": "The library refuses input outside its documented scope rather than guessing. Check the message, then ovf://docs/limitations; do not retry with invented terms."}}
```

That is the actual response to `exit_waterfall` on the USD 60M table with an unconverted
post-money SAFE added. `code` is stable. `message` is the library's text, unchanged. `hint`
and `details` appear only when there is something to put in them.

| Code | Raised when | What the caller should do |
|---|---|---|
| `invalid_terms` | The library refused one position's terms while building it (the message names its index and id), or a library model rejected a field (`details` lists up to 20 of them) | Correct that position from the source documents |
| `refused_by_model` | The library refused input outside its documented scope (a `ValueError` raised inside `ovf`), for example an unconverted SAFE at exit, a duplicate `security_id` or debt without `as_of` | Read the message and `ovf://docs/limitations`; do not retry with invented terms |
| `solver_failure` | A library solver raised a `RuntimeError`, for example the pre-money SAFE bisection failing to converge; no numbers are returned | Report the input if it is within the documented scope |
| `convergence_failure` | The best-response search cycled or ran out of `max_iterations` | Call `conversion_equilibria` (up to 14 positions), or raise `max_iterations` |
| `missing_charter_terms` | `weighted_average` without both `capitalization` and `definition` | Ask the user; there is no default |
| `unused_terms` | `full_ratchet` given `capitalization` or `definition` | Omit them, or use `weighted_average` |
| `invalid_range` | `exit_sweep` with `exit_to` ≤ `exit_from` | Correct the range |
| `invariant_violation` | An adapter re-check failed; no numbers are returned | Treat as a bug; report it with the `input_hash` in `details` |
| `unrepresentable_security` | A library security has no MCP spec, or carries a term the spec cannot express (every returned position is rebuilt from its spec and compared), typically because the library changed after the adapter | Use the Python API for that table |
| `ocf_schema_error` | The input is not OCF v1.2.0-shaped | Check the package and its `ocf_version` |
| `ocf_unsupported` | Valid OCF that expresses a right ovf cannot represent without guessing | See `ovf://docs/ocf` |
| `ocf_integrity_error` | A file does not match its manifest MD5 | Re-export; pass `verify_md5: false` only if the mismatch is understood |
| `ocf_error` | Any other OCF refusal | Read the message |
| `file_error` | A path is missing, is or is not a directory as required, already exists, or cannot be accessed | Correct the path or permissions |
| `path_not_allowed` | A path lies outside `OVF_MCP_ALLOWED_ROOTS` | Use a path inside an allowed root; the hint lists them |

**Argument-shape errors are not in this format.** A missing required argument, a wrong
type, a value outside a declared range or an unknown key is rejected by the SDK's argument
validation before the tool runs. The result is still `isError: true`, but its text is the
SDK's message, for example
`Error executing tool safe_priced_round: 1 validation error for safe_priced_roundArguments
target_pool_pct Field required`. An exception the adapter does not anticipate is also left
to the SDK, which reports a generic failure and writes the traceback to stderr. That
includes a `ValueError` raised by adapter code: only one raised inside the library is
reported as `refused_by_model`.

## Resources and prompts

| Resource | Content |
|---|---|
| `ovf://docs` | Index of the documents below |
| `ovf://docs/{name}` | `semantics`, `limitations`, `debt`, `dividends`, `antidilution`, `financing`, `ocf`, `fixtures`, `findings`, `mcp` (Markdown) |
| `ovf://schema/securities` | JSON Schema of the `securities` argument |

Documents are read from an `ovf_mcp/docs` directory next to the server if one exists, and
otherwise from the checkout's `docs/`. In an installation that has neither, the index marks
each missing document "(not available here)" and reading it fails. Only the ten names above
are served.

| Prompt | Arguments | What it asks the model to do |
|---|---|---|
| `analyze_exit` | `cap_table`, `exit_valuation` (free text) | Translate the table into `securities`, asking for any missing term. Confirm the preference stack with `cap_table_summary`. Run `exit_waterfall`, `conversion_equilibria` and `exit_sweep` from 0 to about twice the exit. Name anything in `ovf://docs/limitations` that applies |
| `safe_round_to_exit` | `round_terms`, `exit_valuation` (free text) | Confirm the round terms without mixing SAFE forms. Run `safe_priced_round`, pass `post_round_securities` to `exit_waterfall`, and state the capitalization convention and the limitations that apply |

The server also sends instructions at initialization. They tell the model not to invent
contract terms, to supply `as_of` where required, to report `assumptions` and
`verification` with the numbers, to resolve SAFEs before an exit, and to check the
limitations resource.

## Walkthrough: the README examples through the server

Each step below is a tool call and the values it returned when this document was written.
The same numbers are derived in [README](../README.md) and [fixtures](fixtures.md).

**1. Get the table.** `example_cap_tables` returns seven tables. They are F1 (suggested
exit USD 35M), F2 (USD 15M), F3 (USD 25M), F5a (USD 40M), F5b (USD 60M), F8a (USD 14M) and
`readme_60m` (USD 60M). The last is the README's stack, which can also be written by hand:

```json
{"securities": [
  {"type": "common", "shares": 8000000, "holder_id": "founders", "security_id": "common"},
  {"type": "preferred", "shares": 2000000, "price": 2.5, "seniority": 2,
   "participating": true, "participation_cap": 2.0,
   "holder_id": "series_a", "security_id": "series_a"},
  {"type": "preferred", "shares": 1500000, "price": 6.0, "seniority": 1,
   "holder_id": "series_b", "security_id": "series_b"}],
 "exit_valuation": 60000000}
```

**2. `exit_waterfall`** with those arguments. `summary.by_holder` is founders `40800000.0`,
series_a `10200000.0` and series_b `9000000.0`, and `summary.converted` is `["series_a"]`.
Series A converts and Series B retains its senior USD 9M preference. The three payments sum
to USD 60M. `tolerance` is `6.001e-05` (`1e-8 + 1e-12 × 60,000,000`), `max_unilateral_gain`
and `conservation_error` are both `0.0`, and `verification.all_passed` is true for all eight
checks. The deviation check enumerated all 4 conversion profiles.

**3. `conversion_equilibria`** with the same arguments. `states_evaluated` is 4,
`equilibrium_exists` is true and `payoff_unique` is true. `solver_selected_profile.converted`
is `["series_a"]`: the main solver found the one equilibrium payout.

**4. `exit_sweep`** with `exit_to: 80000000` and `steps: 81`, a USD 1M grid. The
`conversion_switches` are series_a "starts converting" between USD 59M and USD 60M, and
series_b "starts converting" between USD 69M and USD 70M. These bracket the README's
hand-derived indifference points of USD 59M and USD 69M. At an exact tie the solver keeps
the incumbent election (fixture F3), so each switch shows at the next sample.
`common_receives_nothing_up_to` is `14000000.0`: the USD 5M and USD 9M preferences absorb
every sampled exit up to USD 14M. `verification.points_checked` is 81.

**5. `safe_priced_round`**, the README's SAFE example (fixture S1):

```json
{"prior_common_shares": 8000000, "new_money": 3000000, "pre_money_valuation": 12000000,
 "target_pool_pct": 0, "method": "post_money_yc",
 "safes": [{"amount": 1000000, "cap": 10000000, "holder_id": "angel"}]}
```

`ownership_breakdown` is angel `0.08`, founders `0.7200000000000001`, new_preferred `0.2` and
option_pool `0.0`. `share_price` is `1.35`. The SAFE (`safe_post_angel`) converts into
888,888.89 shares at `1.125`, the cap price. All three verification checks pass. The
founders' figure shows that results are unrounded floats. With `target_pool_pct: 0.10`,
the angel holds `0.07`, founders `0.63` (to float precision) and the pool `0.1`: the README's
7% and fixture S3.

**6. Continue to an exit.** `post_round_securities` holds `round:common` (founders, 8,000,000
common), `safe_post_angel` (888,888.89 preferred at 1.125) and `round:new` (new_preferred,
2,222,222.22 preferred at 1.35). Both preferred positions are 1x non-participating at
seniority 1. Pass that list unchanged as `securities` to `exit_waterfall` at any exit. The
founders' cost basis is unknown, so their `effective_multiple` is null
([semantics](semantics.md), "Round-to-exit transition").

**Replaying without an AI client.** The SDK's in-process client calls the same tools:

```python
import asyncio

from mcp import Client
from ovf_mcp.server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        examples = (await client.call_tool("example_cap_tables", {})).structured_content
        table = next(e for e in examples["examples"] if e["id"] == "readme_60m")["securities"]
        result = await client.call_tool(
            "exit_waterfall", {"securities": table, "exit_valuation": 60_000_000}
        )
        print(result.structured_content["summary"]["by_holder"])
        # {'founders': 40800000.0, 'series_a': 10200000.0, 'series_b': 9000000.0}


asyncio.run(main())
```

The CLI gives an independent route to the SAFE numbers:
`python -m ovf safe --prior-common 8000000 --new-money 3000000 --pre-money 12000000
--safe 1000000:10000000:angel`.

## Security

- **Local and single-user.** Over stdio the server is a subprocess of one client, running
  with that user's permissions, and it opens no listening socket.
- **No network access.** No tool opens a network connection, and every tool is annotated
  `openWorldHint: false`. The Streamable HTTP transport listens on the given host and port,
  and that is the only network activity.
- **No clock.** No tool reads the current date. Accrual uses the `as_of`, `issue_date` and
  `financing_date` passed in, so the same arguments give the same result and the same
  `input_hash`.
- **File access.** Only `ocf_import` (reads) and `ocf_export` with a `directory` (writes)
  touch files the caller names. Resources read only the ten named documents from a fixed
  directory.
- **`OVF_MCP_ALLOWED_ROOTS`.** Directories separated by `os.pathsep` (`:` on macOS and Linux,
  `;` on Windows). When it is set, each root and each requested path is `~`-expanded and
  resolved to an absolute path, following symlinks, and the path must equal a root or lie
  inside one. A relative path resolves against the server process's working directory,
  which the client chooses. When it is unset or empty, the OCF tools can use any path the
  server process can reach. When roots are set, `ocf_import` also resolves every `*.json`
  file in a package directory, because the reader opens each one to find the manifest, and
  refuses a symlink that leads outside the roots. Separately, the OCF reader refuses manifest `filepath` entries
  that escape the package directory, and `ocf_export` writes only into a new or empty
  directory.
- **Streamable HTTP has no authentication and no TLS.** Any process that can reach the
  port can call every tool, including `ocf_export`. Keep the default `127.0.0.1`, set
  `OVF_MCP_ALLOWED_ROOTS`, and do not expose the port to other machines.
- **Imported text is data.** `ocf_import` returns strings taken from the package, such as
  each note's qualified-financing condition text. A calling model should treat them as
  data, not instructions.
- **Logs.** Protocol traffic uses stdout. Logs go to stderr at level WARNING. Refusals are
  logged at INFO, so they do not appear by default.

## Limitations

Everything in [limitations](limitations.md) still applies: no carve-outs, class voting,
coordinated holders, granted options, taxes, earnouts or multi-currency, and the rest of
that list. The adapter adds no modelling and removes no refusal. In addition:

- The server checks the shape of each term. It cannot check that a term matches the
  financing documents. The defaults above are applied when a field is omitted, and
  reported in `defaults_applied`.
- Only `exit_waterfall`, `exit_sweep` and `safe_priced_round` carry a `verification` block,
  and above 10 preferred positions the deviation check relies on the engine's reported
  gain (see above).
- `exit_waterfall` reports one equilibrium. `conversion_equilibria` stops at 14 preferred
  positions, and `exit_sweep` at 401 samples, located only to its grid.
- Results are unrounded IEEE-754 floats in one base currency, with the tolerance above.
  No settlement rounding is applied.
- A security type added to the library before the adapter learns it returns
  `unrepresentable_security`.
- `ovf` is not published on PyPI, so the `uvx` form does not work yet. `smithery.yaml`
  assumes `ovf-mcp` is on `PATH`, and no container image is provided.
- The numbers are the tool's structured result. A model's paraphrase of them can be
  wrong. Check the result, its `assumptions` and its `verification` block before relying
  on a figure.
