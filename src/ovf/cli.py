"""Command-line demo for the exit waterfall and SAFE round solvers.

Every subcommand prints the assumptions the result depends on. The CLI is a
demonstration surface for the documented scope in ``docs/semantics.md``; it adds
no modelling of its own.

    python -m ovf waterfall --demo F5b
    python -m ovf waterfall --file table.json --exit 35000000
    python -m ovf sweep --demo F8a --to 40000000
    python -m ovf equilibria --demo F3
    python -m ovf safe --prior-common 8000000 --new-money 3000000 \\
        --pre-money 12000000 --pool 0.10 --safe 1000000:10000000:angel
    python -m ovf pme report --flows examples/pme/flows.csv --sign-convention typed \\
        --index examples/pme/index.csv --benchmark-name "GGS index" \\
        --return-basis total_return_gross --nav-value 75 --nav-date 2010-12-31 \\
        --as-of 2010-12-31 --name "GGS fund" --currency USD --basis net_lp \\
        --stale-nav refuse --day-count ACT/365F --lookup exact --max-gap-days 0
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import get_args

import ovf
from ovf.contracts.securities import Security
from ovf.pme.benchmark import BenchmarkIndex, IndexLookup, ReturnBasis
from ovf.pme.daycount import DayCountConvention
from ovf.pme.flows import FlowBasis, FundCashFlows, NavObservation, StaleNavPolicy
from ovf.pme.io import SignConvention, parse_iso_date, read_flows_csv, read_index_csv, read_nav_csv
from ovf.pme.mpme import FundNavHistory, InterimNavPolicy
from ovf.pme.report import pme_report

DEMOS: dict[str, tuple[str, list[dict[str, object]], float]] = {
    "F1": (
        "1x non-participating above the conversion threshold",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        35_000_000,
    ),
    "F2": (
        "1x non-participating below the conversion threshold",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        15_000_000,
    ),
    "F3": (
        "exact conversion indifference point: two equilibria, one payout",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        25_000_000,
    ),
    "F5a": (
        "participation cap binds",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "participating": True,
                "participation_cap": 2.0,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        40_000_000,
    ),
    "F5b": (
        "cap makes conversion the better action",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "participating": True,
                "participation_cap": 2.0,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        60_000_000,
    ),
    "F8a": (
        "stacked seniority; common receives nothing up to $14M of preference",
        [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.50,
                "seniority": 2,
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
        14_000_000,
    ),
}


def build_security(spec: dict[str, object]) -> Security:
    kind = str(spec.get("type", "")).lower()
    data = {k: v for k, v in spec.items() if k != "type"}
    if kind == "common":
        return ovf.common(**data)  # type: ignore[arg-type]
    if kind == "preferred":
        return ovf.preferred(**data)  # type: ignore[arg-type]
    if kind in ("pool", "option_pool"):
        return ovf.option_pool(**data)  # type: ignore[arg-type]
    raise SystemExit(f"Unknown security type {spec.get('type')!r}; use common, preferred or pool")


def load_table(args: argparse.Namespace) -> tuple[list[Security], float, str]:
    if args.demo:
        if args.demo not in DEMOS:
            raise SystemExit(f"Unknown demo {args.demo!r}; choose from {', '.join(DEMOS)}")
        label, specs, default_exit = DEMOS[args.demo]
        return [build_security(s) for s in specs], default_exit, f"demo {args.demo}: {label}"
    if not args.file:
        raise SystemExit("Provide --file with a cap table JSON document, or --demo")
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    specs = payload["securities"] if isinstance(payload, dict) else payload
    return [build_security(s) for s in specs], 0.0, str(args.file)


def money(value: float) -> str:
    return f"${value:>16,.2f}"


def price(value: float) -> str:
    """Per-share amounts need more precision than cash totals."""
    return f"${value:,.6f}".rstrip("0").rstrip(".")


def print_assumptions(lines: Sequence[str]) -> None:
    print("\nAssumptions")
    for line in lines:
        print(f"  - {line}")


def cmd_waterfall(args: argparse.Namespace) -> int:
    securities, default_exit, source = load_table(args)
    exit_value = args.exit if args.exit is not None else default_exit
    report = ovf.CapTable(securities=securities).waterfall_detailed(
        exit_value, args.costs, as_of=args.as_of
    )
    print(f"Source            {source}")
    print(f"Gross exit        {money(report.gross_exit)}")
    print(f"Transaction costs {money(report.transaction_costs)}")
    print(f"Net proceeds      {money(report.net_exit)}\n")
    width = max(len(p.security_id) for p in report.payouts)
    print(f"{'position':<{width}}  {'cash':>17}  {'of proceeds':>11}  converted  multiple")
    for payout in report.payouts:
        multiple = "-" if payout.effective_multiple is None else f"{payout.effective_multiple:.2f}x"
        print(
            f"{payout.security_id:<{width}}  {money(payout.amount)}  "
            f"{payout.payout_pct:>10.2%}  {str(payout.converted):>9}  {multiple:>8}"
        )
    print(
        f"\nVerified equilibrium: {report.converged}  "
        f"(max unilateral gain {report.max_unilateral_gain:.2e}, "
        f"tolerance {report.tolerance:.2e}, sweeps {report.iterations})"
    )
    print(f"Conservation error:   {report.conservation_error:.2e}")
    print(f"Input fingerprint:    {report.input_hash[:16]}  engine {report.engine_version}")
    if report.multi_position_holders:
        print(
            "Note: these holders own several preferred positions, so the independent"
            f"-position assumption is weakest for them: {', '.join(report.multi_position_holders)}"
        )
    print_assumptions(report.assumptions)
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    securities, default_exit, source = load_table(args)
    upper = args.to if args.to is not None else max(default_exit * 3, 1.0)
    lower = args.from_
    steps = max(args.steps, 2)
    table = ovf.CapTable(securities=securities)
    ids = [s.security_id for s in securities]
    width = max(len(i) for i in ids)
    print(f"Source  {source}")
    print(f"Sweep   {money(lower)} to {money(upper)} in {steps} steps\n")
    print(f"{'exit':>17}  " + "  ".join(f"{i:>{max(width, 12)}}" for i in ids) + "   common share")
    dead_zone_top = None
    for step in range(steps):
        exit_value = lower + (upper - lower) * step / (steps - 1)
        payouts = {p.security_id: p for p in table.waterfall(exit_value, as_of=args.as_of)}
        cells = "  ".join(f"{payouts[i].amount:>{max(width, 12)},.0f}" for i in ids)
        common_ids = [s.security_id for s in securities if isinstance(s, ovf.CommonStock)]
        common_cash = sum(payouts[i].amount for i in common_ids)
        share = common_cash / exit_value if exit_value else 0.0
        if common_cash <= 1e-9:
            dead_zone_top = exit_value
        bar = "#" * int(round(share * 20))
        print(f"{money(exit_value)}  {cells}   {share:>6.1%} {bar}")
    if dead_zone_top is not None:
        print(
            f"\nCommon holders received nothing at every sampled exit up to {money(dead_zone_top)}."
        )
    print_assumptions(
        [
            "Each sampled exit is solved independently; no path dependence is modeled.",
            "The sweep grid may step over a breakpoint; refine --steps near a kink.",
        ]
    )
    return 0


def cmd_equilibria(args: argparse.Namespace) -> int:
    securities, default_exit, source = load_table(args)
    exit_value = args.exit if args.exit is not None else default_exit
    survey = ovf.enumerate_equilibria(securities, exit_value, args.costs, as_of=args.as_of)
    print(f"Source              {source}")
    print(f"Net proceeds        {money(survey.net_exit)}")
    print(f"Preferred positions {len(survey.positions)} -> {survey.states_evaluated} profiles")
    print(f"Pure equilibria     {len(survey.equilibria)}")
    print(f"Fully allocating    {len(survey.feasible_equilibria)}")
    print(f"Distinct payouts    {survey.distinct_payoff_vectors}")
    print(f"Payout unique       {survey.payoff_unique}\n")
    for profile, payoff in zip(survey.feasible_equilibria, survey.feasible_payoffs, strict=True):
        converted = ", ".join(f"{k}={'convert' if v else 'preference'}" for k, v in profile.items())
        amounts = ", ".join(f"{k}={v:,.0f}" for k, v in payoff.items())
        print(f"  [{converted}]  ->  {amounts}")
    print_assumptions(
        [
            "Enumeration is exhaustive over 2**n conversion profiles.",
            "A profile is reported only if it allocates the whole net exit.",
            "Several profiles paying identical amounts is common and is not an error.",
        ]
    )
    return 0


def cmd_safe(args: argparse.Namespace) -> int:
    instruments = []
    factory = ovf.safe_post if args.method == "post_money_yc" else ovf.safe_pre
    for index, raw in enumerate(args.safe or []):
        parts = raw.split(":")
        if len(parts) not in (2, 3):
            raise SystemExit(f"--safe expects amount:cap[:holder], received {raw!r}")
        amount, cap = float(parts[0]), float(parts[1])
        holder = parts[2] if len(parts) == 3 else f"safe_{index + 1}"
        instruments.append(factory(amount=amount, cap=cap, holder_id=holder))
    result = ovf.solve_priced_round_with_safes(
        prior_common_shares=args.prior_common,
        new_money=args.new_money,
        pre_money_valuation=args.pre_money,
        target_pool_pct=args.pool,
        safes=instruments,
        method=args.method,
    )
    print(f"Method              {result.method}")
    print(f"Pre-money           {money(result.pre_money_valuation)}")
    print(f"New money           {money(result.new_money_invested)}")
    print(f"Post-money          {money(result.post_money_valuation)}")
    print(f"Round share price   {price(result.share_price)}")
    print(f"Post-round shares   {result.total_post_shares:,.4f}\n")
    width = max(len(h) for h in result.ownership_breakdown)
    print(f"{'holder':<{width}}  ownership")
    for holder, fraction in result.ownership_breakdown.items():
        print(f"{holder:<{width}}  {fraction:>8.4%}")
    if result.safe_conversion_prices:
        print("\nSAFE conversion")
        for security_id, conversion in result.safe_conversion_prices.items():
            shares = result.safe_shares[security_id]
            print(f"  {security_id}: {shares:,.4f} shares at {price(conversion)}")
    print(f"\nShare conservation error {result.share_balance_error:.2e}")
    print(f"Input fingerprint        {result.input_hash[:16]}  engine {result.engine_version}")
    print_assumptions(result.assumptions)
    return 0


PME_REPORT_COLUMNS = """\
CSV files (UTF-8) use these fixed headers on line 1; extra columns are ignored, but a
header name may appear only once:
  --flows, --sign-convention typed      date,kind,amount
                                        kind is contribution or distribution; amount > 0
  --flows, --sign-convention signed_lp  date,amount
                                        negative = contribution (paid in by the LP),
                                        positive = distribution (received by the LP)
  --index                               date,level
  --nav-history                         date,value
