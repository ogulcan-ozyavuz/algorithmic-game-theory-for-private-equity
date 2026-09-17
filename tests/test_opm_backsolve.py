"""Backsolve: round trips, the refusals, the schedule reuse, and the fixtures in the docs.

Expected numbers are derived in docs/opm-backsolve.md by two routes that do not import
``ovf`` (60-digit Decimal with Newton's method, and scipy's normal CDF with Brent).
"""

from __future__ import annotations

import math
import re

import pytest

import ovf
from ovf.opm import backsolve as backsolve_module
from ovf.opm.allocate import opm_allocate
from ovf.opm.backsolve import MAX_EXPANSIONS, backsolve
from ovf.opm.breakpoints import breakpoint_schedule
from ovf.opm.types import BacksolveError, OpmAssumptionError, OpmInputs
from tests import governance_fixtures as gov
from tests.fixtures import FIXTURES

BY_ID = {f.case_id: f for f in FIXTURES}
M = 1_000_000
DOC_MARKET = {"volatility": 0.60, "time_to_liquidity": 3.0, "risk_free_rate": 0.04}


def price_at(securities, security_id, equity_value, volatility, time, rate=0.04):
    result = opm_allocate(
        securities,
        inputs=OpmInputs(
            equity_value=equity_value,
            volatility=volatility,
            time_to_liquidity=time,
            risk_free_rate=rate,
        ),
    )
    return next(cv.value_per_share for cv in result.class_values if cv.security_id == security_id)


def founders():
    return ovf.common(8_000_000, holder_id="founders", security_id="common")


def series_a(shares):
    return ovf.preferred(
        shares=shares, price=2.50, seniority=2, holder_id="series_a", security_id="series_a"
    )


# --- round trips ----------------------------------------------------------------------

ROUND_TRIP_TABLES = ["F1", "F4", "F5a", "F6", "F7", "F10"]
MARKETS = [(0.30, 1.0), (0.60, 3.0), (1.00, 5.0)]


@pytest.mark.parametrize("case_id", ROUND_TRIP_TABLES)
@pytest.mark.parametrize(("volatility", "time"), MARKETS)
@pytest.mark.parametrize("equity_value", [8e6, 4e7])
def test_round_trip_recovers_the_equity_value_for_every_class(
    case_id, volatility, time, equity_value
):
    """Allocate at S, read one class's price, backsolve on it, and get S back."""
    securities = BY_ID[case_id].securities
    for security in securities:
        price = price_at(securities, security.security_id, equity_value, volatility, time)
        result = backsolve(
            securities,
            security_id=security.security_id,
            price_per_share=price,
            volatility=volatility,
            time_to_liquidity=time,
            risk_free_rate=0.04,
        )
        assert result.equity_value == pytest.approx(equity_value, rel=1e-9)
        assert abs(result.residual) <= 1e-9 * price
        assert result.implied_price_per_share - price == result.residual
        assert result.bracket_low <= result.equity_value <= result.bracket_high
        assert result.monotone_verified


# --- the schedule is a property of the table, not of the equity value -------------------


@pytest.mark.parametrize("case_id", ["F1", "F5a", "F6", "F7"])
def test_the_derived_schedule_does_not_move_with_equity_value(case_id):
    securities = BY_ID[case_id].securities
    schedule = breakpoint_schedule(securities)
    for equity_value in (1e5, 2e7, 5e9):
        derived = opm_allocate(
            securities,
            inputs=OpmInputs(
                equity_value=equity_value,
                volatility=0.6,
                time_to_liquidity=3.0,
                risk_free_rate=0.04,
            ),
        ).schedule
        assert derived == schedule


def test_backsolve_derives_the_schedule_exactly_once(monkeypatch):
    calls = []

    def counting(*args, **kwargs):
        calls.append(1)
        return breakpoint_schedule(*args, **kwargs)

    monkeypatch.setattr(backsolve_module, "breakpoint_schedule", counting)
    securities = BY_ID["F6"].securities
    result = backsolve(securities, security_id="series_b", price_per_share=6.0, **DOC_MARKET)
    assert len(calls) == 1
    assert result.opm.schedule == breakpoint_schedule(securities)
    assert any("derived once" in line for line in result.assumptions)


