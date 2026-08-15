from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import quant_trade.ops.crypto_gates as crypto_gates
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.crypto_capital import (
    CapitalFeasibility,
    CapitalFeasibilityRequest,
    CapitalInstrumentEvidence,
    FxEvidence,
    evaluate_capital_feasibility,
)
from quant_trade.ops.crypto_gates import (
    CanaryEvidence,
    CanaryPolicy,
    CanaryScaleEvidence,
    CryptoGateError,
    Gate0Evidence,
    Gate0Verdict,
    ShadowEvidence,
    ShadowPolicy,
    VenuePolicy,
    canary_capital_limit,
    canary_order_limit,
    evaluate_canary_readiness,
    evaluate_canary_scale,
    evaluate_gate0,
    evaluate_shadow,
    load_venue_policy,
    require_gate0_passed,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "crypto" / "bybit_spot_demo.yaml"


def _passing_capital_feasibility() -> CapitalFeasibility:
    fx_payload = {
        "base_currency": "MXN",
        "quote_currency": "USDT",
        "quote_per_base": 0.054,
        "captured_at_utc": "2026-08-12T11:00:00Z",
    }
    fx = FxEvidence(
        base_currency="MXN",
        quote_currency="USDT",
        quote_per_base=0.054,
        captured_at_utc="2026-08-12T11:00:00Z",
        source="offline test fixture",
        source_payload=fx_payload,
        raw_sha256=sha256_of_text(canonical_dumps(fx_payload)),
    )
    instruments: list[CapitalInstrumentEvidence] = []
    for index in range(1, 21):
        payload = {
            "venue": "bybit",
            "market": "spot",
            "environment": "demo",
            "account_scope": "dedicated_subaccount",
            "instrument_id": f"CMC:{index}",
            "venue_symbol": f"COIN{index}USDT",
            "base_currency": f"COIN{index}",
            "quote_currency": "USDT",
            "reference_ask_quote": 1.0,
            "tick_size_quote": 0.01,
            "quantity_step": 0.1,
            "min_notional_quote": 1.0,
            "taker_fee_bps": 10.0,
            "fee_currency": "USDT",
            "fee_charging_mode": "QUOTE_ON_TOP",
            "minimum_fee_amount": 0.0,
            "captured_at_utc": "2026-08-12T11:00:00Z",
        }
        instruments.append(
            CapitalInstrumentEvidence(
                instrument_id=f"CMC:{index}",
                venue_symbol=f"COIN{index}USDT",
                base_currency=f"COIN{index}",
                quote_currency="USDT",
                reference_ask_quote=1.0,
                tick_size_quote=0.01,
                quantity_step=0.1,
                min_notional_quote=1.0,
                taker_fee_bps=10.0,
                fee_currency="USDT",
                fee_charging_mode="QUOTE_ON_TOP",
                minimum_fee_amount=0.0,
                captured_at_utc="2026-08-12T11:00:00Z",
                source="offline test fixture",
                source_payload=payload,
                raw_sha256=sha256_of_text(canonical_dumps(payload)),
            )
        )
    quote_usd_payload = {
        "base_currency": "USDT",
        "quote_currency": "USD",
        "quote_per_base": 0.999,
        "captured_at_utc": "2026-08-12T11:00:00Z",
    }
    return evaluate_capital_feasibility(
        CapitalFeasibilityRequest(
            sleeve_amount=1_000.0,
            sleeve_currency="MXN",
            as_of_utc="2026-08-12T12:00:00Z",
            fx=fx,
            instruments=tuple(instruments),
            venue="bybit",
            market="spot",
            environment="demo",
            account_scope="dedicated_subaccount",
            quote_to_usd_fx=FxEvidence(
                base_currency="USDT",
                quote_currency="USD",
                quote_per_base=0.999,
                captured_at_utc="2026-08-12T11:00:00Z",
                source="offline test fixture",
                source_payload=quote_usd_payload,
                raw_sha256=sha256_of_text(canonical_dumps(quote_usd_payload)),
            ),
        )
    )


def _complete_gate0(**overrides: object) -> Gate0Evidence:
    values: dict[str, object] = {
        "venue": "bybit",
        "environment": "demo",
        "kyc_mexico_approved": True,
        "contractual_entity_identified": True,
        "spot_account_enabled": True,
        "api_access_enabled": True,
        "dedicated_subaccount_active": True,
        "ip_allowlist_active": True,
        "read_permission_enabled": True,
        "spot_permission_enabled": True,
        "withdrawal_permission_disabled": True,
        "transfer_permission_disabled": True,
        "margin_permission_disabled": True,
        "derivatives_permission_disabled": True,
        "loan_permission_disabled": True,
        "fee_rate_captured_per_symbol": True,
        "minimum_deposit_test_passed": True,
        "minimum_withdrawal_test_passed": True,
        "dataset_venue": "bybit",
        "cost_venue": "bybit",
        "planned_execution_venue": "bybit",
    }
    values.update(overrides)
    return Gate0Evidence(**values)  # type: ignore[arg-type]


def _complete_shadow(**overrides: object) -> ShadowEvidence:
    values: dict[str, object] = {
        "demo_completed_order_cycles": 100,
        "shadow_calendar_days": 365,
        "complete_annual_rebalances": 1,
        "unresolved_reconciliation_discrepancies": 0,
        "duplicate_orders": 0,
        "submit_cancel_cycle_passed": True,
        "idempotency_passed": True,
        "reconnection_passed": True,
        "rate_limit_handling_passed": True,
        "restart_recovery_passed": True,
        "reconciliation_passed": True,
        "kill_switch_drills_passed": True,
    }
    values.update(overrides)
    return ShadowEvidence(**values)  # type: ignore[arg-type]


def _complete_canary(**overrides: object) -> CanaryEvidence:
    values: dict[str, object] = {
        "shadow_passed": True,
        "own_capital_only": True,
        "spot_only": True,
        "leverage_disabled": True,
        "shorts_disabled": True,
        "human_approval_each_initial_rebalance": True,
        "post_rebalance_reconciliation_required": True,
        "venue_balance_operational_only": True,
        "capital_feasibility": _passing_capital_feasibility(),
        "minimum_order_constraints_allow_diversification": True,
        "risk_capital_usd": 4_000.0,
        "proposed_initial_capital_usd": 53.946,
        "configured_maximum_asset_fraction": 0.05,
        "configured_maximum_order_adv_fraction": 0.01,
        "configured_maximum_order_depth_fraction": 0.05,
        "configured_daily_loss_kill_fraction": 0.01,
        "configured_drawdown_pause_fraction": 0.05,
        "stale_data_pause_configured": True,
        "unexpected_fee_pause_configured": True,
        "abnormal_latency_pause_configured": True,
        "slippage_outside_model_pause_configured": True,
    }
    values.update(overrides)
    return CanaryEvidence(**values)  # type: ignore[arg-type]


def _complete_scale(**overrides: object) -> CanaryScaleEvidence:
    values: dict[str, object] = {
        "observed_fills": 100,
        "observed_calendar_days": 30,
        "p95_realized_to_simulated_slippage_ratio": 1.5,
        "median_cost_error_fraction": 0.2,
        "unresolved_reconciliation_discrepancies": 0,
        "duplicate_orders": 0,
        "proposed_scale_increment_fraction": 0.25,
        "daily_loss_kill_triggered": False,
        "drawdown_pause_triggered": False,
        "stale_data_detected": False,
        "unexpected_fee_detected": False,
        "abnormal_latency_detected": False,
        "slippage_outside_model_detected": False,
    }
    values.update(overrides)
    return CanaryScaleEvidence(**values)  # type: ignore[arg-type]


def test_shipped_venue_policy_is_locked_to_bybit_demo_spot() -> None:
    policy = load_venue_policy(POLICY_PATH)

    assert policy == VenuePolicy()
    assert policy.live_endpoint_enabled is False
    assert policy.credentials_in_repository is False
    assert policy.execution_adapter_enabled is False
    with pytest.raises(FrozenInstanceError):
        policy.venue = "binance"  # type: ignore[misc]


def test_policy_loader_rejects_unknown_endpoint_or_credential_fields(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text("venue: bybit\nbase_url: https://example.invalid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown venue policy keys.*base_url"):
        load_venue_policy(path)

    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        load_venue_policy(path)


def test_gate0_is_insufficient_when_evidence_is_absent() -> None:
    verdict = evaluate_gate0(VenuePolicy(), None)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "kyc_mexico_approved" in verdict.missing_conditions
    assert "dataset_venue" in verdict.missing_conditions
    assert verdict.to_dict()["real_money_authorized"] is False


def test_gate0_blocks_unsafe_policy_and_mixed_venue_evidence() -> None:
    policy = VenuePolicy(execution_adapter_enabled=True)
    evidence = _complete_gate0(
        withdrawal_permission_disabled=False,
        dataset_venue="binance",
        cost_venue="bybit",
    )

    verdict = evaluate_gate0(policy, evidence)

    assert verdict.status == "BLOCKED"
    assert any("execution_adapter_enabled" in item for item in verdict.blocking_conditions)
    assert any("withdrawal permission" in item for item in verdict.blocking_conditions)
    assert any("dataset_venue" in item for item in verdict.blocking_conditions)


def test_gate0_pass_only_removes_gate0_as_a_research_blocker() -> None:
    verdict = evaluate_gate0(VenuePolicy(), _complete_gate0())

    assert verdict.status == "PASS"
    assert verdict.passed is True
    require_gate0_passed(verdict, "pnl_generation")
    payload = verdict.to_dict()
    assert payload["downstream_gates_still_required"] is True
    assert payload["demo_order_submission_authorized"] is False
    assert payload["external_action_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert len(verdict.digest()) == 64
    assert verdict.digest() == evaluate_gate0(VenuePolicy(), _complete_gate0()).digest()
    assert payload["evidence"] == _complete_gate0().to_dict()
    assert payload["evidence_digest"] == verdict.evidence_digest()


def test_gate0_digest_binds_the_exact_evidence_not_only_the_status() -> None:
    first = evaluate_gate0(VenuePolicy(), _complete_gate0(contractual_entity_identified=False))
    second = evaluate_gate0(VenuePolicy(), _complete_gate0(ip_allowlist_active=False))

    assert first.status == second.status == "BLOCKED"
    assert first.evidence != second.evidence
    assert first.evidence_digest() != second.evidence_digest()
    assert first.digest() != second.digest()


def test_gate0_guard_raises_for_missing_or_blocked_evidence() -> None:
    verdict = evaluate_gate0(VenuePolicy(), Gate0Evidence())
    with pytest.raises(CryptoGateError, match="Gate 0 blocks holdout_seal"):
        require_gate0_passed(verdict, "holdout_seal")

    passed = evaluate_gate0(VenuePolicy(), _complete_gate0())
    with pytest.raises(CryptoGateError, match="unsupported action"):
        require_gate0_passed(passed, "live_order_submission")

    fabricated = Gate0Verdict(
        status="PASS",
        blocking_conditions=(),
        missing_conditions=(),
        policy=VenuePolicy(),
        evidence=Gate0Evidence(),
    )
    with pytest.raises(CryptoGateError, match="inconsistent with its policy and evidence"):
        require_gate0_passed(fabricated, "holdout_seal")


def test_shadow_requires_every_demo_drill_and_twelve_months() -> None:
    verdict = evaluate_shadow(ShadowPolicy(), _complete_shadow())

    assert verdict.status == "PASS"
    assert verdict.passed is True
    assert verdict.to_dict()["automatic_transition_authorized"] is False
    assert verdict.to_dict()["real_money_authorized"] is False


def test_shadow_fails_closed_on_missing_or_bad_evidence() -> None:
    missing = evaluate_shadow(ShadowPolicy(), ShadowEvidence())
    assert missing.status == "INSUFFICIENT_EVIDENCE"
    assert "demo_completed_order_cycles" in missing.missing_conditions

    failed = evaluate_shadow(
        ShadowPolicy(),
        _complete_shadow(
            demo_completed_order_cycles=99,
            shadow_calendar_days=True,
            duplicate_orders=1,
            restart_recovery_passed=False,
        ),
    )
    assert failed.status == "NO_GO"
    assert any("below required 100" in item for item in failed.blocking_conditions)
    assert any("non-negative integer" in item for item in failed.blocking_conditions)
    assert any("duplicate_orders" in item for item in failed.blocking_conditions)
    assert any("restart_recovery_passed" in item for item in failed.blocking_conditions)


def test_invalid_shadow_policy_is_no_go() -> None:
    verdict = evaluate_shadow(ShadowPolicy(minimum_demo_order_cycles=-1), _complete_shadow())
    assert verdict.status == "NO_GO"
    assert any("shadow policy" in item for item in verdict.blocking_conditions)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_demo_order_cycles", "100"),
        ("minimum_shadow_calendar_days", 365.0),
        ("maximum_unresolved_reconciliation_discrepancies", "0"),
        ("maximum_duplicate_orders", None),
    ],
)
def test_shadow_invalid_policy_types_return_no_go_without_type_error(
    field: str,
    value: object,
) -> None:
    policy = ShadowPolicy(**{field: value})  # type: ignore[arg-type]

    verdict = evaluate_shadow(policy, _complete_shadow())

    assert verdict.status == "NO_GO"
    assert any(field in item for item in verdict.blocking_conditions)


def test_shadow_hard_floors_cannot_be_relaxed_by_a_caller() -> None:
    relaxed = ShadowPolicy(
        minimum_demo_order_cycles=0,
        minimum_shadow_calendar_days=0,
        minimum_complete_annual_rebalances=0,
        maximum_unresolved_reconciliation_discrepancies=1,
        maximum_duplicate_orders=1,
    )
    verdict = evaluate_shadow(relaxed, _complete_shadow())

    assert verdict.status == "NO_GO"
    assert any("cannot be relaxed" in item for item in verdict.blocking_conditions)


def test_canary_sizing_helpers_only_calculate_limits() -> None:
    policy = CanaryPolicy()

    assert canary_capital_limit(policy, 4_000) == 400.0
    assert canary_capital_limit(policy, 10_000) == 500.0
    assert canary_order_limit(policy, 20_000, 2_000) == 100.0
    assert canary_order_limit(policy, 20_000, 500) == 25.0
    relaxed = CanaryPolicy(
        maximum_initial_capital_fraction=1.0,
        maximum_initial_capital_usd=50_000.0,
        maximum_order_adv_fraction=1.0,
        maximum_order_depth_fraction=1.0,
    )
    assert canary_capital_limit(relaxed, 10_000) == 500.0
    assert canary_order_limit(relaxed, 20_000, 2_000) == 100.0
    with pytest.raises(ValueError, match="risk_capital_usd"):
        canary_capital_limit(policy, True)
    with pytest.raises(ValueError, match="median_daily_notional_usd"):
        canary_order_limit(policy, -1, 100)
    with pytest.raises(ValueError, match="executable_depth_usd"):
        canary_order_limit(policy, 100, float("inf"))


def test_canary_readiness_pass_never_authorizes_money_or_actions() -> None:
    verdict = evaluate_canary_readiness(CanaryPolicy(), _complete_canary())

    assert verdict.status == "PASS"
    payload = verdict.to_dict()
    assert payload["gate"] == "CANARY_REVIEW"
    assert payload["automatic_transition_authorized"] is False
    assert payload["external_action_authorized"] is False
    assert payload["real_money_authorized"] is False


def test_canary_readiness_is_insufficient_without_positive_evidence() -> None:
    verdict = evaluate_canary_readiness(CanaryPolicy(), None)
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "shadow_passed" in verdict.missing_conditions
    assert "risk_capital_usd" in verdict.missing_conditions
    assert "capital_feasibility" in verdict.missing_conditions


def test_legacy_diversification_boolean_cannot_replace_calculated_feasibility() -> None:
    verdict = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(
            capital_feasibility=None,
            minimum_order_constraints_allow_diversification=True,
        ),
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "capital_feasibility" in verdict.missing_conditions


def test_tampered_or_no_go_capital_feasibility_blocks_canary_review() -> None:
    genuine = _passing_capital_feasibility()
    forged = replace(genuine, per_asset_cap_quote=999.0)
    tampered = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(capital_feasibility=forged),
    )
    no_go = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(
            capital_feasibility=evaluate_capital_feasibility(
                replace(genuine.request, instruments=genuine.request.instruments[:19])
            )
        ),
    )

    assert tampered.status == no_go.status == "NO_GO"
    assert any("recomputation" in item for item in tampered.blocking_conditions)
    assert any("capital_feasibility is NO_GO" in item for item in no_go.blocking_conditions)


