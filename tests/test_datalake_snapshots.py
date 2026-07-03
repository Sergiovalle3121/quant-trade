from pathlib import Path

import pandas as pd

from quant_trade.datalake.config import DataLakeConfig
from quant_trade.datalake.models import DatasetDefinition
from quant_trade.datalake.registry import register_dataset
from quant_trade.datalake.snapshots import create_snapshot, diff_snapshots
from quant_trade.datalake.versioning import compute_data_hash


def _cfg(tmp_path: Path) -> DataLakeConfig:
    return DataLakeConfig(
        lake_root=tmp_path / "lake",
        outputs_root=tmp_path / "out",
        registry_dir=tmp_path / "lake/registry",
        manifests_dir=tmp_path / "lake/manifests",
        snapshots_dir=tmp_path / "lake/snapshots",
        datasets_dir=tmp_path / "lake/datasets",
        quality_reports_dir=tmp_path / "lake/quality",
    )


def test_snapshot_and_hash_changes(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    csv = tmp_path / "data.csv"
    df = pd.DataFrame(
        {
            "timestamp": ["2020-01-01"],
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [2.0],
            "low": [1.0],
            "close": [1.5],
            "volume": [100],
        }
    )
    df.to_csv(csv, index=False)
    definition = DatasetDefinition(
        dataset_id="d1",
        name="D1",
        symbols=["SPY"],
        provider="csv",
        start="2020-01-01",
        end="2020-01-01",
    )
    h1 = compute_data_hash(csv)
    register_dataset(cfg, definition, csv)
    s1 = create_snapshot(cfg, "d1")
    df.loc[0, "close"] = 1.7
    df.to_csv(csv, index=False)
    h2 = compute_data_hash(csv)
    register_dataset(cfg, definition, csv)
    s2 = create_snapshot(cfg, "d1")
    assert h1 != h2
    assert s1.version == "v1" and s2.version == "v2"
    assert diff_snapshots(cfg, "d1", "v1", "v2")["data_changed"] is True
