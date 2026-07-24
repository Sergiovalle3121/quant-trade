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


@opportunities_app.command("scan-trading")
def scan_trading(
    config: Annotated[Path, typer.Option(help="Trading scan YAML (hypotheses list)")],
    output: Annotated[Path, typer.Option(help="Leaderboard JSON artifact")] = Path(
        "artifacts/v5/TRADING_OPPORTUNITY_LEADERBOARD.json"
    ),
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Run every pre-registered hypothesis whose dataset exists; report the rest."""
    from quant_trade.opportunities.trading_scan import (
        load_trading_scan_config,
        scan_trading_opportunities,
        write_trading_leaderboard,
    )

    cfg = load_trading_scan_config(config)
    result = scan_trading_opportunities(
        cfg, evaluated_at_utc=evaluated_at_utc or _now_utc(), config_dir=Path(".")
    )
    table = Table(title="Trading opportunity leaderboard")
    for column in ("Hypothesis", "Status", "Sharpe/period", "Reason"):
        table.add_column(column)
    for row in result.rows:
        sharpe = row.metrics.get("sharpe_per_period")
        table.add_row(
            f"{row.hypothesis_id} {row.name}"[:40],
            row.status,
            f"{sharpe:.3f}" if isinstance(sharpe, float) else "—",
            (row.reasons[0] if row.reasons else "—")[:60],
        )
    console.print(table)
    path = write_trading_leaderboard(output, result)
    console.print(f"Leaderboard: {path}")
    console.print("real_money=NO-GO  a leaderboard rank is never an authorization")


@opportunities_app.command("rank")
def rank(
    trading: Annotated[Path, typer.Option(help="TRADING_OPPORTUNITY_LEADERBOARD.json")],
    mining: Annotated[Path, typer.Option(help="MINING_RENTAL_MATRIX.json")],
    output: Annotated[Path, typer.Option(help="Unified board JSON artifact")] = Path(
        "artifacts/v5/UNIFIED_OPPORTUNITY_BOARD.json"
    ),
    cash_yield_annual: Annotated[
        float, typer.Option(help="Annual cash/collateral yield baseline")
    ] = 0.04,
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Merge trading + mining + cash into the unified opportunity board."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.opportunities.board import build_opportunity_board, write_board

    trading_payload = load_json(trading)
    mining_payload = load_json(mining)
    board = build_opportunity_board(
        trading_rows=trading_payload.get("rows", []),
        mining_cells=mining_payload.get("cells", []),
        cash_yield_annual=cash_yield_annual,
        evaluated_at_utc=evaluated_at_utc or _now_utc(),
    )
    table = Table(title="Unified opportunity board")
    for column in ("Rank", "Entry", "Kind", "Status", "Eligible"):
        table.add_column(column)
    for entry in board["entries"]:
        table.add_row(
            str(entry["rank"]) if entry["rank"] is not None else "—",
            entry["entry_id"][:44],
            entry["kind"],
            entry["status"][:40],
            "yes" if entry["eligible"] else "no",
        )
    console.print(table)
    console.print(f"Champion: {board['champion']['entry_id']}")
    path = write_board(output, board)
    console.print(f"Board: {path}")
    console.print("real_money=NO-GO  ranking is research output only")


@opportunities_app.command("allocate-paper")
def allocate_paper(
    board: Annotated[Path, typer.Option(help="UNIFIED_OPPORTUNITY_BOARD.json")],
    capital: Annotated[float, typer.Option(help="Total PAPER capital (USD)")] = 100_000.0,
    max_fraction: Annotated[
        float, typer.Option(help="Per-opportunity cap as a fraction of capital")
    ] = 0.25,
    output: Annotated[Path, typer.Option(help="Allocation JSON artifact")] = Path(
        "artifacts/v5/PAPER_CAPITAL_ALLOCATION.json"
    ),
) -> None:
    """Allocate PAPER capital across the board. No orders, no transfers, no spend."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.opportunities.board import allocate_paper_capital, write_board

    board_payload = load_json(board)
    allocation = allocate_paper_capital(
        board_payload, capital, max_fraction_per_opportunity=max_fraction
    )
    table = Table(title="Paper capital allocation")
    for column in ("Entry", "Fraction", "Capital (USD)", "Rationale"):
        table.add_column(column)
    for line in allocation["allocations"]:
        table.add_row(
            line["entry_id"][:44],
            f"{line['fraction']:.3f}",
            f"{line['capital_usd']:,.2f}",
            line["rationale"][:50],
        )
    console.print(table)
    path = write_board(output, allocation)
    console.print(f"Allocation: {path}")
    console.print("paper_only=True  real_money=NO-GO  nothing was ordered or spent")
