from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .exceptions import AllocationConfigError
from .models import AllocationCandidate, AllocationPolicy


def load_yaml(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise AllocationConfigError(f"config not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_policy(path: Path | str) -> AllocationPolicy:
    raw = load_yaml(path)
    return AllocationPolicy.from_dict(raw.get("policy", raw))


def load_allocation_config(path: Path | str) -> dict[str, Any]:
    cfg = load_yaml(path)
    if "policy" in cfg:
        cfg["policy"] = AllocationPolicy.from_dict(cfg["policy"])
    elif "policy_path" in cfg:
        cfg["policy"] = load_policy(cfg["policy_path"])
    else:
        raise AllocationConfigError("allocation config requires policy or policy_path")
    cfg.setdefault("registry_path", "configs/allocation/allocation_registry.yaml")
    cfg.setdefault("output_root", "outputs/allocation")
    cfg.setdefault("allocator", "conservative_blend")
    return cfg


def load_registry(path: Path | str) -> list[AllocationCandidate]:
    raw = load_yaml(path)
    return [AllocationCandidate.from_dict(x) for x in raw.get("candidates", [])]
