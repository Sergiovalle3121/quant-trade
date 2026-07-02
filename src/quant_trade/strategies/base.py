"""Strategy interface for deterministic research signals."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class Strategy(Protocol):
    """Protocol implemented by all research strategies."""

    name: str

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return timestamp-aligned signals with columns timestamp and signal."""
