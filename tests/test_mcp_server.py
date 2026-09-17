"""MCP wire contracts and independently derived financing examples.

Only the in-process transport and one stdio subprocess are used; no async pytest plugin.
"""

from __future__ import annotations

# Optional MCP imports must follow the collection-time skip.
# ruff: noqa: E402
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

import anyio
from mcp import Client, MCPError, StdioServerParameters
from mcp_types import CallToolResult, TextContent

from ovf.cli import DEMOS
from ovf_mcp.server import mcp
from ovf_mcp.specs import SECURITIES_ADAPTER, build_securities

TOOL_NAMES = {
    "exit_waterfall",
    "exit_sweep",
    "conversion_equilibria",
    "cap_table_summary",
    "safe_priced_round",
    "anti_dilution_adjustment",
    "dilutive_issuance",
    "debt_claim",
    "convert_note",
    "ocf_import",
    "ocf_export",
    "example_cap_tables",
}
EXAMPLE_IDS = {"F1", "F2", "F3", "F5a", "F5b", "F8a", "readme_60m"}

# README.md, USD 60M worked example: A invests 2M * $2.50 = $5M,
# B invests 1.5M * $6 = $9M; junior A participates up to 2 * $5M.
README_SECURITIES: list[dict[str, Any]] = [
    {"type": "common", "shares": 8_000_000, "holder_id": "founders", "security_id": "common"},
    {
        "type": "preferred",
        "shares": 2_000_000,
        "price": 2.50,
        "seniority": 2,
        "participating": True,
        "participation_cap": 2.0,
        "holder_id": "series_a",
        "security_id": "series_a",
    },
    {
        "type": "preferred",
        "shares": 1_500_000,
        "price": 6.0,
        "seniority": 1,
        "holder_id": "series_b",
        "security_id": "series_b",
    },
]


@pytest.fixture(autouse=True)
def isolate_allowed_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's path policy must not affect temporary-directory tests."""
    monkeypatch.delenv("OVF_MCP_ALLOWED_ROOTS", raising=False)


async def _call(name: str, args: dict[str, Any]) -> CallToolResult:
    async with Client(mcp) as client:
        return await client.call_tool(name, args)


