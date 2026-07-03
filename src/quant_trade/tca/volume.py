"""Volume capacity estimates for simulated execution."""

import pandas as pd


def estimate_volume_capacity(
    frame: pd.DataFrame, max_participation_rate: float = 0.10
) -> pd.Series:
    return (frame["volume"].fillna(0).clip(lower=0) * max_participation_rate).astype(
        float
    )
