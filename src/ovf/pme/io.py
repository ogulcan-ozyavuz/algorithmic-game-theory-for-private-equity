"""CSV loaders for fund flows, index levels and NAV observations.

Every loader is told its columns and conventions; nothing is guessed. Dates are ISO
``YYYY-MM-DD`` only (no locale formats, no week or compact ISO forms). Numbers are plain
ASCII decimals (optional sign, point and exponent), parsed with ``float()``, and must be
finite. ``source`` is a path (read as UTF-8) or an open text stream; one leading UTF-8
byte-order mark is dropped from either.

Parsing is strict. The header is line 1 and names every column once: a repeated name,
in any column, is refused because picking one of the copies would be a guess. Quoting is
checked in every field, ignored columns included; an unterminated quote is refused rather
than allowed to swallow the rows after it. A quoted field may span lines (RFC 4180); a
record's line is the line it starts on. A field longer than the ``csv`` module's field
size limit is refused (the limit is not raised). Every refusal is a ``ValueError`` naming
the file (when there is one) and the line: an unopenable path, undecodable bytes, an
empty or header-only file, a missing column and a malformed row alike.

The loaders return the model tuples the engine consumes (``CashFlow``, ``IndexLevel``,
``NavObservation``); building the ``FundCashFlows`` or ``BenchmarkIndex`` (name, currency,
basis, return basis) stays an explicit step for the caller.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
from collections import Counter
from collections.abc import Iterator
from datetime import date
from typing import IO, Literal, get_args

from ovf.pme.benchmark import IndexLevel
from ovf.pme.flows import CashFlow, FlowKind, NavObservation

SignConvention = Literal["typed", "signed_lp"]
"""How a flows file encodes the kind of each flow.

``"typed"``: a kind column holding ``contribution`` or ``distribution`` and a strictly
positive amount. ``"signed_lp"``: no kind column; the amount is signed from the LP's side,
negative for a contribution (cash paid in) and positive for a distribution."""

CsvSource = str | os.PathLike[str] | IO[str]

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_BOM = "﻿"


def parse_iso_date(text: str, *, what: str) -> date:
    """``text`` as a calendar date written ``YYYY-MM-DD``; anything else is refused.

    ``date.fromisoformat`` alone would also accept ``20210101`` and ``2021-W01-1``; a
    loader that silently accepts several spellings invites misreading, so only the one
    unambiguous form is taken.
    """
    if not isinstance(text, str):
        raise ValueError(
            f"{what}: {text!r} is a {type(text).__name__}, not text; expected an ISO date "
            "written YYYY-MM-DD"
        )
    stripped = text.strip()
    if not _ISO_DATE.fullmatch(stripped):
        raise ValueError(f"{what}: {text!r} is not an ISO date written YYYY-MM-DD")
    try:
        return date.fromisoformat(stripped)
    except ValueError as exc:
        raise ValueError(f"{what}: {text!r} is not a valid calendar date") from exc


def _parse_number(text: str, *, what: str) -> float:
    stripped = text.strip()
    try:
        value = float(stripped)
    except ValueError as exc:
        raise ValueError(f"{what}: {text!r} is not a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{what}: {text!r} is not a finite number")
    if not _DECIMAL.fullmatch(stripped):
        # float() also takes digit-group underscores and non-ASCII digits.
        raise ValueError(
            f"{what}: {text!r} is not a plain decimal number (ASCII digits with an optional "
            "sign, point and exponent)"
        )
    return value


class _Lines:
    """The source's physical lines, counted, as text, with one leading BOM dropped."""

    def __init__(self, lines: Iterator[object], place: str) -> None:
        self._lines = lines
        self.place = place
        self.count = 0

    def __iter__(self) -> _Lines:
        return self

    def __next__(self) -> str:
        number = self.count + 1
        try:
            line = next(self._lines)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"{self.place} line {number}: the stream cannot be decoded as text ({exc})"
            ) from exc
        except OSError as exc:
            raise ValueError(f"{self.place} line {number}: reading failed ({exc})") from exc
        if not isinstance(line, str):
            raise ValueError(
                f"{self.place} line {number}: the stream yields {type(line).__name__}, not "
                "text; open the file in text mode (encoding='utf-8', newline='')"
            )
        if number == 1 and line.startswith(_BOM):
            line = line[len(_BOM) :]
        self.count = number
        return line


