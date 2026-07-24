"""Tests for policy-gated AWS/Alibaba rental evaluation (all offline)."""

from __future__ import annotations

import pytest

from quant_trade.cloud_rental import (
    SAFETY_POSTURE,
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    FeasibilityStatus,
    InstanceSpecification,
    ProviderPolicyEvidence,
    PurchaseModel,
    RevenueAssumptions,
    WorkloadPurpose,
    compute_rental_economics,
    evaluate_feasibility,
    feasibility_matrix,
    matrix_markdown,
)
from quant_trade.cloud_rental.alibaba_readonly import AlibabaReadOnlyPriceAdapter
from quant_trade.cloud_rental.aws_readonly import AwsReadOnlyPriceAdapter
from quant_trade.cloud_rental.catalog import check_quote_freshness

NOW = "2026-07-24T12:00:00Z"


def _quote(provider=CloudProvider.AWS, **overrides) -> ComputeQuote:
    base = dict(
        provider=provider,
        sku="p5.48xlarge" if provider is CloudProvider.AWS else "ecs.gn7i-c32g1.8xlarge",
        region="us-east-1" if provider is CloudProvider.AWS else "us-west-1",
        purchase_model=PurchaseModel.ON_DEMAND,
        price_per_hour=10.0,
        currency="USD",
        source_kind="fixture",
        source_name="offline_fixture",
        captured_at_utc="2026-07-24T10:00:00Z",
        max_age_hours=24.0,
    )
    base.update(overrides)
    return ComputeQuote(**base)


def _spec(provider=CloudProvider.AWS, architecture="gpu", **overrides) -> InstanceSpecification:
    base = dict(
        provider=provider,
        sku="p5.48xlarge" if provider is CloudProvider.AWS else "ecs.gn7i-c32g1.8xlarge",
        region="us-east-1" if provider is CloudProvider.AWS else "us-west-1",
        architecture=architecture,
        vcpus=192,
        memory_gb=2048.0,
        accelerator_model="NVIDIA H100",
        accelerator_count=8,
    )
    base.update(overrides)
    return InstanceSpecification(**base)


def _benchmark(provider=CloudProvider.AWS, **overrides) -> BenchmarkEvidence:
    base = dict(
        provider=provider,
        sku="p5.48xlarge" if provider is CloudProvider.AWS else "ecs.gn7i-c32g1.8xlarge",
        accelerator_model="NVIDIA H100",
        accelerator_count=8,
        algorithm="sha256",
        hashrate_hs=2.0e10,  # measured: ~20 GH/s — honestly tiny vs ASICs
        duration_seconds=3600.0,
        warmup_seconds=300.0,
        shares_accepted=1000,
        shares_rejected=5,
        captured_at_utc="2026-07-20T00:00:00Z",
        source="offline benchmark artifact",
        artifact_sha256="ab" * 32,
    )
    base.update(overrides)
    return BenchmarkEvidence(**base)


def _approval(provider=CloudProvider.AWS, status="written_approval") -> ProviderPolicyEvidence:
    return ProviderPolicyEvidence(
        provider=provider,
        workload=WorkloadPurpose.HASHING_WORKER,
        policy_status=status,
        source_url="https://example.test/approval",
        reviewed_at_utc="2026-07-01T00:00:00Z",
        snapshot_sha256="cd" * 32,
        expires_at_utc="2026-12-31T00:00:00Z",
        human_reviewed=True,
    )


# --- policy gates ---------------------------------------------------------


def test_aws_hashing_without_written_approval_is_blocked():
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=_benchmark(),
        policy_evidence=None,
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_PENDING_WRITTEN_APPROVAL)
    assert "1.25" in decision.policy_reason
    assert decision.economic_reason == ""  # legal block never becomes economic


def test_aws_free_tier_or_credits_is_blocked_even_with_approval():
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(uses_free_tier_or_credits=True),
        spec=_spec(),
        benchmark=_benchmark(),
        policy_evidence=_approval(),
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_PROVIDER_POLICY)
    assert "Free Tier" in decision.policy_reason


def test_alibaba_hashing_blocked_by_default():
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(provider=CloudProvider.ALIBABA),
        spec=_spec(provider=CloudProvider.ALIBABA),
        benchmark=_benchmark(provider=CloudProvider.ALIBABA),
        policy_evidence=None,
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_PROVIDER_POLICY)
    assert "security-violation" in decision.policy_reason


