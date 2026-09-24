# Crypto funding carry on real data — results (H1-BIN, H1-BIN-R)

Research backtest only. No order was placed, no key was used, no venue was
connected to anything but its public data archive. Nothing here authorises
real money (`real_money_approved=false` in every artifact).

**Verdict: both registered campaigns are `MEASURED_REJECTED`.** On six years
and eight months of Binance BTC data, the delta-neutral funding carry earned
roughly nothing out of sample after costs, lost money at 2× costs, did not
enter at all during the sealed holdout, and trailed both holding cash and
holding BTC over the walk-forward period.

Machine-readable results: `artifacts/v9/H1_BIN_CARRY_RESULTS.json`,
`artifacts/v9/H1_BIN_R_CARRY_RESULTS.json`. Registrations:
`src/quant_trade/v9/binance_carry_registration.py`.

## Why Binance and not the pre-registered venues

| Venue | What happened (2026-09-24) |
|---|---|
| Bybit (H1) | `api.bybit.com` answers 403 from CloudFront: "configured to block access from your country". The research host is in the US. |
| OKX (H2) | Reachable, but the REST funding history only covers about three months: 212 settlements over 70 days. `quant-trade v8 campaign --hypothesis H2` → `NOT_RUN_INSUFFICIENT_REAL_DATA` (needs 1,000 settlements and 730 days). |
| Binance REST | HTTP 451, restricted location. |
| Binance archive | `data.binance.vision`, published by the venue, reachable. Monthly and daily ZIP files with a SHA-256 `.CHECKSUM` beside each; every file was checked against it. |

Running H1's strategy on Binance is a different experiment, so it was
registered as **H1-BIN** before any panel was built (commit `7e72fce`). Its
strategy, four variants, gates and cost stack are H1's; its split procedure
is V9's (per-window out-of-sample selection, sealed holdout).

## Data

- BTCUSDT spot, USD-M perpetual, mark price, index price: hourly, 2020-01-01
  to 2026-08-31, plus 7,305 settled funding events (every 8h, none missing).
- 58,409 panel hours. The monthly archive omits some whole days of mark and
  index bars that the daily archive has; those were read from the daily
  files. 31 spot hours exist in neither file (exchange maintenance, e.g.
  2020-02-19 and 2023-03-24). They are recorded in `venue_outages.json` and
  get no row: nothing is forward-filled. One spot bar (2020-12-21 13:00)
  differs between the monthly and daily files; the monthly bar is kept and the
  conflict is recorded.
- The panel is rebuilt byte-for-byte from the archived raw files before it
  is used, and every declared outage is checked to be truly absent and backed
  by a daily-file receipt.

Funding context (settled rate, simple annualisation of the 8h mean):

| Year | Mean per 8h | ≈ per year | Share of settlements > 0.01% | Share negative |
|---|---|---|---|---|
| 2020 | 0.0157% | 17.2% | 27% | 14% |
| 2021 | 0.0280% | 30.6% | 43% | 7% |
| 2022 | 0.0038% | 4.2% | 0% | 22% |
| 2023 | 0.0072% | 7.9% | 6% | 10% |
| 2024 | 0.0109% | 11.9% | 19% | 8% |
| 2025 | 0.0047% | 5.1% | 0% | 13% |
| 2026 (to Aug) | 0.0024% | 2.6% | 0% | 29% |

Funding was rich in 2020–2021 and has been thin since 2025.

## Procedure

- Long spot, short perp (3× on the perp margin), entered when the trailing
  mean of the last 3 or 6 settled rates exceeds 0.005% or 0.01% per 8h.
- Conservative retail cost stack (`conservative_cost_stack('binance')`):
  taker fees on every fill (spot 0.10%, perp 0.05%), spread, slippage, impact,
  a 4%/yr opportunity cost on the capital in the position, conversion and
  unwind reserves. Also run at 2× and 3×. These are assumptions, not captured
  fees, so no result here can promote (`cost_evidence_promotable` fails by
  design).
- Split 50/30/20 in time. Walk-forward over the middle 30% (2023-05-03 →
  2025-05-02): 73 windows of 240 hours; each window picks a variant using only
  earlier data (minus a 7-hour purge/embargo). Holdout: the last 20%
  (2025-05-02 → 2026-08-31), sealed until the final variant was frozen,
  revealed once.
- All eight variants are in the hash-chained trial ledger
  (`data/v9_evidence/trials.jsonl`), so the deflated Sharpe counts them all.

