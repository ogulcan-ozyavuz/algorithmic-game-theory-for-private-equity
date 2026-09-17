"""Lossless security specs, stable refusal codes and independent invariant checks."""

from __future__ import annotations

# Optional MCP imports must follow the collection-time skip.
# ruff: noqa: E402
from typing import Any

import pytest

pytest.importorskip("mcp")

from pydantic import ValidationError

import ovf
from ovf.cli import DEMOS, build_security
from ovf.ocf import OcfError, OcfIntegrityError, OcfSchemaError, OcfUnsupportedError
from ovf.waterfall import WaterfallConvergenceError
from ovf_mcp.errors import DomainError, classify
from ovf_mcp.server import _verify_waterfall
from ovf_mcp.specs import (
    SECURITIES_ADAPTER,
    CommonSpec,
    CumulativeDividendSpec,
    NonCumulativeDividendSpec,
    PreferredSpec,
    build_securities,
    securities_to_specs,
    security_to_spec,
)

# These are explicit round-trip inputs, not expected financial calculations.
DEBT_TERMS: dict[str, Any] = {
    "principal": 1_000_000,
    "annual_rate": 0.08,
    "accrual": "simple",
    "day_count": "actual/365_fixed",
    "issue_date": "2025-01-01",
    "maturity_date": "2027-01-01",
    "seniority": 2,
    "holder_id": "lender",
    "security_id": "loan",
}
PREFERRED_TERMS: dict[str, Any] = {
    "type": "preferred",
    "shares": 2_000_000,
    "price": 2.5,
    "seniority": 2,
    "liquidation_multiple": 1.5,
    "participating": True,
    "participation_cap": 3.0,
    "conversion_ratio": 1.25,
    "holder_id": "investor",
    "security_id": "preferred",
}


def _library_value_error() -> ValueError:
    """A refusal raised inside the ovf library, as the adapter sees one."""
    try:
        ovf.waterfall.solve_waterfall([ovf.common(1)], -1.0)
    except ValueError as error:
        return error
    raise AssertionError("the library accepted a negative exit")


def _verify(
    result: ovf.WaterfallResult,
    securities: list[Any],
    exit_valuation: float,
    *,
    enumerate_profiles: bool = True,
) -> dict[str, Any]:
    return _verify_waterfall(
        result,
        securities,
        exit_valuation=exit_valuation,
        transaction_costs=0.0,
        as_of=None,
        enumerate_profiles=enumerate_profiles,
    )


