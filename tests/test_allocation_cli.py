from typer.testing import CliRunner

from quant_trade.cli import app


def test_allocation_cli_list_offline():
    result = CliRunner().invoke(
        app,
        [
            "allocation",
            "list-candidates",
            "--config",
            "configs/allocation/conservative_portfolio.yaml",
        ],
    )
    assert result.exit_code == 0
    assert "real_money_ready=false" in result.output


def test_allocation_cli_run_offline():
    result = CliRunner().invoke(
        app, ["allocation", "run", "--config", "configs/allocation/conservative_portfolio.yaml"]
    )
    assert result.exit_code == 0
    assert "real_money_ready=false" in result.output
