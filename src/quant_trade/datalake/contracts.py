"""Dataset contract validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from .models import ContractValidationResult, DatasetContract
from .quality import detect_stale_data


def load_contract(path: Path) -> DatasetContract:
    return DatasetContract(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))


def validate_contract(
    dataset_id: str, df: pd.DataFrame, contract: DatasetContract
) -> ContractValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    missing_cols = [c for c in contract.required_columns if c not in df.columns]
    if missing_cols:
        errors.append(f"missing required columns: {', '.join(missing_cols)}")
    if len(df) < contract.min_row_count:
        errors.append(f"row count {len(df)} below minimum {contract.min_row_count}")
    missing_pct = float(df.isna().mean().max()) if not df.empty else 1.0
    if missing_pct > contract.max_missing_pct:
        errors.append(f"missing pct {missing_pct:.2%} exceeds {contract.max_missing_pct:.2%}")
    keys = [c for c in ["timestamp", "symbol"] if c in df.columns]
    duplicate_count = int(df.duplicated(subset=keys or None).sum())
    if duplicate_count and contract.duplicate_policy == "fail":
        errors.append(f"duplicate bars found: {duplicate_count}")
    elif duplicate_count and contract.duplicate_policy == "warn":
        warnings.append(f"duplicate bars found: {duplicate_count}")
    if contract.allowed_symbols and "symbol" in df.columns:
        extra = sorted(set(df["symbol"].astype(str)) - set(contract.allowed_symbols))
        if extra:
            errors.append(f"symbols outside contract: {', '.join(extra)}")
    if contract.validate_prices and {"open", "high", "low", "close"}.issubset(df.columns):
        bad = (
            (df[["open", "high", "low", "close"]] <= 0).any(axis=1) | (df["high"] < df["low"])
        ).sum()
        if int(bad):
            errors.append(f"invalid price rows: {int(bad)}")
    if contract.validate_volume and "volume" in df.columns:
        bad_volume = int((df["volume"] < 0).sum())
        if bad_volume:
            errors.append(f"negative volume rows: {bad_volume}")
    if detect_stale_data(df, contract.stale_data_threshold_days):
        warnings.append("stale data threshold exceeded")
    status = "fail" if errors else ("warn" if warnings else "pass")
    return ContractValidationResult(
        dataset_id=dataset_id,
        status=status,
        errors=errors,
        warnings=warnings,
        metrics={
            "row_count": len(df),
            "missing_pct": missing_pct,
            "duplicate_count": duplicate_count,
        },
    )