SECURITY_CASES = [
    pytest.param(
        {
            "type": "common",
            "shares": 8_000_000,
            "price": 0.1,
            "holder_id": "founders",
            "security_id": "common",
        },
        id="common",
    ),
    pytest.param({"type": "common", "shares": 100}, id="derived-id"),
    pytest.param(PREFERRED_TERMS, id="preferred"),
    pytest.param(
        {
            "type": "pool",
            "reserved_shares": 1_000_000,
            "allocated_shares": 250_000,
            "holder_id": "employees",
            "security_id": "pool",
        },
        id="pool",
    ),
    pytest.param({"type": "option_pool", "reserved_shares": 1_000_000}, id="pool-alias"),
    pytest.param(
        {
            "type": "safe_post",
            "amount": 1_000_000,
            "cap": 10_000_000,
            "discount_rate": 0.2,
            "holder_id": "angel",
            "security_id": "post",
        },
        id="safe-post",
    ),
    pytest.param(
        {
            "type": "safe_pre",
            "amount": 500_000,
            "cap": 8_000_000,
            "discount_rate": 0.1,
            "holder_id": "angel",
            "security_id": "pre",
        },
        id="safe-pre",
    ),
    pytest.param({**DEBT_TERMS, "type": "debt"}, id="debt-simple"),
    pytest.param(
        {
            **DEBT_TERMS,
            "type": "debt",
            "accrual": "compound",
            "compounding_frequency": 4,
            "day_count": "actual/360",
            "maturity_date": None,
        },
        id="debt-compound",
    ),
    pytest.param(
        {
            **DEBT_TERMS,
            "type": "venture_debt",
            "exit_fee": 50_000,
            "accrual": "pik",
            "compounding_frequency": 2,
        },
        id="venture-debt",
    ),
    pytest.param(
        {
            **DEBT_TERMS,
            "type": "convertible_note",
            "qualified_financing_threshold": 2_000_000,
            "valuation_cap": 8_000_000,
            "discount_rate": 0.2,
        },
        id="unresolved-note",
    ),
    pytest.param(
        {
            **DEBT_TERMS,
            "type": "convertible_note",
            "qualified_financing_threshold": 2_000_000,
            "exit_treatment": "repay",
        },
        id="repay-note",
    ),
    pytest.param(
        {
            **DEBT_TERMS,
            "type": "convertible_note",
            "qualified_financing_threshold": 2_000_000,
            "valuation_cap": 8_000_000,
            "discount_rate": 0.2,
            "exit_treatment": "multiple",
            "exit_principal_multiple": 2.0,
        },
        id="multiple-note",
    ),
    pytest.param(
        {**PREFERRED_TERMS, "dividend": {"kind": "non_cumulative", "annual_rate": 0.08}},
        id="non-cumulative-dividend",
    ),
    pytest.param(
        {
            **PREFERRED_TERMS,
            "dividend": {
                "kind": "cumulative",
                "annual_rate": 0.08,
                "accrual": "simple",
                "day_count": "actual/365_fixed",
                "accrues_from": "2025-01-01",
                "settlement": "forfeit_on_conversion",
                "participation_cap_basis": "includes_dividends",
            },
        },
        id="simple-cumulative-dividend",
    ),
    pytest.param(
        {
            **PREFERRED_TERMS,
            "dividend": {
                "kind": "cumulative",
                "annual_rate": 0.08,
                "accrual": "compound",
                "compounding_frequency": 4,
                "day_count": "actual/360",
                "accrues_from": "2025-01-01",
                "settlement": "forfeit_on_conversion",
                "participation_cap_basis": "excludes_dividends",
            },
        },
        id="compound-cumulative-dividend",
    ),
    pytest.param(
        {
            **PREFERRED_TERMS,
            "dividend": {
                "kind": "cumulative",
                "annual_rate": 0.08,
                "accrual": "compound",
                "compounding_frequency": 4,
                "day_count": "actual/360",
                "accrues_from": "2025-01-01",
                "settlement": "paid_in_kind",
            },
        },
        id="compound-pik-dividend",
    ),
]


@pytest.mark.parametrize("raw", SECURITY_CASES)
def test_security_spec_round_trip_is_lossless(raw: dict[str, Any]) -> None:
    (spec,) = SECURITIES_ADAPTER.validate_python([raw])
    original = spec.build()
    encoded = security_to_spec(original)
    (rebuilt_spec,) = SECURITIES_ADAPTER.validate_python([encoded])
    assert rebuilt_spec.build() == original
    # The serialized form must also survive the JSON representation used by MCP.
    serialized = SECURITIES_ADAPTER.dump_json([rebuilt_spec])
    (json_spec,) = SECURITIES_ADAPTER.validate_json(serialized)
    assert json_spec.build() == original
    assert securities_to_specs([original]) == [encoded]


@pytest.mark.parametrize(
    "raw",
    [
        {"kind": "non_cumulative", "annual_rate": 0.08},
        {
            "kind": "cumulative",
            "annual_rate": 0.08,
            "accrual": "simple",
            "day_count": "actual/365_fixed",
            "accrues_from": "2025-01-01",
            "settlement": "forfeit_on_conversion",
        },
    ],
    ids=["non-cumulative", "cumulative"],
)
def test_dividend_spec_build_round_trip(raw: dict[str, Any]) -> None:
    spec = (
        NonCumulativeDividendSpec.model_validate(raw)
        if raw["kind"] == "non_cumulative"
        else CumulativeDividendSpec.model_validate(raw)
    )
    dividend = spec.build()
    security = ovf.preferred(2_000_000, 2.5, dividend=dividend)
    rebuilt = PreferredSpec.model_validate(security_to_spec(security)).build()
    assert rebuilt == security
    assert rebuilt.dividend == dividend


