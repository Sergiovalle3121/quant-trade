"""Tests for the trial ledger, results.json contract, and statistical gates."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.ledger import append_trial, ledger_stats, read_trials
from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment
from quant_trade.research.selection import run_selection, select_candidates_from_outputs
from quant_trade.research.splits import chronological_train_test_split, walk_forward_splits


def _panel(n: int = 320, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    rows = []
    for sym, drift in [("AAA", 0.0012), ("BBB", 0.0008)]:
        close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
        open_ = np.concatenate([[100.0], close[:-1]])
        for i, ts in enumerate(dates):
            o, c = open_[i], close[i]
            rows.append(
                {
                    "timestamp": ts,
                    "symbol": sym,
                    "open": o,
                    "high": max(o, c) * 1.001,
                    "low": min(o, c) * 0.999,
                    "close": c,
                    "volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _run_research(tmp_path, data_path, name="ledger_test"):
    return run_multi_asset_research_experiment(
        {
            "mode": "multi_asset_research",
            "experiment_name": name,
            "data_path": str(data_path),
            "strategy": "time_series_momentum",
            "strategy_params": {"lookback_days": 21, "rebalance_frequency": "weekly"},
            "initial_cash": 100_000,
            "costs": {"percentage_commission": 0.0005},
            "robustness": {"run_cost_sensitivity": True, "run_subperiod_analysis": True},
            "output_dir": str(tmp_path / "outputs"),
        }
    )


def test_ledger_append_read_and_stats(tmp_path):
    assert read_trials(tmp_path) == []
    append_trial(tmp_path, {"test_sharpe_per_period": 0.05})
    append_trial(tmp_path, {"test_sharpe_per_period": 0.10})
    append_trial(tmp_path, {"other": 1})
    trials = read_trials(tmp_path)
    assert len(trials) == 3
    assert all("recorded_at_utc" in t for t in trials)
    n, variance = ledger_stats(tmp_path)
    assert n == 3
    assert variance == pytest.approx(np.var([0.05, 0.10], ddof=1))


def test_runner_emits_results_json_and_ledger_entry(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    result = _run_research(tmp_path, data_path)
    run_dir = tmp_path / "outputs"
    results_files = list(run_dir.rglob("results.json"))
    assert len(results_files) == 1
    payload = json.loads(results_files[0].read_text())
    tm = payload["test_metrics"]
    for key in ("sharpe", "turnover", "trade_count", "psr", "sharpe_per_period",
                "observations", "skewness", "kurtosis"):
        assert key in tm, f"results.json test_metrics missing {key}"
    assert payload["robustness"]["cost_sensitivity_pass"] in (True, False)
    assert payload["robustness"]["subperiod_pass"] in (True, False)
    assert payload["dataset_binding"]["data_sha256"]
    trials = read_trials(run_dir)
    assert len(trials) == 1
    assert trials[0]["source"] == "multi_asset_research"
    assert result["test_metrics"]["sharpe"] is not None


def test_selection_consumes_runner_output_end_to_end(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    _run_research(tmp_path, data_path)
    outputs = tmp_path / "outputs"
    # permissive criteria: the wiring (not the strategy quality) is under test
    criteria = SelectionCriteria(
        min_test_sharpe=-10.0,
        min_excess_return=-10.0,
        max_test_drawdown=1.0,
        max_turnover=1e9,
        require_beats_benchmark=False,
        require_cost_sensitivity_pass=False,
        min_test_months=0,
        max_train_test_sharpe_gap=1e9,
    )
    candidates = select_candidates_from_outputs(outputs, criteria)
    assert len(candidates) == 1
    out = run_selection(outputs, criteria)
    assert (out / "candidates.json").exists()


def test_statistical_gates_reject_thin_or_unproven_evidence(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    _run_research(tmp_path, data_path)
    outputs = tmp_path / "outputs"
    base = dict(
        min_test_sharpe=-10.0,
        min_excess_return=-10.0,
        max_test_drawdown=1.0,
        max_turnover=1e9,
        require_beats_benchmark=False,
        require_cost_sensitivity_pass=False,
        min_test_months=0,
        max_train_test_sharpe_gap=1e9,
    )
    # trade-count gate
    starved = SelectionCriteria(**base, min_trade_count=10_000)
    assert select_candidates_from_outputs(outputs, starved) == []
    # PSR gate at an impossible threshold
    psr_gate = SelectionCriteria(**base, min_probabilistic_sharpe=0.999999)
    assert select_candidates_from_outputs(outputs, psr_gate) == []
    # DSR gate: inflate the ledger with hundreds of high-variance trials so
    # the expected-max-Sharpe threshold dwarfs the candidate
    rng = np.random.default_rng(1)
    for _ in range(400):
        append_trial(outputs, {"test_sharpe_per_period": float(rng.normal(0, 0.4))})
    deflated = SelectionCriteria(**base, require_deflated_sharpe=True, min_deflated_sharpe=0.9)
    assert select_candidates_from_outputs(outputs, deflated) == []


def test_deflated_gate_requires_ledger(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    _run_research(tmp_path, data_path)
    outputs = tmp_path / "outputs"
    (outputs / "trial_ledger.jsonl").unlink()  # simulate a run without a ledger
    criteria = SelectionCriteria(
        min_test_sharpe=-10.0,
        min_excess_return=-10.0,
        max_test_drawdown=1.0,
        max_turnover=1e9,
        require_beats_benchmark=False,
        require_cost_sensitivity_pass=False,
        min_test_months=0,
        max_train_test_sharpe_gap=1e9,
        require_deflated_sharpe=True,
    )
    assert select_candidates_from_outputs(outputs, criteria) == []


def test_embargo_removes_boundary_bars():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "close": range(100),
        }
    )
    train, test = chronological_train_test_split(frame, 0.7, embargo_bars=5)
    assert len(train) == 70
    assert len(test) == 25
    gap = (test["timestamp"].min() - train["timestamp"].max()).days
    assert gap == 6  # 5 embargoed bars + 1 normal step
    windows = walk_forward_splits(frame, 30, 10, 10, embargo_bars=5)
    for train_w, test_w in windows:
        assert (test_w["timestamp"].min() - train_w["timestamp"].max()).days == 6
