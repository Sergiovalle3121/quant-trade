# Safe ML Alpha Lab

Phase 13 adds a research-only supervised learning lab for deterministic baseline experiments. It does not implement live trading, broker orders, online learning, reinforcement learning, deep learning, or auto-deployment. All artifacts set `real_money_ready=false`.

Workflow: canonical OHLCV data, past-only features, forward labels, chronological split, baseline model, out-of-sample evaluation, research backtest, reports, and static dashboard.

Run:

```bash
quant-trade ml run --config configs/ml/ml_baseline_synthetic.yaml
```

Outputs are written under `outputs/ml/<run_id>/` and must be interpreted as model-risk evidence, not profitability evidence.
