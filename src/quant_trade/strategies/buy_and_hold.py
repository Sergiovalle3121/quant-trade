import pandas as pd


def generate_signals(data: pd.DataFrame) -> pd.Series:
    return pd.Series(1, index=data.index, dtype=int)
