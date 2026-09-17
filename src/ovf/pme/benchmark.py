"""Benchmark index levels and the lookup that dates them against fund flows.

A public-market equivalent compares fund flows with an index bought and sold on the same
dates, so every flow date needs an index level. This module holds the levels and the one
lookup rule that picks them. The lookup never looks forward and never interpolates: a
level dated after the requested date is never used, and a date the policy cannot serve is
refused with ``ValueError`` naming it.

The index's return basis is stated, never inferred. A price-return index omits dividends,
so every PME against it overstates the fund's relative performance; it is allowed, and
``benchmark_assumptions`` says so in every result that uses it. There is no FX: the index
currency must equal the fund currency, and the PME functions refuse a mismatch.
"""

from __future__ import annotations

import bisect
import sys
from datetime import date, datetime
from typing import Literal, get_args

from pydantic import ConfigDict, Field, field_validator

from ovf.core.types import FinancialBaseModel
from ovf.pme.flows import PlainDate

ReturnBasis = Literal["total_return_gross", "total_return_net", "price_return"]
IndexLookup = Literal["exact", "last_on_or_before"]

_RETURN_BASIS_TEXT: dict[str, str] = {
    "total_return_gross": (
        "Benchmark return basis: total_return_gross (dividends reinvested gross of "
        "withholding tax)."
    ),
    "total_return_net": (
        "Benchmark return basis: total_return_net (dividends reinvested net of withholding tax)."
    ),
    "price_return": (
        "Benchmark return basis: price_return. WARNING: a price index omits dividends, so "
        "every PME against it overstates the fund's performance relative to an investable "
        "total-return position."
    ),
}


class IndexLevel(FinancialBaseModel):
    """One index level, observed at the end of ``date``.

    ``level`` must be a normal float (at least ``sys.float_info.min``): growth ratios
    ``I_T / I_t`` of subnormal levels lose precision or underflow. ``date`` is a plain
    date; a ``datetime`` is refused, since a level is an end-of-day close.
    """

    model_config = ConfigDict(frozen=True)

    date: PlainDate
    level: float = Field(gt=0.0)

    @field_validator("level")
    @classmethod
    def _normal_level(cls, level: float) -> float:
        if level < sys.float_info.min:
            raise ValueError(
                f"index level {level!r} is subnormal (below {sys.float_info.min!r}); growth "
                "ratios of such levels lose precision or underflow, so rescale the index"
            )
        return level


class BenchmarkIndex(FinancialBaseModel):
    """A dated index series with its currency and stated return basis.

    ``levels`` is stored in ascending date order whatever the input order; two levels on
    one date are refused, because choosing between them would be a guess.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    return_basis: ReturnBasis
    levels: tuple[IndexLevel, ...] = Field(min_length=1)

    @field_validator("levels")
    @classmethod
    def _ascending_unique_dates(cls, levels: tuple[IndexLevel, ...]) -> tuple[IndexLevel, ...]:
        ordered = tuple(sorted(levels, key=lambda item: item.date))
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if earlier.date == later.date:
                raise ValueError(
                    f"duplicate index date {later.date.isoformat()}: one level per date; "
                    "remove or correct the duplicate observation"
                )
        return ordered


class IndexLookupRecord(FinancialBaseModel):
    """Which level was used for a requested date, and how stale it was."""

    model_config = ConfigDict(frozen=True)

    requested: PlainDate
    used: PlainDate
    level: float = Field(gt=0.0)
    gap_days: int = Field(ge=0)


def _level_date(item: IndexLevel) -> date:
    return item.date


def _require_gap(lookup: str, max_gap_days: int) -> None:
    if lookup not in get_args(IndexLookup):
        raise ValueError(f"lookup must be one of {list(get_args(IndexLookup))}, got {lookup!r}")
    if isinstance(max_gap_days, bool) or not isinstance(max_gap_days, int):
        raise ValueError(f"max_gap_days must be an integer, got {type(max_gap_days).__name__}")
    if max_gap_days < 0:
        raise ValueError(f"max_gap_days must be >= 0, got {max_gap_days}")
    if lookup == "exact" and max_gap_days != 0:
        raise ValueError(
            f"lookup 'exact' uses no gap, so max_gap_days must be 0, got {max_gap_days}; "
            "use 'last_on_or_before' to allow a stale level"
        )


def index_level(
    benchmark: BenchmarkIndex, on: date, *, lookup: IndexLookup, max_gap_days: int
) -> IndexLookupRecord:
    """The index level used for flows dated ``on``.

    ``"exact"`` requires a level dated ``on`` and ``max_gap_days == 0``.
    ``"last_on_or_before"`` uses the latest level dated on or before ``on`` provided
    ``(on - used).days <= max_gap_days``. A level dated after ``on`` is never used, even
    when it is the only one; nothing is interpolated. Raises ``ValueError`` naming ``on``
    when the policy cannot serve it.
    """
    if not isinstance(benchmark, BenchmarkIndex):
        raise ValueError(f"benchmark must be a BenchmarkIndex, got {type(benchmark).__name__}")
    if isinstance(on, datetime) or not isinstance(on, date):
        raise ValueError(
            "on must be a datetime.date (not a datetime: a level is an end-of-day close), "
            f"got {type(on).__name__}"
        )
    _require_gap(lookup, max_gap_days)
    levels = benchmark.levels
    position = bisect.bisect_right(levels, on, key=_level_date) - 1
    if position < 0:
        raise ValueError(
            f"benchmark '{benchmark.name}' has no level on or before {on.isoformat()} "
            f"(first level is {levels[0].date.isoformat()}); levels are never taken from a "
            "later date"
        )
    found = benchmark.levels[position]
    gap = (on - found.date).days
    if lookup == "exact" and gap != 0:
        raise ValueError(
            f"benchmark '{benchmark.name}' has no level dated {on.isoformat()} "
            f"(latest earlier level is {found.date.isoformat()}); lookup 'exact' requires "
            "one, or state 'last_on_or_before' with a max_gap_days"
        )
    if gap > max_gap_days:
        raise ValueError(
            f"benchmark '{benchmark.name}' has no level within {max_gap_days} days on or "
            f"before {on.isoformat()} (latest is {found.date.isoformat()}, {gap} days "
            "earlier); supply the level or state a larger max_gap_days"
        )
    return IndexLookupRecord(requested=on, used=found.date, level=found.level, gap_days=gap)


def benchmark_assumptions(
    benchmark: BenchmarkIndex, *, lookup: IndexLookup, max_gap_days: int
) -> list[str]:
    """Assumption lines every PME result against ``benchmark`` carries.

    States the return basis (with the price-return warning), the lookup policy and its
    maximum gap, and the end-of-day timing of a level.
    """
    if not isinstance(benchmark, BenchmarkIndex):
        raise ValueError(f"benchmark must be a BenchmarkIndex, got {type(benchmark).__name__}")
    _require_gap(lookup, max_gap_days)
    if lookup == "exact":
        policy = (
            "Index lookup: exact; every flow date and the as-of date must have an index "
            "level dated that day (max_gap_days 0)."
        )
    else:
        policy = (
            "Index lookup: last_on_or_before with max_gap_days "
            f"{max_gap_days}; the latest level dated on or before the flow date is used, "
            "never a later level and never an interpolated one."
        )
    return [
        f"Benchmark '{benchmark.name}' in {benchmark.currency}.",
        _RETURN_BASIS_TEXT[benchmark.return_basis],
        policy,
        "An index level dated d is the end-of-day close of d and applies to every flow "
        "dated d and to a NAV dated d.",
    ]
