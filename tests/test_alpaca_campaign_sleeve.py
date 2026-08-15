from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from quant_trade.execution.alpaca_campaign_sleeve import (
    USD_200,
    AlpacaAssetEvidence,
    AlpacaCampaignSleeveError,
    PaperOrderOutcome,
    PaperPlanConsumptionLedger,
    PaperPlannedOrder,
    SealedPaperPlan,
    SleeveOpenOrder,
    SleevePolicy,
    SleevePosition,
    SleeveSnapshot,
    load_sealed_paper_plan,
    plan_json,
    preflight_paper_plan,
    seal_paper_plan,
)

CREATED = "2026-08-14T15:00:00Z"
EVALUATED = "2026-08-14T15:00:10Z"
EXPIRES = "2026-08-14T15:05:00Z"


def _policy(**changes: object) -> SleevePolicy:
    values: dict[str, object] = {"campaign_id": "SPY_TOM_Dm1_P3_v1"}
    values.update(changes)
    return SleevePolicy(**values)  # type: ignore[arg-type]


def _snapshot(**changes: object) -> SleeveSnapshot:
    values: dict[str, object] = {
        "campaign_id": "SPY_TOM_Dm1_P3_v1",
        "captured_at_utc": "2026-08-14T14:59:30Z",
        "trading_date": "2026-08-14",
        "cash": Decimal("200"),
    }
    values.update(changes)
    return SleeveSnapshot(**values)  # type: ignore[arg-type]


def _evidence(
    *,
    symbol: str = "SPY",
    price: str = "650",
    quote_at: str = "2026-08-14T14:59:40Z",
    tradable: bool = True,
    fractionable: bool = True,
) -> AlpacaAssetEvidence:
    return AlpacaAssetEvidence(
        symbol=symbol,
        quote_price=Decimal(price),
        quote_at_utc=quote_at,
        tradable=tradable,
        fractionable=fractionable,
    )


def _buy(
    *,
    client_order_id: str = "tom-20260814-entry",
    symbol: str = "SPY",
    quantity: str = "0.3",
    price: str = "650",
) -> PaperPlannedOrder:
    return PaperPlannedOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side="buy",
        quantity=Decimal(quantity),
        limit_price=Decimal(price),
    )


def _sell(
    *,
    client_order_id: str = "tom-20260814-exit",
    symbol: str = "SPY",
    quantity: str = "0.3",
    price: str = "650",
) -> PaperPlannedOrder:
    return PaperPlannedOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side="sell",
        quantity=Decimal(quantity),
        limit_price=Decimal(price),
    )


def _plan(
    *,
    policy: SleevePolicy | None = None,
    snapshot: SleeveSnapshot | None = None,
    evidence: tuple[AlpacaAssetEvidence, ...] | None = None,
    orders: tuple[PaperPlannedOrder, ...] | None = None,
    created_at_utc: str = CREATED,
    expires_at_utc: str = EXPIRES,
):
    actual_policy = policy or _policy()
    actual_snapshot = snapshot or _snapshot()
    actual_evidence = evidence or (_evidence(),)
    actual_orders = orders or (_buy(),)
    plan = seal_paper_plan(
        actual_policy,
        actual_snapshot,
        actual_evidence,
        actual_orders,
        created_at_utc=created_at_utc,
        expires_at_utc=expires_at_utc,
    )
    return plan, actual_policy, actual_snapshot, actual_evidence


def _consume(tmp_path: Path):
    plan, policy, snapshot, evidence = _plan()
    ledger = PaperPlanConsumptionLedger(tmp_path)
    decision = ledger.consume_once(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )
    assert decision.should_submit is True
    return ledger, plan, policy, snapshot, evidence


def test_usd_200_preflight_projects_portfolio_and_preserves_fee_reserve() -> None:
    plan, policy, snapshot, evidence = _plan()
    result = preflight_paper_plan(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )

    assert policy.initial_cash == USD_200
    assert plan.initial_cash == USD_200
    assert result.passed is True
    assert result.paper_only is True
    assert result.real_money_enabled is False
    assert result.conservative_cash_after_buys == Decimal("5")
    assert result.worst_case_gross_notional == Decimal("195.0")
    assert result.total_orders_today_after_plan == 1
    assert result.projected_positions[0].symbol == "SPY"
    assert result.projected_positions[0].quantity == Decimal("0.3")


