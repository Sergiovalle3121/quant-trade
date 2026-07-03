from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def configured_paths(config: dict[str, Any], key: str, default: list[str]) -> list[Path]:
    return [Path(p) for p in config.get(key, default)]
