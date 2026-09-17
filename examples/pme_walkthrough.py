#!/usr/bin/env python3
"""open-pme walkthrough: Gredil, Griffiths & Stucke (2014), Exhibits 5-6, end to end.

Reads the exhibit's displayed inputs from ``examples/pme/`` (``flows.csv``,
``index.csv``), builds the fund and the benchmark, runs every open-pme metric with
``pme_report`` and prints the report. It then checks the numbers against the published
display: TVPI 2.00, KS-PME 1.67, IRR 17.5% and Direct Alpha 12.6%. It also checks that
the Long-Nickels ICM series has two roots, -27.26% and +5.97% (the paper shows only the
+6.0% one), and that the index position goes short on 2007-12-31. The exit code is 1 on
any mismatch.

The same report from the command line:

    python -m ovf pme report --flows examples/pme/flows.csv --sign-convention typed \\
        --index examples/pme/index.csv --benchmark-name "GGS 2014 Exhibit 5 index" \\
        --return-basis total_return_gross --nav-value 75 --nav-date 2010-12-31 \\
        --as-of 2010-12-31 --name "GGS 2014 Exhibit 5 fund" --currency USD \\
        --basis net_lp --stale-nav refuse --day-count ACT/365F --lookup exact \\
        --max-gap-days 0
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ovf.pme.benchmark import BenchmarkIndex
from ovf.pme.flows import FundCashFlows, NavObservation
from ovf.pme.io import read_flows_csv, read_index_csv
from ovf.pme.report import PmeReport, Refusal, pme_report

DATA = Path(__file__).resolve().parent / "pme"
AS_OF = date(2010, 12, 31)


def build_report() -> PmeReport:
    """The GGS 2014 Exhibit 5 fund against its index, every policy stated."""
    fund = FundCashFlows(
        name="GGS 2014 Exhibit 5 fund",
        currency="USD",
        basis="net_lp",
        flows=read_flows_csv(
            DATA / "flows.csv",
            date_column="date",
            amount_column="amount",
            kind_column="kind",
            sign_convention="typed",
        ),
        nav=NavObservation(date=AS_OF, value=75.0),
    )
    index = BenchmarkIndex(
        name="GGS 2014 Exhibit 5 index",
        currency="USD",
        return_basis="total_return_gross",
        levels=read_index_csv(DATA / "index.csv", date_column="date", level_column="level"),
    )
    return pme_report(
        fund,
        index,
        as_of=AS_OF,
        stale_nav="refuse",
        day_count="ACT/365F",
        lookup="exact",
        max_gap_days=0,
        nav_history=None,
        interim_nav=None,
        max_nav_gap_days=None,
    )


def published_checks(report: PmeReport) -> list[tuple[str, str, str]]:
    """``(what, published, reproduced)`` at the precision of the published display."""
    m, irr, ks, da, icm = (
        report.multiples,
        report.fund_irr,
        report.ks_pme,
        report.direct_alpha,
        report.ln_pme,
    )
    if any(isinstance(slot, Refusal) for slot in (m, irr, ks, da, icm)):
        raise SystemExit("a method refused; see the report above")
    assert not isinstance(m, Refusal) and not isinstance(irr, Refusal)
    assert not isinstance(ks, Refusal) and not isinstance(da, Refusal)
    assert not isinstance(icm, Refusal)
    tvpi = "n/a" if m.tvpi is None else f"{m.tvpi:.2f}"
    rate = "n/a" if irr.irr is None else f"{irr.irr:.1%}"
    alpha = "n/a" if da.alpha_annual_effective is None else f"{da.alpha_annual_effective:.1%}"
    roots = ", ".join(f"{root.rate:+.2%}" for root in icm.icm_irr.roots)
    short = "never" if icm.first_short_date is None else icm.first_short_date.isoformat()
    return [
        ("TVPI", "2.00", tvpi),
        ("KS-PME", "1.67", f"{ks.ks_pme:.2f}"),
        ("IRR", "17.5%", rate),
        ("Direct Alpha", "12.6%", alpha),
        ("ICM status", "multiple", icm.icm_irr.status),
        ("ICM roots", "-27.26%, +5.97%", roots),
        ("ICM short on", "2007-12-31", short),
    ]


def main() -> int:
    report = build_report()
    print(report.to_text())
    print("\nGGS 2014 Exhibits 5-6: published display vs reproduced")
    mismatches = 0
    for what, published, reproduced in published_checks(report):
        verdict = "ok" if published == reproduced else "MISMATCH"
        mismatches += verdict != "ok"
        print(f"  {what:<14} {published:>16}  {reproduced:>16}  {verdict}")
    print("  (the paper shows the ICM's +6.0% root only; the series has two)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
