"""Explicit leakage checks for safe ML research."""

from __future__ import annotations

from typing import Any

import pandas as pd

FUTURE_TOKENS = ("future", "forward", "label", "target", "next")


def check_leakage(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> dict[str, Any]:
    issues: list[str] = []
    bad_names = [
        c
        for c in features.columns
        if any(token in c.lower() for token in FUTURE_TOKENS)
    ]
    if bad_names:
        issues.append(f"feature columns look forward-looking: {bad_names}")
    if (
        not train.empty
        and not test.empty
        and pd.to_datetime(train["timestamp"], utc=True).max()
        >= pd.to_datetime(test["timestamp"], utc=True).min()
    ):
        issues.append("train/test split is not chronological")
    key = ["timestamp", "symbol"]
    overlap = set(map(tuple, features[key].itertuples(index=False, name=None))) & set(
        map(tuple, labels[key].itertuples(index=False, name=None))
    )
    if not overlap:
        issues.append("features and labels have no aligned observations")
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "real_money_ready": False,
    }
