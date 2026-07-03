# ML Leakage Prevention

The ML lab requires past-only features, forward-shifted labels, chronological splits, no random shuffling, and optional embargo days. Feature names containing future-looking terms such as `future`, `forward`, `label`, `target`, or `next` fail leakage checks.

The leakage report is saved as `leakage_report.json` with `real_money_ready=false`. Passing leakage checks does not prove profitability or live readiness.
