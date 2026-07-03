"""Typed data lake domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DatasetDefinition(BaseModel):
    dataset_id: str
    name: str
    symbols: list[str]
    asset_class: str = "equity"
    provider: str
    interval: str = "1d"
    start: str
    end: str
    adjusted: bool = True


class DatasetVersion(BaseModel):
    dataset_id: str
    version: str
    created_at_utc: str = Field(default_factory=utc_now_iso)
    schema_hash: str
    data_hash: str
    source_manifest: str
    row_count: int
    data_path: str | None = None
    quality_status: Literal["pass", "warn", "fail"] = "warn"


class DatasetSnapshot(BaseModel):
    dataset_id: str
    version: str
    snapshot_id: str
    created_at_utc: str = Field(default_factory=utc_now_iso)
    source_data_path: str
    snapshot_path: str
    schema_hash: str
    data_hash: str
    row_count: int


class DatasetContract(BaseModel):
    required_columns: list[str] = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    min_row_count: int = 1
    max_missing_pct: float = 0.0
    duplicate_policy: Literal["fail", "warn", "allow"] = "fail"
    timezone_policy: Literal["utc", "date", "allow"] = "allow"
    expected_interval: str = "1d"
    allowed_symbols: list[str] = []
    validate_prices: bool = True
    validate_volume: bool = True
    max_gap_days: int | None = None
    stale_data_threshold_days: int | None = None


class DatasetQualityReport(BaseModel):
    dataset_id: str
    version: str | None = None
    status: Literal["pass", "warn", "fail"]
    row_count: int
    missing_pct: float
    duplicate_count: int
    stale: bool = False
    warnings: list[str] = []
    errors: list[str] = []


class ProviderComparisonReport(BaseModel):
    symbol: str
    interval: str
    provider_a: str
    provider_b: str
    status: Literal["pass", "warn", "fail"]
    compared_rows: int
    max_close_diff_pct: float
    missing_bars_a: int = 0
    missing_bars_b: int = 0
    warnings: list[str] = []


class CorporateActionWarning(BaseModel):
    symbol: str
    date: str
    reason: str
    severity: Literal["info", "warn", "fail"] = "warn"


class SurvivorshipBiasWarning(BaseModel):
    dataset_id: str
    reason: str
    severity: Literal["info", "warn", "fail"] = "warn"


class DatasetRegistryRecord(DatasetDefinition):
    created_at_utc: str = Field(default_factory=utc_now_iso)
    version: str = "v1"
    schema_hash: str
    data_hash: str
    source_manifest: str
    quality_status: Literal["pass", "warn", "fail"] = "warn"
    data_path: str
    row_count: int


class ContractValidationResult(BaseModel):
    dataset_id: str
    status: Literal["pass", "warn", "fail"]
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
