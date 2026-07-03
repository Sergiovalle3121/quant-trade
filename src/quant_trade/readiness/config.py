from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def output_dir(config: dict[str, Any]) -> Path:
    run_id = str(config.get("run_id", "sample_run"))
    root = Path(str(config.get("output_root", "outputs/readiness")))
    path = root / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path
