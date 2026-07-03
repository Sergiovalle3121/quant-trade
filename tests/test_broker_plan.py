from pathlib import Path

from typer.testing import CliRunner

from quant_trade.cli import app


def test_broker_plan_writes_artifacts() -> None:
    result = CliRunner().invoke(
        app,
        [
            "broker",
            "plan",
            "--paper-config",
            "configs/paper/ts_momentum_synthetic_paper.yaml",
            "--broker-config",
            "configs/broker/alpaca_paper.example.yaml",
        ],
    )
    assert result.exit_code == 0, result.output
    out = Path(result.output.strip().split(": ")[-1].strip())
    for name in [
        "broker_config_used.yaml",
        "proposed_orders.json",
        "proposed_orders.csv",
        "risk_checks.json",
        "dry_run_results.json",
        "plan_summary.md",
    ]:
        assert (out / name).exists()
