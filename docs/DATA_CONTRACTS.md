# Data Contracts

Dataset contracts define required columns, minimum row counts, missing-data limits, duplicate policy, timezone policy, expected interval, allowed symbols, price validation, volume validation, gap policy, and stale-data thresholds.

The default ETF contract is in `configs/datalake/daily_etf_dataset_contract.yaml`. Contract validation is deterministic and offline. Missing evidence or invalid data should fail conservatively.
