"""`ovf.pme.report.pme_report`: one call, every metric, refusals in their slots, flags."""

from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

import ovf.pme.report as report_module
from ovf.pme.benchmark import BenchmarkIndex, IndexLevel
from ovf.pme.flows import CashFlow, FundCashFlows, NavObservation
from ovf.pme.irr import IrrResult
from ovf.pme.metrics import Multiples
from ovf.pme.mpme import FundNavHistory, MpmeResult
from ovf.pme.pme import DirectAlphaResult, KsPmeResult, LnPmeResult, PmePlusResult
from ovf.pme.report import ROW_COLUMNS, PmeReport, Refusal, pme_report

Row = tuple[date, str, float]

POLICY: dict[str, Any] = {
    "stale_nav": "refuse",
    "day_count": "ACT/365F",
    "lookup": "exact",
    "max_gap_days": 0,
}
NO_HISTORY: dict[str, Any] = {"nav_history": None, "interim_nav": None, "max_nav_gap_days": None}


def _fund(
    rows: list[Row], nav: tuple[date, float] | None, *, name: str = "Fund I"
) -> FundCashFlows:
    return FundCashFlows(
        name=name,
        currency="USD",
        basis="net_lp",
        flows=tuple(CashFlow(date=d, kind=k, amount=a) for d, k, a in rows),  # type: ignore[arg-type]
        nav=None if nav is None else NavObservation(date=nav[0], value=nav[1]),
    )


def _index(pairs: list[tuple[date, float]], *, basis: str = "total_return_gross") -> BenchmarkIndex:
    return BenchmarkIndex(
        name="Index",
        currency="USD",
        return_basis=basis,  # type: ignore[arg-type]
        levels=tuple(IndexLevel(date=d, level=v) for d, v in pairs),
    )


def _report(
    fund: FundCashFlows, index: BenchmarkIndex, *, as_of: date, **overrides: Any
) -> PmeReport:
    return pme_report(fund, index, as_of=as_of, **{**POLICY, **NO_HISTORY, **overrides})


def _codes(report: PmeReport) -> list[tuple[str, str | None]]:
    return [(flag.code, flag.method) for flag in report.flags]


# Gredil, Griffiths & Stucke (2014) Exhibits 5-6 (fixture PME-F12): year-end dates.
YEARS = [date(year, 12, 31) for year in range(2001, 2011)]
GGS_END = YEARS[-1]
GGS_ROWS: list[Row] = [
    (YEARS[0], "contribution", 100.0),
    (YEARS[2], "contribution", 100.0),
    (YEARS[2], "distribution", 25.0),
    (YEARS[4], "contribution", 50.0),
    (YEARS[4], "distribution", 150.0),
    (YEARS[6], "distribution", 150.0),
    (YEARS[8], "distribution", 100.0),
]
GGS_INDEX = _index(
    list(
        zip(
            YEARS, (100.0, 78.0, 100.0, 111.0, 117.0, 135.0, 142.0, 90.0, 113.0, 131.0), strict=True
        )
    )
)


def _ggs(**overrides: Any) -> PmeReport:
    return _report(
        _fund(GGS_ROWS, (GGS_END, 75.0), name="GGS"), GGS_INDEX, as_of=GGS_END, **overrides
    )


# --- Values -----------------------------------------------------------------------


def test_ggs_exhibits_5_and_6_values() -> None:
    report = _ggs()
    assert isinstance(report.multiples, Multiples)
    assert report.multiples.tvpi == pytest.approx(2.0, rel=1e-15)  # 500 / 250
    assert isinstance(report.fund_irr, IrrResult)
    assert report.fund_irr.irr == pytest.approx(0.17520129832391, rel=1e-10)
    assert isinstance(report.ks_pme, KsPmeResult)
    assert report.ks_pme.ks_pme == pytest.approx(1990055721 / 1193950768, rel=1e-12)
    assert isinstance(report.direct_alpha, DirectAlphaResult)
    assert report.direct_alpha.alpha_annual_effective == pytest.approx(0.12560316898427, rel=1e-10)
    assert isinstance(report.pme_plus, PmePlusResult)
    assert report.pme_plus.scale == pytest.approx(912343468 / 1708448421, rel=1e-12)
    assert isinstance(report.ln_pme, LnPmeResult)
    assert report.ln_pme.icm_irr.status == "multiple"
    assert [root.rate for root in report.ln_pme.icm_irr.roots] == pytest.approx(
        [-0.27255088669879, 0.05967014313864], rel=1e-10
    )
    assert report.ln_pme.first_short_date == YEARS[6]
    assert report.mpme is None
    assert _codes(report) == [("IRR_NOT_UNIQUE", "ln_pme"), ("ICM_WENT_SHORT", "ln_pme")]
    assert (report.fund_name, report.as_of, report.nav_source) == (
        "GGS",
        GGS_END,
        "reported_at_as_of",
    )


