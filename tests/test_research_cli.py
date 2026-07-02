from typer.testing import CliRunner

from quant_trade.cli import app


def test_research_cli_list():
    r = CliRunner().invoke(app, ["research", "list-strategies"])
    assert r.exit_code == 0 and "time_series_momentum" in r.output
