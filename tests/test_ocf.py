"""OCF v1.2.0 adapter: seniority direction, hand-derived payouts, refusals, round trips.

Every expected number is derived by hand in docs/ocf.md (cases O1-O11) or in
docs/fixtures.md (the F-series). None is engine output pasted back in.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import ovf
from ovf.instruments import (
    ConvertibleNote,
    DebtInstrument,
    convertible_note,
    debt,
    venture_debt,
)
from ovf.ocf import (
    APPLIED_TRANSACTIONS,
    IGNORED_TRANSACTIONS,
    OCF_SCHEMA_COMMIT,
    REFUSED_TRANSACTIONS,
    Issuer,
    OcfIntegrityError,
    OcfNoteTerms,
    OcfPackage,
    OcfSchemaError,
    OcfUnsupportedError,
    Stakeholder,
    from_ocf,
    import_ocf,
    load_ocf_package,
    note_terms_from,
    to_ocf,
    write_ocf_package,
)
from ovf.ocf.notes import read_notes
from ovf.ocf.schema import (
    PERCENTAGE_PATTERN,
    TRANSACTION_OBJECT_TYPES,
    ConvertibleIssuance,
    Name,
    Ratio,
    StockClass,
)
from tests.fixtures import FIXTURES, WaterfallFixture

FIXTURE_DIR = Path(__file__).parent / "ocf_fixtures"
TWO_SERIES = FIXTURE_DIR / "two_series_seniority"
PARTICIPATING = FIXTURE_DIR / "participating_with_pool"
NOTES = FIXTURE_DIR / "two_series_with_notes"
OCF_SAMPLE = FIXTURE_DIR / "ocf_v1_2_0_sample"

# The terms the notes package cannot carry (docs/ocf.md, "Finding: an OCF v1.2.0 package
# cannot round-trip a convertible note's economics"). EXIT_DATE is the explicit accrual date
# for every note case: CN-1 has run 365 days and CN-2 730 days, no leap day in either span.
NOTE_TERMS = {
    "CN-1": OcfNoteTerms(
        maturity_date=dt.date(2028, 1, 1),
        qualified_financing_threshold=1_000_000,
        day_count="actual/365_fixed",
    ),
    "CN-2": OcfNoteTerms(
        maturity_date=dt.date(2028, 1, 1),
        qualified_financing_threshold=2_000_000,
        day_count="actual/365_fixed",
    ),
}
EXIT_DATE = dt.date(2027, 1, 1)

ISSUER = Issuer(
    object_type="ISSUER",
    id="issuer-example",
    legal_name="Example Robotics, Inc.",
    formation_date=dt.date(2019, 5, 1),
    country_of_formation="US",
)
AS_OF = dt.date(2026, 9, 15)


def payouts(
    table: ovf.CapTable, exit_value: float, as_of: dt.date | None = None
) -> dict[str, float]:
    return {p.security_id: p.amount for p in table.waterfall(exit_value, as_of=as_of)}


def canonical(table: ovf.CapTable) -> dict[str, dict[str, Any]]:
    """Payout-relevant state keyed by security_id.

    Two things OCF does not carry are normalised (docs/ocf.md, "Round trip"): preferred
    and debt seniority each become their dense rank (1 = paid first), because OCF keeps
    only the order; a pool's holder_id becomes its security_id, because an OCF stock plan
    has no holder.
    """
    levels = sorted({s.seniority for s in table.securities if isinstance(s, ovf.PreferredStock)})
    rank = {level: index + 1 for index, level in enumerate(levels)}
    debt_levels = sorted({s.seniority for s in table.securities if isinstance(s, DebtInstrument)})
    debt_rank = {level: index + 1 for index, level in enumerate(debt_levels)}
    state: dict[str, dict[str, Any]] = {}
    for s in table.securities:
        fields: dict[str, Any] = {"kind": type(s).__name__, **s.model_dump()}
        if isinstance(s, ovf.PreferredStock):
            fields["seniority"] = rank[s.seniority]
        if isinstance(s, DebtInstrument):
            fields["seniority"] = debt_rank[s.seniority]
        if isinstance(s, ovf.StockOptionPool):
            fields["holder_id"] = s.security_id
        state[s.security_id] = fields
    return state


def export(table: ovf.CapTable, **kwargs: Any) -> OcfPackage:
    return to_ocf(table, issuer=ISSUER, currency="USD", as_of=AS_OF, **kwargs)


def with_class(package: OcfPackage, class_id: str, **update: Any) -> OcfPackage:
    """Replace fields on one stock class, re-validating it as the reader would see it."""
    classes = tuple(
        StockClass.model_validate({**c.model_dump(exclude_none=True), **update})
        if c.id == class_id
        else c
        for c in package.stock_classes
    )
    return package.model_copy(update={"stock_classes": classes})


def with_transactions(
    package: OcfPackage, edit: Callable[[list[dict[str, Any]]], None]
) -> OcfPackage:
    transactions = [json.loads(json.dumps(tx)) for tx in package.transactions]
    edit(transactions)
    return package.model_copy(update={"transactions": tuple(transactions)})


def tx(transactions: list[dict[str, Any]], tx_id: str) -> dict[str, Any]:
    return next(t for t in transactions if t["id"] == tx_id)


# ---------------------------------------------------------------------------
# Seniority direction: the one convention that must not be guessed
# ---------------------------------------------------------------------------


def test_seniority_direction_follows_the_schema_text() -> None:
    """OCF StockClass.seniority, verbatim, at tag v1.2.0
    (commit 9f987b48e288703ff2cd6c4534f7769bb04e724a,
    schema/objects/StockClass.schema.json):

        "Seniority of the stock - determines repayment priority. Seniority is ordered by
        increasing number so that stock classes with a higher seniority have higher
        repayment priority."

    ovf pays the LOWER integer first, so the mapping inverts. In the fixture Series B has
    OCF seniority 3 and Series A 2, so Series B is repaid first. Case O1 in docs/ocf.md:
    at a $10M exit Series B takes its $9M preference, Series A the $1M remainder and
    common nothing. The opposite reading would pay Series A $5M and Series B $5M.
    """
    assert OCF_SCHEMA_COMMIT == "9f987b48e288703ff2cd6c4534f7769bb04e724a"
    imported = import_ocf(TWO_SERIES)
    assert imported.seniority_ranks == {"series-a": 2, "series-b": 1}
    result = payouts(imported.cap_table, 10_000_000)
    assert result == pytest.approx({"CS-1": 0, "PA-1": 1_000_000, "PB-1": 9_000_000}, abs=1e-6)
    assert result != pytest.approx({"CS-1": 0, "PA-1": 5_000_000, "PB-1": 5_000_000}, abs=1e-6)


def test_the_two_series_fixture_discriminates_the_two_readings() -> None:
    """Case O1, reversed reading: Series A senior pays A $5M and B the $5M left (docs/ocf.md)."""
    table = from_ocf(TWO_SERIES)
    reversed_order = ovf.CapTable(
        securities=[
            s.model_copy(update={"seniority": 3 - s.seniority})
            if isinstance(s, ovf.PreferredStock)
            else s
            for s in table.securities
        ]
    )
    assert payouts(reversed_order, 10_000_000) == pytest.approx(
        {"CS-1": 0, "PA-1": 5_000_000, "PB-1": 5_000_000}, abs=1e-6
    )


def test_two_series_above_total_preference() -> None:
    """Case O2: a $20M exit pays both preferences in full and $6M to common."""
    result = payouts(from_ocf(TWO_SERIES), 20_000_000)
    assert result == pytest.approx(
        {"CS-1": 6_000_000, "PA-1": 5_000_000, "PB-1": 9_000_000}, abs=1e-6
    )


def test_fractional_seniority_between_two_classes() -> None:
    """The schema lets a class inserted between two others take "some decimal number between"."""
    package = load_ocf_package(TWO_SERIES)
    series_a = next(c for c in package.stock_classes if c.id == "series-a")
    inserted = series_a.model_copy(update={"id": "series-a2", "seniority": "2.5"})
    package = package.model_copy(update={"stock_classes": (*package.stock_classes, inserted)})
    assert import_ocf(package).seniority_ranks == {"series-a": 3, "series-a2": 2, "series-b": 1}


def test_equal_seniority_is_pari_passu() -> None:
    """Case O3: equal OCF seniority shares a $10M shortfall 5:9 by preference (as F7)."""
    package = with_class(load_ocf_package(TWO_SERIES), "series-a", seniority="3")
    result = payouts(from_ocf(package), 10_000_000)
    assert result == pytest.approx(
        {"CS-1": 0, "PA-1": 10_000_000 * 5 / 14, "PB-1": 10_000_000 * 9 / 14}, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Participation, pool and ratio adjustments
# ---------------------------------------------------------------------------


def test_participating_fixture_applies_adjustments_and_ignores_the_rest() -> None:
    imported = import_ocf(PARTICIPATING)
    by_id = {s.security_id: s for s in imported.cap_table.securities}
    series_a = by_id["PA-1"]
    pool = by_id["plan-2020"]
    assert isinstance(series_a, ovf.PreferredStock)
    assert isinstance(pool, ovf.StockOptionPool)
    assert (series_a.price, series_a.liquidation_multiple, series_a.conversion_ratio) == (
        2.5,
        1.0,
        1.25,
    )
    assert series_a.participating and series_a.participation_cap == 2.0
    assert (pool.reserved_shares, pool.allocated_shares) == (1_000_000, 0)
    assert imported.ignored_transactions == [
        "TX_STOCK_ACCEPTANCE acc-common-1",
        "TX_STOCK_CLASS_AUTHORIZED_SHARES_ADJUSTMENT auth-series-a",
    ]
    assert imported.currency == "USD"


def test_participating_fixture_ownership() -> None:
    """Case O4: 8M common, 2M x 1.25 = 2.5M as-converted, 1M reserve; 11.5M fully diluted."""
    ownership = from_ocf(PARTICIPATING).ownership_breakdown()
    assert ownership == pytest.approx(
        {"founders": 8 / 11.5, "fund-a": 2.5 / 11.5, "plan-2020": 1 / 11.5}
    )


def test_total_cap_binds() -> None:
    """Case O5: $40M exit, cap includes the preference, so Series A stops at $10M."""
    result = payouts(from_ocf(PARTICIPATING), 40_000_000)
    assert result == pytest.approx(
        {"CS-1": 30_000_000, "PA-1": 10_000_000, "plan-2020": 0}, abs=1e-6
    )


def test_adjusted_ratio_makes_conversion_win() -> None:
    """Case O5: $63M exit, 2.5M/10.5M as converted is $15M, above the $10M cap."""
    result = payouts(from_ocf(PARTICIPATING), 63_000_000)
    assert result == pytest.approx(
        {"CS-1": 48_000_000, "PA-1": 15_000_000, "plan-2020": 0}, abs=1e-6
    )


def test_participation_only_basis_changes_the_number() -> None:
    """Case O6: read as a 2x cap on participation alone, the total cap is 3x ($15M) and does
    not bind at $40M: $5M + 2.5/10.5 x $35M = $40M/3 to Series A, $80M/3 to common."""
    table = from_ocf(PARTICIPATING, participation_cap_basis="participation_only")
    series_a = next(s for s in table.securities if s.security_id == "PA-1")
    assert isinstance(series_a, ovf.PreferredStock)
    assert series_a.participation_cap == 3.0
    assert payouts(table, 40_000_000) == pytest.approx(
        {"CS-1": 80_000_000 / 3, "PA-1": 40_000_000 / 3, "plan-2020": 0}, abs=1e-6
    )


def test_absent_cap_is_non_participating() -> None:
    table = from_ocf(TWO_SERIES)
    assert all(
        not s.participating and s.participation_cap is None
        for s in table.securities
        if isinstance(s, ovf.PreferredStock)
    )


def test_latest_pool_adjustment_wins_and_same_day_agreement_is_accepted() -> None:
    def add_same_day_duplicate(transactions: list[dict[str, Any]]) -> None:
        transactions.append({**tx(transactions, "pool-adj-2"), "id": "pool-adj-2b"})

    table = from_ocf(with_transactions(load_ocf_package(PARTICIPATING), add_same_day_duplicate))
    pool = next(s for s in table.securities if isinstance(s, ovf.StockOptionPool))
    assert pool.reserved_shares == 1_000_000


def test_price_comparison_is_numeric_not_textual() -> None:
    def rewrite(transactions: list[dict[str, Any]]) -> None:
        tx(transactions, "iss-series-a-1")["share_price"]["amount"] = "2.5000"

    table = from_ocf(with_transactions(load_ocf_package(TWO_SERIES), rewrite))
    assert payouts(table, 10_000_000)["PA-1"] == pytest.approx(1_000_000, abs=1e-6)


# ---------------------------------------------------------------------------
# OCF's own sample package
# ---------------------------------------------------------------------------


def test_official_sample_checksums_are_placeholders() -> None:
    with pytest.raises(OcfIntegrityError, match="placeholder checksums"):
        load_ocf_package(OCF_SAMPLE)


def test_official_sample_loads_and_reports_unread_files() -> None:
    package = load_ocf_package(OCF_SAMPLE, verify_md5=False)
    assert len(package.stock_classes) == 2
    assert package.unread_files == (
        "stock_legend_templates_files: ./StockLegends.ocf.json",
        "vesting_terms_files: ./VestingTerms.ocf.json",
        "valuations_files: ./Valuations.ocf.json",
        "financings_files: ./Financings.ocf.json",
    )


def test_official_sample_is_refused_by_a_strict_reading_in_this_order() -> None:
    with pytest.raises(
        OcfUnsupportedError,
        match=r"COMMON StockClass '8d8371e8-d41d-4a49-9f42-b91758fd155d'"
        r"\.liquidation_preference_multiple is 1\..*ignore_common_preference_fields=True",
    ):
        from_ocf(OCF_SAMPLE, verify_md5=False)
    with pytest.raises(
        OcfUnsupportedError,
        match=r"PREFERRED StockClass 'cc775778-7d6e-4f8a-93cf-4df2242d7d6d' has no "
        r"price_per_share",
    ):
        from_ocf(OCF_SAMPLE, verify_md5=False, ignore_common_preference_fields=True)
    patched = with_class(
        load_ocf_package(OCF_SAMPLE, verify_md5=False),
        "cc775778-7d6e-4f8a-93cf-4df2242d7d6d",
        price_per_share={"amount": "1.00", "currency": "USD"},
    )
    with pytest.raises(OcfUnsupportedError, match=r"TX_\w+ is not supported"):
        from_ocf(patched, ignore_common_preference_fields=True)


def test_common_preference_fields_can_be_treated_as_placeholder() -> None:
    package = with_class(
        load_ocf_package(TWO_SERIES),
        "common",
        liquidation_preference_multiple="1",
        participation_cap_multiple="1",
    )
    imported = import_ocf(package, ignore_common_preference_fields=True)
    assert imported.ignored_fields == [
        "COMMON StockClass 'common'.liquidation_preference_multiple = 1 "
        "(ignore_common_preference_fields=True)",
        "COMMON StockClass 'common'.participation_cap_multiple = 1 "
        "(ignore_common_preference_fields=True)",
    ]
    assert payouts(imported.cap_table, 10_000_000) == pytest.approx(
        {"CS-1": 0, "PA-1": 1_000_000, "PB-1": 9_000_000}, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Refusals: each names the field
# ---------------------------------------------------------------------------


def _series_a_right() -> Any:
    package = load_ocf_package(TWO_SERIES)
    series_a = next(c for c in package.stock_classes if c.id == "series-a")
    assert series_a.conversion_rights
    return series_a.conversion_rights[0]


_RIGHT = _series_a_right()
_ZERO_RATIO = _RIGHT.model_copy(
    update={
        "conversion_mechanism": _RIGHT.conversion_mechanism.model_copy(
            update={"ratio": Ratio(numerator="0", denominator="1")}
        )
    }
)


@pytest.mark.parametrize(
    ("class_id", "update", "message"),
    [
        ("series-a", {"price_per_share": None}, r"'series-a' has no price_per_share"),
        (
            "series-a",
            {"liquidation_preference_multiple": None},
            r"no liquidation_preference_multiple; ovf will not assume 1x",
        ),
        ("series-a", {"liquidation_preference_multiple": "-1"}, r"is negative \(-1\)"),
        (
            "series-a",
            {"participation_cap_multiple": "0.5"},
            r"participation_cap_multiple 0\.5 is below liquidation_preference_multiple 1",
        ),
        ("series-a", {"conversion_rights": ()}, r"has 0 conversion_rights"),
        ("series-a", {"conversion_rights": (_RIGHT, _RIGHT)}, r"has 2 conversion_rights"),
        (
            "series-a",
            {"conversion_rights": (_RIGHT.model_copy(update={"converts_to_future_round": True}),)},
            r"converts_to_future_round is true",
        ),
        (
            "series-a",
            {
                "conversion_rights": (
                    _RIGHT.model_copy(update={"converts_to_stock_class_id": "series-b"}),
                )
            },
            r"converts into PREFERRED class 'series-b'",
        ),
        (
            "series-a",
            {
                "conversion_rights": (
                    _RIGHT.model_copy(update={"converts_to_stock_class_id": None}),
                )
            },
            r"has no converts_to_stock_class_id",
        ),
        ("series-a", {"conversion_rights": (_ZERO_RATIO,)}, r"positive numerator and denominator"),
        ("series-a", {"seniority": "1"}, r"\['series-a'\] have seniority at or below the COMMON"),
        ("series-a", {"seniority": "0.5"}, r"at or below the COMMON seniority 1"),
        ("common", {"conversion_rights": (_RIGHT,)}, r"'common' has conversion_rights"),
        (
            "common",
            {"liquidation_preference_multiple": "1"},
            r"'common'\.liquidation_preference_multiple is 1\.",
        ),
        (
            "common",
            {"participation_cap_multiple": "1"},
            r"'common'\.participation_cap_multiple is 1\.",
        ),
    ],
)
def test_class_refusals_name_the_field(class_id: str, update: dict[str, Any], message: str) -> None:
    package = with_class(load_ocf_package(TWO_SERIES), class_id, **update)
    with pytest.raises(OcfUnsupportedError, match=message):
        from_ocf(package)


def test_common_classes_with_different_seniority_are_refused() -> None:
    package = load_ocf_package(TWO_SERIES)
    common = next(c for c in package.stock_classes if c.id == "common")
    extra = common.model_copy(update={"id": "common-b", "seniority": "1.5"})
    package = package.model_copy(update={"stock_classes": (*package.stock_classes, extra)})
    with pytest.raises(OcfUnsupportedError, match=r"COMMON stock classes have different"):
        from_ocf(package)


@pytest.mark.parametrize("object_type", sorted(REFUSED_TRANSACTIONS))
def test_refused_transaction_types_name_themselves(object_type: str) -> None:
    def add(transactions: list[dict[str, Any]]) -> None:
        transactions.append({"object_type": object_type, "id": "tx-x", "date": "2024-01-01"})

    with pytest.raises(OcfUnsupportedError, match=rf"'tx-x': {object_type} is not supported"):
        from_ocf(with_transactions(load_ocf_package(TWO_SERIES), add))


def test_unknown_transaction_type_is_a_schema_error() -> None:
    def add(transactions: list[dict[str, Any]]) -> None:
        transactions.append({"object_type": "TX_STOCK_DIVIDEND", "id": "tx-y"})

    with pytest.raises(OcfSchemaError, match="not an OCF v1.2.0 transaction type"):
        from_ocf(with_transactions(load_ocf_package(TWO_SERIES), add))


def _edit_issuance(tx_id: str, **update: Any) -> Callable[[list[dict[str, Any]]], None]:
    def edit(transactions: list[dict[str, Any]]) -> None:
        tx(transactions, tx_id).update(update)

    return edit


@pytest.mark.parametrize(
    ("edit", "error", "message"),
    [
        (
            _edit_issuance("iss-series-a-1", share_price={"amount": "2.00", "currency": "USD"}),
            OcfUnsupportedError,
            r"share_price 2\.00 USD differs from StockClass 'series-a' price_per_share 2\.50",
        ),
        (
            _edit_issuance("iss-common-1", share_price={"amount": "0.0001", "currency": "EUR"}),
            OcfUnsupportedError,
            r"several currencies \['EUR', 'USD'\]",
        ),
        (
            _edit_issuance("iss-common-1", stock_plan_id="plan-1"),
            OcfUnsupportedError,
            r"stock_plan_id is 'plan-1'",
        ),
        (
            _edit_issuance("iss-series-b-1", date="2026-09-16"),
            OcfUnsupportedError,
            r"dated 2026-09-16, after the package as_of 2026-09-15",
        ),
        (
            _edit_issuance("iss-common-1", quantity="-5"),
            OcfUnsupportedError,
            r"quantity is negative",
        ),
        (
            _edit_issuance("iss-common-1", stakeholder_id="nobody"),
            OcfSchemaError,
            r"unknown stakeholder 'nobody'",
        ),
        (
            _edit_issuance("iss-series-b-1", security_id="PA-1"),
            OcfSchemaError,
            r"security_id 'PA-1' appears twice",
        ),
        (
            _edit_issuance("iss-common-1", quantity="1e6"),
            OcfSchemaError,
            r"quantity: String should match pattern",
        ),
    ],
)
def test_issuance_refusals(
    edit: Callable[[list[dict[str, Any]]], None], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        from_ocf(with_transactions(load_ocf_package(TWO_SERIES), edit))


def test_conflicting_same_day_pool_adjustments_are_refused() -> None:
    def conflict(transactions: list[dict[str, Any]]) -> None:
        transactions.append(
            {**tx(transactions, "pool-adj-2"), "id": "pool-adj-2b", "shares_reserved": "900000"}
        )

    with pytest.raises(OcfUnsupportedError, match=r"are all dated 2022-06-30 and disagree"):
        from_ocf(with_transactions(load_ocf_package(PARTICIPATING), conflict))


def test_plan_reserving_preferred_is_refused() -> None:
    package = load_ocf_package(PARTICIPATING)
    plan = package.stock_plans[0].model_copy(update={"stock_class_ids": ("series-a",)})
    with pytest.raises(OcfUnsupportedError, match=r"reserves PREFERRED class 'series-a'"):
        from_ocf(package.model_copy(update={"stock_plans": (plan,)}))


def test_every_v1_2_0_transaction_type_is_classified_exactly_once() -> None:
    applied, ignored, refused = (
        set(APPLIED_TRANSACTIONS),
        set(IGNORED_TRANSACTIONS),
        set(REFUSED_TRANSACTIONS),
    )
    assert not (applied & ignored or applied & refused or ignored & refused)
    assert applied | ignored | refused == set(TRANSACTION_OBJECT_TYPES)
    assert len(TRANSACTION_OBJECT_TYPES) == 43
    assert (len(applied), len(ignored), len(refused)) == (4, 7, 32)
    assert {t for t in refused if t.startswith("TX_WARRANT_")} == {
        f"TX_WARRANT_{action}"
        for action in (
            "ACCEPTANCE",
            "CANCELLATION",
            "EXERCISE",
            "ISSUANCE",
            "RETRACTION",
            "TRANSFER",
        )
    }


# ---------------------------------------------------------------------------
# Loading from disk
# ---------------------------------------------------------------------------


@pytest.fixture
def package_copy(tmp_path: Path) -> Path:
    target = tmp_path / "pkg"
    shutil.copytree(TWO_SERIES, target)
    return target


def _rewrite_manifest(directory: Path, **update: Any) -> None:
    path = directory / "Manifest.ocf.json"
    manifest = json.loads(path.read_text())
    manifest.update(update)
    path.write_text(json.dumps(manifest))


def test_manifest_path_and_directory_are_equivalent() -> None:
    assert canonical(from_ocf(TWO_SERIES / "Manifest.ocf.json")) == canonical(from_ocf(TWO_SERIES))


def test_other_ocf_versions_are_refused(package_copy: Path) -> None:
    _rewrite_manifest(package_copy, ocf_version="1.1.0")
    with pytest.raises(OcfUnsupportedError, match=r"ocf_version '1\.1\.0' is not supported"):
        load_ocf_package(package_copy)


def test_edited_file_fails_its_checksum(package_copy: Path) -> None:
    path = package_copy / "Transactions.ocf.json"
    path.write_text(path.read_text().replace('"8000000"', '"9000000"'))
    with pytest.raises(OcfIntegrityError, match=r"Transactions\.ocf\.json: manifest md5"):
        load_ocf_package(package_copy)


def test_file_outside_the_package_is_refused(package_copy: Path) -> None:
    _rewrite_manifest(package_copy, stock_plans_files=[{"filepath": "../x.json", "md5": "0" * 32}])
    with pytest.raises(OcfSchemaError, match="outside the package directory"):
        load_ocf_package(package_copy)


def test_two_manifests_in_one_directory_are_refused(package_copy: Path) -> None:
    shutil.copy(package_copy / "Manifest.ocf.json", package_copy / "Manifest2.ocf.json")
    with pytest.raises(OcfSchemaError, match="exactly one OCF_MANIFEST_FILE"):
        load_ocf_package(package_copy)


def test_unknown_property_is_a_schema_error() -> None:
    package = load_ocf_package(TWO_SERIES)
    raw = package.stock_classes[1].model_dump(mode="json", exclude_none=True)
    raw["accruing_dividend_rate"] = "0.08"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        type(package.stock_classes[1]).model_validate(raw)


# ---------------------------------------------------------------------------
# Writer refusals and placeholders
# ---------------------------------------------------------------------------

UNCAPPED = [
    f
    for f in FIXTURES
    if any(
        isinstance(s, ovf.PreferredStock) and s.participating and s.participation_cap is None
        for s in f.securities
    )
]
WRITABLE = [f for f in FIXTURES if f not in UNCAPPED]


@pytest.mark.parametrize("fixture", UNCAPPED, ids=lambda f: f.case_id)
def test_uncapped_participating_is_not_expressible(fixture: WaterfallFixture) -> None:
    with pytest.raises(
        OcfUnsupportedError,
        match="Participating-uncapped preferred is not expressible in OCF v1.2.0",
    ):
        export(ovf.CapTable(securities=list(fixture.securities)))


@pytest.mark.parametrize(
    ("security", "message"),
    [
        (ovf.safe_post(1_000_000, 10_000_000, holder_id="angel"), r"PostMoneySAFE .* no OCF"),
        (ovf.option_pool(1_000_000, allocated_shares=10), r"has allocated_shares 10"),
        (ovf.common(1, price=1e-11, security_id="tiny"), r"tiny\.price = 1e-11 needs 11 decimal"),
        (ovf.common(1, holder_id="ovf-common"), r"object ids would collide: \['ovf-common'\]"),
    ],
)
def test_writer_refusals(security: ovf.Security, message: str) -> None:
    with pytest.raises(OcfUnsupportedError, match=message):
        export(ovf.CapTable(securities=[security]))


def test_writer_argument_errors() -> None:
    table = from_ocf(TWO_SERIES)
    with pytest.raises(ValueError, match="ISO 4217"):
        to_ocf(table, issuer=ISSUER, currency="usd", as_of=AS_OF)
    with pytest.raises(ValueError, match="timezone-aware"):
        export(table, generated_at=dt.datetime(2026, 9, 15))
    wrong = Stakeholder(
        object_type="STAKEHOLDER",
        id="someone-else",
        name=Name(legal_name="X"),
        stakeholder_type="INDIVIDUAL",
    )
    with pytest.raises(ValueError, match="must equal the holder_id"):
        export(table, stakeholders={"founders": wrong})
    with pytest.raises(ValueError, match=r"not in the table: \['nobody'\]"):
        export(table, stakeholders={"nobody": wrong})


def test_writer_marks_placeholders_and_inverts_seniority() -> None:
    package = export(from_ocf(TWO_SERIES))
    classes = {c.id: c for c in package.stock_classes}
    assert {c: classes[c].seniority for c in classes} == {
        "ovf-common": "1",
        "ovf-preferred-1": "2",
        "ovf-preferred-2": "3",
    }
    assert classes["ovf-preferred-2"].price_per_share is not None
    assert classes["ovf-preferred-2"].price_per_share.amount == "6.0"
    assert all("placeholder" in (s.comments or ("",))[0] for s in package.stakeholders)
    assert package.generated_at == dt.datetime(2026, 9, 15, tzinfo=dt.UTC)


def test_ten_decimal_places_round_trip_exactly() -> None:
    table = ovf.CapTable(securities=[ovf.common(1, price=1e-10, security_id="tiny")])
    assert canonical(from_ocf(export(table))) == canonical(table)


def test_write_refuses_to_overwrite_and_to_drop_unread_files(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        write_ocf_package(export(from_ocf(TWO_SERIES)), occupied)
    with pytest.raises(OcfUnsupportedError, match="would silently drop them"):
        write_ocf_package(load_ocf_package(OCF_SAMPLE, verify_md5=False), tmp_path / "new")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("basis", ["total", "participation_only"])
@pytest.mark.parametrize("fixture", WRITABLE, ids=lambda f: f.case_id)
def test_round_trip_over_waterfall_fixtures(fixture: WaterfallFixture, basis: str) -> None:
    table = ovf.CapTable(securities=list(fixture.securities))
    back = from_ocf(export(table, participation_cap_basis=basis), participation_cap_basis=basis)
    assert canonical(back) == canonical(table)
    assert payouts(back, fixture.exit_valuation) == pytest.approx(fixture.expected, abs=1e-6)


@pytest.mark.parametrize("source", [TWO_SERIES, PARTICIPATING], ids=lambda p: p.name)
def test_round_trip_through_disk(source: Path, tmp_path: Path) -> None:
    first = from_ocf(source)
    manifest = write_ocf_package(export(first), tmp_path / "out")
    assert canonical(from_ocf(manifest)) == canonical(first)


_prices = st.integers(min_value=0, max_value=10**9).map(lambda cents: cents / 100)
_shares = st.integers(min_value=0, max_value=10**8).map(float)


@st.composite
def cap_tables(draw: st.DrawFn) -> ovf.CapTable:
    securities: list[ovf.Security] = [
        ovf.common(draw(_shares), holder_id="h0", security_id="c0", price=draw(_prices))
    ]
    for index in range(draw(st.integers(min_value=0, max_value=4))):
        multiple = draw(st.sampled_from([0.5, 1.0, 1.5, 2.0, 3.0]))
        participating = draw(st.booleans())
        securities.append(
            ovf.preferred(
                shares=draw(_shares),
                price=draw(_prices),
                seniority=draw(st.integers(min_value=0, max_value=5)),
                liquidation_multiple=multiple,
                participating=participating,
                participation_cap=(
                    multiple + draw(st.sampled_from([0.0, 0.5, 1.0, 2.0]))
                    if participating
                    else None
                ),
                conversion_ratio=draw(st.sampled_from([1.0, 1.1, 1.25, 2.0, 0.75, 1 / 3])),
                holder_id=f"h{draw(st.integers(min_value=0, max_value=3))}",
                security_id=f"p{index}",
            )
        )
    if draw(st.booleans()):
        securities.append(ovf.option_pool(draw(_shares), holder_id="esop", security_id="pool"))
    for index in range(draw(st.integers(min_value=0, max_value=2))):
        issue = draw(st.dates(min_value=dt.date(2015, 1, 1), max_value=AS_OF))
        securities.append(
            convertible_note(
                draw(st.integers(min_value=1, max_value=10**9)) / 100,
                draw(st.integers(min_value=0, max_value=2_000)) / 10_000,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=issue,
                maturity_date=issue + dt.timedelta(days=draw(st.integers(1, 3_650))),
                seniority=draw(st.integers(min_value=0, max_value=3)),
                qualified_financing_threshold=draw(st.integers(1, 10**9)) / 100,
                valuation_cap=draw(st.none() | st.integers(1, 10**11).map(lambda c: c / 100)),
                discount_rate=draw(st.sampled_from([0.0, 0.1, 0.15, 0.2, 0.25])),
                holder_id=f"h{draw(st.integers(min_value=0, max_value=3))}",
                security_id=f"n{index}",
            )
        )
    return ovf.CapTable(securities=securities)


@settings(max_examples=150, deadline=None)
@given(table=cap_tables(), basis=st.sampled_from(["total", "participation_only"]))
def test_round_trip_property(table: ovf.CapTable, basis: str) -> None:
    """from_ocf(to_ocf(t), note_terms=note_terms_from(t)) reproduces every payout-relevant
    field exactly, as floats. Without note_terms a table holding notes cannot be read back
    (test_a_note_does_not_round_trip_through_ocf_without_its_terms)."""
    back = from_ocf(
        export(table, participation_cap_basis=basis),
        participation_cap_basis=basis,
        note_terms=note_terms_from(table),
    )
    assert canonical(back) == canonical(table)


# ---------------------------------------------------------------------------
# Convertible notes
# ---------------------------------------------------------------------------


def resolved(table: ovf.CapTable, treatment: str = "repay") -> ovf.CapTable:
    """Notes are read unresolved; state the exit treatment, as a caller must."""
    return ovf.CapTable(
        securities=[
            s.resolved(treatment) if isinstance(s, ConvertibleNote) else s for s in table.securities
        ]
    )


def read_notes_package(package: OcfPackage | Path = NOTES) -> ovf.CapTable:
    return from_ocf(package, note_terms=NOTE_TERMS)


def test_convertible_seniority_runs_opposite_to_stock_class_seniority() -> None:
    """Two seniority fields, at the same tag v1.2.0, verbatim:

    StockClass.seniority: "Seniority is ordered by increasing number so that stock classes
    with a higher seniority have higher repayment priority."

    ConvertibleIssuance.seniority: "use this value to build a seniority stack, with 1 being
    highest seniority and equal seniority values assumed to be equal priority".

    Each is read with its own comparator. In the notes package Series B (StockClass 3) is
    senior to Series A (2), and note CN-2 (convertible 1) is senior to CN-1 (2). Case O7 in
    docs/ocf.md: at a $1.5M exit on 2027-01-01 CN-2 takes its $1,160,000 claim and CN-1 the
    $340,000 left. A shared StockClass comparator would pay CN-1 $530,000 and CN-2 $970,000.
    """
    imported = import_ocf(NOTES, note_terms=NOTE_TERMS)
    assert imported.seniority_ranks == {"series-a": 2, "series-b": 1}
    assert imported.debt_seniority_ranks == {"CN-1": 2, "CN-2": 1}
    result = payouts(resolved(imported.cap_table), 1_500_000, EXIT_DATE)
    assert result == pytest.approx(
        {"CS-1": 0, "PA-1": 0, "PB-1": 0, "CN-2": 1_160_000, "CN-1": 340_000}, abs=1e-6
    )
    assert result != pytest.approx(
        {"CS-1": 0, "PA-1": 0, "PB-1": 0, "CN-2": 970_000, "CN-1": 530_000}, abs=1e-6
    )


def test_the_notes_fixture_discriminates_the_two_debt_readings() -> None:
    """Case O7, reversed reading: CN-1 senior takes $530,000 and CN-2 the $970,000 left."""
    table = resolved(read_notes_package())
    reversed_order = ovf.CapTable(
        securities=[
            s.model_copy(update={"seniority": 3 - s.seniority})
            if isinstance(s, ConvertibleNote)
            else s
            for s in table.securities
        ]
    )
    assert payouts(reversed_order, 1_500_000, EXIT_DATE) == pytest.approx(
        {"CS-1": 0, "PA-1": 0, "PB-1": 0, "CN-2": 970_000, "CN-1": 530_000}, abs=1e-6
    )


def test_notes_rank_ahead_of_all_equity_and_preferred_order_is_kept() -> None:
    """Case O8: $11.69M pays both notes ($1.69M) and leaves O1's $10M for equity."""
    result = payouts(resolved(read_notes_package()), 11_690_000, EXIT_DATE)
    assert result == pytest.approx(
        {"CN-2": 1_160_000, "CN-1": 530_000, "PB-1": 9_000_000, "PA-1": 1_000_000, "CS-1": 0},
        abs=1e-6,
    )


