"""Deterministic synthetic uploads for the backtest-audit tests.

Everything is generated from a seed; nothing here is market data. The
builders return pandas frames, and ``csv_bytes`` turns any of them into the
bytes a client would upload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

START = "2019-01-02"


def business_days(n: int, start: str = START) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="B", tz="UTC")


def positive_drift(
    n: int = 1500, *, mean: float = 0.0009, std: float = 0.01, seed: int = 3
) -> pd.DataFrame:
    """A daily equity curve with a real edge: annualised Sharpe around 1.4."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(mean, std, n)
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def returns_frame(n: int = 600, *, mean: float = 0.0009, std: float = 0.01, seed: int = 5):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"date": business_days(n), "return": rng.normal(mean, std, n)})


def best_of_n_walks(
    trials: int = 100, n: int = 512, *, std: float = 0.01, seed: int = 11
) -> tuple[pd.DataFrame, np.ndarray]:
    """``trials`` unskilled random walks; the winner by Sharpe as an equity
    curve, and the whole matrix as the variants upload."""
    rng = np.random.default_rng(seed)
    matrix = rng.normal(0.0, std, (n, trials))
    sharpes = matrix.mean(axis=0) / matrix.std(axis=0, ddof=1)
    winner = matrix[:, int(np.argmax(sharpes))]
    equity = 10_000.0 * np.cumprod(1.0 + winner)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity}), matrix


def stale_marks(n: int = 400, *, run: int = 25, seed: int = 2) -> pd.DataFrame:
    """A curve with a long run of identical non-zero daily returns."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.01, n)
    returns[100 : 100 + run] = 0.004
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def spiked(n: int = 400, *, spikes: int = 5, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.008, n)
    for index in range(spikes):
        returns[50 + 60 * index] = 0.45
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(n), "equity": equity})


def trades_frame(
    n: int = 60, *, edge: float = 0.8, seed: int = 9, side: str = "long"
) -> pd.DataFrame:
    """Closed round trips of 10 units at 100 with a mean edge of ``edge``."""
    rng = np.random.default_rng(seed)
    days = business_days(n * 25 + 2)
    move = rng.normal(edge, 1.0, n)
    exit_price = 100.0 + move if side == "long" else 100.0 - move
    return pd.DataFrame(
        {
            "entry_time": days[::25][:n],
            "exit_time": days[1::25][:n],
            "quantity": 10.0,
            "entry_price": 100.0,
            "exit_price": exit_price,
            "side": side,
        }
    )


def benchmark_lower_drift(n: int = 1500, *, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.012, n)
    return pd.DataFrame(
        {"timestamp": business_days(n), "equity": 100.0 * np.cumprod(1.0 + returns)}
    )


def csv_bytes(frame: pd.DataFrame, *, sep: str = ",") -> bytes:
    return frame.to_csv(index=False, sep=sep).encode("utf-8")


def variants_bytes(matrix: np.ndarray) -> bytes:
    frame = pd.DataFrame(matrix, columns=[f"v{i}" for i in range(matrix.shape[1])])
    return csv_bytes(frame)
