# Codex V7 Worklog

## Checkpoint 1 — baseline and reproduction

- UTC: `2026-07-25T03:00:00Z`
- `BASE_SHA`: `98daabe6585bfa80d7706a61c8742d5da8ac9ea3`
- Baseline on Windows/Python 3.12.13: **617 passed, 25 failed**.
- All 25 failures shared one root cause: unconditional POSIX `fcntl` import.
- Confirmed provenance, PBO-label, mining annualization and fictitious
  market-price defects.
- Decision: preserve the V6 Linux result as historical context but use the
  reproduced Windows baseline for this sprint.

## Checkpoint 2 — provenance, ledger and statistics

- UTC: `2026-07-25T04:30:00Z`
- Added cross-platform exclusive locking and fail-closed receipt/panel rebuild.
- Added full Bybit funding pagination and exact-range audit.
- Routed performance statistics to marked-equity ledger returns.
- Added settlement-driven signals, CSCV PBO and global hash-chained trials.
- Focused validations: provenance **22 passed**; economic ledger **15 passed**;
  statistical/carry campaign **63 passed**.
- Economic evidence: 0 real settlements; fixtures remained non-promotable.

## Checkpoint 3 — mining, board and shadow

- UTC: `2026-07-25T05:30:00Z`
- Enforced current AWS/Alibaba hashing blocks while allowing control plane.
- Added native Decimal units and complete compute-rental risk outputs.
- Added byte-verifying scanner paths and marketplace discovery importer.
- Removed mining `×8766`, weighted paper allocation, hardened shadow WAL and
  paper order reference marks/idempotency.
- Focused mining and board/shadow/paper regression suites were green.
- Economic decision: zero eligible non-cash rows; keep 100% in paper cash.

## Checkpoint 4 — reproducibility and release controls

- UTC: `2026-07-25T06:00:00Z`
- Added one-command deterministic generation for all V7 JSON outputs.
- Captured and clean-rebuilt 5 public Bybit pages locally: 41 panel rows and
  6 real settlements. The market cache remains uncommitted and non-promotable.
- Added Python 3.11/3.12 CI matrix, Ruff, V7 format check, mypy, compileall,
  full pytest and diff-whitespace validation.
- Regeneration integration: two independent directories produce identical
  SHA-256 maps.
- Remaining engineering blocks are listed in
  `docs/REVENUE_VALIDATION_V7_REPORT.md`; each is technically non-promotable.

## Safety ledger

| Action | Count |
|---|---:|
| Live orders submitted | 0 |
| Wallets or transactions signed | 0 |
| Deposits / hashrate purchases | 0 |
| Miners started | 0 |
| AWS resources created | 0 |
| Alibaba resources created | 0 |
| External spend authorized | 0 |

Final test, PR, CI and merge identifiers belong to the GitHub release record;
they are not hard-coded into deterministic source artifacts.