def test_written_off_fund_reports_every_method_and_flags_the_clamped_rate() -> None:
    # R2's dead fund: the unique root has ln(1 + r) ~ -508, so 1 + r underflows and the rate
    # reads -1.0; nothing is refused (contract §11.1, §11.2).
    rows: list[Row] = [
        (date(2015, 2, 20), "contribution", 8564951.8),
        (date(2015, 4, 18), "contribution", 1980030.11),
        (date(2015, 10, 8), "contribution", 8058613.1),
        (date(2018, 10, 31), "contribution", 4810056.04),
        (date(2019, 9, 6), "contribution", 6178192.46),
        (date(2019, 9, 9), "distribution", 95029.33),
    ]
    as_of = date(2019, 11, 25)
    days = sorted({d for d, _, _ in rows} | {as_of})
    report = _report(
        _fund(rows, (as_of, 0.0)), _index([(d, 100.0 + i) for i, d in enumerate(days)]), as_of=as_of
    )
    slots = (
        report.multiples,
        report.fund_irr,
        report.ks_pme,
        report.direct_alpha,
        report.pme_plus,
        report.ln_pme,
    )
    assert not any(isinstance(slot, Refusal) for slot in slots)
    assert ("RATE_CLAMPED", "fund_irr") in _codes(report)
    assert "-100% (clamped; ln(1+r) = -" in report.to_text()


EXPLOSIVE_END = date(2021, 1, 2)
# Contribute 1, receive 8 a day later: ln(1 + r) = 365 ln 8 = 759 > ln(float max).
EXPLOSIVE: list[Row] = [
    (date(2021, 1, 1), "contribution", 1.0),
    (EXPLOSIVE_END, "distribution", 8.0),
]


def test_a_refused_fund_irr_leaves_every_other_method_in_place() -> None:
    report = _report(
        _fund(EXPLOSIVE, (EXPLOSIVE_END, 0.0)),
        _index([(date(2021, 1, 1), 100.0), (EXPLOSIVE_END, 100.0)]),
        as_of=EXPLOSIVE_END,
    )
    assert isinstance(report.fund_irr, Refusal) and "delta" in report.fund_irr.reason
    assert isinstance(report.direct_alpha, Refusal)  # its compounded series is the same
    assert isinstance(report.ks_pme, KsPmeResult) and report.ks_pme.ks_pme == pytest.approx(8.0)
    assert isinstance(report.pme_plus, PmePlusResult) and report.pme_plus.fund_irr is None
    assert isinstance(report.ln_pme, LnPmeResult) and report.ln_pme.went_short is True
    refused = [flag.method for flag in report.flags if flag.code == "METHOD_REFUSED"]
    assert refused == ["fund_irr", "direct_alpha"]
    assert "refused:" in report.to_text()
    rows = [row for row in report.to_rows() if row["metric"] == "refused"]
    assert {row["method"] for row in rows} == {"fund_irr", "direct_alpha"}


# --- Flags ------------------------------------------------------------------------

T0, T1, T2 = date(2021, 1, 1), date(2022, 1, 1), date(2023, 1, 1)
INDEX3 = _index([(T0, 100.0), (T1, 120.0), (T2, 150.0)])
HAND: list[Row] = [
    (T0, "contribution", 100.0),
    (T1, "contribution", 40.0),
    (T1, "distribution", 80.0),
    (T2, "distribution", 30.0),
]


def test_price_return_flag() -> None:
    price = _index([(T0, 100.0), (T1, 120.0), (T2, 150.0)], basis="price_return")
    report = _report(_fund(HAND, (T2, 110.0)), price, as_of=T2)
    assert ("PRICE_RETURN", None) in _codes(report)


