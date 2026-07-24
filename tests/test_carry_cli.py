"""CLI test for the cash-and-carry research command (offline; no orders)."""

from __future__ import annotations

from typer.testing import CliRunner

from quant_trade.carry.cli import carry_app

runner = CliRunner()
CONFIG = "configs/carry/cash_and_carry_synthetic.yaml"


def test_carry_research_command_is_not_run_on_synthetic(tmp_path):
    result = runner.invoke(
        carry_app, ["research", "--config", CONFIG, "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "NOT_RUN_INSUFFICIENT_REAL_DATA" in result.output
    assert "REAL DATA REQUIRED" in result.output
    assert "no orders were placed" in result.output
    # artifacts written — and results.json is REAL json now
    import json

    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["decision"] == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    assert (tmp_path / "net_returns.csv").exists()
    assert (tmp_path / "dataset_manifest.json").exists()


def test_carry_research_reports_metrics(tmp_path):
    result = runner.invoke(
        carry_app, ["research", "--config", CONFIG, "--output", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "Total return" in result.output
    assert "Walk-forward windows" in result.output


def test_carry_scenarios_command_runs():
    result = runner.invoke(carry_app, ["scenarios", "--config", CONFIG])
    assert result.exit_code == 0, result.output
    assert "Carry stress scenarios" in result.output
    # the shocked scenarios should appear
    for name in ("funding_sign_flip", "depeg", "exchange_outage", "extreme_spread"):
        assert name in result.output
    assert "no orders were placed" in result.output
