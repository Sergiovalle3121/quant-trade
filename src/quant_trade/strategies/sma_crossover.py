import pandas as pd


def generate_signals(data: pd.DataFrame, short_window: int = 5, long_window: int = 20) -> pd.Series:
    if short_window >= long_window:
        raise ValueError("short_window must be less than long_window")
    short = data["close"].rolling(short_window, min_periods=1).mean()
    long = data["close"].rolling(long_window, min_periods=1).mean()
    return (short > long).astype(int)
