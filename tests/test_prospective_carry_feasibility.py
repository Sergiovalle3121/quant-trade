"""Adversarial tests for the offline BTC carry feasibility contract."""

from __future__ import annotations

from dataclasses import replace

import pytest

from quant_trade.research.prospective_carry_feasibility import (
    REQUIRED_EVIDENCE_KINDS,
    CapitalIntent,
    CarryFeasibilityError,
    CarryFeasibilityStatus,
    CarryFeasibilitySubmission,
    CheckStatus,
    CommercialUseStatus,
    EvidenceArtifact,
    EvidenceAuthority,
    EvidenceKind,
    InstrumentPairAssessment,
    KYCStatus,
    OperationalStressAssessment,
    PointInTimeTerms,
    ReviewOutcome,
    VenueAccountAssessment,
    carry_feasibility_policy_sha256,
    evaluate_carry_feasibility,
    expected_evidence_scope,
)

DECISION = "2026-08-13T12:00:00Z"
REQUESTED = "2026-08-13T11:59:50Z"
RECEIVED = "2026-08-13T11:59:55Z"
SERVER = "2026-08-13T11:59:54Z"


def _authority(kind: EvidenceKind) -> EvidenceAuthority:
    if kind is EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY:
        return EvidenceAuthority.INDEPENDENT_MX_LEGAL_REVIEW
    if kind is EvidenceKind.MX_TAX_TREATMENT:
        return EvidenceAuthority.INDEPENDENT_MX_TAX_REVIEW
    if kind is EvidenceKind.COUNTERPARTY_RISK:
        return EvidenceAuthority.INDEPENDENT_COUNTERPARTY_REVIEW
    if kind is EvidenceKind.FX_USDT_USD:
        return EvidenceAuthority.PRIMARY_FX_REFERENCE
    if kind in {
        EvidenceKind.SPREAD_IMPACT_MODEL,
        EvidenceKind.TRANSFER_STRESS,
        EvidenceKind.WITHDRAWAL_STRESS,
    }:
        return EvidenceAuthority.OPERATOR_OFFLINE_STRESS
    return EvidenceAuthority.VENUE_PRIMARY


def _is_manual(kind: EvidenceKind) -> bool:
    return kind in {
        EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY,
        EvidenceKind.MX_TAX_TREATMENT,
        EvidenceKind.TRANSFER_STRESS,
        EvidenceKind.WITHDRAWAL_STRESS,
        EvidenceKind.COUNTERPARTY_RISK,
    }


def _is_dynamic(kind: EvidenceKind) -> bool:
    return kind not in {
        EvidenceKind.VENUE_TERMS,
        EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY,
        EvidenceKind.MX_TAX_TREATMENT,
        EvidenceKind.TRANSFER_STRESS,
        EvidenceKind.WITHDRAWAL_STRESS,
        EvidenceKind.COUNTERPARTY_RISK,
    }


def _source_locator(kind: EvidenceKind) -> str:
    authority = _authority(kind)
    if authority is EvidenceAuthority.VENUE_PRIMARY:
        if kind is EvidenceKind.VENUE_TERMS:
            return "https://www.bybit.com/common-static/compliance/legal/terms.pdf"
        return f"https://api.bybit.com/v5/offline-fixture/{kind.value.lower()}"
    if authority is EvidenceAuthority.PRIMARY_FX_REFERENCE:
        return "https://api.exchange.coinbase.com/products/USDT-USD/book"
    if authority is EvidenceAuthority.OPERATOR_OFFLINE_STRESS:
        return f"artifact://offline/{kind.value.lower()}"
    return f"review://independent/{kind.value.lower()}"


