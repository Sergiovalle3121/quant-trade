"""V7 regressions for board allocation, shadow durability and paper safety."""

from __future__ import annotations

import json

import pytest

from quant_trade.execution.broker import BrokerAccount, BrokerOrderRequest
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerSafetyError
from quant_trade.execution.safety import validate_order_safety
from quant_trade.execution.simulated_broker import SimulatedBroker
from quant_trade.opportunities.board import (
    allocate_paper_capital,
    build_opportunity_board,
    lineage_for_rows,
)
from quant_trade.opportunities.shadow import (
    shadow_advance,
    shadow_start,
    shadow_status,
)

NOW = "2026-07-25T00:00:00Z"


def _real_cash() -> dict:
    return {
        "annual_yield": 0.04,
        "evidence_class": "REAL",
        "raw_artifact": "tests/fixtures/cash_baseline_v7.raw.json",
        "raw_sha256": "4d258de86011484bc99085f813f8a832e89653b8beb5c35526c0ef46448f5462",
    }


def _lineages() -> dict:
    return {
        "trading_lineage": lineage_for_rows(
            [],
            artifact="TRADING_OPPORTUNITY_LEADERBOARD",
            path="<memory>",
            evaluated_at_utc=NOW,
        ),
    }


def _allocation() -> dict:
    return {
        "artifact": "PAPER_CAPITAL_ALLOCATION",
        "paper_only": True,
        "total_capital_usd": 100_000.0,
        "allocations": [
            {
                "entry_id": "cash_usd",
                "kind": "cash",
                "fraction": 1.0,
                "capital_usd": 100_000.0,
            }
        ],
    }


# test_mining_score_does_not_multiply_short_horizon_by_hours_per_year retired
# with _mining_score. The x8766 defect it pinned (V7-015) stays recorded in the
# defect register, and the rule it enforced - one 30d common unit, no
# short-horizon annualisation - is asserted for the surviving kinds below.


def test_board_refuses_rows_scanned_at_a_different_clock() -> None:
    """The single-scan replacement for the retired two-clock reconciliation."""
    with pytest.raises(ValueError, match="re-scan"):
        build_opportunity_board(
            trading_rows=[],
            cash_yield_annual=0.04,
            cash_evidence=_real_cash(),
            evaluated_at_utc="2026-07-25T09:00:00Z",  # not the scan's clock
            **_lineages(),
        )


def test_allocator_rejects_below_cash_and_weights_risk_and_capacity() -> None:
    board = {
        "evaluated_at_utc": NOW,
        "entries": [
            {"entry_id": "cash_usd", "kind": "cash", "eligible": True, "score": 0.05},
            {
                "entry_id": "below-cash",
                "kind": "trading",
                "status": "PAPER_CANDIDATE",
                "eligible": True,
                "score": 0.04,
            },
            {
                "entry_id": "capacity-limited",
                "kind": "trading",
                "status": "PAPER_CANDIDATE",
                "eligible": True,
                "score": 0.25,
                "risk_score": 1.0,
                "liquidity_score": 1.0,
                "capacity_usd": 10_000.0,
            },
            {
                "entry_id": "risk-limited",
                "kind": "trading",
                "status": "PAPER_CANDIDATE",
                "eligible": True,
                "score": 0.15,
                "risk_score": 0.5,
                "liquidity_score": 1.0,
            },
            {
                "entry_id": "blocked",
                "kind": "trading",
                "status": "POLICY_BLOCKED",
                "eligible": False,
                "score": 9.0,
                "reasons": ["blocked"],
            },
        ],
        "champion": {"entry_id": "capacity-limited"},
        "challengers": [],
    }
    allocation = allocate_paper_capital(board, 100_000.0, max_fraction_per_opportunity=0.5)
    by_id = {line["entry_id"]: line for line in allocation["allocations"]}
    assert by_id["below-cash"]["capital_usd"] == 0
    assert by_id["blocked"]["capital_usd"] == 0
    assert by_id["capacity-limited"]["capital_usd"] == pytest.approx(10_000.0)
    assert by_id["risk-limited"]["capital_usd"] == pytest.approx(20_000.0)
    assert by_id["cash_usd"]["capital_usd"] == pytest.approx(70_000.0)