def test_rolled_forward_nav_flag_carries_the_index_growth() -> None:
    # R2-4: NAV 100 at T1 rolled to T2 while the index rose 30%.
    fund = _fund([(T0, "contribution", 100.0)], (T1, 100.0))
    report = _report(
        fund,
        _index([(T0, 100.0), (T1, 100.0), (T2, 130.0)]),
        as_of=T2,
        stale_nav="roll_forward_cash_adjusted",
    )
    flag = next(flag for flag in report.flags if flag.code == "NAV_ROLLED_FORWARD")
    assert flag.value == pytest.approx(1.3, rel=1e-15)
    assert report.nav_source == "rolled_forward"


def test_stale_index_flag_carries_the_largest_gap() -> None:
    stale = _index([(T0, 100.0), (date(2021, 12, 28), 120.0), (T2, 150.0)])
    report = _report(
        _fund(HAND, (T2, 110.0)), stale, as_of=T2, lookup="last_on_or_before", max_gap_days=10
    )
    flag = next(flag for flag in report.flags if flag.code == "INDEX_STALE")
    assert flag.value == 4.0


def test_negative_pme_plus_scale_flag() -> None:
    # FV(C) = 150, FV(D) = 25, NAV 200: s = -2.
    fund = _fund([(T0, "contribution", 100.0), (T1, "distribution", 20.0)], (T2, 200.0))
    report = _report(fund, INDEX3, as_of=T2)
    flag = next(flag for flag in report.flags if flag.code == "PME_PLUS_NEGATIVE_SCALE")
    assert flag.method == "pme_plus" and flag.value == pytest.approx(-2.0)


def test_stated_dust_flag_names_the_date_and_raw_net() -> None:
    rows: list[Row] = [
        (T0, "contribution", 1_000_000.0),
        (T1, "distribution", 300_000.30),
        (T1, "contribution", 100_000.10),
        (T1, "contribution", 200_000.20),
    ]
    report = _report(_fund(rows, (T2, 1_200_000.0)), INDEX3, as_of=T2)
    flag = next(f for f in report.flags if f.code == "STATED_NET_WITHIN_REPRESENTATION_NOISE")
    assert "2022-01-01" in flag.message
    assert flag.value is not None and flag.value != 0.0 and abs(flag.value) < 1e-9


def test_computed_net_dropped_flag() -> None:
    # The ICM rescaling case (contract §9): the terminal ICM net is 7e-15 of rounding.
    dates = [
        date(2021, 1, 1),
        date(2021, 4, 1),
        date(2021, 6, 30),
        date(2021, 9, 28),
        date(2021, 12, 27),
    ]
    rows: list[Row] = [
        (dates[0], "contribution", 10.0),
        (dates[1], "contribution", 90.0),
        (dates[2], "distribution", 77.0),
        (dates[3], "distribution", 50.0),
        (dates[4], "contribution", 10.0),
    ]
    k = 1.990652220727
    index = _index([(d, v * k) for d, v in zip(dates, (50.0, 50.0, 77.0, 50.0, 50.0), strict=True)])
    report = _report(_fund(rows, (dates[4], 0.0)), index, as_of=dates[4])
    assert ("COMPUTED_NET_DROPPED", "ln_pme") in _codes(report)
    # The flag comes from the structured record (contract §13.2), value = the raw net.
    flag = next(f for f in report.flags if f.code == "COMPUTED_NET_DROPPED")
    assert isinstance(report.ln_pme, LnPmeResult)
    assert flag.value == report.ln_pme.dropped_computed_nets[0].raw_net


# --- Assumptions ------------------------------------------------------------------


def test_assumptions_are_split_into_shared_and_method_lines_without_loss() -> None:
    report = _ggs()
    results = {
        "multiples": report.multiples,
        "fund_irr": report.fund_irr,
        "ks_pme": report.ks_pme,
        "direct_alpha": report.direct_alpha,
        "pme_plus": report.pme_plus,
        "ln_pme": report.ln_pme,
    }
    everything = {line for result in results.values() for line in result.assumptions}  # type: ignore[union-attr]
    common = report.common_assumptions
    specific = [line for lines in report.method_assumptions.values() for line in lines]
    assert len(common) == len(set(common))
    assert not set(common) & set(specific)
    assert set(common) | set(specific) == everything
    assert set(report.method_assumptions) == set(results)
    for line in common:
        holders = [m for m, r in results.items() if line in r.assumptions]  # type: ignore[union-attr]
        assert len(holders) >= 2
    for method, lines in report.method_assumptions.items():
        for line in lines:
            assert line in results[method].assumptions  # type: ignore[union-attr]
    # resolve's lines are in every result, so they are shared.
    assert set(report.resolved.assumptions) <= set(common)
    assert common[0] == report.resolved.assumptions[0]


