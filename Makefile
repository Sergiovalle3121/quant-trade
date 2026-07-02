.PHONY: install test lint format backtest-sample

install:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .
	mypy src

format:
	ruff format .
	ruff check . --fix

backtest-sample:
	quant-trade backtest --strategy sma_crossover --data examples/data/sample_ohlcv.csv --initial-cash 10000
