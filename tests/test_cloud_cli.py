from typer.testing import CliRunner

from quant_trade.cli import app


def test_validate_config_cli():
    r = CliRunner().invoke(
        app, ["cloud", "validate-config", "--config", "configs/cloud/local_dry_run.yaml"]
    )
    assert r.exit_code == 0
    assert "dry_run" in r.output


def test_kill_status_cli():
    r = CliRunner().invoke(
        app, ["cloud", "kill-switch", "status", "--config", "configs/cloud/local_dry_run.yaml"]
    )
    assert r.exit_code == 0