@pytest.mark.parametrize("demo_id", sorted(DEMOS))
def test_cli_demos_validate_as_mcp_security_specs(demo_id: str) -> None:
    raw = DEMOS[demo_id][1]
    specs = SECURITIES_ADAPTER.validate_python(raw)
    assert build_securities(specs) == [build_security(item) for item in raw]


@pytest.mark.parametrize(
    "error, code",
    [
        pytest.param(WaterfallConvergenceError("cycle"), "convergence_failure", id="convergence"),
        pytest.param(
            OcfIntegrityError("checksum mismatch"), "ocf_integrity_error", id="ocf-integrity"
        ),
        pytest.param(
            OcfUnsupportedError("unrepresented right"), "ocf_unsupported", id="ocf-unsupported"
        ),
        pytest.param(OcfSchemaError("invalid OCF"), "ocf_schema_error", id="ocf-schema"),
        pytest.param(OcfError("OCF error"), "ocf_error", id="ocf-base"),
        pytest.param(_library_value_error(), "refused_by_model", id="library-value-error"),
        pytest.param(FileNotFoundError("missing package"), "file_error", id="missing-file"),
        pytest.param(
            NotADirectoryError("file in place of directory"), "file_error", id="not-directory"
        ),
        pytest.param(
            IsADirectoryError("directory in place of file"), "file_error", id="is-directory"
        ),
        pytest.param(FileExistsError("nonempty package"), "file_error", id="exists"),
        pytest.param(PermissionError("unreadable package"), "file_error", id="permission"),
    ],
)
def test_classify_anticipated_error_codes(error: BaseException, code: str) -> None:
    classified = classify(error)
    assert isinstance(classified, DomainError)
    assert classified.code == code
    assert classified.message == str(error)


def test_classify_validation_error_retains_field_details() -> None:
    with pytest.raises(ValidationError) as caught:
        CommonSpec.model_validate({"type": "common", "shares": "not-a-number"})
    classified = classify(caught.value)
    assert isinstance(classified, DomainError)
    assert classified.code == "invalid_terms"
    assert classified.message == f"{caught.value.error_count()} validation error(s) for CommonSpec"
    assert classified.details == [{"loc": "shares", "msg": caught.value.errors()[0]["msg"]}]


def test_classify_domain_error_is_identity() -> None:
    error = DomainError(
        "invariant_violation", "tampered result", hint="inspect", details={"field": "amount"}
    )
    assert classify(error) is error


def test_classify_unanticipated_runtime_error_returns_none() -> None:
    assert classify(RuntimeError("unexpected crash")) is None


def test_classify_leaves_adapter_value_errors_as_crashes() -> None:
    # A ValueError raised outside the library is an adapter bug, not a refusal.
    try:
        int("not a number")
    except ValueError as error:
        assert classify(error) is None


def test_verify_waterfall_rejects_tampered_payout() -> None:
    securities = [ovf.common(8_000_000), ovf.preferred(2_000_000, 2.5)]
    result = ovf.CapTable(securities=securities).waterfall_detailed(35_000_000)
    assert _verify(result, securities, 35_000_000)["all_passed"] is True
    # Inject $1 of unbacked proceeds into a real result, exceeding its cash tolerance.
    altered = result.payouts[0].model_copy(update={"amount": result.payouts[0].amount + 1})
    tampered = result.model_copy(update={"payouts": [altered, *result.payouts[1:]]})
    with pytest.raises(DomainError, match="proceeds_conservation") as caught:
        _verify(tampered, securities, 35_000_000)
    assert caught.value.code == "invariant_violation"
    assert caught.value.details["checks"]["proceeds_conservation"]["ok"] is False
    assert caught.value.details["input_hash"] == result.input_hash


