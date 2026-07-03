"""CLI commands for the research-only ML alpha lab."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from quant_trade.ml.config import load_ml_config
from quant_trade.ml.dashboard import write_dashboard
from quant_trade.ml.training import run_ml_workflow

ml_app = typer.Typer(help="Safe supervised ML alpha lab commands (research-only).")
console = Console()


def _load(path: Path):
    return load_ml_config(path)


@ml_app.command("run")
def run(config: Annotated[Path, typer.Option(help="ML YAML config")]) -> None:
    result = run_ml_workflow(_load(config), stage="run")
    write_dashboard(Path(result["output_dir"]))
    console.print(f"ML research run complete: {result['output_dir']}")
    console.print("research-only; real_money_ready=false")


@ml_app.command("features")
def features(config: Annotated[Path, typer.Option(help="ML YAML config")]) -> None:
    result = run_ml_workflow(_load(config), stage="features")
    console.print(f"Features written: {result['output_dir']}/features.csv")


@ml_app.command("leakage-check")
def leakage_check(config: Annotated[Path, typer.Option(help="ML YAML config")]) -> None:
    result = run_ml_workflow(_load(config), stage="leakage-check")
    console.print(f"Leakage status: {result['leakage_report']['status']}")


@ml_app.command("evaluate")
def evaluate(config: Annotated[Path, typer.Option(help="ML YAML config")]) -> None:
    result = run_ml_workflow(_load(config), stage="evaluate")
    console.print(f"Evaluation written: {result['output_dir']}/metrics_test.json")


@ml_app.command("dashboard")
def dashboard(config: Annotated[Path, typer.Option(help="ML YAML config")]) -> None:
    result = run_ml_workflow(_load(config), stage="evaluate")
    path = write_dashboard(Path(result["output_dir"]))
    console.print(f"Dashboard written: {path}")
