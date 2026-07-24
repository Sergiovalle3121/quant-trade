"""CLI for research-only cash-and-carry / funding analysis. Places no orders."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from quant_trade.carry.data import load_snapshots_from_json, synthetic_funding_snapshots
from quant_trade.carry.models import CarryCostModel, CarryPolicy, CarryPosition
from quant_trade.carry.research import run_carry_research, write_carry_artifacts
from quant_trade.carry.scenarios import evaluate_carry_scenarios

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


@carry_app.command("collect-once")
def carry_collect_once(
    config: Annotated[Path, typer.Option(help="Collector YAML (pairs, adapter, output)")],
    output: Annotated[
        Path | None, typer.Option(help="Override the store path from the config")
    ] = None,
) -> None:
    """One read-only funding capture pass. No loop, no orders, no keys."""
    from quant_trade.carry.collector import collect_once, load_collector_config

    cfg = load_collector_config(config)
    if output is not None:
        import dataclasses as _dc

        cfg = _dc.replace(cfg, output_path=str(output))
    summary = collect_once(cfg)
    console.print(
        f"captured={summary.captured} appended={summary.appended} "
        f"deduplicated={summary.deduplicated}"
    )
    for err in summary.errors:
        console.print(f"[yellow]error:[/yellow] {err}")
    console.print(f"store: {summary.output_path}")
    console.print("read-only collector: no orders, no keys, no daemon")
    raise typer.Exit(code=1 if summary.errors and not summary.captured else 0)


@carry_app.command("dataset-audit")
def carry_dataset_audit(
    path: Annotated[Path, typer.Option(help="JSONL funding-history store")],
    output: Annotated[Path | None, typer.Option(help="Write the audit JSON here")] = None,
) -> None:
    """Audit collected funding history: gaps, duplicates, coverage, quarantine."""
    from quant_trade.carry.quality import audit_dataset
    from quant_trade.evidence.canonical_json import atomic_write_json

    report = audit_dataset(path)
    table = Table(title="Funding dataset audit")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Records", str(report.total_records))
    table.add_row("Quarantined lines", str(report.quarantined_lines))
    table.add_row("Pairs", ", ".join(report.pairs) or "-")
    table.add_row("Range", f"{report.time_range_start} → {report.time_range_end}")
    table.add_row("Span (days)", f"{report.span_days:.2f}")
    table.add_row("Funding events", str(report.funding_events))
    table.add_row("Gaps", str(report.gaps_detected))
    table.add_row("Duplicates", str(report.duplicate_keys))
    console.print(table)
    status = "CLEAN" if report.is_clean else "PROBLEMS"
    colour = "green" if report.is_clean else "red"
    console.print(f"Audit: [bold {colour}]{status}[/bold {colour}]")
    for problem in report.problems:
        console.print(f"  - {problem}")
    if output is not None:
        atomic_write_json(output, report.to_dict())
        console.print(f"Report: {output}")
    raise typer.Exit(code=0 if report.is_clean else 1)


@carry_app.command("scenarios")
def carry_scenarios(
    config: Annotated[Path, typer.Option(help="Cash-and-carry campaign YAML")],
) -> None:
    """Run the deterministic stress matrix on the latest snapshot (no orders)."""
    cfg = _load_config(config)
    data_cfg = cfg.get("data", {})
    if data_cfg.get("source") == "json":
        snapshots = load_snapshots_from_json(data_cfg["path"])
    else:
        snapshots = synthetic_funding_snapshots(**data_cfg.get("synthetic", {}))
    if not snapshots:
        raise typer.BadParameter("no snapshots to evaluate")
    latest = snapshots[-1]
    position = CarryPosition(
        **cfg.get("position", {"notional_usd": 100_000, "holding_days": 30})
    )
    costs = CarryCostModel(**cfg.get("costs", {}))
    policy = CarryPolicy(**cfg.get("policy", {}))
    evaluations = evaluate_carry_scenarios(latest, position, costs, policy)

    table = Table(title=f"Carry stress scenarios ({latest.data_source} snapshot)")
    for column in ["Scenario", "Decision", "Net carry", "Reasons"]:
        table.add_column(column)
    for ev in evaluations:
        table.add_row(
            ev.scenario,
            ev.decision,
            f"{ev.net_annual_carry:.3f}",
            "; ".join(ev.reasons) or "-",
        )
    console.print(table)
    console.print("real_money=NO-GO  no orders were placed")
