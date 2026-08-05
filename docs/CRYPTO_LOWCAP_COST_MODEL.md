# Real-cost model for low/mid-cap crypto — measured, with evidence classes

Session A, Block 4. Costs come **before** any strategy design: in ETFs,
turnover at minimal costs killed all five baselines; here every friction is an
order of magnitude larger, so the viable-turnover bound below is a design
constraint, not a tuning parameter.

Implementation: `quant_trade/costs/` (`orderbook.py` walk-the-book math,
`crypto_lowcap.py` model + measured calibration, `measure.py` the live
measurement runner). Evidence vocabulary is the repo's existing
`v9/cost_evidence.py` scale; "MEASURED" below = `REAL_PUBLIC_RETAIL`
(public data, raw bytes archived content-addressed, sha256 recorded).

## What was measured, and how (MEASURED)

On 2026-08-05T05:36Z, 57 Bybit spot order books (`/v5/market/orderbook`,
depth 200) were sampled: 12 symbols per market-cap tier (9 measurable in
mega), chosen by descending market cap from the 2026-08-03 CMC point-in-time
snapshot, stablecoins excluded (declared filter). For each book: half-spread,
and the round-trip execution cost of market orders of $100–$10,000 computed
by walking visible levels against mid — so slippage *includes* the
half-spread, and fees are kept separate (nothing double-counts). A notional
the visible book cannot fill is **None — not executable**, never
extrapolated. Raw pages + ingestion receipts live under
`data/cache/crypto_costs/2026-08-05/` (git-ignored); the measurement manifest
is committed at `data/evidence/crypto_costs/measurement-2026-08-05.json`,
sha256 `b983be0daefb1cccff6df38e0a688bc022c5151e27662b1b612cfa5461bb5928`.

Round-trip execution cost vs mid (bps, p50 with p75 in brackets):

| Tier (mcap) | n | half-spread | $1,000 | $5,000 | $10,000 |
|---|---|---|---|---|---|
| mega (>$10B) | 9 | 0.7 [0.8] | 1.4 [1.9] | 2.7 [3.7] | 4.1 [5.3] |
| large ($1–10B) | 12 | 1.3 [2.7] | 6.8 [9.3] | 11.3 [16.1] | 15.7 [20.8] |
| mid ($100M–1B) | 12 | 2.6 [7.4] | 14.8 [23.7] | 27.2 [47.0] | 43.9 [57.9] |
| low ($10–100M) | 12 | 3.7 [5.3] | 23.3 [25.4] | 52.5 [68.6] | 88.2 [142.3]¹ |
| micro ($1–10M) | 12 | 11.7 [18.8] | 59.5 [124.6] | 229.0 [373.5]² | 223.1 [326.4]³ |

¹ 92% of low-tier books could fill $10k. ² 92% could fill $5k. ³ Only 75% of
micro books could fill $10k, and the p50 sits *below* the $5k p50 because the
books that cannot fill $10k drop out of that quantile — a composition effect;
always read cost quantiles together with the executable fraction.

## Inputs and their evidence classes (Block 4.2)

| Input | Value | Class | Source |
|---|---|---|---|
| Half-spread + slippage per tier/size | table above | **REAL_PUBLIC_RETAIL** (MEASURED) | 57 live books, receipts + manifest hash above |
| Bybit spot taker fee | 10 bps | **ASSUMPTION** | official fee page is bot-walled (HTTP 403) from this environment; base non-VIP rate from vendor docs, errs high vs discounts |
| Bybit spot maker fee | 10 bps | **ASSUMPTION** | same; maker fills additionally carry unmodelled non-fill risk |
| Cost-drag budget (below) | 200/500/1000 bps/yr | **ASSUMPTION** | declared decision parameter; there is no measured "right" value |

NOT_MEASURED, declared (`NOT_MEASURED_COMPONENTS` in code): historical
spread/depth series (this is one live cross-section; the assumption that
today's cost structure resembles the past is itself an ASSUMPTION),
intraday spread variation, perp funding, withdrawal/on-ramp costs, impact
beyond the visible book, maker fill probability.

## Maximum viable turnover (Block 4.3)

Convention: turnover 1.0 = one full round trip of the whole portfolio;
annual cost drag = turnover × round-trip cost. Round-trip cost = 2 × taker
fee + measured execution cost. Max viable annual turnover = budget / RT cost
(`max_viable_annual_turnover`). For reference, the ETF gate (total 3.0 over
the 5.75y window) is ≈ **0.52×/yr**, and the killed strategies ran 4–8.7×/yr
against costs an order of magnitude smaller.

Max annual turnover at cost budget B (bps/yr), p50 costs [p75]:

| Tier, order size | RT cost bps | B=200 | B=500 | B=1000 |
|---|---|---|---|---|
| mid $1k | 34.8 [43.7] | 5.7 [4.6] | 14.4 [11.4] | 28.7 [22.9] |
| mid $10k | 63.9 [77.9] | 3.1 [2.6] | 7.8 [6.4] | 15.6 [12.8] |
| low $1k | 43.3 [45.4] | 4.6 [4.4] | 11.5 [11.0] | 23.1 [22.0] |
| low $5k | 72.5 [88.6] | 2.8 [2.3] | 6.9 [5.6] | 13.8 [11.3] |
| low $10k | 108.2 [162.3] | 1.8 [1.2] | 4.6 [3.1] | 9.2 [6.2] |
| micro $1k | 79.5 [144.6] | 2.5 [1.4] | 6.3 [3.5] | 12.6 [6.9] |
| micro $5k | 249.0 [393.5] | 0.8 [0.5] | 2.0 [1.3] | 4.0 [2.5] |

**The headline numbers.** At a declared 500 bps/yr drag budget, p75 costs,
small-capital order sizes:

- **Weekly full rotation (52×/yr) is not viable anywhere** — not even mega
  clears it (max ≈ 23×/yr at B=500).
- **Monthly full rotation (12×/yr)** is viable in **mid at ≤$1k orders**
  (11.4) and **borderline in low at ≤$1k** (11.0); dead at $5k+ and dead in
  micro.
- **Low tier at realistic $5–10k orders supports ≈3–6×/yr**; **micro at $5k
  supports ≈1–2×/yr** — quarterly-to-annual rebalancing territory.
- The ETF-equivalent gate (≈0.5×/yr) is clearable everywhere; the binding
  constraint here is not the old gate but the sheer cost level: any future
  strategy in low/micro must be designed around **single-digit annual
  turnover**, or its edge must exceed hundreds of bps per round trip.

Capacity note, same measurement: 8% of low-tier and 25% of micro books could
not fill a $10k market order at any price on visible depth. Position sizing
in micro is capacity-constrained before it is cost-constrained.

## Reproduction

```bash
python - <<'PY'
from quant_trade.costs.measure import run_cost_measurement
result = run_cost_measurement(
    "data/cache/crypto_costs/<today>", snapshot_date="<yesterday>",
    symbols_per_tier=12, sleep_seconds=0.15)
print(result.status, result.manifest_sha256)
PY
```

A blocked network records `NOT_RUN_NETWORK_BLOCKED` with the verbatim error
and fabricates nothing. Tests are fixture-driven and never touch the network.
