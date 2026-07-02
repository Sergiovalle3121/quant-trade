import pandas as pd


def chronological_train_test_split(data: pd.DataFrame, train_fraction: float):
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    df = data.sort_values("date").reset_index(drop=True)
    cut = int(len(df) * train_fraction)
    if cut <= 0 or cut >= len(df):
        raise ValueError("insufficient data for train/test split")
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def date_based_split(data: pd.DataFrame, train_start, train_end, test_start, test_end):
    ts, te, ss, se = map(pd.Timestamp, [train_start, train_end, test_start, test_end])
    if not (ts <= te < ss <= se):
        raise ValueError("dates must satisfy train_start <= train_end < test_start <= test_end")
    df = data.sort_values("date").reset_index(drop=True)
    train = df[(df.date >= ts) & (df.date <= te)].copy()
    test = df[(df.date >= ss) & (df.date <= se)].copy()
    if train.empty or test.empty:
        raise ValueError("date split produced empty train or test data")
    return train, test


def walk_forward_splits(data: pd.DataFrame, train_size: int, test_size: int, step_size: int):
    if min(train_size, test_size, step_size) <= 0:
        raise ValueError("window sizes must be positive")
    df = data.sort_values("date").reset_index(drop=True)
    out = []
    start = 0
    while start + train_size + test_size <= len(df):
        train = df.iloc[start : start + train_size].copy()
        test = df.iloc[start + train_size : start + train_size + test_size].copy()
        if train.date.max() >= test.date.min():
            raise ValueError("test window must occur after train window")
        out.append((train, test))
        start += step_size
    if not out:
        raise ValueError("insufficient data for walk-forward splits")
    return out
