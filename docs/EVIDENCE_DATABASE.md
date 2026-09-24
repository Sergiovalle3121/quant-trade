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

## Investment-manager due diligence use case

The evidence database addresses a concrete institutional problem: research
results are often separated from the exact files reviewed by risk, operations
and investment committees. A scorecard therefore re-hashes every indexed file
when it is built. Deleted, unreadable or modified artifacts are blocking
issues and cannot contribute evidence merely because an old database row still
exists. Re-ingestion is required after an intentional artifact change, making
the reviewed bytes explicit and auditable.

Category credit also requires semantic metadata defined by
`metadata_requirements` in the scorecard policy. Each inner list is a set of
accepted alternatives and every listed group must be satisfied. For example,
research quality requires both a strategy identity and a dataset binding;
renaming an arbitrary file to `metrics.json` cannot satisfy that category.
Nested JSON metadata is retained with depth and item limits while secret-like
keys and values remain redacted.

This supports reproducible model-risk and vendor due diligence; it does not
certify returns, authorize capital, or imply that the software has a particular
commercial valuation. A buyer must still assess security, support, licensing,
data rights, deployment, independent validation and fitness for its mandate.
