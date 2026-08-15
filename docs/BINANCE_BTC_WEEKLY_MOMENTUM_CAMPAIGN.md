# Binance BTC weekly momentum campaign

Status: **DEVELOPMENT NO-GO, RETIRED, RESEARCH ONLY**

`binance_btc_weekly_momentum_1w_long_cash_v1` is one new prospective
falsification campaign. It is independent of H1-H4 and of the retired
`binance_btc_eth_tsmom_long_cash_v1` monthly campaign. The monthly `NO_GO`
cannot be erased, relabelled, or treated as a free parameter search for this
weekly rule.

The canonical declaration is
`configs/experiments/binance_btc_weekly_momentum_1w_long_cash_v1.yaml`; its
seal is:

```text
a1a896f4609e4c8283b114404f415d29f97404ed4a50e27cc8393029db8df910
```

The declaration was sealed before the fresh request-bound development dataset
was evaluated. The frozen rule subsequently failed its development gates; see
`docs/BINANCE_BTC_WEEKLY_MOMENTUM_DEVELOPMENT_VERDICT.md`. It must not be
re-parameterized or promoted. It has no generic
runner, CLI, strategy-registry entry, live adapter, credential field, or order
router.

The declaration and verdict first appeared together in the current uncommitted
working tree. The content seal detects later edits, but there is no independent
Git timestamp proving preregistration. That provenance limitation does not
rescue the negative result; it does prohibit describing any future continuation
as prospectively preregistered from this artifact alone.

## External motivation and translation risk

Liu and Tsyvinski report that current weekly cryptocurrency-market returns
predict future cryptocurrency-market returns. The published paper is
[*Risks and Returns of Cryptocurrency*](https://doi.org/10.1093/rfs/hhaa113);
the corresponding [NBER working paper](https://www.nber.org/papers/w24877)
describes the Sunday-to-Sunday UTC weekly horizon.

This campaign is **not an exact replication**. The source result studies a
coin-market return and predictive regressions/sorts. This implementation makes
three additional, predeclared translations:

1. Binance `BTCUSDT` is used as a narrow proxy rather than the paper's market
   index.
2. The predictor is converted into a binary rule: weekly return strictly above
   zero means `LONG`; zero or negative means `CASH`.
3. A Sunday close intention is executed no earlier than the next daily bar's
   Monday open, with explicit costs.

A development failure refutes this translation. A success would only justify
prospective observation; it would not prove the paper, profitability, or live
readiness.

## Frozen signal

For each UTC Sunday daily close `t`:

```text
weekly_return(t) = close(t) / close(t - 7 calendar days) - 1
LONG  if weekly_return(t) > 0
CASH  if weekly_return(t) <= 0
```

The reference must be the exact previous Sunday. A missing reference produces
no signal and cannot fall back to an older price. Only initialization and
state changes emit intentions; continuing `LONG` exposure is not rebalanced.
Each intention records `t + 1 day` as its earliest execution and always carries
`real_money_authorized=false`.

## Development boundary

The only permitted development envelope is:

- Binance Spot `BTCUSDT`, daily UTC bars;
- data from 2017-08-17 through 2023-11-28;
- first possible decision 2017-08-27;
- last decision 2023-11-26 and earliest final fill 2023-11-27;
- 15 bps per side normally; 30 bps under stress;
- BTC buy-and-hold and zero-yield cash as like-for-like benchmarks.

BTC was fetched again into a new, isolated directory. Every Binance request
carried the 2023-11-28 request-side `endTime`; the evaluator verified the final
journal, receipts, policy digest, series hash, exact gap-free calendar, and an
LF byte-for-byte rebuild before calculating P&L. The earlier local collection
was produced under an older URL policy without `endTime` and was not used as
evidence for the verdict.

The development evaluator may only return `NO_GO` or
`INSUFFICIENT_EVIDENCE`. It cannot promote a candidate. The rule is falsified
if it fails any frozen benchmark overall, fails either benchmark in more than
one of four contiguous blocks, exceeds 25% drawdown, has fewer than 300
completed decisions or 30 independent trades, or becomes negative under the
2x-cost/50%-LONG-fill stress. CASH exits remain complete in stress so a losing
position cannot be trapped to improve the result.

## Prospective calendar

The future observation period does not use the reserved 2023-11-29 through
2026-08-16 history as warm-up:

| Event | UTC date |
|---|---|
| Observation starts | 2026-08-17 |
| First reference Sunday | 2026-08-23 |
| First decision Sunday | 2026-08-30 |
| Earliest first fill Monday | 2026-08-31 |
| Primary decision 104 | 2028-08-20 |
| Primary outcome week complete | 2028-08-27 |
| Final decision 156 | 2029-08-19 |
| Final outcome week complete | 2029-08-26 |
| Earliest economic reveal | 2029-08-27 |

The 52-decision extension is committed before results. There is no economic
reveal, parameter change, or stop decision at the primary checkpoint. Missing
evidence means continuing the sealed extension without reveal.

## Known blockers and US$200

This campaign cannot currently progress to real money even if its future
returns are favourable:

- **Gate 0:** the repository's operational venue policy is sealed to Bybit
  Demo. A separate reviewed Binance Demo policy does not exist.
- **PBO:** one trial cannot identify probability of backtest overfitting, while
  PBO remains mandatory. The maximum honest verdict is therefore
  `INSUFFICIENT_EVIDENCE` without new, ex-ante governance.
- **Gate 4:** a one-asset 100% research target contradicts the live ceiling of
  5% per asset and minimum 20 distinct assets. The campaign cannot weaken that
  gate.
- **Execution:** the research engine does not yet bind each simulated order to
  current Binance tick, step, minimum-notional, account fee, and rejection
  evidence.

US$200 can be used as a percentage-return scale in an offline simulation, but
that does not establish that a real US$200 order is executable or prudent. If
US$200 is all risk capital, the existing policy permits at most a US$20
canary. If US$200 is the canary, it requires at least US$2,000 total risk
capital. In both cases, this BTC-only 100% allocation remains incompatible with
Gate 4 and `real_money_authorized=false`.
