.PHONY: install install-pip test lint typecheck sample experiment grid walk clean
PYTHON ?= python

install:
	$(PYTHON) -m pip install -e '.[dev]'

install-pip:
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src

sample:
	PYTHONPATH=src $(PYTHON) -m quant_trade.cli backtest --strategy buy_and_hold --data examples/data/sample_ohlcv.csv --initial-cash 10000

experiment:
	PYTHONPATH=src $(PYTHON) -m quant_trade.cli run-experiment --config configs/sma_crossover_sample.yaml

grid:
	PYTHONPATH=src $(PYTHON) -m quant_trade.cli grid-search --config configs/sma_grid_search_sample.yaml

walk:
	PYTHONPATH=src $(PYTHON) -m quant_trade.cli walk-forward --config configs/sma_walk_forward_sample.yaml

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache outputs
