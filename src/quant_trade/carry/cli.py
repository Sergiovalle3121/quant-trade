"""CLI for research-only cash-and-carry / funding analysis. Places no orders."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from quant_trade.carry.research import run_carry_research, write_carry_artifacts

carry_app = typer.Typer(
    help="Research-only cash-and-carry / funding analysis; no orders, no live venues."
)
console = Console()


@carry_app.callback()
def _carry_main() -> None:
    """Keep `carry` a command group even with a single subcommand."""


def _load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise typer.BadParameter("carry config must be a mapping")
    return payload


@carry_app.command("research")
def carry_research(
    config: Annotated[Path, typer.Option(help="Cash-and-carry campaign YAML")],
    output: Annotated[Path, typer.Option(help="Artifact output directory")] = Path(
        "outputs/carry"
    ),
) -> None:
    """Run a pre-registered carry campaign and print the GO/NO-GO/NOT-RUN verdict."""
    cfg = _load_config(config)
    result = run_carry_research(cfg)
    write_carry_artifacts(output, cfg, result)

    colour = {"GO": "green", "NO-GO": "red", "NOT-RUN": "yellow"}.get(result.decision, "white")
    console.print(f"Decision: [bold {colour}]{result.decision}[/bold {colour}]")
    for reason in result.reasons:
        console.print(f"  - {reason}")

    table = Table(title=f"Carry campaign ({result.data_source} data)")
    for column in ["Metric", "Value"]:
        table.add_column(column)
    m = result.metrics
    table.add_row("Total return", f"{m['total_return']:.4f}")
    table.add_row("Sharpe (per period)", f"{m['sharpe_per_period']:.3f}")
    table.add_row("Active intervals", str(m["active_intervals"]))
    table.add_row("Per-snapshot GO fraction", f"{result.per_snapshot_go_fraction:.3f}")
    table.add_row("Bootstrap available", str(result.bootstrap.get("available")))
    table.add_row("Walk-forward windows", str(len(result.walk_forward)))
    console.print(table)
    console.print(f"Artifacts: {output}")
    if result.data_source == "synthetic":
        console.print("[yellow]Synthetic data cannot produce GO — REAL DATA REQUIRED.[/yellow]")
    console.print("real_money=NO-GO  no orders were placed")