def test_equal_convertible_seniority_is_pari_passu() -> None:
    """Case O9: both notes at convertible seniority 1 share $845,000 = half of $1.69M."""

    def level(transactions: list[dict[str, Any]]) -> None:
        tx(transactions, "iss-note-1")["seniority"] = 1

    table = resolved(read_notes_package(with_transactions(load_ocf_package(NOTES), level)))
    assert payouts(table, 845_000, EXIT_DATE) == pytest.approx(
        {"CN-2": 580_000, "CN-1": 265_000, "PB-1": 0, "PA-1": 0, "CS-1": 0}, abs=1e-6
    )


def test_note_terms_are_read_from_ocf_and_from_the_supplement() -> None:
    """Case O10: every ConvertibleNote field, and the hand-derived accruals."""
    by_id = {s.security_id: s for s in read_notes_package().securities}
    cn1, cn2 = by_id["CN-1"], by_id["CN-2"]
    assert isinstance(cn1, ConvertibleNote) and isinstance(cn2, ConvertibleNote)
    assert cn1.model_dump() == {
        "security_id": "CN-1",
        "holder_id": "angel",
        "shares": 0.0,
        "price": 0.0,
        "principal": 500_000.0,
        "annual_rate": 0.06,
        "accrual": ovf.instruments.AccrualMethod.SIMPLE,
        "compounding_frequency": None,
        "day_count": ovf.instruments.DayCount.ACT_365_FIXED,
        "issue_date": dt.date(2026, 1, 1),
        "maturity_date": dt.date(2028, 1, 1),
        "seniority": 2,
        "valuation_cap": 8_000_000.0,
        "discount_rate": 0.2,
        "qualified_financing_threshold": 1_000_000.0,
        "exit_treatment": None,
        "exit_principal_multiple": None,
    }
    assert (cn2.principal, cn2.annual_rate, cn2.issue_date, cn2.seniority) == (
        1_000_000.0,
        0.08,
        dt.date(2025, 1, 1),
        1,
    )
    assert (cn2.valuation_cap, cn2.discount_rate, cn2.qualified_financing_threshold) == (
        None,
        0.0,
        2_000_000.0,
    )
    # CN-1: $500,000 x 0.06 x 365/365; at maturity 730 days, $60,000.
    accrual = cn1.accrue(EXIT_DATE)
    assert (accrual.days, accrual.accrued_interest) == (365, pytest.approx(30_000, abs=1e-9))
    assert cn1.resolved("repay").exit_claim(EXIT_DATE).claim == pytest.approx(530_000)
    assert cn1.repayment_at_maturity().outstanding_amount == pytest.approx(560_000)
    # CN-2: $1,000,000 x 0.08 x 730/365.
    assert cn2.resolved("repay").exit_claim(EXIT_DATE).claim == pytest.approx(1_160_000)


