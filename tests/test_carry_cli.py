"""CLI test for the cash-and-carry research command (offline; no orders)."""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from quant_trade.carry.cli import carry_app

runner = CliRunner()
CONFIG = "configs/carry/cash_and_carry_synthetic.yaml"


def test_carry_research_command_is_not_run_on_synthetic(tmp_path):
    result = runner.invoke(
        carry_app, ["research", "--config", CONFIG, "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "NOT-RUN" in result.output
    assert "REAL DATA REQUIRED" in result.output
    assert "no orders were placed" in result.output
    # artifacts written
    payload = yaml.safe_load((tmp_path / "results.json").read_text())
    assert payload["decision"] == "NOT-RUN"
    assert (tmp_path / "net_returns.csv").exists()


def test_carry_research_reports_metrics(tmp_path):
    result = runner.invoke(
        carry_app, ["research", "--config", CONFIG, "--output", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "Total return" in result.output
    assert "Walk-forward windows" in result.output