def test_canary_binds_calculated_sleeve_to_exact_proposed_usd_capital() -> None:
    result = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(proposed_initial_capital_usd=5.3946),
    )

    assert result.status == "NO_GO"
    assert any("converted sleeve amount" in item for item in result.blocking_conditions)


def test_full_risk_capital_cannot_be_mislabeled_as_the_ten_percent_canary() -> None:
    # MXN 1,000 converts to USD 53.946 in the fixture.  At that declared risk
    # capital, the hard canary limit is only USD 5.3946, not the full sleeve.
    result = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(
            risk_capital_usd=53.946,
            proposed_initial_capital_usd=5.3946,
        ),
    )

    assert result.status == "NO_GO"
    assert any("converted sleeve amount" in item for item in result.blocking_conditions)


def test_canary_readiness_rejects_capital_and_risk_limit_violations() -> None:
    verdict = evaluate_canary_readiness(
        CanaryPolicy(),
        _complete_canary(
            shadow_passed=False,
            risk_capital_usd=5_000.0,
            proposed_initial_capital_usd=501.0,
            configured_maximum_asset_fraction=0.06,
            configured_daily_loss_kill_fraction="one percent",
        ),
    )

    assert verdict.status == "NO_GO"
    assert any("shadow_passed" in item for item in verdict.blocking_conditions)
    assert any("risk_capital_usd must remain below" in item for item in verdict.blocking_conditions)
    assert any("canary capital limit" in item for item in verdict.blocking_conditions)
    assert any("asset_fraction" in item for item in verdict.blocking_conditions)
    assert any("finite number" in item for item in verdict.blocking_conditions)


