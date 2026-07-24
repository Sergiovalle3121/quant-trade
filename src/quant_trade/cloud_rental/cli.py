"""CLI for rented-infrastructure feasibility. Creates nothing, spends nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.cloud_rental.catalog import check_quote_freshness, load_rental_config
from quant_trade.cloud_rental.feasibility import feasibility_matrix, matrix_markdown
from quant_trade.cloud_rental.models import SAFETY_POSTURE
from quant_trade.evidence.canonical_json import atomic_write_json

cloud_rental_app = typer.Typer(
    help="AWS/Alibaba rented-capacity feasibility; offline evaluation only."
)
console = Console()


@cloud_rental_app.callback()
def _main() -> None:
    """Keep `cloud-rental` a command group."""


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _print_safety() -> None:
    console.print(
        "aws_resources_created=false alibaba_resources_created=false "
        "external_spend_authorized=false miner_execution=false"
    )


@cloud_rental_app.command("quote")
def rental_quote(
    config: Annotated[Path, typer.Option(help="Rental evaluation YAML")],
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Show and freshness-check the quote inside a rental config."""
    loaded = load_rental_config(config)
    quote = loaded["quote"]
    now = evaluated_at_utc or _now_utc()
    problems = check_quote_freshness(quote, evaluated_at_utc=now)
    table = Table(title="Compute quote (read-only)")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Provider / SKU", f"{quote.provider} / {quote.sku}")
    table.add_row("Region", quote.region)
    table.add_row("Model", str(quote.purchase_model))
    table.add_row("Price/h", f"{quote.price_per_hour} {quote.currency}")
    table.add_row("Source", f"{quote.source_kind} ({quote.source_name})")
    table.add_row("Captured", quote.captured_at_utc)
    console.print(table)
    if problems:
        for p in problems:
            console.print(f"[red]stale:[/red] {p}")
    else:
        console.print("[green]quote is fresh[/green]")
    _print_safety()
    raise typer.Exit(code=1 if problems else 0)


@cloud_rental_app.command("evaluate")
def rental_evaluate(
    config: Annotated[Path, typer.Option(help="Rental evaluation YAML")],
    output: Annotated[Path | None, typer.Option(help="Write the decision JSON here")] = None,
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Evaluate one provider/purpose/SKU combination, fail-closed."""
    loaded = load_rental_config(config)
    now = evaluated_at_utc or _now_utc()
    rows = feasibility_matrix([loaded], evaluated_at_utc=now)
    decision = rows[0]
    colour = (
        "green"
        if decision.status.endswith("CANDIDATE") or decision.status.startswith("ELIGIBLE")
        else "red"
    )
    console.print(
        f"{decision.provider} / {decision.purpose}: "
        f"[bold {colour}]{decision.status}[/bold {colour}]"
    )
    for label, reason in (
        ("policy", decision.policy_reason),
        ("benchmark", decision.benchmark_reason),
        ("economics", decision.economic_reason),
    ):
        if reason:
            console.print(f"  {label}: {reason}")
    if output is not None:
        atomic_write_json(output, decision.to_dict())
        console.print(f"Decision: {output}")
    _print_safety()
    raise typer.Exit(code=0 if colour == "green" else 1)


@cloud_rental_app.command("compare")
def rental_compare(
    configs: Annotated[
        list[Path], typer.Option("--config", help="Rental YAML; repeat per combination")
    ],
    output: Annotated[Path | None, typer.Option(help="Write matrix JSON here")] = None,
    markdown: Annotated[Path | None, typer.Option(help="Write matrix markdown here")] = None,
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Evaluate several combinations into the provider/purpose matrix."""
    loaded = [load_rental_config(path) for path in configs]
    now = evaluated_at_utc or _now_utc()
    rows = feasibility_matrix(loaded, evaluated_at_utc=now)
    table = Table(title="Rented-infrastructure feasibility matrix")
    for column in ("Provider", "Purpose", "Status", "Reason"):
        table.add_column(column)
    for row in rows:
        reason = row.policy_reason or row.benchmark_reason or row.economic_reason
        table.add_row(row.provider, row.purpose, row.status, reason[:80])
    console.print(table)
    if output is not None:
        atomic_write_json(
            output,
            {
                "evaluated_at_utc": now,
                "rows": [r.to_dict() for r in rows],
                "safety": SAFETY_POSTURE,
            },
        )
        console.print(f"Matrix JSON: {output}")
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(matrix_markdown(rows), encoding="utf-8")
        console.print(f"Matrix markdown: {markdown}")
    _print_safety()
