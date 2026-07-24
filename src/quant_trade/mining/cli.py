"""CLI for offline, cloud-aware mining economics and shutdown decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.mining.cashflow import project_mining_cashflow
from quant_trade.mining.cloud import publish_report
from quant_trade.mining.config import load_mining_config, load_projection_config
from quant_trade.mining.market import bottom_up_hashprice, compare_hashprice
from quant_trade.mining.profitability import evaluate_all
from quant_trade.mining.projection_scenarios import (
    npv_band,
    project_scenarios,
    scenario_projection_rows,
)
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


#: The V1 evaluate/break-even/stress commands price a CONSTANT daily cash flow.
#: The dynamic per-period engine (`mining project`) supersedes them; their
#: output is retained for comparison but must never feed a promotion decision.
_LEGACY_MARKER = {"legacy_non_promotable": True, "promotable_engine": "mining project"}


def _warn_legacy() -> None:
    console.print(
        "[yellow]legacy_non_promotable=true[/yellow]: constant-flow V1 figures; "
        "use `mining project` (dynamic engine) for any promotable decision"
    )


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
        **_LEGACY_MARKER,
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
    _warn_legacy()
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
        **_LEGACY_MARKER,
        **_safety_metadata(),
    }
    _write_json_report(report, output)
    console.print(f"Break-even report: {output}")
    _warn_legacy()
    console.print("authorized_to_start_miner=false cloud_resources_created=false")


@mining_app.command("project")
def mining_project(
    config: Annotated[Path, typer.Option(help="Projection YAML (rig + market + assumptions)")],
    output: Annotated[Path, typer.Option(help="JSON projection report")] = Path(
        "outputs/mining/cashflow_projection.json"
    ),
    include_daily: Annotated[
        bool, typer.Option(help="Include the full daily series in the JSON report")
    ] = False,
) -> None:
    """Dynamic per-period NPV/IRR (fixes the V1 constant-cash-flow overstatement)."""
    rig, market, assumptions = load_projection_config(config)
    projection = project_mining_cashflow(rig, market, assumptions)
    decision = "GO" if projection.npv_usd > 0 else "NO-GO"
    report: dict[str, object] = {
        "decision": decision,
        **projection.to_dict(include_daily=include_daily),
        **_safety_metadata(),
    }
    _write_json_report(report, output)

    table = Table(title="Mining cash-flow projection (execution disabled)")
    for column in ["Metric", "Value"]:
        table.add_column(column)
    irr = (
        f"{projection.irr_annual_rate:.1%}"
        if projection.irr_annual_rate is not None
        else "undefined"
    )
    payback = (
        str(projection.discounted_payback_days)
        if projection.discounted_payback_days is not None
        else "never"
    )
    prod_cost = (
        f"${projection.production_cost_usd_per_coin:,.0f}"
        if projection.production_cost_usd_per_coin is not None
        else "n/a"
    )
    table.add_row("Decision", decision)
    table.add_row("Dynamic NPV", f"${projection.npv_usd:,.0f}")
    table.add_row("Constant-flow NPV (V1)", f"${projection.constant_flow_npv_usd:,.0f}")
    table.add_row("Overstatement removed", f"${projection.npv_overstatement_vs_constant:,.0f}")
    table.add_row("IRR (annual)", irr)
    table.add_row("Discounted payback (days)", payback)
    table.add_row("Production cost / coin", prod_cost)
    console.print(table)
    console.print(f"Projection report: {output}")
    console.print("authorized_to_start_miner=false hardware_control_enabled=false")


@mining_app.command("project-scenarios")
def mining_project_scenarios(
    config: Annotated[Path, typer.Option(help="Projection YAML (rig + market + assumptions)")],
    output: Annotated[Path, typer.Option(help="JSON scenario report")] = Path(
        "outputs/mining/projection_scenarios.json"
    ),
) -> None:
    """Deterministic NPV bands across a fixed price/difficulty/energy scenario set."""
    rig, market, assumptions = load_projection_config(config)
    results = project_scenarios(rig, market, assumptions)
    rows = scenario_projection_rows(results)
    band = npv_band(results)
    report: dict[str, object] = {
        "scenarios": [row.to_dict() for row in rows],
        "npv_band": band,
        **_safety_metadata(),
    }
    _write_json_report(report, output)

    table = Table(title="Mining NPV scenario band (execution disabled)")
    for column in ["Scenario", "NPV", "Decision"]:
        table.add_column(column)
    for row in rows:
        table.add_row(row.scenario, f"${row.npv_usd:,.0f}", row.decision)
    console.print(table)
    console.print(
        f"NPV band: min ${band['min_npv_usd']:,.0f} / median ${band['median_npv_usd']:,.0f} "
        f"/ max ${band['max_npv_usd']:,.0f}  ({int(band['go_scenarios'])}/"
        f"{int(band['scenarios'])} GO)"
    )
    console.print("authorized_to_start_miner=false hardware_control_enabled=false")


@mining_app.command("rental-evaluate")
def mining_rental_evaluate(
    rental_config: Annotated[
        Path, typer.Option(help="cloud_rental evaluation YAML (provider/SKU/policy)")
    ],
    market_config: Annotated[
        Path, typer.Option(help="Projection YAML whose market block prices revenue")
    ],
    output: Annotated[Path | None, typer.Option(help="Write the decision JSON here")] = None,
    evaluated_at_utc: Annotated[
        str | None, typer.Option(help="Evaluation clock (defaults to now UTC)")
    ] = None,
) -> None:
    """Evaluate GENERIC CLOUD COMPUTE rental for hashing, fail-closed.

    Deployment models are kept separate: owned hardware uses `mining project`;
    hosted-ASIC rental providers are a documented extension contract only (not
    implemented — no external marketplace is called); this command covers
    generic cloud compute via the cloud_rental policy/benchmark/economics gates.
    Market freshness is RECOMPUTED from captured_at against the evaluation
    clock, and a direct-vs-bottom-up hashprice divergence fails closed.
    """
    from quant_trade.cloud_rental.catalog import load_rental_config
    from quant_trade.cloud_rental.feasibility import feasibility_matrix
    from quant_trade.evidence.canonical_json import atomic_write_json
    from quant_trade.mining.market import require_fresh

    now = evaluated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _rig, market, _assumptions = load_projection_config(market_config)
    try:
        require_fresh(market, evaluated_at_utc=now)
    except ValueError as exc:
        console.print(f"[bold red]market snapshot rejected:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    comparison = compare_hashprice(market)
    if comparison.diverges:
        console.print(f"[bold red]ALERT[/bold red]: {comparison.alert}")
        console.print("hashprice sources disagree; failing closed — no evaluation")
        raise typer.Exit(code=1)
    hashprice = bottom_up_hashprice(market)

    loaded = load_rental_config(rental_config)
    revenue = dict(loaded.get("revenue") or {})
    revenue["hashprice_usd_per_th_day"] = hashprice
    loaded["revenue"] = revenue
    decision = feasibility_matrix([loaded], evaluated_at_utc=now)[0]

    colour = "green" if decision.status.endswith("CANDIDATE") else "red"
    console.print(
        f"{decision.provider} / hashing (generic_cloud_compute): "
        f"[bold {colour}]{decision.status}[/bold {colour}]"
    )
    for label, reason in (
        ("policy", decision.policy_reason),
        ("benchmark", decision.benchmark_reason),
        ("economics", decision.economic_reason),
    ):
        if reason:
            console.print(f"  {label}: {reason}")
    console.print(
        f"market: {market.source_name} captured_at={market.captured_at_utc} "
        f"bottom_up_hashprice={hashprice:.4f} USD/TH/day"
    )
    if output is not None:
        atomic_write_json(
            output,
            {
                "deployment_model": "generic_cloud_compute",
                "market_source": market.source_name,
                "market_captured_at_utc": market.captured_at_utc,
                "bottom_up_hashprice_usd_per_th_day": hashprice,
                **decision.to_dict(),
            },
        )
        console.print(f"Decision: {output}")
    console.print("deployment_model=generic_cloud_compute miner_execution=false")
    console.print("authorized_to_start_miner=false cloud_resources_created=false")
    raise typer.Exit(code=0 if colour == "green" else 1)


@mining_app.command("hashprice")
def mining_hashprice(
    config: Annotated[Path, typer.Option(help="Projection YAML (uses its market block)")],
    max_relative_divergence: Annotated[
        float, typer.Option(help="Alert if the two methods diverge by more than this")
    ] = 0.10,
) -> None:
    """Compare direct vs bottom-up hashprice; alert on divergence (no averaging)."""
    _rig, market, _assumptions = load_projection_config(config)
    comparison = compare_hashprice(market, max_relative_divergence=max_relative_divergence)
    table = Table(title="Hashprice methods (read-only)")
    for column in ["Method", "USD/TH/day"]:
        table.add_column(column)
    table.add_row("bottom-up", f"{bottom_up_hashprice(market):.4f}")
    direct = comparison.direct_usd_per_th_day
    table.add_row("direct", f"{direct:.4f}" if direct is not None else "n/a")
    console.print(table)
    if comparison.alert:
        console.print(f"[bold red]ALERT[/bold red]: {comparison.alert}")
    else:
        console.print("methods agree within tolerance")
    console.print(f"source: {market.source_name} stale={market.is_stale}")


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
        **_LEGACY_MARKER,
        **_safety_metadata(),
    }
    _write_json_report(report, output)
    console.print(f"Stress report: {output}")
    _warn_legacy()
    console.print("authorized_to_start_miner=false cloud_resources_created=false")
