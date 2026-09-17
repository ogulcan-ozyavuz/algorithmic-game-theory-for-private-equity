"""ovf-mcp: the Open Venture Framework as a Model Context Protocol server.

The server adds no modelling. Every tool builds library objects from typed specs, calls the
public ``ovf`` API and returns the engine's own record (assumptions, tolerance, input hash)
together with two adapter blocks:

* ``verification``: the accounting invariants re-checked here, independently of the engine.
  If any check fails the call errors instead of returning numbers.
* ``provenance``: tool, server, library and engine versions and the engine's input hash.

Run ``ovf-mcp`` (stdio) or ``ovf-mcp --transport streamable-http``. See ``docs/mcp.md``.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import math
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp_types import ToolAnnotations
from pydantic import Field, ValidationError

import ovf
from ovf.antidilution import (
    BROAD_BASED_NVCA,
    BROAD_BASED_WITH_RESERVED_POOL,
    NARROW_BASED_OUTSTANDING_STOCK,
    CapitalizationBeforeIssue,
    DeemedOutstandingDefinition,
    DilutiveIssuance,
    conversion_ratio,
    full_ratchet,
    weighted_average,
)
from ovf.cli import DEMOS
from ovf.contracts.captable import CapTable
from ovf.contracts.securities import (
    CommonStock,
    CumulativeDividend,
    PostMoneySAFE,
    PreferredStock,
    PreMoneySAFE,
    Security,
    StockOptionPool,
)
from ovf.financing import (
    AntiDilutionProtection,
    ExemptionDetermination,
    NewIssue,
    apply_dilutive_issuance,
)
from ovf.instruments import ConvertibleNote, DebtInstrument
from ovf.ocf import Issuer, OcfNoteTerms, import_ocf, to_ocf, write_ocf_package
from ovf.waterfall import WaterfallResult
from ovf_mcp import __version__
from ovf_mcp.errors import DomainError, classify, error_result
from ovf_mcp.specs import (
    CapitalizationInput,
    ConvertibleNoteSpec,
    CustomDefinition,
    DebtInstrumentSpec,
    DefinitionChoice,
    ExemptionInput,
    IssuerInput,
    NoteTermsInput,
    ProtectionInput,
    SafeTerms,
    SecuritySpec,
    build_securities,
    defaults_applied,
    securities_json_schema,
    securities_to_specs,
    security_to_spec,
)

logger = logging.getLogger("ovf_mcp")

SERVER_NAME = "equilibria"
MAX_SWEEP_STEPS = 401
MAX_ENUMERATED_POSITIONS = 14
# The adapter's own deviation check enumerates every conversion profile up to this size.
VERIFY_ENUMERATION_MAX_POSITIONS = 10
# exit_sweep enumerates at every point only while steps * 2**n stays within this budget.
SWEEP_ENUMERATION_BUDGET = 4096
# The engine's default tolerance: ENGINE_ATOL + ENGINE_RTOL * net exit, in currency units.
ENGINE_ATOL = 1e-8
ENGINE_RTOL = 1e-12
ALLOWED_ROOTS_ENV = "OVF_MCP_ALLOWED_ROOTS"
DOC_NAMES = (
    "semantics",
    "limitations",
    "debt",
    "dividends",
    "antidilution",
    "financing",
    "ocf",
    "fixtures",
    "findings",
    "mcp",
)

INSTRUCTIONS = """\
Equilibria (ovf) computes venture-financing outcomes with explicit assumptions: exit
waterfalls with liquidation preferences and a verified preferred-conversion equilibrium,
SAFE priced rounds, convertible and venture debt, cumulative dividends, price-based
anti-dilution, and Open Cap Table Format (OCF v1.2.0) import/export.

Rules for using these tools well:
1. Never invent contract terms. Seniority, participation, caps, anti-dilution definitions,
   exemptions, note exit treatment and settlement dates set the numbers; ask the user when
   one is missing. Tools refuse rather than assume, and several arguments have no default
   on purpose.
2. All money is in one caller-chosen base currency. `as_of` is required whenever debt or a
   cumulative dividend is present; no clock is ever read.
3. Report the `assumptions` and `verification` blocks with the numbers. `payout_pct` is a
   share of cash proceeds, not equity ownership.
4. An unconverted SAFE cannot enter an exit: resolve it with safe_priced_round, then pass
   `post_round_securities` to exit_waterfall. Tool outputs that contain a cap table are
   ready to pass to the next tool unchanged.
5. What is not modelled (carve-outs, class voting, taxes, earnouts, ...) is listed in the
   resource ovf://docs/limitations. Check it before presenting results as complete.
