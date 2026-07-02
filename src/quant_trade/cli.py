"""Command line interface for research backtests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from quant_trade.backtest.engine import BacktestEngine
from quant_trade.config import get_settings
from quant_trade.data.cache import list_cache, write_cache
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.data.providers import get_data_provider
from quant_trade.data.quality import generate_quality_report
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.validation import validate_ohlcv
from quant_trade.logging_config import configure_logging
from quant_trade.research.experiment_config import load_experiment_config
from quant_trade.research.grid_search import run_grid_search
from quant_trade.research.runner import run_experiment
from quant_trade.research.walk_forward import run_walk_forward
from quant_trade.strategies import STRATEGY_REGISTRY, get_strategy

app = typer.Typer(help="Research-only quantitative trading tooling.")
data_app = typer.Typer(help="Historical data ingestion and validation.")
research_app = typer.Typer(help="Multi-asset research lab commands.")
app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
console = Console()


def _strategy_help() -> str:
    return "Strategy name: " + ", ".join(sorted(STRATEGY_REGISTRY))


def _print_metrics(
    title: str,
    strategy_name: str,
    initial_cash: float,
    final_equity: float,
    metrics,
):
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Strategy", strategy_name)
    table.add_row("Initial cash", f"${initial_cash:,.2f}")
    table.add_row("Final equity", f"${final_equity:,.2f}")
    table.add_row("Total return", f"{metrics['total_return']:.2%}")
    table.add_row("Sharpe", f"{metrics['sharpe']:.2f}")
    table.add_row("Max drawdown", f"{metrics['max_drawdown']:.2%}")
    table.add_row("Trade count", str(metrics["trade_count"]))
    console.print(table)


def _request_from_options(
    provider: str,
    symbols: list[str],
    start: str,
    end: str,
    interval: str,
    adjusted: bool,
    output_dir: str,
    force_refresh: bool,
    config: Path | None,
) -> HistoricalDataRequest:
    payload = {
        "provider": provider,
        "symbols": symbols,
        "start": start,
        "end": end,
        "interval": interval,
        "adjusted": adjusted,
        "output_dir": output_dir,
        "force_refresh": force_refresh,
    }
    if config is not None:
        loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        payload.update(loaded)
    return HistoricalDataRequest(**payload)


@data_app.command("fetch")
def data_fetch(
    provider: Annotated[
        str, typer.Option(help="Provider: csv, synthetic, yfinance, polygon")
    ] = "synthetic",
    symbol: Annotated[
        list[str] | None, typer.Option("--symbol", help="Symbol; repeat for multiple symbols")
    ] = None,
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD")] = "2020-01-01",
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD")] = "2020-12-31",
    interval: Annotated[str, typer.Option(help="Bar interval")] = "1d",
    adjusted: Annotated[bool, typer.Option("--adjusted/--no-adjusted")] = True,
    output_dir: Annotated[str, typer.Option(help="Cache output directory")] = "data/cache",
    force_refresh: Annotated[bool, typer.Option(help="Overwrite existing cache file")] = False,
    config: Annotated[Path | None, typer.Option(help="YAML config path")] = None,
) -> None:
    """Fetch, normalize, validate, and cache historical data."""
    request = _request_from_options(
        provider,
        symbol or ["SPY"],
        start,
        end,
        interval,
        adjusted,
        output_dir,
        force_refresh,
        config,
    )
    data = get_data_provider(request.provider).fetch_ohlcv(request)
    report = generate_quality_report(data)
    path = write_cache(data, request, report.warnings)
    console.print(f"Cached {len(data)} rows: {path}")


@data_app.command("validate")
def data_validate(path: Annotated[Path, typer.Option(help="CSV dataset path")]) -> None:
    """Validate a cached or local canonical OHLCV dataset."""
    data = validate_ohlcv(load_ohlcv_csv(path))
    console.print(f"Validation passed: {len(data)} rows")


@data_app.command("info")
def data_info(path: Annotated[Path, typer.Option(help="CSV dataset path")]) -> None:
    """Print dataset metadata and quality summary."""
    data = load_ohlcv_csv(path)
    console.print(json.dumps(generate_quality_report(data).to_dict(), indent=2))


@data_app.command("list-cache")
def data_list_cache(
    provider: Annotated[str | None, typer.Option(help="Optional provider filter")] = None,
    output_dir: Annotated[str, typer.Option(help="Cache root")] = "data/cache",
) -> None:
    """List cached CSV datasets."""
    for path in list_cache(output_dir, provider):
        console.print(path)


@app.command()
def backtest(
    strategy: Annotated[str, typer.Option(help=_strategy_help())],
    data: Annotated[Path, typer.Option(help="Path to OHLCV CSV data")],
    initial_cash: Annotated[float, typer.Option(help="Initial cash for the simulation")] = 10_000.0,
) -> None:
    """Run a deterministic long-only sample backtest."""
    configure_logging(get_settings().log_level)
    frame = load_ohlcv_csv(data)
    try:
        strategy_instance = get_strategy(strategy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = BacktestEngine(initial_cash=initial_cash).run(frame, strategy_instance)
    _print_metrics(
        "Quant Trade Backtest Summary",
        strategy_instance.name,
        initial_cash,
        float(result.equity_curve["equity"].iloc[-1]),
        result.metrics,
    )


@app.command("run-experiment")
def run_experiment_command(
    config: Annotated[Path, typer.Option(help="Experiment YAML/JSON")],
) -> None:
    """Run an experiment config and write artifacts."""
    result = run_experiment(load_experiment_config(config))
    console.print(f"Experiment complete. Output directory: {result['output_dir']}")
    console.print(f"Test total return: {result['test_metrics']['total_return']:.2%}")


@app.command("grid-search")
def grid_search_command(
    config: Annotated[Path, typer.Option(help="Grid search YAML/JSON")],
) -> None:
    """Run a parameter-grid research sweep and write artifacts."""
    result = run_grid_search(load_experiment_config(config))
    console.print(f"Grid search complete. Output directory: {result['output_dir']}")
    console.print(f"Best parameters: {result['best_params']}")


@app.command("walk-forward")
def walk_forward_command(
    config: Annotated[Path, typer.Option(help="Walk-forward YAML/JSON")],
) -> None:
    """Run walk-forward validation and write artifacts."""
    result = run_walk_forward(load_experiment_config(config))
    console.print(f"Walk-forward complete. Output directory: {result['output_dir']}")
    console.print(f"Windows evaluated: {len(result['windows'])}")


@research_app.command("list-strategies")
def research_list_strategies() -> None:
    """List available multi-asset research signal models."""
    from quant_trade.research.strategy_registry import list_research_signal_models

    table = Table(title="Research signal models")
    table.add_column("Name")
    for name in list_research_signal_models():
        table.add_row(name)
    console.print(table)


def _run_research_config(config: Path) -> dict:
    from quant_trade.research.multi_asset_runner import (
        load_multi_asset_config,
        run_multi_asset_research_experiment,
    )

    result = run_multi_asset_research_experiment(load_multi_asset_config(config))
    console.print(f"Experiment complete: {config}")
    console.print(f"Symbols: {', '.join(result['symbols'])}")
    console.print(f"Train range: {result['train_range'][0]} to {result['train_range'][1]}")
    console.print(f"Test range: {result['test_range'][0]} to {result['test_range'][1]}")
    console.print(f"Strategy return: {result['test_metrics']['total_return']:.2%}")
    console.print(f"Benchmark return: {result['comparison_test']['benchmark_total_return']:.2%}")
    console.print(f"Excess return: {result['comparison_test']['excess_return']:.2%}")
    console.print(f"Sharpe: {result['test_metrics']['sharpe']:.2f}")
    console.print(f"Max drawdown: {result['test_metrics']['max_drawdown']:.2%}")
    console.print(f"Output directory: {result['output_dir']}")
    return result


@research_app.command("run")
def research_run(config: Annotated[Path, typer.Option(help="Multi-asset research YAML")]) -> None:
    """Run a multi-asset research experiment."""
    _run_research_config(config)


@research_app.command("compare")
def research_compare(
    config: Annotated[Path, typer.Option(help="Multi-asset research YAML")],
) -> None:
    """Run an experiment and print benchmark comparison."""
    _run_research_config(config)


@research_app.command("robustness")
def research_robustness(
    config: Annotated[Path, typer.Option(help="Multi-asset research YAML")],
) -> None:
    """Run configured robustness diagnostics for an experiment."""
    _run_research_config(config)


if __name__ == "__main__":
    app()