def _artifact(
    kind: EvidenceKind,
    *,
    response_received_at_utc: str = RECEIVED,
    request_started_at_utc: str = REQUESTED,
    request_side_cutoff_utc: str | None = DECISION,
    server_time_utc: str | None = SERVER,
    scope: str | None = None,
    source_locator: str | None = None,
    authority: EvidenceAuthority | None = None,
    commercial_use_status: CommercialUseStatus | None = None,
    suffix: bytes = b"",
) -> EvidenceArtifact:
    if not _is_dynamic(kind):
        request_side_cutoff_utc = None
        server_time_utc = None
    raw = b'{"fixture":"offline-only","kind":"' + kind.value.encode() + b'"}' + suffix
    return EvidenceArtifact.from_bytes(
        kind=kind,
        scope=scope or expected_evidence_scope(kind),
        source_locator=source_locator or _source_locator(kind),
        authority=authority or _authority(kind),
        commercial_use_status=(
            commercial_use_status
            or (
                CommercialUseStatus.NOT_APPLICABLE_REVIEWED
                if _is_manual(kind)
                else CommercialUseStatus.PERMITTED
            )
        ),
        request_started_at_utc=request_started_at_utc,
        response_received_at_utc=response_received_at_utc,
        source_published_at_utc="2026-08-13T00:00:00Z",
        source_effective_at_utc="2026-08-13T00:00:00Z",
        request_side_cutoff_utc=request_side_cutoff_utc,
        server_time_utc=server_time_utc,
        capture_tool_version="offline-fixture/1",
        reviewer_attestation_id=f"review-{kind.value.lower()}",
        raw_bytes=raw,
        transport_receipt_bytes=b"tls-and-request-metadata:" + kind.value.encode() + suffix,
        reviewer_attestation_bytes=b"independent-review:" + kind.value.encode() + suffix,
    )


def _artifacts() -> tuple[EvidenceArtifact, ...]:
    return tuple(_artifact(kind) for kind in REQUIRED_EVIDENCE_KINDS)


def _account() -> VenueAccountAssessment:
    return VenueAccountAssessment(
        venue="bybit",
        user_country_code="MX",
        contracting_legal_entity="reviewed entity from accepted account terms",
        country_product_review=ReviewOutcome.ACCEPTABLE_FOR_COLLECTION,
        kyc_status=KYCStatus.APPROVED,
        spot_enabled=True,
        linear_perpetual_enabled=True,
        isolated_margin_available=True,
        api_read_only=True,
        api_trade_permission=False,
        api_withdraw_permission=False,
        api_transfer_permission=False,
    )


def _pair() -> InstrumentPairAssessment:
    return InstrumentPairAssessment(
        venue="bybit",
        spot_symbol="BTCUSDT",
        spot_product="spot",
        spot_base_asset="BTC",
        spot_quote_asset="USDT",
        spot_status="TRADING",
        perp_symbol="BTCUSDT",
        perp_product="linear",
        perp_contract_type="linear_perpetual",
        perp_base_asset="BTC",
        perp_quote_asset="USDT",
        perp_settlement_asset="USDT",
        perp_status="TRADING",
        perp_is_prelisting=False,
        funding_interval_minutes=480,
    )


def _terms() -> PointInTimeTerms:
    return PointInTimeTerms(
        observed_at_utc=RECEIVED,
        quote_usdt_per_usd="1",
        spot_mid_usdt_per_btc="100000",
        perp_mark_usdt_per_btc="100000",
        perp_index_usdt_per_btc="100000",
        spot_qty_step_btc="0.000001",
        perp_qty_step_btc="0.000001",
        spot_min_notional_usdt="5",
        perp_min_notional_usdt="5",
        spot_executable_depth_usdt="500",
        perp_executable_depth_usdt="500",
        spot_account_fee_rate="0.001",
        perp_account_fee_rate="0.0006",
        spot_p95_exit_friction_rate="0.002",
        perp_p95_exit_friction_rate="0.002",
        liquidation_distance_fraction="0.75",
        settled_funding_rows_observed=1,
        basis_snapshots_observed=1,
        borrow_balance_usdt="0",
    )


def _operations() -> OperationalStressAssessment:
    return OperationalStressAssessment(
        transfer_path_stress=CheckStatus.PASS,
        withdrawal_path_stress=CheckStatus.PASS,
        withdrawal_freeze_runbook=CheckStatus.PASS,
        emergency_close_without_transfer=CheckStatus.PASS,
        tax_review=CheckStatus.PASS,
        counterparty_review=ReviewOutcome.ACCEPTABLE_FOR_COLLECTION,
        maximum_venue_balance_usd="200",
        full_custody_loss_scenario_acknowledged=True,
    )


