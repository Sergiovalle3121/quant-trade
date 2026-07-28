.PHONY: install test lint format backtest-sample v7-artifacts v8-artifacts

install:
	pip install -e '.[dev]'

test:
	python -m compileall -q src tests
	pytest -q

lint:
	ruff check .
	mypy src

format:
	ruff format .
	ruff check . --fix

backtest-sample:
	quant-trade backtest --strategy sma_crossover --data examples/data/sample_ohlcv.csv --initial-cash 10000

v7-artifacts:
	python -m quant_trade.v7_artifacts --source-commit-sha "$(SOURCE_COMMIT_SHA)"

v8-artifacts:
	quant-trade v8 revenue-run --source-commit-sha "$(SOURCE_COMMIT_SHA)" --verify-determinism
