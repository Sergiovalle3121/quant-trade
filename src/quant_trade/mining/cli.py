"""CLI for offline, cloud-aware mining economics and shutdown decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.mining.cloud import publish_report
from quant_trade.mining.config import load_mining_config
from quant_trade.mining.profitability import evaluate_all
from quant_trade.mining.scenarios import evaluate_all_scenarios

mining_app = typer.Typer(
    help="Authorized crypto-mining economics; evaluation only, no miner process execution."
)
console = Console()


def _write_json_report(
    report: dict[str, object],
    output: Path,
    artifact_uri: str | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if artifact_uri is not None:
        publish_report(report, artifact_uri)


def _safety_metadata() -> dict[str, bool]:
    return {
        "authorized_to_start_miner": False,
        "cloud_resources_created": False,
    }


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("--as-of-utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise typer.BadParameter("--as-of-utc must include a timezone")
    return parsed.astimezone(UTC)


@mining_app.command("evaluate")
def mining_evaluate(
    config: Annotated[Path, typer.Option(help="Mining economics YAML")],
    output: Annotated[Path, typer.Option(help="JSON decision report")] = Path(
        "outputs/mining/profitability_report.json"
    ),
    artifact_uri: Annotated[
        str | None,
        typer.Option(help="Optional s3:// URI for the same report; requires the cloud extra"),
    ] = None,
    as_of_utc: Annotated[
        str | None,
        typer.Option(help="Reproducible UTC evaluation clock (ISO-8601)"),
    ] = None,
) -> None:
    """Rank compatible rigs/coins and produce conservative GO/NO-GO decisions."""
    rigs, markets, policy = load_mining_config(config)
    evaluated_at = _parse_as_of(as_of_utc)
    evaluations = evaluate_all(rigs, markets, policy, evaluated_at)
    report = {
        "evaluations": [item.to_dict() for item in evaluations],
        "go_count": sum(item.decision == "GO" for item in evaluations),
        "evaluated_at_utc": evaluated_at.replace(microsecond=0).isoformat(),
        **_safety_metadata(),
    }
    _write_json_report(report, output, artifact_uri)

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


@mining_app.command("break-even")
def mining_break_even(
    config: Annotated[Path, typer.Option(help="Mining economics YAML")],
    output: Annotated[Path, typer.Option(help="JSON break-even report")] = Path(
        "outputs/mining/break_even_report.json"
    ),
    as_of_utc: Annotated[
        str | None,
        typer.Option(help="Reproducible UTC evaluation clock (ISO-8601)"),
    ] = None,
) -> None:
    """Calculate transparent unit economics without starting any miner."""
    rigs, markets, policy = load_mining_config(config)
    evaluated_at = _parse_as_of(as_of_utc)
    evaluations = evaluate_all(rigs, markets, policy, evaluated_at)
    break_even = [
        {
            "rig": item.rig,
            "coin": item.coin,
            "decision": item.decision,
            "total_capex_usd": item.total_capex_usd,
            "efficiency_j_per_th": item.efficiency_j_per_th,
            "break_even_electricity_usd_per_kwh": (item.break_even_electricity_usd_per_kwh),
            "break_even_coin_price_usd": item.break_even_coin_price_usd,
            "break_even_hashprice_usd_per_th_day": (item.break_even_hashprice_usd_per_th_day),
            "production_cost_usd_per_coin": item.production_cost_usd_per_coin,
            "payback_days": item.payback_days,
            "npv_usd": item.npv_usd,
            "irr_annual_rate": item.irr_annual_rate,
            "market_source": item.market_source,
            "market_captured_at_utc": item.market_captured_at_utc,
            "market_snapshot_age_hours": item.market_snapshot_age_hours,
            "market_snapshot_sha256": item.market_snapshot_sha256,
        }
        for item in evaluations
    ]
    report: dict[str, object] = {
        "break_even": break_even,
        "evaluated_at_utc": evaluated_at.replace(microsecond=0).isoformat(),
        **_safety_metadata(),
    }
    _write_json_report(report, output)
    console.print(f"Break-even report: {output}")
    console.print("authorized_to_start_miner=false cloud_resources_created=false")


@mining_app.command("stress")
def mining_stress(
    config: Annotated[Path, typer.Option(help="Mining economics YAML")],
    output: Annotated[Path, typer.Option(help="JSON stress-scenario report")] = Path(
        "outputs/mining/stress_report.json"
    ),
    as_of_utc: Annotated[
        str | None,
        typer.Option(help="Reproducible UTC evaluation clock (ISO-8601)"),
    ] = None,
) -> None:
    """Run deterministic downside scenarios without network or process execution."""
    rigs, markets, policy = load_mining_config(config)
    evaluated_at = _parse_as_of(as_of_utc)
    scenarios = evaluate_all_scenarios(
        rigs,
        markets,
        policy,
        evaluated_at_utc=evaluated_at,
    )
    report: dict[str, object] = {
        "scenarios": [item.to_dict() for item in scenarios],
        "no_go_count": sum(item.evaluation.decision == "NO-GO" for item in scenarios),
        "evaluated_at_utc": evaluated_at.replace(microsecond=0).isoformat(),
        **_safety_metadata(),
    }
    _write_json_report(report, output)
    console.print(f"Stress report: {output}")
    console.print("authorized_to_start_miner=false cloud_resources_created=false")
