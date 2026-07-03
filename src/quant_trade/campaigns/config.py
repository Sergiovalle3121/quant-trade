from __future__ import annotations

import json
from pathlib import Path

import yaml

from quant_trade.campaigns.exceptions import CampaignError
from quant_trade.campaigns.models import CampaignConfig, GuardrailPolicy

VALID_MODES = {
    "research_strategy_campaign",
    "grid_search_campaign",
    "walk_forward_campaign",
    "robustness_campaign",
    "stress_campaign",
    "ml_baseline_campaign",
    "paper_trial_review_campaign",
}


def load_campaign_config(path: str | Path) -> CampaignConfig:
    p = Path(path)
    raw = json.loads(p.read_text()) if p.suffix == ".json" else yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise CampaignError("campaign config must be a mapping")
    config = CampaignConfig(**raw)
    validate_campaign_config(config)
    return config


def validate_campaign_config(config: CampaignConfig) -> None:
    if config.real_money_enabled:
        raise CampaignError("campaigns are research-only; real_money_enabled must be false")
    if config.mode not in VALID_MODES:
        raise CampaignError(f"unsupported campaign mode: {config.mode}")
    if not config.strategies:
        raise CampaignError("at least one strategy is required")
    if config.max_runs <= 0:
        raise CampaignError("max_runs must be positive")
    if config.ranking_policy.get("single_metric"):
        raise CampaignError("single-metric ranking is prohibited")


def guardrail_policy(config: CampaignConfig) -> GuardrailPolicy:
    return GuardrailPolicy(**config.overfitting_guardrails)


def dump_campaign_config(config: CampaignConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.__dict__, sort_keys=True), encoding="utf-8")
