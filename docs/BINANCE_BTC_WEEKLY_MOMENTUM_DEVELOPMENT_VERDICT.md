# Binance BTC weekly momentum: development verdict

## Outcome

**NO-GO** for `binance_btc_weekly_momentum_1w_long_cash_v1`.

The only sealed trial earned a positive net return in the development sample,
but it failed the two economically important tests: it did not beat BTC
buy-and-hold in any of four contiguous blocks and its 80.84% maximum drawdown
far exceeded the sealed 25% limit. No parameter variant was tried after seeing
this result. This report is development-only and authorizes neither promotion,
live execution nor real-money trading.

Report SHA-256:
`ffb42188d7d9a35dd79a1c8d876f4af1201de951e192f0fcd11b92f9e8a3203d`.

## Frozen experiment

- Venue/instrument: Binance Spot, `BTCUSDT` only.
- Evidence: daily UTC bars from 2017-08-17 through the exact hard cutoff
  2023-11-28.
- Decisions: 327 scheduled Sundays, 2017-08-27 through 2023-11-26; 326
  following outcome weeks are complete at the evidence cutoff. The last
  executable decision is right-censored and is not counted as independent
  evidence.
- Signal: prior exact seven-calendar-day BTC return; strictly positive means
  LONG, otherwise CASH; no missing-reference fallback.
- Execution: decision at Sunday close, earliest fill at Monday `t+1` open.
- Signals/transitions: 165, comprising 82 completed LONG-to-CASH episodes.
- Normal costs: 15 bps per side.
- Stress: 30 bps per side and 50% LONG fills; CASH exits remain complete.
- Benchmarks: BTC/USDT buy-and-hold and zero-yield cash, evaluated under the
  same scenario.

## Results

| Scenario | Portfolio | Net return | CAGR | Sharpe | Max drawdown | Costs | Fills |
|---|---|---:|---:|---:|---:|---:|---:|
| Normal | Weekly LONG/CASH | 255.73% | 22.38% | 0.645 | -80.84% | $54,798.33 | 165 |
| Normal | BTC buy-and-hold | 776.15% | 41.26% | 0.843 | -83.19% | $149.78 | 1 |
| Normal | Cash | 0.00% | 0.00% | 0.000 | 0.00% | $0.00 | 0 |
| Stress | Weekly LONG/CASH | 121.47% | 13.49% | 0.587 | -57.98% | $40,191.23 | 165 |
| Stress | BTC buy-and-hold | 388.58% | 28.72% | 0.735 | -72.04% | $150.00 | 1 |
| Stress | Cash | 0.00% | 0.00% | 0.000 | 0.00% | $0.00 | 0 |

Normal-scenario block outperformance was 0/4 against BTC buy-and-hold and 2/4
against cash; the sealed requirement was at least 3/4 against each benchmark.
There were zero same-bar fills.

The strategy's smaller drawdown than buy-and-hold does not rescue it: an
80.84% loss from peak is still more than three times the absolute 25% risk
ceiling, and the strategy surrendered 520.42 percentage points of total return
relative to holding BTC.

## Blocking reasons

1. `NORMAL_RETURN_DOES_NOT_EXCEED_BTC_USDT_BUY_AND_HOLD`
2. `OUTPERFORMS_BTC_USDT_BUY_AND_HOLD_IN_0_OF_4_BLOCKS`
3. `OUTPERFORMS_ZERO_YIELD_CASH_IN_2_OF_4_BLOCKS`
4. `NORMAL_MAX_DRAWDOWN_EXCEEDS_0.250000_ABS`
5. `PBO_NOT_IDENTIFIABLE_FOR_SINGLE_TRIAL`
6. `ONE_ASSET_POLICY_CONFLICTS_WITH_GATE4_DIVERSIFICATION`
7. `DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_LIVE_EXECUTION`

## Evidence bindings

| Artifact | SHA-256 |
|---|---|
| Sealed strategy spec | `a1a896f4609e4c8283b114404f415d29f97404ed4a50e27cc8393029db8df910` |
| Dataset binding | `b30563248d27cb53ab24c5b018d65b95d3b35641a380c25c475511cdb50a9708` |
| Journal | `cc0290f029f825ebe5bfde1782c69984f7a1dd7454f3eb1e1e1f244096f5066b` |
| Receipts | `5b0d76cd0565b4f9df44c50423bb6ab3d566373266fec76e1f594c6331657396` |
| BTC series | `3d569ef3089f380c5efaa2fa48f8e39539118105ca83173681ab6da6449ce316` |
| Binance collection policy | `19360169137ef223e34cbdddb08155cb840685967785565753da6a0824da2392` |

Before opening the series, the evaluator verifies the hash-chained journal,
the exact window and symbol, current request policy containing Binance
`endTime`, and the live receipt chain. It then verifies contained raw paths,
raw-byte hashes, request-side cutoff, normalized-page hashes, journal-to-receipt
SHA order, and a byte-exact LF series rebuild. A future row, mixed cache,
legacy policy, missing day, non-BTC symbol, synthetic receipt, or changed byte
returns `INSUFFICIENT_EVIDENCE` without calculating P&L.

## Decision

Retire this exact weekly BTC LONG/CASH rule. Do not optimize its threshold,
lookback, weekday, costs or exposure after observing this result; doing so
would create undeclared trials. A genuinely different hypothesis requires a
new literature rationale, new sealed specification, separate trial-ledger
entry and untouched evidence. This result provides no basis to deposit $200 or
place an order.
