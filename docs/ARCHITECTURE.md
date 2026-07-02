# Architecture

`quant_trade.backtest` contains deterministic portfolio simulation, metrics, and the configurable transaction `CostModel` for fixed, percentage, slippage, minimum commission, and spread assumptions.

`quant_trade.strategies` contains pure signal generators: SMA crossover, mean reversion, and buy-and-hold benchmark.

`quant_trade.research` contains validated experiment configs, chronological/date/walk-forward splits, experiment runner, grid search, and walk-forward evaluation. Time-series data is never shuffled because that leaks future information into model selection.

`quant_trade.reporting` writes standardized artifacts with pathlib and avoids silently overwriting prior runs by creating numbered run directories.
