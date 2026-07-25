"""V7 policy, dimensional-unit, billing, and rental-risk regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from quant_trade.cloud_rental import (
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    FeasibilityStatus,
    MarketplaceDeliveryEvidence,
    MarketplaceOrderbookEvidence,
    MarketSnapshot,
    ProviderPolicyEvidence,
    PurchaseModel,
    RentalType,
    RevenueAssumptions,
    WorkloadPurpose,
    algorithm_unit,
    compute_rental_economics,
    evaluate_marketplace_evidence,
    evaluate_provider_policy,
    native_hashrate_units,
    verify_market_snapshot_bytes,
)
from quant_trade.evidence.canonical_json import sha256_of_bytes

NOW = "2026-07-24T12:00:00Z"


def _quote(**overrides: object) -> ComputeQuote:
    values: dict[str, object] = {
        "provider": CloudProvider.AWS,
        "sku": "rental.test",
        "region": "us-east-1",
        "purchase_model": PurchaseModel.ON_DEMAND,
        "price_per_hour": 0.0,
        "currency": "USD",
        "source_kind": "fixture",
        "source_name": "offline_fixture",
        "captured_at_utc": NOW,
    }
    values.update(overrides)
    return ComputeQuote(**values)  # type: ignore[arg-type]


def _benchmark(algorithm: str, hashrate_hs: float, **overrides: object) -> BenchmarkEvidence:
    values: dict[str, object] = {
        "provider": CloudProvider.AWS,
        "sku": "rental.test",
        "accelerator_model": "recorded-device",
        "accelerator_count": 1,
        "algorithm": algorithm,
        "hashrate_hs": hashrate_hs,
        "duration_seconds": 3600.0,
        "warmup_seconds": 300.0,
        "shares_accepted": 1000,
        "shares_rejected": 0,
        "captured_at_utc": NOW,
        "source": "fixture:recorded",
        "artifact_sha256": "ab" * 32,
    }
    values.update(overrides)
    return BenchmarkEvidence(**values)  # type: ignore[arg-type]


def _policy(provider: CloudProvider) -> ProviderPolicyEvidence:
    return ProviderPolicyEvidence(
        provider=provider,
        workload=WorkloadPurpose.HASHING_WORKER,
        policy_status="written_approval",
        source_url="https://example.invalid/generic-ticket",
        reviewed_at_utc="2026-07-01T00:00:00Z",
        snapshot_sha256="cd" * 32,
        expires_at_utc="2026-12-31T00:00:00Z",
        human_reviewed=True,
    )


def test_rental_types_are_explicit() -> None:
    assert {item.value for item in RentalType} == {
        "COMPUTE_RENTAL",
        "HASHPOWER_MARKETPLACE",
        "MANAGED_ASIC_LEASE",
    }
    assert _quote().rental_type is RentalType.COMPUTE_RENTAL


def test_compute_engine_rejects_other_rental_types() -> None:
    with pytest.raises(ValueError, match="separate engines"):
        compute_rental_economics(
            _quote(rental_type=RentalType.HASHPOWER_MARKETPLACE),
            _benchmark("kheavyhash", 1e9),
            RevenueAssumptions(hashprice_usd_per_unit_day=0.01),
        )


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (CloudProvider.AWS, FeasibilityStatus.BLOCKED_PROVIDER_TERMS),
        (CloudProvider.ALIBABA, FeasibilityStatus.BLOCKED_PROVIDER_POLICY),
    ],
)
def test_human_reviewed_written_approval_never_unlocks_v7_hashing(
    provider: CloudProvider, expected: FeasibilityStatus
) -> None:
    result = evaluate_provider_policy(
        provider,
        WorkloadPurpose.HASHING_WORKER,
        _policy(provider),
        evaluated_at_utc=NOW,
    )
    assert result.status is expected
    assert result.control_plane_allowed is True
    assert result.hashing_allowed is False


@pytest.mark.parametrize("provider", list(CloudProvider))
def test_control_plane_permission_is_separate_from_hashing(
    provider: CloudProvider,
) -> None:
    result = evaluate_provider_policy(
        provider,
        WorkloadPurpose.CONTROL_PLANE,
        None,
        evaluated_at_utc=NOW,
    )
    assert result.control_plane_allowed is True
    assert result.hashing_allowed is False


def test_algorithm_registry_uses_decimal_native_units() -> None:
    assert algorithm_unit("sha256")["hashes_per_unit"] == Decimal("1000000000000")
    assert algorithm_unit("kheavyhash")["hashes_per_unit"] == Decimal("1000000000")
    assert algorithm_unit("etchash")["hashes_per_unit"] == Decimal("1000000")
    assert algorithm_unit("kheavyhash")["native_unit"] == "GH/s"
    assert algorithm_unit("etchash")["native_unit"] == "MH/s"
    assert native_hashrate_units("kheavyhash", 1e12) == Decimal("1000")
    assert native_hashrate_units("etchash", 1e12) == Decimal("1000000")


def test_market_snapshot_requires_algorithm_coin_network_and_raw_bytes(tmp_path) -> None:
    raw = b'{"hashprice":0.01,"source":"recorded"}'
    raw_path = tmp_path / "market.raw.json"
    raw_path.write_bytes(raw)
    snapshot = MarketSnapshot(
        algorithm_id="kheavyhash",
        coin="KAS",
        network="kaspa-mainnet",
        hashrate_unit="GH/s",
        hashprice_usd_per_unit_day=0.01,
        coin_price_usd=0.1,
        source_name="recorded-test",
        source_url="https://example.invalid",
        captured_at_utc=NOW,
        raw_sha256=sha256_of_bytes(raw),
    )
    assert verify_market_snapshot_bytes(snapshot, raw_path) == []
    raw_path.write_text(json.dumps({"hashprice": 99}), encoding="utf-8")
    assert "do NOT hash" in verify_market_snapshot_bytes(snapshot, raw_path)[0]
    with pytest.raises(ValueError, match="registered for BTC"):
        MarketSnapshot(
            algorithm_id="sha256",
            coin="KAS",
            network="bitcoin-mainnet",
            hashrate_unit="TH/s",
            hashprice_usd_per_unit_day=0.01,
            coin_price_usd=0.1,
            source_name="recorded-test",
            source_url="https://example.invalid",
            captured_at_utc=NOW,
            raw_sha256=sha256_of_bytes(raw),
        )


def test_marketplace_without_delivery_is_discovery_only_and_cannot_purchase(
    tmp_path,
) -> None:
    raw = tmp_path / "orderbook.raw.json"
    raw.write_bytes(b'{"recorded":"orderbook"}')
    orderbook = MarketplaceOrderbookEvidence(
        provider_name="provider-neutral-fixture",
        algorithm_id="sha256",
        coin="BTC",
        network="bitcoin-mainnet",
        native_unit="TH/s",
        price_usd_per_unit_day=0.05,
        min_amount_units=1.0,
        max_amount_units=100.0,
        min_duration_hours=24.0,
        service_fee_rate=0.03,
        visible_liquidity_units=50.0,
        jurisdiction="fixture-jurisdiction",
        kyc_required=True,
        terms_url="https://example.invalid/terms",
        captured_at_utc=NOW,
        raw_sha256=sha256_of_bytes(raw.read_bytes()),
        evidence_class="FIXTURE",
    )
    result = evaluate_marketplace_evidence(orderbook, orderbook_raw_path=raw)
    assert result["status"] == "DISCOVERY_ONLY"
    assert result["purchase_authorized"] is False
    assert result["deposit_authorized"] is False

    delivery_raw = tmp_path / "delivery.raw.json"
    delivery_raw.write_bytes(b'{"recorded":"delivery"}')
    delivery = MarketplaceDeliveryEvidence(
        provider_name=orderbook.provider_name,
        algorithm_id="sha256",
        purchased_units=10.0,
        delivered_units=9.5,
        duration_hours=24.0,
        reject_rate=0.01,
        stale_rate=0.01,
        pool_name="fixture-pool",
        payout_scheme="PPS",
        minimum_payout_coin=0.001,
        cancellation_refund_usd=0.0,
        captured_at_utc=NOW,
        raw_sha256=sha256_of_bytes(delivery_raw.read_bytes()),
        evidence_class="RECORDED_REAL",
    )
    recorded = evaluate_marketplace_evidence(
        orderbook,
        orderbook_raw_path=raw,
        delivery=delivery,
        delivery_raw_path=delivery_raw,
    )
    assert recorded["status"] == "VALID_TEST_ONLY"
    delivery_raw.write_bytes(b'{"recorded":"tampered"}')
    rejected = evaluate_marketplace_evidence(
        orderbook,
        orderbook_raw_path=raw,
        delivery=delivery,
        delivery_raw_path=delivery_raw,
    )
    assert rejected["status"] == "REJECTED_EVIDENCE"


def test_same_physical_hashrate_has_equivalent_native_unit_economics() -> None:
    quote = _quote()
    sha = compute_rental_economics(
        quote,
        _benchmark("sha256", 1e12),
        RevenueAssumptions(hashprice_usd_per_unit_day=0.05),
        horizon_hours=24.0,
    )
    kheavy = compute_rental_economics(
        quote,
        _benchmark("kheavyhash", 1e12),
        RevenueAssumptions(hashprice_usd_per_unit_day=0.00005),
        horizon_hours=24.0,
    )
    etchash = compute_rental_economics(
        quote,
        _benchmark("etchash", 1e12),
        RevenueAssumptions(hashprice_usd_per_unit_day=0.00000005),
        horizon_hours=24.0,
    )
    assert kheavy.horizon_net_usd == pytest.approx(sha.horizon_net_usd)
    assert etchash.horizon_net_usd == pytest.approx(sha.horizon_net_usd)


def test_minimum_billing_and_granularity_are_charged() -> None:
    quote = _quote(
        price_per_hour=2.0,
        minimum_billing_seconds=3600,
        billing_granularity_seconds=900,
    )
    result = compute_rental_economics(
        quote,
        _benchmark("kheavyhash", 1e9),
        RevenueAssumptions(hashprice_usd_per_unit_day=0.0),
        horizon_hours=0.1,
    )
    assert result.billed_hours == 1.0
    assert result.horizon_cost_usd == 2.0
    assert result.horizon_net_usd == -2.0


def test_risk_metrics_are_ordered_and_costs_rejects_are_monotone() -> None:
    benchmark = _benchmark("kheavyhash", 100e9)
    revenue = RevenueAssumptions(
        hashprice_usd_per_unit_day=0.02,
        revenue_scenario_multipliers=(0.25, 0.5, 1.0, 1.5, 2.0),
    )
    base = compute_rental_economics(
        _quote(price_per_hour=0.02), benchmark, revenue, horizon_hours=24.0
    )
    higher_cost = compute_rental_economics(
        _quote(price_per_hour=0.04), benchmark, revenue, horizon_hours=24.0
    )
    more_rejects = compute_rental_economics(
        _quote(price_per_hour=0.02),
        replace(benchmark, shares_rejected=1000),
        revenue,
        horizon_hours=24.0,
    )
    assert base.p05_net_profit_usd <= base.p50_net_profit_usd <= base.p95_net_profit_usd
    assert 0.0 <= base.probability_of_loss <= 1.0
    assert base.cvar95_loss_usd >= 0.0
    assert higher_cost.horizon_net_usd < base.horizon_net_usd
    assert higher_cost.p05_net_profit_usd < base.p05_net_profit_usd
    assert more_rejects.horizon_net_usd < base.horizon_net_usd
    assert more_rejects.p05_net_profit_usd < base.p05_net_profit_usd


def test_interruptions_and_restart_downtime_never_improve_profit() -> None:
    quote = _quote(price_per_hour=0.01)
    benchmark = _benchmark("etchash", 100e6)
    uninterrupted = compute_rental_economics(
        quote,
        benchmark,
        RevenueAssumptions(hashprice_usd_per_unit_day=0.01),
        horizon_hours=24.0,
    )
    interrupted = compute_rental_economics(
        quote,
        benchmark,
        RevenueAssumptions(
            hashprice_usd_per_unit_day=0.01,
            interruption_rate_per_hour=0.5,
            checkpoint_overhead_fraction=0.5,
            restart_seconds=120.0,
        ),
        horizon_hours=24.0,
    )
    assert interrupted.useful_hours < uninterrupted.useful_hours
    assert interrupted.horizon_net_usd < uninterrupted.horizon_net_usd