def _read_path(path: str | os.PathLike[str] | os.PathLike[bytes], place: str) -> str:
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        raise ValueError(f"{place}: cannot open the file: {reason}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = len(_LINE_BREAK.split(data[: exc.start].decode("utf-8")))
        raise ValueError(
            f"{place} line {line}: the file is not valid UTF-8 ({exc.reason} at byte "
            f"offset {exc.start})"
        ) from exc


def _lines(source: object, label: str) -> _Lines:
    if isinstance(source, str | os.PathLike):
        place = f"{label} {os.fsdecode(source)!r}"
        return _Lines(iter(io.StringIO(_read_path(source, place), newline="")), place)
    if isinstance(source, bytes | bytearray | memoryview) or not hasattr(source, "read"):
        raise ValueError(
            f"{label}: the source must be a path or an open text stream, got "
            f"{type(source).__name__}"
        )
    name = getattr(source, "name", None)
    place = f"{label} {name!r}" if isinstance(name, str) else label
    if isinstance(source, io.RawIOBase | io.BufferedIOBase):
        raise ValueError(
            f"{place}: the stream is binary; open the file in text mode "
            "(encoding='utf-8', newline='')"
        )
    try:
        lines = iter(source)  # type: ignore[call-overload]
    except TypeError as exc:
        raise ValueError(f"{place}: the stream cannot be iterated line by line") from exc
    return _Lines(lines, place)


def _csv_refusal(place: str, start: int, end: int, exc: csv.Error) -> str:
    message = str(exc)
    if message == "unexpected end of data":
        return (
            f"{place} line {start}: a quoted field in the record starting on line {start} "
            f"is never closed (still open at the end of the file, line {end}); the lines "
            "after the quote cannot be read as rows"
        )
    if message.startswith("field larger than field limit"):
        return (
            f"{place} line {start}: a field is longer than the CSV parser's limit of "
            f"{csv.field_size_limit()} characters; refused rather than read with a raised limit"
        )
    span = "" if end == start else f" (the record ends on line {end})"
    return f"{place} line {start}: malformed CSV{span}: {message}"


def _check_columns(label: str, columns: dict[str, object]) -> list[str]:
    """The column names, each a non-empty string and all different."""
    names: list[str] = []
    for parameter, column in columns.items():
        if not isinstance(column, str) or not column:
            raise ValueError(
                f"{label}: {parameter} must be a non-empty column name, got {column!r}"
            )
        names.append(column)
    if len(set(names)) != len(names):
        raise ValueError(f"{label}: {', '.join(columns)} must name different columns, got {names}")
    return names


def _records(
    source: object, required: list[str], label: str
) -> tuple[str, list[tuple[int, dict[str, str]]]]:
    """Where the data came from, and ``(line, row)`` for every data row."""
    lines = _lines(source, label)
    place = lines.place
    reader = csv.reader(lines, strict=True)

    def record() -> tuple[int, list[str]] | None:
        start = lines.count + 1
        try:
            fields = next(reader)
        except StopIteration:
            return None
        except csv.Error as exc:
            raise ValueError(_csv_refusal(place, start, lines.count, exc)) from exc
        return start, fields

    first = record()
    if first is None:
        raise ValueError(f"{place} line 1: the file is empty; expected a header with {required}")
    header = first[1]
    if not header:
        raise ValueError(
            f"{place} line 1: the line is blank; the header with {required} must be the first line"
        )
    counts = Counter(header)
    duplicates = [name for name in counts if counts[name] > 1]
    if duplicates:
        raise ValueError(
            f"{place} line 1: duplicate column name(s) {duplicates} in the header {header}; "
            "each column must be named once (choosing one of the copies would be a guess)"
        )
    missing = [column for column in required if column not in counts]
    if missing:
        raise ValueError(f"{place} line 1: missing column(s) {missing}; the header has {header}")
    rows: list[tuple[int, dict[str, str]]] = []
    while (parsed := record()) is not None:
        line, fields = parsed
        if not fields:
            continue  # a blank line
        if len(fields) > len(header):
            raise ValueError(
                f"{place} line {line}: more fields ({len(fields)}) than the header ({len(header)})"
            )
        if len(fields) < len(header):
            raise ValueError(
                f"{place} line {line}: fewer fields ({len(fields)}) than the header ({len(header)})"
            )
        rows.append((line, dict(zip(header, fields, strict=True))))
    if not rows:
        raise ValueError(
            f"{place} line 1: no data rows after the header (the file ends after line "
            f"{lines.count})"
        )
    return place, rows


def read_flows_csv(
    source: CsvSource,
    *,
    date_column: str,
    amount_column: str,
    kind_column: str | None,
    sign_convention: SignConvention,
) -> tuple[CashFlow, ...]:
    """Contributions and distributions from a CSV file, in file order.

    ``sign_convention="typed"`` needs ``kind_column`` (values ``contribution`` or
    ``distribution``) and positive amounts; a negative amount is refused rather than
    reinterpreted. ``sign_convention="signed_lp"`` needs ``kind_column=None``: a negative
    amount is a contribution of its absolute value, a positive one a distribution. A zero
    amount is refused under both conventions (it is not a flow).
    """
    if sign_convention not in get_args(SignConvention):
        raise ValueError(
            f"sign_convention must be one of {list(get_args(SignConvention))}, got "
            f"{sign_convention!r}"
        )
    if sign_convention == "typed" and kind_column is None:
        raise ValueError("sign_convention='typed' needs kind_column: the kind gives the sign")
    if sign_convention == "signed_lp" and kind_column is not None:
        raise ValueError(
            "sign_convention='signed_lp' takes kind_column=None: the amount's sign gives the "
            "kind, so a kind column would be a second, possibly contradicting, source"
        )
    columns: dict[str, object] = {"date_column": date_column, "amount_column": amount_column}
    if kind_column is not None:
        columns["kind_column"] = kind_column
    required = _check_columns("flows CSV", columns)
    place, records = _records(source, required, "flows CSV")
    flows: list[CashFlow] = []
    for line, record in records:
        where = f"{place} line {line}"
        day = parse_iso_date(record[date_column], what=f"{where}, column {date_column!r}")
        amount = _parse_number(record[amount_column], what=f"{where}, column {amount_column!r}")
        if amount == 0.0:
            raise ValueError(f"{where}: the amount is zero; a zero amount is not a flow")
        kind: FlowKind
        if kind_column is not None:
            text = record[kind_column].strip()
            if text not in ("contribution", "distribution"):
                raise ValueError(
                    f"{where}, column {kind_column!r}: {text!r} must be 'contribution' or "
                    "'distribution'"
                )
            if amount < 0:
                raise ValueError(
                    f"{where}: amount {amount!r} is negative; typed flows carry positive "
                    "amounts and the kind gives the sign (use sign_convention='signed_lp' "
                    "for signed amounts)"
                )
            kind = "contribution" if text == "contribution" else "distribution"
        else:
            kind = "contribution" if amount < 0 else "distribution"
        try:
            flows.append(CashFlow(date=day, kind=kind, amount=abs(amount)))
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    return tuple(flows)


def read_index_csv(
    source: CsvSource, *, date_column: str, level_column: str
) -> tuple[IndexLevel, ...]:
    """Index levels from a CSV file, in file order (``BenchmarkIndex`` sorts them)."""
    required = _check_columns(
        "index CSV", {"date_column": date_column, "level_column": level_column}
    )
    place, records = _records(source, required, "index CSV")
    levels: list[IndexLevel] = []
    for line, record in records:
        where = f"{place} line {line}"
        day = parse_iso_date(record[date_column], what=f"{where}, column {date_column!r}")
        level = _parse_number(record[level_column], what=f"{where}, column {level_column!r}")
        try:
            levels.append(IndexLevel(date=day, level=level))
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    return tuple(levels)


def read_nav_csv(
    source: CsvSource, *, date_column: str, value_column: str
) -> tuple[NavObservation, ...]:
    """NAV observations from a CSV file, in file order."""
    required = _check_columns("NAV CSV", {"date_column": date_column, "value_column": value_column})
    place, records = _records(source, required, "NAV CSV")
    observations: list[NavObservation] = []
    for line, record in records:
        where = f"{place} line {line}"
        day = parse_iso_date(record[date_column], what=f"{where}, column {date_column!r}")
        value = _parse_number(record[value_column], what=f"{where}, column {value_column!r}")
        try:
            observations.append(NavObservation(date=day, value=value))
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    return tuple(observations)
