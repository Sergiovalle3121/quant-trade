"""Command line interface for research backtests."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.backtest.engine import BacktestEngine
from quant_trade.config import get_settings
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.logging_config import configure_logging
from quant_trade.research.experiment_config import load_experiment_config
from quant_trade.research.grid_search import run_grid_search
from quant_trade.research.runner import run_experiment
from quant_trade.research.walk_forward import run_walk_forward
from quant_trade.strategies import STRATEGY_REGISTRY, get_strategy

app = typer.Typer(help="Research-only quantitative trading tooling.")
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


if __name__ == "__main__":
    app()