Start with example_cap_tables or cap_table_summary if unsure of the input shape.
"""

mcp: MCPServer = MCPServer(
    name=SERVER_NAME,
    title="Equilibria / Open Venture Framework",
    description="Verified exit waterfalls, SAFE rounds, debt, anti-dilution and OCF for agents",
    instructions=INSTRUCTIONS,
    version=__version__,
)

P = ParamSpec("P")
R = TypeVar("R")

# ------------------------------------------------------------------------- argument types

Securities = Annotated[
    list[SecuritySpec],
    Field(
        min_length=1,
        description=(
            "The cap table: one object per position, discriminated by 'type' (common, "
            "preferred, pool, safe_post, safe_pre, debt, venture_debt, convertible_note). "
            "Field names match the ovf factories and the CLI --file JSON. Full JSON Schema: "
            "resource ovf://schema/securities."
        ),
    ),
]
ExitValuation = Annotated[
    float, Field(ge=0, description="Gross exit price in the base currency, before costs")
]
TransactionCosts = Annotated[
    float, Field(ge=0, description="One lump sum deducted from the gross exit before any claim")
]
AsOf = Annotated[
    date | None,
    Field(
        description=(
            "Settlement date (YYYY-MM-DD) used to accrue debt interest and cumulative "
            "dividends. Required when the table holds either; never defaulted to today."
        )
    ),
]


def _tool(
    title: str, *, read_only: bool = True, idempotent: bool = True
) -> Callable[[Callable[P, R]], Callable[P, Any]]:
    """Register a tool whose anticipated failures become structured ``is_error`` results.

    Unanticipated exceptions propagate: the SDK reports a generic failure to the client and
    logs the traceback, so no internal detail leaks into the model's context.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, Any]:
        @functools.wraps(fn)
        def guarded(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as error:
                domain = classify(error)
                if domain is None:
                    raise
                logger.info("%s refused: %s: %s", fn.__name__, domain.code, domain.message)
                return error_result(domain, fn.__name__)

        mcp.add_tool(
            guarded,
            name=fn.__name__,
            title=title,
            annotations=ToolAnnotations(
                title=title,
                read_only_hint=read_only,
                destructive_hint=False,
                idempotent_hint=idempotent,
                open_world_hint=False,
            ),
            structured_output=True,
        )
        return guarded

    return decorator


# ------------------------------------------------------------------------- helpers


def _table(specs: Sequence[Any]) -> CapTable:
    securities = build_securities(specs)
    try:
        return CapTable(securities=securities)
    except ValidationError as error:
        # CapTable's validator raises the library's refusal (e.g. a duplicate security_id);
        # pydantic wraps it, so unwrap it back into the refusal it is.
        raise DomainError(
            "refused_by_model",
            "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in error.errors()),
            hint="The library refuses this cap table as a whole; correct it and retry.",
        ) from error


def _merge(engine: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
    """The engine's record plus adapter keys; a name clash is a bug, never an overwrite."""
    clash = sorted(set(engine) & set(adapter))
    if clash:
        raise RuntimeError(f"adapter keys would overwrite engine fields: {clash}")
    return {**engine, **adapter}


def _provenance(
    tool: str, *, engine_version: str | None = None, input_hash: str | None = None
) -> dict[str, Any]:
    return {
        "tool": tool,
        "server": SERVER_NAME,
        "server_version": __version__,
        "library_version": ovf.__version__,
        "engine_version": engine_version,
        "input_hash": input_hash,
    }


def _passed(checks: dict[str, dict[str, Any]], input_hash: str, checked_by: str) -> dict[str, Any]:
    failed = [name for name, check in checks.items() if not check["ok"]]
    if failed:
        raise DomainError(
            "invariant_violation",
            f"adapter re-check failed: {', '.join(failed)}",
            hint="No numbers are returned. This is a bug; report it with the input_hash.",
            details={"checks": checks, "input_hash": input_hash},
        )
    return {"all_passed": True, "checked_by": checked_by, "checks": checks}


WATERFALL_CHECKED_BY = (
    "ovf-mcp adapter. Net proceeds and tolerance are recomputed from the tool's own "
    "arguments; payment order is re-checked from the returned payouts and claims. The "
    "deviation check re-evaluates every conversion profile when its method says so."
)


def _verify_waterfall(
    result: WaterfallResult,
    securities: Sequence[Security],
    *,
    exit_valuation: float,
    transaction_costs: float,
    as_of: date | None,
    enumerate_profiles: bool,
) -> dict[str, Any]:
    """Re-check an engine result against the accounting invariants; raise if any fails."""
    net_exit = max(0.0, exit_valuation - transaction_costs)
    tolerance = ENGINE_ATOL + ENGINE_RTOL * net_exit
    payouts = {p.security_id: p for p in result.payouts}
    amounts = [p.amount for p in result.payouts]
    total = math.fsum(amounts)
    debt_ids = {s.security_id for s in securities if isinstance(s, DebtInstrument)}
    checks: dict[str, dict[str, Any]] = {
        "proceeds_conservation": {
            "ok": abs(total - net_exit) <= tolerance,
            "sum_of_payouts": total,
            "net_exit_from_arguments": net_exit,
            "error": total - net_exit,
            "tolerance": tolerance,
        },
        "non_negative_payouts": {"ok": all(a >= 0 for a in amounts)},
    }

    mismatched = [
        security_id
        for security_id, p in payouts.items()
        if security_id not in debt_ids
        and abs(p.preference_payout + p.participation_payout + p.residual_payout - p.amount)
        > tolerance
    ]
    checks["payout_components_sum_to_amount"] = {"ok": not mismatched, "mismatched": mismatched}

    debt_problems: list[str] = []
    settlements = result.debt_settlements
    for d in settlements:
        security_id = d.claim.security_id
        if d.paid > d.claim.claim + tolerance:
            debt_problems.append(f"{security_id} paid more than its claim")
        if security_id not in payouts or abs(payouts[security_id].amount - d.paid) > tolerance:
            debt_problems.append(f"{security_id} payout differs from its settlement")
        for junior in settlements:
            if (
                junior.claim.seniority > d.claim.seniority
                and d.shortfall > tolerance
                and junior.paid > tolerance
            ):
                debt_problems.append(
                    f"{junior.claim.security_id} paid while senior {security_id} is short"
                )
    equity_paid = math.fsum(p.amount for i, p in payouts.items() if i not in debt_ids)
    if any(d.shortfall > tolerance for d in settlements) and equity_paid > tolerance:
        debt_problems.append("equity paid while debt is short")
    if debt_ids - {d.claim.security_id for d in settlements}:
        debt_problems.append("a debt position has no settlement")
    checks["debt_paid_first_in_seniority_order"] = {
        "ok": not debt_problems,
        "problems": debt_problems,
    }

    preference_problems: list[str] = []
    retained = [
        s
        for s in securities
        if isinstance(s, PreferredStock) and not payouts[s.security_id].converted
    ]
    claims = {s.security_id: s.exit_terms(as_of).preference for s in retained}
    short = {i for i in claims if payouts[i].preference_payout < claims[i] - tolerance}
    for s in retained:
        paid = payouts[s.security_id].preference_payout
        if paid > claims[s.security_id] + tolerance:
            preference_problems.append(f"{s.security_id} preference above its claim")
        if paid > tolerance:
            senior_short = [
                t.security_id
                for t in retained
                if t.seniority < s.seniority and t.security_id in short
            ]
            if senior_short:
                preference_problems.append(
                    f"{s.security_id} paid a preference while senior {senior_short} are short"
                )
    residual_paid = math.fsum(
        p.participation_payout + p.residual_payout for i, p in payouts.items() if i not in debt_ids
    )
    if short and residual_paid > tolerance:
        preference_problems.append(f"residual paid while preferences are short: {sorted(short)}")
    checks["preferences_paid_in_seniority_order"] = {
        "ok": not preference_problems,
        "problems": preference_problems,
    }

    players = sorted(s.security_id for s in securities if isinstance(s, PreferredStock))
    if enumerate_profiles and len(players) <= VERIFY_ENUMERATION_MAX_POSITIONS:
        survey = ovf.enumerate_equilibria(
            securities,
            exit_valuation,
            transaction_costs,
            max_positions=VERIFY_ENUMERATION_MAX_POSITIONS,
            as_of=as_of,
        )
        selected = {i: payouts[i].converted for i in players}
        index = next(
            (k for k, profile in enumerate(survey.feasible_equilibria) if profile == selected),
            None,
        )
        payouts_match = index is not None and all(
            abs(amount - payouts[i].amount) <= tolerance
            for i, amount in survey.feasible_payoffs[index].items()
            if i in payouts
        )
        checks["no_profitable_unilateral_deviation"] = {
            "ok": index is not None and payouts_match,
            "method": "exhaustive enumeration of every conversion profile",
            "independent_of_search": True,
            "profiles_evaluated": survey.states_evaluated,
            "selected_profile_is_an_equilibrium": index is not None,
            "payouts_match_enumerated_profile": payouts_match,
        }
    else:
        checks["no_profitable_unilateral_deviation"] = {
            "ok": result.converged and result.max_unilateral_gain <= tolerance,
            "method": "engine-reported maximum unilateral gain",
            "independent_of_search": False,
            "reason": (
                f"{len(players)} preferred positions exceed the enumeration limit of "
                f"{VERIFY_ENUMERATION_MAX_POSITIONS}"
                if len(players) > VERIFY_ENUMERATION_MAX_POSITIONS
                else "enumeration budget for this sweep exceeded"
            ),
            "max_unilateral_gain": result.max_unilateral_gain,
            "tolerance": tolerance,
        }

    pools = {s.security_id for s in securities if isinstance(s, StockOptionPool)}
    reported = [p.security_id for p in result.payouts]
    checks["unallocated_pool_paid_nothing"] = {
        "ok": all(payouts[i].amount <= tolerance for i in pools if i in payouts)
    }
    checks["every_position_reported_once"] = {
        "ok": sorted(reported) == sorted(s.security_id for s in securities)
        and len(set(reported)) == len(reported)
    }
    return _passed(checks, result.input_hash, WATERFALL_CHECKED_BY)


def _summary(result: WaterfallResult) -> dict[str, Any]:
    by_holder: dict[str, float] = {}
    for p in result.payouts:
        by_holder[p.holder_id] = by_holder.get(p.holder_id, 0.0) + p.amount
    return {
        "net_exit": result.net_exit,
        "by_holder": by_holder,
        "converted": sorted(p.security_id for p in result.payouts if p.converted),
        "debt_paid": {d.claim.security_id: d.paid for d in result.debt_settlements},
    }


def _definition(choice: DefinitionChoice) -> DeemedOutstandingDefinition:
    if isinstance(choice, CustomDefinition):
        return DeemedOutstandingDefinition(**choice.model_dump())
    return {
        "broad_based_nvca": BROAD_BASED_NVCA,
        "broad_based_with_reserved_pool": BROAD_BASED_WITH_RESERVED_POOL,
        "narrow_based_outstanding_stock": NARROW_BASED_OUTSTANDING_STOCK,
    }[choice]


def _roots() -> list[Path]:
    return [
        Path(root).expanduser().resolve()
        for root in os.environ.get(ALLOWED_ROOTS_ENV, "").split(os.pathsep)
        if root.strip()
    ]


def _require_inside(path: Path, roots: list[Path], shown: str) -> None:
    if roots and not any(path == root or path.is_relative_to(root) for root in roots):
        raise DomainError(
            "path_not_allowed",
            f"{shown} resolves to {path}, outside {ALLOWED_ROOTS_ENV}",
            hint=f"Allowed roots: {', '.join(str(r) for r in roots)}",
        )


def _allowed_path(raw: str, *, must_exist: bool) -> Path:
    path = Path(raw).expanduser().resolve()
    _require_inside(path, _roots(), raw)
    if must_exist and not path.exists():
        raise DomainError("file_error", f"{path} does not exist")
    return path


def _defaults_note(applied: dict[str, dict[str, Any]]) -> list[str]:
    if not applied:
        return []
    return [
        "Terms omitted by the caller took the factory defaults listed in defaults_applied; "
        "confirm each one against the financing documents."
    ]


# ------------------------------------------------------------------------- exit tools


@_tool("Exit waterfall")
def exit_waterfall(
    securities: Securities,
    exit_valuation: ExitValuation,
    transaction_costs: TransactionCosts = 0.0,
    as_of: AsOf = None,
    max_iterations: Annotated[int, Field(ge=1, le=1000)] = 20,
) -> dict[str, Any]:
    """Allocate one exit across the cap table and verify the conversion equilibrium.

    Debt is paid first, then preferred preferences by ascending seniority, then the residual
    to common, converted and participating preferred. Each preferred position's conversion
    election is solved as a game and checked for profitable unilateral deviation. Returns
    per-position payouts (preference, participation and residual parts, converted flag,
    payout_pct of proceeds, effective multiple), debt settlements, dividend accruals, the
    engine's assumptions and input hash, `defaults_applied` and an independent
    verification block.
    """
    table = _table(securities)
    applied = defaults_applied(securities, table.securities)
    result = table.waterfall_detailed(
        exit_valuation, transaction_costs, max_iterations, as_of=as_of
    )
    verification = _verify_waterfall(
        result,
        table.securities,
        exit_valuation=exit_valuation,
        transaction_costs=transaction_costs,
        as_of=as_of,
        enumerate_profiles=True,
    )
    return _merge(
        result.model_dump(mode="json"),
        {
            "summary": _summary(result),
            "defaults_applied": applied,
            "adapter_notes": _defaults_note(applied),
            "verification": verification,
            "provenance": _provenance(
                "exit_waterfall", engine_version=result.engine_version, input_hash=result.input_hash
            ),
        },
    )


@_tool("Exit sweep")
def exit_sweep(
    securities: Securities,
    exit_to: Annotated[float, Field(gt=0, description="Largest gross exit sampled")],
    exit_from: Annotated[float, Field(ge=0, description="Smallest gross exit sampled")] = 0.0,
    steps: Annotated[int, Field(ge=2, le=MAX_SWEEP_STEPS)] = 21,
    transaction_costs: TransactionCosts = 0.0,
    as_of: AsOf = None,
) -> dict[str, Any]:
    """Allocate an evenly spaced range of exits to see where each class's payout changes.

    Every sampled exit is solved and verified independently. `conversion_switches` brackets,
    between two sampled exits, each change in a preferred position's conversion election;
    the grid can step over a breakpoint, so refine the range around a bracket.
    `common_receives_nothing_up_to` is the largest sampled exit at which common is paid zero.
    """
    if exit_to <= exit_from:
        raise DomainError("invalid_range", "exit_to must be greater than exit_from")
    table = _table(securities)
    applied = defaults_applied(securities, table.securities)
    ids = [s.security_id for s in table.securities]
    common_ids = {s.security_id for s in table.securities if isinstance(s, CommonStock)}
    preferred_ids = sorted(s.security_id for s in table.securities if isinstance(s, PreferredStock))
    enumerate_profiles = steps * 2 ** len(preferred_ids) <= SWEEP_ENUMERATION_BUDGET
    points: list[dict[str, Any]] = []
    first: WaterfallResult | None = None
    deviation_method = ""
    for step in range(steps):
        exit_value = exit_from + (exit_to - exit_from) * step / (steps - 1)
        result = table.waterfall_detailed(exit_value, transaction_costs, as_of=as_of)
        checked = _verify_waterfall(
            result,
            table.securities,
            exit_valuation=exit_value,
            transaction_costs=transaction_costs,
            as_of=as_of,
            enumerate_profiles=enumerate_profiles,
        )
        deviation_method = checked["checks"]["no_profitable_unilateral_deviation"]["method"]
        first = first or result
        points.append(
            {
                "exit_valuation": exit_value,
                "net_exit": result.net_exit,
                "payouts": {p.security_id: p.amount for p in result.payouts},
                "converted": sorted(p.security_id for p in result.payouts if p.converted),
                "common_total": math.fsum(
                    p.amount for p in result.payouts if p.security_id in common_ids
                ),
                "max_unilateral_gain": result.max_unilateral_gain,
                "conservation_error": result.conservation_error,
                "tolerance": result.tolerance,
                "input_hash": result.input_hash,
            }
        )
    switches = []
    for before, after in zip(points, points[1:], strict=False):
        for security_id in preferred_ids:
            was, now = security_id in before["converted"], security_id in after["converted"]
            if was != now:
                switches.append(
                    {
                        "security_id": security_id,
                        "change": "starts converting" if now else "stops converting",
                        "between_exits": [before["exit_valuation"], after["exit_valuation"]],
                    }
                )
    zero_common = [p["exit_valuation"] for p in points if p["common_total"] <= p["tolerance"]]
    assert first is not None
    return {
        "security_ids": ids,
        "holders": {s.security_id: s.holder_id for s in table.securities},
        "points": points,
        "conversion_switches": switches,
        "common_receives_nothing_up_to": max(zero_common) if common_ids and zero_common else None,
        "assumptions": [
            *first.assumptions,
            "Each sampled exit is solved independently; no path dependence is modelled.",
            "Breakpoints are located only to the sampling grid; refine steps near a switch.",
        ],
        "defaults_applied": applied,
        "adapter_notes": _defaults_note(applied),
        "verification": {
            "all_passed": True,
            "points_checked": len(points),
            "deviation_check_method": deviation_method,
            "checked_by": "ovf-mcp adapter; every sampled exit passed every exit_waterfall check",
        },
        "provenance": _provenance("exit_sweep", engine_version=first.engine_version),
    }


@_tool("Conversion equilibria survey")
def conversion_equilibria(
    securities: Securities,
    exit_valuation: ExitValuation,
    transaction_costs: TransactionCosts = 0.0,
    as_of: AsOf = None,
    max_positions: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_ENUMERATED_POSITIONS,
            description="Refuse above this many preferred positions (cost is 2**n profiles)",
        ),
    ] = 12,
) -> dict[str, Any]:
    """Enumerate every pure conversion equilibrium at one exit and test payout uniqueness.

    Evaluates all 2**n conversion profiles of the n preferred positions. Reports every
    equilibrium, those that allocate the whole exit, their payout vectors and whether they
    pay the same amounts. Several profiles paying identical amounts is ordinary; strategy
    uniqueness and payout uniqueness are different questions. Also reports the profile the
    main solver (exit_waterfall) selects, or why it could not.
    """
    table = _table(securities)
    applied = defaults_applied(securities, table.securities)
    survey = ovf.enumerate_equilibria(
        table.securities,
        exit_valuation,
        transaction_costs,
        max_positions=max_positions,
        as_of=as_of,
    )
    selected: dict[str, Any]
    try:
        result = table.waterfall_detailed(exit_valuation, transaction_costs, as_of=as_of)
        selected = {
            "converted": sorted(p.security_id for p in result.payouts if p.converted),
            "payouts": {p.security_id: p.amount for p in result.payouts},
        }
    except (ovf.WaterfallConvergenceError, ValueError) as error:
        selected = {"converted": None, "unavailable": str(error)}
    return _merge(
        survey.model_dump(mode="json"),
        {
            "equilibrium_exists": bool(survey.feasible_equilibria),
            "solver_selected_profile": selected,
            "interpretation": [
                "Existence is established only for this input; no general theorem is claimed.",
                "payoff_unique compares the payout vectors of the fully allocating equilibria.",
            ],
            "defaults_applied": applied,
            "adapter_notes": _defaults_note(applied),
            "provenance": _provenance("conversion_equilibria"),
        },
    )


