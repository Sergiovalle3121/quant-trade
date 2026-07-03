from pathlib import Path

from typer.testing import CliRunner

from quant_trade.cli import app


def test_broker_check_and_plan_and_dry_submit() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["broker", "check", "--config", "configs/broker/simulated_broker.yaml"]
    )
    assert result.exit_code == 0, result.output
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
    assert plan.exit_code == 0, plan.output
    plan_dir = Path(plan.output.strip().split(": ")[-1].strip())
    assert (plan_dir / "proposed_orders.json").exists()
    submit = runner.invoke(
        app,
        [
            "broker",
            "submit-plan",
            "--plan-dir",
            str(plan_dir),
            "--broker-config",
            "configs/broker/alpaca_paper.example.yaml",
            "--dry-run",
        ],
    )
    assert submit.exit_code == 0, submit.output
