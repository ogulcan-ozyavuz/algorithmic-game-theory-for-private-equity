"""Fund multiples from resolved flows: DPI, RVPI and TVPI.

Multiples use gross sums, not per-date nets: ``paid_in`` is every contribution and
``distributed`` every distribution, as ``resolve`` reports them. They ignore timing, so
they need no day count and no benchmark. An undefined ratio is ``None`` with an
assumption line saying why; nothing here returns NaN or infinity. A sum or ratio outside
the float range is refused with ``ValueError`` naming it.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import ConfigDict

from ovf.core.types import FinancialBaseModel
from ovf.pme.flows import (
    ENGINE_VERSION,
    NavSource,
    PlainDate,
    ResolvedCashFlows,
    canonical_hash,
    finite_fsum,
    finite_ratio,
)

GROSS_LEGS_ASSUMPTION = (
    "Gross legs: every contribution counts in paid-in (and in FV(C)) and every distribution "
    "in distributed (and in FV(D)), so a distribution re-called on the same or a later date "
    "counts in both paid-in and distributed; netting recallables gives different "
    "TVPI/KS-PME/PME+. A recallable policy is not modelled in pme-v1."
)


class Multiples(FinancialBaseModel):
    """DPI, RVPI and TVPI at ``as_of`` with the inputs that produced them.

    ``identity_residual`` is ``tvpi - (dpi + rvpi)``: zero in exact arithmetic, reported
    so float rounding is visible. It is ``None`` whenever one of the three is ``None``.
    """

    model_config = ConfigDict(frozen=True)

    as_of: PlainDate
    paid_in: float
    distributed: float
    residual_value: float | None
    nav_source: NavSource
    dpi: float | None
    rvpi: float | None
    tvpi: float | None
    identity_residual: float | None
    assumptions: list[str]
    input_hash: str
    engine_version: str = ENGINE_VERSION


def resolved_payload(resolved: ResolvedCashFlows) -> dict[str, Any]:
    """Canonical JSON-ready content of ``resolved`` for a metric's ``input_hash``.

    ``resolve`` stores flows in canonical order (date, contributions first, amount,
    ``flow_id``), so the payload, and every hash built on it, does not depend on input
    order. Dates are ISO strings.
    """
    return {
        "fund_name": resolved.fund_name,
        "currency": resolved.currency,
        "basis": resolved.basis,
        "as_of": resolved.as_of.isoformat(),
        "flows": [flow.model_dump(mode="json") for flow in resolved.flows],
        "residual_value": resolved.residual_value,
        "nav_source": resolved.nav_source,
        "nav_roll_forward": (
            None
            if resolved.nav_roll_forward is None
            else resolved.nav_roll_forward.model_dump(mode="json")
        ),
    }


def multiples(resolved: ResolvedCashFlows) -> Multiples:
    """DPI, RVPI and TVPI of ``resolved`` at its ``as_of``.

    ``dpi = distributed / paid_in``, ``rvpi = residual_value / paid_in`` and
    ``tvpi = (distributed + residual_value) / paid_in``. With ``paid_in == 0`` (a
    distributions-only series) all three are ``None``; with no residual value only
    ``dpi`` is reported. The result's assumptions start with the resolved flows' own
    (perspective, basis, currency, NAV source). Raises ``ValueError`` when a sum or ratio
    overflows the float range or a non-zero ratio underflows it.
    """
    if not isinstance(resolved, ResolvedCashFlows):
        raise ValueError(
            f"resolved must be a ResolvedCashFlows (from ovf.pme.flows.resolve), got "
            f"{type(resolved).__name__}"
        )
    paid_in = resolved.paid_in
    distributed = resolved.distributed
    residual = resolved.residual_value
    assumptions = [
        *resolved.assumptions,
        "Multiples use gross sums of contributions and distributions; timing is ignored.",
        GROSS_LEGS_ASSUMPTION,
    ]
    dpi: float | None = None
    rvpi: float | None = None
    tvpi: float | None = None
    if paid_in == 0:
        assumptions.append(
            "Paid-in capital is zero (no contributions), so DPI, RVPI and TVPI are "
            "undefined and reported as None."
        )
    else:
        dpi = finite_ratio(distributed, paid_in, what="DPI = distributed / paid_in")
        if residual is None:
            assumptions.append(
                "No residual value, so RVPI and TVPI are undefined and reported as None; "
                "DPI is still reported."
            )
        else:
            rvpi = finite_ratio(residual, paid_in, what="RVPI = residual value / paid_in")
            total = distributed + residual
            if math.isfinite(total):
                tvpi = finite_ratio(
                    total, paid_in, what="TVPI = (distributed + residual) / paid_in"
                )
            else:
                # The sum overflows, but TVPI may still be representable term by term.
                tvpi = finite_fsum((dpi, rvpi), what="TVPI = DPI + RVPI")
                assumptions.append(
                    "distributed + residual value overflows the float range, so TVPI was "
                    "computed term by term as DPI + RVPI."
                )
    identity = None if tvpi is None or dpi is None or rvpi is None else tvpi - (dpi + rvpi)
    return Multiples(
        as_of=resolved.as_of,
        paid_in=paid_in,
        distributed=distributed,
        residual_value=residual,
        nav_source=resolved.nav_source,
        dpi=dpi,
        rvpi=rvpi,
        tvpi=tvpi,
        identity_residual=identity,
        assumptions=assumptions,
        input_hash=canonical_hash({"method": "multiples", "resolved": resolved_payload(resolved)}),
    )