def test_note_read_from_ocf_converts_as_hand_derived() -> None:
    """Case O11: CN-1 reproduces debt fixtures C1 and C2; CN-2's $2M threshold binds."""
    by_id = {s.security_id: s for s in read_notes_package().securities}
    cn1, cn2 = by_id["CN-1"], by_id["CN-2"]
    assert isinstance(cn1, ConvertibleNote) and isinstance(cn2, ConvertibleNote)
    cap = cn1.convert_at_financing(
        EXIT_DATE, new_money=3_000_000, round_price=1.50, capitalization_shares=8_000_000
    )
    assert (cap.binding, cap.conversion_price, cap.shares) == (
        "cap",
        pytest.approx(1.00),
        pytest.approx(530_000),
    )
    discount = cn1.convert_at_financing(
        EXIT_DATE, new_money=3_000_000, round_price=1.10, capitalization_shares=8_000_000
    )
    assert (discount.binding, discount.conversion_price, discount.shares) == (
        "discount",
        pytest.approx(0.88),
        pytest.approx(530_000 / 0.88),
    )
    assert not cn2.is_qualified_financing(1_500_000)
    plain = cn2.convert_at_financing(EXIT_DATE, new_money=2_000_000, round_price=1.60)
    assert (plain.binding, plain.shares) == ("round_price", pytest.approx(725_000))


