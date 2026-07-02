# Quant Trade

Quant Trade is a Python 3.11+ foundation for an AI-assisted quantitative trading research platform. It is intentionally limited to deterministic research and backtesting. It is **not** a guaranteed money machine, does not claim profitability, and does not implement real-money trading.

## Safety Scope

- No broker APIs, live execution, paid data feeds, API keys, or secrets are included.
- Current functionality is limited to local CSV data, educational baseline strategies, risk checks, metrics, and a simple long-only backtest engine.
- Backtests can be misleading because of overfitting, bad assumptions, costs, slippage, survivorship bias, and lookahead bias.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
quant-trade backtest --strategy sma_crossover --data examples/data/sample_ohlcv.csv --initial-cash 10000
```

With `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Development Commands

```bash
make install
make lint
make test
make backtest-sample
```

## System Modules

- `data`: CSV OHLCV loading and validation.
- `strategies`: research-only baseline signal generators.
- `backtest`: deterministic long-only simulation with next-bar execution approximation.
- `risk`: first-pass position sizing and cash constraints.
- `metrics`: returns, volatility, drawdown, Sharpe, Sortino, trade counts, and exposure.
- `cli`: Typer command line interface.

## Roadmap

Future phases may add richer data ingestion, research workflows, research-quality backtesting, paper trading, broker execution, monitoring, cloud deployment, and portfolio allocation. Integrations such as NautilusTrader, Interactive Brokers, Alpaca, Binance, Polygon, Databento, and AWS are future-only and are not implemented here.
