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
    output: Annotated[Path, typer.Option(help="Unified board JSON artifact")] = Path(
        "artifacts/v5/UNIFIED_OPPORTUNITY_BOARD.json"
    ),
    cash_yield_annual: Annotated[
        float, typer.Option(help="Annual cash/collateral yield baseline")
    ] = 0.04,
    cash_evidence: Annotated[
        Path | None,
        typer.Option(help="Byte-bound cash baseline evidence JSON"),
    ] = None,
    evaluated_at_utc: Annotated[
        str | None,
        typer.Option(help="Evaluation clock (defaults to the scan artifact's clock)"),
    ] = None,
) -> None:
    """Merge trading + cash into the unified opportunity board."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.opportunities.board import build_opportunity_board, write_board

    trading_payload = load_json(trading)
    # The board refuses rows scanned at a different clock than it claims, so
    # the default is the scan's own clock rather than "now".
    scan_clock = str(trading_payload.get("evaluated_at_utc", ""))
    board = build_opportunity_board(
        trading_rows=trading_payload.get("rows", []),
        cash_yield_annual=cash_yield_annual,
        cash_evidence=load_json(cash_evidence) if cash_evidence is not None else None,
        evaluated_at_utc=evaluated_at_utc or scan_clock,
        # lineage from the artifacts' EMBEDDED hashes: an edited row can no
        # longer rank (V6-L) — the board recomputes and compares
        trading_lineage={
            "artifact": str(trading_payload.get("artifact", "")),
            "path": str(trading),
            "evaluated_at_utc": scan_clock,
            "rows_sha256": str(trading_payload.get("rows_sha256", "")),
        },
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


@opportunities_app.command("shadow-start")
def shadow_start_cmd(
    allocation: Annotated[Path, typer.Option(help="PAPER_CAPITAL_ALLOCATION.json")],
    state_dir: Annotated[Path, typer.Option(help="Shadow session state directory")],
    started_at_utc: Annotated[
        str | None, typer.Option(help="Session start clock (defaults to now UTC)")
    ] = None,
    commit_sha: Annotated[str, typer.Option(help="Code commit this session runs")] = "",
) -> None:
    """Freeze a paper allocation into a persistent shadow session."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.opportunities.shadow import shadow_start

    state = shadow_start(
        state_dir,
        load_json(allocation),
        started_at_utc=started_at_utc or _now_utc(),
        commit_sha=commit_sha,
    )
    console.print(f"Shadow session: [bold green]{state['session_id']}[/bold green]")
    console.print(f"  frozen allocation sha: {state['frozen_allocation_sha256'][:16]}…")
    console.print(f"  capital: {state['initial_capital_usd']:,.2f} (paper only)")
    console.print("no orders are sent anywhere; this is a local simulation")


@opportunities_app.command("shadow-advance")
def shadow_advance_cmd(
    state_dir: Annotated[Path, typer.Option(help="Shadow session state directory")],
    events: Annotated[Path, typer.Option(help="JSONL of events (seq/timestamp/yield)")],
) -> None:
    """Advance the shadow session over recorded events (idempotent resume)."""
    import json as _json

    from quant_trade.opportunities.shadow import shadow_advance

    rows = [
        _json.loads(line)
        for line in events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = shadow_advance(state_dir, rows)
    console.print(
        f"applied={result['applied']} skipped={result['skipped']} "
        f"equity={result['equity_usd']:,.2f}"
    )


@opportunities_app.command("shadow-status")
def shadow_status_cmd(
    state_dir: Annotated[Path, typer.Option(help="Shadow session state directory")],
    output: Annotated[Path | None, typer.Option(help="Write status JSON here")] = None,
) -> None:
    """Report the shadow session's equity, drawdown, scoreboard and switches."""
    from quant_trade.evidence.canonical_json import atomic_write_json
    from quant_trade.opportunities.shadow import shadow_status

    status = shadow_status(state_dir)
    console.print(f"Session {status['session_id']}: [bold]{status['status']}[/bold]")
    console.print(
        f"  equity={status['equity_usd']:,.2f} "
        f"return={status['total_return']:+.4%} drawdown={status['drawdown']:.4%}"
    )
    console.print(f"  events processed: {status['events_processed']}")
    if output is not None:
        atomic_write_json(output, status)
        console.print(f"Status: {output}")
    console.print("real_money=NO-GO  shadow only")


@opportunities_app.command("shadow-reconcile")
def shadow_reconcile_cmd(
    state_dir: Annotated[Path, typer.Option(help="Shadow session state directory")],
    now_utc: Annotated[
        str | None, typer.Option(help="Reconciliation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Rebuild equity from flows and evaluate every kill switch."""
    from quant_trade.opportunities.shadow import shadow_reconcile

    report = shadow_reconcile(state_dir, now_utc=now_utc or _now_utc())
    colour = "green" if report["reconciled"] and not report["kill_switch_engaged"] else "red"
    console.print(f"Reconciled: [bold {colour}]{report['reconciled']}[/bold {colour}]")
    for name, engaged in report["kill_switches"].items():
        console.print(f"  kill_switch[{name}]: {'ENGAGED' if engaged else 'ok'}")
    raise typer.Exit(code=0 if report["reconciled"] and not report["kill_switch_engaged"] else 1)


@opportunities_app.command("shadow-stop")
def shadow_stop_cmd(
    state_dir: Annotated[Path, typer.Option(help="Shadow session state directory")],
    stopped_at_utc: Annotated[
        str | None, typer.Option(help="Stop clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Stop the shadow session (state is preserved, never deleted)."""
    from quant_trade.opportunities.shadow import shadow_stop

    state = shadow_stop(state_dir, stopped_at_utc=stopped_at_utc or _now_utc())
    console.print(f"Session {state['session_id']}: [bold]{state['status']}[/bold]")
