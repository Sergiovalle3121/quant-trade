from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from quant_trade.campaigns.aggregator import write_ranking, write_results, write_run_index
from quant_trade.campaigns.config import dump_campaign_config, guardrail_policy
from quant_trade.campaigns.dashboard import write_dashboard
from quant_trade.campaigns.generator import generate_run_configs
from quant_trade.campaigns.guardrails import rejection_reason
from quant_trade.campaigns.models import CampaignConfig, CampaignResult, CampaignRunConfig
from quant_trade.campaigns.ranking import rank_candidates
from quant_trade.campaigns.reports import write_campaign_report


def plan_campaign(config: CampaignConfig) -> list[CampaignRunConfig]:
    return generate_run_configs(config)


def run_campaign(config: CampaignConfig) -> Path:
    runs = plan_campaign(config)
    campaign_dir = Path(config.output_dir) / config.campaign_id / "latest"
    generated_dir = campaign_dir / "generated_configs"
    generated_dir.mkdir(parents=True, exist_ok=True)
    dump_campaign_config(config, campaign_dir / "campaign_config_used.yaml")
    for run in runs:
        (generated_dir / f"{run.run_id}.yaml").write_text(
            yaml.safe_dump(asdict(run)), encoding="utf-8"
        )
    write_run_index(campaign_dir / "run_index.csv", [asdict(r) for r in runs])
    policy = guardrail_policy(config)
    results = [_simulate_run(r) for r in runs]
    results = [
        CampaignResult(
            r.run_id,
            r.strategy,
            r.metrics,
            r.artifacts_complete,
            rejection_reason(r, policy),
        )
        for r in results
    ]
    ranked = rank_candidates(results, policy)
    write_results(campaign_dir / "run_results.csv", results)
    write_ranking(campaign_dir / "ranking.csv", ranked)
    write_ranking(campaign_dir / "rejected.csv", [r for r in ranked if r.rejected])
    write_campaign_report(campaign_dir / "campaign_summary.md", config, ranked)
    write_dashboard(campaign_dir / "dashboard" / "index.html", ranked)
    return campaign_dir


def _simulate_run(run: CampaignRunConfig) -> CampaignResult:
    # Deterministic offline synthetic metrics; intentionally conservative and cost-aware.
    key = yaml.safe_dump(asdict(run), sort_keys=True)
    digest = hashlib.sha256(key.encode()).hexdigest()
    base = int(digest[:8], 16) / 0xFFFFFFFF
    cost_bps = float(run.cost_assumptions.get("slippage_bps", 0)) + float(
        run.cost_assumptions.get("spread_bps", 0)
    )
    param_count = len(run.parameters)
    train_return = 0.04 + 0.20 * base + 0.01 * param_count
    oos_return = max(-0.20, train_return - 0.04 - 0.001 * cost_bps - 0.015 * param_count)
    metrics: dict[str, Any] = {
        "train_return": train_return,
        "oos_return": oos_return,
        "benchmark_return": 0.06,
        "cost_sensitivity": -0.0005 * cost_bps,
        "stress_return": oos_return - 0.05,
        "max_drawdown": min(0.5, 0.08 + 0.20 * (1 - base) + 0.002 * cost_bps),
        "turnover": 1.0 + 0.4 * param_count + 0.02 * cost_bps,
        "trade_count": 12 + int(30 * base),
        "operational_score": 0.8,
    }
    return CampaignResult(run.run_id, run.strategy, metrics)