def test_notes_are_read_unresolved_and_refused_at_exit() -> None:
    with pytest.raises(ValueError, match="no stated exit treatment"):
        read_notes_package().waterfall(11_690_000, as_of=EXIT_DATE)


def test_import_trace_for_notes() -> None:
    imported = import_ocf(NOTES, note_terms=NOTE_TERMS)
    assert imported.ignored_transactions == ["TX_CONVERTIBLE_ACCEPTANCE acc-note-1"]
    assert "TX_CONVERTIBLE_ISSUANCE iss-note-1" in imported.applied_transactions
    assert "no less than $1,000,000" in imported.qualified_financing_conditions["CN-1"]
    assert "no less than $2,000,000" in imported.qualified_financing_conditions["CN-2"]
    assert any("trigger_condition text is not parsed" in a for a in imported.assumptions)
    assert [f.split(":")[0] for f in imported.ignored_fields] == [
        "TX_CONVERTIBLE_ISSUANCE 'iss-note-2'.pro_rata = 0.05",
        "TX_CONVERTIBLE_ISSUANCE 'iss-note-1'.conversion_triggers[0].conversion_right"
        ".conversion_mechanism.capitalization_definition(_rules)",
    ]
    # A package with no notes keeps the eight pre-convertible assumptions and nothing else.
    equity_only = import_ocf(TWO_SERIES)
    assert len(equity_only.assumptions) == 8
    assert imported.assumptions[:8] == equity_only.assumptions
    assert not equity_only.debt_seniority_ranks and not equity_only.qualified_financing_conditions