@_tool("Cap table summary")
def cap_table_summary(securities: Securities) -> dict[str, Any]:
    """Validate a cap table and describe it: ownership, preference stack and debt ranks.

    Returns the normalized securities (with derived ids filled in) ready for the other tools,
    `defaults_applied` (every omitted contract term and the default used), fully diluted
    ownership by holder (unavailable while an unconverted SAFE is present), the preference
    stack by seniority tier (base preference = invested x multiple, excluding accrued
    dividends), debt by rank, and holders owning several preferred positions.
    """
    table = _table(securities)
    applied = defaults_applied(securities, table.securities)
    items = table.securities
    counts: dict[str, int] = {}
    for spec in securities_to_specs(items):
        counts[spec["type"]] = counts.get(spec["type"], 0) + 1
    fully_diluted: dict[str, Any]
    try:
        fully_diluted = {
            "available": True,
            "shares": table.fully_diluted_shares,
            "ownership_by_holder": table.ownership_breakdown(),
        }
    except ValueError as error:
        fully_diluted = {"available": False, "reason": str(error)}
    tiers: dict[int, list[dict[str, Any]]] = {}
    for s in items:
        if isinstance(s, PreferredStock):
            tiers.setdefault(s.seniority, []).append(
                {
                    "security_id": s.security_id,
                    "holder_id": s.holder_id,
                    "invested_capital": s.invested_capital,
                    "liquidation_multiple": s.liquidation_multiple,
                    "base_preference": s.invested_capital * s.liquidation_multiple,
                    "cumulative_dividend": isinstance(s.dividend, CumulativeDividend),
                    "participating": s.participating,
                    "participation_cap": s.participation_cap,
                    "as_converted_shares": s.converted_shares,
                }
            )
    stack = []
    for seniority in sorted(tiers):
        positions = tiers[seniority]
        stack.append(
            {
                "seniority": seniority,
                "positions": positions,
                "tier_base_preference": math.fsum(p["base_preference"] for p in positions),
                "excludes_accrued_dividends": any(p["cumulative_dividend"] for p in positions),
            }
        )
    debt = sorted(
        (
            {
                "security_id": s.security_id,
                "holder_id": s.holder_id,
                "type": security_to_spec(s)["type"],
                "seniority": s.seniority,
                "principal": s.principal,
            }
            for s in items
            if isinstance(s, DebtInstrument)
        ),
        key=lambda d: (d["seniority"], d["security_id"]),
    )
    notes = [
        "Debt, when present, is paid ahead of all equity; see debt_claim for accruals.",
        *_defaults_note(applied),
    ]
    if any(isinstance(s, PostMoneySAFE | PreMoneySAFE) for s in items):
        notes.append("Unconverted SAFEs present: resolve them with safe_priced_round first.")
    return {
        "positions": len(items),
        "by_type": counts,
        "total_shares": table.total_shares,
        "fully_diluted": fully_diluted,
        "preference_stack": stack,
        "debt": debt,
        "multi_position_holders": ovf.multi_position_holders(items),
        "normalized_securities": securities_to_specs(items),
        "defaults_applied": applied,
        "notes": notes,
        "provenance": _provenance("cap_table_summary"),
    }


