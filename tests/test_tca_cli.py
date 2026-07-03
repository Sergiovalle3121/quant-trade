from typer.testing import CliRunner

from quant_trade.cli import app

runner = CliRunner()

def test_tca_cli_works_offline():
    result = runner.invoke(
        app, ["tca", "run", "--config", "configs/tca/synthetic_execution_quality.yaml"]
    )
    assert result.exit_code == 0
    assert "real_money_ready=false" in result.output
