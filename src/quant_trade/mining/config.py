"""YAML configuration for offline mining profitability evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_trade.mining.models import MiningMarketSnapshot, MiningPolicy, MiningRig


class MiningConfigError(ValueError):
    """Raised when a mining evaluation configuration is malformed."""


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MiningConfigError(f"{name} must be a mapping")
    return dict(value)


def _items(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise MiningConfigError(f"{name} must be a non-empty list")
    return [_mapping(item, f"{name} item") for item in value]


def load_mining_config(
    path: Path,
) -> tuple[tuple[MiningRig, ...], tuple[MiningMarketSnapshot, ...], MiningPolicy]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = _mapping(payload, "mining config")
    try:
        rigs = tuple(MiningRig(**item) for item in _items(root.get("rigs"), "rigs"))
        markets = tuple(
            MiningMarketSnapshot(**item) for item in _items(root.get("markets"), "markets")
        )
        policy = MiningPolicy(**_mapping(root.get("policy"), "policy"))
    except (TypeError, ValueError) as exc:
        raise MiningConfigError(str(exc)) from exc
    return rigs, markets, policy

