"""YAML configuration for offline mining profitability evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_trade.mining.cashflow import ProjectionAssumptions
from quant_trade.mining.market import MiningMarketData
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


def _coerce_scientific(mapping: dict[str, Any]) -> dict[str, Any]:
    """Coerce string values that are really numbers (YAML 1.1 parses ``2.0e14``
    without an exponent sign as a string). Non-numeric strings are left as-is."""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, str):
            try:
                out[key] = float(value)
                continue
            except ValueError:
                pass
        out[key] = value
    return out


def load_projection_config(
    path: Path,
) -> tuple[MiningRig, MiningMarketData, ProjectionAssumptions]:
    """Load a dynamic cash-flow projection config: rig + market + assumptions."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = _mapping(payload, "projection config")
    assumptions_raw = dict(_mapping(root.get("assumptions", {}), "assumptions"))
    # YAML lists -> tuples for the frozen dataclass fields.
    if "halving_day_indices" in assumptions_raw:
        assumptions_raw["halving_day_indices"] = tuple(
            int(d) for d in assumptions_raw["halving_day_indices"]
        )
    if "capex_events" in assumptions_raw:
        assumptions_raw["capex_events"] = tuple(
            (int(day), float(amount)) for day, amount in assumptions_raw["capex_events"]
        )
    try:
        rig = MiningRig(**_coerce_scientific(_mapping(root.get("rig"), "rig")))
        market = MiningMarketData(**_coerce_scientific(_mapping(root.get("market"), "market")))
        assumptions = ProjectionAssumptions(**assumptions_raw)
    except (TypeError, ValueError) as exc:
        raise MiningConfigError(str(exc)) from exc
    if rig.algorithm.casefold() != market.algorithm.casefold():
        raise MiningConfigError("rig and market algorithms must match")
    return rig, market, assumptions

