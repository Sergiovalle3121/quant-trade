from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd


class SignalModel(Protocol):
    name: str

    def generate(
        self, data: pd.DataFrame, params: dict[str, Any] | None = None
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class FunctionSignalModel:
    name: str
    func: Any

    def generate(self, data: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return self.func(data, params or {})


def rebalance_mask(index: pd.DatetimeIndex, frequency: str) -> pd.Series:
    f = frequency.lower()
    if f == "daily":
        return pd.Series(True, index=index)
    if f == "weekly":
        return pd.Series(
            index.to_series()
            .dt.isocalendar()
            .week.ne(index.to_series().shift().dt.isocalendar().week.to_numpy()),
            index=index,
        ).fillna(True)
    if f == "monthly":
        return pd.Series(
            index.to_series().dt.month.ne(index.to_series().shift().dt.month.to_numpy()),
            index=index,
        ).fillna(True)
    raise ValueError("rebalance_frequency must be daily, weekly, or monthly")


def weights_to_long(weights: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ts, row in weights.iterrows():
        for sym, w in row.dropna().items():
            if float(w) > 0:
                rows.append({"timestamp": ts, "symbol": sym, "target_weight": float(w)})
    return pd.DataFrame(rows, columns=["timestamp", "symbol", "target_weight"])