# ------------------------------------------------------------------------- financing tools


def _relative_gap(value: float, expected: float) -> float:
    return abs(value - expected) / max(abs(expected), 1e-300)


@_tool("SAFE priced round")
def safe_priced_round(
    prior_common_shares: Annotated[
        float, Field(gt=0, description="Common shares before the round")
    ],
    new_money: Annotated[float, Field(gt=0, description="New cash invested in the priced round")],
    pre_money_valuation: Annotated[float, Field(gt=0, description="Negotiated pre-money")],
    target_pool_pct: Annotated[
        float,
        Field(
            ge=0,
            lt=1,
            description="New unallocated pool as a fraction of post-round shares; 0 for none",
        ),
    ],
    method: Annotated[
        Literal["post_money_yc", "pre_money"],
        Field(
            description=(
                "The SAFEs' form, which sets the cap denominator: post_money_yc (YC post-money "
                "SAFE) or pre_money. No default: the two convert to different share counts"
            )
        ),
    ],
    safes: list[SafeTerms] | None = None,
) -> dict[str, Any]:
    """Solve a priced round in which SAFEs convert, from a common-only starting table.

    Converting SAFEs and the new pool sit inside the negotiated pre-money, which fixes new
    investor ownership at new_money / (pre_money + new_money). All SAFEs share one form,
    set by `method`. Returns the share price, each SAFE's conversion price and shares,
    ownership by holder, the share-conservation error and `post_round_securities`, the
    resulting cap table ready for exit_waterfall. The verification block re-derives the
    round from `post_round_securities`.
    """
    factory = ovf.safe_post if method == "post_money_yc" else ovf.safe_pre
    terms_list = list(safes or [])
    instruments = []
    for index, terms in enumerate(terms_list):
        try:
            instruments.append(
                factory(
                    amount=terms.amount,
                    cap=terms.cap,
                    discount_rate=terms.discount_rate,
                    holder_id=terms.holder_id,
                    security_id=terms.security_id,
                )
            )
        except ValueError as error:
            raise DomainError(
                "invalid_terms", f"safes[{index}] ({terms.holder_id}): {error}"
            ) from error
    applied = {
        s.security_id: omitted
        for terms, s in zip(terms_list, instruments, strict=True)
        if (omitted := terms.defaults_applied())
    }
    result = ovf.solve_priced_round_with_safes(
        prior_common_shares=prior_common_shares,
        new_money=new_money,
        pre_money_valuation=pre_money_valuation,
        target_pool_pct=target_pool_pct,
        safes=instruments,
        method=method,
    )
    post_round = result.to_cap_table()
    by_id = {s.security_id: s for s in post_round.securities}

    def held(s: Security) -> float:
        return s.reserved_shares if isinstance(s, StockOptionPool) else s.shares

    shares_total = math.fsum(held(s) for s in post_round.securities)
    new = by_id["round:new"]
    pool_shares = math.fsum(
        held(s) for s in post_round.securities if isinstance(s, StockOptionPool)
    )
    safe_positions = [by_id[s.security_id] for s in instruments]
    converted_total = math.fsum(s.shares for s in safe_positions)
    price_gaps: dict[str, float] = {}
    for instrument, position in zip(instruments, safe_positions, strict=True):
        denominator = (
            prior_common_shares + converted_total
            if method == "post_money_yc"
            else prior_common_shares + pool_shares
        )
        cap_price = instrument.valuation_cap / denominator
        discount_price = new.price * (1 - instrument.discount_rate)
        price_gaps[instrument.security_id] = _relative_gap(
            position.price, min(cap_price, discount_price)
        )
    ownership_total = math.fsum(result.ownership_breakdown.values())
    expected_new = new_money / (pre_money_valuation + new_money)
    checks: dict[str, dict[str, Any]] = {
        "share_conservation": {
            "ok": _relative_gap(shares_total, result.total_post_shares) <= 1e-9,
            "post_round_shares": shares_total,
            "reported_total_post_shares": result.total_post_shares,
        },
        "new_money_buys_new_shares": {
            "ok": _relative_gap(new.shares * new.price, new_money) <= 1e-9,
            "new_shares_times_price": new.shares * new.price,
            "new_money": new_money,
        },
        "new_investor_ownership_is_new_money_over_post_money": {
            "ok": abs(new.shares / shares_total - expected_new) <= 1e-9,
            "new_preferred_fraction": new.shares / shares_total,
            "expected": expected_new,
        },
        "pool_is_target_fraction": {
            "ok": abs(pool_shares / shares_total - target_pool_pct) <= 1e-9,
            "pool_fraction": pool_shares / shares_total,
            "target": target_pool_pct,
        },
        "safe_price_is_best_of_cap_and_discount": {
            "ok": all(gap <= 1e-9 for gap in price_gaps.values()),
            "relative_gap_by_safe": price_gaps,
            "cap_denominator": (
                "prior common + converted SAFE shares"
                if method == "post_money_yc"
                else "prior common + new pool"
            ),
        },
        "ownership_sums_to_one": {"ok": abs(ownership_total - 1.0) <= 1e-9, "sum": ownership_total},
    }
    verification = _passed(
        checks,
        result.input_hash,
        "ovf-mcp adapter; re-derived from post_round_securities and the tool's own arguments",
    )
    return _merge(
        result.model_dump(mode="json", exclude={"converted_safes"}),
        {
            "converted_safes": securities_to_specs(result.converted_safes),
            "post_round_securities": securities_to_specs(post_round.securities),
            "next_step": "Pass post_round_securities as `securities` to exit_waterfall.",
            "defaults_applied": applied,
            "adapter_notes": _defaults_note(applied),
            "verification": verification,
            "provenance": _provenance(
                "safe_priced_round",
                engine_version=result.engine_version,
                input_hash=result.input_hash,
            ),
        },
    )


