from pathlib import Path

import pandas as pd

from quant_trade.datalake.config import DataLakeConfig
from quant_trade.datalake.models import DatasetDefinition
from quant_trade.datalake.registry import list_versions, register_dataset


def test_register_dataset(tmp_path: Path) -> None:
    csv = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "timestamp": ["2020-01-01"],
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [2.0],
            "low": [1.0],
            "close": [1.5],
            "volume": [100],
        }
    ).to_csv(csv, index=False)
    cfg = DataLakeConfig(
        lake_root=tmp_path / "lake",
        outputs_root=tmp_path / "out",
        registry_dir=tmp_path / "lake/registry",
        manifests_dir=tmp_path / "lake/manifests",
        snapshots_dir=tmp_path / "lake/snapshots",
        datasets_dir=tmp_path / "lake/datasets",
        quality_reports_dir=tmp_path / "lake/quality",
    )
    rec = register_dataset(
        cfg,
        DatasetDefinition(
            dataset_id="d1",
            name="D1",
            symbols=["SPY"],
            provider="csv",
            start="2020-01-01",
            end="2020-01-01",
        ),
        csv,
    )
    assert rec.version == "v1"
    assert Path(rec.data_path).exists()
    assert len(list_versions(cfg, "d1")) == 1
