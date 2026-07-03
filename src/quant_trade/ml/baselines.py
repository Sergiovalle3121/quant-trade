"""Deterministic baseline models with optional lazy sklearn support."""

from __future__ import annotations

import numpy as np
import pandas as pd


class SimpleRankModel:
    def fit(self, x: pd.DataFrame, y: pd.Series) -> SimpleRankModel:
        self.feature_ = (
            "rolling_momentum_10d" if "rolling_momentum_10d" in x else x.columns[0]
        )
        corr = x[self.feature_].corr(y)
        self.sign_ = -1.0 if pd.notna(corr) and corr < 0 else 1.0
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return x[self.feature_].fillna(0.0).to_numpy(dtype=float) * self.sign_


def naive_momentum_score(x: pd.DataFrame) -> np.ndarray:
    cols = [
        c
        for c in ["rolling_momentum_10d", "return_5d_lag1", "sma_distance_20d"]
        if c in x
    ]
    return (
        x[cols].fillna(0.0).mean(axis=1).to_numpy(dtype=float)
        if cols
        else np.zeros(len(x))
    )


def make_model(name: str):
    if name in {"simple_rank_model", "naive_momentum_score"}:
        return SimpleRankModel()
    try:
        if name == "linear_regression":
            from sklearn.linear_model import LinearRegression

            return LinearRegression()
        if name == "logistic_regression":
            from sklearn.linear_model import LogisticRegression

            return LogisticRegression(max_iter=200, random_state=42)
        if name == "random_forest":
            from sklearn.ensemble import RandomForestRegressor

            return RandomForestRegressor(n_estimators=25, random_state=42, max_depth=4)
    except ImportError as exc:
        raise RuntimeError(f"optional ML model '{name}' requires scikit-learn") from exc
    raise ValueError(f"unknown ML baseline: {name}")