# --- refusals ----------------------------------------------------------------------------


def test_a_flat_stretch_containing_the_price_is_not_identified():
    """1x non-participating at volatility 1%, r = 0: between the preference and conversion
    Series A receives nothing, so its value sits at exactly $5M ($2.50 a share) across most
    of that tranche, and the round price $2.50 is that level."""
    with pytest.raises(BacksolveError) as info:
        backsolve(
            BY_ID["F1"].securities,
            security_id="series_a",
            price_per_share=2.50,
            volatility=0.01,
            time_to_liquidity=1.0,
            risk_free_rate=0.0,
        )
    message = str(info.value)
    assert "not identified" in message
    assert "tranche in which it receives nothing" in message
    low, high = (
        float(x.replace(",", ""))
        for x in re.search(r"from at least ([\d,.]+) to ([\d,.]+)", message).groups()
    )
    assert 5 * M < low < 6 * M
    assert 23 * M < high < 25 * M


def test_a_flat_stretch_away_from_the_price_is_excluded_from_the_bracket():
    """At volatility 5% and r = 4% Series A's flat level is 2.5 exp(-0.04) = 2.40; the price
    $2.50 lies above it, so the root is identified, but the search bracket contains the flat
    stretch and the bracket handed to Brent must not."""
    result = backsolve(
        BY_ID["F1"].securities,
        security_id="series_a",
        price_per_share=2.50,
        volatility=0.05,
        time_to_liquidity=1.0,
        risk_free_rate=0.04,
    )
    assert result.bracket_low > 12.5 * M
    assert any("Flat stretches away from the target" in line for line in result.assumptions)
    assert result.implied_price_per_share == pytest.approx(2.50, rel=1e-9)


def test_no_bracket_reports_the_range_searched_and_the_prices_found():
    """A 1,000% dividend yield over ten years leaks exp(-100) of equity value away before
    liquidity, so no equity value within 4**40 of the starting scale reaches $2.50."""
    with pytest.raises(BacksolveError) as info:
        backsolve(
            BY_ID["F1"].securities,
            security_id="series_a",
            price_per_share=2.50,
            volatility=0.6,
            time_to_liquidity=10.0,
            risk_free_rate=0.04,
            dividend_yield=10.0,
        )
    message = str(info.value)
    assert message.startswith("No bracket")
    assert f"after {MAX_EXPANSIONS} widenings" in message
    assert "starting scale 25,000,000.00" in message


def test_a_falling_price_is_refused(monkeypatch):
    """No valid table reaches this guard, because the allocation refuses a negative weight
    first; the price function is replaced to exercise it."""

    def dipping(self, equity_value):
        return equity_value / 1e7 - (0.5 if 2.2e7 < equity_value < 2.4e7 else 0.0)

    monkeypatch.setattr(backsolve_module._Pricer, "price", dipping)
    with pytest.raises(BacksolveError, match="falls as equity value rises"):
        backsolve(BY_ID["F1"].securities, security_id="series_a", price_per_share=2.5, **DOC_MARKET)


def test_a_target_missing_from_the_table_says_the_round_must_be_in_it():
    with pytest.raises(BacksolveError, match="must already be in the cap table"):
        backsolve(BY_ID["F1"].securities, security_id="series_b", price_per_share=6.0, **DOC_MARKET)


def test_a_position_without_issued_shares_has_no_price():
    with pytest.raises(BacksolveError, match="holds no issued shares"):
        backsolve(BY_ID["F9"].securities, security_id="pool", price_per_share=1.0, **DOC_MARKET)


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("price_per_share", 0.0, "must be positive"),
        ("price_per_share", -2.5, "must be positive"),
        ("price_per_share", math.nan, "finite"),
        ("volatility", 0.0, "volatility must be positive"),
        ("time_to_liquidity", -1.0, "time_to_liquidity must be positive"),
        ("risk_free_rate", math.inf, "finite"),
    ],
)
def test_invalid_inputs_are_refused(field, value, fragment):
    arguments = {"security_id": "series_a", "price_per_share": 2.5, **DOC_MARKET, field: value}
    with pytest.raises(BacksolveError, match=fragment):
        backsolve(BY_ID["F1"].securities, **arguments)


