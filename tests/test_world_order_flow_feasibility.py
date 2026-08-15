"""Adversarial offline tests for the world-order-flow data gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pytest

from quant_trade.data.world_order_flow_feasibility import (
    MINIMUM_CROSS_SECTION_ASSETS,
    PAPER_DAILY_CALENDAR,
    REQUIRED_FIAT_CURRENCIES,
    BlockerSeverity,
    CommercialLicenseStatus,
    SignedVolumeDefinition,
    SourceScope,
    WorldOrderFlowCalendarEvidence,
    WorldOrderFlowFeasibilityError,
    WorldOrderFlowFeasibilityStatus,
    WorldOrderFlowFeasibilityVerdict,
    WorldOrderFlowIdentity,
    WorldOrderFlowObservation,
    evaluate_world_order_flow_data_feasibility,
)

DECISION = "2025-04-02T12:00:00Z"
VENUES = ("cryptocompare-aggregate",)


def _measurement_dates() -> tuple[date, ...]:
    values: list[date] = []
    cursor = date(2025, 2, 19)
    while len(values) < 30:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)
    return tuple(values)


CALENDAR = WorldOrderFlowCalendarEvidence(
    measurement_dates=tuple(day.isoformat() for day in _measurement_dates()),
    calendar_name=PAPER_DAILY_CALENDAR,
    method_version="paper-rule-v1",
    source_name="reviewed-us-holiday-calendar",
    source_bytes_sha256="d" * 64,
    observed_at_utc="2025-02-18T00:00:00Z",
)
FIRST_MEASUREMENT_DATE = _measurement_dates()[0]


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _observation(
    asset_index: int = 0,
    measurement_day: date = FIRST_MEASUREMENT_DATE,
    currency: str = "USD",
) -> WorldOrderFlowObservation:
    complete_at = datetime.combine(measurement_day + timedelta(days=1), datetime.min.time(), UTC)
    return WorldOrderFlowObservation(
        identity=WorldOrderFlowIdentity(
            cmc_id=10_000 + asset_index,
            chain_id="native",
            contract_or_native_id=f"native-{asset_index}",
        ),
        measurement_date=measurement_day.isoformat(),
        fiat_currency=currency,
        buyer_initiated_volume="100.25",
        seller_initiated_volume="98.75",
        contributing_venues=VENUES,
        signed_volume_definition=SignedVolumeDefinition.BUYER_AND_SELLER_INITIATED,
        source_scope=SourceScope.MULTI_VENUE_FIAT,
        computed_at_utc=_stamp(complete_at + timedelta(minutes=5)),
        published_at_utc=_stamp(complete_at + timedelta(minutes=10)),
        observed_at_utc=_stamp(complete_at + timedelta(minutes=15)),
        provider_name="CCData",
        source_contract="cryptocompare_signed_volume_g11_multi_exchange",
        method_name="buyer-seller-initiator-classification",
        method_version="2026.01",
        source_bytes_sha256="a" * 64,
        license_status=CommercialLicenseStatus.COMMERCIAL_USE_PERMITTED,
        license_terms_sha256="b" * 64,
        license_verified_at_utc="2025-02-18T00:00:00Z",
    )


@lru_cache(maxsize=1)
def _passing_population() -> tuple[WorldOrderFlowObservation, ...]:
    return tuple(
        _observation(asset_index, measurement_day, currency)
        for asset_index in range(MINIMUM_CROSS_SECTION_ASSETS)
        for measurement_day in _measurement_dates()
        for currency in REQUIRED_FIAT_CURRENCIES
    )


def _blocker_codes(verdict: object) -> set[str]:
    return {blocker.code for blocker in verdict.blockers}  # type: ignore[attr-defined]


def test_exact_paper_scale_panel_is_structurally_complete_but_unattested() -> None:
    verdict = evaluate_world_order_flow_data_feasibility(
        _passing_population(), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert verdict.eligible_assets == 84
    assert "EXTERNAL_SOURCE_LICENSE_VINTAGE_ATTESTATION_NOT_IMPLEMENTED" in _blocker_codes(verdict)
    assert verdict.required_fiat_currencies == REQUIRED_FIAT_CURRENCIES
    assert len(REQUIRED_FIAT_CURRENCIES) == 11
    assert verdict.structural_feasibility_only is True
    assert verdict.preregistration_authorized is False
    assert verdict.signal_generation_authorized is False
    assert verdict.model_training_authorized is False
    assert verdict.portfolio_sort_authorized is False
    assert verdict.backtest_authorized is False
    assert verdict.pnl_evaluation_authorized is False
    assert verdict.holdout_access_authorized is False
    assert verdict.network_access_authorized is False
    assert verdict.real_money_authorized is False
    assert verdict.profitability_evidence is False
    assert verdict.to_dict()["seal"] == verdict.seal


def test_prefix_invariance_ignores_later_data_and_later_vintages() -> None:
    baseline = evaluate_world_order_flow_data_feasibility(
        _passing_population(), calendar=CALENDAR, decision_at_utc=DECISION
    )
    later_day = replace(
        _observation(measurement_day=date(2025, 4, 3)),
        computed_at_utc="2025-04-04T00:05:00Z",
        published_at_utc="2025-04-04T00:10:00Z",
        observed_at_utc="2025-04-04T00:15:00Z",
    )
    later_revision = replace(
        _passing_population()[0],
        source_bytes_sha256="c" * 64,
        computed_at_utc="2025-04-03T00:05:00Z",
        published_at_utc="2025-04-03T00:10:00Z",
        observed_at_utc="2025-04-03T00:15:00Z",
    )

    with_future = evaluate_world_order_flow_data_feasibility(
        _passing_population() + (later_day, later_revision),
        calendar=CALENDAR,
        decision_at_utc=DECISION,
    )

    assert with_future.to_dict() == baseline.to_dict()


def test_binance_usdt_kline_proxy_is_an_explicit_no_go() -> None:
    proxy = replace(
        _observation(),
        fiat_currency="USDT",
        contributing_venues=("binance",),
        signed_volume_definition=SignedVolumeDefinition.TAKER_BUY_ONLY_DERIVED_COMPLEMENT,
        source_scope=SourceScope.SINGLE_VENUE,
        provider_name="local-binance-kline-cache",
        source_contract="binance_spot_usdt_kline",
    )
    verdict = evaluate_world_order_flow_data_feasibility(
        (proxy,), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.NO_GO
    assert {
        "NON_G11_OR_MISSING_FIAT",
        "SIGNED_BUY_SELL_VOLUME_NOT_PROVEN",
        "MULTI_VENUE_FIAT_SCOPE_NOT_PROVEN",
        "PAPER_SOURCE_PROVIDER_NOT_PROVEN",
        "PAPER_SIGNED_VOLUME_CONTRACT_NOT_PROVEN",
    } <= _blocker_codes(verdict)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CommercialLicenseStatus.NON_COMMERCIAL_ONLY, WorldOrderFlowFeasibilityStatus.NO_GO),
        (CommercialLicenseStatus.UNKNOWN, WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE),
    ],
)
def test_commercial_rights_fail_closed(
    status: CommercialLicenseStatus, expected: WorldOrderFlowFeasibilityStatus
) -> None:
    row = replace(_observation(), license_status=status)
    verdict = evaluate_world_order_flow_data_feasibility(
        (row,), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is expected
    assert "COMMERCIAL_LICENSE_NOT_PROVEN" in _blocker_codes(verdict)


def test_missing_pit_vintage_and_identity_are_insufficient() -> None:
    row = replace(
        _observation(),
        identity=WorldOrderFlowIdentity(None, None, None),
        observed_at_utc=None,
        computed_at_utc=None,
        published_at_utc=None,
    )
    verdict = evaluate_world_order_flow_data_feasibility(
        (row,), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert {
        "UNSTABLE_OR_MISSING_IDENTITY",
        "OBSERVED_AT_INVALID_OR_MISSING",
        "COMPUTED_AT_INVALID_OR_MISSING",
        "PUBLISHED_AT_INVALID_OR_MISSING",
    } <= _blocker_codes(verdict)


def test_impossible_prepublished_daily_volume_is_no_go() -> None:
    row = replace(
        _observation(),
        computed_at_utc="2025-02-19T12:00:00Z",
        published_at_utc="2025-02-19T12:05:00Z",
        observed_at_utc="2025-02-19T12:10:00Z",
    )
    verdict = evaluate_world_order_flow_data_feasibility(
        (row,), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.NO_GO
    assert "VINTAGE_PRECEDES_COMPLETE_DAILY_MEASUREMENT" in _blocker_codes(verdict)


def test_missing_g11_cells_cannot_be_called_feasible() -> None:
    verdict = evaluate_world_order_flow_data_feasibility(
        (_observation(),), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "INCOMPLETE_30_DAY_G11_PANEL" in _blocker_codes(verdict)
    assert "CROSS_SECTION_COVERAGE_BELOW_84_ASSETS" in _blocker_codes(verdict)


def test_source_venue_coverage_claim_is_required() -> None:
    row = replace(_observation(), contributing_venues=())
    verdict = evaluate_world_order_flow_data_feasibility(
        (row,), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
    assert "SOURCE_VENUE_COVERAGE_INSUFFICIENT" in _blocker_codes(verdict)


def test_duplicate_asset_day_fiat_cell_is_no_go() -> None:
    row = _observation()
    verdict = evaluate_world_order_flow_data_feasibility(
        (row, row), calendar=CALENDAR, decision_at_utc=DECISION
    )

    assert verdict.status is WorldOrderFlowFeasibilityStatus.NO_GO
    assert "DUPLICATE_ASSET_DAY_FIAT_CELL" in _blocker_codes(verdict)


def test_public_constructor_cannot_fabricate_feasible_status() -> None:
    genuine = evaluate_world_order_flow_data_feasibility(
        _passing_population(), calendar=CALENDAR, decision_at_utc=DECISION
    )
    no_blockers = tuple(
        blocker for blocker in genuine.blockers if blocker.severity is not BlockerSeverity.MISSING
    )

    with pytest.raises(
        WorldOrderFlowFeasibilityError,
        match="v1 cannot construct FEASIBLE_FOR_PREREGISTRATION",
    ):
        WorldOrderFlowFeasibilityVerdict(
            status=WorldOrderFlowFeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION,
            decision_at_utc=genuine.decision_at_utc,
            expected_first_measurement_date=genuine.expected_first_measurement_date,
            expected_last_measurement_date=genuine.expected_last_measurement_date,
            assets_evaluated=genuine.assets_evaluated,
            eligible_assets=genuine.eligible_assets,
            minimum_cross_section_assets=genuine.minimum_cross_section_assets,
            required_fiat_currencies=genuine.required_fiat_currencies,
            calendar_name=genuine.calendar_name,
            calendar_evidence_sha256=genuine.calendar_evidence_sha256,
            formula=genuine.formula,
            blockers=no_blockers,
            causal_evidence_sha256=genuine.causal_evidence_sha256,
        )


@pytest.mark.parametrize("decision", ["2026-01-31", "2026-01-31T12:00:00", "not-a-date"])
def test_ambiguous_decision_instant_is_rejected(decision: str) -> None:
    with pytest.raises(WorldOrderFlowFeasibilityError):
        evaluate_world_order_flow_data_feasibility((), calendar=CALENDAR, decision_at_utc=decision)