def _submission(**changes: object) -> CarryFeasibilitySubmission:
    values: dict[str, object] = {
        "decision_at_utc": DECISION,
        "capital": CapitalIntent(),
        "venue_account": _account(),
        "instrument_pair": _pair(),
        "point_in_time_terms": _terms(),
        "operations": _operations(),
        "evidence_artifacts": _artifacts(),
    }
    values.update(changes)
    return CarryFeasibilitySubmission(**values)  # type: ignore[arg-type]


def _codes(verdict: object) -> set[str]:
    assert hasattr(verdict, "blockers")
    return {row.code for row in verdict.blockers}  # type: ignore[attr-defined]


def test_complete_self_asserted_pack_remains_insufficient_in_schema_v1() -> None:
    verdict = evaluate_carry_feasibility(_submission())

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert _codes(verdict) == {
        "EXTERNAL_ATTESTATION_TRUST_ROOT_NOT_IMPLEMENTED",
        "EVIDENCE_CONTENT_BINDING_PARSERS_NOT_IMPLEMENTED",
        "ACCOUNT_MANUAL_REVIEW_AUTHENTICITY_NOT_IMPLEMENTED",
    }
    assert verdict.capital.capital_only_matched_notional_usd_per_leg == "80"
    assert verdict.capital.matched_quantity_btc == "0.0008"
    assert verdict.capital.spot_notional_usdt == "80"
    assert verdict.capital.perp_notional_usdt == "80"
    assert verdict.capital.perp_initial_margin_usdt == "80"
    assert verdict.capital.remaining_contingency_usdt == "40"
    assert verdict.experiment_spec_authorized is False
    assert verdict.pnl_evaluation_authorized is False
    assert verdict.holdout_access_authorized is False
    assert verdict.promotion_authorized is False
    assert verdict.network_access_authorized is False
    assert verdict.derivatives_execution_authorized is False
    assert verdict.real_money_authorized is False
    assert verdict.money_movement_authorized is False
    assert verdict.profitability_evidence is False
    assert "expected_profit" not in verdict.to_dict()
    assert "return" not in verdict.to_dict()


def test_arbitrary_self_hashed_reviewer_bytes_cannot_clear_v1() -> None:
    arbitrary = tuple(
        _artifact(kind, suffix=f"caller-invented-{kind.value}".encode())
        for kind in REQUIRED_EVIDENCE_KINDS
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=arbitrary))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "EXTERNAL_ATTESTATION_TRUST_ROOT_NOT_IMPLEMENTED" in _codes(verdict)
    assert "ACCOUNT_MANUAL_REVIEW_AUTHENTICITY_NOT_IMPLEMENTED" in _codes(verdict)


def test_changed_typed_terms_with_same_receipts_cannot_clear_v1() -> None:
    receipts = _artifacts()
    before = evaluate_carry_feasibility(_submission(evidence_artifacts=receipts))
    changed = replace(
        _terms(),
        spot_mid_usdt_per_btc="99000",
        perp_mark_usdt_per_btc="99000",
        perp_index_usdt_per_btc="99000",
    )
    after = evaluate_carry_feasibility(
        _submission(evidence_artifacts=receipts, point_in_time_terms=changed)
    )

    assert before.status is CarryFeasibilityStatus.INSUFFICIENT
    assert after.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "EVIDENCE_CONTENT_BINDING_PARSERS_NOT_IMPLEMENTED" in _codes(after)
    assert before.selected_evidence_sha256 != after.selected_evidence_sha256


def test_direct_positive_verdict_construction_is_rejected_in_schema_v1() -> None:
    insufficient = evaluate_carry_feasibility(_submission())

    with pytest.raises(CarryFeasibilityError, match="schema v1 cannot emit"):
        replace(
            insufficient,
            status=CarryFeasibilityStatus.FEASIBLE_FOR_DEVELOPMENT_COLLECTION,
            blockers=(),
        )


