# quant-trade

Educational, research-only backtesting toolkit focused on reproducibility, out-of-sample evaluation, realistic costs, and anti-overfitting workflow. It does **not** implement live trading, broker connectivity, paid data APIs, secrets, or profitability claims.

## Install

### uv
```bash
uv venv
uv pip install -e '.[dev]'
```

### Standard venv + pip
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If package index/proxy access fails, retry on a network with PyPI access or configure your corporate proxy. Do not vendor credentials or tokens into this repository.

## Commands
```bash
make install       # editable install with dev tools
make test          # pytest -q
make lint          # ruff check .
make typecheck     # mypy src
make sample        # buy-and-hold sample backtest
```

Direct CLI examples:
```bash
quant-trade backtest --strategy buy_and_hold --data examples/data/sample_ohlcv.csv --initial-cash 10000
quant-trade run-experiment --config configs/sma_crossover_sample.yaml
quant-trade grid-search --config configs/sma_grid_search_sample.yaml
quant-trade walk-forward --config configs/sma_walk_forward_sample.yaml
```

When running from a source checkout without installing, use `PYTHONPATH=src python -m quant_trade.cli ...`.

## Outputs
Experiment artifacts are written below `outputs/<experiment_name>` or a numbered sibling if the directory already exists. Standard experiments include `config_used.yaml`, train/test metrics JSON, test trades/equity CSV files, and `summary.md`. Grid search and walk-forward runs write their own CSV/JSON summaries.

## Research cautions
Costs, slippage, spread, overfitting, and data mining can destroy apparent edge. Always compare to buy-and-hold and evaluate out-of-sample after costs.
