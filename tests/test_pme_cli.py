"""`python -m ovf pme report`: required conventions, text and JSON output, refusals."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ovf.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "pme"


def _args(
    flows: Path = EXAMPLES / "flows.csv",
    *,
    sign: str = "typed",
    as_of: str = "2010-12-31",
    extra: tuple[str, ...] = (),
) -> list[str]:
    return [
        "pme",
        "report",
        "--flows",
        str(flows),
        "--sign-convention",
        sign,
        "--index",
        str(EXAMPLES / "index.csv"),
        "--benchmark-name",
        "GGS index",
        "--return-basis",
        "total_return_gross",
        "--nav-value",
        "75",
        "--nav-date",
        "2010-12-31",
        "--as-of",
        as_of,
        "--name",
        "GGS fund",
        "--currency",
        "USD",
        "--basis",
        "net_lp",
        "--stale-nav",
        "refuse",
        "--day-count",
        "ACT/365F",
        "--lookup",
        "exact",
        "--max-gap-days",
        "0",
        *extra,
    ]


def test_text_report_on_the_ggs_example(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args()) == 0
    out = capsys.readouterr().out
    assert "PME report: GGS fund as of 2010-12-31" in out
    assert "TVPI 2.00x" in out and "17.52% [unique]" in out and "KS-PME        1.667" in out
    assert "roots: -27.26%, 5.97%" in out and "ICM_WENT_SHORT" in out


def test_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(extra=("--json",))) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ks_pme"]["ks_pme"] == pytest.approx(1990055721 / 1193950768, rel=1e-12)
    assert payload["mpme"] is None
    assert [flag["code"] for flag in payload["flags"]] == ["IRR_NOT_UNIQUE", "ICM_WENT_SHORT"]


def test_signed_lp_flows_give_the_same_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    signed = tmp_path / "signed.csv"
    signed.write_text(
        "date,amount\n2001-12-31,-100\n2003-12-31,-100\n2003-12-31,25\n2005-12-31,-50\n"
        "2005-12-31,150\n2007-12-31,150\n2009-12-31,100\n",
        encoding="utf-8",
    )
    assert main(_args(extra=("--json",))) == 0
    typed = json.loads(capsys.readouterr().out)
    assert main(_args(signed, sign="signed_lp", extra=("--json",))) == 0
    assert json.loads(capsys.readouterr().out)["input_hash"] == typed["input_hash"]


def test_nav_history_enables_the_mpme(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "navs.csv"
    history.write_text(
        "date,value\n2003-12-31,120\n2005-12-31,100\n2007-12-31,90\n2009-12-31,80\n",
        encoding="utf-8",
    )
    extra = ("--nav-history", str(history), "--interim-nav", "refuse", "--max-nav-gap-days", "0")
    assert main(_args(extra=extra)) == 0
    assert "mPME          IRR" in capsys.readouterr().out
    # --nav-history without its policies is refused (exit 2), not defaulted.
    assert main(_args(extra=("--nav-history", str(history)))) == 2
    assert "needs interim_nav" in capsys.readouterr().err


def test_refusals_exit_with_code_two_and_the_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_args(as_of="2001-01-01")) == 2
    assert "error:" in capsys.readouterr().err
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "date,kind,amount\n2001-12-31,contribution,100\n2003-12-31,contribution,0\n",
        encoding="utf-8",
    )
    assert main(_args(bad)) == 2
    assert f"flows CSV {str(bad)!r} line 3: the amount is zero" in capsys.readouterr().err
    assert main(_args(tmp_path / "missing.csv")) == 2
    assert "missing.csv': cannot open the file" in capsys.readouterr().err


# R3 findings 2 and 3 through the CLI: each bad file exits 2 with the file and line, never
# exit 0 with a silently shortened flow list, never exit 1 with a traceback.
BAD_FLOW_FILES = {
    "unterminated-quote": (
        b'date,kind,amount,memo\n2001-12-31,contribution,100,"memo\n'
        b"2009-12-31,distribution,100,done\n",
        "line 2: a quoted field in the record starting on line 2 is never closed",
    ),
    "long-memo": (
        b"date,kind,amount,memo\n2001-12-31,contribution,100," + b"x" * 140_000 + b"\n",
        "line 2: a field is longer than the CSV parser's limit",
    ),
    "duplicate-header": (
        b"date,kind,amount,amount\n2001-12-31,contribution,100,1\n",
        "line 1: duplicate column name(s) ['amount']",
    ),
    "undecodable": (
        b"date,kind,amount\n2001-12-31,contribution,100\n2003-12-31,contribution,\xff\n",
        "line 3: the file is not valid UTF-8",
    ),
    "empty": (b"", "line 1: the file is empty"),
    "header-only": (b"date,kind,amount\n", "line 1: no data rows after the header"),
}


@pytest.mark.parametrize("case", sorted(BAD_FLOW_FILES))
def test_bad_flow_files_exit_two_with_file_and_line(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data, message = BAD_FLOW_FILES[case]
    path = tmp_path / f"{case}.csv"
    path.write_bytes(data)
    assert main(_args(path, extra=("--json",))) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error: flows CSV {str(path)!r} {message}" in captured.err


def test_bad_index_and_nav_files_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index = tmp_path / "index.csv"
    index.write_text('date,level\n2001-12-31,"100\n2002-12-31,78\n', encoding="utf-8")
    argv = _args()
    argv[argv.index("--index") + 1] = str(index)
    assert main(argv) == 2
    assert f"index CSV {str(index)!r} line 2: a quoted field" in capsys.readouterr().err
    history = tmp_path / "navs.csv"
    history.write_text("date,value,value\n2003-12-31,120,1\n", encoding="utf-8")
    extra = ("--nav-history", str(history), "--interim-nav", "refuse", "--max-nav-gap-days", "0")
    assert main(_args(extra=extra)) == 2
    assert f"NAV CSV {str(history)!r} line 1: duplicate" in capsys.readouterr().err
    assert main(_args(extra=("--nav-history", str(tmp_path)))) == 2
    assert f"NAV CSV {str(tmp_path)!r}: cannot open the file" in capsys.readouterr().err


@pytest.mark.parametrize("case", ["unterminated-quote", "long-memo"])
def test_bad_flow_files_never_print_a_traceback(case: str, tmp_path: Path) -> None:
    # The R3 CLI repro (out/r3/cli_checks.py) as a subprocess: exit 2, one error line.
    path = tmp_path / f"{case}.csv"
    path.write_bytes(BAD_FLOW_FILES[case][0])
    completed = subprocess.run(
        [sys.executable, "-W", "error", "-m", "ovf", *_args(path), "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert completed.stderr.startswith("error: flows CSV ") and "line 2:" in completed.stderr


@pytest.mark.parametrize("flag", ["--day-count", "--sign-convention", "--stale-nav", "--lookup"])
def test_every_convention_flag_is_required(flag: str) -> None:
    argv = _args()
    position = argv.index(flag)
    del argv[position : position + 2]
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_choices_come_from_the_literal_types() -> None:
    argv = _args()
    argv[argv.index("--day-count") + 1] = "30/360"
    with pytest.raises(SystemExit):
        main(argv)
    argv = _args()
    argv[argv.index("--as-of") + 1] = "31/12/2010"
    with pytest.raises(SystemExit):
        main(argv)


def test_help_documents_the_csv_headers(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["pme", "report", "--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "date,kind,amount" in out and "date,level" in out and "date,value" in out


def test_python_dash_m_ovf_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "-W", "error", "-m", "ovf", *_args()],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    assert "KS-PME        1.667" in completed.stdout


def test_the_walkthrough_example_runs_and_matches_the_published_display() -> None:
    completed = subprocess.run(
        [sys.executable, "-W", "error", str(ROOT / "examples" / "pme_walkthrough.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "MISMATCH" not in completed.stdout
    for line in (
        "TVPI                       2.00              2.00  ok",
        "Direct Alpha              12.6%             12.6%  ok",
    ):
        assert line in completed.stdout
