"""Option Pricing Method: breakpoints, allocation, backsolve and marketability discounts.

The Option Pricing Method treats total equity value as lognormal at an assumed liquidity
date and each share class's claim on it as a portfolio of call spreads struck at the
**breakpoints** of the exit waterfall. Its arithmetic needs four properties of the payoff:
continuity, piecewise linearity, monotonicity, and marginal weights that are non-negative
and sum to one. Practice treats those as facts about cap tables. They are assumptions about
a particular cap table, and this package's reason to exist is that it checks them.

`breakpoint_schedule` derives the breakpoints from the verified waterfall engine rather
than from a hand-built table, then proves the derivation by replaying it against the engine
either side of every candidate. `opm_allocate` refuses, rather than returning a number,
when a property fails. The refusal that matters most is continuity: under a Requisite
Holders mandatory conversion the payoff **steps**, and no combination of call spreads in
any weights reproduces a step, so the payoff is not in the span of the instruments the
method decomposes into. See `docs/opm-breakpoints.md` and `docs/governance.md`.

`backsolve` calibrates total equity value to an observed transaction price, verifying that
the target's value is strictly increasing across the bracket rather than assuming it.

`ovf.opm.dlom` holds four published marketability discounts as four separate estimators.
There is no default method and no average across them: simulating the payoffs they each
claim to price shows they disagree by more than the inputs move any one of them, and
`docs/dlom.md` reports that disagreement as the finding it is.

Nothing here claims conformance with any valuation standard or with 409A. The formulas are
implemented as published; whether a given method is a reasonable application to a given
company is a judgment this package does not make.
"""

from __future__ import annotations

from ovf.opm.allocate import opm_allocate

# `backsolve` is DELIBERATELY not imported here. `ovf.opm.backsolve` is a submodule, and
# binding the function of the same name over it would shadow the module: after the shadow,
# both `import ovf.opm.backsolve as m` and `from ovf.opm import backsolve` return the
# function, and nothing can reach the module by its own name. The function is reachable as
# `ovf.backsolve`, where no module competes for the name, and canonically as
# `ovf.opm.backsolve.backsolve`. Do not "tidy" this by adding the import back.
from ovf.opm.blackscholes import call_value, normal_cdf
from ovf.opm.breakpoints import breakpoint_schedule
from ovf.opm.dlom import (
    DLOM_METHODS,
    chaffe_dlom,
    dlom_comparison,
    finnerty_dlom,
    ghaidarov_dlom,
    longstaff_dlom,
)
from ovf.opm.types import (
    BacksolveError,
    BacksolveResult,
    Breakpoint,
    BreakpointError,
    BreakpointSchedule,
    ClassValue,
    Discontinuity,
    DlomEstimate,
    OpmAssumptionError,
    OpmError,
    OpmInputs,
    OpmResult,
    Tranche,
)

__all__ = [
    "DLOM_METHODS",
    "BacksolveError",
    "BacksolveResult",
    "Breakpoint",
    "BreakpointError",
    "BreakpointSchedule",
    "ClassValue",
    "Discontinuity",
    "DlomEstimate",
    "OpmAssumptionError",
    "OpmError",
    "OpmInputs",
    "OpmResult",
    "Tranche",
    "breakpoint_schedule",
    "call_value",
    "chaffe_dlom",
    "dlom_comparison",
    "finnerty_dlom",
    "ghaidarov_dlom",
    "longstaff_dlom",
    "normal_cdf",
    "opm_allocate",
]