def test_notes_without_terms_are_refused_naming_the_gap() -> None:
    with pytest.raises(OcfUnsupportedError, match=r"'CN-2'\) has no note_terms\. OCF v1\.2\.0"):
        from_ocf(NOTES)
    with pytest.raises(OcfUnsupportedError, match=r"'CN-1'\) has no note_terms"):
        from_ocf(NOTES, note_terms={"CN-2": NOTE_TERMS["CN-2"]})


def test_note_terms_have_no_defaults() -> None:
    for missing in ("maturity_date", "qualified_financing_threshold", "day_count"):
        values = NOTE_TERMS["CN-1"].model_dump()
        del values[missing]
        with pytest.raises(ValueError, match=missing):
            OcfNoteTerms(**values)
    with pytest.raises(ValueError, match="greater than 0"):
        OcfNoteTerms(**{**NOTE_TERMS["CN-1"].model_dump(), "qualified_financing_threshold": 0})


def _mechanism(transactions: list[dict[str, Any]], tx_id: str = "iss-note-1") -> dict[str, Any]:
    trigger = tx(transactions, tx_id)["conversion_triggers"][0]
    mechanism: dict[str, Any] = trigger["conversion_right"]["conversion_mechanism"]
    return mechanism


def _edit_note(**update: Any) -> Callable[[list[dict[str, Any]]], None]:
    def edit(transactions: list[dict[str, Any]]) -> None:
        tx(transactions, "iss-note-1").update(update)

    return edit


