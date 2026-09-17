"""One call, one report: every open-pme metric for a fund and a benchmark.

``pme_report`` resolves the fund once and runs the multiples, the fund IRR, KS-PME, Direct
Alpha, PME+, the Long–Nickels ICM and, when a NAV history is given, the mPME. Each
method's slot holds its result, or a ``Refusal`` carrying the ``ValueError`` message when
that method refused: one refusal never removes the others. Only ``ValueError`` (the
library's refusal type) is caught; any other exception is a bug and propagates. A refusal
of ``resolve`` itself (flows after ``as_of``, a stale NAV under ``"refuse"``) refuses the
whole report, since no method can run without resolved flows.

The report adds no arithmetic of its own. It gathers machine-readable ``flags`` (a
price-return benchmark, a rolled-forward NAV, stale index levels, IRRs that are not
unique or whose rate is clamped, PME+ with ``s < 0``, a short ICM position, stated or
computed nets dropped as noise, refused methods), splits the results' assumption lines
into the lines shared by several results and the lines specific to one, and renders
plain text (``to_text``) or one row per metric (``to_rows``, for CSV). Every policy is
keyword-only with no default.

The fund IRR is solved once for the ``fund_irr`` slot; ``pme_plus``, ``ln_pme`` and
``mpme`` solve the same deterministic series again internally and carry an identical
result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Literal, TypeVar

from pydantic import ConfigDict

from ovf.core.types import FinancialBaseModel
from ovf.pme.benchmark import BenchmarkIndex, IndexLookup, ReturnBasis, benchmark_assumptions
from ovf.pme.daycount import DayCountConvention, check_convention
from ovf.pme.flows import (
    ENGINE_VERSION,
    FlowBasis,
    FundCashFlows,
    NavSource,
    PlainDate,
    ResolvedCashFlows,
    StaleNavPolicy,
    canonical_hash,
    resolve,
)
from ovf.pme.irr import IrrResult, fund_irr
from ovf.pme.metrics import Multiples, multiples
from ovf.pme.mpme import (
    FundNavHistory,
    InterimNavPolicy,
    MpmeResult,
    check_interim_policy,
    mpme,
)
from ovf.pme.pme import (
    DirectAlphaResult,
    KsPmeResult,
    LnPmeResult,
    PmePlusResult,
    PmeResultBase,
    direct_alpha,
    ks_pme,
    ln_pme,
    pme_plus,
)

MethodName = Literal[
    "multiples", "fund_irr", "ks_pme", "direct_alpha", "pme_plus", "ln_pme", "mpme"
]

ReportFlagCode = Literal[
    "PRICE_RETURN",
    "NAV_ROLLED_FORWARD",
    "INDEX_STALE",
    "IRR_NOT_UNIQUE",
    "RATE_CLAMPED",
    "PME_PLUS_NEGATIVE_SCALE",
    "ICM_WENT_SHORT",
    "STATED_NET_WITHIN_REPRESENTATION_NOISE",
    "COMPUTED_NET_DROPPED",
    "METHOD_REFUSED",
]

METHOD_LABELS: dict[str, str] = {
    "multiples": "Multiples",
    "fund_irr": "Fund IRR",
    "ks_pme": "KS-PME",
    "direct_alpha": "Direct Alpha",
    "pme_plus": "PME+",
    "ln_pme": "ICM",
    "mpme": "mPME",
}

ROW_COLUMNS = (
    "method",
    "metric",
    "value",
    "available",
    "reason",
    "irr_status",
    "rate_clamped",
    "log_rate",
    "note",
)
"""The keys of every ``PmeReport.to_rows()`` row, in CSV column order."""

_T = TypeVar("_T")


class Refusal(FinancialBaseModel):
    """A method that refused, with the ``ValueError`` message it raised."""

    model_config = ConfigDict(frozen=True)

    method: MethodName
    reason: str


class ReportFlag(FinancialBaseModel):
    """A machine-readable warning: a code, the method it concerns, a message and a number.

    ``method`` is ``None`` for a property of the inputs (the benchmark's return basis, the
    NAV source, stated nets). ``value`` is the number behind the flag when there is one
    (``I_T / I_navdate``, the largest lookup gap in days, ``s``, the minimum ICM position,
    a clamped root's ``log_rate``, a raw stated net), else ``None``.
    """

    model_config = ConfigDict(frozen=True)

    code: ReportFlagCode
    method: MethodName | None
    message: str
    value: float | None


class PmeReport(FinancialBaseModel):
    """Every open-pme metric for one fund, benchmark and set of stated policies.

    Each method slot is its result or a ``Refusal``; ``mpme`` is ``None`` when no NAV
    history was given. ``common_assumptions`` are the assumption lines shared by two or
    more results, in first-seen order; ``method_assumptions`` maps each method that
    produced a result to its remaining lines. Together they hold every line once.
    """

    model_config = ConfigDict(frozen=True)

    fund_name: str
    currency: str
    basis: FlowBasis
    as_of: PlainDate
    stale_nav: StaleNavPolicy
    nav_source: NavSource
    benchmark_name: str
    return_basis: ReturnBasis
    lookup: IndexLookup
    max_gap_days: int
    day_count: DayCountConvention
    interim_nav: InterimNavPolicy | None
    max_nav_gap_days: int | None
    resolved: ResolvedCashFlows
    multiples: Multiples | Refusal
    fund_irr: IrrResult | Refusal
    ks_pme: KsPmeResult | Refusal
    direct_alpha: DirectAlphaResult | Refusal
    pme_plus: PmePlusResult | Refusal
    ln_pme: LnPmeResult | Refusal
    mpme: MpmeResult | Refusal | None
    flags: tuple[ReportFlag, ...]
    common_assumptions: list[str]
    method_assumptions: dict[str, list[str]]
    input_hash: str
    engine_version: str = ENGINE_VERSION

    def to_text(self) -> str:
        """A plain-text report: header, one block per method, flags, then assumptions."""
        lines: list[str] = []

        def row(label: str, text: str) -> None:
            lines.append(f"{label:<14}{text}")

        def roots(irr: IrrResult | None) -> None:
            if irr is not None and irr.status != "unique" and irr.roots:
                row("", f"roots: {_roots_text(irr)}")

        lines.append(f"PME report: {self.fund_name} as of {self.as_of.isoformat()}")
        lines.append(
            f"  fund       basis {self.basis}, currency {self.currency}, NAV "
            f"{self.nav_source} (stale_nav={self.stale_nav})"
        )
        lines.append(
            f"  benchmark  {self.benchmark_name} ({self.return_basis}); lookup {self.lookup}, "
            f"max gap {self.max_gap_days} days; day count {self.day_count}"
        )
        if self.mpme is None:
            lines.append("  mPME       not computed: no NAV history was given")
        else:
            lines.append(
                f"  mPME       interim NAVs {self.interim_nav}, max NAV gap "
                f"{self.max_nav_gap_days} days"
            )
        lines.append("")

        m = self.multiples
        if isinstance(m, Refusal):
            row("Multiples", _refused(m))
        else:
            row("Multiples", f"DPI {_mult(m.dpi)}  RVPI {_mult(m.rvpi)}  TVPI {_mult(m.tvpi)}")
        f = self.fund_irr
        if isinstance(f, Refusal):
            row("Fund IRR", _refused(f))
        else:
            row("Fund IRR", _irr_text(f))
            roots(f)
        k = self.ks_pme
        row("KS-PME", _refused(k) if isinstance(k, Refusal) else _decimal(k.ks_pme, 3))
        d = self.direct_alpha
        if isinstance(d, Refusal):
            row("Direct Alpha", _refused(d))
        else:
            row(
                "Direct Alpha",
                f"{_pct(d.alpha_annual_effective)} (continuous {_pct(d.alpha_continuous)}) "
                f"[{d.irr.status}]",
            )
            roots(d.irr)
        p = self.pme_plus
        if isinstance(p, Refusal):
            row("PME+", _refused(p))
        else:
            scale = "n/a (no distributions)" if p.scale is None else _decimal(p.scale, 4)
            row(
                "PME+",
                f"IRR {_irr_text(p.pme_plus_irr)}  s {scale}  spread {_pct(p.spread)}  "
                f"log spread {_num(p.log_spread)}",
            )
            roots(p.pme_plus_irr)
        i = self.ln_pme
        if isinstance(i, Refusal):
            row("ICM", _refused(i))
        else:
            short = (
                f"went short {i.first_short_date.isoformat()} (minimum {_amount(i.min_position)})"
                if i.went_short and i.first_short_date is not None
                else "never short"
            )
            row(
                "ICM",
                f"IRR {_irr_text(i.icm_irr)}  spread {_pct(i.spread)}  V_T "
                f"{_amount(i.terminal_value_recursive)}  {short}",
            )
            roots(i.icm_irr)
        mp = self.mpme
        if mp is None:
            row("mPME", "not computed (no NAV history)")
        elif isinstance(mp, Refusal):
            row("mPME", _refused(mp))
        else:
            row(
                "mPME",
                f"IRR {_irr_text(mp.mpme_irr)}  spread {_pct(mp.spread)}  NAV_mPME,T "
                f"{_amount(mp.terminal_value)}",
            )
            roots(mp.mpme_irr)

        lines.append("")
        lines.append("Flags" if self.flags else "Flags: none")
        for flag in self.flags:
            where = "" if flag.method is None else f" ({flag.method})"
            lines.append(f"  {flag.code}{where}: {flag.message}")
        lines.append("")
        lines.append("Assumptions shared by several results")
        lines.extend(f"  - {line}" for line in self.common_assumptions)
        for method, method_lines in self.method_assumptions.items():
            if method_lines:
                lines.append(f"Assumptions: {METHOD_LABELS[method]}")
                lines.extend(f"  - {line}" for line in method_lines)
        lines.append("")
        lines.append(f"Input fingerprint {self.input_hash[:16]}  engine {self.engine_version}")
        return "\n".join(lines)

    def to_rows(self) -> list[dict[str, object]]:
        """One row per metric with the keys ``ROW_COLUMNS`` (CSV-ready).

        ``value`` is a float, a bool (``went_short``) or ``None``. ``available`` says
        whether the metric has a value and ``reason`` says why not when it does not (a
        refused method, a withheld spread, an IRR that is not unique, a missing residual
        value). ``irr_status`` is the status of the IRR behind the metric, kept apart from
        the metric's own availability. ``rate_clamped`` and ``log_rate`` accompany a rate
        taken from a unique root, so a clamped ``-1.0`` keeps its exact log rate.
        """
        rows: list[dict[str, object]] = []

        def add(
            method: str,
            metric: str,
            value: object,
            *,
            reason: str,
            irr: IrrResult | None,
            is_rate: bool,
            note: str,
        ) -> None:
            root = irr.roots[0] if is_rate and irr is not None and irr.status == "unique" else None
            rows.append(
                {
                    "method": method,
                    "metric": metric,
                    "value": value,
                    "available": value is not None,
                    "reason": "" if value is not None else reason,
                    "irr_status": "" if irr is None else irr.status,
                    "rate_clamped": None if root is None else root.rate_clamped,
                    "log_rate": None if root is None else root.log_rate,
                    "note": note,
                }
            )

        def plain(method: str, metric: str, value: object, reason: str = "") -> None:
            add(method, metric, value, reason=reason, irr=None, is_rate=False, note="")

        def rate(
            method: str, metric: str, value: float | None, irr: IrrResult | None, reason: str
        ) -> None:
            note = "" if irr is None or irr.status == "unique" else f"roots: {_roots_text(irr)}"
            add(method, metric, value, reason=reason, irr=irr, is_rate=True, note=note)

        def spread_reason(fund: IrrResult | None, other: IrrResult | None, name: str) -> str:
            if fund is None:
                return "the fund IRR is refused"
            if other is None:
                return f"there is no {name} IRR"
            return (
                f"a spread needs two unique IRRs: the fund IRR is '{fund.status}' and the "
                f"{name} IRR is '{other.status}'"
            )

        def not_unique(irr: IrrResult) -> str:
            return f"the IRR has status '{irr.status}', so no single rate is reported"

        slots: list[tuple[str, object]] = [
            ("multiples", self.multiples),
            ("fund_irr", self.fund_irr),
            ("ks_pme", self.ks_pme),
            ("direct_alpha", self.direct_alpha),
            ("pme_plus", self.pme_plus),
            ("ln_pme", self.ln_pme),
            ("mpme", self.mpme),
        ]
        for method, slot in slots:
            if slot is None:
                continue
            if isinstance(slot, Refusal):
                add(method, "refused", None, reason=slot.reason, irr=None, is_rate=False, note="")
            elif isinstance(slot, Multiples):
                missing = "paid-in capital is zero" if slot.paid_in == 0 else "no residual value"
                plain(method, "dpi", slot.dpi, "paid-in capital is zero")
                plain(method, "rvpi", slot.rvpi, missing)
                plain(method, "tvpi", slot.tvpi, missing)
            elif isinstance(slot, IrrResult):
                rate(method, "irr", slot.irr, slot, not_unique(slot))
            elif isinstance(slot, KsPmeResult):
                plain(method, "ks_pme", slot.ks_pme)
            elif isinstance(slot, DirectAlphaResult):
                why = f"the compounded series IRR has status '{slot.irr.status}'"
                rate(method, "alpha_annual_effective", slot.alpha_annual_effective, slot.irr, why)
                add(
                    method,
                    "alpha_continuous",
                    slot.alpha_continuous,
                    reason=why,
                    irr=slot.irr,
                    is_rate=False,
                    note="",
                )
            elif isinstance(slot, PmePlusResult):
                plus = slot.pme_plus_irr
                no_scale = "no distributions: FV(D) = 0, so there is nothing to scale"
                rate(
                    method,
                    "pme_plus_irr",
                    None if plus is None else plus.irr,
                    plus,
                    no_scale if plus is None else not_unique(plus),
                )
                plain(method, "scale", slot.scale, no_scale)
                withheld = (
                    "withheld: s < 0, so the scaled distributions are contributions and the "
                    "difference is not a performance difference (contract §11.4)"
                    if slot.scale_negative
                    else spread_reason(slot.fund_irr, plus, "PME+")
                )
                add(
                    method, "spread", slot.spread, reason=withheld, irr=plus, is_rate=False, note=""
                )
                add(
                    method,
                    "log_spread",
                    slot.log_spread,
                    reason=withheld,
                    irr=plus,
                    is_rate=False,
                    note="",
                )
            elif isinstance(slot, LnPmeResult):
                icm = slot.icm_irr
                rate(method, "icm_irr", icm.irr, icm, not_unique(icm))
                why = spread_reason(slot.fund_irr, icm, "ICM")
                add(method, "spread", slot.spread, reason=why, irr=icm, is_rate=False, note="")
                add(
                    method,
                    "log_spread",
                    slot.log_spread,
                    reason=why,
                    irr=icm,
                    is_rate=False,
                    note="",
                )
                plain(method, "terminal_value", slot.terminal_value_recursive)
                plain(method, "min_position", slot.min_position)
                first = slot.first_short_date
                add(
                    method,
                    "went_short",
                    slot.went_short,
                    reason="",
                    irr=None,
                    is_rate=False,
                    note="" if first is None else f"first short {first.isoformat()}",
                )
            elif isinstance(slot, MpmeResult):
                irr = slot.mpme_irr
                rate(method, "mpme_irr", irr.irr, irr, not_unique(irr))
                why = spread_reason(slot.fund_irr, irr, "mPME")
                add(method, "spread", slot.spread, reason=why, irr=irr, is_rate=False, note="")
                add(
                    method,
                    "log_spread",
                    slot.log_spread,
                    reason=why,
                    irr=irr,
                    is_rate=False,
                    note="",
                )
                plain(method, "terminal_value", slot.terminal_value)
        return rows


_FIXED_LIMIT = 1e9


def _decimal(value: float, places: int) -> str:
    """``value`` to ``places`` decimals, or in scientific notation when fixed-point would
    hide it (a non-zero value below one unit in the last place) or be unwieldy (>= 1e9)."""
    if value == 0.0:
        return f"{0.0:.{places}f}"
    magnitude = abs(value)
    if magnitude >= _FIXED_LIMIT or magnitude < 10.0**-places:
        return f"{value:.3e}"
    return f"{value:.{places}f}"


def _pct(value: float | None) -> str:
    """A rate as a percentage without overflow (the product with 100 is exact in Decimal).

    Scientific notation outside ``[0.01%, 1e9%)``; a tiny non-zero rate never reads as zero,
    and an ordinary near-total loss (``-0.999999``) never reads as ``-100.00%``, which is
    reserved for a clamped root.
    """
    if value is None:
        return "n/a"
    if value == 0.0:
        return "0.00%"
    percent = Decimal(value) * 100
    magnitude = abs(percent)
    if magnitude >= Decimal(_FIXED_LIMIT) or magnitude < Decimal("0.01"):
        return f"{percent:.3E}%"
    text = f"{percent:.2f}%"
    if value > -1.0 and text == "-100.00%":
        places = 2 - Decimal(1.0 + value).adjusted()
        text = f"{percent:.{places}f}%"
    return text


def _mult(value: float | None) -> str:
    return "n/a" if value is None else f"{_decimal(value, 2)}x"


def _num(value: float | None) -> str:
    return "n/a" if value is None else _decimal(value, 4)


def _amount(value: float) -> str:
    """A currency amount: thousands separators in the ordinary range, else scientific."""
    if value == 0.0:
        return "0.00"
    if 0.01 <= abs(value) < 1e15:
        return f"{value:,.2f}"
    return f"{value:.3e}"


def _refused(refusal: Refusal) -> str:
    return f"refused: {refusal.reason}"


def _root_text(rate: float, log_rate: float, clamped: bool) -> str:
    if clamped:
        return f"-100% (clamped; ln(1+r) = {_decimal(log_rate, 4)})"
    return _pct(rate)


def _roots_text(irr: IrrResult) -> str:
    parts: list[str] = []
    for root in irr.roots:
        text = _root_text(root.rate, root.log_rate, root.rate_clamped)
        parts.append(f"{text} (tangent)" if root.kind == "tangent" else text)
    return ", ".join(parts) if parts else "none"


def _irr_text(irr: IrrResult | None) -> str:
    if irr is None:
        return "n/a"
    if irr.status == "unique" and irr.irr is not None:
        root = irr.roots[0]
        return f"{_root_text(irr.irr, root.log_rate, root.rate_clamped)} [unique]"
    return f"n/a [{irr.status}]"


def _attempt(method: MethodName, run: Callable[[], _T]) -> _T | Refusal:
    """Run one method; a ``ValueError`` becomes a ``Refusal``, anything else propagates."""
    try:
        return run()
    except ValueError as exc:
        return Refusal(method=method, reason=str(exc))


def _check_nav_policy(nav_history: object, interim_nav: object, max_nav_gap_days: object) -> None:
    if nav_history is None:
        if interim_nav is not None or max_nav_gap_days is not None:
            raise ValueError(
                "nav_history is None, so no mPME is computed: interim_nav and "
                "max_nav_gap_days must be None as well (a policy for an absent history "
                "would be silently ignored)"
            )
        return
    if not isinstance(nav_history, FundNavHistory):
        raise ValueError(
            f"nav_history must be a FundNavHistory or None, got {type(nav_history).__name__}"
        )
    if interim_nav is None or max_nav_gap_days is None:
        raise ValueError(
            "a nav_history computes the mPME, which needs interim_nav and max_nav_gap_days "
            "stated; neither has a default"
        )
    # The mPME's own validator, run before any method: an unknown policy, a negative gap
    # and "refuse" with a gap above 0 refuse the whole report (contract §13.5).
    check_interim_policy(interim_nav, max_nav_gap_days)


def _irr_flags(method: MethodName, irr: IrrResult | None) -> list[ReportFlag]:
    if irr is None:
        return []
    flags: list[ReportFlag] = []
    label = METHOD_LABELS[method]
    if irr.status != "unique":
        flags.append(
            ReportFlag(
                code="IRR_NOT_UNIQUE",
                method=method,
                message=f"the {label} IRR has status '{irr.status}' (roots: "
                f"{_roots_text(irr)}); no single rate is reported",
                value=None,
            )
        )
    for root in irr.roots:
        if root.rate_clamped:
            flags.append(
                ReportFlag(
                    code="RATE_CLAMPED",
                    method=method,
                    message=f"a {label} IRR root has 1 + r below float resolution: its rate "
                    f"reads -1.0 and ln(1 + r) = {root.log_rate!r} carries the root",
                    value=root.log_rate,
                )
            )
    return flags


def _flags(
    resolved: ResolvedCashFlows,
    benchmark: BenchmarkIndex,
    slots: dict[MethodName, object],
) -> tuple[ReportFlag, ...]:
    flags: list[ReportFlag] = []
    if benchmark.return_basis == "price_return":
        flags.append(
            ReportFlag(
                code="PRICE_RETURN",
                method=None,
                message="the benchmark is a price index: it omits dividends, so every PME "
                "against it overstates the fund's relative performance",
                value=None,
            )
        )
    pmes = [slot for slot in slots.values() if isinstance(slot, PmeResultBase)]
    roll = resolved.nav_roll_forward
    if resolved.nav_source == "rolled_forward" and roll is not None:
        growth = next(
            (r.index_growth_over_nav_gap for r in pmes if r.index_growth_over_nav_gap),
            None,
        )
        movement = (
            "the index move over that gap could not be quantified"
            if growth is None
            else f"the index grew by I_T / I_navdate = {growth!r} over that gap (above 1 the "
            "PMEs move against the fund)"
        )
        flags.append(
            ReportFlag(
                code="NAV_ROLLED_FORWARD",
                method=None,
                message=f"the residual value is a NAV rolled forward with zero return from "
                f"{roll.reported_date.isoformat()} to {resolved.as_of.isoformat()}; {movement}",
                value=growth,
            )
        )
    max_gap_used = max((r.max_gap_used_days for r in pmes), default=0)
    if max_gap_used > 0:
        flags.append(
            ReportFlag(
                code="INDEX_STALE",
                method=None,
                message=f"an index level up to {max_gap_used} days older than its date was "
                "used (lookup last_on_or_before), counting the NAV-date lookup behind "
                "index_growth_over_nav_gap",
                value=float(max_gap_used),
            )
        )
    for record in resolved.stated_nets_within_noise:
        flags.append(
            ReportFlag(
                code="STATED_NET_WITHIN_REPRESENTATION_NOISE",
                method=None,
                message=f"the stated legs on {record.date.isoformat()} net to "
                f"{record.raw_net!r} on gross legs {record.gross!r}, within the "
                f"decimal-representation bound {record.bound!r}; the date counts as zero",
                value=record.raw_net,
            )
        )
    fund = slots["fund_irr"]
    flags.extend(_irr_flags("fund_irr", fund if isinstance(fund, IrrResult) else None))
    da = slots["direct_alpha"]
    if isinstance(da, DirectAlphaResult):
        flags.extend(_irr_flags("direct_alpha", da.irr))
    plus = slots["pme_plus"]
    if isinstance(plus, PmePlusResult):
        flags.extend(_irr_flags("pme_plus", plus.pme_plus_irr))
        if plus.scale_negative and plus.scale is not None:
            flags.append(
                ReportFlag(
                    code="PME_PLUS_NEGATIVE_SCALE",
                    method="pme_plus",
                    message=f"s = {plus.scale!r} < 0: NAV_T exceeds FV(C), the scaled "
                    "distributions become contributions and the spread is withheld",
                    value=plus.scale,
                )
            )
    icm = slots["ln_pme"]
    if isinstance(icm, LnPmeResult):
        flags.extend(_irr_flags("ln_pme", icm.icm_irr))
        if icm.went_short and icm.first_short_date is not None:
            flags.append(
                ReportFlag(
                    code="ICM_WENT_SHORT",
                    method="ln_pme",
                    message=f"the ICM index position went short on "
                    f"{icm.first_short_date.isoformat()} (minimum {icm.min_position!r}); the "
                    "ICM IRR then describes a levered short, not an index holding",
                    value=icm.min_position,
                )
            )
    mp = slots.get("mpme")
    if isinstance(mp, MpmeResult):
        flags.extend(_irr_flags("mpme", mp.mpme_irr))
    computed_methods: tuple[MethodName, ...] = ("pme_plus", "ln_pme", "mpme")
    for method in computed_methods:
        result = slots.get(method)
        if isinstance(result, PmePlusResult | LnPmeResult | MpmeResult):
            for record in result.dropped_computed_nets:
                flags.append(
                    ReportFlag(
                        code="COMPUTED_NET_DROPPED",
                        method=method,
                        message=f"the {METHOD_LABELS[method]} net {record.raw_net!r} on "
                        f"{record.date.isoformat()} is within the float rounding bound "
                        f"{record.bound!r} (gross magnitude {record.gross!r}) and was dropped "
                        "as rounding of an exact zero",
                        value=record.raw_net,
                    )
                )
    for slot in slots.values():
        if isinstance(slot, Refusal):
            flags.append(
                ReportFlag(
                    code="METHOD_REFUSED", method=slot.method, message=slot.reason, value=None
                )
            )
    return tuple(flags)


def _split_assumptions(
    slots: dict[MethodName, object],
) -> tuple[list[str], dict[str, list[str]]]:
    per_method: dict[str, list[str]] = {}
    for method, slot in slots.items():
        lines = getattr(slot, "assumptions", None)
        if isinstance(lines, list):
            per_method[method] = list(dict.fromkeys(lines))
    counts: dict[str, int] = {}
    for lines in per_method.values():
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
    common = [
        line
        for line in dict.fromkeys(line for lines in per_method.values() for line in lines)
        if counts[line] >= 2
    ]
    shared = set(common)
    specific = {
        method: [line for line in lines if line not in shared]
        for method, lines in per_method.items()
    }
    return common, specific


def pme_report(
    fund: FundCashFlows,
    benchmark: BenchmarkIndex,
    *,
    as_of: date,
    stale_nav: StaleNavPolicy,
    day_count: DayCountConvention,
    lookup: IndexLookup,
    max_gap_days: int,
    nav_history: FundNavHistory | None,
    interim_nav: InterimNavPolicy | None,
    max_nav_gap_days: int | None,
) -> PmeReport:
    """Every open-pme metric for ``fund`` against ``benchmark`` under stated policies.

    ``nav_history`` is a ``FundNavHistory`` (then ``interim_nav`` and
    ``max_nav_gap_days`` are required and the mPME is computed) or an explicit ``None``
    (then both must be ``None`` and no mPME is computed). Argument values outside their
    domains (an unknown day count or lookup, a negative gap, a policy for an absent NAV
    history) and a refusal of ``resolve`` refuse the whole report with ``ValueError``;
    after that, each method that refuses is recorded as a ``Refusal`` in its slot and
    flagged ``METHOD_REFUSED``.
    """
    if not isinstance(fund, FundCashFlows):
        raise ValueError(f"fund must be a FundCashFlows, got {type(fund).__name__}")
    if not isinstance(benchmark, BenchmarkIndex):
        raise ValueError(f"benchmark must be a BenchmarkIndex, got {type(benchmark).__name__}")
    day_count = check_convention(day_count)
    benchmark_assumptions(benchmark, lookup=lookup, max_gap_days=max_gap_days)  # validates
    _check_nav_policy(nav_history, interim_nav, max_nav_gap_days)
    resolved = resolve(fund, as_of=as_of, stale_nav=stale_nav)

    def pme_call(method: Callable[..., _T]) -> Callable[[], _T]:
        return lambda: method(
            resolved, benchmark, lookup=lookup, max_gap_days=max_gap_days, day_count=day_count
        )

    slots: dict[MethodName, object] = {
        "multiples": _attempt("multiples", lambda: multiples(resolved)),
        "fund_irr": _attempt("fund_irr", lambda: fund_irr(resolved, day_count=day_count)),
        "ks_pme": _attempt(
            "ks_pme",
            lambda: ks_pme(resolved, benchmark, lookup=lookup, max_gap_days=max_gap_days),
        ),
        "direct_alpha": _attempt("direct_alpha", pme_call(direct_alpha)),
        "pme_plus": _attempt("pme_plus", pme_call(pme_plus)),
        "ln_pme": _attempt("ln_pme", pme_call(ln_pme)),
    }
    mpme_slot: MpmeResult | Refusal | None = None
    if nav_history is not None and interim_nav is not None and max_nav_gap_days is not None:
        history, policy, gap = nav_history, interim_nav, max_nav_gap_days
        mpme_slot = _attempt(
            "mpme",
            lambda: mpme(
                resolved,
                history,
                benchmark,
                lookup=lookup,
                max_gap_days=max_gap_days,
                day_count=day_count,
                interim_nav=policy,
                max_nav_gap_days=gap,
            ),
        )
        slots["mpme"] = mpme_slot
    common, specific = _split_assumptions(slots)
    return PmeReport(
        fund_name=resolved.fund_name,
        currency=resolved.currency,
        basis=resolved.basis,
        as_of=resolved.as_of,
        stale_nav=stale_nav,
        nav_source=resolved.nav_source,
        benchmark_name=benchmark.name,
        return_basis=benchmark.return_basis,
        lookup=lookup,
        max_gap_days=max_gap_days,
        day_count=day_count,
        interim_nav=interim_nav,
        max_nav_gap_days=max_nav_gap_days,
        resolved=resolved,
        multiples=slots["multiples"],  # type: ignore[arg-type]
        fund_irr=slots["fund_irr"],  # type: ignore[arg-type]
        ks_pme=slots["ks_pme"],  # type: ignore[arg-type]
        direct_alpha=slots["direct_alpha"],  # type: ignore[arg-type]
        pme_plus=slots["pme_plus"],  # type: ignore[arg-type]
        ln_pme=slots["ln_pme"],  # type: ignore[arg-type]
        mpme=mpme_slot,
        flags=_flags(resolved, benchmark, slots),
        common_assumptions=common,
        method_assumptions=specific,
        input_hash=canonical_hash(
            {
                "method": "pme_report",
                "fund": fund.model_dump(mode="json"),
                "benchmark": benchmark.model_dump(mode="json"),
                "as_of": resolved.as_of.isoformat(),
                "stale_nav": stale_nav,
                "day_count": day_count,
                "lookup": lookup,
                "max_gap_days": max_gap_days,
                "nav_history": None if nav_history is None else nav_history.model_dump(mode="json"),
                "interim_nav": interim_nav,
                "max_nav_gap_days": max_nav_gap_days,
            }
        ),
    )