def test_verify_waterfall_net_exit_comes_from_the_arguments() -> None:
    securities = [ovf.common(8_000_000), ovf.preferred(2_000_000, 2.5)]
    result = ovf.CapTable(securities=securities).waterfall_detailed(35_000_000)
    # The same result checked against a different exit: the engine's own net_exit is not trusted.
    with pytest.raises(DomainError, match="proceeds_conservation"):
        _verify(result, securities, 36_000_000)


@pytest.mark.parametrize(
    "update",
    [{"converged": False}, {"max_unilateral_gain": 1.0}],
    ids=["nonconverged", "profitable-deviation"],
)
def test_verify_waterfall_fallback_rejects_unstable_result(update: dict[str, Any]) -> None:
    # Without enumeration the check falls back to the engine's reported gain.
    securities = [ovf.common(8_000_000), ovf.preferred(2_000_000, 2.5)]
    result = ovf.CapTable(securities=securities).waterfall_detailed(35_000_000)
    with pytest.raises(DomainError, match="no_profitable_unilateral_deviation") as caught:
        _verify(result.model_copy(update=update), securities, 35_000_000, enumerate_profiles=False)
    assert caught.value.code == "invariant_violation"


def test_verify_waterfall_enumeration_rejects_a_non_equilibrium_profile() -> None:
    # F1 (docs/fixtures.md): at USD 35M the 1x non-participating Series A converts, because
    # 20% of 35M = 7M beats its 5M preference. Report it as retained with the same cash:
    # the enumerated equilibrium set does not contain that profile.
    securities = [ovf.common(8_000_000), ovf.preferred(2_000_000, 2.5)]
    result = ovf.CapTable(securities=securities).waterfall_detailed(35_000_000)
    payouts = [
        p.model_copy(update={"converted": False}) if p.converted else p for p in result.payouts
    ]
    with pytest.raises(DomainError, match="no_profitable_unilateral_deviation") as caught:
        _verify(result.model_copy(update={"payouts": payouts}), securities, 35_000_000)
    check = caught.value.details["checks"]["no_profitable_unilateral_deviation"]
    assert check["independent_of_search"] is True
    assert check["selected_profile_is_an_equilibrium"] is False


def test_verify_waterfall_rejects_junior_preference_paid_before_senior() -> None:
    # F8a (docs/fixtures.md) at USD 14M: senior Series B takes 9M, junior Series A 5M.
    # Move USD 1M of preference from B to A: cash still reconciles, seniority does not.
    securities = [
        ovf.common(8_000_000, security_id="common"),
        ovf.preferred(2_000_000, 2.5, seniority=2, security_id="series_a"),
        ovf.preferred(1_500_000, 6.0, seniority=1, security_id="series_b"),
    ]
    result = ovf.CapTable(securities=securities).waterfall_detailed(14_000_000)
    shift = {"series_a": 1_000_000.0, "series_b": -1_000_000.0}
    payouts = [
        p.model_copy(
            update={
                "amount": p.amount + shift.get(p.security_id, 0.0),
                "preference_payout": p.preference_payout + shift.get(p.security_id, 0.0),
            }
        )
        for p in result.payouts
    ]
    with pytest.raises(DomainError, match="preferences_paid_in_seniority_order") as caught:
        _verify(result.model_copy(update={"payouts": payouts}), securities, 14_000_000)
    assert caught.value.details["checks"]["proceeds_conservation"]["ok"] is True


def test_verify_waterfall_rejects_pool_payment_even_when_cash_conserves() -> None:
    securities = [ovf.common(8_000_000), ovf.option_pool(1_000_000)]
    result = ovf.CapTable(securities=securities).waterfall_detailed(10_000_000)
    # Transfer $1 from common to unallocated capacity; total cash still reconciles.
    payouts = [
        p.model_copy(
            update={"amount": p.amount + (1 if p.security_id == securities[1].security_id else -1)}
        )
        for p in result.payouts
    ]
    with pytest.raises(DomainError, match="unallocated_pool_paid_nothing") as caught:
        _verify(result.model_copy(update={"payouts": payouts}), securities, 10_000_000)
    assert caught.value.code == "invariant_violation"
    assert caught.value.details["checks"]["proceeds_conservation"]["ok"] is True