def test_invalid_canary_policy_is_no_go() -> None:
    policy = CanaryPolicy(
        maximum_asset_fraction=0.0,
        maximum_slippage_ratio=float("nan"),
        minimum_fills_before_scale=True,  # type: ignore[arg-type]
    )
    verdict = evaluate_canary_readiness(policy, _complete_canary())
    assert verdict.status == "NO_GO"
    assert len(verdict.blocking_conditions) >= 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_declared_risk_capital_usd", "5000"),
        ("maximum_asset_fraction", "0.05"),
        ("maximum_slippage_ratio", None),
        ("minimum_fills_before_scale", "100"),
        ("minimum_calendar_days_before_scale", 30.0),
    ],
)
def test_canary_invalid_policy_types_return_no_go_without_type_error(
    field: str,
    value: object,
) -> None:
    policy = CanaryPolicy(**{field: value})  # type: ignore[arg-type]

    readiness = evaluate_canary_readiness(policy, _complete_canary())
    scaling = evaluate_canary_scale(policy, _complete_scale())

    assert readiness.status == scaling.status == "NO_GO"
    assert any(field in item for item in readiness.blocking_conditions)
    assert any(field in item for item in scaling.blocking_conditions)


def test_canary_hard_floors_cannot_be_relaxed_by_a_caller() -> None:
    policy = CanaryPolicy(
        maximum_declared_risk_capital_usd=50_000.0,
        maximum_asset_fraction=0.50,
        minimum_fills_before_scale=1,
        minimum_calendar_days_before_scale=1,
        maximum_slippage_ratio=10.0,
    )

    readiness = evaluate_canary_readiness(policy, _complete_canary())
    scaling = evaluate_canary_scale(policy, _complete_scale())
    assert readiness.status == scaling.status == "NO_GO"
    assert any("cannot be relaxed" in item for item in readiness.blocking_conditions)
    assert any("cannot be relaxed" in item for item in scaling.blocking_conditions)


