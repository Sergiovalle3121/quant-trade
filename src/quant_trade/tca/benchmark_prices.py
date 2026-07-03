"""Benchmark price helpers."""
import pandas as pd


def vwap_proxy(row: pd.Series) -> float:
    return float((row["open"] + row["high"] + row["low"] + row["close"]) / 4.0)
