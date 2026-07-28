"""V8 paper launch gating, session honesty, and canary readiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.v8.campaigns import (
    STATUS_INSUFFICIENT,
    STATUS_NO_EVIDENCE,
    STATUS_PAPER_CANDIDATE,
    STATUS_REJECTED,
    CampaignResult,
)
from quant_trade.v8.canary import (
    CONDITION_HUMAN,
    CONDITION_MACHINE,
    MIN_PAPER_EVENTS,
    MIN_PAPER_WALL_CLOCK_HOURS,
    evaluate_canary_readiness,
)
from quant_trade.v8.paper_launch import (
    CLOCK_REPLAY,
    CLOCK_WALL,
    PAPER_STATUS_NOT_STARTED,
    PAPER_STATUS_RUNNING,
    NoCandidateError,
    advance_paper_session,
    build_paper_candidate_manifest,
    launch_paper_session,
    not_started_report,
    paper_session_status,
    resume_command_for,
)


def _candidate(status: str = STATUS_PAPER_CANDIDATE) -> CampaignResult:
    return CampaignResult(
        hypothesis_id="H1",
        title="Bybit BTC carry",
        status=status,
        preregistration_hash="a" * 64,
        evidence={
            "venues": {
                "bybit": {
                    "directory": "/evidence/bybit_btc_usdt",
                    "provenance": "real",
                    "raw_pages": 120,
                    "receipts": 120,
                    "sufficiency": {
                        "span_days": 731.0,
                        "unique_settlements": 2193,
                        "evidence_sha256": "b" * 64,
                    },
                }
            }
        },
        economics={
            "net_return": 0.21,
            "net_return_2x_costs": 0.12,
            "net_return_3x_costs": 0.05,
            "max_drawdown": -0.04,
            "holdout_net_return": 0.03,
        },
        capacity={"available": True, "capacity_notional_usd": 75_000.0},
        holdout={"selected": "H1-t5-w3", "reveal_count": 1, "selection_frozen": True},
        variants_evaluated=[
            {
                "variant_id": "H1-t5-w3",
                "parameters": {"entry_threshold": 5e-5, "trailing_window": 3},
            }
        ],
        cost_stack={"venue": "bybit", "promotable": True, "components": []},
    )


# --- manifest gating --------------------------------------------------------------


@pytest.mark.parametrize("status", [STATUS_REJECTED, STATUS_NO_EVIDENCE, STATUS_INSUFFICIENT])
def test_no_manifest_without_a_passing_campaign(status: str) -> None:
    with pytest.raises(NoCandidateError, match="there is no candidate to launch"):
        build_paper_candidate_manifest(_candidate(status), created_at_utc="2026-07-28T00:00:00Z")


def test_manifest_freezes_everything_that_defines_the_candidate() -> None:
    manifest = build_paper_candidate_manifest(
        _candidate(), created_at_utc="2026-07-28T00:00:00Z", capital_usd=10_000.0
    )
    assert manifest.candidate_id == "H1-H1-t5-w3"
    assert manifest.preregistration_hash == "a" * 64
    assert manifest.evidence["dataset_sha256"] == "b" * 64
    assert manifest.frozen_config["parameters"]["entry_threshold"] == 5e-5
    assert manifest.allocation["paper_only"] is True
    assert manifest.expected_economics["net_return"] == 0.21
    assert len(manifest.manifest_sha256) == 64


def test_manifest_hash_changes_when_anything_frozen_changes() -> None:
    base = build_paper_candidate_manifest(_candidate(), created_at_utc="2026-07-28T00:00:00Z")
    other = build_paper_candidate_manifest(
        _candidate(), created_at_utc="2026-07-28T00:00:00Z", capital_usd=20_000.0
    )
    assert base.manifest_sha256 != other.manifest_sha256


def test_position_cap_respects_the_measured_capacity() -> None:
    manifest = build_paper_candidate_manifest(
        _candidate(), created_at_utc="2026-07-28T00:00:00Z", capital_usd=1_000_000.0
    )
    assert manifest.limits["max_position_notional_usd"] == 75_000.0


def test_manifest_never_authorises_real_money() -> None:
    manifest = build_paper_candidate_manifest(_candidate(), created_at_utc="2026-07-28T00:00:00Z")
    safety = manifest.to_dict()["safety"]
    assert safety["real_money_authorized"] is False
    assert safety["order_routing_enabled"] is False
    assert safety["withdrawals_enabled"] is False
    assert safety["deposits_enabled"] is False


# --- not started ------------------------------------------------------------------


def test_not_started_report_is_explicit_about_staying_in_cash() -> None:
    report = not_started_report("no hypothesis passed its gates")
    payload = report.to_dict()
    assert payload["status"] == PAPER_STATUS_NOT_STARTED
    assert payload["wall_clock_seconds"] == 0.0
    assert payload["simulated_span_days"] == 0.0
    assert payload["events_processed"] == 0
    assert any("100% cash" in n for n in payload["notes"])


# --- running sessions --------------------------------------------------------------


def _launch(tmp_path: Path, clock: str = CLOCK_WALL, started_at: str = "2026-07-28T00:00:00Z"):
    manifest = build_paper_candidate_manifest(
        _candidate(), created_at_utc="2026-07-28T00:00:00Z", capital_usd=10_000.0
    )
    report = launch_paper_session(
        manifest, tmp_path / "session", started_at_utc=started_at, clock=clock
    )
    return manifest, report


def test_launch_writes_a_recoverable_session(tmp_path: Path) -> None:
    manifest, report = _launch(tmp_path)
    assert report.status == PAPER_STATUS_RUNNING
    assert report.manifest_sha256 == manifest.manifest_sha256
    assert (tmp_path / "session" / "state.json").exists()
    assert (tmp_path / "session" / "paper_candidate_manifest.json").exists()
    assert report.resume_command.startswith("quant-trade v8 paper-status")


def test_advancing_records_events_signals_orders_and_fills(tmp_path: Path) -> None:
    _manifest, _report = _launch(tmp_path)
    events = [
        {"seq": 1, "timestamp_utc": "2026-07-28T00:01:00Z", "kind": "signal"},
        {"seq": 2, "timestamp_utc": "2026-07-28T00:02:00Z", "kind": "paper_order"},
        {
            "seq": 3,
            "timestamp_utc": "2026-07-28T00:03:00Z",
            "kind": "paper_fill",
            "cash_yield_daily": 0.001,
        },
    ]
    report = advance_paper_session(tmp_path / "session", events, wall_clock_seconds=180.0)
    assert report.events_processed == 3
    assert report.signals_emitted == 1
    assert report.paper_orders == 1
    assert report.paper_fills == 1
    assert report.equity_usd == pytest.approx(10_010.0)  # one 0.1% accrual
    assert report.heartbeat_at_utc == "2026-07-28T00:03:00Z"


def test_replaying_two_years_in_minutes_does_not_claim_two_years(tmp_path: Path) -> None:
    """The one claim this module exists to make impossible."""
    # A replay session's clock starts at the beginning of the replayed history.
    _manifest, _report = _launch(tmp_path, clock=CLOCK_REPLAY, started_at="2023-12-31T00:00:00Z")
    events = [
        {"seq": 1, "timestamp_utc": "2024-01-01T00:00:00Z", "kind": "signal"},
        {"seq": 2, "timestamp_utc": "2026-01-01T00:00:00Z", "kind": "signal"},
    ]
    report = advance_paper_session(
        tmp_path / "session", events, clock=CLOCK_REPLAY, wall_clock_seconds=90.0
    )
    payload = report.to_dict()
    assert payload["clock"] == CLOCK_REPLAY
    assert payload["wall_clock_seconds"] == 90.0
    assert payload["simulated_span_days"] > 700
    assert "never summed" in payload["duration_note"]


def test_replayed_events_are_applied_exactly_once(tmp_path: Path) -> None:
    _manifest, _report = _launch(tmp_path)
    events = [
        {"seq": 1, "timestamp_utc": "2026-07-28T00:01:00Z", "kind": "signal"},
    ]
    advance_paper_session(tmp_path / "session", events, wall_clock_seconds=1.0)
    again = advance_paper_session(tmp_path / "session", events, wall_clock_seconds=1.0)
    assert again.events_processed == 1


def test_status_survives_a_process_restart(tmp_path: Path) -> None:
    _manifest, _report = _launch(tmp_path)
    advance_paper_session(
        tmp_path / "session",
        [
            {
                "seq": 1,
                "timestamp_utc": "2026-07-28T00:01:00Z",
                "kind": "paper_fill",
                "cash_yield_daily": 0.005,
            }
        ],
        wall_clock_seconds=60.0,
    )
    # A fresh reader with no in-memory state.
    report = paper_session_status(tmp_path / "session", wall_clock_seconds=60.0)
    assert report.status == PAPER_STATUS_RUNNING
    assert report.events_processed == 1
    assert report.paper_fills == 1
    assert report.equity_usd == pytest.approx(10_050.0)


def test_resume_command_names_the_state_directory(tmp_path: Path) -> None:
    assert str(tmp_path.as_posix()) in resume_command_for(tmp_path)


def test_an_unknown_clock_is_rejected(tmp_path: Path) -> None:
    manifest = build_paper_candidate_manifest(_candidate(), created_at_utc="2026-07-28T00:00:00Z")
    with pytest.raises(ValueError, match="clock must be"):
        launch_paper_session(
            manifest, tmp_path / "s", started_at_utc="2026-07-28T00:00:00Z", clock="vibes"
        )


# --- canary readiness ---------------------------------------------------------------


def test_canary_is_blocked_with_no_paper_session() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z", paper_status=None
    )
    payload = readiness.to_dict()
    assert payload["status"] == "BLOCKED"
    assert payload["canary_authorized"] is False
    assert len(payload["blocking_conditions"]) == 6


def test_a_short_smoke_test_does_not_satisfy_the_paper_condition() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status={"status": "RUNNING", "wall_clock_seconds": 300.0, "events_processed": 12},
    )
    condition = next(c for c in readiness.conditions if c.condition_id == "paper_result_sufficient")
    assert not condition.satisfied
    assert condition.required["wall_clock_hours"] == MIN_PAPER_WALL_CLOCK_HOURS
    assert condition.required["events_processed"] == MIN_PAPER_EVENTS


def test_four_conditions_require_a_human_by_construction() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z", paper_status=None
    )
    human = [c for c in readiness.conditions if c.kind == CONDITION_HUMAN]
    machine = [c for c in readiness.conditions if c.kind == CONDITION_MACHINE]
    assert len(human) == 4
    assert len(machine) == 2
    assert {c.condition_id for c in human} == {
        "owner_budget_explicit",
        "exchange_and_jurisdiction_confirmed",
        "loss_limits_configured",
        "credentials_delivery_secure",
    }


def test_engineering_alone_can_never_unblock_the_canary() -> None:
    """Perfect paper evidence still leaves the human conditions blocking."""
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status={
            "status": "RUNNING",
            "wall_clock_seconds": MIN_PAPER_WALL_CLOCK_HOURS * 3600.0,
            "events_processed": MIN_PAPER_EVENTS,
            "reconciliation": {"reconciled": True},
        },
    )
    assert readiness.status == "BLOCKED"
    assert set(readiness.blocking_conditions) == {
        "owner_budget_explicit",
        "exchange_and_jurisdiction_confirmed",
        "loss_limits_configured",
        "credentials_delivery_secure",
    }


def test_all_six_satisfied_still_does_not_authorise_real_money() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status={
            "status": "RUNNING",
            "wall_clock_seconds": MIN_PAPER_WALL_CLOCK_HOURS * 3600.0,
            "events_processed": MIN_PAPER_EVENTS,
            "reconciliation": {"reconciled": True},
        },
        owner_budget_usd=500.0,
        exchange_and_jurisdiction_confirmed=True,
        loss_limits_configured={"per_trade": 25.0, "daily": 50.0, "total": 150.0},
        credentials_delivery_mechanism_confirmed=True,
    )
    payload = readiness.to_dict()
    assert payload["status"] == "READY_PENDING_HUMAN_AUTHORISATION"
    assert payload["unblocked"] is True
    assert payload["canary_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert payload["safety"]["no_credentials_requested_or_stored"] is True


def test_partial_loss_limits_do_not_count() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status=None,
        loss_limits_configured={"daily": 50.0},
    )
    assert "loss_limits_configured" in readiness.blocking_conditions


def test_a_zero_budget_is_not_a_budget() -> None:
    readiness = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z", paper_status=None, owner_budget_usd=0.0
    )
    assert "owner_budget_explicit" in readiness.blocking_conditions
