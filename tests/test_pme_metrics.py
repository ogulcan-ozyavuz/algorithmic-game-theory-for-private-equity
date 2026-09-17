"""DPI, RVPI and TVPI from resolved flows, asserted against `ovf.pme.metrics`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from ovf.pme.flows import (
    ENGINE_VERSION,
    CashFlow,
    FundCashFlows,
    NavObservation,
    ResolvedCashFlows,
    resolve,
)
from ovf.pme.metrics import Multiples, multiples

D0 = date(2020, 1, 1)
D1 = date(2021, 1, 1)
D2 = date(2022, 1, 1)
D3 = date(2023, 1, 1)


def _fund(
    flows: list[tuple[date, str, float]],
    nav: tuple[date, float] | None,
    *,
    name: str = "Fund I",
) -> FundCashFlows:
    return FundCashFlows(
        name=name,
        currency="USD",
        basis="net_lp",
        flows=tuple(CashFlow(date=d, kind=k, amount=a) for d, k, a in flows),  # type: ignore[arg-type]
        nav=None if nav is None else NavObservation(date=nav[0], value=nav[1]),
    )


def _resolved(
    flows: list[tuple[date, str, float]],
    nav: tuple[date, float] | None,
    *,
    as_of: date = D3,
) -> ResolvedCashFlows:
    return resolve(_fund(flows, nav), as_of=as_of, stale_nav="refuse")


# Paid in 100 + 50 = 150; distributed 30 + 60 = 90; NAV 120 at D3.
HAND_FLOWS = [
    (D0, "contribution", 100.0),
    (D1, "contribution", 50.0),
    (D2, "distribution", 30.0),
    (D3, "distribution", 60.0),
]


def test_hand_computed_multiples() -> None:
    result = multiples(_resolved(HAND_FLOWS, (D3, 120.0)))
    # DPI = 90 / 150 = 0.6; RVPI = 120 / 150 = 0.8; TVPI = (90 + 120) / 150 = 1.4.
    assert result.as_of == D3
    assert (result.paid_in, result.distributed, result.residual_value) == (150.0, 90.0, 120.0)
    assert result.dpi == pytest.approx(0.6, rel=1e-15)
    assert result.rvpi == pytest.approx(0.8, rel=1e-15)
    assert result.tvpi == pytest.approx(1.4, rel=1e-15)
    assert result.identity_residual == pytest.approx(0.0, abs=1e-15)
    assert result.nav_source == "reported_at_as_of"
    assert result.engine_version == ENGINE_VERSION


def test_fully_realised_fund_has_tvpi_equal_to_dpi() -> None:
    # NAV 0 stated explicitly: RVPI 0, TVPI = DPI = 90 / 150.
    result = multiples(_resolved(HAND_FLOWS, (D3, 0.0)))
    assert result.rvpi == 0.0
    assert result.tvpi == pytest.approx(result.dpi, rel=1e-15)
    assert result.tvpi == pytest.approx(0.6, rel=1e-15)


def test_multiples_use_gross_sums_not_same_date_nets() -> None:
    # Contribution 40 and distribution 40 on D1 net to zero for discounting, but paid-in
    # is 100 + 40 = 140 and distributed is 40 + 70 = 110.
    flows = [
        (D0, "contribution", 100.0),
        (D1, "contribution", 40.0),
        (D1, "distribution", 40.0),
        (D2, "distribution", 70.0),
    ]
    result = multiples(_resolved(flows, (D3, 28.0)))
    assert (result.paid_in, result.distributed) == (140.0, 110.0)
    assert result.dpi == pytest.approx(110.0 / 140.0, rel=1e-15)
    assert result.tvpi == pytest.approx(138.0 / 140.0, rel=1e-15)


def test_no_residual_value_reports_dpi_only() -> None:
    result = multiples(_resolved(HAND_FLOWS, None))
    assert result.residual_value is None
    assert result.nav_source == "none"
    assert result.dpi == pytest.approx(0.6, rel=1e-15)
    assert result.rvpi is None and result.tvpi is None and result.identity_residual is None
    assert any("RVPI and TVPI are undefined" in line for line in result.assumptions)


def test_distributions_only_series_has_no_multiples() -> None:
    # A series with only distributions has paid_in 0: every ratio is undefined, not inf.
    flows = [(D1, "distribution", 25.0), (D2, "distribution", 5.0)]
    result = multiples(_resolved(flows, (D3, 10.0)))
    assert result.paid_in == 0.0
    assert result.distributed == 30.0
    assert (result.dpi, result.rvpi, result.tvpi, result.identity_residual) == (
        None,
        None,
        None,
        None,
    )
    assert any("Paid-in capital is zero" in line for line in result.assumptions)


def test_rolled_forward_nav_flows_through_with_its_source() -> None:
    # NAV 100 reported at D2; after it, contribution 20 and distribution 30 up to D3:
    # rolled residual = 100 + 20 - 30 = 90.
    flows = [
        (D0, "contribution", 100.0),
        (date(2022, 6, 30), "contribution", 20.0),
        (D3, "distribution", 30.0),
    ]
    resolved = resolve(_fund(flows, (D2, 100.0)), as_of=D3, stale_nav="roll_forward_cash_adjusted")
    result = multiples(resolved)
    assert result.nav_source == "rolled_forward"
    assert result.residual_value == pytest.approx(90.0, rel=1e-15)
    assert result.rvpi == pytest.approx(90.0 / 120.0, rel=1e-15)
    assert result.tvpi == pytest.approx(120.0 / 120.0, rel=1e-15)
    text = " ".join(result.assumptions)
    assert "rolled forward" in text and "2022-01-01" in text


def test_assumptions_carry_resolution_basis_and_nav_source() -> None:
    resolved = _resolved(HAND_FLOWS, (D3, 120.0))
    result = multiples(resolved)
    assert result.assumptions[: len(resolved.assumptions)] == resolved.assumptions
    text = " ".join(result.assumptions)
    assert "net_lp" in text
    assert "NAV source: reported at as_of (2023-01-01)" in text
    assert "gross sums" in text


def test_input_hash_is_stable_across_permuted_flow_inputs() -> None:
    forward = multiples(_resolved(HAND_FLOWS, (D3, 120.0)))
    backward = multiples(_resolved(list(reversed(HAND_FLOWS)), (D3, 120.0)))
    assert forward.input_hash == backward.input_hash
    assert forward == backward
    changed = multiples(_resolved(HAND_FLOWS, (D3, 121.0)))
    assert changed.input_hash != forward.input_hash


def test_result_is_frozen() -> None:
    result = multiples(_resolved(HAND_FLOWS, (D3, 120.0)))
    assert isinstance(result, Multiples)
    with pytest.raises(ValidationError):
        result.tvpi = 2.0  # type: ignore[misc]


def test_representable_multiples_survive_an_overflowing_sum() -> None:
    # Distributed 1e308 plus NAV 1e308 overflows as a sum, but TVPI = 2e308 / 1e308 = 2 is
    # representable: it is computed term by term (math.fsum raised OverflowError before,
    # reviewer R1).
    big = _resolved([(D0, "contribution", 1e308), (D1, "distribution", 1e308)], (D3, 1e308))
    result = multiples(big)
    assert (result.dpi, result.rvpi, result.tvpi) == (1.0, 1.0, 2.0)
    assert any("term by term" in line for line in result.assumptions)


def test_unrepresentable_ratios_are_refused() -> None:
    # DPI = 1e300 / 1e-10 overflows.
    lopsided = _resolved([(D0, "contribution", 1e-10), (D1, "distribution", 1e300)], (D3, 0.0))
    with pytest.raises(ValueError, match="DPI .* overflows"):
        multiples(lopsided)
    # RVPI = 1e-300 / 1e10 underflows below the smallest normal float.
    faint = _resolved([(D0, "contribution", 1e10), (D1, "distribution", 1.0)], (D3, 1e-300))
    with pytest.raises(ValueError, match="RVPI .* underflows"):
        multiples(faint)


def test_gross_legs_and_typed_nav_source() -> None:
    # Contract §11.5/§11.6: the gross-legs convention is stated, nav_source is the literal.
    result = multiples(_resolved(HAND_FLOWS, (D3, 120.0)))
    assert any(line.startswith("Gross legs:") for line in result.assumptions)
    with pytest.raises(ValidationError):
        Multiples.model_validate({**result.model_dump(), "nav_source": "guessed"})


def test_non_resolved_input_is_refused() -> None:
    with pytest.raises(ValueError, match="ResolvedCashFlows"):
        multiples(_fund(HAND_FLOWS, (D3, 120.0)))  # type: ignore[arg-type]


_AMOUNT = st.floats(min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False)


@st.composite
def _random_funds(draw: st.DrawFn) -> ResolvedCashFlows:
    n = draw(st.integers(min_value=1, max_value=12))
    offsets = draw(st.lists(st.integers(min_value=0, max_value=5000), min_size=n, max_size=n))
    kinds = draw(
        st.lists(st.sampled_from(["contribution", "distribution"]), min_size=n, max_size=n)
    )
    amounts = draw(st.lists(_AMOUNT, min_size=n, max_size=n))
    flows = [
        (D0 + timedelta(days=o), k, a) for o, k, a in zip(offsets, kinds, amounts, strict=True)
    ]
    as_of = D0 + timedelta(days=max(offsets))
    # NAVs so small that RVPI = NAV / paid_in falls below the smallest normal float are
    # refused as an underflow (covered by an explicit test); this property is about TVPI.
    nav = draw(st.one_of(st.just(0.0), st.floats(min_value=1e-290, max_value=1e9)))
    return _resolved(flows, (as_of, nav), as_of=as_of)


@settings(max_examples=200, deadline=None)
@given(_random_funds())
def test_tvpi_identity_residual_is_rounding_only(resolved: ResolvedCashFlows) -> None:
    result = multiples(resolved)
    if resolved.paid_in == 0:
        assert result.tvpi is None and result.identity_residual is None
        return
    assert result.tvpi is not None and result.identity_residual is not None
    assert result.dpi is not None and result.rvpi is not None
    # Three correctly rounded divisions and one addition: a few ulps of TVPI at most.
    assert abs(result.identity_residual) <= 1e-15 * max(result.tvpi, 1.0)
    assert result.dpi >= 0 and result.rvpi >= 0
