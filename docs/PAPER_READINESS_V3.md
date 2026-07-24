# Paper Readiness V3

Research/paper only. `REAL_MONEY: NO-GO`. Nothing here connects to a live broker
or sends an order (paper or otherwise) during tests.

## 1. Realistic execution is mandatory for promotable evidence

Closed in the statistical-integrity work and enforced by the conservative V2
gate (`configs/selection/conservative_v2.yaml`,
`quant_trade.research.promotion_v2`):

- The multi-asset runner stamps the exact execution policy **and its hash** into
  `results.json` (`execution_policy.specified`, `execution_policy.hash`), and
  applies the *same* policy to the strategy and the benchmark
  (`applied_to_benchmark: true`).
- The promotion gate requires `execution_policy_specified`; a run whose config
  omits an execution policy (i.e. unlimited fills) is **NOT PROMOTABLE**.
- Cost-sensitivity and walk-forward reuse the same policy, and the gate also
  requires fill-rate ≥ 90% and incomplete-order rate ≤ 10%.

There is no fallback to unlimited fills for a candidate.

## 2. Parity report (`quant_trade.paper.parity`)

`compare_executions` and `three_way_parity` compare **backtest vs simulated
paper vs broker paper** field by field:

- target weights, order quantities;
- fills, fill prices/timestamps, fees, slippage, partial fills, cancellations;
- final positions, cash, equity, and equity/position drift.

Each field is classified `match` / `within_tolerance` / `divergence` with an
**explanation** (e.g. "fee models differ", "partial-fill counts differ:
participation limits or liquidity"). The broker-paper record is built from
*recorded* fills — a fixture in tests, a real Alpaca-Paper session log in
production — never a live call.

## 3. Readiness V3 (`quant_trade.paper.readiness`)

`evaluate_paper_readiness` validates the operational prerequisites, fail-closed:

- config present; **broker paper-only** (live trading off);
- exporter, crash recovery, kill switch, orphan detection;
- a positive heartbeat interval; position/cash reconciliation.

Final status is `READY_FOR_PAPER_TRIAL` or `NOT_READY`. It **does not claim any
trial has run** — `trial_days_completed` is always 0 here — and
`real_money_authorized` is always false. `generate_paper_runbook` emits a
markdown runbook with a manual pre-flight checklist, operating procedure, and
abort conditions.

## Status

`PAPER_READINESS: READY` for a *supervised paper trial* once a config passes the
checks — never a real-money authorization. The 90-day trial itself has not been
run and is not represented as having run.
