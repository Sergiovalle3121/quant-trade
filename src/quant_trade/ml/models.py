"""Typed ML artifact names for the research lab."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MLRunSummary:
    run_id: str
    output_dir: str
    real_money_ready: bool = False
