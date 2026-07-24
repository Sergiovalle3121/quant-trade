# Claude Fable V5 Sprint Worklog — Profit Discovery

Objective: turn the platform into an opportunity-discovery engine — close the
remaining economic false positives, run reproducible campaigns on available
real data, and rank trading / rented-mining / cash honestly. No live orders,
no miners, no cloud resources, no spend.

Safety posture held: `REAL_MONEY: NO-GO` · `LIVE_ORDER_SUBMISSION: DISABLED` ·
`MINER_EXECUTION: DISABLED` · `MINING_HARDWARE_CONTROL: DISABLED` ·
`WALLET_SIGNING: DISABLED` · `AWS_RESOURCES_CREATED: FALSE` ·
`ALIBABA_RESOURCES_CREATED: FALSE` · `EXTERNAL_SPEND_AUTHORIZED: FALSE`

## CP0 — 2026-07-24T19:55Z — baseline + P0 red tests

- **Observed-state correction:** the prompt assumed PR #41 open; it was merged
  at the owner's order as `f3be7a8` before this sprint. Base rule 2 applies:
  branch `claude/profit-discovery-v5` from `origin/main` = `f3be7a8`.
- **Baseline (executed on `f3be7a8`):** ruff pass · mypy pass (235 files) ·
  compileall OK · diff-check OK · **pytest 538 passed**.
- **Network probe:** Bybit and OKX public funding endpoints return proxy 403
  (`CONNECT tunnel failed`) from this sandbox. Live backfill will be recorded
  as `NOT_RUN` with this verifiable error; adapters are built and tested
  offline per the sprint mandate.
- **P0 red tests** (`tests/test_v5_defect_reproduction.py`, xfail strict, 3):
  - **A** mixed symbols (BTC/ETH alternating) and mixed venues (binance/okx)
    in one store flow into ONE return series — cross-instrument "price moves"
    become fake basis P&L; campaign must fail closed on mixed identity.
  - **B** 90 five-minute polls of the same 8h funding rate accrue ~90× the
    funding a position could actually collect (one settlement).

Next: V5-1 instrument identity + poll/settlement event semantics.
