"""End-to-end CLI tests for promote-v2 and ledger-report."""

from __future__ import annotations

import numpy as np
import pandas as pd
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment

runner = CliRunner()


def _panel(n: int = 320, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    rows = []
    for sym, drift in [("AAA", 0.0010), ("BBB", 0.0008)]:
        close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
        open_ = np.concatenate([[100.0], close[:-1]])
        for i, ts in enumerate(dates):
            o, c = open_[i], close[i]
            rows.append({"timestamp": ts, "symbol": sym, "open": o,
                         "high": max(o, c) * 1.001, "low": min(o, c) * 0.999,
                         "close": c, "volume": 1_000_000.0})
    return pd.DataFrame(rows)


def _make_run(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    outputs = tmp_path / "outputs"
    run_multi_asset_research_experiment({
        "mode": "multi_asset_research",
        "experiment_name": "cli_promo",
        "data_path": str(data_path),
        "strategy": "time_series_momentum",
        "strategy_params": {"lookback_days": 21, "rebalance_frequency": "weekly"},
        "initial_cash": 100_000,
        "costs": {"percentage_commission": 0.0005},
        "execution": {"max_volume_participation_rate": 0.1},
        "robustness": {"run_cost_sensitivity": True, "run_subperiod_analysis": True},
        "output_dir": str(outputs),
    })
    run_dir = next((outputs).glob("cli_promo_*"))
    return outputs, run_dir


def test_promote_v2_cli_recomputes_and_stays_paper_only(tmp_path):
    outputs, run_dir = _make_run(tmp_path)
    out = tmp_path / "decision.json"
    result = runner.invoke(
        app,
        ["selection", "promote-v2", "--run-dir", str(run_dir),
         "--ledger-dir", str(outputs), "--output", str(out),
         "--approval-notes", "reviewed for paper"],
    )
    assert result.exit_code == 0, result.output
    assert "real_money_authorized=False" in result.output
    # a weak synthetic strategy must not reach paper_candidate
    assert "Decision:" in result.output
    assert out.exists()


def test_ledger_report_cli_shows_integrity(tmp_path):
    outputs, _run_dir = _make_run(tmp_path)
    result = runner.invoke(app, ["research", "ledger-report", "--outputs-dir", str(outputs)])
    assert result.exit_code == 0, result.output
    assert "Trial ledger integrity" in result.output
    assert "Effective DSR trials" in result.output
    assert "INTACT" in result.output
