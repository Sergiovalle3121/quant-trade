"""Cross-provider comparison."""

from __future__ import annotations

import pandas as pd

from .models import ProviderComparisonReport


def compare_providers(
    a: pd.DataFrame,
    b: pd.DataFrame,
    symbol: str,
    interval: str,
    provider_a: str,
    provider_b: str,
    price_diff_threshold_pct: float = 1.0,
) -> ProviderComparisonReport:
    aa = a[a["symbol"].astype(str) == symbol].copy()
    bb = b[b["symbol"].astype(str) == symbol].copy()
    merged = aa.merge(bb, on="timestamp", suffixes=("_a", "_b"), how="outer", indicator=True)
    missing_a = int((merged["_merge"] == "right_only").sum())
    missing_b = int((merged["_merge"] == "left_only").sum())
    both = merged[merged["_merge"] == "both"]
    diffs = (
        (
            (both["close_a"] - both["close_b"]).abs()
            / both[["close_a", "close_b"]].mean(axis=1)
            * 100
        )
        if not both.empty
        else pd.Series(dtype=float)
    )
    max_diff = float(diffs.max()) if not diffs.empty else 0.0
    warnings: list[str] = []
    if max_diff > price_diff_threshold_pct:
        warnings.append(f"large close price difference detected: {max_diff:.2f}%")
    if missing_a or missing_b:
        warnings.append("missing bars detected between providers")
    status = "fail" if max_diff > price_diff_threshold_pct * 5 else ("warn" if warnings else "pass")
    return ProviderComparisonReport(
        symbol=symbol,
        interval=interval,
        provider_a=provider_a,
        provider_b=provider_b,
        status=status,
        compared_rows=len(both),
        max_close_diff_pct=max_diff,
        missing_bars_a=missing_a,
        missing_bars_b=missing_b,
        warnings=warnings,
    )
