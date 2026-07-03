# Evidence Database

Phase 12 adds a local, offline SQLite evidence database for research governance. It stores sanitized metadata and checksums for research runs, paper trials, trial reviews, operations reports, stress tests, allocation decisions, incidents, alerts, generic artifacts, evidence links, and scorecards.

Safety constraints:
- Research/backtesting and simulated paper evidence only.
- No live trading, order routing, broker submission, secrets, or network access.
- Local database files live under `data/evidence/*.sqlite` and are ignored by git.

Common commands:

```bash
quant-trade evidence init --config configs/evidence/local_evidence_db.yaml
quant-trade evidence ingest --config configs/evidence/local_evidence_db.yaml --path outputs
quant-trade evidence search --config configs/evidence/local_evidence_db.yaml --query drawdown
```

Ingestion computes SHA-256 checksums, detects artifact type from path and metadata, infers a strategy id, skips likely secret-bearing files, and records malformed text artifacts conservatively.
