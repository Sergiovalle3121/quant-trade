from pathlib import Path

import pandas as pd
import yaml
from typer.testing import CliRunner

from quant_trade.cli import app

runner = CliRunner()


def test_datalake_cli_offline(tmp_path: Path) -> None:
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
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "lake_root": str(tmp_path / "lake"),
                "outputs_root": str(tmp_path / "out"),
                "registry_dir": str(tmp_path / "lake/registry"),
                "manifests_dir": str(tmp_path / "lake/manifests"),
                "snapshots_dir": str(tmp_path / "lake/snapshots"),
                "datasets_dir": str(tmp_path / "lake/datasets"),
                "quality_reports_dir": str(tmp_path / "lake/quality"),
                "dataset": {
                    "dataset_id": "d1",
                    "name": "D1",
                    "symbols": ["SPY"],
                    "asset_class": "etf",
                    "provider": "csv",
                    "interval": "1d",
                    "start": "2020-01-01",
                    "end": "2020-01-01",
                    "adjusted": True,
                },
            }
        ),
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "required_columns": [
                    "timestamp",
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
                "min_row_count": 1,
                "max_missing_pct": 0.0,
                "allowed_symbols": ["SPY"],
            }
        ),
        encoding="utf-8",
    )
    assert (
        runner.invoke(
            app, ["datalake", "register", "--config", str(cfg), "--data-path", str(csv)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["datalake", "snapshot", "--dataset-id", "d1", "--config", str(cfg)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "datalake",
                "validate",
                "--dataset-id",
                "d1",
                "--contract",
                str(contract),
                "--config",
                str(cfg),
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["datalake", "versions", "--dataset-id", "d1", "--config", str(cfg)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["datalake", "quality", "--dataset-id", "d1", "--config", str(cfg)]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["datalake", "dashboard", "--config", str(cfg)]).exit_code == 0