def _success(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return _success(anyio.run(_call, name, args))


def _error(result: CallToolResult, tool: str, code: str) -> dict[str, Any]:
    assert result.is_error is True
    assert isinstance(result.structured_content, dict)
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structured_content
    assert set(result.structured_content) == {"error"}
    error = result.structured_content["error"]
    assert {"code", "message", "tool"} <= error.keys()
    assert error.keys() <= {"code", "message", "tool", "hint", "details"}
    assert error["code"] == code
    assert error["tool"] == tool
    assert isinstance(error["message"], str) and error["message"]
    return error


def _shape_error(result: CallToolResult, field: str) -> None:
    assert result.is_error is True
    assert result.structured_content is None
    assert isinstance(result.content[0], TextContent)
    assert field in result.content[0].text


def _assert_readme_exit(data: dict[str, Any]) -> None:
    # README.md: B takes $9M, leaving $51M; A gets 2/10 * $51M = $10.2M,
    # founders 8/10 * $51M = $40.8M. A exceeds its $10M cap by converting.
    expected = {"founders": 40_800_000, "series_a": 10_200_000, "series_b": 9_000_000}
    assert data["summary"]["by_holder"] == pytest.approx(expected, rel=0, abs=1e-6)
    payouts = {p["holder_id"]: p for p in data["payouts"]}
    assert {holder: p["amount"] for holder, p in payouts.items()} == pytest.approx(
        expected, rel=0, abs=1e-6
    )
    assert payouts["series_a"]["converted"] is True
    assert payouts["series_b"]["converted"] is False
    assert payouts["founders"]["effective_multiple"] is None
    assert data["summary"]["converted"] == ["series_a"]
    assert data["net_exit"] == 60_000_000
    assert math.fsum(data["summary"]["by_holder"].values()) == pytest.approx(
        data["net_exit"], rel=0, abs=1e-6
    )
    assert data["verification"]["all_passed"] is True
    assert all(check["ok"] for check in data["verification"]["checks"].values())
    assert data["max_unilateral_gain"] <= data["tolerance"]
    assert data["provenance"]["engine_version"] == data["engine_version"]
    assert data["provenance"]["input_hash"] == data["input_hash"]
    assert data["provenance"]["tool"] == "exit_waterfall"
    assert data["assumptions"]


def test_list_tools_metadata() -> None:
    async def scenario() -> None:
        async with Client(mcp) as client:
            result = await client.list_tools()
        assert len(result.tools) == len(TOOL_NAMES)
        assert {tool.name for tool in result.tools} == TOOL_NAMES
        for tool in result.tools:
            assert tool.title
            assert tool.output_schema
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is (tool.name != "ocf_export")
            assert tool.annotations.destructive_hint is False

    anyio.run(scenario)


def test_exit_waterfall_readme_60m() -> None:
    _assert_readme_exit(
        _tool("exit_waterfall", {"securities": README_SECURITIES, "exit_valuation": 60_000_000})
    )


def test_exit_waterfall_net_costs_and_unallocated_pool() -> None:
    # docs/fixtures.md F9: 2/10 of $35M = $7M to A, $28M to founders, pool $0.
    # Gross $36M less $1M costs leaves that same $35M net exit.
    securities = [
        *DEMOS["F1"][1],
        {"type": "pool", "reserved_shares": 1_000_000, "security_id": "pool"},
    ]
    data = _tool(
        "exit_waterfall",
        {"securities": securities, "exit_valuation": 36_000_000, "transaction_costs": 1_000_000},
    )
    assert data["summary"]["by_holder"] == pytest.approx(
        {"founders": 28_000_000, "series_a": 7_000_000, "esop": 0}, rel=0, abs=1e-6
    )
    assert data["net_exit"] == 35_000_000
    assert data["verification"]["all_passed"] is True
    assert math.fsum(p["amount"] for p in data["payouts"]) == pytest.approx(
        data["net_exit"], rel=0, abs=1e-6
    )


def test_exit_sweep_brackets_readme_conversion_thresholds() -> None:
    data = _tool(
        "exit_sweep",
        {"securities": README_SECURITIES, "exit_from": 0, "exit_to": 80_000_000, "steps": 17},
    )
    # README.md: A's threshold solves .2*(X-9M)=10M -> 59M;
    # B's solves (1.5/11.5)*X=9M -> 69M. Grid spacing = 80M/(17-1) = 5M.
    assert data["conversion_switches"] == [
        {
            "security_id": "series_a",
            "change": "starts converting",
            "between_exits": [55_000_000, 60_000_000],
        },
        {
            "security_id": "series_b",
            "change": "starts converting",
            "between_exits": [65_000_000, 70_000_000],
        },
    ]
    assert [p["exit_valuation"] for p in data["points"]] == [
        index * 5_000_000 for index in range(17)
    ]
    assert data["verification"]["all_passed"] is True
    assert data["verification"]["points_checked"] == 17
    for point in data["points"]:
        assert math.fsum(point["payouts"].values()) == pytest.approx(
            point["net_exit"], rel=0, abs=1e-6
        )
        assert point["max_unilateral_gain"] <= point["tolerance"]


@pytest.mark.parametrize("exit_to", [10_000_000, 5_000_000], ids=["equal", "descending"])
def test_exit_sweep_rejects_invalid_range(exit_to: float) -> None:
    _error(
        anyio.run(
            _call,
            "exit_sweep",
            {"securities": README_SECURITIES, "exit_from": 10_000_000, "exit_to": exit_to},
        ),
        "exit_sweep",
        "invalid_range",
    )


def test_conversion_equilibria_readme() -> None:
    data = _tool(
        "conversion_equilibria", {"securities": README_SECURITIES, "exit_valuation": 60_000_000}
    )
    assert data["equilibrium_exists"] is True
    assert data["payoff_unique"] is True
    assert data["solver_selected_profile"]["converted"] == ["series_a"]
    # README.md: two preferred players give 2**2 profiles, one feasible equilibrium.
    assert data["states_evaluated"] == 4
    assert data["feasible_equilibria"] == [{"series_a": True, "series_b": False}]
    assert data["solver_selected_profile"]["payouts"] == pytest.approx(
        {"common": 40_800_000, "series_a": 10_200_000, "series_b": 9_000_000}, rel=0, abs=1e-6
    )


def test_conversion_equilibria_f3_indifference() -> None:
    _, securities, exit_value = DEMOS["F3"]
    data = _tool("conversion_equilibria", {"securities": securities, "exit_valuation": exit_value})
    # docs/fixtures.md F3: .2 * $25M = $5M preference, so both actions are equilibria.
    assert len(data["feasible_equilibria"]) == 2
    assert {p["series_a"] for p in data["feasible_equilibria"]} == {False, True}
    assert data["distinct_payoff_vectors"] == 1
    assert data["payoff_unique"] is True
    assert data["solver_selected_profile"]["converted"] == []
    for payoff in data["feasible_payoffs"]:
        assert payoff == pytest.approx({"common": 20_000_000, "series_a": 5_000_000})


def test_cap_table_summary_preference_stack_and_ownership() -> None:
    data = _tool("cap_table_summary", {"securities": README_SECURITIES})
    stack = data["preference_stack"]
    assert [tier["seniority"] for tier in stack] == [1, 2]
    # README.md: B 1.5M*$6*1=$9M; A 2M*$2.50*1=$5M; FD = 8M+2M+1.5M.
    assert [tier["tier_base_preference"] for tier in stack] == [9_000_000, 5_000_000]
    assert [tier["positions"][0]["base_preference"] for tier in stack] == [9_000_000, 5_000_000]
    assert data["fully_diluted"]["available"] is True
    assert data["fully_diluted"]["shares"] == 11_500_000
    assert data["fully_diluted"]["ownership_by_holder"] == pytest.approx(
        {"founders": 8 / 11.5, "series_a": 2 / 11.5, "series_b": 1.5 / 11.5}
    )
    _assert_readme_exit(
        _tool(
            "exit_waterfall",
            {"securities": data["normalized_securities"], "exit_valuation": 60_000_000},
        )
    )


def test_cap_table_summary_safe_ownership_unavailable() -> None:
    data = _tool(
        "cap_table_summary",
        {
            "securities": [
                *README_SECURITIES,
                {"type": "safe_post", "amount": 1_000_000, "cap": 10_000_000},
            ]
        },
    )
    assert data["fully_diluted"]["available"] is False
    assert "SAFE" in data["fully_diluted"]["reason"]


def _safe_args(pool: float = 0) -> dict[str, Any]:
    return {
        "prior_common_shares": 8_000_000,
        "new_money": 3_000_000,
        "pre_money_valuation": 12_000_000,
        "target_pool_pct": pool,
        "method": "post_money_yc",
        "safes": [{"amount": 1_000_000, "cap": 10_000_000, "holder_id": "angel"}],
    }


@pytest.mark.parametrize("pool", [0.0, 0.10], ids=["no-pool", "ten-percent-pool"])
def test_safe_priced_round_ownership_and_exit_chain(pool: float) -> None:
    data = _tool("safe_priced_round", _safe_args(pool))
    # docs/semantics.md and docs/fixtures.md S1/S3: q=3/(12+3)=.2;
    # a=1/10=.1, SAFE=a*(1-q-t), founders=(1-a)*(1-q-t).
    expected = {
        "founders": 0.9 * (0.8 - pool),
        "angel": 0.1 * (0.8 - pool),
        "new_preferred": 0.2,
        "option_pool": pool,
    }
    assert data["ownership_breakdown"] == pytest.approx(expected)
    assert data["verification"]["all_passed"] is True
    # S1/S3: B=8M/.9; T=B/(.8-t), SAFE shares=.1*B; cap price=10M/B=$1.125.
    total = (8_000_000 / 0.9) / (0.8 - pool)
    assert data["total_post_shares"] == pytest.approx(total)
    assert data["new_option_pool_shares"] == pytest.approx(total * pool)
    assert list(data["safe_conversion_prices"].values()) == pytest.approx([1.125])
    specs = data["post_round_securities"]
    allocated = sum(s["shares"] for s in specs if s["type"] != "pool")
    reserve = sum(
        s["reserved_shares"] - s["allocated_shares"] for s in specs if s["type"] == "pool"
    )
    assert allocated + reserve == pytest.approx(total, rel=0, abs=1e-6)
    exited = _tool("exit_waterfall", {"securities": specs, "exit_valuation": 100_000_000})
    assert exited["verification"]["all_passed"] is True
    # At $100M both 1x nonparticipants convert; reserve is excluded from cash weights.
    expected_cash = {
        holder: fraction / (1 - pool) * 100_000_000
        for holder, fraction in expected.items()
        if holder != "option_pool"
    }
    if pool:
        expected_cash["option_pool"] = 0
    assert exited["summary"]["by_holder"] == pytest.approx(expected_cash, rel=0, abs=1e-6)


def test_safe_priced_round_requires_explicit_pool_target() -> None:
    args = _safe_args()
    del args["target_pool_pct"]
    _shape_error(anyio.run(_call, "safe_priced_round", args), "target_pool_pct")


def _adjustment_args() -> dict[str, Any]:
    return {
        "method": "weighted_average",
        "conversion_price": 2.0,
        "shares_issued": 4_000_000,
        "aggregate_consideration": 4_000_000,
        "original_issue_price": 3.0,
    }


def _capitalization() -> dict[str, float]:
    return {
        "common_outstanding": 6_000_000,
        "preferred_as_converted": 2_000_000,
        "options_and_warrants_as_exercised": 1_000_000,
        "other_convertibles_as_converted": 1_000_000,
        "reserved_unissued_pool": 2_000_000,
    }


@pytest.mark.parametrize("missing", ["both", "capitalization", "definition"])
def test_weighted_average_requires_charter_terms(missing: str) -> None:
    args = _adjustment_args()
    if missing == "capitalization":
        args["definition"] = "broad_based_nvca"
    elif missing == "definition":
        args["capitalization"] = _capitalization()
    _error(
        anyio.run(_call, "anti_dilution_adjustment", args),
        "anti_dilution_adjustment",
        "missing_charter_terms",
    )


def test_full_ratchet_rejects_unused_definition() -> None:
    args = {**_adjustment_args(), "method": "full_ratchet", "definition": "broad_based_nvca"}
    _error(
        anyio.run(_call, "anti_dilution_adjustment", args),
        "anti_dilution_adjustment",
        "unused_terms",
    )


def test_weighted_average_hand_derived_adjustment_and_ratios() -> None:
    data = _tool(
        "anti_dilution_adjustment",
        {
            **_adjustment_args(),
            "capitalization": _capitalization(),
            "definition": "broad_based_nvca",
        },
    )
    # Hand derivation: NVCA A=6M+2M+1M+1M=10M (2M reserve excluded),
    # B=$4M/$2=2M, C=4M, CP2=$2*(10+2)/(10+4)=$12/7.
    assert data["a"] == 10_000_000
    assert data["b"] == 2_000_000
    assert data["c"] == 4_000_000
    assert data["conversion_price_after"] == pytest.approx(12 / 7)
    assert data["adjustment_factor"] == pytest.approx(6 / 7)
    assert data["triggered"] is True
    # OIP=$3: old CR=3/2; new CR=3/(12/7)=7/4.
    assert data["conversion_ratio_before"] == pytest.approx(3 / 2)
    assert data["conversion_ratio_after"] == pytest.approx(7 / 4)


def test_full_ratchet_hand_derived_adjustment_and_ratios() -> None:
    data = _tool("anti_dilution_adjustment", {**_adjustment_args(), "method": "full_ratchet"})
    # Hand derivation: $4M/4M shares=$1 CP2; factor=$1/$2; CR2=$3/$1=3.
    assert data["conversion_price_after"] == 1
    assert data["adjustment_factor"] == 0.5
    assert data["conversion_ratio_before"] == 1.5
    assert data["conversion_ratio_after"] == 3
    assert data["a"] is None and data["b"] is None
    assert data["triggered"] is True


def _issuance_args() -> dict[str, Any]:
    return {
        "securities": [
            {
                "type": "common",
                "shares": 8_000_000,
                "holder_id": "founders",
                "security_id": "common",
            },
            {
                "type": "preferred",
                "shares": 2_000_000,
                "price": 2.0,
                "holder_id": "series_a",
                "security_id": "series_a",
            },
        ],
        "new_securities": [
            {
                "type": "preferred",
                "shares": 4_000_000,
                "price": 1.0,
                "holder_id": "series_b",
                "security_id": "series_b",
            }
        ],
        "aggregate_consideration": 4_000_000,
        "protection": {
            "series_a": {"method": "weighted_average", "definition": "broad_based_nvca"}
        },
        "exemption": {
            "exempted": False,
            "basis": "Stated test charter: cash financing is not exempt",
        },
    }


def test_dilutive_issuance_requires_every_preferred_protection() -> None:
    args = {**_issuance_args(), "protection": {}}
    _error(anyio.run(_call, "dilutive_issuance", args), "dilutive_issuance", "refused_by_model")


def test_dilutive_issuance_down_round_and_exit_chain() -> None:
    data = _tool("dilutive_issuance", _issuance_args())
    (position,) = data["positions"]
    # Hand derivation: A=8M+2M=10M, B=$4M/$2=2M, C=4M;
    # CP2=2*12/14=12/7, CR2=2/(12/7)=7/6; converted shares=2M*7/6.
    assert position["outcome"] == "adjusted"
    assert position["conversion_price_after"] == pytest.approx(12 / 7)
    assert position["conversion_ratio_after"] == pytest.approx(7 / 6)
    assert position["converted_shares_after"] == pytest.approx(2_000_000 * 7 / 6)
    after = {s["security_id"]: s for s in data["securities_after"]}
    assert after["series_a"]["conversion_ratio"] == pytest.approx(7 / 6)
    assert after["series_a"]["shares"] == 2_000_000
    assert after["series_a"]["price"] == 2
    exited = _tool(
        "exit_waterfall", {"securities": data["securities_after"], "exit_valuation": 43_000_000}
    )
    # FD=8M+7M/3+4M=43M/3. At $43M, $3/common equivalent gives
    # founders $24M, A $7M and B $12M; both exceed their $4M preferences.
    assert exited["summary"]["by_holder"] == pytest.approx(
        {"founders": 24_000_000, "series_a": 7_000_000, "series_b": 12_000_000}, rel=0, abs=1e-6
    )
    assert exited["summary"]["converted"] == ["series_a", "series_b"]
    assert exited["verification"]["all_passed"] is True


def _debt_spec() -> dict[str, Any]:
    return {
        "type": "debt",
        "principal": 1_000_000,
        "annual_rate": 0.10,
        "accrual": "simple",
        "day_count": "actual/365_fixed",
        "issue_date": "2025-01-01",
        "seniority": 0,
        "security_id": "loan",
        "holder_id": "lender",
    }


def _note_spec() -> dict[str, Any]:
    return {
        **_debt_spec(),
        "type": "convertible_note",
        "security_id": "note",
        "maturity_date": "2027-01-01",
        "qualified_financing_threshold": 2_000_000,
        "valuation_cap": 8_000_000,
        "discount_rate": 0.20,
    }


def test_debt_claim_simple_actual_365() -> None:
    data = _tool("debt_claim", {"instrument": _debt_spec(), "as_of": "2026-01-01"})
    # Hand derivation: 2025 is 365 days, t=365/365=1; I=$1M*.10*1=$100k.
    assert data["accrual"]["days"] == 365
    assert data["accrual"]["year_fraction"] == 1
    assert data["accrual"]["accrued_interest"] == 100_000
    assert data["accrual"]["day_count"] == "actual/365_fixed"
    assert data["outstanding_amount"] == 1_100_000
    assert data["exit_claim"]["claim"] == 1_100_000


def test_debt_claim_note_without_exit_treatment() -> None:
    data = _tool("debt_claim", {"instrument": _note_spec(), "as_of": "2026-01-01"})
    assert data["exit_claim"] is None
    assert "exit treatment" in data["exit_claim_unavailable"]
    # Same simple accrual as the loan; maturity is 730/365=2 years -> $1.2M.
    assert data["outstanding_amount"] == 1_100_000
    maturity = data["repayment_at_maturity"]
    assert maturity["days"] == 730
    assert maturity["accrued_interest"] == 200_000
    assert maturity["outstanding_principal"] + maturity["accrued_interest"] == 1_200_000


@pytest.mark.parametrize(
    "cap, binding, price", [(8_000_000, "cap", 1.0), (16_000_000, "discount", 1.6)]
)
def test_convert_note_cap_or_discount(cap: float, binding: str, price: float) -> None:
    data = _tool(
        "convert_note",
        {
            "note": {**_note_spec(), "valuation_cap": cap},
            "financing_date": "2026-01-01",
            "new_money": 2_000_000,
            "round_price": 2.0,
            "capitalization_shares": 8_000_000,
        },
    )
    # Hand derivation: accrued principal=$1M*(1+.10*365/365)=$1.1M;
    # cap $8M/8M=$1 beats $2*.8=$1.60; cap $16M/8M=$2 loses to $1.60.
    assert data["qualified_financing"] is True
    assert data["binding"] == binding
    assert data["cap_price"] == cap / 8_000_000
    assert data["discount_price"] == 1.6
    assert data["conversion_price"] == price
    assert data["amount_converted"] == 1_100_000
    assert data["shares"] == pytest.approx(1_100_000 / price)


def test_convert_note_refuses_nonqualified_financing() -> None:
    args = {
        "note": _note_spec(),
        "financing_date": "2026-01-01",
        "new_money": 1_000_000,
        "round_price": 2.0,
        "capitalization_shares": 8_000_000,
    }
    _error(anyio.run(_call, "convert_note", args), "convert_note", "refused_by_model")


def test_exit_refuses_unconverted_safe() -> None:
    args = {
        "securities": [
            *README_SECURITIES,
            {"type": "safe_post", "amount": 1_000_000, "cap": 10_000_000},
        ],
        "exit_valuation": 60_000_000,
    }
    _error(anyio.run(_call, "exit_waterfall", args), "exit_waterfall", "refused_by_model")


def test_exit_refuses_duplicate_security_id() -> None:
    args = {
        "securities": [README_SECURITIES[0], {**README_SECURITIES[1], "security_id": "common"}],
        "exit_valuation": 60_000_000,
    }
    _error(anyio.run(_call, "exit_waterfall", args), "exit_waterfall", "refused_by_model")


def test_exit_debt_requires_as_of() -> None:
    args = {"securities": [README_SECURITIES[0], _debt_spec()], "exit_valuation": 60_000_000}
    error = _error(anyio.run(_call, "exit_waterfall", args), "exit_waterfall", "refused_by_model")
    assert "as_of" in error["message"]


def test_exit_negative_shares_names_position() -> None:
    args = {
        "securities": [README_SECURITIES[0], {**README_SECURITIES[1], "shares": -1}],
        "exit_valuation": 60_000_000,
    }
    error = _error(anyio.run(_call, "exit_waterfall", args), "exit_waterfall", "invalid_terms")
    assert "securities[1]" in error["message"]
    assert "series_a" in error["message"]


@pytest.mark.parametrize(
    "change, field",
    [({"shares": "not-a-number"}, "shares"), ({"invented_term": 2}, "invented_term")],
    ids=["wrong-type", "unknown-security-key"],
)
def test_exit_argument_shape_error(change: dict[str, Any], field: str) -> None:
    args = {"securities": [{**README_SECURITIES[0], **change}], "exit_valuation": 60_000_000}
    _shape_error(anyio.run(_call, "exit_waterfall", args), field)


def _ocf_args() -> dict[str, Any]:
    return {
        "securities": README_SECURITIES,
        "issuer": {
            "id": "issuer",
            "legal_name": "MCP Example Inc.",
            "formation_date": "2020-01-01",
            "country_of_formation": "US",
        },
        "currency": "USD",
        "as_of": "2026-01-01",
        "participation_cap_basis": "total",
    }


def test_ocf_export_import_round_trip(tmp_path: Path) -> None:
    directory = tmp_path / "new-package"
    exported = _tool("ocf_export", {**_ocf_args(), "directory": str(directory)})
    assert exported["written"] is True
    assert Path(exported["manifest"]).is_file()
    assert exported["directory"] == str(directory)
    assert set(exported["files"]) == {p.name for p in directory.iterdir()}
    imported = _tool("ocf_import", {"path": str(directory), "participation_cap_basis": "total"})
    before = build_securities(SECURITIES_ADAPTER.validate_python(README_SECURITIES))
    after = build_securities(SECURITIES_ADAPTER.validate_python(imported["securities"]))
    assert {s.security_id: s for s in after} == {s.security_id: s for s in before}
    _assert_readme_exit(
        _tool(
            "exit_waterfall", {"securities": imported["securities"], "exit_valuation": 60_000_000}
        )
    )


def test_ocf_export_refuses_nonempty_directory(tmp_path: Path) -> None:
    sentinel = tmp_path / "existing.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    args = {**_ocf_args(), "directory": str(tmp_path)}
    _error(anyio.run(_call, "ocf_export", args), "ocf_export", "file_error")
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert list(tmp_path.iterdir()) == [sentinel]


@pytest.mark.parametrize("tool", ["ocf_export", "ocf_import"])
def test_ocf_path_policy_excludes_outside_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    denied = tmp_path / "denied"
    monkeypatch.setenv("OVF_MCP_ALLOWED_ROOTS", str(allowed))
    args = (
        {**_ocf_args(), "directory": str(denied)}
        if tool == "ocf_export"
        else {"path": str(denied), "participation_cap_basis": "total"}
    )
    _error(anyio.run(_call, tool, args), tool, "path_not_allowed")
    assert not denied.exists()


def test_ocf_export_without_directory_returns_package() -> None:
    data = _tool("ocf_export", _ocf_args())
    assert data["written"] is False
    assert isinstance(data["package"], dict) and data["package"]
    assert "directory" not in data
    assert "manifest" not in data
    assert json.loads(json.dumps(data["package"])) == data["package"]


def test_example_catalogue_ids() -> None:
    examples = _tool("example_cap_tables", {})["examples"]
    assert len(examples) == len(EXAMPLE_IDS)
    assert {example["id"] for example in examples} == EXAMPLE_IDS


@pytest.mark.parametrize("example_id", sorted(EXAMPLE_IDS))
def test_every_example_passes_verified_exit(example_id: str) -> None:
    examples = _tool("example_cap_tables", {})["examples"]
    example = next(item for item in examples if item["id"] == example_id)
    data = _tool(
        "exit_waterfall",
        {
            "securities": example["securities"],
            "exit_valuation": example["suggested_exit_valuation"],
        },
    )
    assert data["verification"]["all_passed"] is True
    assert math.fsum(data["summary"]["by_holder"].values()) == pytest.approx(
        example["suggested_exit_valuation"], rel=0, abs=1e-6
    )


def test_documentation_resources_and_security_schema() -> None:
    async def scenario() -> None:
        async with Client(mcp) as client:
            index = await client.read_resource("ovf://docs")
            assert "ovf://docs/limitations" in index.contents[0].text
            assert "ovf://schema/securities" in index.contents[0].text
            limitations = await client.read_resource("ovf://docs/limitations")
            source = Path(__file__).resolve().parents[1] / "docs" / "limitations.md"
            assert limitations.contents[0].text == source.read_text(encoding="utf-8")
            assert limitations.contents[0].mime_type == "text/markdown"
            schema = await client.read_resource("ovf://schema/securities")
            assert schema.contents[0].mime_type == "application/json"
            payload = json.loads(schema.contents[0].text)
            assert payload["items"]["discriminator"]["propertyName"] == "type"
            assert {
                "common",
                "preferred",
                "safe_post",
                "safe_pre",
                "pool",
                "debt",
                "venture_debt",
                "convertible_note",
            } <= payload["items"]["discriminator"]["mapping"].keys()

    anyio.run(scenario)


def test_unknown_document_returns_protocol_error() -> None:
    async def scenario() -> None:
        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="no document named"):
                await client.read_resource("ovf://docs/not-a-document")

    anyio.run(scenario)