def test_open_orders_are_projected_but_must_reconcile_before_consumption(
    tmp_path: Path,
) -> None:
    existing = SleeveOpenOrder(
        client_order_id="existing-paper-order",
        symbol="TEST",
        side="buy",
        remaining_quantity=Decimal("5"),
        limit_price=Decimal("10"),
    )
    snapshot = _snapshot(
        cash=Decimal("200"),
        open_orders=(existing,),
        orders_submitted_today=1,
    )
    evidence = (_evidence(symbol="TEST", price="10"),)
    orders = (_buy(client_order_id="new-paper-order", symbol="TEST", quantity="14.5", price="10"),)
    plan, policy, snapshot, evidence = _plan(
        snapshot=snapshot,
        evidence=evidence,
        orders=orders,
    )

    result = preflight_paper_plan(plan, policy, snapshot, evidence, evaluated_at_utc=EVALUATED)
    assert result.conservative_cash_after_buys == Decimal("5.0")
    assert result.worst_case_gross_notional == Decimal("195.0")
    assert result.projected_positions[0].quantity == Decimal("19.5")
    assert result.total_orders_today_after_plan == 2
    refused = PaperPlanConsumptionLedger(tmp_path).consume_once(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )
    assert refused.should_submit is False
    assert refused.state == "REFUSED_OPEN_ORDERS"


@pytest.mark.parametrize(
    ("evidence", "match"),
    [
        ((_evidence(quote_at="2026-08-14T14:58:00Z"),), "stale"),
        ((_evidence(tradable=False),), "not proven tradable"),
        ((_evidence(fractionable=False),), "not proven fractionable"),
    ],
)
def test_stale_or_ineligible_asset_evidence_blocks_plan(
    evidence: tuple[AlpacaAssetEvidence, ...], match: str
) -> None:
    with pytest.raises(AlpacaCampaignSleeveError, match=match):
        _plan(evidence=evidence)


@pytest.mark.parametrize(
    ("order", "match"),
    [
        (_buy(quantity="0.301"), "fee reserve|gross exposure"),
        (
            _buy(quantity="195", price="1"),
            "gross exposure",
        ),
        (_buy(quantity="0.1234567891"), "quantity precision"),
        (_buy(price="650.001"), "limit_price precision"),
        (_buy(quantity="0.001", price="1"), "below the USD 1 minimum"),
        (
            PaperPlannedOrder(
                client_order_id="market-is-unbounded",
                symbol="SPY",
                side="buy",
                quantity=Decimal("0.3"),
                limit_price=Decimal("650"),
                order_type="market",
            ),
            "bounded limit",
        ),
    ],
)
def test_unfunded_or_unbounded_orders_fail_closed(order: PaperPlannedOrder, match: str) -> None:
    with pytest.raises(AlpacaCampaignSleeveError, match=match):
        _plan(orders=(order,))


def test_cumulative_open_and_planned_sells_cannot_create_a_short() -> None:
    snapshot = _snapshot(
        cash=Decimal("100"),
        positions=(SleevePosition("SPY", Decimal("1")),),
        open_orders=(
            SleeveOpenOrder(
                "already-selling",
                "SPY",
                "sell",
                Decimal("0.6"),
                Decimal("100"),
            ),
        ),
        orders_submitted_today=1,
    )
    sell = PaperPlannedOrder(
        client_order_id="would-be-short",
        symbol="SPY",
        side="sell",
        quantity=Decimal("0.5"),
        limit_price=Decimal("100"),
    )
    with pytest.raises(AlpacaCampaignSleeveError, match="exceeds the sleeve position"):
        _plan(snapshot=snapshot, evidence=(_evidence(price="100"),), orders=(sell,))


def test_daily_order_limit_includes_prior_submissions() -> None:
    snapshot = _snapshot(orders_submitted_today=2)
    with pytest.raises(AlpacaCampaignSleeveError, match="daily paper order count"):
        _plan(snapshot=snapshot)


@pytest.mark.parametrize(
    "policy",
    [
        _policy(initial_cash=Decimal("201")),
        _policy(real_money_enabled=True),
        _policy(allow_leverage=True),
        _policy(allow_short=True),
        _policy(fee_reserve=Decimal("4.99")),
        _policy(max_gross_notional=Decimal("196"), fee_reserve=Decimal("5")),
        _policy(max_orders_per_day=3),
        _policy(max_quote_age_seconds=61),
        _policy(max_snapshot_age_seconds=61),
        _policy(max_plan_ttl_seconds=301),
    ],
)
def test_policy_cannot_enable_more_money_or_live_risk(policy: SleevePolicy) -> None:
    with pytest.raises(AlpacaCampaignSleeveError):
        _plan(policy=policy)


