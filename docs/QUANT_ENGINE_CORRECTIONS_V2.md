# Quant engine corrections V2

## Scope

This change hardens multi-asset cash accounting and transaction-cost sizing.
It does not enable live trading or claim profitability.

## Confirmed defect

The previous engine calculated target notionals from pre-cost equity and then
executed them in symbol order. A 100% target could therefore spend all cash on
notional and push cash negative when commission, slippage, or spread was
deducted. A rebalance could also buy before sale proceeds were available.

## Corrected execution sequence

1. Decisions formed at bar `t` remain eligible no earlier than bar `t+1`.
2. The execution price is the observable next-bar open. A missing open is not
   replaced by that bar's close.
3. Orders are split into exposure-reducing and exposure-increasing legs.
4. Long reductions and other sales execute before buys/covers.
5. For `allow_leverage=false`, a deterministic 60-step bisection scales
   exposure-increasing quantities to satisfy both available cash and gross
   exposure. Integer-share mode truncates each candidate quantity.
6. The engine verifies finite positive equity after fills and accounting.

Fixed/minimum commissions make cost functions discontinuous near zero. If no
positive order size is affordable, the deterministic result is no fill rather
than negative cash.

## Cost contract

All `CostModel` fields must be finite and non-negative. Frictionless execution
remains available only by explicitly passing `CostModel()`; omitted costs still
resolve to the conservative default.

## Golden regression

The multi-asset momentum golden file was intentionally updated. The new engine
reserves costs and therefore invests slightly less notional. On the bundled
synthetic fixture, total return changes from `0.16020043003216378` to
`0.16019026951525728`; minimum cash is `0.0` and maximum gross exposure is
`1.0`. Tolerances were not relaxed.

## Remaining work

Order persistence, partial fills, bar-volume participation, latency, explicit
reject/defer records, lot sizes, and a shared backtest/paper order-state
contract belong to the next execution-model phase. Missing opens currently
produce no fill for that decision; there is no silent close-price fallback.

