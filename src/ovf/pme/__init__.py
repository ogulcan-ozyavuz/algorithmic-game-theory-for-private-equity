"""open-pme: dated fund cash-flow metrics and public-market comparison.

Signed dated flows, TVPI/DPI/RVPI, a certified XIRR root policy, KS-PME, Direct Alpha,
PME+, the Long-Nickels index comparison and a labelled mPME reconstruction, with a
one-call report and strict CSV loaders. Conventions are in ``docs/pme.md``.
"""

from ovf.pme.benchmark import (
    BenchmarkIndex,
    IndexLevel,
    IndexLookup,
    IndexLookupRecord,
    ReturnBasis,
    index_level,
)
from ovf.pme.daycount import DayCountConvention, year_fraction
from ovf.pme.flows import (
    ENGINE_VERSION,
    CashFlow,
    DatedAmount,
    FlowBasis,
    FlowKind,
    FundCashFlows,
    NavObservation,
    NavRollForward,
    NavSource,
    ResolvedCashFlows,
    StaleNavPolicy,
    resolve,
)
from ovf.pme.io import SignConvention, read_flows_csv, read_index_csv, read_nav_csv
from ovf.pme.irr import (
    TOLERANCE,
    IrrResult,
    IrrRoot,
    IrrStatus,
    fund_irr,
    npv,
    npv_at_log_rate,
    xirr,
)
from ovf.pme.metrics import Multiples, multiples
from ovf.pme.mpme import FundNavHistory, InterimNavPolicy, MpmeResult, MpmeStep, mpme
from ovf.pme.pme import (
    DirectAlphaResult,
    FlowValuation,
    IcmStep,
    KsPmeResult,
    LnPmeResult,
    PmePlusResult,
    direct_alpha,
    ks_pme,
    ln_pme,
    pme_plus,
)
from ovf.pme.report import PmeReport, Refusal, ReportFlag, pme_report

__all__ = [
    "ENGINE_VERSION",
    # Inputs and their resolution at a date (ovf.pme.flows, ovf.pme.daycount)
    "CashFlow",
    "NavObservation",
    "DatedAmount",
    "FundCashFlows",
    "FlowKind",
    "FlowBasis",
    "StaleNavPolicy",
    "NavSource",
    "NavRollForward",
    "ResolvedCashFlows",
    "resolve",
    "DayCountConvention",
    "year_fraction",
    # Certified IRR (ovf.pme.irr)
    "TOLERANCE",
    "IrrStatus",
    "IrrRoot",
    "IrrResult",
    "npv",
    "npv_at_log_rate",
    "xirr",
    "fund_irr",
    # Multiples (ovf.pme.metrics)
    "Multiples",
    "multiples",
    # Benchmark index (ovf.pme.benchmark)
    "ReturnBasis",
    "IndexLookup",
    "IndexLevel",
    "BenchmarkIndex",
    "IndexLookupRecord",
    "index_level",
    # Public-market equivalents (ovf.pme.pme, ovf.pme.mpme)
    "FlowValuation",
    "KsPmeResult",
    "DirectAlphaResult",
    "PmePlusResult",
    "IcmStep",
    "LnPmeResult",
    "ks_pme",
    "direct_alpha",
    "pme_plus",
    "ln_pme",
    "FundNavHistory",
    "InterimNavPolicy",
    "MpmeStep",
    "MpmeResult",
    "mpme",
    # One-call report and CSV loaders (ovf.pme.report, ovf.pme.io)
    "Refusal",
    "ReportFlag",
    "PmeReport",
    "pme_report",
    "SignConvention",
    "read_flows_csv",
    "read_index_csv",
    "read_nav_csv",
]
