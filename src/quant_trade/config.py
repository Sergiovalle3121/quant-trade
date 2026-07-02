"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Environment-driven settings with no secrets required."""

    log_level: str = os.getenv("QUANT_TRADE_LOG_LEVEL", "INFO")


def get_settings() -> Settings:
    """Return application settings."""
    return Settings()