# --- Rendering --------------------------------------------------------------------


def test_to_text_reports_every_method_flags_and_assumptions() -> None:
    text = _ggs().to_text()
    for expected in (
        "PME report: GGS as of 2010-12-31",
        "DPI 1.70x  RVPI 0.30x  TVPI 2.00x",
        "Fund IRR      17.52% [unique]",
        "KS-PME        1.667",
        "Direct Alpha  12.56% (continuous 11.83%) [unique]",
        "PME+          IRR 4.06% [unique]  s 0.5340  spread 13.46%",
        "ICM           IRR n/a [multiple]",
        "roots: -27.26%, 5.97%",
        "went short 2007-12-31",
        "mPME          not computed (no NAV history)",
        "ICM_WENT_SHORT (ln_pme)",
        "Assumptions shared by several results",
        "Assumptions: KS-PME",
        "Input fingerprint",
    ):
        assert expected in text, expected


def test_to_rows_is_one_row_per_metric_and_csv_ready() -> None:
    rows = _ggs().to_rows()
    by_key = {(row["method"], row["metric"]): row for row in rows}
    tvpi = by_key[("multiples", "tvpi")]
    assert tvpi["value"] == pytest.approx(2.0) and tvpi["available"] is True
    assert tvpi["reason"] == ""
    assert by_key[("ks_pme", "ks_pme")]["value"] == pytest.approx(1990055721 / 1193950768)
    icm = by_key[("ln_pme", "icm_irr")]
    assert icm["value"] is None and icm["available"] is False
    assert icm["irr_status"] == "multiple" and "status 'multiple'" in str(icm["reason"])
    assert "-27.26%" in str(icm["note"])
    spread = by_key[("ln_pme", "spread")]
    assert spread["available"] is False and "two unique IRRs" in str(spread["reason"])
    irr = by_key[("fund_irr", "irr")]
    assert irr["rate_clamped"] is False
    assert irr["log_rate"] == pytest.approx(math.log1p(0.17520129832391), rel=1e-10)
    assert by_key[("ln_pme", "went_short")]["value"] is True
    assert all(tuple(row) == ROW_COLUMNS for row in rows)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(ROW_COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
    assert buffer.getvalue().count("\n") == len(rows) + 1


def test_rows_explain_unavailable_metrics_and_keep_clamped_roots() -> None:
    # R3-8 (out/r3/repro_08.py): s = (100 - 200) / 20 = -5, so the spread is withheld; the
    # row says why rather than showing the PME+ IRR's 'unique' as if all were well.
    fund = _fund([(T0, "contribution", 100.0), (T1, "distribution", 20.0)], (T2, 200.0))
    flat = _index([(T0, 1.0), (T1, 1.0), (T2, 1.0)])
    rows = {(r["method"], r["metric"]): r for r in _report(fund, flat, as_of=T2).to_rows()}
    for metric in ("spread", "log_spread"):
        row = rows[("pme_plus", metric)]
        assert row["available"] is False and row["irr_status"] == "unique"
        assert "s < 0" in str(row["reason"])
    # A clamped fund IRR keeps its exact log root: contribute 100, receive 1e-100 a day
    # later, NAV 0: ln(1 + r) = 365 * ln(1e-100 / 100) = -85725.243...
    day = T0 + timedelta(days=1)
    clamped = _fund([(T0, "contribution", 100.0), (day, "distribution", 1e-100)], (T2, 0.0))
    index = _index([(T0, 1.0), (day, 1.0), (T2, 1.0)])
    rows = {(r["method"], r["metric"]): r for r in _report(clamped, index, as_of=T2).to_rows()}
    row = rows[("fund_irr", "irr")]
    assert row["value"] == -1.0 and row["rate_clamped"] is True
    assert row["log_rate"] == pytest.approx(365 * math.log(1e-100 / 100), rel=1e-9)
    # No residual value: RVPI and TVPI are unavailable, and the rows say why.
    no_nav = _report(_fund(HAND, None), INDEX3, as_of=T2)
    rows = {(r["method"], r["metric"]): r for r in no_nav.to_rows()}
    assert rows[("multiples", "tvpi")]["reason"] == "no residual value"
    assert rows[("ks_pme", "refused")]["available"] is False


def test_text_is_magnitude_aware() -> None:
    # R3-7 (out/r3/render_extremes.py): contribute 1, receive d a year later, NAV 0, flat
    # index. d = 1e307: the IRR is 1e307 - 1 (finite) and s = 1e-307 (non-zero).
    flat = _index([(T0, 1.0), (T1, 1.0)])
    big = (
        _report(
            _fund([(T0, "contribution", 1.0), (T1, "distribution", 1e307)], (T1, 0.0)),
            flat,
            as_of=T1,
        )
        .to_text()
        .split("\nFlags")[0]
    )
    assert "inf" not in big and "nan" not in big
    assert "Fund IRR      1.000E+309% [unique]" in big
    assert "s 1.000e-307" in big and "s 0.0000" not in big
    assert "TVPI 1.000e+307x" in big
    # d = 1e-6: an ordinary near-total loss (-99.9999%), not a clamped root; tiny multiples
    # are never printed as zero.
    small = (
        _report(
            _fund([(T0, "contribution", 1.0), (T1, "distribution", 1e-6)], (T1, 0.0)),
            flat,
            as_of=T1,
        )
        .to_text()
        .split("\nFlags")[0]
    )
    assert "Fund IRR      -99.99990000% [unique]" in small
    assert "-100.00%" not in small
    # DPI and TVPI are 1e-6, non-zero, so never "0.00x"; RVPI is an exact 0 and may be.
    assert "DPI 0.00x" not in small and "TVPI 0.00x" not in small and "RVPI 0.00x" in small
    assert "TVPI 1.000e-06x" in small and "KS-PME        1.000e-06" in small


def test_flags_ignore_metadata_that_looks_like_a_diagnostic() -> None:
    # R3-5 (out/r3/repro_05.py): PME+ s = (100 - 80) / 20 = 1 and both the PME+ and ICM
    # series are -100, +20, +80: nothing is dropped, whatever the benchmark is called.
    fund = _fund([(T0, "contribution", 100.0), (T1, "distribution", 20.0)], (T2, 80.0))
    for name in ("B", "within the float rounding bound"):
        index = BenchmarkIndex(
            name=name,
            currency="USD",
            return_basis="total_return_net",
            levels=tuple(IndexLevel(date=d, level=1.0) for d in (T0, T1, T2)),
        )
        assert _report(fund, index, as_of=T2).flags == ()


def test_the_nav_date_lookup_raises_index_stale() -> None:
    # R3-6 (out/r3/repro_06.py): the NAV-date lookup's 1-day gap counts (contract §13.3).
    fund = _fund([(T0, "contribution", 100.0)], (T1, 80.0))
    index = _index([(T0, 1.0), (T1 - timedelta(days=1), 2.0), (T2, 4.0)])
    report = _report(
        fund,
        index,
        as_of=T2,
        stale_nav="roll_forward_cash_adjusted",
        lookup="last_on_or_before",
        max_gap_days=1,
    )
    stale = next(flag for flag in report.flags if flag.code == "INDEX_STALE")
    assert stale.value == 1.0
    rolled = next(flag for flag in report.flags if flag.code == "NAV_ROLLED_FORWARD")
    assert rolled.value == 2.0


def test_refuse_with_a_gap_refuses_the_whole_report() -> None:
    # R3-9 (out/r3/repro_09.py): a contradictory interim policy is an argument error,
    # refused before any method runs, not an mPME Refusal inside a successful report.
    with pytest.raises(ValueError, match="must be 0"):
        _ggs(nav_history=GGS_HISTORY, interim_nav="refuse", max_nav_gap_days=1)


def test_report_date_field_refuses_datetime() -> None:
    report = _ggs()
    with pytest.raises(ValidationError, match="not a datetime"):
        PmeReport.model_validate({**report.model_dump(), "as_of": datetime(2010, 12, 31)})


# --- mPME and the NAV-history arguments ---------------------------------------------

GGS_HISTORY = FundNavHistory(
    observations=tuple(
        NavObservation(date=d, value=v)
        for d, v in ((YEARS[2], 120.0), (YEARS[4], 100.0), (YEARS[6], 90.0), (YEARS[8], 80.0))
    )
)


def test_mpme_is_computed_with_a_nav_history() -> None:
    report = _ggs(nav_history=GGS_HISTORY, interim_nav="refuse", max_nav_gap_days=0)
    assert isinstance(report.mpme, MpmeResult)
    assert report.mpme.mpme_irr.status in ("unique", "multiple", "none", "undetermined")
    assert report.interim_nav == "refuse" and report.max_nav_gap_days == 0
    assert "mpme" in report.method_assumptions
    text = report.to_text()
    assert "mPME          IRR" in text and "interim NAVs refuse" in text
    assert any(row["method"] == "mpme" for row in report.to_rows())


def test_an_mpme_refusal_is_recorded_in_its_slot() -> None:
    # No NAV at the 2007 distribution date, and interim NAVs may not be rolled: refused.
    partial = FundNavHistory(observations=(NavObservation(date=YEARS[2], value=120.0),))
    report = _ggs(nav_history=partial, interim_nav="refuse", max_nav_gap_days=0)
    assert isinstance(report.mpme, Refusal)
    assert ("METHOD_REFUSED", "mpme") in _codes(report)
    assert isinstance(report.ks_pme, KsPmeResult)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"interim_nav": "refuse"}, "must be None as well"),
        ({"max_nav_gap_days": 0}, "must be None as well"),
        ({"nav_history": GGS_HISTORY}, "needs interim_nav and max_nav_gap_days"),
        ({"nav_history": GGS_HISTORY, "interim_nav": "refuse"}, "needs interim_nav"),
        (
            {"nav_history": GGS_HISTORY, "interim_nav": "guess", "max_nav_gap_days": 0},
            "interim_nav must be one of",
        ),
        ({"nav_history": GGS_HISTORY, "interim_nav": "refuse", "max_nav_gap_days": -1}, ">= 0"),
        (
            {
                "nav_history": (NavObservation(date=GGS_END, value=75.0),),
                "interim_nav": "refuse",
                "max_nav_gap_days": 0,
            },
            "FundNavHistory",
        ),
    ],
)
def test_nav_history_argument_rules(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _ggs(**overrides)


# --- Whole-report refusals, immutability, hashing -----------------------------------


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"day_count": "30/360"}, "day-count"),
        ({"lookup": "nearest"}, "lookup must be one of"),
        ({"max_gap_days": 3}, "max_gap_days must be 0"),
        ({"stale_nav": "interpolate"}, "stale_nav"),
    ],
)
def test_invalid_policies_refuse_the_whole_report(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _ggs(**overrides)


def test_a_resolve_refusal_refuses_the_whole_report() -> None:
    with pytest.raises(ValueError, match="before the first flow"):
        _report(_fund(GGS_ROWS, (GGS_END, 75.0)), GGS_INDEX, as_of=date(2001, 1, 1))
    with pytest.raises(ValueError, match="FundCashFlows"):
        pme_report(GGS_ROWS, GGS_INDEX, as_of=GGS_END, **POLICY, **NO_HISTORY)  # type: ignore[arg-type]


def test_policies_are_keyword_only_without_defaults() -> None:
    fund = _fund(GGS_ROWS, (GGS_END, 75.0))
    with pytest.raises(TypeError):
        pme_report(fund, GGS_INDEX, GGS_END)  # type: ignore[misc]
    with pytest.raises(TypeError):
        pme_report(fund, GGS_INDEX, as_of=GGS_END, **POLICY)  # type: ignore[call-arg]


def test_only_value_errors_become_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a bug, not a refusal")

    monkeypatch.setattr(report_module, "ks_pme", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        _ggs()


def test_report_is_frozen_and_its_hash_ignores_flow_order() -> None:
    report = _ggs()
    with pytest.raises(ValidationError):
        report.fund_name = "other"  # type: ignore[misc]
    shuffled = _report(
        _fund(list(reversed(GGS_ROWS)), (GGS_END, 75.0), name="GGS"), GGS_INDEX, as_of=GGS_END
    )
    assert shuffled.input_hash == report.input_hash
    assert _ggs(day_count="ACT/365.25").input_hash != report.input_hash
    assert report.engine_version == "pme-v1"
