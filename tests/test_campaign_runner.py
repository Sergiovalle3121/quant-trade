from quant_trade.campaigns.config import load_campaign_config
from quant_trade.campaigns.runner import run_campaign


def test_campaign_run_writes_artifacts(tmp_path):
    cfg = load_campaign_config("configs/campaigns/daily_etf_research_campaign.yaml")
    cfg.output_dir = str(tmp_path)
    cfg.max_runs = 2
    out = run_campaign(cfg)
    assert (out / "campaign_config_used.yaml").exists()
    assert (out / "generated_configs").exists()
    assert (out / "run_index.csv").exists()
    assert (out / "run_results.csv").exists()
    assert (out / "ranking.csv").exists()
    assert (out / "rejected.csv").exists()
    assert (out / "campaign_summary.md").exists()
    assert (out / "dashboard" / "index.html").exists()