def test_canary_scale_requires_100_fills_30_days_and_clean_reconciliation() -> None:
    verdict = evaluate_canary_scale(CanaryPolicy(), _complete_scale())

    assert verdict.status == "PASS"
    assert verdict.to_dict()["automatic_transition_authorized"] is False
    assert verdict.policy["maximum_scale_increment_fraction"] == 0.25


def test_canary_scale_fails_closed_on_missing_or_out_of_policy_evidence() -> None:
    missing = evaluate_canary_scale(CanaryPolicy(), None)
    assert missing.status == "INSUFFICIENT_EVIDENCE"

    failed = evaluate_canary_scale(
        CanaryPolicy(),
        _complete_scale(
            observed_fills=99,
            observed_calendar_days=29,
            p95_realized_to_simulated_slippage_ratio=1.51,
            median_cost_error_fraction=0.21,
            unresolved_reconciliation_discrepancies=1,
            duplicate_orders=-1,
            proposed_scale_increment_fraction=0.26,
        ),
    )
    assert failed.status == "NO_GO"
    assert any("observed_fills" in item for item in failed.blocking_conditions)
    assert any("observed_calendar_days" in item for item in failed.blocking_conditions)
    assert any("slippage" in item for item in failed.blocking_conditions)
    assert any("median_cost_error" in item for item in failed.blocking_conditions)
    assert any("discrepancies" in item for item in failed.blocking_conditions)
    assert any("non-negative integer" in item for item in failed.blocking_conditions)
    assert any("scale_increment" in item for item in failed.blocking_conditions)


@pytest.mark.parametrize(
    "field",
    [
        "daily_loss_kill_triggered",
        "drawdown_pause_triggered",
        "stale_data_detected",
        "unexpected_fee_detected",
        "abnormal_latency_detected",
        "slippage_outside_model_detected",
    ],
)
def test_canary_scale_pauses_on_every_operational_trigger(field: str) -> None:
    verdict = evaluate_canary_scale(CanaryPolicy(), _complete_scale(**{field: True}))

    assert verdict.status == "NO_GO"
    assert any(field in item and "pause" in item for item in verdict.blocking_conditions)


def test_crypto_gate_module_has_no_connectivity_or_submission_surface() -> None:
    source = inspect.getsource(crypto_gates).lower()
    forbidden = (
        "/v5/",
        "api-demo.bybit",
        "requests.",
        "urllib.",
        "os.getenv",
        "submit_order",
        "sign_request",
    )
    assert not any(item in source for item in forbidden)
