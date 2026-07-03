# Data Lake v2

Phase 15 adds a local, versioned research data lake for reproducible offline backtesting datasets. It is paper/research only and does not include live trading, broker connectivity, paid data calls, or secrets.

Generated CSV datasets, manifests, and snapshots live under `data/lake/` and are ignored by git except placeholder README files.

Core commands:

```bash
quant-trade datalake register --config configs/datalake/local_datalake.yaml --data-path local.csv
quant-trade datalake snapshot --dataset-id sample_daily_etf --config configs/datalake/local_datalake.yaml
quant-trade datalake validate --dataset-id sample_daily_etf --contract configs/datalake/daily_etf_dataset_contract.yaml
quant-trade datalake versions --dataset-id sample_daily_etf --config configs/datalake/local_datalake.yaml
quant-trade datalake diff --dataset-id sample_daily_etf --from-version v1 --to-version v2 --config configs/datalake/local_datalake.yaml
quant-trade datalake quality --dataset-id sample_daily_etf --config configs/datalake/local_datalake.yaml
quant-trade datalake dashboard --config configs/datalake/local_datalake.yaml
```

Artifacts are written to `outputs/datalake/<run_id>/`.
