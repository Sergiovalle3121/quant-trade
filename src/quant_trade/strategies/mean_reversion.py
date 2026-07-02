import pandas as pd


def generate_signals(data: pd.DataFrame, window: int = 10, z_threshold: float = 1.0) -> pd.Series:
    mean = data["close"].rolling(window, min_periods=2).mean()
    std = data["close"].rolling(window, min_periods=2).std().replace(0, pd.NA)
    z = (data["close"] - mean) / std
    return (z < -z_threshold).fillna(False).astype(int)
