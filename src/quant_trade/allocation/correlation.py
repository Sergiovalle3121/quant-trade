from __future__ import annotations

import pandas as pd

from .models import AllocationCandidate


def load_returns(candidates: list[AllocationCandidate]) -> pd.DataFrame:
    series = []
    for c in candidates:
        df = pd.read_csv(c.daily_returns_path)
        if "date" not in df.columns or "daily_return" not in df.columns:
            raise ValueError(
                f"daily returns file requires date,daily_return: {c.daily_returns_path}"
            )
        s = pd.Series(
            df["daily_return"].astype(float).to_numpy(),
            index=pd.to_datetime(df["date"]),
            name=c.strategy_id,
        )
        series.append(s)
    return pd.concat(series, axis=1).sort_index().fillna(0.0) if series else pd.DataFrame()


def pairwise_correlation(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr().fillna(0.0) if not returns.empty else pd.DataFrame()


def high_correlation_pairs(corr: pd.DataFrame, threshold: float) -> list[dict[str, float | str]]:
    pairs: list[dict[str, float | str]] = []
    cols = list(corr.columns)
    for i, left in enumerate(cols):
        for right in cols[i + 1 :]:
            val = float(corr.loc[left, right])
            if abs(val) > threshold:
                pairs.append({"strategy_id_1": left, "strategy_id_2": right, "correlation": val})
    return pairs


def drawdown_overlap_pairs(returns: pd.DataFrame) -> list[dict[str, float | str]]:
    pairs: list[dict[str, float | str]] = []
    if returns.empty:
        return pairs
    dd = (1 + returns).cumprod().div((1 + returns).cumprod().cummax()).sub(1)
    cols = list(dd.columns)
    for i, left in enumerate(cols):
        for right in cols[i + 1 :]:
            mask = (dd[left] < -0.02) & (dd[right] < -0.02)
            overlap = float(mask.mean())
            if overlap > 0:
                pairs.append(
                    {"strategy_id_1": left, "strategy_id_2": right, "overlap_pct": overlap}
                )
    return pairs


def rolling_correlation(returns: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    return returns.rolling(window).corr().dropna() if len(returns) >= window else pd.DataFrame()
