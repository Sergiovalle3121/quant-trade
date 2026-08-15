"""Adversarial offline tests for the AANV30 data-feasibility gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from quant_trade.data.aanv30_feasibility import (
    AANV30_FORMULA,
    V1_REQUIRED_ATTESTATION_BLOCKER_CODES,
    AANV30AssetEvidence,
    AANV30Blocker,
    AANV30FeasibilityError,
    AANV30FeasibilityStatus,
    AANV30FeasibilityVerdict,
    AANV30Identity,
    ActiveAddressMetricDefinition,
    BlockerSeverity,
    CommercialLicenseStatus,
    DailyActiveAddressesEvidence,
    MarketCapAtDecisionEvidence,
    evaluate_aanv30_data_feasibility,
)

DECISION = "2023-11-01T12:00:00Z"
SOURCE_SHA = "a" * 64
LICENSE_SHA = "b" * 64


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity(cmc_id: int) -> AANV30Identity:
    return AANV30Identity(
        chain_id=f"chain-{cmc_id}",
        contract_or_native_id=f"contract-{cmc_id}",
        cmc_id=cmc_id,
    )


def _daily_row(
    identity: AANV30Identity,
    measurement_date: date,
    *,
    definition: ActiveAddressMetricDefinition = (
        ActiveAddressMetricDefinition.DAILY_ACTIVE_ADDRESSES
    ),
    published_at_utc: str | None = None,
) -> DailyActiveAddressesEvidence:
    day_end = datetime.combine(measurement_date + timedelta(days=1), time.min, tzinfo=UTC)
    return DailyActiveAddressesEvidence(
        identity=identity,
        measurement_date=measurement_date.isoformat(),
        active_addresses=1_000 + int(identity.cmc_id or 0),
        metric_definition=definition,
        observed_at_utc=_utc(day_end + timedelta(hours=1)),
        computed_at_utc=_utc(day_end + timedelta(hours=2)),
        published_at_utc=published_at_utc or _utc(day_end + timedelta(hours=3)),
        method_name="daily-successful-transaction-addresses",
        method_version="1.0.0",
        source_name="licensed-offline-fixture",
        source_bytes_sha256=SOURCE_SHA,
        license_status=CommercialLicenseStatus.COMMERCIAL_USE_PERMITTED,
        license_terms_sha256=LICENSE_SHA,
        license_verified_at_utc="2023-01-01T00:00:00Z",
    )


def _asset(cmc_id: int) -> AANV30AssetEvidence:
    identity = _identity(cmc_id)
    decision = datetime.fromisoformat(DECISION.replace("Z", "+00:00"))
    first_day = decision.date() - timedelta(days=30)
    rows = tuple(_daily_row(identity, first_day + timedelta(days=offset)) for offset in range(30))
    market_cap = MarketCapAtDecisionEvidence(
        identity=identity,
        effective_at_utc=DECISION,
        market_cap_usd=str(10_000_000 + cmc_id),
        observed_at_utc=DECISION,
        computed_at_utc=DECISION,
        published_at_utc=DECISION,
        method_name="point-in-time-market-cap",
        method_version="1.0.0",
        source_name="licensed-offline-fixture",
        source_bytes_sha256="c" * 64,
        license_status=CommercialLicenseStatus.COMMERCIAL_USE_PERMITTED,
        license_terms_sha256=LICENSE_SHA,
        license_verified_at_utc="2023-01-01T00:00:00Z",
    )
    return AANV30AssetEvidence(
        identity=identity,
        daily_active_addresses=rows,
        market_cap_at_decision=market_cap,
    )


def _population(size: int = 100) -> tuple[AANV30AssetEvidence, ...]:
    return tuple(_asset(cmc_id) for cmc_id in range(1, size + 1))


def _blocker_codes(verdict: object) -> set[str]:
    assert hasattr(verdict, "blockers")
    return {blocker.code for blocker in verdict.blockers}  # type: ignore[attr-defined]


def test_exact_100_asset_metadata_remains_insufficient_without_attestation() -> None:
    verdict = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert verdict.eligible_assets == 100
    assert verdict.causal_assets_evaluated == 100
    assert verdict.formula == AANV30_FORMULA
    assert _blocker_codes(verdict) == set(V1_REQUIRED_ATTESTATION_BLOCKER_CODES)
    assert verdict.real_money_authorized is False
    assert verdict.signal_generation_authorized is False
    assert verdict.pnl_evaluation_authorized is False
    assert verdict.holdout_access_authorized is False
    assert verdict.network_access_authorized is False
    assert verdict.profitability_evidence is False
    assert "score" not in verdict.to_dict()
    assert "return" not in verdict.to_dict()


def test_99_eligible_assets_are_insufficient_for_top_quintile_of_20() -> None:
    verdict = evaluate_aanv30_data_feasibility(_population(99), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert verdict.eligible_assets == 99
    assert "FEWER_THAN_100_ELIGIBLE_ASSETS" in _blocker_codes(verdict)


def test_unknown_license_fails_closed_as_insufficient() -> None:
    assets = list(_population())
    first = assets[0]
    changed_row = replace(
        first.daily_active_addresses[0],
        license_status=CommercialLicenseStatus.UNKNOWN,
    )
    assets[0] = replace(
        first,
        daily_active_addresses=(changed_row, *first.daily_active_addresses[1:]),
    )

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "LICENSE_STATUS_UNKNOWN" in _blocker_codes(verdict)
    assert verdict.eligible_assets == 99


@pytest.mark.parametrize(
    "license_status",
    [
        CommercialLicenseStatus.RESEARCH_ONLY,
        CommercialLicenseStatus.COMMERCIAL_USE_PROHIBITED,
    ],
)
def test_explicitly_noncommercial_license_is_no_go(
    license_status: CommercialLicenseStatus,
) -> None:
    assets = list(_population())
    first = assets[0]
    changed_cap = replace(first.market_cap_at_decision, license_status=license_status)
    assets[0] = replace(first, market_cap_at_decision=changed_cap)

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "COMMERCIAL_USE_NOT_PERMITTED" in _blocker_codes(verdict)


def test_window_unique_count_is_not_silently_accepted_as_daily_mean_input() -> None:
    assets = list(_population())
    first = assets[0]
    wrong = replace(
        first.daily_active_addresses[0],
        metric_definition=ActiveAddressMetricDefinition.WINDOW_UNIQUE_ACTIVE_ADDRESSES,
    )
    assets[0] = replace(first, daily_active_addresses=(wrong, *first.daily_active_addresses[1:]))

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "WINDOW_UNIQUE_METRIC_REJECTED" in _blocker_codes(verdict)


def test_missing_exact_day_is_insufficient_and_duplicate_day_is_no_go() -> None:
    assets = list(_population())
    first = assets[0]
    assets[0] = replace(first, daily_active_addresses=first.daily_active_addresses[:-1])
    missing = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)
    assert missing.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "ACTIVE_ADDRESS_COVERAGE_NOT_EXACT" in _blocker_codes(missing)

    assets[0] = replace(
        first,
        daily_active_addresses=(
            *first.daily_active_addresses[:-1],
            first.daily_active_addresses[0],
        ),
    )
    duplicate = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)
    assert duplicate.status is AANV30FeasibilityStatus.NO_GO
    assert "DUPLICATE_DAILY_OBSERVATION" in _blocker_codes(duplicate)


def test_publication_after_decision_cannot_complete_a_past_window() -> None:
    assets = list(_population())
    first = assets[0]
    late = replace(first.daily_active_addresses[-1], published_at_utc="2023-11-02T00:00:00Z")
    assets[0] = replace(first, daily_active_addresses=(*first.daily_active_addresses[:-1], late))

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert verdict.eligible_assets == 99
    assert "ACTIVE_ADDRESS_COVERAGE_NOT_EXACT" in _blocker_codes(verdict)


def test_appending_future_publications_changes_no_verdict_byte() -> None:
    original = _population()
    before = evaluate_aanv30_data_feasibility(original, decision_at_utc=DECISION)

    first = original[0]
    future_correction = replace(
        first.daily_active_addresses[0],
        active_addresses=999_999_999,
        published_at_utc="2023-11-02T00:00:00Z",
    )
    changed_first = replace(
        first,
        daily_active_addresses=(*first.daily_active_addresses, future_correction),
    )
    future_asset = _asset(999)
    future_asset = replace(
        future_asset,
        daily_active_addresses=tuple(
            replace(row, published_at_utc="2023-11-02T00:00:00Z")
            for row in future_asset.daily_active_addresses
        ),
        market_cap_at_decision=replace(
            future_asset.market_cap_at_decision,
            published_at_utc="2023-11-02T00:00:00Z",
        ),
    )
    future_daily_only = replace(
        _asset(1_000),
        daily_active_addresses=tuple(
            replace(row, published_at_utc="2023-11-03T00:00:00Z")
            for row in _asset(1_000).daily_active_addresses
        ),
        market_cap_at_decision=None,
    )
    after = evaluate_aanv30_data_feasibility(
        (changed_first, *original[1:], future_asset, future_daily_only),
        decision_at_utc=DECISION,
    )

    assert before.to_dict() == after.to_dict()
    assert before.digest() == after.digest()


def test_input_order_and_daily_row_order_do_not_change_canonical_verdict() -> None:
    original = _population()
    reversed_rows = tuple(
        replace(asset, daily_active_addresses=tuple(reversed(asset.daily_active_addresses)))
        for asset in reversed(original)
    )

    left = evaluate_aanv30_data_feasibility(original, decision_at_utc=DECISION)
    right = evaluate_aanv30_data_feasibility(reversed_rows, decision_at_utc=DECISION)

    assert left.to_dict() == right.to_dict()


def test_identity_collision_and_row_identity_mismatch_are_no_go() -> None:
    assets = list(_population())
    first, second = assets[0], assets[1]
    colliding = replace(
        second,
        identity=AANV30Identity(
            chain_id=second.identity.chain_id,
            contract_or_native_id=second.identity.contract_or_native_id,
            cmc_id=first.identity.cmc_id,
        ),
    )
    assets[1] = colliding

    collision = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)
    assert collision.status is AANV30FeasibilityStatus.NO_GO
    assert "CMC_IDENTITY_COLLISION" in _blocker_codes(collision)
    assert "IDENTITY_MISMATCH" in _blocker_codes(collision)


def test_incomplete_identity_is_insufficient_not_assumed() -> None:
    assets = list(_population())
    first = assets[0]
    missing = AANV30Identity(
        chain_id=first.identity.chain_id,
        contract_or_native_id=None,
        cmc_id=first.identity.cmc_id,
    )
    assets[0] = replace(first, identity=missing)

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "IDENTITY_MISSING" in _blocker_codes(verdict)


def test_pit_timestamp_order_violation_is_no_go() -> None:
    assets = list(_population())
    first = assets[0]
    bad = replace(
        first.daily_active_addresses[0],
        computed_at_utc="2023-10-02T00:30:00Z",
    )
    assets[0] = replace(first, daily_active_addresses=(bad, *first.daily_active_addresses[1:]))

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "PIT_TIMESTAMP_ORDER_INVALID" in _blocker_codes(verdict)


def test_method_change_and_invalid_source_digest_are_no_go() -> None:
    assets = list(_population())
    first = assets[0]
    bad = replace(
        first.daily_active_addresses[0],
        method_version="2.0.0",
        source_bytes_sha256="not-a-sha",
    )
    assets[0] = replace(first, daily_active_addresses=(bad, *first.daily_active_addresses[1:]))

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "DAILY_METHOD_CHANGED_WITHIN_WINDOW" in _blocker_codes(verdict)
    assert "SOURCE_SHA256_INVALID" in _blocker_codes(verdict)


def test_unknown_source_digest_and_timestamp_are_insufficient() -> None:
    assets = list(_population())
    first = assets[0]
    bad = replace(
        first.daily_active_addresses[0],
        source_bytes_sha256=None,
        computed_at_utc=None,
    )
    assets[0] = replace(first, daily_active_addresses=(bad, *first.daily_active_addresses[1:]))

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "SOURCE_SHA256_MISSING" in _blocker_codes(verdict)
    assert "PIT_TIMESTAMP_MISSING" in _blocker_codes(verdict)


def test_market_cap_must_be_positive_canonical_and_effective_at_decision() -> None:
    assets = list(_population())
    first = assets[0]
    bad_cap = replace(
        first.market_cap_at_decision,
        market_cap_usd="0",
        effective_at_utc="2023-11-01T11:59:59Z",
    )
    assets[0] = replace(first, market_cap_at_decision=bad_cap)

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "MARKET_CAP_VALUE_INVALID" in _blocker_codes(verdict)
    assert "MARKET_CAP_NOT_AT_DECISION" in _blocker_codes(verdict)


def test_changed_active_address_value_under_same_claimed_sha_never_clears_v1() -> None:
    original = _population()
    baseline = evaluate_aanv30_data_feasibility(original, decision_at_utc=DECISION)
    first = original[0]
    original_row = first.daily_active_addresses[0]
    changed_row = replace(
        original_row,
        active_addresses=(original_row.active_addresses or 0) + 1,
        # Deliberately retain the caller-asserted source hash.  V1 has no raw
        # byte loader with which to prove or disprove this projection.
        source_bytes_sha256=original_row.source_bytes_sha256,
    )
    changed_first = replace(
        first,
        daily_active_addresses=(changed_row, *first.daily_active_addresses[1:]),
    )
    changed = evaluate_aanv30_data_feasibility(
        (changed_first, *original[1:]), decision_at_utc=DECISION
    )

    assert baseline.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert changed.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "SOURCE_BYTES_REHASH_ATTESTATION_MISSING" in _blocker_codes(changed)
    assert baseline.causal_evidence_sha256 != changed.causal_evidence_sha256


def test_self_asserted_commercial_license_never_clears_v1() -> None:
    verdict = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "COMMERCIAL_LICENSE_ATTESTATION_MISSING" in _blocker_codes(verdict)
    assert "HISTORICAL_VINTAGE_ATTESTATION_MISSING" in _blocker_codes(verdict)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("source_name", "different-provider"),
        ("method_name", "different-active-address-definition"),
        ("method_version", "2.0.0"),
    ],
)
def test_mixed_active_address_provider_or_method_across_assets_is_no_go(
    field_name: str,
    value: str,
) -> None:
    assets = list(_population())
    first = assets[0]
    changed_rows = tuple(
        replace(row, **{field_name: value}) for row in first.daily_active_addresses
    )
    assets[0] = replace(first, daily_active_addresses=changed_rows)

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "CROSS_ASSET_ACTIVE_ADDRESS_METHOD_MISMATCH" in _blocker_codes(verdict)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("source_name", "different-market-cap-provider"),
        ("method_name", "different-market-cap-definition"),
        ("method_version", "2.0.0"),
    ],
)
def test_mixed_market_cap_provider_or_method_across_assets_is_no_go(
    field_name: str,
    value: str,
) -> None:
    assets = list(_population())
    first = assets[0]
    changed_cap = replace(first.market_cap_at_decision, **{field_name: value})
    assets[0] = replace(first, market_cap_at_decision=changed_cap)

    verdict = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)

    assert verdict.status is AANV30FeasibilityStatus.NO_GO
    assert "CROSS_ASSET_MARKET_CAP_METHOD_MISMATCH" in _blocker_codes(verdict)


def test_invalid_decision_is_rejected_before_any_evidence_is_inspected() -> None:
    with pytest.raises(AANV30FeasibilityError, match="canonical UTC"):
        evaluate_aanv30_data_feasibility((), decision_at_utc="2023-11-01")


def test_direct_structurally_consistent_feasible_constructor_is_rejected_in_v1() -> None:
    insufficient = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)

    with pytest.raises(AANV30FeasibilityError, match="schema v1 cannot construct FEASIBLE"):
        AANV30FeasibilityVerdict(
            status=AANV30FeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION,
            decision_at_utc=insufficient.decision_at_utc,
            expected_first_measurement_date=insufficient.expected_first_measurement_date,
            expected_last_measurement_date=insufficient.expected_last_measurement_date,
            causal_assets_evaluated=100,
            eligible_assets=100,
            minimum_eligible_assets=100,
            future_top_quintile_size=20,
            formula=AANV30_FORMULA,
            blockers=(),
            causal_evidence_sha256="d" * 64,
        )


@pytest.mark.parametrize(
    ("field_name", "forged_value", "message"),
    [
        ("status", AANV30FeasibilityStatus.NO_GO, "status"),
        ("eligible_assets", 99, "coverage blocker"),
        ("causal_assets_evaluated", 99, "no smaller"),
        ("minimum_eligible_assets", 99, "frozen policy"),
        ("future_top_quintile_size", 21, "frozen policy"),
        ("formula", "different", "frozen AANV30"),
        ("causal_evidence_sha256", "not-a-sha", "SHA-256"),
        ("expected_first_measurement_date", "2023-10-03", "exact AANV30 window"),
        ("expected_last_measurement_date", "2023-10-30", "exact AANV30 window"),
    ],
)
def test_public_verdict_constructor_rejects_feasible_forgery(
    field_name: str,
    forged_value: object,
    message: str,
) -> None:
    valid = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)

    with pytest.raises(AANV30FeasibilityError, match=message):
        replace(valid, **{field_name: forged_value})


def test_public_verdict_constructor_derives_status_from_blocker_severity() -> None:
    insufficient = evaluate_aanv30_data_feasibility(_population(99), decision_at_utc=DECISION)
    with pytest.raises(AANV30FeasibilityError, match="external attestation loader"):
        replace(
            insufficient,
            status=AANV30FeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION,
        )

    assets = list(_population())
    first = assets[0]
    wrong = replace(
        first.daily_active_addresses[0],
        metric_definition=ActiveAddressMetricDefinition.WINDOW_UNIQUE_ACTIVE_ADDRESSES,
    )
    assets[0] = replace(first, daily_active_addresses=(wrong, *first.daily_active_addresses[1:]))
    no_go = evaluate_aanv30_data_feasibility(tuple(assets), decision_at_utc=DECISION)
    with pytest.raises(AANV30FeasibilityError, match="status"):
        replace(no_go, status=AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE)


def test_public_verdict_constructor_rejects_untyped_or_noncanonical_blockers() -> None:
    valid = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)
    hard = AANV30Blocker(code="HARD_BLOCKER", severity=BlockerSeverity.HARD, count=1)
    missing = AANV30Blocker(code="MISSING_BLOCKER", severity=BlockerSeverity.MISSING, count=1)

    with pytest.raises(AANV30FeasibilityError, match="typed immutable tuple"):
        replace(valid, blockers=[hard])
    with pytest.raises(AANV30FeasibilityError, match="canonical severity/code order"):
        replace(
            valid,
            status=AANV30FeasibilityStatus.NO_GO,
            blockers=(missing, hard),
        )
    with pytest.raises(AANV30FeasibilityError, match="combined"):
        replace(
            valid,
            status=AANV30FeasibilityStatus.NO_GO,
            blockers=(hard, hard),
        )


def test_public_verdict_constructor_cannot_enable_safety_flags() -> None:
    valid = evaluate_aanv30_data_feasibility(_population(), decision_at_utc=DECISION)
    payload = {
        "status": valid.status,
        "decision_at_utc": valid.decision_at_utc,
        "expected_first_measurement_date": valid.expected_first_measurement_date,
        "expected_last_measurement_date": valid.expected_last_measurement_date,
        "causal_assets_evaluated": valid.causal_assets_evaluated,
        "eligible_assets": valid.eligible_assets,
        "minimum_eligible_assets": valid.minimum_eligible_assets,
        "future_top_quintile_size": valid.future_top_quintile_size,
        "formula": valid.formula,
        "blockers": valid.blockers,
        "causal_evidence_sha256": valid.causal_evidence_sha256,
        "real_money_authorized": True,
    }

    with pytest.raises(TypeError, match="real_money_authorized"):
        AANV30FeasibilityVerdict(**payload)  # type: ignore[arg-type]