@_tool("Anti-dilution adjustment")
def anti_dilution_adjustment(
    method: Literal["weighted_average", "full_ratchet"],
    conversion_price: Annotated[float, Field(gt=0, description="CP1, in effect before the issue")],
    shares_issued: Annotated[float, Field(gt=0, description="C: common-equivalent shares issued")],
    aggregate_consideration: Annotated[
        float, Field(ge=0, description="What the company received for them, as stated")
    ],
    capitalization: CapitalizationInput | None = None,
    definition: Annotated[
        DefinitionChoice | None,
        Field(description="The charter's 'A': a named composition or a custom one"),
    ] = None,
    original_issue_price: Annotated[
        float | None, Field(gt=0, description="If given, conversion ratios are reported too")
    ] = None,
) -> dict[str, Any]:
    """Compute one price-based anti-dilution adjustment (NVCA Model COI 4.4.4).

    Weighted average: CP2 = CP1 * (A + B) / (A + C), where A is the deemed-outstanding count
    under the charter's definition, B = consideration / CP1 and C the shares issued; it needs
    `capitalization` and `definition` and has no default for either. Full ratchet: CP2 is the
    issue price, and takes neither. Adjusts only downward; CP2 is unrounded.
    """
    issuance = DilutiveIssuance(
        shares_issued=shares_issued, aggregate_consideration=aggregate_consideration
    )
    if method == "weighted_average":
        if capitalization is None or definition is None:
            raise DomainError(
                "missing_charter_terms",
                "a weighted-average adjustment needs both `capitalization` and `definition`",
                hint=(
                    "Ask the user for the pre-issuance capitalization and the charter's "
                    "definition of A. There is no default: broad- and narrow-based differ "
                    "only in A."
                ),
            )
        adjustment = weighted_average(
            conversion_price=conversion_price,
            capitalization=CapitalizationBeforeIssue(**capitalization.model_dump()),
            definition=_definition(definition),
            issuance=issuance,
        )
    else:
        if capitalization is not None or definition is not None:
            raise DomainError(
                "unused_terms",
                "full ratchet does not use `capitalization` or `definition`",
                hint="Omit them, or use method='weighted_average'.",
            )
        adjustment = full_ratchet(conversion_price=conversion_price, issuance=issuance)
    adapter: dict[str, Any] = {"adjustment_factor": adjustment.adjustment_factor}
    if original_issue_price is not None:
        adapter["conversion_ratio_before"] = conversion_ratio(
            original_issue_price=original_issue_price,
            conversion_price=adjustment.conversion_price_before,
        )
        adapter["conversion_ratio_after"] = conversion_ratio(
            original_issue_price=original_issue_price,
            conversion_price=adjustment.conversion_price_after,
        )
    adapter["provenance"] = _provenance(
        "anti_dilution_adjustment",
        engine_version=adjustment.engine_version,
        input_hash=adjustment.input_hash,
    )
    return _merge(adjustment.model_dump(mode="json"), adapter)


