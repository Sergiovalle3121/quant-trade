from typer.testing import CliRunner

from quant_trade.cli import app


def test_ml_cli_features_offline(tmp_path):
    cfg = tmp_path / "ml.yaml"
    cfg.write_text(f"""
run_id: cli_run
output_root: {tmp_path}
provider: synthetic
symbols: [AAA, BBB]
start: '2020-01-01'
end: '2020-03-01'
interval: 1d
model: simple_rank_model
real_money_ready: false
""".strip())
    result = CliRunner().invoke(app, ["ml", "features", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli_run" / "features.csv").exists()
