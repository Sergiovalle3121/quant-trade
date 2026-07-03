"""Configuration loading for the simulation-only stress lab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_trade.stress.exceptions import StressConfigError
from quant_trade.stress.models import StressPolicy, StressScenario


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    raise StressConfigError("required_symbols must be a list")


def load_stress_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise StressConfigError("stress config must be a mapping")
    return payload


def load_stress_policy(path: Path) -> StressPolicy:
    payload = load_stress_config(path)
    policy_raw = payload.get("policy", payload)
    if not isinstance(policy_raw, dict):
        raise StressConfigError("policy must be a mapping")
    policy_raw = dict(policy_raw)
    policy_raw["required_symbols"] = _as_tuple(policy_raw.get("required_symbols"))
    policy_raw["real_money_ready"] = False
    return StressPolicy(**policy_raw)


def load_stress_scenarios(path: Path) -> tuple[StressScenario, ...]:
    payload = load_stress_config(path)
    raw_items = payload.get("scenarios", [])
    if not isinstance(raw_items, list):
        raise StressConfigError("scenarios must be a list")
    scenarios: list[StressScenario] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise StressConfigError("each scenario must be a mapping")
        item = dict(raw)
        item["required_symbols"] = _as_tuple(item.get("required_symbols"))
        scenarios.append(StressScenario(**item))
    return tuple(scenarios)


def load_suite_config(
    path: Path,
) -> tuple[StressPolicy, tuple[StressScenario, ...], dict[str, Any]]:
    payload = load_stress_config(path)
    policy_file = payload.get("policy_file")
    scenario_file = payload.get("scenario_file")
    policy = load_stress_policy(Path(policy_file)) if policy_file else load_stress_policy(path)
    scenarios = (
        load_stress_scenarios(Path(scenario_file)) if scenario_file else load_stress_scenarios(path)
    )
    return policy, scenarios, payload