def test_alibaba_ambiguous_evidence_is_policy_unknown():
    ambiguous = ProviderPolicyEvidence(
        provider=CloudProvider.ALIBABA,
        workload=WorkloadPurpose.HASHING_WORKER,
        policy_status="unknown",
        source_url="https://example.test/ticket",
        reviewed_at_utc="2026-07-01T00:00:00Z",
        snapshot_sha256="ef" * 32,
        expires_at_utc="2026-12-31T00:00:00Z",
        human_reviewed=True,
    )
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(provider=CloudProvider.ALIBABA),
        spec=_spec(provider=CloudProvider.ALIBABA),
        benchmark=_benchmark(provider=CloudProvider.ALIBABA),
        policy_evidence=ambiguous,
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_POLICY_UNKNOWN)


def test_expired_approval_fails_closed():
    stale = ProviderPolicyEvidence(
        provider=CloudProvider.AWS,
        workload=WorkloadPurpose.HASHING_WORKER,
        policy_status="written_approval",
        source_url="https://example.test/approval",
        reviewed_at_utc="2025-01-01T00:00:00Z",
        snapshot_sha256="cd" * 32,
        expires_at_utc="2025-06-30T00:00:00Z",  # expired
        human_reviewed=True,
    )
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=_benchmark(),
        policy_evidence=stale,
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_PENDING_WRITTEN_APPROVAL)
    assert "expired" in decision.policy_reason


def test_control_plane_is_evaluable_and_distinct_from_hashing():
    for provider in (CloudProvider.AWS, CloudProvider.ALIBABA):
        decision = evaluate_feasibility(
            purpose=WorkloadPurpose.CONTROL_PLANE,
            quote=_quote(provider=provider, price_per_hour=0.10),
            spec=_spec(provider=provider, architecture="cpu", accelerator_count=0,
                       accelerator_model=""),
            benchmark=None,
            policy_evidence=None,
            horizon_hours=720.0,
            budget_ceiling_usd=200.0,
            evaluated_at_utc=NOW,
        )
        assert decision.status == str(FeasibilityStatus.PAPER_CONTROL_PLANE_CANDIDATE)
        assert "no resources are created" in decision.policy_reason


# --- benchmark gates (defect F) -------------------------------------------


def test_manual_hashrate_without_benchmark_is_rejected():
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=_benchmark(),
        policy_evidence=_approval(),
        manual_hashrate_declared=True,  # a 100 TH/s number typed into YAML
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK)
    assert "not evidence" in decision.benchmark_reason


def test_cpu_gpu_sha256_without_benchmark_is_incompatible_hardware():
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(architecture="gpu"),
        benchmark=None,
        policy_evidence=_approval(),
        algorithm="sha256",
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_INCOMPATIBLE_HARDWARE)


def test_benchmark_from_another_sku_is_not_reusable():
    foreign = _benchmark(sku="g5.xlarge")
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=foreign,
        policy_evidence=_approval(),
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK)
    assert "not transferable" in decision.benchmark_reason


def test_stale_benchmark_is_rejected():
    old = _benchmark(captured_at_utc="2025-01-01T00:00:00Z")
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=old,
        policy_evidence=_approval(),
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK)


# --- quote validation -----------------------------------------------------


def test_expired_quote_fails():
    stale_quote = _quote(captured_at_utc="2026-07-20T00:00:00Z", max_age_hours=24.0)
    problems = check_quote_freshness(stale_quote, evaluated_at_utc=NOW)
    assert any("exceeds max age" in p for p in problems)


def test_future_quote_fails():
    future_quote = _quote(captured_at_utc="2026-08-01T00:00:00Z")
    problems = check_quote_freshness(future_quote, evaluated_at_utc=NOW)
    assert any("future" in p for p in problems)


def test_aws_spot_and_on_demand_sources_cannot_mix():
    with pytest.raises(ValueError, match="DescribeSpotPriceHistory"):
        _quote(purchase_model=PurchaseModel.SPOT, source_kind="price_list")
    with pytest.raises(ValueError, match="Price List"):
        _quote(purchase_model=PurchaseModel.ON_DEMAND, source_kind="spot_price_history")


# --- economics ------------------------------------------------------------