def test_a_governed_table_backsolves_only_without_its_term():
    """The silent-wrong-answer case the passthrough exists to prevent: without the term the
    README table calibrates to a number; with its mandatory-conversion term it is refused,
    because the payoff steps and the allocation cannot value it."""
    arguments = {"security_id": "series_b", "price_per_share": 6.0, **DOC_MARKET}
    ungoverned = backsolve(gov.TABLE, **arguments)
    assert ungoverned.equity_value > 0
    with pytest.raises(OpmAssumptionError, match="not continuous"):
        backsolve(gov.TABLE, collective_conversion=gov.MAJORITY, **arguments)


def test_the_pre_round_table_returns_a_different_plausible_number_silently():
    """A Series A second closing: 1,000,000 more shares at the same $2.50. Both tables
    calibrate without complaint; only the post-round one describes the company."""
    pre = backsolve(
        (founders(), series_a(2_000_000)),
        security_id="series_a",
        price_per_share=2.50,
        **DOC_MARKET,
    )
    post = backsolve(
        (founders(), series_a(3_000_000)),
        security_id="series_a",
        price_per_share=2.50,
        **DOC_MARKET,
    )
    assert post.equity_value - pre.equity_value > 3 * M


# --- fixtures derived in docs/opm-backsolve.md -------------------------------------------

CENT = 0.005


def common_per_share(result):
    return next(cv.value_per_share for cv in result.opm.class_values if cv.security_id == "common")


def test_b1_one_x_non_participating_series_a_at_2_50():
    result = backsolve(
        BY_ID["F1"].securities, security_id="series_a", price_per_share=2.50, **DOC_MARKET
    )
    assert result.equity_value == pytest.approx(16_120_936.94, abs=CENT)
    assert result.implied_price_per_share == pytest.approx(2.50, rel=1e-12)
    assert common_per_share(result) == pytest.approx(1.3901171173, abs=5e-10)
    assert (result.bracket_low, result.bracket_high) == (12_500_000.0, 50_000_000.0)
    text = " ".join(result.assumptions)
    assert "AICPA Accounting and Valuation Guide" in text
    assert "no conformance" in text
    assert "include the round" in text


def test_b2_participating_with_a_2x_cap_series_a_at_2_50():
    result = backsolve(
        BY_ID["F5a"].securities, security_id="series_a", price_per_share=2.50, **DOC_MARKET
    )
    assert result.equity_value == pytest.approx(11_010_530.23, abs=CENT)
    assert common_per_share(result) == pytest.approx(0.7513162792, abs=5e-10)


SENSITIVITY_VOLS = (0.30, 0.45, 0.60, 0.75, 0.90)
SENSITIVITY_TIMES = (1.0, 2.0, 3.0, 4.0, 5.0)
# docs/opm-backsolve.md §Sensitivity; rows volatility, columns years to liquidity.
SENSITIVITY = (
    (19_669_279, 19_173_554, 19_062_388, 19_118_027, 19_258_079),
    (16_502_125, 16_186_904, 16_506_179, 16_943_130, 17_393_421),
    (14_695_529, 15_342_549, 16_120_937, 16_842_547, 17_497_702),
    (14_306_692, 15_512_506, 16_567_725, 17_478_780, 18_274_327),
    (14_467_557, 16_042_467, 17_315_358, 18_374_599, 19_271_067),
)


def test_sensitivity_table_in_the_docs():
    for volatility, row in zip(SENSITIVITY_VOLS, SENSITIVITY, strict=True):
        for time, expected in zip(SENSITIVITY_TIMES, row, strict=True):
            result = backsolve(
                BY_ID["F1"].securities,
                security_id="series_a",
                price_per_share=2.50,
                volatility=volatility,
                time_to_liquidity=time,
                risk_free_rate=0.04,
            )
            assert result.equity_value == pytest.approx(expected, abs=0.5), (volatility, time)
