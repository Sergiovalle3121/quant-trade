from typer.testing import CliRunner

from quant_trade.cli import app


def test_readiness_cli_works_offline(tmp_path):
    cfg = tmp_path / "dossier.yaml"
    cfg.write_text(
        "run_id: cli\noutput_root: '"
        + str(tmp_path)
        + "'\nsecurity_controls: {security_scan_pass: true}\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(app, ["readiness", "dossier", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "real_money_ready=false" in res.output
