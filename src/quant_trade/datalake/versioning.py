"""Dataset hashing and version comparison utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

CANONICAL_COLUMNS = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]


def read_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"date": "timestamp"})
    return df


def compute_schema_hash(df: pd.DataFrame) -> str:
    schema = [(str(c), str(df[c].dtype)) for c in df.columns]
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def compute_data_hash(path: Path) -> str:
    df = read_dataset(path).copy()
    cols = sorted(df.columns)
    df = df[cols].sort_values(cols).reset_index(drop=True)
    payload = df.to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(payload.encode()).hexdigest()


def next_version(existing: list[str]) -> str:
    nums = [int(v[1:]) for v in existing if v.startswith("v") and v[1:].isdigit()]
    return f"v{(max(nums) if nums else 0) + 1}"


def compare_dataset_versions(old: dict, new: dict) -> dict:
    return {
        "dataset_id": new.get("dataset_id", old.get("dataset_id")),
        "from_version": old.get("version"),
        "to_version": new.get("version"),
        "schema_changed": old.get("schema_hash") != new.get("schema_hash"),
        "data_changed": old.get("data_hash") != new.get("data_hash"),
        "row_count_delta": int(new.get("row_count", 0)) - int(old.get("row_count", 0)),
    }
