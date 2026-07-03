from typer.testing import CliRunner

from quant_trade.cli import app


def test_stress_cli_list_scenarios_offline():
    result = CliRunner().invoke(
        app, ["stress", "list-scenarios", "--config", "configs/stress/equity_etf_scenarios.yaml"]
    )
    assert result.exit_code == 0
    assert "spy_one_day_crash" in result.output


def test_stress_cli_run_offline(tmp_path):
    config = tmp_path / "stress.yaml"
    config.write_text(
        "policy_file: configs/stress/stress_policy_conservative.yaml\n"
        "scenario_file: configs/stress/equity_etf_scenarios.yaml\n"
        f"output_dir: {tmp_path}\n"
        "symbols: [SPY, TLT, GLD]\n"
        "real_money_ready: false\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["stress", "run", "--config", str(config)])
    assert result.exit_code == 0
    assert "real_money_ready=false" in result.output
