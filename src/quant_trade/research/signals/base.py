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


def weights_to_long(
    weights: pd.DataFrame,
    rebalance: pd.Series | None = None,
    allow_short: bool = False,
) -> pd.DataFrame:
    """Serialize a wide target-weight matrix into long-form rebalance targets.

    Zero weights are emitted (NaN counts as zero) so an all-flat target is an
    explicit exit-to-cash rebalance instead of a silently skipped date. When
    ``rebalance`` is given, only timestamps marked True emit rows; timestamps
    without rows mean "no rebalance", never "go to cash". Negative weights
    (short targets) require ``allow_short=True``; without it they raise so a
    long-only pipeline can never silently strip a short leg.
    """
    filled = weights.fillna(0.0)
    if not allow_short and (filled.to_numpy() < 0).any():
        raise ValueError(
            "negative weights require allow_short=True; refusing to silently drop shorts"
        )
    if rebalance is not None:
        keep = rebalance.reindex(weights.index, fill_value=False).astype(bool)
        filled = filled.loc[keep]
    if filled.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    stacked = filled.stack()
    return pd.DataFrame(
        {
            "timestamp": stacked.index.get_level_values(0),
            "symbol": stacked.index.get_level_values(1).astype(str),
            "target_weight": stacked.to_numpy(dtype=float),
        }
    )