def test_gpu_sha256_economics_is_a_massive_no_go():
    # A measured ~20 GH/s GPU benchmark vs a $10/h SKU: revenue is microscopic.
    decision = evaluate_feasibility(
        purpose=WorkloadPurpose.HASHING_WORKER,
        quote=_quote(),
        spec=_spec(),
        benchmark=_benchmark(),
        policy_evidence=_approval(),
        revenue=RevenueAssumptions(hashprice_usd_per_th_day=0.05),
        evaluated_at_utc=NOW,
    )
    assert decision.status == str(FeasibilityStatus.ECONOMIC_NO_GO)
    details = decision.details or {}
    assert details["margin_per_hour_usd"] < 0
    assert details["revenue_per_useful_hour_usd"] < 0.001  # fractions of a cent


def test_no_multi_year_npv_for_rentals():
    with pytest.raises(ValueError, match="cancelable-rental cap"):
        compute_rental_economics(
            _quote(),
            _benchmark(),
            RevenueAssumptions(hashprice_usd_per_th_day=0.05),
            horizon_hours=24.0 * 365 * 3,  # 3 years like owned hardware — refused
        )


def test_budget_ceiling_is_enforced():
    econ = compute_rental_economics(
        _quote(price_per_hour=100.0),
        _benchmark(),
        RevenueAssumptions(hashprice_usd_per_th_day=0.05),
        horizon_hours=720.0,
        budget_ceiling_usd=1000.0,
    )
    assert not econ.within_budget


def test_interruption_and_fees_reduce_revenue():
    rich = RevenueAssumptions(hashprice_usd_per_th_day=100.0)
    poor = RevenueAssumptions(
        hashprice_usd_per_th_day=100.0,
        pool_fee_rate=0.05,
        interruption_rate_per_hour=0.5,
        checkpoint_overhead_fraction=0.5,
    )
    econ_rich = compute_rental_economics(_quote(), _benchmark(), rich)
    econ_poor = compute_rental_economics(_quote(), _benchmark(), poor)
    assert econ_poor.revenue_per_useful_hour_usd < econ_rich.revenue_per_useful_hour_usd


# --- adapters are read-only -----------------------------------------------


def test_adapters_have_no_creation_verbs():
    forbidden = {
        "run_instances", "create_instance", "create_instances", "terminate_instances",
        "start_instances", "stop_instances", "request_spot_instances",
        "create_fleet", "deploy", "apply",
    }
    for adapter in (AwsReadOnlyPriceAdapter, AlibabaReadOnlyPriceAdapter):
        assert forbidden.isdisjoint(dir(adapter)), adapter.__name__


# --- matrix ----------------------------------------------------------------


def test_feasibility_matrix_four_rows_and_markdown():
    configs = []
    for provider in (CloudProvider.AWS, CloudProvider.ALIBABA):
        configs.append(
            {
                "purpose": WorkloadPurpose.CONTROL_PLANE,
                "quote": _quote(provider=provider, price_per_hour=0.10),
                "spec": _spec(provider=provider, architecture="cpu",
                              accelerator_count=0, accelerator_model=""),
                "benchmark": None,
                "policy_evidence": None,
                "horizon_hours": 720.0,
                "budget_ceiling_usd": 200.0,
            }
        )
        configs.append(
            {
                "purpose": WorkloadPurpose.HASHING_WORKER,
                "quote": _quote(provider=provider),
                "spec": _spec(provider=provider),
                "benchmark": None,
                "policy_evidence": None,
            }
        )
    rows = feasibility_matrix(configs, evaluated_at_utc=NOW)
    assert len(rows) == 4
    statuses = {(r.provider, r.purpose): r.status for r in rows}
    assert statuses[("aws", "control_plane")] == str(
        FeasibilityStatus.PAPER_CONTROL_PLANE_CANDIDATE
    )
    assert statuses[("aws", "hashing_worker")] == str(
        FeasibilityStatus.BLOCKED_PENDING_WRITTEN_APPROVAL
    )
    assert statuses[("alibaba", "control_plane")] == str(
        FeasibilityStatus.PAPER_CONTROL_PLANE_CANDIDATE
    )
    assert statuses[("alibaba", "hashing_worker")] == str(
        FeasibilityStatus.BLOCKED_PROVIDER_POLICY
    )
    markdown = matrix_markdown(rows)
    assert "BLOCKED_PENDING_WRITTEN_APPROVAL" in markdown
    assert "BLOCKED_PROVIDER_POLICY" in markdown
    # every decision carries the safety posture
    for row in rows:
        assert row.safety == SAFETY_POSTURE
