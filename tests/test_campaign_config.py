import pytest

from quant_trade.campaigns.config import load_campaign_config, validate_campaign_config
from quant_trade.campaigns.exceptions import CampaignError
from quant_trade.campaigns.models import CampaignConfig


def test_campaign_config_loads():
    cfg = load_campaign_config("configs/campaigns/daily_etf_research_campaign.yaml")
    assert cfg.real_money_enabled is False
    assert cfg.allow_parallel is False


def test_real_money_rejected():
    cfg = CampaignConfig(
        "x",
        "x",
        "grid_search_campaign",
        ["SPY"],
        "data.csv",
        ["s"],
        real_money_enabled=True,
    )
    with pytest.raises(CampaignError):
        validate_campaign_config(cfg)
