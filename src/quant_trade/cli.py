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
from quant_trade.strategies.mean_reversion import MeanReversionStrategy
from quant_trade.strategies.sma_crossover import SmaCrossoverStrategy

app = typer.Typer(help="Research-only quantitative trading tooling.")
console = Console()


def _build_strategy(name: str):
    if name == "sma_crossover":
        return SmaCrossoverStrategy()
    if name == "mean_reversion":
        return MeanReversionStrategy()
    raise typer.BadParameter("strategy must be one of: sma_crossover, mean_reversion")


@app.command()
def backtest(
    strategy: Annotated[str, typer.Option(help="Strategy name: sma_crossover or mean_reversion")],
    data: Annotated[Path, typer.Option(help="Path to OHLCV CSV data")],
    initial_cash: Annotated[float, typer.Option(help="Initial cash for the simulation")] = 10_000.0,
) -> None:
    """Run a deterministic long-only sample backtest."""
    configure_logging(get_settings().log_level)
    frame = load_ohlcv_csv(data)
    strategy_instance = _build_strategy(strategy)
    result = BacktestEngine(initial_cash=initial_cash).run(frame, strategy_instance)

    table = Table(title="Quant Trade Backtest Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    metrics = result.metrics
    table.add_row("Strategy", strategy_instance.name)
    table.add_row(
        "Date range", f"{frame['timestamp'].min().date()} to {frame['timestamp'].max().date()}"
    )
    table.add_row("Initial cash", f"${initial_cash:,.2f}")
    table.add_row("Final equity", f"${result.equity_curve['equity'].iloc[-1]:,.2f}")
    table.add_row("Total return", f"{metrics['total_return']:.2%}")
    table.add_row("Sharpe", f"{metrics['sharpe']:.2f}")
    table.add_row("Max drawdown", f"{metrics['max_drawdown']:.2%}")
    table.add_row("Number of trades", str(metrics["number_of_trades"]))
    console.print(table)


if __name__ == "__main__":
    app()