def test_verdict_status_severity_and_frozen_identity_are_enforced() -> None:
    insufficient = evaluate_carry_feasibility(_submission())
    no_go = evaluate_carry_feasibility(
        _submission(capital=replace(CapitalIntent(), perp_leverage="1.01"))
    )

    with pytest.raises(CarryFeasibilityError, match="NO_GO requires"):
        replace(insufficient, status=CarryFeasibilityStatus.NO_GO)
    with pytest.raises(CarryFeasibilityError, match="INSUFFICIENT cannot"):
        replace(no_go, status=CarryFeasibilityStatus.INSUFFICIENT)
    with pytest.raises(CarryFeasibilityError, match="venue/country"):
        replace(insufficient, venue="arbitrary")
    with pytest.raises(CarryFeasibilityError, match="schema_version"):
        replace(insufficient, schema_version=2)
    with pytest.raises(CarryFeasibilityError, match="CapitalEnvelope"):
        replace(insufficient, capital="not-an-envelope")  # type: ignore[arg-type]


def test_submission_rejects_untyped_nested_assessments() -> None:
    with pytest.raises(CarryFeasibilityError, match="venue_account must"):
        CarryFeasibilitySubmission(
            decision_at_utc=DECISION,
            venue_account={"venue": "bybit"},  # type: ignore[arg-type]
        )


def test_no_evidence_is_insufficient_but_200_dollar_capital_ceiling_is_explicit() -> None:
    verdict = evaluate_carry_feasibility(CarryFeasibilitySubmission(decision_at_utc=DECISION))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert verdict.capital.capital_only_matched_notional_usd_per_leg == "80"
    assert verdict.capital.matched_quantity_btc is None
    assert "VENUE_ACCOUNT_ASSESSMENT_MISSING" in _codes(verdict)
    assert "POINT_IN_TIME_TERMS_MISSING" in _codes(verdict)
    assert "MISSING_EVIDENCE_MX_TAX_TREATMENT" in _codes(verdict)


def test_policy_and_report_are_deterministic_under_artifact_reordering() -> None:
    first = evaluate_carry_feasibility(_submission())
    second = evaluate_carry_feasibility(
        _submission(evidence_artifacts=tuple(reversed(_artifacts())))
    )

    assert carry_feasibility_policy_sha256() == first.policy_sha256
    assert first.to_dict() == second.to_dict()
    assert first.report_sha256() == second.report_sha256()


def test_appending_future_capture_changes_no_past_verdict_byte() -> None:
    before = evaluate_carry_feasibility(_submission())
    future = _artifact(
        EvidenceKind.ACCOUNT_FEE_SPOT,
        request_started_at_utc="2026-08-14T00:00:00Z",
        response_received_at_utc="2026-08-14T00:00:05Z",
        request_side_cutoff_utc="2026-08-14T00:00:10Z",
        server_time_utc="2026-08-14T00:00:04Z",
        suffix=b"future-revision",
    )
    after = evaluate_carry_feasibility(_submission(evidence_artifacts=(*_artifacts(), future)))

    assert before.to_dict() == after.to_dict()
    assert before.report_sha256() == after.report_sha256()


