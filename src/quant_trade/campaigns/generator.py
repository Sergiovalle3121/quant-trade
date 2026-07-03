from __future__ import annotations

from itertools import product
from typing import Any

from quant_trade.campaigns.models import CampaignConfig, CampaignRunConfig


def _expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = sorted(grid)
    values = [grid[k] for k in keys]
    combos = [dict(zip(keys, item, strict=True)) for item in product(*values)]
    return [c for c in combos if _valid_parameters(c)]


def _valid_parameters(params: dict[str, Any]) -> bool:
    short = params.get("short_window")
    long = params.get("long_window")
    if short is not None and long is not None and int(short) >= int(long):
        return False
    lookback = params.get("lookback")
    return not (lookback is not None and int(lookback) <= 0)


def generate_run_configs(config: CampaignConfig) -> list[CampaignRunConfig]:
    runs: list[CampaignRunConfig] = []
    costs = config.cost_assumptions or [{}]
    for strategy in config.strategies:
        for params in _expand_grid(config.parameter_grids.get(strategy, {})):
            for cost_index, cost in enumerate(costs):
                if len(runs) >= config.max_runs:
                    return runs
                runs.append(
                    CampaignRunConfig(
                        run_id=f"run_{len(runs) + 1:04d}",
                        campaign_id=config.campaign_id,
                        mode=config.mode,
                        strategy=strategy,
                        parameters=params,
                        cost_assumptions=cost,
                        universe=config.universe,
                        data_path=config.data_path,
                        split_policy=config.split_policy,
                        benchmark=config.benchmark,
                        random_seed=config.random_seed + cost_index + len(runs),
                    )
                )
    return runs
