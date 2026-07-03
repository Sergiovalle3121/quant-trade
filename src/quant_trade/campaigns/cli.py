from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from quant_trade.campaigns.aggregator import read_results, write_ranking
from quant_trade.campaigns.config import load_campaign_config
from quant_trade.campaigns.dashboard import write_dashboard
from quant_trade.campaigns.models import GuardrailPolicy
from quant_trade.campaigns.ranking import rank_candidates
from quant_trade.campaigns.runner import plan_campaign, run_campaign

campaigns_app = typer.Typer(help="Offline research campaign automation.")
console = Console()


@campaigns_app.command("plan")
def plan(config: Annotated[Path, typer.Option(help="Campaign YAML/JSON config")]) -> None:
    cfg = load_campaign_config(config)
    runs = plan_campaign(cfg)
    console.print(f"Campaign plan generated: {len(runs)} runs")
    for run in runs:
        console.print(f"{run.run_id}: {run.strategy} {run.parameters}")


@campaigns_app.command("run")
def run(config: Annotated[Path, typer.Option(help="Campaign YAML/JSON config")]) -> None:
    cfg = load_campaign_config(config)
    out = run_campaign(cfg)
    console.print(f"Campaign complete. Output directory: {out}")


@campaigns_app.command("aggregate")
def aggregate(
    campaign_dir: Annotated[Path, typer.Option(help="Campaign output directory")],
) -> None:
    results = read_results(campaign_dir / "run_results.csv")
    ranked = rank_candidates(results, GuardrailPolicy())
    write_ranking(campaign_dir / "ranking.csv", ranked)
    write_ranking(campaign_dir / "rejected.csv", [r for r in ranked if r.rejected])
    console.print(f"Aggregated {len(results)} results")


@campaigns_app.command("dashboard")
def dashboard(
    campaign_dir: Annotated[Path, typer.Option(help="Campaign output directory")],
) -> None:
    results = read_results(campaign_dir / "run_results.csv")
    ranked = rank_candidates(results, GuardrailPolicy())
    write_dashboard(campaign_dir / "dashboard" / "index.html", ranked)
    console.print(f"Dashboard written: {campaign_dir / 'dashboard' / 'index.html'}")
