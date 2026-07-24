"""Tests for execution parity and paper-trial readiness V3 (offline)."""

from __future__ import annotations

from quant_trade.paper.parity import (
    ExecutionRecord,
    ParityTolerances,
    compare_executions,
    three_way_parity,
)
from quant_trade.paper.readiness import (
    NOT_READY,
    READY,
    evaluate_paper_readiness,
    generate_paper_runbook,
)


def _record(source: str, **overrides) -> ExecutionRecord:
    base = dict(
        source=source,
        target_weights={"AAA": 0.5, "BBB": 0.5},
        order_quantities={"AAA": 10.0, "BBB": 5.0},
        fills=[
            {"symbol": "AAA", "quantity": 10.0, "price": 100.0, "fee": 1.0, "slippage_bps": 1.0},
            {"symbol": "BBB", "quantity": 5.0, "price": 200.0, "fee": 1.0, "slippage_bps": 1.0},
        ],
        cancellations=0,
        partial_fills=0,
        final_positions={"AAA": 10.0, "BBB": 5.0},
        final_cash=1000.0,
        final_equity=3000.0,
    )
    base.update(overrides)
    return ExecutionRecord(**base)


# --- parity ---------------------------------------------------------------


def test_identical_paths_reconcile():
    report = compare_executions(_record("backtest"), _record("simulated_paper"))
    assert report.reconciled
    assert report.equity_drift == 0.0
    assert all(c.status == "match" for c in report.comparisons)


def test_equity_divergence_is_flagged_and_explained():
    a = _record("backtest")
    b = _record("simulated_paper", final_equity=2900.0)
    report = compare_executions(a, b)
    assert not report.reconciled
    assert report.equity_drift == 100.0
    equity = next(c for c in report.comparisons if c.field == "final_equity")
    assert equity.status == "divergence"
    assert "diverge" in equity.explanation


def test_partial_fill_and_cancellation_differences_flagged():
    a = _record("backtest")
    b = _record("simulated_paper", partial_fills=2, cancellations=1)
    report = compare_executions(a, b)
    codes = {c.field for c in report.comparisons if c.status == "divergence"}
    assert "partial_fills" in codes
    assert "cancellations" in codes


def test_within_tolerance_is_not_a_divergence():
    a = _record("backtest")
    b = _record("simulated_paper", final_equity=3000.5)  # < equity_abs tolerance of 1.0
    report = compare_executions(a, b, tolerances=ParityTolerances(equity_abs=1.0))
    equity = next(c for c in report.comparisons if c.field == "final_equity")
    assert equity.status == "within_tolerance"
    assert report.reconciled


def test_fee_divergence_flagged():
    a = _record("backtest")
    b = _record(
        "broker_paper",
        fills=[
            {"symbol": "AAA", "quantity": 10.0, "price": 100.0, "fee": 5.0},
            {"symbol": "BBB", "quantity": 5.0, "price": 200.0, "fee": 5.0},
        ],
    )
    report = compare_executions(a, b)
    fees = next(c for c in report.comparisons if c.field == "total_fees")
    assert fees.status == "divergence"


def test_three_way_parity_structure():
    result = three_way_parity(
        _record("backtest"), _record("simulated_paper"), _record("broker_paper")
    )
    assert result["fully_reconciled"]
    assert "backtest_vs_simulated_paper" in result
    assert "simulated_paper_vs_broker_paper" in result


# --- readiness (drill-evidence based) --------------------------------------

from quant_trade.paper.readiness import (  # noqa: E402
    REQUIRED_DRILLS,
    record_drill,
    run_parity_drill,
)

NOW = "2026-07-24T12:00:00Z"


def _record_all_drills(evidence_dir, executed_at: str = "2026-07-20T00:00:00Z") -> None:
    for name in REQUIRED_DRILLS:
        record_drill(
            evidence_dir,
            name=name,
            result="pass",
            executed_at_utc=executed_at,
            failure_injected=name in ("kill_switch", "recovery", "orphan_detection"),
            details={"note": "test drill"},
        )


def _ready_config(evidence_dir=None, **overrides) -> dict:
    base = dict(
        broker_mode="paper",
        broker_endpoint="https://paper-api.alpaca.markets",
        live_trading=False,
        exporter_enabled=True,
        recovery_enabled=True,
        kill_switch_enabled=True,
        orphan_detection_enabled=True,
        heartbeat_interval_seconds=30,
        reconciliation_enabled=True,
    )
    if evidence_dir is not None:
        base["drill_evidence_dir"] = str(evidence_dir)
    base.update(overrides)
    return base


def test_full_config_with_executed_drills_is_ready(tmp_path):
    _record_all_drills(tmp_path)
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    assert report.status == READY, report.blocking
    assert report.blocking == []
    assert report.real_money_authorized is False
    assert report.trial_days_completed == 0  # never fabricated


def test_missing_single_drill_is_not_ready(tmp_path):
    _record_all_drills(tmp_path)
    (tmp_path / "drill_kill_switch.json").unlink()
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    assert report.status == NOT_READY
    assert "drill_kill_switch_executed" in report.blocking


def test_expired_drill_is_not_ready(tmp_path):
    _record_all_drills(tmp_path, executed_at="2026-01-01T00:00:00Z")  # months old
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    assert report.status == NOT_READY
    assert any(name.startswith("drill_") for name in report.blocking)


def test_failed_drill_result_is_not_ready(tmp_path):
    _record_all_drills(tmp_path)
    record_drill(
        tmp_path, name="recovery", result="fail",
        executed_at_utc="2026-07-20T00:00:00Z", failure_injected=True,
        details={"note": "recovery lost state"},
    )
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    assert report.status == NOT_READY
    assert "drill_recovery_executed" in report.blocking


def test_no_failure_injection_is_not_ready(tmp_path):
    _record_all_drills(tmp_path)
    record_drill(
        tmp_path, name="kill_switch", result="pass",
        executed_at_utc="2026-07-20T00:00:00Z", failure_injected=False,  # no-op run
        details={"note": "switch toggled with nothing running"},
    )
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    assert report.status == NOT_READY
    assert "no-op" in report.drill_summary["kill_switch"]


def test_live_trading_blocks_readiness(tmp_path):
    _record_all_drills(tmp_path)
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path, live_trading=True), evaluated_at_utc=NOW
    )
    assert report.status == NOT_READY
    assert "broker_is_paper_only" in report.blocking


def test_zero_heartbeat_blocks(tmp_path):
    _record_all_drills(tmp_path)
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path, heartbeat_interval_seconds=0),
        evaluated_at_utc=NOW,
    )
    assert "heartbeat_configured" in report.blocking


def test_parity_drill_actually_executes_and_records(tmp_path):
    path = run_parity_drill(tmp_path, executed_at_utc="2026-07-20T00:00:00Z")
    import json

    payload = json.loads(path.read_text())
    assert payload["drill"] == "parity"
    assert payload["result"] == "pass"
    assert payload["details"]["identical_run_reconciled"] is True
    assert payload["details"]["perturbed_run_diverged"] is True
    assert payload["evidence_sha256"]


def test_runbook_lists_checks_and_real_money_nogo(tmp_path):
    _record_all_drills(tmp_path)
    report = evaluate_paper_readiness(
        _ready_config(evidence_dir=tmp_path), evaluated_at_utc=NOW
    )
    runbook = generate_paper_runbook(report)
    assert "Real money: **NO-GO**" in runbook
    assert "kill_switch" in runbook
    assert "executed drills, not booleans" in runbook
