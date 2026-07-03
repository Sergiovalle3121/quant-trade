from typer.testing import CliRunner

from quant_trade.cli import app


def test_campaign_cli_plan_offline():
    r = CliRunner().invoke(
        app,
        [
            "campaigns",
            "plan",
            "--config",
            "configs/campaigns/daily_etf_research_campaign.yaml",
        ],
    )
    assert r.exit_code == 0
    assert "Campaign plan generated" in r.output


def test_campaign_cli_run_offline(tmp_path):
    cfg = tmp_path / "campaign.yaml"
    cfg.write_text(
        f"""
campaign_id: cli_test
campaign_name: CLI Test
mode: grid_search_campaign
universe: [SPY]
data_path: synthetic.csv
strategies: [sma_crossover]
parameter_grids:
  sma_crossover:
    short_window: [5]
    long_window: [20]
cost_assumptions:
  - slippage_bps: 1
    spread_bps: 1
split_policy:
  method: chronological
  train_fraction: 0.7
benchmark: SPY
max_runs: 1
output_dir: "{tmp_path}"
real_money_enabled: false
""",
        encoding="utf-8",
    )
    r = CliRunner().invoke(app, ["campaigns", "run", "--config", str(cfg)])
    assert r.exit_code == 0
    assert "Campaign complete" in r.output