## H1-BIN (as registered): rejected

Every variant stopped with "position losses exhausted cash and posted
margin", and at 2×/3× costs some with "entry sizing consumed more cash than
available". The short perp pays variation margin in cash while BTC rises; the
ledger never moves the spot leg's gains into the margin account, so a long
rally drains the margin. That triggers the registered falsifier "any
liquidation or maintenance-margin breach". No return figure exists for H1-BIN.

## H1-BIN-R (margin re-hedging): rejected

Registered after H1-BIN failed and before it ran (commit `b145270`). Only two
mechanics change: when posted margin falls below half its entry level the
hedge is closed and reopened at current prices, paying all four fills again;
entries are sized from current equity. Everything else is H1-BIN's.

Out of sample:

| Period | Carry 1× costs | Carry 2× | Carry 3× | Hold BTC | Hold cash (4%/yr) |
|---|---|---|---|---|---|
| Walk-forward, 2023-05 → 2025-05 | +0.41% | −5.78% | −11.57% | +239.3% | +8.15% |
| Holdout, 2025-05 → 2026-08 | 0.00% | 0.00% | 0.00% | −19.1% | +5.37% |

- Walk-forward: the selector picked the same variant (threshold 0.01%,
  window 6) in all 73 windows; 7 windows were positive, most were flat.
  Annualised +0.21% at 1× costs.
- Holdout: the frozen variant never entered. The trailing funding mean never
  cleared 0.01% per 8h after May 2025, so the strategy sat in cash earning
  nothing in this model. It lost less than BTC (0% vs −19%) only because it
  held nothing; it did not beat cash. PSR 0.00, deflated Sharpe 0.00.

Failed gates: holdout not positive (1× and 2×), bootstrap P05 not positive,
PSR and DSR below 0.95, walk-forward majority not positive, does not beat
cash on the holdout, cost evidence assumed.

Full sample, **in-sample** (the variant was chosen on this data, so this is
context only):

| Variant | Total 2020-01 → 2026-08 | Per year | Max drawdown | Time in position | Entries (re-hedges) |
|---|---|---|---|---|---|
| t0.01%, w6 (selected) | +13.4% | +1.9% | −2.6% | 20% | 54 (7) |
| t0.01%, w3 | +0.8% | +0.1% | −9.6% | 18% | 79 (6) |
| t0.005%, w6 | −30.9% | −5.4% | −41.6% | 62% | 190 (18) |
| t0.005%, w3 | −63.8% | −14.1% | −68.0% | 63% | 343 (18) |
| Hold BTC | +992% | +43.2% | −77.2% | — | — |

Calendar years for the selected variant vs BTC: 2020 +2.0% vs +302%; 2021
+11.9% vs +59%; 2022 0.0% vs −64%; 2023 −1.1% vs +155%; 2024 +0.5% vs +121%;
2025 0.0% vs −6.5%; 2026 to Aug 0.0% vs −10.5%. Almost all of the carry's
gain came from 2021.

## What this does and does not show

- The lower threshold loses money because it trades often: fees and the
  capital charge eat the funding. The higher threshold is barely positive and
  only when funding was exceptional.
- The model is conservative in three ways that a real desk could improve:
  retail taker fees on every fill, a 4%/yr opportunity cost on capital in the
  position (so comparing to 4% cash counts that cost twice while invested),
  and zero yield on idle capital. Adding 4% on idle cash would roughly turn
  the carry into "cash plus a little in 2021"; it would still not approach
  holding BTC in rising years, and a supervised trial would need captured fee
  schedules first.
- Not tested: other coins, other venues' funding (Bybit is unreachable from
  here, OKX keeps only three months), maker execution, VIP fees, or a
  cross-venue spread (H3 needs two venues).
- Liquidation is modelled as exhausting cash plus posted margin; exchange
  maintenance-margin tiers and auto-deleveraging are not.

## Reproduce

```bash
quant-trade v8 evidence-backfill --venue binance --symbol BTC \
  --since 2020-01-01T00:00:00Z --until 2026-08-31T23:00:00Z
quant-trade v9 h1-bin-run --hypothesis H1-BIN-R
```

The raw archive, series and panel stay git-ignored; receipts, attempt logs,
the outage record and results are committed. In the trial ledger, a rerun
with byte-identical code, config and data is logged as a reproduction; any
other rerun counts as new trials.