@pytest.mark.parametrize(
    "name, argument, value, expected_step",
    [
        (
            "analyze_exit",
            "cap_table",
            "Founders own 8000000 common shares",
            "conversion_equilibria",
        ),
        (
            "safe_round_to_exit",
            "round_terms",
            "USD 1M SAFE at USD 10M post-money cap",
            "post_round_securities",
        ),
    ],
)
def test_prompts_render_supplied_arguments(
    name: str, argument: str, value: str, expected_step: str
) -> None:
    async def scenario() -> None:
        async with Client(mcp) as client:
            result = await client.get_prompt(name, {argument: value, "exit_valuation": "USD 60M"})
        assert result.messages
        text = "\n".join(
            message.content.text
            for message in result.messages
            if isinstance(message.content, TextContent)
        )
        assert value in text
        assert "USD 60M" in text
        assert expected_step in text

    anyio.run(scenario)


def test_stdio_server_lists_tools_and_runs_waterfall() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ovf_mcp"],
        env={**os.environ, "PYTHONPATH": "src"},
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    async def scenario() -> None:
        with anyio.fail_after(30):
            async with Client(params) as client:
                listed = await client.list_tools()
                assert {tool.name for tool in listed.tools} == TOOL_NAMES
                result = await client.call_tool(
                    "exit_waterfall",
                    {"securities": README_SECURITIES, "exit_valuation": 60_000_000},
                )
                _assert_readme_exit(_success(result))

    anyio.run(scenario)


