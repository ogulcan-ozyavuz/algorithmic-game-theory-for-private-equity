"""Benchmark index levels and the no-look-forward lookup in `ovf.pme.benchmark`."""

from __future__ import annotations

import math
import sys
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from ovf.pme.benchmark import (
    BenchmarkIndex,
    IndexLevel,
    IndexLookupRecord,
    benchmark_assumptions,
    index_level,
)

D0 = date(2021, 1, 1)
D1 = date(2021, 3, 31)
D2 = date(2021, 6, 30)


def _index(*levels: tuple[date, float], basis: str = "total_return_net") -> BenchmarkIndex:
    return BenchmarkIndex(
        name="MSCI World NR",
        currency="USD",
        return_basis=basis,  # type: ignore[arg-type]
        levels=tuple(IndexLevel(date=d, level=v) for d, v in levels),
    )


INDEX = _index((D0, 100.0), (D1, 120.0), (D2, 150.0))


# --- Exact lookup -----------------------------------------------------------------


def test_exact_hit_returns_the_level_with_zero_gap() -> None:
    record = index_level(INDEX, D1, lookup="exact", max_gap_days=0)
    assert record == IndexLookupRecord(requested=D1, used=D1, level=120.0, gap_days=0)


def test_exact_miss_is_refused_naming_the_date() -> None:
    with pytest.raises(ValueError, match="2021-04-01"):
        index_level(INDEX, date(2021, 4, 1), lookup="exact", max_gap_days=0)


def test_exact_with_a_gap_is_refused() -> None:
    # 'exact' allows no staleness; a non-zero gap is a contradictory policy, not a hint.
    with pytest.raises(ValueError, match="max_gap_days must be 0"):
        index_level(INDEX, D1, lookup="exact", max_gap_days=5)


# --- last_on_or_before ------------------------------------------------------------


def test_last_on_or_before_within_the_gap_uses_the_earlier_level() -> None:
    # 2021-04-05 is 5 days after the D1 level (2021-03-31).
    record = index_level(INDEX, date(2021, 4, 5), lookup="last_on_or_before", max_gap_days=5)
    assert record.used == D1
    assert record.level == 120.0
    assert record.gap_days == 5
    assert record.requested == date(2021, 4, 5)


def test_last_on_or_before_on_an_observed_date_has_zero_gap() -> None:
    record = index_level(INDEX, D2, lookup="last_on_or_before", max_gap_days=3)
    assert (record.used, record.level, record.gap_days) == (D2, 150.0, 0)


def test_last_on_or_before_beyond_the_gap_is_refused_naming_the_date() -> None:
    # 6 days > 5 allowed.
    with pytest.raises(ValueError, match=r"2021-04-06.*6 days"):
        index_level(INDEX, date(2021, 4, 6), lookup="last_on_or_before", max_gap_days=5)


def test_last_on_or_before_after_the_last_level_is_stale_not_extrapolated() -> None:
    record = index_level(INDEX, date(2021, 7, 2), lookup="last_on_or_before", max_gap_days=2)
    assert (record.used, record.level) == (D2, 150.0)
    with pytest.raises(ValueError, match="2021-07-03"):
        index_level(INDEX, date(2021, 7, 3), lookup="last_on_or_before", max_gap_days=2)


def test_never_looks_forward_even_when_the_later_level_is_the_only_one() -> None:
    only_later = _index((D1, 120.0))
    for lookup, gap in (("exact", 0), ("last_on_or_before", 10_000)):
        with pytest.raises(ValueError, match="2021-01-01"):
            index_level(only_later, D0, lookup=lookup, max_gap_days=gap)  # type: ignore[arg-type]


def test_never_looks_forward_when_a_closer_later_level_exists() -> None:
    # 2021-03-30 is 1 day before D1 but 88 days after D0: only D0 may be used.
    record = index_level(INDEX, date(2021, 3, 30), lookup="last_on_or_before", max_gap_days=88)
    assert (record.used, record.level, record.gap_days) == (D0, 100.0, 88)
    with pytest.raises(ValueError, match="2021-03-30"):
        index_level(INDEX, date(2021, 3, 30), lookup="last_on_or_before", max_gap_days=87)


# --- Policy arguments -------------------------------------------------------------


def test_negative_max_gap_days_is_refused() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        index_level(INDEX, D1, lookup="last_on_or_before", max_gap_days=-1)


