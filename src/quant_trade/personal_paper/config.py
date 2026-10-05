from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path
from typing import Any

import yaml

UNIVERSE = ("GLD", "IWM", "QQQ", "SPY", "TLT")
PORTFOLIOS: dict[str, dict[str, Any]] = {
    "inverse_volatility": {
        "volatility_window": 63,
        "rebalance_frequency": "monthly",
        "max_weight_per_asset": 0.35,
    },
    "vol_targeted_equal_weight": {
        "volatility_window": 63,
        "target_volatility": 0.10,
        "periods_per_year": 252,
        "rebalance_frequency": "monthly",
        "max_weight_per_asset": 0.25,
    },
    "equal_weight_quarterly": {"max_weight_per_asset": 0.25},
}
PROSPECTIVE_RUNTIME = {
    "numpy": "2.2.6",
    "pandas": "3.0.3",
    "PyYAML": "6.0.3",
    "yfinance": "1.5.1",
    "exchange_calendars": "4.13.2",
    "korean_lunar_calendar": "0.4.0",
    "pyluach": "2.3.0",
    "toolz": "1.1.0",
    "tzdata": "2026.5",
}


class PersonalPaperError(RuntimeError):
    """A paper input or persisted record failed a conservative check."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for name in PROSPECTIVE_RUNTIME:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "UNAVAILABLE"
    return versions


def validate_runtime(config: dict[str, Any], mode: str) -> dict[str, str]:
    versions = runtime_versions()
    if mode == "prospective" and config["data_kind"] == "market":
        mismatches = {
            name: {"expected": expected, "observed": versions[name]}
            for name, expected in PROSPECTIVE_RUNTIME.items()
            if versions[name] != expected
        }
        if mismatches:
            raise PersonalPaperError(
                f"market prospective runtime differs from frozen protocol: {canonical(mismatches)}"
            )
    return versions


def load_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "experiment_id",
        "capital_mxn",
        "monthly_host_budget_mxn",
        "data_kind",
        "price_basis",
        "max_drawdown",
        "max_daily_loss",
        "costs",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise PersonalPaperError(f"config must contain exactly {sorted(required)}")
    if raw["schema_version"] != 1 or not str(raw["experiment_id"]).strip():
        raise PersonalPaperError("invalid schema or experiment_id")
    for key in ("capital_mxn", "monthly_host_budget_mxn", "max_drawdown", "max_daily_loss"):
        if isinstance(raw[key], bool) or not math.isfinite(float(raw[key])) or float(raw[key]) <= 0:
            raise PersonalPaperError(f"{key} must be finite and positive")
    if raw["capital_mxn"] > 20000 or raw["monthly_host_budget_mxn"] > 500:
        raise PersonalPaperError("owner's capital/hosting ceilings are 20,000/500 MXN")
    if raw["max_drawdown"] > 0.05 or raw["max_daily_loss"] > 0.02:
        raise PersonalPaperError("drawdown/daily-loss ceilings are 5%/2%")
    if raw["data_kind"] not in {"synthetic", "market"}:
        raise PersonalPaperError("data_kind must be synthetic or market")
    if raw["price_basis"] not in {"adjusted_total_return", "raw_with_actions"}:
        raise PersonalPaperError("price_basis must declare corporate-action treatment")
    if raw["costs"] != {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2}:
        raise PersonalPaperError("v1 fixes declared costs to commission/slippage/spread 5/5/2 bps")
    return raw


def execution_code_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "personal_paper" / name
        for name in ("config.py", "store.py", "engine.py", "actions.py", "fetch.py", "worker.py")
    ]
    paths += [
        root / name
        for name in (
            "research/signals/allocation.py",
            "research/signals/base.py",
            "research/strategy_registry.py",
            "data/panel.py",
            "execution/bar_model.py",
        )
    ]
    return digest({str(p.relative_to(root)): file_hash(p) for p in paths})