@_tool("Dilutive issuance")
def dilutive_issuance(
    securities: Securities,
    new_securities: Annotated[
        list[SecuritySpec],
        Field(min_length=1, description="The common or preferred issued in this transaction"),
    ],
    aggregate_consideration: Annotated[
        float, Field(ge=0, description="Cash (or board-valued property) the company received")
    ],
    protection: Annotated[
        dict[str, ProtectionInput],
        Field(
            description=(
                "security_id -> anti-dilution term, for EVERY preferred position in "
                "`securities`; use {'method': 'none'} for an unprotected one"
            )
        ),
    ],
    exemption: ExemptionInput,
) -> dict[str, Any]:
    """Issue new shares against a cap table and apply each preferred position's protection.

    All positions are adjusted from one capitalization immediately before the issuance.
    Only conversion ratios change. Returns each position's before/after conversion price,
    ratio and as-converted shares, the capitalization used, and `securities_after`, the new
    cap table (input positions in order, adjusted ones replaced, then the new securities).
    """
    table = _table(securities)
    issued = build_securities(new_securities)
    applied = {
        **defaults_applied(securities, table.securities),
        **defaults_applied(new_securities, issued),
    }
    issue = NewIssue(securities=tuple(issued), aggregate_consideration=aggregate_consideration)
    terms = {
        security_id: AntiDilutionProtection(
            method=term.method,
            definition=None if term.definition is None else _definition(term.definition),
        )
        for security_id, term in protection.items()
    }
    result = apply_dilutive_issuance(
        table,
        issue=issue,
        protection=terms,
        exemption=ExemptionDetermination(exempted=exemption.exempted, basis=exemption.basis),
    )
    return _merge(
        result.model_dump(
            mode="json", exclude={"table": True, "positions": {"__all__": {"position_after"}}}
        ),
        {
            "securities_after": securities_to_specs(result.table.securities),
            "defaults_applied": applied,
            "adapter_notes": _defaults_note(applied),
            "provenance": _provenance(
                "dilutive_issuance",
                engine_version=result.engine_version,
                input_hash=result.input_hash,
            ),
        },
    )


