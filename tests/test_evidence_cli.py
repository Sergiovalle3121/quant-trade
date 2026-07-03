import json

from typer.testing import CliRunner

from quant_trade.cli import app


def test_evidence_cli_offline(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("weights: {}\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"database_path: {tmp_path / 'db.sqlite'}\n"
        f"output_dir: {tmp_path / 'out'}\n"
        f"scorecard_policy_path: {policy}\n",
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "research.json").write_text(
        json.dumps({"strategy_id": "s1", "note": "drawdown"}), encoding="utf-8"
    )
    runner = CliRunner()
    assert runner.invoke(app, ["evidence", "init", "--config", str(config)]).exit_code == 0
    assert (
        runner.invoke(
            app, ["evidence", "ingest", "--config", str(config), "--path", str(outputs)]
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app, ["evidence", "search", "--config", str(config), "--query", "drawdown"]
    )
    assert result.exit_code == 0
    assert "s1" in result.output
