from quant_trade.campaigns.generator import generate_run_configs
from quant_trade.campaigns.models import CampaignConfig


def test_campaign_plan_generated_and_max_runs_enforced():
    cfg = CampaignConfig(
        "c",
        "C",
        "grid_search_campaign",
        ["SPY"],
        "d.csv",
        ["s"],
        {"s": {"short_window": [5, 10], "long_window": [20, 30]}},
        max_runs=3,
    )
    runs = generate_run_configs(cfg)
    assert len(runs) == 3


def test_invalid_parameter_combos_rejected():
    cfg = CampaignConfig(
        "c",
        "C",
        "grid_search_campaign",
        ["SPY"],
        "d.csv",
        ["s"],
        {"s": {"short_window": [50], "long_window": [20]}},
    )
    runs = generate_run_configs(cfg)
    assert runs == [] or all(
        r.parameters["short_window"] < r.parameters["long_window"] for r in runs
    )
