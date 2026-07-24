"""CLI for opportunity discovery. Research only: no orders, no miners, no spend."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

opportunities_app = typer.Typer(
    help="Scan, rank, and paper-allocate opportunities; nothing here spends money."
)
console = Console()


@opportunities_app.callback()
def _opportunities_main() -> None:
    """Keep `opportunities` a command group."""


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@opportunities_app.command("scan-mining")
def scan_mining(
    config: Annotated[Path, typer.Option(help="Mining scan YAML (cells list)")],
    output: Annotated[Path, typer.Option(help="Matrix JSON artifact")] = Path(
        "artifacts/v5/MINING_RENTAL_MATRIX.json"
    ),
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Scan provider×region×SKU×algorithm×coin cells into the rental matrix."""
    from quant_trade.opportunities.mining_scan import (
        load_scan_config,
        scan_mining_cells,
        write_mining_matrix,
    )

    cells = load_scan_config(config)
    result = scan_mining_cells(
        cells,
        evaluated_at_utc=evaluated_at_utc or _now_utc(),
        config_dir=config.parent,
    )
    table = Table(title="Mining rental matrix")
    for column in ("Cell", "Status", "Test-only", "Reason"):
        table.add_column(column)
    for cell_row in result.cells:
        table.add_row(
            cell_row.identity,
            cell_row.status,
            "yes" if cell_row.test_only else "no",
            (cell_row.reasons[0] if cell_row.reasons else "—")[:70],
        )
    console.print(table)
    for status, count in result.counts_by_status.items():
        console.print(f"  {status}: {count}")
    path = write_mining_matrix(output, result)
    console.print(f"Matrix: {path}")
    console.print(
        "no miners were run, no cloud resources created, no spend authorized"
    )
