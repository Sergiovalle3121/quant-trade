"""Data lake CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from .config import load_datalake_config
from .contracts import load_contract, validate_contract
from .dashboard import render_dashboard
from .models import DatasetDefinition
from .quality import generate_dataset_quality_report
from .registry import latest_record, list_versions, load_registry, register_dataset
from .reports import produce_lineage_report, write_json, write_summary
from .snapshots import create_snapshot, diff_snapshots
from .versioning import compare_dataset_versions, read_dataset

app = typer.Typer(help="Versioned research data lake commands.")
console = Console()


def _run_dir(cfg):
    from datetime import UTC, datetime

    p = cfg.outputs_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _definition_from_config(path: Path) -> DatasetDefinition:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DatasetDefinition(**payload.get("dataset", payload))


@app.command("register")
def register(
    config: Annotated[Path, typer.Option(help="Data lake dataset YAML config")],
    data_path: Annotated[Path, typer.Option(help="CSV input path")],
) -> None:
    cfg = load_datalake_config(config)
    rec = register_dataset(cfg, _definition_from_config(config), data_path)
    out = _run_dir(cfg)
    write_json(out / "registry_snapshot.json", rec.model_dump())
    write_json(
        out / "quality_report.json",
        generate_dataset_quality_report(
            rec.dataset_id, read_dataset(Path(rec.data_path)), rec.version
        ).model_dump(),
    )
    write_summary(
        out / "datalake_summary.md", "Data Lake Registration", produce_lineage_report(rec)
    )
    console.print(f"Registered {rec.dataset_id} {rec.version}")


@app.command("snapshot")
def snapshot(
    dataset_id: Annotated[str, typer.Option(help="Dataset id")],
    config: Annotated[Path, typer.Option(help="Data lake config")],
) -> None:
    cfg = load_datalake_config(config)
    snap = create_snapshot(cfg, dataset_id)
    out = _run_dir(cfg)
    write_json(out / "registry_snapshot.json", snap.model_dump())
    console.print(f"Snapshot created: {snap.snapshot_path}")


@app.command("validate")
def validate(
    dataset_id: Annotated[str, typer.Option(help="Dataset id")],
    contract: Annotated[Path, typer.Option(help="Contract YAML")],
    config: Annotated[Path, typer.Option(help="Data lake config")] = Path(
        "configs/datalake/local_datalake.yaml"
    ),
) -> None:
    cfg = load_datalake_config(config)
    rec = latest_record(cfg, dataset_id)
    result = validate_contract(
        dataset_id, read_dataset(Path(rec.data_path)), load_contract(contract)
    )
    out = _run_dir(cfg)
    write_json(out / "contract_validation.json", result.model_dump())
    console.print(json.dumps(result.model_dump(), indent=2))
    if result.status == "fail":
        raise typer.Exit(1)


@app.command("versions")
def versions(
    dataset_id: Annotated[str, typer.Option(help="Dataset id")],
    config: Annotated[Path, typer.Option(help="Data lake config")],
) -> None:
    cfg = load_datalake_config(config)
    console.print(json.dumps([v.model_dump() for v in list_versions(cfg, dataset_id)], indent=2))


@app.command("diff")
def diff(
    dataset_id: Annotated[str, typer.Option(help="Dataset id")],
    from_version: Annotated[str, typer.Option("--from-version")],
    to_version: Annotated[str, typer.Option("--to-version")],
    config: Annotated[Path, typer.Option(help="Data lake config")],
) -> None:
    cfg = load_datalake_config(config)
    records = {r["version"]: r for r in load_registry(cfg).get(dataset_id, [])}
    result = (
        compare_dataset_versions(records[from_version], records[to_version])
        if from_version in records and to_version in records
        else diff_snapshots(cfg, dataset_id, from_version, to_version)
    )
    out = _run_dir(cfg)
    write_json(out / "version_diff.json", result)
    console.print(json.dumps(result, indent=2))


@app.command("quality")
def quality(
    dataset_id: Annotated[str, typer.Option(help="Dataset id")],
    config: Annotated[Path, typer.Option(help="Data lake config")],
) -> None:
    cfg = load_datalake_config(config)
    rec = latest_record(cfg, dataset_id)
    report = generate_dataset_quality_report(
        dataset_id, read_dataset(Path(rec.data_path)), rec.version
    )
    out = _run_dir(cfg)
    write_json(out / "quality_report.json", report.model_dump())
    console.print(json.dumps(report.model_dump(), indent=2))


@app.command("dashboard")
def dashboard(config: Annotated[Path, typer.Option(help="Data lake config")]) -> None:
    cfg = load_datalake_config(config)
    out = _run_dir(cfg) / "dashboard"
    path = render_dashboard(load_registry(cfg), out)
    console.print(f"Dashboard: {path}")
