FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
RUN pip install --no-cache-dir .
CMD ["quant-trade", "backtest", "--strategy", "sma_crossover", "--data", "examples/data/sample_ohlcv.csv", "--initial-cash", "10000"]