def test_shadow_rejects_same_batch_duplicates_and_nonmonotonic_input(tmp_path) -> None:
    shadow_start(tmp_path, _allocation(), started_at_utc=NOW)
    event = {
        "seq": 1,
        "timestamp_utc": "2026-07-25T01:00:00Z",
        "cash_yield_daily": 0.001,
    }
    with pytest.raises(ValueError, match="duplicate"):
        shadow_advance(tmp_path, [event, event])
    with pytest.raises(ValueError, match="strictly increasing"):
        shadow_advance(
            tmp_path,
            [
                {**event, "seq": 2, "timestamp_utc": "2026-07-25T02:00:00Z"},
                event,
            ],
        )
    with pytest.raises(ValueError, match="timestamps"):
        shadow_advance(
            tmp_path,
            [
                {**event, "timestamp_utc": "2026-07-25T02:00:00Z"},
                {
                    **event,
                    "seq": 2,
                    "timestamp_utc": "2026-07-25T01:00:00Z",
                },
            ],
        )
    assert shadow_status(tmp_path)["events_processed"] == 0


def test_shadow_recovers_checkpoint_after_event_wal_was_fsynced(tmp_path) -> None:
    shadow_start(tmp_path, _allocation(), started_at_utc=NOW)
    result = shadow_advance(
        tmp_path,
        [
            {
                "seq": 1,
                "timestamp_utc": "2026-07-25T01:00:00Z",
                "cash_yield_daily": 0.001,
            },
            {
                "seq": 2,
                "timestamp_utc": "2026-07-25T02:00:00Z",
                "cash_yield_daily": 0.001,
            },
        ],
    )
    snapshots = tmp_path / "snapshots.jsonl"
    lines = snapshots.read_text(encoding="utf-8").splitlines()
    snapshots.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    status = shadow_status(tmp_path)
    assert status["events_processed"] == 2
    assert status["equity_usd"] == pytest.approx(result["equity_usd"])
    assert len(snapshots.read_text(encoding="utf-8").splitlines()) == 3


def test_shadow_reverifies_frozen_allocation_hash(tmp_path) -> None:
    shadow_start(tmp_path, _allocation(), started_at_utc=NOW)
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["frozen_allocation"]["total_capital_usd"] = 1.0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="allocation hash"):
        shadow_status(tmp_path)


def test_market_order_requires_fresh_reference_price() -> None:
    account = BrokerAccount(
        "simulated", "sim****", "USD", 100_000.0, 100_000.0, 100_000.0, "active", True
    )
    config = BrokerConfig(max_reference_age_seconds=60.0)
    missing = BrokerOrderRequest("SPY", "buy", 1.0, "market", "day", "missing")
    with pytest.raises(BrokerSafetyError, match="fresh reference"):
        validate_order_safety(missing, config, account, evaluated_at_utc=NOW)

    stale = BrokerOrderRequest(
        "SPY",
        "buy",
        1.0,
        "market",
        "day",
        "stale",
        reference_price=500.0,
        reference_timestamp_utc="2026-07-24T23:00:00Z",
    )
    with pytest.raises(BrokerSafetyError, match="stale"):
        validate_order_safety(stale, config, account, evaluated_at_utc=NOW)


def test_simulated_broker_is_idempotent_by_client_order_id() -> None:
    broker = SimulatedBroker()
    request = BrokerOrderRequest("SPY", "buy", 1.0, "market", "day", "stable-key")
    first = broker.submit_order(request)
    second = broker.submit_order(request)
    assert first.broker_order_id == second.broker_order_id
    assert len(broker.orders) == 1

    conflicting = BrokerOrderRequest("SPY", "buy", 2.0, "market", "day", "stable-key")
    with pytest.raises(BrokerSafetyError, match="different order"):
        broker.submit_order(conflicting)
