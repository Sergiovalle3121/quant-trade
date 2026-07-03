"""ML prediction and backtest metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def prediction_metrics(frame: pd.DataFrame, bucket_count: int = 5) -> dict[str, object]:
    clean = frame.dropna(subset=["prediction", "forward_return"]).copy()
    if clean.empty:
        return {
            "prediction_direction_accuracy": 0.0,
            "rank_ic": 0.0,
            "feature_coverage": 0.0,
        }
    acc = ((clean["prediction"] > 0) == (clean["forward_return"] > 0)).mean()
    rank_ic = (
        clean.groupby("timestamp")
        .apply(
            lambda g: (
                g["prediction"].rank().corr(g["forward_return"].rank())
                if len(g) > 1
                else np.nan
            )
        )
        .mean()
    )
    clean["bucket"] = pd.qcut(
        clean["prediction"].rank(method="first"),
        q=min(bucket_count, len(clean)),
        duplicates="drop",
    )
    buckets = (
        clean.groupby("bucket", observed=False)["forward_return"]
        .mean()
        .astype(float)
        .to_dict()
    )
    return {
        "prediction_direction_accuracy": float(acc),
        "rank_ic": float(0.0 if pd.isna(rank_ic) else rank_ic),
        "mean_forward_return_by_prediction_bucket": {
            str(k): v for k, v in buckets.items()
        },
        "feature_coverage": float(
            frame.drop(columns=["timestamp", "symbol"], errors="ignore")
            .notna()
            .mean()
            .mean()
        ),
    }


def predictions_to_weights(
    predictions: pd.DataFrame, top_fraction: float = 0.34
) -> pd.DataFrame:
    rows = []
    for ts, g in predictions.dropna(subset=["prediction"]).groupby("timestamp"):
        n = max(1, int(len(g) * top_fraction))
        top = g.sort_values("prediction", ascending=False).head(n)
        weight = 1.0 / len(top) if len(top) else 0.0
        for symbol in top["symbol"]:
            rows.append({"timestamp": ts, "symbol": symbol, "target_weight": weight})
    return pd.DataFrame(rows)
