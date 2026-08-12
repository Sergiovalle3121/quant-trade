"""Classify research that must use the sealed crypto workflow.

The legacy research and promotion paths predate venue-specific crypto costs,
causal membership and terminal-event handling.  A strategy name is not a
security boundary: the same model can be renamed or applied to a crypto CSV.
This module therefore combines explicit metadata with instrument and dataset
identity.  Positive evidence of crypto always routes to the sealed workflow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

CRYPTO_STRATEGIES = frozenset(
    {
        "crypto_capacity_illiquidity",
        "crypto_death_avoidance",
        "crypto_annual_equal_weight_rebalance",
        "crypto_survival_duration",
    }
)
CRYPTO_VENUES = frozenset({"bybit", "binance", "coinbase", "kraken", "okx"})
_CRYPTO_DATASET_MARKERS = ("crypto", "bybit", "binance", "coinbase", "kraken", "okx")


def _instrument_is_crypto(value: object) -> bool:
    instrument = str(value).strip().upper()
    if not instrument:
        return False
    if instrument.startswith("CMC:"):
        return True
    return any(
        instrument.endswith(suffix)
        for suffix in (
            "-USD",
            "/USD",
            "-USDT",
            "/USDT",
            "USDT",
            "-USDC",
            "/USDC",
            "USDC",
        )
    )


def requires_sealed_crypto_route(
    *,
    strategy: object = "",
    asset_class: object = "",
    venue: object = "",
    provider: object = "",
    dataset_id: object = "",
    data_path: object = "",
    instruments: Iterable[object] = (),
    tags: Iterable[object] = (),
) -> bool:
    """Return whether a payload has any positive crypto identity.

    Missing metadata is not interpreted as non-crypto.  Productive callers
    must additionally inspect the loaded panel before using a legacy engine.
    """
    strategy_name = str(strategy).strip().lower()
    if strategy_name in CRYPTO_STRATEGIES or strategy_name.startswith("crypto_"):
        return True
    if str(asset_class).strip().lower() in {"crypto", "digital_asset", "digital_assets"}:
        return True
    if str(venue).strip().lower() in CRYPTO_VENUES:
        return True
    joined_identity = " ".join(
        (
            str(dataset_id).lower(),
            str(data_path).lower(),
            str(provider).lower(),
            *(str(tag).lower() for tag in tags),
        )
    )
    if any(marker in joined_identity for marker in _CRYPTO_DATASET_MARKERS):
        return True
    return any(_instrument_is_crypto(instrument) for instrument in instruments)


def panel_requires_sealed_crypto_route(panel: pd.DataFrame) -> bool:
    """Inspect a loaded canonical panel before a legacy engine can consume it."""
    if panel.empty:
        return False
    for name in ("asset_class", "venue", "dataset_id", "provider"):
        if name in panel.columns and any(
            requires_sealed_crypto_route(**{name: value}) for value in panel[name].dropna().unique()
        ):
            return True
    for name in ("instrument_id", "symbol", "venue_symbol"):
        if name in panel.columns and any(_instrument_is_crypto(value) for value in panel[name]):
            return True
    return False


def mapping_requires_sealed_crypto_route(payload: Mapping[str, Any]) -> bool:
    """Classify a config or result mapping without trusting one mutable field."""
    dataset = payload.get("dataset_binding")
    dataset = dataset if isinstance(dataset, Mapping) else {}
    universe = payload.get("universe", payload.get("symbols", ()))
    if isinstance(universe, Mapping):
        universe = universe.get("symbols", universe.get("instruments", ()))
    if isinstance(universe, str) or not isinstance(universe, Iterable):
        universe = (universe,)
    tags = payload.get("tags", ())
    if isinstance(tags, str) or not isinstance(tags, Iterable):
        tags = (tags,)
    return requires_sealed_crypto_route(
        strategy=payload.get("strategy", payload.get("strategy_name", "")),
        asset_class=payload.get("asset_class", dataset.get("asset_class", "")),
        venue=payload.get("venue", dataset.get("venue", "")),
        provider=payload.get("provider", dataset.get("provider", "")),
        dataset_id=payload.get("dataset_id", dataset.get("dataset_id", "")),
        data_path=payload.get("data_path", dataset.get("data_path", "")),
        instruments=universe,
        tags=tags,
    )


def candidate_requires_sealed_crypto_route(candidate: Any) -> bool:
    """Classify a legacy CandidateStrategy without changing its persisted schema."""
    return requires_sealed_crypto_route(
        strategy=getattr(candidate, "strategy_name", ""),
        dataset_id=getattr(candidate, "research_run_dir", ""),
        instruments=getattr(candidate, "universe", ()),
        tags=getattr(candidate, "tags", ()),
    )


def path_looks_crypto(path: str | Path) -> bool:
    """Small helper for callers that have not loaded dataset bytes yet."""
    return requires_sealed_crypto_route(data_path=str(path))


__all__ = [
    "CRYPTO_STRATEGIES",
    "candidate_requires_sealed_crypto_route",
    "mapping_requires_sealed_crypto_route",
    "panel_requires_sealed_crypto_route",
    "path_looks_crypto",
    "requires_sealed_crypto_route",
]