def test_plan_is_factory_only_frozen_and_detects_serialized_tamper() -> None:
    plan, _, _, _ = _plan()
    with pytest.raises(FrozenInstanceError):
        plan.campaign_id = "changed"  # type: ignore[misc]
    assert not hasattr(plan, "_construction_token")
    with pytest.raises((TypeError, ValueError), match="InitVar.*must be specified"):
        replace(plan, campaign_id="changed")
    with pytest.raises(AlpacaCampaignSleeveError, match="cannot be constructed directly"):
        SealedPaperPlan(
            campaign_id=plan.campaign_id,
            initial_cash=plan.initial_cash,
            policy_sha256=plan.policy_sha256,
            snapshot_sha256=plan.snapshot_sha256,
            state_claim_sha256=plan.state_claim_sha256,
            asset_evidence_sha256=plan.asset_evidence_sha256,
            trading_date=plan.trading_date,
            orders_submitted_before=plan.orders_submitted_before,
            planned_order_count=plan.planned_order_count,
            orders=plan.orders,
            created_at_utc=plan.created_at_utc,
            expires_at_utc=plan.expires_at_utc,
            paper_only=True,
            real_money_enabled=False,
            plan_sha256=plan.plan_sha256,
            _construction_token=None,
        )

    restored = load_sealed_paper_plan(plan_json(plan))
    assert restored == plan
    tampered = json.loads(plan_json(plan))
    tampered["orders"][0]["quantity"] = "0.2"
    with pytest.raises(AlpacaCampaignSleeveError, match="digest mismatch"):
        load_sealed_paper_plan(tampered)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("trading_date", "2026-08-13", "trading_date differs"),
        ("orders_submitted_before", 1, "order sequence differs"),
    ],
)
def test_resealed_redundant_plan_fields_cannot_decouple_snapshot(
    field: str, value: object, match: str
) -> None:
    plan, policy, snapshot, evidence = _plan()
    payload = json.loads(plan_json(plan))
    payload[field] = value
    unsigned = dict(payload)
    unsigned.pop("plan_sha256")
    payload["plan_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    forged = load_sealed_paper_plan(payload)
    with pytest.raises(AlpacaCampaignSleeveError, match=match):
        preflight_paper_plan(
            forged,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc=EVALUATED,
        )


def test_loader_rejects_malformed_unknown_and_wrong_schema() -> None:
    plan, _, _, _ = _plan()
    with pytest.raises(AlpacaCampaignSleeveError, match="valid JSON"):
        load_sealed_paper_plan("{")
    extra = json.loads(plan_json(plan))
    extra["unexpected"] = True
    with pytest.raises(AlpacaCampaignSleeveError, match="fields mismatch"):
        load_sealed_paper_plan(extra)
    wrong_schema = json.loads(plan_json(plan))
    wrong_schema["schema_version"] = 2
    with pytest.raises(AlpacaCampaignSleeveError, match="unsupported"):
        load_sealed_paper_plan(wrong_schema)


def test_expired_plan_never_gets_a_consumption_marker(tmp_path: Path) -> None:
    plan, policy, snapshot, evidence = _plan()
    ledger = PaperPlanConsumptionLedger(tmp_path)
    with pytest.raises(AlpacaCampaignSleeveError, match="expired"):
        ledger.consume_once(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc="2026-08-14T15:05:01Z",
        )
    assert list(tmp_path.iterdir()) == []


def test_unconsumed_plan_cannot_be_finalized(tmp_path: Path) -> None:
    plan, _, _, _ = _plan()
    outcome = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="rejected",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0"),
    )
    with pytest.raises(AlpacaCampaignSleeveError, match="never consumed"):
        PaperPlanConsumptionLedger(tmp_path).finalize(
            plan,
            (outcome,),
            finalized_at_utc=EVALUATED,
        )


def test_plan_consumption_is_idempotent_across_restart(tmp_path: Path) -> None:
    ledger, plan, policy, snapshot, evidence = _consume(tmp_path)

    restarted = PaperPlanConsumptionLedger(tmp_path)
    duplicate = restarted.consume_once(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc="2026-08-14T15:00:20Z",
    )
    assert duplicate.should_submit is False
    assert duplicate.state == "PENDING_RECONCILIATION"
    assert duplicate.preflight is None

    filled = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("649.50"),
    )
    receipt = restarted.finalize(plan, (filled,), finalized_at_utc="2026-08-14T15:00:30Z")
    assert receipt.state == "COMMITTED"
    assert receipt.campaign_halted is False
    assert restarted.finalize(plan, (filled,), finalized_at_utc="2026-08-14T15:00:30Z") == receipt

    after_outcome = ledger.consume_once(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc="2026-08-14T15:00:40Z",
    )
    assert after_outcome.should_submit is False
    assert after_outcome.state == "COMMITTED"