def test_safe_priced_round_requires_explicit_method() -> None:
    # Pre- and post-money SAFEs convert to different share counts, so there is no default.
    args = _safe_args(0.0)
    del args["method"]
    _shape_error(anyio.run(_call, "safe_priced_round", args), "method")


def test_omitted_contract_terms_are_reported_in_defaults_applied() -> None:
    securities = [
        {"type": "common", "shares": 8_000_000, "security_id": "common"},
        {
            "type": "preferred",
            "shares": 2_000_000,
            "price": 2.5,
            "seniority": 1,
            "security_id": "a",
        },
    ]
    data = _tool("exit_waterfall", {"securities": securities, "exit_valuation": 35_000_000})
    # Only the preferred terms the caller omitted, with the factory defaults used.
    assert data["defaults_applied"] == {
        "a": {
            "liquidation_multiple": 1.0,
            "participating": False,
            "conversion_ratio": 1.0,
            "dividend": None,
        }
    }
    assert data["adapter_notes"]


def test_ocf_import_refuses_symlinked_manifest_outside_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed, outside = tmp_path / "allowed" / "pkg", tmp_path / "outside"
    allowed.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.json").write_text('{"secret": 1}', encoding="utf-8")
    (allowed / "manifest.json").symlink_to(outside / "secret.json")
    monkeypatch.setenv("OVF_MCP_ALLOWED_ROOTS", str(tmp_path / "allowed"))
    result = anyio.run(
        _call, "ocf_import", {"path": str(allowed), "participation_cap_basis": "total"}
    )
    _error(result, "ocf_import", "path_not_allowed")
