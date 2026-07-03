"""Stress dashboard entry points."""

from __future__ import annotations

from pathlib import Path


def dashboard_path(run_id: str, output_root: Path = Path("outputs/stress")) -> Path:
    return output_root / run_id / "dashboard" / "index.html"