def _edit_mechanism(**update: Any) -> Callable[[list[dict[str, Any]]], None]:
    def edit(transactions: list[dict[str, Any]]) -> None:
        _mechanism(transactions).update(update)

    return edit


def _retype_trigger(trigger_type: str, **extra: Any) -> Callable[[list[dict[str, Any]]], None]:
    def edit(transactions: list[dict[str, Any]]) -> None:
        trigger = tx(transactions, "iss-note-1")["conversion_triggers"][0]
        del trigger["trigger_condition"]
        trigger.update(type=trigger_type, **extra)

    return edit


def _two_triggers(transactions: list[dict[str, Any]]) -> None:
    triggers = tx(transactions, "iss-note-1")["conversion_triggers"]
    triggers.append({**json.loads(json.dumps(triggers[0])), "trigger_id": "CN-1.QF2"})


def _right_type(transactions: list[dict[str, Any]]) -> None:
    right = tx(transactions, "iss-note-1")["conversion_triggers"][0]["conversion_right"]
    right["type"] = "WARRANT_CONVERSION_RIGHT"


def _safe_mechanism(transactions: list[dict[str, Any]]) -> None:
    right = tx(transactions, "iss-note-1")["conversion_triggers"][0]["conversion_right"]
    right["conversion_mechanism"] = {"type": "SAFE_CONVERSION", "conversion_mfn": False}


_RATE = {"rate": "0.06", "accrual_start_date": "2026-01-01"}


