"""Research campaign automation package (offline and research-only)."""

from quant_trade.campaigns.config import load_campaign_config
from quant_trade.campaigns.runner import plan_campaign, run_campaign

__all__ = ["load_campaign_config", "plan_campaign", "run_campaign"]