def test_two_plans_cannot_fork_and_spend_the_same_campaign_state(tmp_path: Path) -> None:
    first, policy, snapshot, evidence = _plan()
    second, _, _, _ = _plan(
        policy=policy,
        snapshot=snapshot,
        evidence=evidence,
        orders=(_buy(client_order_id="competing-plan"),),
    )
    assert first.plan_sha256 != second.plan_sha256
    assert first.state_claim_sha256 == second.state_claim_sha256

    ledger = PaperPlanConsumptionLedger(tmp_path)
    assert (
        ledger.consume_once(
            first,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc=EVALUATED,
        ).should_submit
        is True
    )
    refused = ledger.consume_once(
        second,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )
    assert refused.should_submit is False
    assert refused.state == "REFUSED_CAMPAIGN_PENDING"


def test_pending_plan_blocks_even_a_claimed_next_order_sequence(tmp_path: Path) -> None:
    first, policy, snapshot, evidence = _plan()
    ledger = PaperPlanConsumptionLedger(tmp_path)
    assert (
        ledger.consume_once(
            first,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc=EVALUATED,
        ).should_submit
        is True
    )

    claimed_next_snapshot = _snapshot(orders_submitted_today=1)
    next_plan, _, _, _ = _plan(
        policy=policy,
        snapshot=claimed_next_snapshot,
        evidence=evidence,
        orders=(_buy(client_order_id="premature-next-plan"),),
    )
    refused = ledger.consume_once(
        next_plan,
        policy,
        claimed_next_snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )
    assert refused.should_submit is False
    assert refused.state == "REFUSED_CAMPAIGN_PENDING"


def test_orphaned_outcome_never_unlocks_submission(tmp_path: Path) -> None:
    plan, policy, snapshot, evidence = _plan()
    orphan = tmp_path / f"{plan.plan_sha256}.outcome.json"
    orphan.write_text("{}", encoding="utf-8")
    with pytest.raises(AlpacaCampaignSleeveError, match="orphaned outcome"):
        PaperPlanConsumptionLedger(tmp_path).consume_once(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc=EVALUATED,
        )


def test_partial_fill_is_one_immutable_failed_closed_campaign(tmp_path: Path) -> None:
    ledger, plan, policy, snapshot, evidence = _consume(tmp_path)
    partial = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="partially_filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.1"),
        average_fill_price=Decimal("650"),
    )
    receipt = ledger.finalize(plan, (partial,), finalized_at_utc="2026-08-14T15:00:30Z")
    assert receipt.state == "FAILED_CLOSED"
    assert receipt.campaign_halted is True
    assert receipt.requires_manual_reconciliation is True
    assert receipt.outcomes[0].filled_quantity == Decimal("0.1")

    restarted = PaperPlanConsumptionLedger(tmp_path)
    assert (
        restarted.consume_once(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc="2026-08-14T15:00:40Z",
        ).should_submit
        is False
    )
    exact_later = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("650"),
    )
    with pytest.raises(AlpacaCampaignSleeveError, match="different immutable outcome"):
        restarted.finalize(plan, (exact_later,), finalized_at_utc="2026-08-14T15:00:50Z")

    next_snapshot = _snapshot(
        captured_at_utc="2026-08-14T15:00:30Z",
        orders_submitted_today=1,
    )
    next_evidence = (_evidence(quote_at="2026-08-14T15:00:35Z"),)
    next_plan, _, _, _ = _plan(
        policy=policy,
        snapshot=next_snapshot,
        evidence=next_evidence,
        orders=(_buy(client_order_id="blocked-after-partial"),),
        created_at_utc="2026-08-14T15:00:40Z",
        expires_at_utc="2026-08-14T15:05:40Z",
    )
    halted = restarted.consume_once(
        next_plan,
        policy,
        next_snapshot,
        next_evidence,
        evaluated_at_utc="2026-08-14T15:00:55Z",
    )
    assert halted.should_submit is False
    assert halted.state == "REFUSED_CAMPAIGN_HALTED"


def test_committed_plan_advances_exact_daily_sequence(tmp_path: Path) -> None:
    ledger, plan, policy, _, evidence = _consume(tmp_path)
    filled = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("650"),
    )
    assert (
        ledger.finalize(plan, (filled,), finalized_at_utc="2026-08-14T15:00:30Z").state
        == "COMMITTED"
    )

    exit_snapshot = _snapshot(
        cash=Decimal("5"),
        positions=(SleevePosition("SPY", Decimal("0.3")),),
        orders_submitted_today=1,
    )
    exit_plan, _, _, _ = _plan(
        policy=policy,
        snapshot=exit_snapshot,
        evidence=evidence,
        orders=(_sell(),),
    )
    decision = ledger.consume_once(
        exit_plan,
        policy,
        exit_snapshot,
        evidence,
        evaluated_at_utc=EVALUATED,
    )
    assert decision.should_submit is True


