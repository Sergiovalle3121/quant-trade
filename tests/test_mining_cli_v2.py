"""CLI tests for the mining V2 projection and hashprice commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.mining.cli import mining_app

runner = CliRunner()
CONFIG = "configs/mining/cashflow_projection_example.yaml"


def test_project_command_uses_dynamic_cashflow(tmp_path):
    out = tmp_path / "proj.json"
    result = runner.invoke(mining_app, ["project", "--config", CONFIG, "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "Dynamic NPV" in result.output
    assert "Overstatement removed" in result.output
    assert "authorized_to_start_miner=false" in result.output
    payload = json.loads(out.read_text())
    # the dynamic NPV must differ from the V1 constant-flow NPV (difficulty grows)
    assert payload["npv_usd"] != payload["constant_flow_npv_usd"]
    assert payload["npv_overstatement_vs_constant"] > 0
    assert payload["authorized_to_start_miner"] is False
    assert "monthly_series" in payload


def test_project_command_can_include_daily_series(tmp_path):
    out = tmp_path / "proj.json"
    result = runner.invoke(
        mining_app, ["project", "--config", CONFIG, "--output", str(out), "--include-daily"]
    )
    assert result.exit_code == 0
    payload = json.loads(out.read_text())
    assert len(payload["daily_series"]) == payload["horizon_days"]


def test_hashprice_command_flags_divergence():
    result = runner.invoke(mining_app, ["hashprice", "--config", CONFIG])
    assert result.exit_code == 0
    assert "bottom-up" in result.output
    # the example's direct quote diverges >10% from bottom-up
    assert "ALERT" in result.output


def test_hashprice_no_alert_with_loose_tolerance():
    result = runner.invoke(
        mining_app, ["hashprice", "--config", CONFIG, "--max-relative-divergence", "0.5"]
    )
    assert result.exit_code == 0
    assert "methods agree within tolerance" in result.output


def test_project_scenarios_command_reports_npv_band(tmp_path):
    out = tmp_path / "scenarios.json"
    result = runner.invoke(
        mining_app, ["project-scenarios", "--config", CONFIG, "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "NPV band" in result.output
    payload = json.loads(out.read_text())
    assert {"scenarios", "npv_band"} <= payload.keys()
    band = payload["npv_band"]
    assert band["min_npv_usd"] <= band["median_npv_usd"] <= band["max_npv_usd"]
    assert payload["authorized_to_start_miner"] is False
