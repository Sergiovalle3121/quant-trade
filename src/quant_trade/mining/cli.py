"""CLI for offline, cloud-aware mining economics and shutdown decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.mining.cloud import publish_report
from quant_trade.mining.config import load_mining_config
from quant_trade.mining.profitability import evaluate_all

mining_app = typer.Typer(
    help="Authorized crypto-mining economics; evaluation only, no miner process execution."
)
console = Console()


@mining_app.command("evaluate")
def mining_evaluate(
    config: Annotated[Path, typer.Option(help="Mining economics YAML")],
    output: Annotated[
        Path, typer.Option(help="JSON decision report")
    ] = Path("outputs/mining/profitability_report.json"),
    artifact_uri: Annotated[
        str | None,
        typer.Option(help="Optional s3:// URI for the same report; requires the cloud extra"),
    ] = None,
) -> None:
    """Rank compatible rigs/coins and produce conservative GO/NO-GO decisions."""
    rigs, markets, policy = load_mining_config(config)
    evaluations = evaluate_all(rigs, markets, policy)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "evaluations": [item.to_dict() for item in evaluations],
        "go_count": sum(item.decision == "GO" for item in evaluations),
        "authorized_to_start_miner": False,
        "cloud_resources_created": False,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if artifact_uri is not None:
        publish_report(report, artifact_uri)

    table = Table(title="Mining profitability (execution disabled)")
    for column in ["Rig", "Coin", "Decision", "Net/day", "Stress/day", "Margin"]:
        table.add_column(column)
    for item in evaluations:
        table.add_row(
            item.rig,
            item.coin,
            item.decision,
            f"${item.net_profit_usd:,.2f}",
            f"${item.stressed_net_profit_usd:,.2f}",
            f"{item.net_margin_rate:.1%}",
        )
    console.print(table)
    console.print(f"Report: {output}")
    if artifact_uri is not None:
        console.print(f"Cloud report: {artifact_uri}")
    console.print("authorized_to_start_miner=false cloud_resources_created=false")