def test_committed_campaign_rejects_a_rewound_daily_counter(tmp_path: Path) -> None:
    ledger, plan, policy, snapshot, evidence = _consume(tmp_path)
    filled = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("650"),
    )
    ledger.finalize(plan, (filled,), finalized_at_utc="2026-08-14T15:00:30Z")
    rewound_snapshot = _snapshot(captured_at_utc="2026-08-14T15:00:20Z")
    rewound_evidence = (_evidence(quote_at="2026-08-14T15:00:20Z"),)
    rewound, _, _, _ = _plan(
        policy=policy,
        snapshot=rewound_snapshot,
        evidence=rewound_evidence,
        orders=(_buy(client_order_id="rewound-counter"),),
        created_at_utc="2026-08-14T15:00:25Z",
        expires_at_utc="2026-08-14T15:05:25Z",
    )
    decision = ledger.consume_once(
        rewound,
        policy,
        rewound_snapshot,
        rewound_evidence,
        evaluated_at_utc="2026-08-14T15:00:40Z",
    )
    assert decision.should_submit is False
    assert decision.state == "REFUSED_STATE_REGRESSION"


def test_committed_buy_rejects_reset_cash_and_positions(tmp_path: Path) -> None:
    ledger, plan, policy, _, _ = _consume(tmp_path)
    filled = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("650"),
    )
    ledger.finalize(plan, (filled,), finalized_at_utc="2026-08-14T15:00:30Z")

    reset_snapshot = _snapshot(
        captured_at_utc="2026-08-14T15:00:20Z",
        cash=Decimal("200"),
        positions=(),
        orders_submitted_today=1,
    )
    reset_evidence = (_evidence(quote_at="2026-08-14T15:00:20Z"),)
    second, _, _, _ = _plan(
        policy=policy,
        snapshot=reset_snapshot,
        evidence=reset_evidence,
        orders=(_buy(client_order_id="forbidden-second-buy"),),
        created_at_utc="2026-08-14T15:00:25Z",
        expires_at_utc="2026-08-14T15:05:25Z",
    )
    refused = ledger.consume_once(
        second,
        policy,
        reset_snapshot,
        reset_evidence,
        evaluated_at_utc="2026-08-14T15:00:40Z",
    )
    assert refused.should_submit is False
    assert refused.state == "REFUSED_STATE_DISCONTINUITY"


def test_rejection_halts_campaign_and_missing_outcome_cannot_unlock_retry(
    tmp_path: Path,
) -> None:
    ledger, plan, policy, snapshot, evidence = _consume(tmp_path)
    with pytest.raises(AlpacaCampaignSleeveError, match="exactly cover"):
        ledger.finalize(plan, (), finalized_at_utc="2026-08-14T15:00:20Z")
    assert (
        ledger.consume_once(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc="2026-08-14T15:00:25Z",
        ).should_submit
        is False
    )

    rejected = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="rejected",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0"),
    )
    receipt = ledger.finalize(plan, (rejected,), finalized_at_utc="2026-08-14T15:00:30Z")
    assert receipt.state == "FAILED_CLOSED"
    assert receipt.campaign_halted is True
    assert receipt.requires_manual_reconciliation is True


def test_exact_quantity_at_a_price_outside_limit_fails_closed(tmp_path: Path) -> None:
    ledger, plan, _, _, _ = _consume(tmp_path)
    impossible_price = PaperOrderOutcome(
        client_order_id=plan.orders[0].client_order_id,
        status="filled",
        requested_quantity=Decimal("0.3"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("651"),
    )
    receipt = ledger.finalize(
        plan,
        (impossible_price,),
        finalized_at_utc="2026-08-14T15:00:30Z",
    )
    assert receipt.state == "FAILED_CLOSED"
    assert "limit price" in receipt.reason


def test_consumption_marker_tamper_blocks_restart(tmp_path: Path) -> None:
    _, plan, policy, snapshot, evidence = _consume(tmp_path)
    marker = next(tmp_path.glob("*.consumption.json"))
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["record"]["campaign_id"] = "tampered"
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AlpacaCampaignSleeveError, match="digest mismatch"):
        PaperPlanConsumptionLedger(tmp_path).consume_once(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc="2026-08-14T15:00:20Z",
        )
