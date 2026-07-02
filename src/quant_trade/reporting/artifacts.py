"""Helpers for writing research artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def create_run_dir(base: str | Path, name: str) -> Path:
    root = Path(base)
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    if not candidate.exists():
        candidate.mkdir()
        return candidate
    suffix = 1
    while (root / f"{name}_{suffix:03d}").exists():
        suffix += 1
    candidate = root / f"{name}_{suffix:03d}"
    candidate.mkdir()
    return candidate


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def write_csv(path: Path, data: Any) -> None:
    if isinstance(data, pd.DataFrame):
        frame = data
    else:
        rows = [item.model_dump() if hasattr(item, "model_dump") else item for item in data]
        frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)


def write_summary(path: Path, title: str, lines: list[str]) -> None:
    path.write_text("# " + title + "\n\n" + "\n".join(lines) + "\n")
