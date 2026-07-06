"""Validated historical market data request models."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

SUPPORTED_INTERVALS = {"1d", "4h", "1h", "30m", "15m", "5m", "1m"}


class HistoricalDataRequest(BaseModel):
    """Request for research-only historical OHLCV data."""

    provider: str
    symbols: list[str] = Field(min_length=1)
    start: date
    end: date
    interval: str
    adjusted: bool = True
    output_dir: str = "data/cache"
    force_refresh: bool = False
    path: str | None = None
    seed: int = 42

    @field_validator("provider", "interval")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, value: list[str]) -> list[str]:
        out = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not out:
            raise ValueError("symbols cannot be empty")
        return out

    @field_validator("interval")
    @classmethod
    def _interval(cls, value: str) -> str:
        if value not in SUPPORTED_INTERVALS:
            raise ValueError(f"interval must be one of: {', '.join(sorted(SUPPORTED_INTERVALS))}")
        return value

    @model_validator(mode="after")
    def _dates(self) -> HistoricalDataRequest:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)
