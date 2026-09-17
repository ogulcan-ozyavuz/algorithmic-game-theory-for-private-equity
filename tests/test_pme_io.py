"""CSV loaders in `ovf.pme.io`: stated conventions, strict dates, line-numbered refusals."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ovf.pme.benchmark import IndexLevel
from ovf.pme.flows import CashFlow, NavObservation
from ovf.pme.io import parse_iso_date, read_flows_csv, read_index_csv, read_nav_csv

TYPED: dict[str, Any] = {
    "date_column": "date",
    "amount_column": "amount",
    "kind_column": "kind",
    "sign_convention": "typed",
}
SIGNED: dict[str, Any] = {
    "date_column": "date",
    "amount_column": "amount",
    "kind_column": None,
    "sign_convention": "signed_lp",
}


def _text(body: str) -> io.StringIO:
    return io.StringIO(body)


# --- Flows ------------------------------------------------------------------------


def test_typed_flows_from_a_stream() -> None:
    flows = read_flows_csv(
        _text("date,kind,amount\n2021-01-01,contribution,100\n2022-01-01,distribution,30.5\n"),
        **TYPED,
    )
    assert flows == (
        CashFlow(date=date(2021, 1, 1), kind="contribution", amount=100.0),
        CashFlow(date=date(2022, 1, 1), kind="distribution", amount=30.5),
    )


def test_signed_lp_flows_from_a_path(tmp_path: Path) -> None:
    # signed_lp: negative = contribution (cash paid in), positive = distribution.
    path = tmp_path / "flows.csv"
    path.write_text("date,amount\n2021-01-01,-100\n2022-01-01,40\n", encoding="utf-8")
    flows = read_flows_csv(path, **SIGNED)
    assert [(f.date, f.kind, f.amount) for f in flows] == [
        (date(2021, 1, 1), "contribution", 100.0),
        (date(2022, 1, 1), "distribution", 40.0),
    ]
    assert read_flows_csv(str(path), **SIGNED) == flows


def test_byte_order_mark_blank_lines_and_extra_columns_are_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "flows.csv"
    path.write_text(
        "﻿date,amount,memo\n2021-01-01,-1,call 1\n\n2021-06-30, 2 ,dist\n", encoding="utf-8"
    )
    flows = read_flows_csv(path, **SIGNED)
    assert [(f.kind, f.amount) for f in flows] == [("contribution", 1.0), ("distribution", 2.0)]


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ("2021-01-01,contribution,0", "line 2: the amount is zero"),
        ("2021/01/01,contribution,1", "line 2.*YYYY-MM-DD"),
        ("20210101,contribution,1", "line 2.*YYYY-MM-DD"),
        ("01-02-2021,contribution,1", "line 2.*YYYY-MM-DD"),
        ("2021-W01-1,contribution,1", "line 2.*YYYY-MM-DD"),
        ("2021-02-30,contribution,1", "line 2.*calendar date"),
        ("2021-01-01,contribution,1,000", "line 2: more fields"),
        ("2021-01-01,contribution", "line 2: fewer fields"),
        ("2021-01-01,contribution,abc", "line 2.*not a number"),
        ("2021-01-01,contribution,", "line 2.*not a number"),
        ("2021-01-01,contribution,nan", "line 2.*finite"),
        ("2021-01-01,contribution,inf", "line 2.*finite"),
        ("2021-01-01,fee,1", "line 2.*'contribution' or 'distribution'"),
        ("2021-01-01,contribution,-5", "line 2.*negative"),
    ],
)
def test_malformed_typed_rows_are_refused_with_their_line(row: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        read_flows_csv(_text(f"date,kind,amount\n{row}\n"), **TYPED)


def test_the_line_number_counts_from_the_header() -> None:
    body = "date,amount\n2021-01-01,-100\n2021-02-01,5\n2021-03-01,0\n"
    with pytest.raises(ValueError, match="flows CSV line 4: the amount is zero"):
        read_flows_csv(_text(body), **SIGNED)


def test_sign_convention_and_kind_column_must_agree() -> None:
    body = "date,kind,amount\n2021-01-01,contribution,1\n"
    with pytest.raises(ValueError, match="needs kind_column"):
        read_flows_csv(_text(body), **{**TYPED, "kind_column": None})
    with pytest.raises(ValueError, match="kind_column=None"):
        read_flows_csv(_text(body), **{**SIGNED, "kind_column": "kind"})
    with pytest.raises(ValueError, match="sign_convention must be one of"):
        read_flows_csv(_text(body), **{**TYPED, "sign_convention": "signed"})


def test_conventions_and_columns_are_keyword_only_without_defaults() -> None:
    with pytest.raises(TypeError):
        read_flows_csv(_text("date,amount\n"), "date", "amount", None, "signed_lp")  # type: ignore[misc]
    with pytest.raises(TypeError):
        read_flows_csv(_text("date,amount\n"), date_column="date", amount_column="amount")  # type: ignore[call-arg]


def test_missing_columns_empty_files_and_header_only_files_are_refused() -> None:
    with pytest.raises(ValueError, match=r"line 1: missing column\(s\) \['kind'\]"):
        read_flows_csv(_text("date,amount\n2021-01-01,1\n"), **TYPED)
    with pytest.raises(ValueError, match="flows CSV line 1: the file is empty"):
        read_flows_csv(_text(""), **SIGNED)
    with pytest.raises(ValueError, match=r"line 1: no data rows.*ends after line 1\)"):
        read_flows_csv(_text("date,amount\n"), **SIGNED)
    with pytest.raises(ValueError, match=r"line 1: no data rows.*ends after line 3\)"):
        read_flows_csv(_text("date,amount\n\n\n"), **SIGNED)
    with pytest.raises(ValueError, match="line 1: the line is blank"):
        read_flows_csv(_text("\ndate,amount\n2021-01-01,-1\n"), **SIGNED)


# --- Duplicate headers (R3 finding 1) ---------------------------------------------


@pytest.mark.parametrize(
    ("body", "duplicate"),
    [
        # R3 repro_01: the second `amount` used to win (a contribution of 1, not 100).
        ("date,kind,amount,amount\n2021-01-01,contribution,100,1\n", "amount"),
        # ... and a second `kind` reversed the sign (a distribution of 100).
        ("date,kind,kind,amount\n2021-01-01,contribution,distribution,100\n", "kind"),
        # A repeated column the loader does not even read is still refused.
        ("date,kind,amount,memo,memo\n2021-01-01,contribution,100,a,b\n", "memo"),
        ("date,kind,amount,,\n2021-01-01,contribution,100,,\n", ""),
    ],
)
def test_duplicate_header_names_are_refused_on_line_1(body: str, duplicate: str) -> None:
    with pytest.raises(
        ValueError,
        match=rf"flows CSV line 1: duplicate column name\(s\) "
        rf"\['{duplicate}'\]",
    ):
        read_flows_csv(_text(body), **TYPED)


def test_duplicate_headers_are_refused_for_index_and_nav_files() -> None:
    with pytest.raises(ValueError, match=r"index CSV line 1: duplicate.*\['level'\]"):
        read_index_csv(
            _text("date,level,level\n2021-01-01,100,1\n"), date_column="date", level_column="level"
        )
    with pytest.raises(ValueError, match=r"NAV CSV line 1: duplicate.*\['date'\]"):
        read_nav_csv(
            _text("date,date,value\n2021-01-01,2022-01-01,5\n"),
            date_column="date",
            value_column="value",
        )


# --- Strict CSV parsing (R3 finding 2) --------------------------------------------


def test_an_unterminated_quote_does_not_swallow_the_next_row() -> None:
    # R3 repro_02: the open memo quote consumed the distribution; the loader returned
    # only the contribution of 100 (and the CLI reported distributed=0 with exit 0).
    body = 'date,kind,amount,memo\n2021-01-01,contribution,100,"memo\n2022-01-01,distribution,110,done\n'
    with pytest.raises(
        ValueError,
        match=r"flows CSV line 2: a quoted field in the record "
        r"starting on line 2 is never closed.*line 3",
    ):
        read_flows_csv(_text(body), **TYPED)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        # An unfinished quoted amount at the end of the file used to be read as 100.
        ('date,kind,amount\n2021-01-01,contribution,"100', "line 2: a quoted field.*never closed"),
        (
            'date,kind,amount\n2021-01-01,contribution,1\n2021-02-01,distribution,"5\n',
            "line 3: a quoted field.*never closed",
        ),
        ('date,kind,amount,memo\n2021-01-01,contribution,100,"a"b\n', "line 2: malformed CSV"),
        (
            'date,kind,amount,memo\n2021-01-01,contribution,100,"a\nb"c\n',
            r"line 2: malformed CSV \(the record ends on line 3\)",
        ),
    ],
)
def test_malformed_quoting_is_refused_with_its_line(body: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        read_flows_csv(_text(body), **TYPED)


def test_index_and_nav_parsing_is_strict_too() -> None:
    with pytest.raises(ValueError, match="index CSV line 2: a quoted field.*never closed"):
        read_index_csv(
            _text('date,level\n2021-01-01,"100\n2022-01-01,110\n'),
            date_column="date",
            level_column="level",
        )
    with pytest.raises(ValueError, match="NAV CSV line 2: a quoted field.*never closed"):
        read_nav_csv(
            _text('date,value,memo\n2021-01-01,1,"x\n2022-01-01,2,y\n'),
            date_column="date",
            value_column="value",
        )


def test_a_closed_multi_line_quoted_field_is_one_record_counted_from_its_first_line() -> None:
    body = 'date,amount,memo\n2021-01-01,-1,"two\nlines"\n2021-02-01,3,x\n'
    assert [f.amount for f in read_flows_csv(_text(body), **SIGNED)] == [1.0, 3.0]
    # Header line 1, the memo record lines 2-3, then lines 4 and 5.
    with pytest.raises(ValueError, match="flows CSV line 5: the amount is zero"):
        read_flows_csv(_text(body + "2021-03-01,0,y\n"), **SIGNED)


def test_a_field_over_the_parser_limit_is_refused_and_the_limit_is_not_raised() -> None:
    limit = csv.field_size_limit()
    body = f"date,kind,amount,memo\n2021-01-01,contribution,100,{'x' * (limit + 1)}\n"
    with pytest.raises(ValueError, match=rf"flows CSV line 2: .*limit of {limit} characters"):
        read_flows_csv(_text(body), **TYPED)
    assert csv.field_size_limit() == limit


# --- Every failure is a located ValueError (R3 finding 3) -------------------------


def test_unopenable_paths_are_refused_naming_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(
        ValueError,
        match=rf"flows CSV {re.escape(repr(str(missing)))}: "
        "cannot open the file",
    ):
        read_flows_csv(missing, **SIGNED)
    with pytest.raises(ValueError, match="cannot open the file"):
        read_flows_csv(str(missing), **SIGNED)
    with pytest.raises(ValueError, match=rf"{re.escape(repr(str(tmp_path)))}: cannot open"):
        read_index_csv(tmp_path, date_column="date", level_column="level")


def test_path_refusals_name_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "flows.csv"
    path.write_text("date,amount\n2021-01-01,-1\n2021-02-01,0\n", encoding="utf-8")
    with pytest.raises(
        ValueError,
        match=rf"flows CSV {re.escape(repr(str(path)))} line 3: "
        "the amount is zero",
    ):
        read_flows_csv(path, **SIGNED)
    # An open text file is named too.
    with (
        path.open(encoding="utf-8", newline="") as handle,
        pytest.raises(ValueError, match=rf"{re.escape(repr(str(path)))} line 3"),
    ):
        read_flows_csv(handle, **SIGNED)


@pytest.mark.parametrize(
    ("data", "line"),
    [
        (b"date,amount\n2021-01-01,-1\n2021-02-01,\xff\n", 3),
        (b"date,amount\r\n2021-01-01,-1\r\n2021-02-01,\xff\r\n", 3),
        (b"date,amount\r2021-01-01,-1\r2021-02-01,\xff\r", 3),
        (b"\xef\xbb\xbfdate,amount\n2021-01-01,\xc3\n", 2),
    ],
)
def test_undecodable_bytes_are_refused_with_their_line(
    tmp_path: Path, data: bytes, line: int
) -> None:
    path = tmp_path / "flows.csv"
    path.write_bytes(data)
    with pytest.raises(ValueError, match=rf"line {line}: the file is not valid UTF-8"):
        read_flows_csv(path, **SIGNED)


def test_an_undecodable_text_stream_is_refused_with_a_line() -> None:
    stream = io.TextIOWrapper(io.BytesIO(b"date,amount\n\xff\n"), encoding="utf-8")
    with pytest.raises(ValueError, match=r"flows CSV line \d+: the stream cannot be decoded"):
        read_flows_csv(stream, **SIGNED)


class _BytesLines:
    """Stream-like, but yields bytes."""

    def read(self) -> bytes:
        return b""

    def __iter__(self) -> Any:
        return iter([b"date,amount\n", b"2021-01-01,-1\n"])


def test_binary_streams_and_non_streams_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="flows CSV: the stream is binary"):
        read_flows_csv(io.BytesIO(b"date,amount\n2021-01-01,-1\n"), **SIGNED)
    path = tmp_path / "flows.csv"
    path.write_bytes(b"date,amount\n2021-01-01,-1\n")
    with (
        path.open("rb") as handle,
        pytest.raises(ValueError, match=rf"{re.escape(repr(str(path)))}: the stream is binary"),
    ):
        read_flows_csv(handle, **SIGNED)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="flows CSV line 1: the stream yields bytes, not text"):
        read_flows_csv(_BytesLines(), **SIGNED)  # type: ignore[arg-type]
    for source in (["date,amount\n", "2021-01-01,-1\n"], b"date,amount\n", 42, None):
        with pytest.raises(ValueError, match="must be a path or an open text stream"):
            read_flows_csv(source, **SIGNED)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("columns", "match"),
    [
        ({**TYPED, "kind_column": ""}, "kind_column must be a non-empty column name"),
        ({**TYPED, "date_column": ""}, "date_column must be a non-empty column name"),
        ({**SIGNED, "amount_column": 5}, "amount_column must be a non-empty column name"),
        ({**TYPED, "kind_column": "amount"}, "must name different columns"),
    ],
)
def test_column_arguments_must_be_distinct_non_empty_names(
    columns: dict[str, Any], match: str
) -> None:
    # R3 repro_03: kind_column='' used to leak KeyError('').
    with pytest.raises(ValueError, match=match):
        read_flows_csv(_text("date,amount\n2021-01-01,100\n"), **columns)
    with pytest.raises(ValueError, match="level_column must be a non-empty column name"):
        read_index_csv(_text("date,level\n2021-01-01,1\n"), date_column="date", level_column=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="value_column must be a non-empty column name"):
        read_nav_csv(_text("date,value\n2021-01-01,1\n"), date_column="date", value_column="")


@pytest.mark.parametrize("value", [None, 20210101, b"2021-01-01", date(2021, 1, 1)])
def test_parse_iso_date_refuses_non_text(value: object) -> None:
    # R3 repro_03: None used to leak AttributeError.
    with pytest.raises(ValueError, match="not text"):
        parse_iso_date(value, what="date")  # type: ignore[arg-type]


def test_numbers_and_dates_take_ascii_digits_only() -> None:
    for amount in ("1_000", "١٠٠"):  # digit groups, Arabic-Indic 100
        with pytest.raises(ValueError, match="line 2.*not a plain decimal number"):
            read_flows_csv(_text(f"date,amount\n2021-01-01,{amount}\n"), **SIGNED)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_iso_date("٢٠٢١-٠١-٠١", what="x")
    for amount in ("+5", "5.", ".5", "5e2", " 5 "):
        assert read_flows_csv(_text(f"date,amount\n2021-01-01,{amount}\n"), **SIGNED)


# --- Byte-order mark: paths and text streams alike --------------------------------


def test_a_byte_order_mark_is_handled_identically_for_paths_and_streams(tmp_path: Path) -> None:
    body = "﻿date,kind,amount\n2021-01-01,contribution,100\n"
    path = tmp_path / "flows.csv"
    path.write_text(body, encoding="utf-8")
    from_path = read_flows_csv(path, **TYPED)
    # R3 repro_03: the StringIO was refused for a missing `date` column.
    assert read_flows_csv(_text(body), **TYPED) == from_path
    with path.open(encoding="utf-8", newline="") as handle:
        assert read_flows_csv(handle, **TYPED) == from_path
    assert from_path == (CashFlow(date=date(2021, 1, 1), kind="contribution", amount=100.0),)
    # Only one leading mark is dropped, for both kinds of source.
    doubled = "﻿" + body
    path.write_text(doubled, encoding="utf-8")
    for source in (path, _text(doubled)):
        with pytest.raises(ValueError, match=r"line 1: missing column\(s\) \['date'\]"):
            read_flows_csv(source, **TYPED)


# --- Index levels and NAVs --------------------------------------------------------


def test_index_levels() -> None:
    levels = read_index_csv(
        _text("date,level\n2021-01-01,100\n2022-01-01,120.5\n"),
        date_column="date",
        level_column="level",
    )
    assert levels == (
        IndexLevel(date=date(2021, 1, 1), level=100.0),
        IndexLevel(date=date(2022, 1, 1), level=120.5),
    )


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ("2021-01-01,0", "index CSV line 2"),
        ("2021-01-01,-3", "index CSV line 2"),
        ("2021-01-01,1e-320", r"(?s)index CSV line 2.*subnormal"),
        ("2021-13-01,1", "index CSV line 2.*calendar date"),
    ],
)
def test_bad_index_rows_are_refused_with_their_line(row: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        read_index_csv(_text(f"date,level\n{row}\n"), date_column="date", level_column="level")


def test_nav_observations() -> None:
    navs = read_nav_csv(
        _text("date,value\n2021-03-31,90\n2021-06-30,0\n"), date_column="date", value_column="value"
    )
    assert navs == (
        NavObservation(date=date(2021, 3, 31), value=90.0),
        NavObservation(date=date(2021, 6, 30), value=0.0),
    )
    with pytest.raises(ValueError, match="NAV CSV line 3"):
        read_nav_csv(
            _text("date,value\n2021-03-31,90\n2021-06-30,-1\n"),
            date_column="date",
            value_column="value",
        )


def test_parse_iso_date_takes_only_the_extended_calendar_form() -> None:
    assert parse_iso_date(" 2021-01-31 ", what="x") == date(2021, 1, 31)
    for text in ("2021-1-31", "31/01/2021", "2021-01-31T00:00", "20210131"):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_iso_date(text, what="x")