# ------------------------------------------------------------------------- debt tools


@_tool("Debt claim")
def debt_claim(instrument: DebtInstrumentSpec, as_of: date) -> dict[str, Any]:
    """Accrue one debt instrument to `as_of` and state what it claims at an exit.

    Returns the accrual (day count, year fraction, periods, interest), the exit claim with
    the formula that produced it (or the reason it is unavailable, e.g. a convertible note
    without a stated exit treatment) and, for a note, the repayment due at maturity.
    """
    (security,) = build_securities([instrument])
    assert isinstance(security, DebtInstrument)
    accrual = security.accrue(as_of)
    out: dict[str, Any] = {
        "instrument": security_to_spec(security),
        "accrual": accrual.model_dump(mode="json"),
        "outstanding_amount": accrual.outstanding_amount,
        "defaults_applied": instrument.defaults_applied(),
    }
    try:
        out["exit_claim"] = security.exit_claim(as_of).model_dump(mode="json")
    except ValueError as error:
        out["exit_claim"] = None
        out["exit_claim_unavailable"] = str(error)
    if isinstance(security, ConvertibleNote):
        out["repayment_at_maturity"] = security.repayment_at_maturity().model_dump(mode="json")
    out["provenance"] = _provenance("debt_claim")
    return out


@_tool("Convert a note at a financing")
def convert_note(
    note: ConvertibleNoteSpec,
    financing_date: date,
    new_money: Annotated[float, Field(ge=0, description="New money raised in the financing")],
    round_price: Annotated[float, Field(gt=0, description="Price per share of the new round")],
    capitalization_shares: Annotated[
        float | None,
        Field(gt=0, description="Shares the note's cap is divided by; required with a cap"),
    ] = None,
) -> dict[str, Any]:
    """Convert a convertible note automatically in a qualified financing.

    Principal plus interest accrued to `financing_date` converts at
    min(valuation_cap / capitalization_shares, round_price * (1 - discount_rate)). A
    financing below the qualified threshold is refused (optional conversion is not modelled).
    """
    (security,) = build_securities([note])
    assert isinstance(security, ConvertibleNote)
    conversion = security.convert_at_financing(
        financing_date,
        new_money=new_money,
        round_price=round_price,
        capitalization_shares=capitalization_shares,
    )
    return _merge(
        conversion.model_dump(mode="json"),
        {
            "qualified_financing": True,
            "defaults_applied": note.defaults_applied(),
            "provenance": _provenance("convert_note"),
        },
    )


# ------------------------------------------------------------------------- OCF tools

CapBasis = Annotated[
    Literal["total", "participation_only"],
    Field(
        description=(
            "How OCF's participation_cap_multiple relates to the preference. 'total' (the NVCA "
            "meaning, and PreferredStock.participation_cap's) caps preference plus "
            "participation; 'participation_only' caps participation alone. OCF v1.2.0 does "
            "not say which, so there is no default"
        )
    ),
]


@_tool("Import an OCF package")
def ocf_import(
    path: Annotated[str, Field(description="OCF v1.2.0 package directory or its manifest file")],
    participation_cap_basis: CapBasis,
    ignore_common_preference_fields: bool = False,
    verify_md5: bool = True,
    note_terms: Annotated[
        dict[str, NoteTermsInput] | None,
        Field(description="Convertible security_id -> terms OCF does not carry"),
    ] = None,
) -> dict[str, Any]:
    """Read an Open Cap Table Format v1.2.0 package into `securities` with its import trace.

    Refuses, naming the field, any right ovf cannot represent. The trace lists applied and
    ignored transactions, ignored fields, unread files and the conventions that set numbers.
    """
    source = _allowed_path(path, must_exist=True)
    roots = _roots()
    if roots:
        # The reader opens every *.json in a package directory to find the manifest; a
        # symlink among them must not lead outside the allowed roots.
        candidates = (
            [source] if source.is_file() else sorted(Path(path).expanduser().glob("*.json"))
        )
        for candidate in candidates:
            _require_inside(candidate.resolve(), roots, str(candidate))
    imported = import_ocf(
        source,
        participation_cap_basis=participation_cap_basis,
        ignore_common_preference_fields=ignore_common_preference_fields,
        verify_md5=verify_md5,
        note_terms=None
        if note_terms is None
        else {k: OcfNoteTerms(**v.model_dump()) for k, v in note_terms.items()},
    )
    return _merge(
        imported.model_dump(mode="json", exclude={"cap_table"}),
        {
            "securities": securities_to_specs(imported.cap_table.securities),
            "provenance": _provenance("ocf_import"),
        },
    )


@_tool("Export an OCF package", read_only=False, idempotent=False)
def ocf_export(
    securities: Securities,
    issuer: IssuerInput,
    currency: Annotated[str, Field(min_length=3, max_length=3, description="ISO 4217, e.g. USD")],
    as_of: date,
    participation_cap_basis: CapBasis,
    directory: Annotated[
        str | None,
        Field(description="Write the package here (must be new or empty); omit to return JSON"),
    ] = None,
) -> dict[str, Any]:
    """Express a cap table as an OCF v1.2.0 package; optionally write it to a new directory.

    Refuses terms OCF v1.2.0 cannot express (e.g. participating-uncapped preferred, preferred
    carrying a dividend, non-convertible debt) instead of writing a lossy package. Never
    overwrites: the directory must not exist or must be empty.
    """
    table = _table(securities)
    applied = defaults_applied(securities, table.securities)
    package = to_ocf(
        table,
        issuer=Issuer(object_type="ISSUER", **issuer.model_dump()),
        currency=currency,
        as_of=as_of,
        participation_cap_basis=participation_cap_basis,
    )
    common = {"defaults_applied": applied, "provenance": _provenance("ocf_export")}
    if directory is None:
        return {"written": False, "package": package.model_dump(mode="json"), **common}
    target = _allowed_path(directory, must_exist=False)
    manifest = write_ocf_package(package, target)
    return {
        "written": True,
        "directory": str(target),
        "manifest": str(manifest),
        "files": sorted(p.name for p in target.iterdir()),
        **common,
    }