def test_missing_one_required_receipt_is_insufficient_not_feasible() -> None:
    artifacts = tuple(
        row for row in _artifacts() if row.receipt.kind is not EvidenceKind.MX_TAX_TREATMENT
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "MISSING_EVIDENCE_MX_TAX_TREATMENT" in _codes(verdict)


@pytest.mark.parametrize(
    "status",
    [CommercialUseStatus.PROHIBITED, CommercialUseStatus.RESEARCH_ONLY],
)
def test_noncommercial_market_bytes_are_no_go(status: CommercialUseStatus) -> None:
    replacement = _artifact(
        EvidenceKind.FUNDING_HISTORY_SCHEMA,
        commercial_use_status=status,
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert "COMMERCIAL_USE_NOT_PERMITTED" in _codes(verdict)


def test_dynamic_data_cannot_claim_license_not_applicable() -> None:
    replacement = _artifact(
        EvidenceKind.PERP_ORDER_BOOK,
        commercial_use_status=CommercialUseStatus.NOT_APPLICABLE_REVIEWED,
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "DATA_LICENSE_NOT_CONFIRMED" in _codes(verdict)


def test_wrong_scope_is_no_go_and_cannot_satisfy_exact_identity_receipt() -> None:
    replacement = _artifact(EvidenceKind.PERP_INSTRUMENT, scope="bybit:linear:ETHUSDT")
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert "EVIDENCE_SCOPE_MISMATCH" in _codes(verdict)
    assert "MISSING_EVIDENCE_PERP_INSTRUMENT" in _codes(verdict)


def test_wrong_authority_is_insufficient() -> None:
    replacement = _artifact(
        EvidenceKind.MX_TAX_TREATMENT,
        authority=EvidenceAuthority.VENUE_PRIMARY,
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "EVIDENCE_AUTHORITY_NOT_ACCEPTED" in _codes(verdict)


def test_authority_label_cannot_make_an_arbitrary_host_primary() -> None:
    replacement = _artifact(
        EvidenceKind.ACCOUNT_FEE_SPOT,
        source_locator="https://attacker.invalid/fees",
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "EVIDENCE_SOURCE_LOCATOR_NOT_ACCEPTED" in _codes(verdict)


def test_request_side_cutoff_before_decision_is_insufficient() -> None:
    replacement = _artifact(
        EvidenceKind.FUNDING_HISTORY_SCHEMA,
        request_side_cutoff_utc="2026-08-13T11:59:59Z",
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "REQUEST_SIDE_CUTOFF_NOT_DECISION" in _codes(verdict)


def test_request_after_response_is_no_go() -> None:
    replacement = _artifact(
        EvidenceKind.ACCOUNT_FEE_PERP,
        request_started_at_utc="2026-08-13T11:59:56Z",
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert "RECEIPT_REQUEST_AFTER_RESPONSE" in _codes(verdict)


def test_request_side_cutoff_after_decision_is_no_go() -> None:
    replacement = _artifact(
        EvidenceKind.FUNDING_HISTORY_SCHEMA,
        request_side_cutoff_utc="2026-08-13T12:00:01Z",
    )
    artifacts = tuple(
        replacement if row.receipt.kind is replacement.receipt.kind else row for row in _artifacts()
    )
    verdict = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))

    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert "REQUEST_SIDE_CUTOFF_AFTER_DECISION" in _codes(verdict)


def test_missing_server_time_and_large_clock_skew_are_insufficient() -> None:
    missing = _artifact(EvidenceKind.SPOT_INSTRUMENT, server_time_utc=None)
    artifacts = tuple(
        missing if row.receipt.kind is missing.receipt.kind else row for row in _artifacts()
    )
    first = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))
    assert first.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "VENUE_SERVER_TIME_MISSING" in _codes(first)

    skewed = _artifact(
        EvidenceKind.SPOT_INSTRUMENT,
        server_time_utc="2026-08-13T11:00:00Z",
    )
    artifacts = tuple(
        skewed if row.receipt.kind is skewed.receipt.kind else row for row in _artifacts()
    )
    second = evaluate_carry_feasibility(_submission(evidence_artifacts=artifacts))
    assert second.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "VENUE_SERVER_CLOCK_SKEW" in _codes(second)


def test_conflicting_receipts_at_same_capture_time_are_no_go() -> None:
    first = _artifact(EvidenceKind.FX_USDT_USD, suffix=b"a")
    second = _artifact(EvidenceKind.FX_USDT_USD, suffix=b"b")
    artifacts = tuple(
        row for row in _artifacts() if row.receipt.kind is not EvidenceKind.FX_USDT_USD
    )
    verdict = evaluate_carry_feasibility(
        _submission(evidence_artifacts=(*artifacts, first, second))
    )

    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert "CONFLICTING_RECEIPTS_AT_SAME_TIME" in _codes(verdict)


def test_artifact_rejects_tampered_raw_transport_or_attestation_bytes() -> None:
    original = _artifact(EvidenceKind.VENUE_TERMS)
    with pytest.raises(CarryFeasibilityError, match="raw bytes digest"):
        replace(original, raw_bytes=b"x" * len(original.raw_bytes))
    with pytest.raises(CarryFeasibilityError, match="transport receipt digest"):
        replace(original, transport_receipt_bytes=b"tampered")
    with pytest.raises(CarryFeasibilityError, match="reviewer attestation digest"):
        replace(original, reviewer_attestation_bytes=b"tampered")


@pytest.mark.parametrize(
    ("account", "code"),
    [
        (replace(_account(), kyc_status=KYCStatus.REJECTED), "KYC_REJECTED"),
        (
            replace(_account(), country_product_review=ReviewOutcome.REJECTED),
            "DERIVATIVES_NOT_LEGALLY_AVAILABLE",
        ),
        (replace(_account(), linear_perpetual_enabled=False), "PERP_PRODUCT_DISABLED"),
        (replace(_account(), api_trade_permission=True), "API_TRADE_PERMISSION_MUST_BE_DISABLED"),
        (
            replace(_account(), api_withdraw_permission=True),
            "API_WITHDRAW_PERMISSION_MUST_BE_DISABLED",
        ),
        (
            replace(_account(), api_transfer_permission=True),
            "API_TRANSFER_PERMISSION_MUST_BE_DISABLED",
        ),
    ],
)
def test_account_or_legal_contradictions_are_no_go(
    account: VenueAccountAssessment,
    code: str,
) -> None:
    verdict = evaluate_carry_feasibility(_submission(venue_account=account))
    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert code in _codes(verdict)


def test_unknown_legal_or_kyc_state_is_insufficient() -> None:
    account = replace(
        _account(),
        country_product_review=ReviewOutcome.UNKNOWN,
        kyc_status=KYCStatus.UNKNOWN,
    )
    verdict = evaluate_carry_feasibility(_submission(venue_account=account))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "LEGAL_PRODUCT_REVIEW_UNKNOWN" in _codes(verdict)
    assert "KYC_NOT_CONFIRMED" in _codes(verdict)


@pytest.mark.parametrize(
    "pair",
    [
        replace(_pair(), spot_base_asset="ETH"),
        replace(_pair(), perp_quote_asset="USDC"),
        replace(_pair(), perp_settlement_asset="BTC"),
        replace(_pair(), perp_product="inverse"),
        replace(_pair(), perp_is_prelisting=True),
    ],
)
def test_inexact_or_prelisting_instruments_are_no_go(pair: InstrumentPairAssessment) -> None:
    verdict = evaluate_carry_feasibility(_submission(instrument_pair=pair))
    assert verdict.status is CarryFeasibilityStatus.NO_GO


@pytest.mark.parametrize(
    ("capital", "code"),
    [
        (replace(CapitalIntent(), perp_leverage="1.01"), "PERP_LEVERAGE_ABOVE_1X"),
        (replace(CapitalIntent(), borrow_used=True), "BORROWED_OR_UNFUNDED_SPOT_FORBIDDEN"),
        (
            replace(CapitalIntent(), spot_fully_funded=False),
            "BORROWED_OR_UNFUNDED_SPOT_FORBIDDEN",
        ),
        (replace(CapitalIntent(), margin_mode="CROSS"), "ISOLATED_MARGIN_REQUIRED"),
        (
            replace(CapitalIntent(), liquidity_reserve_fraction="0.19"),
            "LIQUIDITY_RESERVE_BELOW_POLICY",
        ),
        (replace(CapitalIntent(), budget_usd="201"), "BUDGET_DIFFERS_FROM_200_USD_POLICY"),
    ],
)
def test_capital_policy_violations_are_no_go(capital: CapitalIntent, code: str) -> None:
    verdict = evaluate_carry_feasibility(_submission(capital=capital))
    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert code in _codes(verdict)


@pytest.mark.parametrize(
    ("terms", "code"),
    [
        (
            replace(_terms(), spot_min_notional_usdt="100"),
            "BUDGET_BELOW_VENUE_MINIMUMS",
        ),
        (
            replace(_terms(), spot_qty_step_btc="0.01"),
            "BUDGET_CANNOT_PLACE_COMMON_QUANTITY_STEP",
        ),
        (
            replace(_terms(), liquidation_distance_fraction="0.49"),
            "LIQUIDATION_BUFFER_BELOW_POLICY",
        ),
        (replace(_terms(), quote_usdt_per_usd="0.94"), "USDT_USD_OUTSIDE_POLICY_BAND"),
        (replace(_terms(), borrow_balance_usdt="0.01"), "NONZERO_BORROW_BALANCE"),
        (
            replace(_terms(), spot_executable_depth_usdt="159"),
            "SPOT_DEPTH_BELOW_2X_NOTIONAL",
        ),
    ],
)
def test_technical_infeasibility_is_no_go(terms: PointInTimeTerms, code: str) -> None:
    verdict = evaluate_carry_feasibility(_submission(point_in_time_terms=terms))
    assert verdict.status is CarryFeasibilityStatus.NO_GO
    assert code in _codes(verdict)


def test_stale_or_incompatible_point_in_time_market_evidence_is_insufficient() -> None:
    stale = replace(_terms(), observed_at_utc="2026-08-13T11:00:00Z")
    first = evaluate_carry_feasibility(_submission(point_in_time_terms=stale))
    assert first.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "POINT_IN_TIME_TERMS_STALE" in _codes(first)

    incompatible = replace(_terms(), perp_mark_usdt_per_btc="120000")
    second = evaluate_carry_feasibility(_submission(point_in_time_terms=incompatible))
    assert second.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "PRICE_IDENTITY_OR_STALENESS_UNRESOLVED" in _codes(second)


def test_missing_funding_or_basis_schema_is_insufficient() -> None:
    terms = replace(
        _terms(),
        settled_funding_rows_observed=0,
        basis_snapshots_observed=0,
    )
    verdict = evaluate_carry_feasibility(_submission(point_in_time_terms=terms))

    assert verdict.status is CarryFeasibilityStatus.INSUFFICIENT
    assert "SETTLED_FUNDING_SCHEMA_NOT_OBSERVED" in _codes(verdict)
    assert "BASIS_SCHEMA_NOT_OBSERVED" in _codes(verdict)


@pytest.mark.parametrize(
    ("operations", "code", "expected"),
    [
        (
            replace(_operations(), transfer_path_stress=CheckStatus.NOT_RUN),
            "TRANSFER_PATH_STRESS_NOT_RUN",
            CarryFeasibilityStatus.INSUFFICIENT,
        ),
        (
            replace(_operations(), withdrawal_path_stress=CheckStatus.FAIL),
            "WITHDRAWAL_PATH_STRESS_FAILED",
            CarryFeasibilityStatus.NO_GO,
        ),
        (
            replace(_operations(), emergency_close_without_transfer=CheckStatus.FAIL),
            "EMERGENCY_CLOSE_WITHOUT_TRANSFER_FAILED",
            CarryFeasibilityStatus.NO_GO,
        ),
        (
            replace(_operations(), tax_review=CheckStatus.NOT_RUN),
            "MX_TAX_REVIEW_NOT_RUN",
            CarryFeasibilityStatus.INSUFFICIENT,
        ),
        (
            replace(_operations(), counterparty_review=ReviewOutcome.REJECTED),
            "COUNTERPARTY_REVIEW_REJECTED",
            CarryFeasibilityStatus.NO_GO,
        ),
        (
            replace(_operations(), maximum_venue_balance_usd="201"),
            "MAXIMUM_VENUE_BALANCE_EXCEEDS_POLICY",
            CarryFeasibilityStatus.NO_GO,
        ),
    ],
)
def test_operational_tax_and_counterparty_gates(
    operations: OperationalStressAssessment,
    code: str,
    expected: CarryFeasibilityStatus,
) -> None:
    verdict = evaluate_carry_feasibility(_submission(operations=operations))
    assert verdict.status is expected
    assert code in _codes(verdict)


def test_non_iso_timestamp_fails_closed_before_any_evaluation() -> None:
    with pytest.raises(CarryFeasibilityError, match="ending in Z"):
        CarryFeasibilitySubmission(decision_at_utc="2026-08-13T12:00:00")
