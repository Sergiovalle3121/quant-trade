from pathlib import Path

from typer.testing import CliRunner

from quant_trade.cli import app


def test_submit_plan_requires_flags() -> None:
    runner = CliRunner()
    plan = runner.invoke(
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
    plan_dir = Path(plan.output.strip().split(": ")[-1].strip())
    result = runner.invoke(
        app,
        [
            "broker",
            "submit-plan",
            "--plan-dir",
            str(plan_dir),
            "--broker-config",
            "configs/broker/alpaca_paper.example.yaml",
        ],
    )
    assert result.exit_code != 0
