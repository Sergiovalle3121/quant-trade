"""Data lake quality checks."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from .models import CorporateActionWarning, DatasetQualityReport, SurvivorshipBiasWarning


def _dup_count(df: pd.DataFrame) -> int:
    keys = [c for c in ["timestamp", "symbol"] if c in df.columns]
    return int(df.duplicated(subset=keys or None).sum())


def detect_stale_data(df: pd.DataFrame, threshold_days: int | None) -> bool:
    if threshold_days is None or "timestamp" not in df.columns or df.empty:
        return False
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").max()
    if pd.isna(ts):
        return True
    return (datetime.now(UTC) - ts.to_pydatetime()).days > threshold_days


def generate_dataset_quality_report(
    dataset_id: str,
    df: pd.DataFrame,
    version: str | None = None,
    stale_threshold_days: int | None = None,
) -> DatasetQualityReport:
    errors: list[str] = []
    warnings: list[str] = []
    missing_pct = float(df.isna().mean().max()) if not df.empty else 1.0
    dup = _dup_count(df)
    if missing_pct > 0:
        warnings.append(f"missing values detected: {missing_pct:.2%}")
    if dup:
        errors.append(f"duplicate bars detected: {dup}")
    stale = detect_stale_data(df, stale_threshold_days)
    if stale:
        warnings.append("dataset appears stale relative to threshold")
    status = "fail" if errors else ("warn" if warnings else "pass")
    return DatasetQualityReport(
        dataset_id=dataset_id,
        version=version,
        status=status,
        row_count=len(df),
        missing_pct=missing_pct,
        duplicate_count=dup,
        stale=stale,
        warnings=warnings,
        errors=errors,
    )


def flag_corporate_action_risk(
    df: pd.DataFrame, pct_threshold: float = 0.25
) -> list[CorporateActionWarning]:
    if not {"timestamp", "symbol", "close"}.issubset(df.columns):
        return []
    out: list[CorporateActionWarning] = []
    for symbol, group in df.sort_values("timestamp").groupby("symbol"):
        changes = group["close"].pct_change().abs()
        for idx in changes[changes > pct_threshold].index:
            out.append(
                CorporateActionWarning(
                    symbol=str(symbol),
                    date=str(group.loc[idx, "timestamp"]),
                    reason="large close-to-close move may indicate split/dividend adjustment risk",
                )
            )
    return out


def flag_survivorship_bias_risk(
    dataset_id: str, symbols: list[str], asset_class: str
) -> list[SurvivorshipBiasWarning]:
    warnings: list[SurvivorshipBiasWarning] = []
    if asset_class in {"equity", "etf"} and len(symbols) <= 1:
        warnings.append(
            SurvivorshipBiasWarning(
                dataset_id=dataset_id,
                reason=(
                    "single/current-symbol universe can hide delisted constituents; "
                    "document universe construction"
                ),
            )
        )
    return warnings
