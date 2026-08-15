# Binance BTC/ETH TSMOM development verdict

Status: **NO_GO**

This is a development falsification, not out-of-sample evidence and not a
trading authorization. The raw Binance bars remain local and uncommitted. The
evaluator is offline, verifies their byte hashes, refuses a collection whose
declared window extends beyond 2023-11-28, and can return only `NO_GO` or
`INSUFFICIENT_EVIDENCE`.

## Frozen rule evaluated

- Strategy: `binance_btc_eth_tsmom_long_cash_v1`
- Final prospective spec seal:
  `8f59ede2dce8814dc0863f7f842613b35495df851c2b0ee639b3a10038be2eb7`
- Venue/data: Binance Spot daily BTCUSDT and ETHUSDT
- Raw data window: 2017-08-17 through 2023-11-28
- Evaluation decisions: 2018-08-31 through 2023-11-28
- Costs: 15 bps per side; stress at 30 bps per side and 50% target fills
- Execution: decision at month-end close, earliest fill at next daily open
- Signal observations: 63 complete decision months and 17 state transitions

Input byte hashes:

- Journal: `87f456019d52f325161f82ab20c85dcfb197b61c00ba37aad728141ff22dbd28`
- BTCUSDT series: `d346550d10c3fc373c7645f1f048bacd89b6f446b6a03e6d589a74231efa636a`
- ETHUSDT series: `c98d61902b6d6f730bf8ec2773885bc9c691928d4d1fda4b2987ac8337826b2c`
- Combined evidence digest: `d78ecc933d68a9093628a5df99b87040ff2692eacd6a3d2e28607431ff9828a3`

## Result

| Scenario | Total return | CAGR | Max drawdown |
|---|---:|---:|---:|
| Strategy, 15 bps/side | 417.68% | 36.81% | -58.34% |
| BTC buy-and-hold | 438.60% | 37.85% | -76.63% |
| ETH buy-and-hold | 626.59% | 45.95% | -79.30% |
| BTC/ETH 50/50 buy-and-hold | 532.60% | 42.14% | -76.85% |
| Strategy stress, 30 bps/side + 50% fills | 224.11% | 25.13% | -48.22% |

The strategy failed every overall benchmark, exceeded the sealed 25% absolute
drawdown ceiling, beat BTC in only 1 of 4 contiguous blocks, and beat the
50/50 basket in only 2 of 4; the requirement was at least 3 of 4 against both.
The positive stress return does not override those failures.

Canonical development report SHA-256:
`6df2b74b161ffed24ec98613de54991d16a79b8881c3d72c5acb97ebca362389`

## Decision

Do not start this campaign's prospective holdout, Demo promotion, shadow run,
or canary. Retain its spec and evaluator only as auditable negative evidence.
Do not change the 12-month lookback or add variants in response to this result;
any new hypothesis must be a separately budgeted campaign with a new future
holdout.

The signal and benchmark set were sealed before the first diagnostic, while
the acceptance fields were made machine-readable afterward from criteria
already stated in the task. For that reason, even a favorable result would not
have been confirmatory. The observed result is nevertheless an unambiguous
falsification under the final conservative criteria.
