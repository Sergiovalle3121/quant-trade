# Mining Economics V2

Research-only. This software decides whether an ASIC *should be a candidate to
operate*; it never mines a hash or controls hardware
(`MINING_HARDWARE_CONTROL: DISABLED`).

## The defect this fixes

V1 discounted a **single constant daily cash flow** over the whole horizon
(`_present_value` in `mining/profitability.py`) even though the policy carried a
non-zero `monthly_difficulty_growth_rate`. Difficulty growth only touched the
one-shot stress figure, never the NPV. A multi-year NPV was therefore
overstated.

`mining/cashflow.py` replaces this with an explicit per-day projection.

### Illustrative comparison (S21-like, 200 TH/s, 3.5 kW, $0.06/kWh)

3% monthly difficulty growth, a halving mid-horizon, 3-year window:

| Method | NPV |
| --- | --- |
| **Dynamic per-period (V2)** | **−$5,029** |
| Constant daily flow (V1 method) | −$1,068 |
| **Overstatement removed** | **$3,961** |

Production cost ≈ **$65,745/coin** against a $60,000 price, IRR undefined, no
discounted payback — an honest **NO-GO**. The constant-flow method hid roughly
$4k of the loss on this single rig.

## What the projection models per period

- Difficulty growth path (monthly → daily), so your network share shrinks over time.
- Scheduled halvings (subsidy halves; **transaction fees do not halve**).
- Price drift or scenario multipliers (no forecast is mandatory).
- Uptime degradation, hashrate/efficiency degradation, energy inflation.
- Repair/replacement CAPEX on the day it lands.
- Pool fee and configurable simplified tax; residual value at horizon.

Outputs: daily and monthly cash-flow series, **cash vs accounting profit**, NPV,
IRR (bisection over the varying series), discounted payback, production cost, and
break-even electricity / coin price. `constant_flow_npv_usd` and
`npv_overstatement_vs_constant` are reported so the V1 bias is always visible.

## Two independent revenue methods (`mining/market.py`)

- **Direct hashprice** — a provider's published USD/TH/day quote.
- **Bottom-up** — rebuilt from `block_subsidy + tx_fee_revenue`, blocks/day,
  network hashrate, and coin price.

`compare_hashprice` flags divergence beyond a threshold as a data-quality alert
rather than silently averaging. Snapshots are attributable (`source_name`,
`source_url`, `captured_at_utc`) and **fail closed when stale** (`require_fresh`).
Live access, if ever added, sits behind a read-only adapter with a timeout,
bounded retries, and attribution; fixtures carry no keys and tests never touch
the network.

## Electricity tariffs (`mining/tariffs.py`)

Flat, time-of-use (peak/off-peak), demand charges, taxes/surcharges, PUE,
curtailment, all-inclusive hosting, and a max-contracted-demand guard. No tariff
is hardcoded as universal: `cfe_receipt_template()` lists the fields to
transcribe from a real CFE bill into a per-site config.

## Pool economics (`mining/pool.py`)

PPS (subsidy only), FPPS and PPS+ (subsidy + tx fees), and PPLNS (proportional,
variance-flagged) are modelled separately, each with pool fee, stale/reject rate,
payout threshold, and an operator-supplied counterparty-risk score — so "which
pool" is never an invisible assumption.

## Verdict

`MINING_ECONOMICS: NO-GO` for the example rig at these inputs, and
`NEEDS-INPUT` in general: a real GO requires a real, attributable, fresh market
snapshot, a real per-site tariff, and a real pool contract. The machinery is
here; the honest numbers are not favourable, and none were invented.