@pytest.mark.parametrize(
    ("edit", "error", "message"),
    [
        (
            _edit_note(convertible_type="SAFE"),
            OcfUnsupportedError,
            r"convertible_type is SAFE\. SAFEs are not mapped",
        ),
        (
            _edit_note(convertible_type="CONVERTIBLE_SECURITY"),
            OcfUnsupportedError,
            r"convertible_type is CONVERTIBLE_SECURITY",
        ),
        (
            _retype_trigger("AUTOMATIC_ON_DATE", trigger_date="2028-01-01"),
            OcfUnsupportedError,
            r"'CN-1\.QF'\) is AUTOMATIC_ON_DATE: it converts automatically on a date",
        ),
        (
            _retype_trigger("ELECTIVE_AT_WILL"),
            OcfUnsupportedError,
            r"is ELECTIVE_AT_WILL: it gives the holder an option to convert",
        ),
        (
            _retype_trigger("ELECTIVE_IN_RANGE", start_date="2026-01-01", end_date="2027-01-01"),
            OcfUnsupportedError,
            r"is ELECTIVE_IN_RANGE",
        ),
        (_retype_trigger("UNSPECIFIED"), OcfUnsupportedError, r"is UNSPECIFIED: it has no"),
        (_two_triggers, OcfUnsupportedError, r"has 2 AUTOMATIC_ON_CONDITION triggers"),
        (_right_type, OcfUnsupportedError, r"conversion_right\.type is WARRANT_CONVERSION_RIGHT"),
        (
            _safe_mechanism,
            OcfUnsupportedError,
            r"conversion_mechanism\.type is 'SAFE_CONVERSION'",
        ),
        (
            _edit_mechanism(day_count_convention="30_360"),
            OcfUnsupportedError,
            r"day_count_convention is 30_360\. OCF does not say which 30/360 variant",
        ),
        (
            _edit_mechanism(interest_payout="CASH"),
            OcfUnsupportedError,
            r"interest_payout is CASH",
        ),
        (
            _edit_mechanism(compounding_type="COMPOUNDING"),
            OcfUnsupportedError,
            r"compounding_type is COMPOUNDING\. .* no compounding frequency",
        ),
        (
            _edit_mechanism(interest_accrual_period="MONTHLY"),
            OcfUnsupportedError,
            r"interest_accrual_period is MONTHLY",
        ),
        (
            _edit_mechanism(interest_rates=[]),
            OcfUnsupportedError,
            r"interest_rates has 0 entries: none; .* will not assume a 0% rate",
        ),
        (
            _edit_mechanism(interest_rates=[_RATE, {**_RATE, "accrual_start_date": "2027-01-01"}]),
            OcfUnsupportedError,
            r"interest_rates has 2 entries: a schedule of rates",
        ),
        (
            _edit_mechanism(interest_rates=[{**_RATE, "rate": ""}]),
            OcfUnsupportedError,
            r"rate is the empty string\. The OCF v1\.2\.0 Percentage pattern admits it",
        ),
        (
            _edit_mechanism(interest_rates=[{**_RATE, "accrual_start_date": "2026-02-01"}]),
            OcfUnsupportedError,
            r"accrual_start_date 2026-02-01 differs from the issuance date 2026-01-01",
        ),
        (
            _edit_mechanism(interest_rates=[{**_RATE, "accrual_end_date": "2027-12-31"}]),
            OcfUnsupportedError,
            r"accrual_end_date is 2027-12-31",
        ),
        (
            _edit_mechanism(exit_multiple={"numerator": "2", "denominator": "1"}),
            OcfUnsupportedError,
            r"exit_multiple is 2/1\. OCF says only",
        ),
        (
            _edit_mechanism(conversion_mfn=True),
            OcfUnsupportedError,
            r"conversion_mfn is true",
        ),
        (
            _edit_mechanism(conversion_discount="1"),
            OcfUnsupportedError,
            r"conversion_discount is 1; a discount of 100%",
        ),
        (
            _edit_mechanism(conversion_discount=""),
            OcfUnsupportedError,
            r"conversion_discount is the empty string",
        ),
        (
            _edit_mechanism(conversion_valuation_cap={"amount": "8000000", "currency": "EUR"}),
            OcfUnsupportedError,
            r"several currencies \['EUR', 'USD'\]",
        ),
        (
            _edit_note(investment_amount={"amount": "0", "currency": "USD"}),
            OcfUnsupportedError,
            r"investment_amount\.amount is 0; ovf requires a positive amount",
        ),
        (
            _edit_note(date="2026-09-16"),
            OcfUnsupportedError,
            r"TX_CONVERTIBLE_ISSUANCE 'iss-note-1' is dated 2026-09-16, after the package as_of",
        ),
        (
            _edit_note(stakeholder_id="nobody"),
            OcfSchemaError,
            r"'iss-note-1' references unknown stakeholder 'nobody'",
        ),
        (
            _edit_note(seniority="1"),
            OcfSchemaError,
            r"seniority must be a JSON integer",
        ),
        (
            _retype_trigger("AUTOMATIC_ON_CONDITION"),
            OcfSchemaError,
            r"AUTOMATIC_ON_CONDITION trigger requires trigger_condition",
        ),
        (
            _edit_mechanism(interest_payout="PIK"),
            OcfSchemaError,
            r"does not match OCF v1\.2\.0 NoteConversionMechanism: interest_payout",
        ),
    ],
)
def test_note_refusals_name_the_field(
    edit: Callable[[list[dict[str, Any]]], None], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        read_notes_package(with_transactions(load_ocf_package(NOTES), edit))


def _terms(**update: Any) -> OcfNoteTerms:
    return OcfNoteTerms(**{**NOTE_TERMS["CN-1"].model_dump(), **update})


def test_note_terms_refusals() -> None:
    contradiction = {**NOTE_TERMS, "CN-1": _terms(day_count="actual/360")}
    with pytest.raises(
        OcfUnsupportedError,
        match=r"day_count_convention is ACTUAL_365 but note_terms\['CN-1'\]\.day_count is "
        r"actual/360\. The two contradict",
    ):
        from_ocf(NOTES, note_terms=contradiction)
    with pytest.raises(ValueError, match=r"not convertible issuances in this package: \['PA-1'\]"):
        from_ocf(NOTES, note_terms={**NOTE_TERMS, "PA-1": NOTE_TERMS["CN-1"]})
    early = {**NOTE_TERMS, "CN-1": _terms(maturity_date=dt.date(2025, 6, 1))}
    with pytest.raises(OcfUnsupportedError, match=r"'CN-1': ovf rejects the note .* maturity"):
        from_ocf(NOTES, note_terms=early)


def test_ocf_percentage_pattern_admits_the_empty_string() -> None:
    """types/Percentage at v1.2.0 makes every part optional in its first alternative."""
    assert re.fullmatch(PERCENTAGE_PATTERN, "") is not None
    assert re.fullmatch(PERCENTAGE_PATTERN, "0.125") is not None
    assert re.fullmatch(PERCENTAGE_PATTERN, "1.5") is None


def _sample_transactions(object_type: str) -> dict[str, dict[str, Any]]:
    data = json.loads((OCF_SAMPLE / "Transactions.ocf.json").read_text())
    return {t["id"]: t for t in data["items"] if t["object_type"] == object_type}


def test_official_sample_convertibles_validate_and_are_refused_for_what_they_carry() -> None:
    samples = _sample_transactions("TX_CONVERTIBLE_ISSUANCE")
    assert len(samples) == 4
    issuances = {tx_id: ConvertibleIssuance.model_validate(raw) for tx_id, raw in samples.items()}
    expected = {
        "test-convertible-issuance-minimal": r"is AUTOMATIC_ON_DATE",
        "test-convertible-custom-conversion-issuance-minimal": r"is AUTOMATIC_ON_DATE",
        "test-convertible-issuance-all-fields": r"convertible_type is SAFE",
        "test-safe-issuance-all-fields": r"convertible_type is SAFE",
    }
    for tx_id, message in expected.items():
        with pytest.raises(OcfUnsupportedError, match=message):
            read_notes([issuances[tx_id]], {})
    # The sample's "SAFE" carries a note mechanism with a three-rate interest schedule:
    # nothing in OCF ties convertible_type to the mechanism that states the economics.
    mechanism = samples["test-convertible-issuance-all-fields"]["conversion_triggers"][0][
        "conversion_right"
    ]["conversion_mechanism"]
    assert mechanism["type"] == "CONVERTIBLE_NOTE_CONVERSION"
    assert len(mechanism["interest_rates"]) == 3


def test_official_sample_warrants_state_inconsistent_or_no_share_counts() -> None:
    """Evidence for docs/ocf.md, 'What a warrant model would have to carry'."""
    warrants = _sample_transactions("TX_WARRANT_ISSUANCE")
    minimal = warrants["test-warrant-issuance-minimal"]
    mechanism = minimal["exercise_triggers"][0]["conversion_right"]["conversion_mechanism"]
    assert (minimal["quantity"], mechanism["converts_to_quantity"]) == ("1000", "10000.00")
    pps = warrants["test-pps-based-warrant-issuance-full-fields"]
    assert "quantity" not in pps and "exercise_price" not in pps


def test_notes_package_is_refused_on_warrants() -> None:
    def add_warrant(transactions: list[dict[str, Any]]) -> None:
        transactions.append(
            {**_sample_transactions("TX_WARRANT_ISSUANCE")["test-warrant-issuance-minimal"]}
        )

    with pytest.raises(OcfUnsupportedError, match=r"TX_WARRANT_ISSUANCE is not supported"):
        read_notes_package(with_transactions(load_ocf_package(NOTES), add_warrant))


# ---------------------------------------------------------------------------
# Writing notes, and debt OCF cannot carry
# ---------------------------------------------------------------------------


def _note(**kwargs: Any) -> ConvertibleNote:
    terms: dict[str, Any] = {
        "accrual": "simple",
        "day_count": "actual/365_fixed",
        "issue_date": dt.date(2026, 1, 1),
        "maturity_date": dt.date(2028, 1, 1),
        "seniority": 0,
        "qualified_financing_threshold": 1_000_000,
        "holder_id": "angel",
        "security_id": "note",
    }
    terms.update(kwargs)
    return convertible_note(500_000, 0.06, **terms)


@pytest.mark.parametrize(
    ("security", "message"),
    [
        (
            debt(
                1_000_000,
                0.08,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=dt.date(2025, 1, 1),
                seniority=0,
            ),
            r"DebtInstrument .* is non-convertible debt\. OCF v1\.2\.0 has no object",
        ),
        (
            venture_debt(
                2_000_000,
                0.10,
                exit_fee=60_000,
                accrual="simple",
                day_count="actual/365_fixed",
                issue_date=dt.date(2025, 1, 1),
                seniority=0,
            ),
            r"VentureDebt .* is non-convertible debt",
        ),
        (_note(accrual="compound", compounding_frequency=1), r"accrues compound interest"),
        (_note(accrual="pik", compounding_frequency=2), r"accrues pik interest"),
        (_note(day_count="actual/360"), r"uses day count actual/360\. OCF v1\.2\.0 offers only"),
        (_note().resolved("repay"), r"has exit_treatment 'repay'\. OCF v1\.2\.0 has no repayment"),
        (
            _note().resolved("multiple", exit_principal_multiple=2),
            r"has exit_treatment 'multiple'",
        ),
        (_note(issue_date=dt.date(2026, 10, 1)), r"issued on 2026-10-01, after as_of 2026-09-15"),
    ],
)
def test_writer_refuses_debt_ocf_cannot_carry(security: ovf.Security, message: str) -> None:
    with pytest.raises(OcfUnsupportedError, match=message):
        export(ovf.CapTable(securities=[security]))


def test_writer_does_not_invert_note_seniority() -> None:
    package = export(read_notes_package())
    written = {
        t["security_id"]: t["seniority"]
        for t in package.transactions
        if t["object_type"] == "TX_CONVERTIBLE_ISSUANCE"
    }
    assert written == {"CN-2": 1, "CN-1": 2}
    classes = {c.id: c.seniority for c in package.stock_classes}
    assert classes == {"ovf-common": "1", "ovf-preferred-1": "2", "ovf-preferred-2": "3"}


def test_a_note_does_not_round_trip_through_ocf_without_its_terms() -> None:
    """The finding, as an assertion: OCF v1.2.0 cannot carry a note's economics.

    The writer has nowhere structured to put a maturity date or a qualified-financing
    threshold, so it writes them into comments (and the threshold into trigger text). The
    package it produces is refused on read until the caller supplies them again.
    """
    table = read_notes_package()
    package = export(table)
    with pytest.raises(OcfUnsupportedError, match="carries no maturity date"):
        from_ocf(package)
    notes = {
        t["security_id"]: t
        for t in package.transactions
        if t["object_type"] == "TX_CONVERTIBLE_ISSUANCE"
    }
    for security_id, threshold in (("CN-1", "1000000.0"), ("CN-2", "2000000.0")):
        issuance = json.loads(json.dumps(notes[security_id]))
        assert "2028-01-01" in " ".join(issuance.pop("comments"))
        trigger = issuance["conversion_triggers"][0]
        assert threshold in trigger.pop("trigger_condition")
        structured = json.dumps(issuance)
        assert "2028-01-01" not in structured and threshold not in structured
    back = from_ocf(package, note_terms=note_terms_from(table))
    assert canonical(back) == canonical(table)
    assert payouts(resolved(back), 1_500_000, EXIT_DATE) == pytest.approx(
        {"CS-1": 0, "PA-1": 0, "PB-1": 0, "CN-2": 1_160_000, "CN-1": 340_000}, abs=1e-6
    )


def test_notes_round_trip_through_disk(tmp_path: Path) -> None:
    first = read_notes_package()
    manifest = write_ocf_package(export(first), tmp_path / "out")
    assert canonical(from_ocf(manifest, note_terms=NOTE_TERMS)) == canonical(first)


# ---------------------------------------------------------------------------
# Optional: validation against the real OCF JSON Schema
# ---------------------------------------------------------------------------

OCF_SCHEMA_DIR = os.environ.get("OCF_SCHEMA_DIR")
_FILE_SCHEMAS = {
    "OCF_MANIFEST_FILE": "files/OCFManifestFile.schema.json",
    "OCF_STOCK_CLASSES_FILE": "files/StockClassesFile.schema.json",
    "OCF_STAKEHOLDERS_FILE": "files/StakeholdersFile.schema.json",
    "OCF_STOCK_PLANS_FILE": "files/StockPlansFile.schema.json",
    "OCF_TRANSACTIONS_FILE": "files/TransactionsFile.schema.json",
}


@pytest.mark.skipif(
    not OCF_SCHEMA_DIR, reason="set OCF_SCHEMA_DIR to the schema/ directory of OCF v1.2.0"
)
def test_packages_validate_against_the_ocf_schema(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    assert OCF_SCHEMA_DIR is not None
    root = Path(OCF_SCHEMA_DIR)
    schemas: dict[str, Any] = {}
    registry = referencing.Registry()
    for path in root.rglob("*.schema.json"):
        document = json.loads(path.read_text())
        schemas[document["$id"]] = document
        registry = registry.with_resource(
            document["$id"], referencing.Resource.from_contents(document)
        )
    base = "https://schema.opencaptablecoalition.com/v/1.2.0/"
    object_type_id = base + "enums/ObjectType.schema.json"
    assert object_type_id in schemas, (
        f"{root} does not contain OCF v1.2.0 schemas. Schema $id values are version-pinned, "
        "so a checkout on main or another tag will not match. Check out tag v1.2.0 "
        "(commit 9f987b4) and point OCF_SCHEMA_DIR at its schema/ directory."
    )
    enum = schemas[object_type_id]["enum"]
    assert set(TRANSACTION_OBJECT_TYPES) == {t for t in enum if t.startswith("TX_")}
    assert schemas[base + "types/Percentage.schema.json"]["pattern"] == PERCENTAGE_PATTERN

    packages = [TWO_SERIES, PARTICIPATING, NOTES]
    for index, fixture in enumerate(WRITABLE):
        table = ovf.CapTable(securities=list(fixture.securities))
        packages.append(write_ocf_package(export(table), tmp_path / str(index)).parent)
    packages.append(write_ocf_package(export(read_notes_package()), tmp_path / "notes").parent)
    for package in packages:
        for file in sorted(package.glob("*.json")):
            data = json.loads(file.read_text())
            validator = jsonschema.Draft7Validator(
                schemas[base + _FILE_SCHEMAS[data["file_type"]]],
                registry=registry,
                format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
            )
            errors = [error.message for error in validator.iter_errors(data)]
            assert not errors, f"{file}: {errors[:3]}"
