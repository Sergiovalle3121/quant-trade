"""Fase E tests: fail-closed trial data, the paper->trials bridge, and
policy gates that actually gate."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

from quant_trade.trials.decisions import recommend_decision
from quant_trade.trials.exceptions import TrialDataMissingError
from quant_trade.trials.export import export_daily_records_from_paper_run
from quant_trade.trials.models import DailyTrialRecord, TrialConfig, TrialPolicy
from quant_trade.trials.performance import calculate_trial_performance
from quant_trade.trials.tracker import collect_daily_records, load_trial_timeseries


def _trial(trial_id: str = "t1") -> TrialConfig:
    return TrialConfig(
        trial_id=trial_id,
        display_name="test",
        status="active",
        paper_session_id="sess1",
        strategy_name="time_series_momentum",
        strategy_params={},
        universe=["BTC-USD"],
        benchmark="equal_weight_universe",
        paper_config_path="configs/paper/x.yaml",
        ops_config_path="configs/ops/x.yaml",
        start_date=date(2026, 1, 1),
        planned_end_date=date(2026, 3, 31),
        trial_length_days=90,
        review_frequency="weekly",
        timezone="UTC",
        owner="o",
        reviewer="r",
        initial_paper_equity=100_000.0,
        expected_rebalance_frequency="weekly",
        expected_turnover_range=(0.0, 1.0),
    )


def test_collect_fails_closed_without_real_records(tmp_path):
    with pytest.raises(TrialDataMissingError, match="never fabricated"):
        collect_daily_records(_trial(), artifact_roots=[tmp_path])


def test_export_bridge_produces_loadable_records(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(5)]
    equities = [100_000.0, 100_500.0, 100_200.0, 100_900.0, 101_200.0]
    with (run / "account_snapshots.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp", "cash", "equity", "gross_exposure",
                "realized_pnl", "unrealized_pnl", "drawdown",
            ],
        )
        w.writeheader()
        for d, e in zip(days, equities, strict=True):
            w.writerow(
                {
                    "timestamp": f"{d}T00:00:00+00:00",
                    "cash": e * 0.2,
                    "equity": e,
                    "gross_exposure": 0.8,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "drawdown": 0.01,
                }
            )
    with (run / "orders.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "status", "quantity", "price"])
        w.writeheader()
        w.writerow({"timestamp": f"{days[1]}T00:00:00+00:00", "status": "filled",
                    "quantity": 10, "price": 100})
        w.writerow({"timestamp": f"{days[1]}T00:00:00+00:00", "status": "rejected",
                    "quantity": 5, "price": 100})
    with (run / "fills.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "quantity", "price"])
        w.writeheader()
        w.writerow({"timestamp": f"{days[1]}T00:00:00+00:00", "quantity": 10, "price": 100})

    out = export_daily_records_from_paper_run(run, "t1", "sess1", tmp_path / "trials")
    assert out.name == "t1_daily_records.csv"
    # the exported file is exactly what collect_daily_records consumes
    records = collect_daily_records(_trial("t1"), artifact_roots=[tmp_path / "trials"])
    assert len(records) == 5
    day2 = [r for r in records if r.date == days[1]][0]
    assert day2.orders_count == 2
    assert day2.rejected_orders_count == 1
    assert day2.fills_count == 1
    assert day2.turnover == pytest.approx(1000.0 / 100_500.0)
    assert records[-1].cumulative_return == pytest.approx(101_200.0 / 100_000.0 - 1)


def _records(daily_returns, **overrides) -> list[DailyTrialRecord]:
    records = []
    equity = 100_000.0
    peak = equity
    for i, r in enumerate(daily_returns):
        equity *= 1 + r
        peak = max(peak, equity)
        records.append(
            DailyTrialRecord(
                trial_id="t1",
                date=date(2026, 1, 1) + timedelta(days=i),
                paper_session_id="s",
                equity=equity,
                cash=equity * 0.2,
                daily_return=r,
                cumulative_return=equity / 100_000.0 - 1,
                drawdown=equity / peak - 1,
                benchmark_return=overrides.get("benchmark_return", 0.0),
                excess_return=r,
                orders_count=overrides.get("orders_count", 2),
                fills_count=2,
                rejected_orders_count=overrides.get("rejected", 0),
                turnover=0.05,
                gross_exposure=0.8,
                max_position_weight=0.2,
                slippage_bps=overrides.get("slippage", 2.0),
                risk_events_count=0,
                open_incidents_count=0,
                heartbeat_status="ok",
                reconciliation_status=overrides.get("reconciliation", "pass"),
                kill_switch_active=False,
            )
        )
    return records


def test_policy_gates_block_bad_trials():
    policy = TrialPolicy()
    good = _records([0.004, -0.001, 0.005, 0.002, -0.002, 0.006] * 5)
    base_pack = {"trial_id": "t1", "human_notes": "reviewed"}
    ok = recommend_decision(
        {**base_pack, "performance_summary": calculate_trial_performance(good)}, policy
    )
    assert ok.decision == "continue_trial", ok.blocking_issues

    big_daily_loss = _records([0.001] * 10 + [-0.05] + [0.001] * 10)
    d = recommend_decision(
        {**base_pack, "performance_summary": calculate_trial_performance(big_daily_loss)}, policy
    )
    assert d.decision == "pause_trial"
    assert any("single-day loss" in b for b in d.blocking_issues)

    slippy = _records([0.001] * 30, slippage=25.0)
    d = recommend_decision(
        {**base_pack, "performance_summary": calculate_trial_performance(slippy)}, policy
    )
    assert any("slippage" in b for b in d.blocking_issues)

    reconciliation_broken = _records([0.001] * 30, reconciliation="fail")
    d = recommend_decision(
        {**base_pack, "performance_summary": calculate_trial_performance(reconciliation_broken)},
        policy,
    )
    assert any("reconciliation" in b for b in d.blocking_issues)


def test_thin_evidence_warns_not_blocks():
    policy = TrialPolicy(min_observation_days=20)
    thin = _records([0.001] * 5)
    d = recommend_decision(
        {
            "trial_id": "t1",
            "human_notes": "x",
            "performance_summary": calculate_trial_performance(thin),
        },
        policy,
    )
    assert d.decision == "needs_human_review"
    assert any("observation days" in w for w in d.warnings)


def test_performance_summary_has_statistical_content():
    perf = calculate_trial_performance(_records([0.002] * 60))
    assert 0.0 <= perf["psr"] <= 1.0
    assert perf["minimum_track_record_days"] != 0.0
    # constant positive returns with zero variance: PSR degenerates to 0 by design
    varied = calculate_trial_performance(
        _records([0.002, -0.001, 0.003, 0.001, -0.002] * 12)
    )
    assert varied["psr"] > 0.5  # positive-mean track record


def test_load_trial_timeseries_roundtrip(tmp_path):
    path = tmp_path / "records.csv"
    records = _records([0.001] * 3)
    from quant_trade.trials.tracker import FIELDS

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in records:
            w.writerow(r.to_dict())
    loaded = load_trial_timeseries("t1", path)
    assert len(loaded) == 3
    assert isinstance(loaded[0], DailyTrialRecord)
    assert isinstance(Path(path), Path)
