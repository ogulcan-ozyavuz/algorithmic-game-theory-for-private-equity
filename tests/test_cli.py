"""CLI surface: exit codes, reported numbers and the assumptions block."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ovf.cli import main

TABLE = {
    "securities": [
        {"type": "common", "shares": 8_000_000, "holder_id": "founders", "security_id": "common"},
        {
            "type": "preferred",
            "shares": 2_000_000,
            "price": 2.50,
            "holder_id": "series_a",
            "security_id": "series_a",
        },
        {
            "type": "pool",
            "reserved_shares": 1_000_000,
            "holder_id": "esop",
            "security_id": "pool",
        },
    ]
}


@pytest.fixture
def table_file(tmp_path: Path) -> Path:
    path = tmp_path / "table.json"
    path.write_text(json.dumps(TABLE), encoding="utf-8")
    return path


def test_waterfall_demo(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["waterfall", "--demo", "F5b"]) == 0
    out = capsys.readouterr().out
    assert "48,000,000.00" in out
    assert "12,000,000.00" in out
    assert "Verified equilibrium: True" in out
    assert "Assumptions" in out


def test_waterfall_from_file(table_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["waterfall", "--file", str(table_file), "--exit", "35000000"]) == 0
    out = capsys.readouterr().out
    assert "28,000,000.00" in out
    assert "7,000,000.00" in out


def test_waterfall_reports_founder_multiple_as_undefined(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A zero founder cost basis must not be reported as a huge return."""
    assert main(["waterfall", "--demo", "F1"]) == 0
    line = next(row for row in capsys.readouterr().out.splitlines() if row.startswith("common "))
    assert line.rstrip().endswith("-")


def test_sweep_marks_the_dead_zone(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sweep", "--demo", "F8a", "--to", "30000000", "--steps", "8"]) == 0
    out = capsys.readouterr().out
    assert "Common holders received nothing" in out


def test_equilibria_reports_the_tie_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["equilibria", "--demo", "F3"]) == 0
    out = capsys.readouterr().out
    assert "Pure equilibria     2" in out
    assert "Distinct payouts    1" in out
    assert "Payout unique       True" in out


def test_safe_round(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "safe",
            "--prior-common",
            "8000000",
            "--new-money",
            "3000000",
            "--pre-money",
            "12000000",
            "--pool",
            "0.10",
            "--safe",
            "1000000:10000000:angel",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "63.0000%" in out
    assert "7.0000%" in out
    assert "$1.18125" in out
    assert "$1.125" in out


def test_safe_rejects_malformed_specification() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "safe",
                "--prior-common",
                "1",
                "--new-money",
                "1",
                "--pre-money",
                "1",
                "--safe",
                "oops",
            ]
        )


def test_unknown_demo_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["waterfall", "--demo", "NOPE"])


def test_domain_error_returns_exit_code_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["waterfall", "--demo", "F1", "--exit", "-1"]) == 2
    assert "error:" in capsys.readouterr().err


def test_missing_input_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["waterfall"])