@pytest.mark.parametrize("gap", [True, 1.0, "1"])
def test_non_integer_max_gap_days_is_refused(gap: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        index_level(INDEX, D1, lookup="last_on_or_before", max_gap_days=gap)  # type: ignore[arg-type]


def test_unknown_lookup_is_refused() -> None:
    with pytest.raises(ValueError, match="lookup must be one of"):
        index_level(INDEX, D1, lookup="nearest", max_gap_days=0)  # type: ignore[arg-type]


def test_policy_arguments_are_keyword_only_without_defaults() -> None:
    with pytest.raises(TypeError):
        index_level(INDEX, D1, "exact", 0)  # type: ignore[misc]
    with pytest.raises(TypeError):
        index_level(INDEX, D1)  # type: ignore[call-arg]


# --- Model validation -------------------------------------------------------------


def test_unsorted_levels_are_stored_ascending() -> None:
    shuffled = _index((D2, 150.0), (D0, 100.0), (D1, 120.0))
    assert [item.date for item in shuffled.levels] == [D0, D1, D2]
    assert shuffled == INDEX


def test_duplicate_index_dates_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate index date 2021-03-31"):
        _index((D0, 100.0), (D1, 120.0), (D1, 121.0))


def test_duplicate_date_with_equal_levels_is_still_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        _index((D1, 120.0), (D1, 120.0))


@pytest.mark.parametrize("level", [0.0, -1.0, math.nan, math.inf])
def test_non_positive_or_non_finite_level_is_refused(level: float) -> None:
    with pytest.raises(ValidationError):
        IndexLevel(date=D0, level=level)


def test_empty_series_blank_name_and_blank_currency_are_refused() -> None:
    with pytest.raises(ValidationError):
        BenchmarkIndex(name="X", currency="USD", return_basis="price_return", levels=())
    with pytest.raises(ValidationError):
        BenchmarkIndex(name="", currency="USD", return_basis="price_return", levels=INDEX.levels)
    with pytest.raises(ValidationError):
        BenchmarkIndex(name="X", currency="", return_basis="price_return", levels=INDEX.levels)


def test_return_basis_must_be_stated_and_known() -> None:
    with pytest.raises(ValidationError):
        BenchmarkIndex(name="X", currency="USD", levels=INDEX.levels)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BenchmarkIndex(
            name="X",
            currency="USD",
            return_basis="total_return",  # type: ignore[arg-type]
            levels=INDEX.levels,
        )


def test_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        INDEX.name = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        INDEX.levels[0].level = 1.0  # type: ignore[misc]
    record = index_level(INDEX, D0, lookup="exact", max_gap_days=0)
    with pytest.raises(ValidationError):
        record.level = 1.0  # type: ignore[misc]


# --- Float range, datetime and long series (reviewer R1) --------------------------


def test_subnormal_level_is_refused_and_the_smallest_normal_is_accepted() -> None:
    # A subnormal level (below sys.float_info.min) makes I_T / I_t lose precision or
    # underflow, e.g. a constant 1e-323 index silently turned KS 1.1 into 1.
    with pytest.raises(ValidationError, match="subnormal"):
        IndexLevel(date=D0, level=1e-320)
    assert IndexLevel(date=D0, level=sys.float_info.min).level == sys.float_info.min


def test_datetime_is_refused_as_lookup_date_and_as_level_date() -> None:
    with pytest.raises(ValueError, match="datetime"):
        index_level(INDEX, datetime(2021, 3, 31), lookup="exact", max_gap_days=0)
    with pytest.raises(ValidationError, match="datetime"):
        IndexLevel(date=datetime(2021, 3, 31), level=1.0)


def test_lookups_on_a_long_series_bisect_the_stored_levels() -> None:
    # 100,000 daily levels and 2,000 lookups: each lookup bisects the stored tuple rather
    # than copying the dates (the copy made this quadratic).
    levels = tuple(IndexLevel(date=D0 + timedelta(days=i), level=100.0) for i in range(100_000))
    index = BenchmarkIndex(name="X", currency="USD", return_basis="price_return", levels=levels)
    for i in range(0, 100_000, 50):
        on = D0 + timedelta(days=i)
        assert index_level(index, on, lookup="exact", max_gap_days=0).used == on


# --- Assumption lines -------------------------------------------------------------


def test_price_return_basis_carries_the_dividend_warning() -> None:
    price = _index((D0, 100.0), basis="price_return")
    lines = " ".join(benchmark_assumptions(price, lookup="exact", max_gap_days=0))
    assert "price_return" in lines
    assert "omits dividends" in lines and "overstates" in lines


@pytest.mark.parametrize("basis", ["total_return_gross", "total_return_net"])
def test_total_return_basis_is_stated_without_the_warning(basis: str) -> None:
    lines = " ".join(
        benchmark_assumptions(_index((D0, 1.0), basis=basis), lookup="exact", max_gap_days=0)
    )
    assert basis in lines
    assert "WARNING" not in lines


def test_assumptions_state_the_lookup_gap_and_end_of_day_timing() -> None:
    lines = " ".join(benchmark_assumptions(INDEX, lookup="last_on_or_before", max_gap_days=4))
    assert "last_on_or_before" in lines and "max_gap_days 4" in lines
    assert "end-of-day" in lines
    assert "USD" in lines


@pytest.mark.parametrize("stamp", [datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=UTC)])
def test_lookup_records_refuse_datetime(stamp: datetime) -> None:
    # R3-11, contract §13.6: IndexLookupRecord coerced midnight datetimes before.
    with pytest.raises(ValidationError, match="not a datetime"):
        IndexLookupRecord(requested=stamp, used=D0, level=1.0, gap_days=0)
    with pytest.raises(ValidationError, match="not a datetime"):
        IndexLookupRecord(requested=D0, used=stamp, level=1.0, gap_days=0)
    with pytest.raises(ValidationError, match="not a datetime"):
        IndexLevel(date=stamp, level=1.0)