# ------------------------------------------------------------------------- examples


README_EXAMPLE: tuple[str, list[dict[str, object]], float] = (
    "README USD 60M exit: junior capped participating Series A converts, senior Series B "
    "retains its preference",
    [
        {"type": "common", "shares": 8_000_000, "holder_id": "founders", "security_id": "common"},
        {
            "type": "preferred",
            "shares": 2_000_000,
            "price": 2.50,
            "seniority": 2,
            "participating": True,
            "participation_cap": 2.0,
            "holder_id": "series_a",
            "security_id": "series_a",
        },
        {
            "type": "preferred",
            "shares": 1_500_000,
            "price": 6.00,
            "seniority": 1,
            "holder_id": "series_b",
            "security_id": "series_b",
        },
    ],
    60_000_000,
)


@_tool("Example cap tables")
def example_cap_tables() -> dict[str, Any]:
    """The built-in example cap tables, ready to pass as `securities`.

    F1, F2, F3, F5a, F5b and F8a are the CLI demos (derivations in ovf://docs/fixtures);
    readme_60m is the README's worked example. Each comes with a suggested exit.
    """
    from ovf_mcp.specs import SECURITIES_ADAPTER

    catalogue = {**DEMOS, "readme_60m": README_EXAMPLE}
    examples = []
    for example_id, (label, raw, exit_value) in catalogue.items():
        specs = SECURITIES_ADAPTER.validate_python(raw)
        examples.append(
            {
                "id": example_id,
                "description": label,
                "suggested_exit_valuation": exit_value,
                "securities": securities_to_specs(build_securities(specs)),
            }
        )
    return {"examples": examples, "provenance": _provenance("example_cap_tables")}


# ------------------------------------------------------------------------- resources


def _docs_dir() -> Path:
    packaged = Path(__file__).with_name("docs")
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "docs"


@mcp.resource(
    "ovf://docs",
    name="ovf-docs-index",
    title="Equilibria documentation index",
    description="The calculation semantics, limitations and module documents, by URI",
    mime_type="text/markdown",
)
def docs_index() -> str:
    lines = ["# Equilibria documentation", ""]
    for name in DOC_NAMES:
        present = (_docs_dir() / f"{name}.md").is_file()
        lines.append(f"- ovf://docs/{name}" + ("" if present else " (not available here)"))
    lines += ["", "JSON Schema of the `securities` argument: ovf://schema/securities"]
    return "\n".join(lines)


@mcp.resource(
    "ovf://docs/{name}",
    name="ovf-doc",
    title="Equilibria document",
    description=f"One of: {', '.join(DOC_NAMES)}",
    mime_type="text/markdown",
)
def doc(name: str) -> str:
    path = _docs_dir() / f"{name}.md"
    if name not in DOC_NAMES or not path.is_file():
        raise ResourceNotFoundError(f"no document named {name!r}; see ovf://docs")
    return path.read_text(encoding="utf-8")


@mcp.resource(
    "ovf://schema/securities",
    name="ovf-securities-schema",
    title="Cap table input schema",
    description="JSON Schema of the `securities` argument shared by the cap table tools",
    mime_type="application/json",
)
def securities_schema() -> str:
    return json.dumps(securities_json_schema(), indent=2)


# ------------------------------------------------------------------------- prompts


@mcp.prompt(name="analyze_exit", title="Analyze an exit")
def analyze_exit(cap_table: str, exit_valuation: str) -> str:
    """Walk a cap table through an exit with verification and stated limitations."""
    return (
        "Analyze this exit with the equilibria tools.\n\n"
        f"Cap table (as described by the user):\n{cap_table}\n\n"
        f"Exit valuation: {exit_valuation}\n\n"
        "Steps:\n"
        "1. Translate the cap table into `securities`. If a term that sets a number is "
        "missing (seniority, participation and cap, liquidation multiple, dividend terms, "
        "debt dates), ask for it instead of assuming.\n"
        "2. Call cap_table_summary and confirm the preference stack with the user.\n"
        "3. Call exit_waterfall. Report payouts by holder, which classes convert, the "
        "verification block and the assumptions.\n"
        "4. Call conversion_equilibria to state whether the payout is unique.\n"
        "5. Call exit_sweep from 0 to about twice the exit to show where each class's "
        "payout changes.\n"
        "6. Read ovf://docs/limitations and name anything in the user's situation it lists."
    )


@mcp.prompt(name="safe_round_to_exit", title="SAFE round, then an exit")
def safe_round_to_exit(round_terms: str, exit_valuation: str) -> str:
    """Resolve SAFEs in a priced round, then follow the post-round table to an exit."""
    return (
        "Model this financing and exit with the equilibria tools.\n\n"
        f"Round terms (as described by the user):\n{round_terms}\n\n"
        f"Exit valuation: {exit_valuation}\n\n"
        "Steps:\n"
        "1. Confirm prior common shares, new money, pre-money, the new pool target and each "
        "SAFE's amount, cap, discount and form (post- or pre-money). Do not mix forms.\n"
        "2. Call safe_priced_round and report ownership by holder and each SAFE's conversion "
        "price and binding term.\n"
        "3. Pass its post_round_securities to exit_waterfall and report the payouts.\n"
        "4. State the capitalization convention used and the limitations that apply."
    )


# ------------------------------------------------------------------------- entry point


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ovf-mcp", description="Equilibria / OVF Model Context Protocol server"
    )
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--version", action="version", version=f"ovf-mcp {__version__}")
    args = parser.parse_args(argv)
    # stdout carries the protocol on stdio; every log line goes to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