Dates are ISO YYYY-MM-DD. A zero amount, an unterminated quote and every malformed row
are refused with the file and line (exit code 2). Every convention flag is required; none
has a default. The index is taken to be in --currency (there is no FX).
"""


def _cli_date(text: str) -> date:
    try:
        return parse_iso_date(text, what="date")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def cmd_pme_report(args: argparse.Namespace) -> int:
    # The loaders refuse every unreadable or malformed file with a ValueError naming the
    # file and line, which main() turns into exit code 2.
    sign: SignConvention = args.sign_convention
    flows = read_flows_csv(
        args.flows,
        date_column="date",
        amount_column="amount",
        kind_column="kind" if sign == "typed" else None,
        sign_convention=sign,
    )
    levels = read_index_csv(args.index, date_column="date", level_column="level")
    history = None
    if args.nav_history is not None:
        observations = read_nav_csv(args.nav_history, date_column="date", value_column="value")
        history = FundNavHistory(observations=observations)
    fund = FundCashFlows(
        name=args.name,
        currency=args.currency,
        basis=args.basis,
        flows=flows,
        nav=NavObservation(date=args.nav_date, value=args.nav_value),
    )
    benchmark = BenchmarkIndex(
        name=args.benchmark_name,
        currency=args.currency,
        return_basis=args.return_basis,
        levels=levels,
    )
    report = pme_report(
        fund,
        benchmark,
        as_of=args.as_of,
        stale_nav=args.stale_nav,
        day_count=args.day_count,
        lookup=args.lookup,
        max_gap_days=args.max_gap_days,
        nav_history=history,
        interim_nav=args.interim_nav,
        max_nav_gap_days=args.max_nav_gap_days,
    )
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(report.to_text())
    return 0


def add_pme_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    pme = sub.add_parser("pme", help="private-market performance: multiples, IRR and PMEs")
    pme_sub = pme.add_subparsers(dest="pme_command", required=True)
    report = pme_sub.add_parser(
        "report",
        help="every open-pme metric for one fund and one benchmark",
        description="Resolve the fund once and report the multiples, the fund IRR, "
        "KS-PME, Direct Alpha, PME+, the Long-Nickels ICM and (with --nav-history) the "
        "mPME, with flags and de-duplicated assumptions.",
        epilog=PME_REPORT_COLUMNS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report.add_argument("--flows", required=True, help="flows CSV (headers below)")
    report.add_argument(
        "--sign-convention",
        required=True,
        choices=get_args(SignConvention),
        help="how the flows file encodes contributions and distributions",
    )
    report.add_argument("--index", required=True, help="benchmark CSV: date,level")
    report.add_argument("--benchmark-name", required=True)
    report.add_argument("--return-basis", required=True, choices=get_args(ReturnBasis))
    report.add_argument(
        "--nav-value", required=True, type=float, help="the fund's NAV (residual value)"
    )
    report.add_argument(
        "--nav-date", required=True, type=_cli_date, help="date of the NAV (YYYY-MM-DD)"
    )
    report.add_argument(
        "--as-of",
        required=True,
        type=_cli_date,
        help="valuation date (YYYY-MM-DD); no clock is read",
    )
    report.add_argument("--name", required=True, help="fund name")
    report.add_argument("--currency", required=True, help="fund and benchmark currency")
    report.add_argument("--basis", required=True, choices=get_args(FlowBasis))
    report.add_argument("--stale-nav", required=True, choices=get_args(StaleNavPolicy))
    report.add_argument("--day-count", required=True, choices=get_args(DayCountConvention))
    report.add_argument("--lookup", required=True, choices=get_args(IndexLookup))
    report.add_argument(
        "--max-gap-days",
        required=True,
        type=int,
        help="largest index-level gap in days (0 with --lookup exact)",
    )
    report.add_argument("--nav-history", help="interim NAV CSV (date,value); enables the mPME")
    report.add_argument(
        "--interim-nav", choices=get_args(InterimNavPolicy), help="required with --nav-history"
    )
    report.add_argument("--max-nav-gap-days", type=int, help="required with --nav-history")
    report.add_argument("--json", action="store_true", help="print the report as JSON")
    report.set_defaults(func=cmd_pme_report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ovf",
        description="Exit waterfall, SAFE round and private-market performance (PME) "
        "demonstrations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_table_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--file", help="cap table JSON document")
        target.add_argument("--demo", help=f"built-in case: {', '.join(DEMOS)}")
        target.add_argument("--costs", type=float, default=0.0, help="transaction costs")
        target.add_argument(
            "--as-of",
            dest="as_of",
            type=date.fromisoformat,
            help="settlement date (YYYY-MM-DD), required when the table holds debt or an "
            "accruing dividend; no clock is ever read",
        )

    waterfall = sub.add_parser("waterfall", help="allocate one exit")
    add_table_args(waterfall)
    waterfall.add_argument("--exit", type=float, help="exit valuation")
    waterfall.set_defaults(func=cmd_waterfall)

    sweep = sub.add_parser("sweep", help="allocate a range of exits")
    add_table_args(sweep)
    sweep.add_argument("--from", dest="from_", type=float, default=0.0)
    sweep.add_argument("--to", type=float)
    sweep.add_argument("--steps", type=int, default=15)
    sweep.set_defaults(func=cmd_sweep)

    survey = sub.add_parser("equilibria", help="enumerate every conversion equilibrium")
    add_table_args(survey)
    survey.add_argument("--exit", type=float, help="exit valuation")
    survey.set_defaults(func=cmd_equilibria)

    safe = sub.add_parser("safe", help="solve a priced round with SAFEs")
    safe.add_argument("--prior-common", type=float, required=True)
    safe.add_argument("--new-money", type=float, required=True)
    safe.add_argument("--pre-money", type=float, required=True)
    safe.add_argument("--pool", type=float, default=0.0, help="post-round pool fraction")
    safe.add_argument("--safe", action="append", metavar="AMOUNT:CAP[:HOLDER]", help="repeatable")
    safe.add_argument("--method", choices=["post_money_yc", "pre_money"], default="post_money_yc")
    safe.set_defaults(func=cmd_safe)
    add_pme_parser(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except (ValueError, ovf.WaterfallConvergenceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
